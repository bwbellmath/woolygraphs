#!/usr/bin/env python
"""Helical spiral layout for a circular hat chart.

Reads a chart CSV (see chart.py: one line per round, cast-on first,
cells ``f`` / ``b`` / ``f-k2tog`` / blank), tiles one pattern repeat
horizontally, and places every live stitch on a continuous helix:
stitch i of a count-N round sits at fractional turn round + i/N, so the
fabric is one unbroken spiral of yarn rather than a stack of closed
rings. The cross-section radius of each round is the circle whose
chord between neighbouring stitches is exactly 1/horizontal_gauge.

The cast-on round is the anchor: the first turn of the same helix (a
circular arc rising one round height, from z=0 to just under
1/vertical_gauge) with gauge-exact stitch spacing, flagged
``anchor_flag`` so the optimizer holds it there; everything above hangs
from it.

``build_bundle`` is the single entry point (used by the server on every
edit); the CLI just writes the bundle to JSON for the static viewer.
"""

import argparse
import json
import math
import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart import DEFAULT_HORIZONTAL_GAUGE, DEFAULT_VERTICAL_GAUGE, Chart, nearest_slot  # noqa: E402


def ring_radius(count, horizontal_gauge):
    """Radius of the circle on which ``count`` stitches sit with a
    chord of exactly 1/horizontal_gauge between neighbours."""
    if count < 2:
        return 0.0
    return (1.0 / horizontal_gauge) / (2.0 * math.sin(math.pi / count))


def build_layout(rounds, horizontal_gauge, vertical_gauge, chart_width,
                 device="cpu"):
    n_slots = max(max(rd.live) for rd in rounds if rd.live) + 1

    index_of = {}
    positions = []
    colors = []
    ops = []
    round_index = []
    decrease_flag = []
    increase_flag = []
    anchor_flag = []
    synthesized = []
    stitch_counts = []
    stitch_slot = []
    chart_cell = []
    n = 0
    for r, rd in enumerate(rounds):
        count = rd.count
        stitch_counts.append(count)
        radius = ring_radius(count, horizontal_gauge)
        for i, s in enumerate(rd.live):
            cell = rd.cells[s]
            index_of[(r, s)] = n
            stitch_slot.append(s)
            # One helix from the first cast-on stitch, so round 0 rises a
            # round height like every other and meets round 1 at the seam.
            turn = r + i / count
            theta = 2.0 * math.pi * turn
            z = turn / vertical_gauge
            positions.append((radius * math.cos(theta),
                              radius * math.sin(theta), z))
            colors.append(cell.color)
            ops.append(list(cell.ops))
            round_index.append(r)
            decrease_flag.append(cell.is_decrease)
            increase_flag.append(cell.is_increase or s in rd.newly_cast)
            anchor_flag.append(r == 0)
            synthesized.append(rd.synthesized)
            # The sheet cell, so every vertical repeat maps back to it.
            chart_cell.append([rd.sheet_row, s % chart_width])
            n += 1
    live_slots = [rd.live for rd in rounds]

    # Yarn path: one continuous strand through every stitch in knit order.
    yarn_edges = [[i, i + 1] for i in range(n - 1)]

    # Column edges: each stitch hangs from the stitch it is worked into
    # (Round.below: the nearest live stitch one round below, or the same
    # stitch counted after collapsing the blanks when a round only moves
    # its gaps; cast-ons have none); consumed slots additionally feed up
    # into the decrease they were worked into (Round.merged_into), so a
    # cdd has three parents -- left, centre, right -- and every stitch is
    # bound upward.
    column_edges = []
    for r in range(1, len(rounds)):
        for s in live_slots[r]:
            if s in rounds[r].below:
                below = rounds[r].below[s]
                column_edges.append([index_of[(r - 1, below)],
                                     index_of[(r, s)]])
        for s, above in rounds[r].merged_into.items():
            column_edges.append([index_of[(r - 1, s)],
                                 index_of[(r, above)]])

    # Neighbor graph for the smoothing optimizer: for every stitch its
    # [left, right, down, up] global indices (-1 where missing).
    # Left/right wrap within the round's ring; down/up follow the column
    # edges, falling through to the nearest live slot (for a cast-on, or
    # a stitch with nothing worked into it).
    above_of = [{b: s for s, b in rd.below.items()} for rd in rounds]
    neighbors = []
    for v in range(n):
        r, s = round_index[v], stitch_slot[v]
        slots = live_slots[r]
        i = slots.index(s)
        left = index_of[(r, slots[i - 1])]
        right = index_of[(r, slots[(i + 1) % len(slots)])]
        down = up = -1
        if r > 0:
            below = rounds[r].below.get(s)
            if below is None:
                below = nearest_slot(live_slots[r - 1], s, n_slots)
            down = index_of[(r - 1, below)]
        if r + 1 < len(rounds):
            nxt = rounds[r + 1]
            above = nxt.merged_into.get(s, above_of[r + 1].get(s))
            if above is None:
                above = nearest_slot(live_slots[r + 1], s, n_slots)
            up = index_of[(r + 1, above)]
        neighbors.append([left, right, down, up])

    # Leaf tensor with gradients enabled, ready for the layout optimizer.
    pos = torch.tensor(positions, dtype=torch.float32,
                       device=device).requires_grad_(True)

    return pos, {
        "neighbors": neighbors,
        "colors": colors,
        "ops": ops,
        "round_index": round_index,
        "decrease_flag": decrease_flag,
        "increase_flag": increase_flag,
        "anchor_flag": anchor_flag,
        "synthesized": synthesized,
        "stitch_counts": stitch_counts,
        "chart_cell": chart_cell,
        "round_sheet_row": [rd.sheet_row for rd in rounds],
        "stitch_slot": stitch_slot,   # slot in the tiled round, for remapping
        "yarn_edges": yarn_edges,
        "column_edges": column_edges,
    }


