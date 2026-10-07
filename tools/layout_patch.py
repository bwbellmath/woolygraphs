"""Carry a layout across a structural chart edit with a minimal local change.

When an edit adds or removes stitches (a cell blanked for a k2tog, a
stray character, an inserted round or column), the stitch graph changes
and the old positions no longer line up one-to-one with the new bundle.
Rather than starting over from the helix, ``patch_positions``:

1. matches every stitch of the new chart to the same stitch of the old
   one -- same (round, slot), after aligning inserted / deleted rows and
   columns -- and keeps its position;
2. places each new stitch between the stitches around it: a run of k new
   stitches in a round between known stitches a and b is spread evenly
   along the ring from a to b (one new stitch lands half way, at half the
   usual spacing from each); a new stitch with no known neighbour in its
   round is placed between the nearest known stitches below and above it
   in its column (or one gauge step past the last one when only one side
   is known).

Removed stitches are simply dropped, so adding a stitch and deleting it
again leaves every other stitch where it was.
"""

import math
from difflib import SequenceMatcher


def align(old, new):
    """{old index: new index} for items that survive between two
    sequences (rows, or columns as tuples). Equal blocks match; a
    replaced block of the same length matches one-to-one (edited rows);
    inserts and deletes match nothing."""
    if len(old) == len(new):
        return {i: i for i in range(len(old))}
    out = {}
    sm = SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            out.update({i1 + k: j1 + k for k in range(i2 - i1)})
    return out


def _columns(rows, width):
    return [tuple(r[c] if c < len(r) else "" for r in rows)
            for c in range(width)]


def stitch_map(old_bundle, old_rows, new_bundle, new_rows):
    """{old stitch index: new stitch index} for stitches in both."""
    if old_bundle["repeats"] != new_bundle["repeats"]:
        return {}
    ho, hn = len(old_rows), len(new_rows)
    wo, wn = old_bundle["chart_width"], new_bundle["chart_width"]
    if ho != hn and wo != wn:
        # Rows and columns both changed in one edit: no reliable diff,
        # keep whatever still sits at the same sheet coordinates.
        rmap = {r: r for r in range(min(ho, hn))}
        cmap = {c: c for c in range(min(wo, wn))}
    else:
        rmap = align([tuple(r) for r in old_rows], [tuple(r) for r in new_rows])
        cmap = align(_columns(old_rows, wo), _columns(new_rows, wn))
    new_index = {(r, s): j for j, (r, s) in enumerate(
        zip(new_bundle["round_index"], new_bundle["stitch_slot"]))}
    out = {}
    for i, (r, s) in enumerate(zip(old_bundle["round_index"],
                                   old_bundle["stitch_slot"])):
        rep, c = divmod(s, wo)
        # Synthesized crown rounds sit past the chart; keep their offset.
        nr = rmap.get(r) if r < ho else r - ho + hn
        nc = cmap.get(c)
        if nr is None or nc is None:
            continue
        j = new_index.get((nr, rep * wn + nc))
        if j is not None:
            out[i] = j
    return out


def _ring_interp(a, b, t, full_turn):
    """Point a fraction t of the way from a to b, going forward
    (counter-clockwise, the knitting direction) around the hat's z axis:
    angle, radius and height interpolated. full_turn: a and b are the
    same stitch, so the path is once round the ring."""
    ta, tb = math.atan2(a[1], a[0]), math.atan2(b[1], b[0])
    dt = (tb - ta) % (2 * math.pi)
    if full_turn:
        dt = 2 * math.pi
    elif dt > math.pi:
        # Backwards (the ring folded over, or a stitch near the axis):
        # the angle means nothing here, take the straight chord.
        return [a[k] + (b[k] - a[k]) * t for k in range(3)]
    ra, rb = math.hypot(a[0], a[1]), math.hypot(b[0], b[1])
    th, rad = ta + dt * t, ra + (rb - ra) * t
    return [rad * math.cos(th), rad * math.sin(th), a[2] + (b[2] - a[2]) * t]


def fill_new(bundle, pos):
    """Place every None in pos (positions of the new bundle) from its
    known neighbours; returns False if some stitch could not be placed."""
    rounds = {}
    for i, r in enumerate(bundle["round_index"]):
        rounds.setdefault(r, []).append(i)   # ring (knit) order
    nbr = bundle["neighbors"]

    # 1. Runs of new stitches between known stitches of the same round.
    for ring in rounds.values():
        known = [k for k, i in enumerate(ring) if pos[i] is not None]
        if not known or len(known) == len(ring):
            continue
        n = len(ring)
        for a, b in zip(known, known[1:] + [known[0] + n]):
            run = b - a - 1
            if not run:
                continue
            pa, pb = pos[ring[a]], pos[ring[b % n]]
            for k in range(1, run + 1):
                pos[ring[(a + k) % n]] = _ring_interp(
                    pa, pb, k / (run + 1), full_turn=len(known) == 1)

    # 2. Whole new rounds: between the known stitches below and above.
    vstep = 1.0 / bundle["vertical_gauge"]

    def walk(i, d):
        """(first known stitch from i along direction d, steps) or None."""
        steps = 0
        while True:
            i = nbr[i][d]
            steps += 1
            if i < 0 or steps > len(pos):
                return None
            if pos[i] is not None:
                return i, steps

    def beyond(i, d, steps):
        """Extrapolate `steps` gauge steps past known stitch i, away
        from its own neighbour in direction d (or straight up/down)."""
        p, q = pos[i], nbr[i][d]
        if q >= 0 and pos[q] is not None:
            v = [p[k] - pos[q][k] for k in range(3)]
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            v = [x / norm for x in v]
        else:
            v = [0.0, 0.0, 1.0 if d == 2 else -1.0]
        return [p[k] + v[k] * vstep * steps for k in range(3)]

    placed = {}
    for i, p in enumerate(pos):
        if p is not None:
            continue
        down, up = walk(i, 2), walk(i, 3)
        if down and up:
            (di, a), (ui, b) = down, up
            t = a / (a + b)
            placed[i] = [pos[di][k] + (pos[ui][k] - pos[di][k]) * t
                         for k in range(3)]
        elif down:
            placed[i] = beyond(down[0], 2, down[1])
        elif up:
            placed[i] = beyond(up[0], 3, up[1])
    for i, p in placed.items():
        pos[i] = p
    return all(p is not None for p in pos)


def patch_positions(old_bundle, old_rows, old_positions,
                    new_bundle, new_rows):
    """Positions for new_bundle that keep old_positions wherever the
    stitch survived the edit, or None when too little survived (a
    repeat-count change, or no stitch in common)."""
    m = stitch_map(old_bundle, old_rows, new_bundle, new_rows)
    if not m:
        return None
    pos = [None] * new_bundle["n_stitches"]
    for i, j in m.items():
        pos[j] = list(old_positions[i])
    if not fill_new(new_bundle, pos):
        return None
    return [[round(v, 5) for v in p] for p in pos]
