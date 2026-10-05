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

Chart-level parameters ride along as ``# key: value`` lines at the top of
the CSV: ``shaping_row`` (the 1-based sheet row where crown shaping
begins, i.e. the sphere's equator) and ``vrepeat_start`` /
``vrepeat_end`` / ``vrepeat_count`` (a vertical repeat: sheet rows
start..end, 1-based and inclusive, are worked count times in all).
Unknown keys are preserved.
"""

import csv
import io
from dataclasses import dataclass, field

COLORS = ("b", "f")           # index == color id in the bundle (0 = bg, 1 = fg)
DECREASE_OPS = {"k2tog", "ssk", "k3tog", "cdd", "p2tog"}
# Centred double decreases: the stitch in this slot is the middle of
# three, and the dead slots on either side of it are worked into it.
# k3tog is kept for older charts; new ones use cdd.
CENTRED_DECREASE_OPS = {"k3tog", "cdd"}
INCREASE_OPS = {"co", "kfb", "m1", "m1l", "m1r", "yo", "pfb"}

# Default gauge, measured from a finished hat: 17.5 stitches and 26
# rounds in 2 inches.
DEFAULT_HORIZONTAL_GAUGE = 17.5 / 2    # stitches per inch
DEFAULT_VERTICAL_GAUGE = 26 / 2        # rounds per inch


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
    def is_centred_decrease(self):
        return any(o in CENTRED_DECREASE_OPS for o in self.ops)

    @property
    def consumes(self):
        """Stitches from the round below this one absorbs besides its own
        (k2tog / ssk 1, cdd 2)."""
        if self.is_centred_decrease:
            return 2
        return 1 if self.is_decrease else 0

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
    sheet_row: int = -1         # chart row this round was knit from
    # newly dead slot -> live slot of the stitch it was worked into
    merged_into: dict = field(default_factory=dict)
    # live slot -> slot of the stitch it is worked into on the round
    # below; absent on the first round and for cast-ons
    below: dict = field(default_factory=dict)

    @property
    def count(self):
        return len(self.live)


class Chart:
    def __init__(self, rows, name="chart", meta=None):
        rows = [list(r) for r in rows]
        width = max((len(r) for r in rows), default=0)
        for r in rows:
            r.extend([""] * (width - len(r)))
        self.rows = rows
        self.name = name
        self.meta = dict(meta or {})

    @property
    def shaping_row(self):
        """1-based sheet row where crown shaping begins, or None."""
        try:
            row = int(self.meta.get("shaping_row"))
        except (TypeError, ValueError):
            return None
        return row if 1 <= row <= self.height else None

    @shaping_row.setter
    def shaping_row(self, row):
        if row is None or row == "":
            self.meta.pop("shaping_row", None)
        else:
            self.meta["shaping_row"] = str(int(row))

    @property
    def vertical_repeat(self):
        """(start, end, count): sheet rows start..end (1-based,
        inclusive) worked count times in all; None if unset or invalid."""
        try:
            start = int(self.meta["vrepeat_start"])
            end = int(self.meta["vrepeat_end"])
            count = int(self.meta.get("vrepeat_count", 1))
        except (KeyError, TypeError, ValueError):
            return None
        if not 1 <= start <= end <= self.height or count < 1:
            return None
        return start, end, count

    @vertical_repeat.setter
    def vertical_repeat(self, spec):
        """spec: None, (start, end, count) or {"start", "end", "count"}."""
        for k in ("vrepeat_start", "vrepeat_end", "vrepeat_count"):
            self.meta.pop(k, None)
        if not spec:
            return
        if isinstance(spec, dict):
            spec = (spec.get("start"), spec.get("end"), spec.get("count", 1))
        start, end, count = (int(v) for v in spec)
        self.meta["vrepeat_start"] = str(start)
        self.meta["vrepeat_end"] = str(end)
        self.meta["vrepeat_count"] = str(max(1, count))

    def round_rows(self):
        """Sheet row (0-based) of every round in knit order, with the
        vertical repeat expanded."""
        rows = list(range(self.height))
        vr = self.vertical_repeat
        if vr is None:
            return rows
        start, end, count = vr
        return rows[:start - 1] + rows[start - 1:end] * count + rows[end:]

    def expanded_rows(self):
        """Cell text of every round in knit order (vertical repeat
        expanded)."""
        return [self.rows[i] for i in self.round_rows()]

    @property
    def width(self):
        return len(self.rows[0]) if self.rows else 0

    @property
    def height(self):
        return len(self.rows)

    @classmethod
    def from_csv_text(cls, text, name="chart"):
        """Parse CSV text: leading ``# key: value`` lines are chart meta."""
        lines = text.splitlines()
        meta = {}
        while lines and lines[0].lstrip().startswith("#"):
            key, sep, value = lines.pop(0).lstrip()[1:].partition(":")
            if sep and key.strip():
                meta[key.strip()] = value.strip().rstrip(",")
        rows = [[c.strip() for c in row]
                for row in csv.reader(io.StringIO("\n".join(lines)))]
        return cls(strip_trailing_blank(rows), name=name, meta=meta)

    @classmethod
    def read_csv(cls, path, name=None):
        with open(path, newline="") as f:
            text = f.read()
        if name is None:
            import os
            name = os.path.splitext(os.path.basename(path))[0]
        return cls.from_csv_text(text, name=name)

    def write_csv(self, path):
        with open(path, "w", newline="") as f:
            for key, value in self.meta.items():
                f.write(f"# {key}: {value}\n")
            csv.writer(f).writerows(self.rows)

    def to_json(self):
        return {"cells": self.rows, "width": self.width,
                "height": self.height, "name": self.name,
                "shaping_row": self.shaping_row,
                "vertical_repeat": self._vertical_repeat_json()}

    def _vertical_repeat_json(self):
        vr = self.vertical_repeat
        return dict(zip(("start", "end", "count"), vr)) if vr else None

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
        parsed = self.parsed()
        sheet_rows = self.round_rows()
        grid = [parsed[i] * repeats for i in sheet_rows]
        if not grid or not any(grid[0]):
            raise ValueError("first round has no stitches; "
                             "is the chart upside-down?")
        n_slots = len(grid[0])
        rounds = []
        prev = []
        for r, row in enumerate(grid):
            live = [s for s in range(n_slots) if row[s] is not None]
            if not live:
                raise ValueError(f"round {sheet_rows[r] + 1} has no stitches")
            cells = {s: row[s] for s in live}
            if r and len(live) == len(prev) and not any(
                    c.is_decrease or c.is_increase for c in cells.values()):
                # Same count, no shaping: blanks that moved are only
                # where the chart draws the gap, not a cast-on plus a
                # decrease. Collapse both rounds and stack them.
                rounds.append(Round(live, cells, [], [],
                                    sheet_row=sheet_rows[r],
                                    below=align_ranks(prev, live, n_slots)))
            else:
                newly_dead = sorted(set(prev) - set(live))
                newly_cast = sorted(set(live) - set(prev)) if r else []
                rounds.append(Round(live, cells, newly_dead, newly_cast,
                                    sheet_row=sheet_rows[r],
                                    merged_into=resolve_merges(
                                        live, cells, newly_dead, n_slots),
                                    below=link_nearest(prev, live,
                                                       newly_cast, n_slots)))
            prev = live

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
                                    below=link_nearest(prev.live, live, [],
                                                       n_slots),
                                    synthesized=True,
                                    sheet_row=self.height + len(rounds)
                                    - len(sheet_rows),
                                    merged_into=resolve_merges(
                                        live, cells, newly_dead,
                                        n_slots)))
                frontier = newly_dead
        return rounds


