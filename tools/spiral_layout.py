#!/usr/bin/env python
"""Helical spiral layout for a circular double-knitting chart.

Reads a chart CSV in knit order (one line per round, cast-on first;
symbols B/W for the two colors, O for slots not yet cast on, D for slots
already killed by a decrease), tiles one pattern repeat horizontally,
and places every live stitch on a continuous helix: stitch i of a
count-N round sits at fractional turn round + i/N, so the fabric is one
unbroken spiral of yarn rather than a stack of closed rings. The
cross-section radius of each round is implied by its live stitch count
at the horizontal gauge, so the brim cast-ons flare outward and the
crown decreases spiral closed.

Outputs a JSON bundle for the web viewer: positions (inches), per-stitch
color / round / shaping flags, the yarn path, and inter-round edges.
The position tensor is built with torch and is the same N x 3 leaf
tensor a later edge-length / planarity optimizer would consume.
"""

import argparse
import csv
import json
import math
import os

import torch

LIVE = ("B", "W")


def read_chart(path, repeats):
    with open(path, newline="") as f:
        rows = [[s.strip() for s in row] * repeats for row in csv.reader(f) if row]
    width = len(rows[0])
    for i, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"round {i} has {len(row)} cells, expected {width}")
    return rows


def resolve_rounds(rows, extend_crown=False, wedges=8):
    """Per-round live slots, colors, and shaping events.

    D marks are cumulative in the chart (a killed column stays marked to
    the crown), but a dead-set keeps slots dead even if a chart re-colors
    one. newly_dead / newly_cast record the round each event happens.
    With extend_crown, decrease diagonals keep consuming their nearest
    live neighbor past the end of the chart until <= wedges remain.
    """
    n_slots = len(rows[0])
    dead = set()
    rounds = []  # (live_slots, colors_by_slot, newly_dead, newly_cast)
    for r, row in enumerate(rows):
        newly_dead = [s for s, sym in enumerate(row)
                      if sym == "D" and s not in dead]
        dead.update(newly_dead)
        live = [s for s in range(n_slots)
                if s not in dead and row[s] in LIVE]
        col = {s: (1 if row[s] == "B" else 0) for s in live}
        newly_cast = [s for s in live if r > 0 and rows[r - 1][s] == "O"]
        rounds.append((live, col, newly_dead, newly_cast))

    if not rounds[0][0]:
        raise ValueError("first round has no live stitches; "
                         "is the chart upside-down?")

    last_dec = next((r for r in reversed(rounds) if r[2]), None)
    if extend_crown and last_dec is not None:
        frontier = list(last_dec[2])[:wedges]
        while len(rounds[-1][0]) - len(frontier) >= wedges:
            prev_live, prev_col, _, _ = rounds[-1]
            newly_dead = []
            live = list(prev_live)
            for s in frontier:
                victim = min(live, key=lambda c: min((c - s) % n_slots,
                                                     (s - c) % n_slots))
                live.remove(victim)
                newly_dead.append(victim)
            dead.update(newly_dead)
            col = {s: prev_col[s] for s in live}
            rounds.append((live, col, newly_dead, []))
            frontier = newly_dead
    return rounds


