#!/usr/bin/env python
"""Re-carve a chart's crown so its stitch count follows a sphere.

A circular hat closes correctly when the live stitch count of each round
is the circumference of the sphere at that latitude (the math in
patterns/Sphere Hat Decs.xlsx and web/shaping.js):

    R      = N0 / (2*pi*hg)                 sphere radius, N0 = brim sts
    W(r)   = W0 * cos((r - equator) / (vg*R))

so the crown takes (pi/2)*vg*R rounds to close. This tool keeps a
chart's colours and its decrease geometry -- one gore per repeat, dead
slots growing outward from a centre column until a single spine column
survives -- and only re-times *when* each slot dies so the profile
matches W(r).

The equator is chosen so the remaining rounds are exactly the rounds the
sphere needs; rounds below it stay untouched as the brim cylinder. Slots
that the new profile keeps alive but the old chart had killed borrow
their colour from the round below (or the nearest live neighbour).

  reshape_crown.py patterns/alt_cubes.csv --repeats 6 --centre 10 --spine 20
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart import Chart, parse_cell  # noqa: E402


def kill_order(width, centre, spine):
    """Slots in the order the gore consumes them, spine last.

    The wedge opens at ``centre`` and alternates outward, left then
    right, wrapping around the repeat and stopping at ``spine``.
    """
    left, right = centre, (centre + 1) % width
    order = []
    while len(order) < width - 1:
        for s in (left, right):
            if s != spine and s not in order:
                order.append(s)
                if len(order) == width - 1:
                    break
        left = (left - 1) % width
        right = (right + 1) % width
    return order


def sphere_widths(w0, n_rounds, hg, vg, repeats):
    """Live stitches per repeat for each crown round, round 0 = equator."""
    radius = w0 * repeats / hg / (2.0 * math.pi)
    widths = []
    prev = w0
    for i in range(n_rounds):
        u = i / (vg * radius)
        w = w0 * math.cos(u) if u < math.pi / 2 else 0.0
        w = max(1, min(prev, int(round(w))))
        widths.append(w)
        prev = w
    return widths, radius


def colour_for(rows, r, c, width):
    """A colour token for a cell the old chart left blank."""
    for rr in range(r - 1, -1, -1):          # same column, below
        cell = parse_cell(rows[rr][c])
        if cell is not None:
            return cell.text.split("-")[0]
    for d in range(1, width):                 # nearest live neighbour
        for cc in ((c - d) % width, (c + d) % width):
            cell = parse_cell(rows[r][cc])
            if cell is not None:
                return cell.text.split("-")[0]
    return "b"


def reshape(chart, repeats, hg, vg, centre, spine, equator=None):
    rows = [list(r) for r in chart.rows]
    width = chart.width
    w0 = max(sum(1 for t in row if t.strip()) for row in rows)

    radius = w0 * repeats / hg / (2.0 * math.pi)
    needed = int(round(math.pi / 2 * vg * radius))
    if equator is None:
        equator = len(rows) - needed
    if equator < 0:
        raise ValueError(
            f"chart has {len(rows)} rounds but the sphere needs {needed} "
            f"crown rounds at {repeats} repeats; add rounds or use fewer "
            f"repeats")

    widths, radius = sphere_widths(w0, len(rows) - equator, hg, vg, repeats)
    order = kill_order(width, centre, spine)

    dead = set()
    events = []
    for i, w in enumerate(widths):
        r = equator + i
        want_dead = order[:w0 - w] if w0 - w > 0 else []
        newly = [s for s in want_dead if s not in dead]
        dead.update(want_dead)
        live = [c for c in range(width) if c not in dead]

        for c in range(width):
            if c in dead:
                rows[r][c] = ""
            else:
                cell = parse_cell(rows[r][c])
                rows[r][c] = (cell.text.split("-")[0] if cell
                              else colour_for(rows, r, c, width))
        # Each dead slot is worked together with its nearest survivor.
        eaten = {}
        for s in newly:
            k = min(live, key=lambda c: min((c - s) % width, (s - c) % width))
            eaten[k] = eaten.get(k, 0) + 1
        for k, n in eaten.items():
            rows[r][k] += f"-k{n + 1}tog"
        if newly:
            events.append((r, len(live), sorted(s + 1 for s in newly)))

    return Chart(rows, name=chart.name), equator, widths, radius, events


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chart_csv")
    ap.add_argument("-o", "--output", help="default: overwrite the input")
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--horizontal-gauge", type=float, default=8.0)
    ap.add_argument("--vertical-gauge", type=float, default=12.0)
    ap.add_argument("--centre", type=int, required=True,
                    help="1-based column the gore opens at")
    ap.add_argument("--spine", type=int, required=True,
                    help="1-based column that survives to the crown")
    ap.add_argument("--equator", type=int,
                    help="1-based round the crown starts (default: as late "
                         "as the sphere allows)")
    ap.add_argument("-n", "--dry-run", action="store_true")
    args = ap.parse_args()

    chart = Chart.read_csv(args.chart_csv)
    out, equator, widths, radius, events = reshape(
        chart, args.repeats, args.horizontal_gauge, args.vertical_gauge,
        args.centre - 1, args.spine - 1,
        None if args.equator is None else args.equator - 1)

    n0 = max(sum(1 for t in r if t.strip()) for r in chart.rows) * args.repeats
    print(f"{chart.name}: {chart.height} rounds x {chart.width} cols, "
          f"{args.repeats} repeats -> {n0} stitches "
          f"({n0 / args.horizontal_gauge:.1f} in around), sphere radius "
          f"{radius:.2f} in")
    print(f"  brim rounds 1-{equator}, crown rounds {equator + 1}-"
          f"{chart.height} ({len(widths)} rounds, sphere wants "
          f"{math.pi / 2 * args.vertical_gauge * radius:.1f})")
    print(f"  live per repeat: {widths[0]} -> {widths[-1]}, "
          f"{len(events)} decrease rounds")
    for r, live, slots in events:
        print(f"    round {r + 1:3d}: -{len(slots)} at {slots} -> {live}")

    if not args.dry_run:
        path = args.output or args.chart_csv
        out.write_csv(path)
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
