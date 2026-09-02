"""Chart model for circular hat patterns.

A chart is one pattern repeat: a list of rounds in knit order (cast-on
first), each a list of cell strings. A cell is blank (no stitch in that
slot on that round) or a token ``<color>[-<op>[-<op>...]]`` where color
is ``f`` (foreground) or ``b`` (background) and each op is a stitch
modifier such as ``k2tog`` or ``co``. See HAT_EDITOR_PLAN.md.

Structure (which slots are live, which have parents, which were
consumed) is derived from blank-vs-filled cells. Ops only record where
the author placed a decrease / cast-on, which the renderer and
optimizer use as flags. Unknown ops are preserved and ignored.
"""

import csv
from dataclasses import dataclass, field

COLORS = ("b", "f")           # index == color id in the bundle (0 = bg, 1 = fg)
DECREASE_OPS = {"k2tog", "ssk", "k3tog", "cdd", "p2tog"}
INCREASE_OPS = {"co", "kfb", "m1", "m1l", "m1r", "yo", "pfb"}


@dataclass(frozen=True)
class Cell:
    color: int                 # 0 background, 1 foreground
    ops: tuple = ()

    @property
    def text(self):
        return "-".join((COLORS[self.color],) + self.ops)

    @property
    def is_decrease(self):
        return any(o in DECREASE_OPS for o in self.ops)

    @property
    def is_increase(self):
        return any(o in INCREASE_OPS for o in self.ops)


def parse_cell(text):
    """Return a Cell, None for blank, or raise ValueError for bad text."""
    if text is None:
        return None
    parts = [p.strip().lower() for p in str(text).strip().split("-")]
    if parts == [""]:
        return None
    if parts[0] not in COLORS:
        raise ValueError(f"unknown color {parts[0]!r} in cell {text!r}")
    ops = tuple(p for p in parts[1:] if p)
    return Cell(COLORS.index(parts[0]), ops)


@dataclass
class Round:
    """One knitted round of the tiled chart."""

    live: list                  # slot indices with a stitch, in knit order
    cells: dict                 # slot -> Cell
    newly_dead: list            # slots live on the previous round, blank now
    newly_cast: list            # slots blank on the previous round, live now
    synthesized: bool = False   # generated past the end of the chart

    @property
    def count(self):
        return len(self.live)