def build_layout(rounds, horizontal_gauge, vertical_gauge,
                 n_chart_rounds, device="cpu"):
    n_slots = max(max(r[0]) for r in rounds if r[0]) + 1

    def nearest_slot(slots, s):
        return min(slots, key=lambda c: min((c - s) % n_slots,
                                            (s - c) % n_slots))

    index_of = {}
    positions = []
    colors = []
    round_index = []
    decrease_flag = []
    increase_flag = []
    synthesized = []
    stitch_counts = []
    stitch_slot = []
    n = 0
    for r, (slots, col, newly_dead, newly_cast) in enumerate(rounds):
        count = len(slots)
        stitch_counts.append(count)
        # The k2tog for each newly dead slot is its nearest survivor.
        k2togs = {nearest_slot(slots, s) for s in newly_dead}
        cast_ons = set(newly_cast)
        for i, s in enumerate(slots):
            index_of[(r, s)] = n
            stitch_slot.append(s)
            turn = r + i / count
            theta = 2.0 * math.pi * turn
            radius = (count / horizontal_gauge) / (2.0 * math.pi)
            positions.append((radius * math.cos(theta),
                              radius * math.sin(theta),
                              turn / vertical_gauge))
            colors.append(col[s])
            round_index.append(r)
            decrease_flag.append(s in k2togs)
            increase_flag.append(s in cast_ons)
            synthesized.append(r >= n_chart_rounds)
            n += 1
    live_slots = [r[0] for r in rounds]

    # Yarn path: one continuous strand through every stitch in knit order.
    yarn_edges = [[i, i + 1] for i in range(n - 1)]

    # Column edges: each stitch hangs from the nearest live stitch one
    # round below (skipped for freshly cast-on slots, which have no
    # parent); decreased slots additionally feed up into their k2tog so
    # every stitch is bound upward.
    column_edges = []
    for r in range(1, len(rounds)):
        _, _, _, newly_cast = rounds[r]
        cast_ons = set(newly_cast)
        for s in live_slots[r]:
            if s in cast_ons:
                continue
            below = nearest_slot(live_slots[r - 1], s)
            column_edges.append([index_of[(r - 1, below)], index_of[(r, s)]])
        for s in live_slots[r - 1]:
            if (r, s) not in index_of:
                above = nearest_slot(live_slots[r], s)
                column_edges.append([index_of[(r - 1, s)],
                                     index_of[(r, above)]])

    # Neighbor graph for the smoothing optimizer: for every stitch its
    # [left, right, down, up] global indices (-1 where missing).
    # Left/right wrap within the round's ring; down/up follow the column,
    # falling through to the nearest live slot across shaping rounds.
    neighbors = []
    for v in range(n):
        r, s = round_index[v], stitch_slot[v]
        slots = live_slots[r]
        i = slots.index(s)
        left = index_of[(r, slots[i - 1])]
        right = index_of[(r, slots[(i + 1) % len(slots)])]
        down = up = -1
        if r > 0:
            down = index_of[(r - 1, nearest_slot(live_slots[r - 1], s))]
        if r + 1 < len(rounds):
            up = index_of[(r + 1, nearest_slot(live_slots[r + 1], s))]
        neighbors.append([left, right, down, up])

    # Leaf tensor with gradients enabled, ready for the layout optimizer.
    pos = torch.tensor(positions, dtype=torch.float32,
                       device=device).requires_grad_(True)

    return pos, {
        "neighbors": neighbors,
        "colors": colors,
        "round_index": round_index,
        "decrease_flag": decrease_flag,
        "increase_flag": increase_flag,
        "synthesized": synthesized,
        "stitch_counts": stitch_counts,
        "yarn_edges": yarn_edges,
        "column_edges": column_edges,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("chart_csv")
    ap.add_argument("output_json")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--horizontal-gauge", type=float, default=8.0,
                    help="stitches per inch")
    ap.add_argument("--vertical-gauge", type=float, default=12.0,
                    help="rounds per inch")
    ap.add_argument("--extend-crown", action="store_true",
                    help="if the chart does not close the crown, keep "
                         "decreasing past its last round until closed")
    args = ap.parse_args()

    rows = read_chart(args.chart_csv, args.repeats)
    rounds = resolve_rounds(rows, extend_crown=args.extend_crown)
    pos, meta = build_layout(rounds, args.horizontal_gauge,
                             args.vertical_gauge, n_chart_rounds=len(rows))

    counts = meta["stitch_counts"]
    first_dec = next((r for r, rd in enumerate(rounds) if rd[2]), len(rounds))
    bundle = {
        "name": os.path.splitext(os.path.basename(args.chart_csv))[0],
        "horizontal_gauge": args.horizontal_gauge,
        "vertical_gauge": args.vertical_gauge,
        "repeats": args.repeats,
        "n_stitches": pos.shape[0],
        "n_rounds": len(rounds),
        "n_chart_rounds": len(rows),
        "crown_start_round": first_dec,
        "stitch_counts": counts,
        "positions": [[round(v, 5) for v in p] for p in pos.detach().tolist()],
        **meta,
    }
    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(bundle, f)

    n_dec = sum(meta["decrease_flag"])
    n_inc = sum(meta["increase_flag"])
    n_synth = len(rounds) - len(rows)
    print(f"{bundle['name']}: {pos.shape[0]} stitches over {len(rounds)} "
          f"rounds ({counts[0]} -> {counts[-1]}), {n_inc} cast-ons, "
          f"{n_dec} k2togs, crown starts round {first_dec}, "
          f"{n_synth} synthesized rounds -> {args.output_json}")


if __name__ == "__main__":
    main()