def from_bundle(bundle):
    """Rebuild the single-repeat chart from a layout bundle.

    Accepts a server bundle (has "chart"), a bare chart export (has
    "cells"), or a static layout JSON (has per-stitch chart_cell,
    colors, ops); repeat 0 of every round is read back.
    """
    if "cells" in bundle:
        chart = Chart(bundle["cells"], name=bundle.get("name", "chart"))
        chart.shaping_row = bundle.get("shaping_row")
        chart.vertical_repeat = bundle.get("vertical_repeat")
        return chart
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


def link_nearest(prev, live, newly_cast, n_slots):
    """Each stitch hangs from the nearest live slot below; cast-ons
    (and the first round, prev empty) have no stitch below."""
    if not prev:
        return {}
    cast = set(newly_cast)
    return {s: nearest_slot(prev, s, n_slots) for s in live if s not in cast}


def align_ranks(prev, live, n_slots, max_shift=8):
    """Stack two rounds with the same stitch count: the k-th stitch of
    ``live`` is worked into the (k + shift)-th of ``prev`` (cyclic), as if
    both rows were collapsed left over their blanks. shift is the one
    that moves stitches least around the ring, 0 (the plain left
    collapse) on a tie, so a gap that wraps past the edge of a repeat
    does not twist the whole round."""
    n = len(live)
    if live == prev:
        return dict(zip(live, prev))

    def cost(k):
        return sum(min((a - b) % n_slots, (b - a) % n_slots)
                   for a, b in zip(live, prev[k:] + prev[:k]))
    shift = min(range(-min(max_shift, n - 1), min(max_shift, n - 1) + 1),
                key=lambda k: (cost(k % n), abs(k)))
    k = shift % n
    return dict(zip(live, prev[k:] + prev[:k]))