class Chart:
    def __init__(self, rows, name="chart"):
        rows = [list(r) for r in rows]
        width = max((len(r) for r in rows), default=0)
        for r in rows:
            r.extend([""] * (width - len(r)))
        self.rows = rows
        self.name = name

    @property
    def width(self):
        return len(self.rows[0]) if self.rows else 0

    @property
    def height(self):
        return len(self.rows)

    @classmethod
    def read_csv(cls, path, name=None):
        with open(path, newline="") as f:
            rows = [[c.strip() for c in row] for row in csv.reader(f)]
        rows = strip_trailing_blank(rows)
        if name is None:
            import os
            name = os.path.splitext(os.path.basename(path))[0]
        return cls(rows, name=name)

    def write_csv(self, path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerows(self.rows)

    def to_json(self):
        return {"cells": self.rows, "width": self.width,
                "height": self.height, "name": self.name}

    def errors(self):
        """[(row, col, message)] for cells that do not parse."""
        out = []
        for r, row in enumerate(self.rows):
            for c, text in enumerate(row):
                try:
                    parse_cell(text)
                except ValueError as e:
                    out.append((r, c, str(e)))
        return out

    def parsed(self):
        """rows x width grid of Cell | None; bad cells count as blank."""
        grid = []
        for row in self.rows:
            prow = []
            for text in row:
                try:
                    prow.append(parse_cell(text))
                except ValueError:
                    prow.append(None)
            grid.append(prow)
        return grid

    def rounds(self, repeats=1, extend_crown=False, wedges=8):
        """Tile the chart ``repeats`` times around and resolve rounds.

        With extend_crown, decrease diagonals keep consuming their
        nearest live neighbour past the end of the chart until at most
        ``wedges`` stitches remain (rounds marked synthesized).
        """
        grid = [row * repeats for row in self.parsed()]
        if not grid or not any(grid[0]):
            raise ValueError("first round has no stitches; "
                             "is the chart upside-down?")
        n_slots = len(grid[0])
        rounds = []
        prev_live = set()
        for r, row in enumerate(grid):
            live = [s for s in range(n_slots) if row[s] is not None]
            if not live:
                raise ValueError(f"round {r + 1} has no stitches")
            live_set = set(live)
            newly_dead = sorted(prev_live - live_set)
            newly_cast = sorted(live_set - prev_live) if r > 0 else []
            rounds.append(Round(live, {s: row[s] for s in live},
                                newly_dead, newly_cast))
            prev_live = live_set

        last_dec = next((rd for rd in reversed(rounds) if rd.newly_dead), None)
        if extend_crown and last_dec is not None:
            frontier = list(last_dec.newly_dead)[:wedges]
            while rounds[-1].count - len(frontier) >= wedges:
                prev = rounds[-1]
                live = list(prev.live)
                newly_dead = []
                for s in frontier:
                    victim = nearest_slot(live, s, n_slots)
                    live.remove(victim)
                    newly_dead.append(victim)
                cells = {}
                for s in live:
                    base = prev.cells[s]
                    ops = tuple(o for o in base.ops if o not in DECREASE_OPS
                                and o not in INCREASE_OPS)
                    cells[s] = Cell(base.color, ops)
                for s in newly_dead:
                    k = nearest_slot(live, s, n_slots)
                    cells[k] = Cell(cells[k].color, cells[k].ops + ("k2tog",))
                rounds.append(Round(live, cells, newly_dead, [],
                                    synthesized=True))
                frontier = newly_dead
        return rounds


def from_bundle(bundle):
    """Rebuild the single-repeat chart from a layout bundle.

    Accepts a server bundle (has "chart"), a bare chart export (has
    "cells"), or a static layout JSON (has per-stitch chart_cell,
    colors, ops); repeat 0 of every round is read back.
    """
    if "cells" in bundle:
        return Chart(bundle["cells"], name=bundle.get("name", "chart"))
    if "chart" in bundle:
        return from_bundle(bundle["chart"])
    if "chart_cell" not in bundle:
        raise ValueError("JSON has no chart: expected cells, chart, "
                         "or chart_cell fields")
    h = bundle.get("chart_height", bundle.get("n_chart_rounds", 0))
    w = bundle.get("chart_width", 0)
    rows = [[""] * w for _ in range(h)]
    ops = bundle.get("ops") or [[]] * len(bundle["chart_cell"])
    for i, (r, c) in enumerate(bundle["chart_cell"]):
        if r < h and not rows[r][c]:
            rows[r][c] = Cell(bundle["colors"][i], tuple(ops[i])).text
    return Chart(rows, name=bundle.get("name", "chart"))


def strip_trailing_blank(rows):
    """Drop empty rows at the end (a sheet's spare lines); interior
    empty rows are kept so row numbers stay 1-1 with the sheet and
    rounds() can report them."""
    rows = list(rows)
    while rows and not any(c for c in rows[-1]):
        rows.pop()
    return rows


def nearest_slot(slots, s, n_slots):
    """Live slot closest to slot s around the ring."""
    return min(slots, key=lambda c: min((c - s) % n_slots, (s - c) % n_slots))


def from_legacy(rows, implicit_decreases=False):
    """Convert a B/W/O/D chart (extract_chart.py) to text cells.

    B -> f, W -> b, O/D -> blank. D marks are cumulative; a killed slot
    stays dead even if re-coloured later. Every killed slot puts
    ``k2tog`` on its nearest survivor (``k3tog`` when two slots share a
    survivor), and every slot that goes from O
    to live gets ``co`` -- the rules the old spiral_layout used. With
    implicit_decreases, a slot that was live and simply turns O also
    counts as killed (sheets that only mark the decrease diagonal).
    """
    n_slots = len(rows[0])
    dead = set()
    out = []
    prev_live = set()
    for r, row in enumerate(rows):
        newly_dead = [s for s, sym in enumerate(row) if sym == "D" and s not in dead]
        if implicit_decreases:
            newly_dead += [s for s in sorted(prev_live)
                           if row[s] == "O" and s not in dead
                           and s not in newly_dead]
        dead.update(newly_dead)
        live = [s for s in range(n_slots) if s not in dead and row[s] in ("B", "W")]
        prev_live = set(live)
        text = [""] * n_slots
        for s in live:
            text[s] = "f" if row[s] == "B" else "b"
            if r > 0 and rows[r - 1][s] == "O":
                text[s] += "-co"
        eaten = {}
        for s in newly_dead:
            k = nearest_slot(live, s, n_slots)
            eaten[k] = eaten.get(k, 0) + 1
        for k, n in eaten.items():
            # one consumed neighbour -> k2tog, two -> k3tog, ...
            text[k] += f"-k{n + 1}tog"
        out.append(text)
    return Chart(out)