def build_bundle(chart, repeats=4, horizontal_gauge=DEFAULT_HORIZONTAL_GAUGE,
                 vertical_gauge=DEFAULT_VERTICAL_GAUGE,
                 extend_crown=False):
    """Compile a Chart into the JSON-serialisable viewer bundle."""
    rounds = chart.rounds(repeats, extend_crown=extend_crown)
    pos, meta = build_layout(rounds, horizontal_gauge, vertical_gauge,
                             chart_width=chart.width)
    first_dec = next((r for r, rd in enumerate(rounds)
                      if any(c.is_decrease for c in rd.cells.values())),
                     len(rounds))
    return {
        "name": chart.name,
        "horizontal_gauge": horizontal_gauge,
        "vertical_gauge": vertical_gauge,
        "repeats": repeats,
        "chart_width": chart.width,
        "chart_height": chart.height,
        "n_stitches": pos.shape[0],
        "n_rounds": len(rounds),
        "n_chart_rounds": sum(not rd.synthesized for rd in rounds),
        "crown_start_round": first_dec,
        # sheet row (0-based) of the first decrease round, i.e. the
        # default 1-based shaping row
        "crown_start_row": (rounds[first_dec].sheet_row
                            if first_dec < len(rounds) else chart.height),
        "vertical_repeat": chart._vertical_repeat_json(),
        "shaping_row": chart.shaping_row,   # 1-based sheet row, or None
        "positions": [[round(v, 5) for v in p] for p in pos.detach().tolist()],
        **meta,
    }


def describe(bundle):
    counts = bundle["stitch_counts"]
    n_synth = bundle["n_rounds"] - bundle["n_chart_rounds"]
    return (f"{bundle['name']}: {bundle['n_stitches']} stitches over "
            f"{bundle['n_rounds']} rounds ({counts[0]} -> {counts[-1]}), "
            f"{sum(bundle['increase_flag'])} cast-ons, "
            f"{sum(bundle['decrease_flag'])} decreases, crown starts round "
            f"{bundle['crown_start_round']}, {n_synth} synthesized rounds")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("chart_csv")
    ap.add_argument("output_json")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--horizontal-gauge", type=float,
                    default=DEFAULT_HORIZONTAL_GAUGE,
                    help="stitches per inch")
    ap.add_argument("--vertical-gauge", type=float,
                    default=DEFAULT_VERTICAL_GAUGE,
                    help="rounds per inch")
    ap.add_argument("--extend-crown", action="store_true",
                    help="if the chart does not close the crown, keep "
                         "decreasing past its last round until closed")
    args = ap.parse_args()

    chart = Chart.read_csv(args.chart_csv)
    for r, c, msg in chart.errors():
        print(f"warning: row {r} col {c}: {msg} (treated as blank)",
              file=sys.stderr)
    bundle = build_bundle(chart, args.repeats, args.horizontal_gauge,
                          args.vertical_gauge, args.extend_crown)
    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(bundle, f)
    print(f"{describe(bundle)} -> {args.output_json}")


if __name__ == "__main__":
    main()