def resolve_merges(live, cells, newly_dead, n_slots):
    """Assign each newly dead slot to the stitch it was worked into.

    A centred decrease (k3tog, cdd) takes the nearest newly dead slot on
    each side of it, so its three parents are left, itself and right and
    it sits over the middle one. Other decreases (k2tog, ssk, ...) take
    the nearest remaining dead slot on either side (left on a tie).
    Neither looks past a stitch live on this round. Dead slots no
    decrease claims fall back to the nearest live stitch.
    """
    live_set = set(live)
    dead = set(newly_dead)     # slots dead for longer are stepped over
    merged = {}

    def walk(s, step):
        """First unclaimed newly dead slot from s in direction step,
        and its distance; (None, None) if a live stitch comes first."""
        for d in range(1, n_slots):
            t = (s + step * d) % n_slots
            if t in live_set:
                return None, None
            if t in dead and t not in merged:
                return t, d
        return None, None

    decs = [s for s in live if cells[s].consumes]
    for s in decs:
        if cells[s].is_centred_decrease:
            for step in (-1, 1):
                t, _ = walk(s, step)
                if t is not None:
                    merged[t] = s
    for s in decs:
        if not cells[s].is_centred_decrease:
            (lt, ld), (rt, rd) = walk(s, -1), walk(s, 1)
            if lt is not None and (rt is None or ld <= rd):
                merged[lt] = s
            elif rt is not None:
                merged[rt] = s
    for t in newly_dead:
        if t not in merged:
            merged[t] = nearest_slot(live, t, n_slots)
    return merged


def from_legacy(rows, implicit_decreases=False):
    """Convert a B/W/O/D chart (extract_chart.py) to text cells.

    B -> f, W -> b, O/D -> blank. D marks are cumulative; a killed slot
    stays dead even if re-coloured later. Every killed slot puts
    ``k2tog`` on its nearest survivor (``cdd`` when two slots share a
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
            # one consumed neighbour -> k2tog, two -> cdd, more -> k<n>tog
            text[k] += "-cdd" if n == 2 else f"-k{n + 1}tog"
        out.append(text)
    return Chart(out)
