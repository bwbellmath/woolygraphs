"""Tests for tools/chart.py and the hat bundle built from it."""

import csv
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from chart import Cell, Chart, from_legacy, parse_cell  # noqa: E402
from spiral_layout import build_bundle, ring_radius  # noqa: E402
from hat_optimizer import HatOptimizer  # noqa: E402

CHART_CSV = os.path.join(os.path.dirname(__file__), "..", "patterns",
                         "small_cubes.csv")


def test_parse_cell_grammar():
    assert parse_cell("") is None
    assert parse_cell("   ") is None
    assert parse_cell(None) is None
    assert parse_cell("f") == Cell(1)
    assert parse_cell("B") == Cell(0)
    assert parse_cell("f-k2tog") == Cell(1, ("k2tog",))
    assert parse_cell(" b - co ") == Cell(0, ("co",))
    assert parse_cell("f-k2tog-weird") == Cell(1, ("k2tog", "weird"))
    assert parse_cell("f-k2tog").is_decrease
    assert parse_cell("b-co").is_increase
    assert not parse_cell("f-weird").is_decrease
    assert parse_cell("f-k2tog").text == "f-k2tog"
    with pytest.raises(ValueError):
        parse_cell("W")
    with pytest.raises(ValueError):
        parse_cell("k2tog")


def test_rounds_structure_from_blanks():
    rows = [["f", "b", "f", "b"],
            ["f", "b", "f", "b"],
            ["f-k2tog", "", "f", "b"],
            ["f", "", "f-k2tog", ""]]
    ch = Chart(rows)
    rounds = ch.rounds(repeats=2)
    assert [rd.count for rd in rounds] == [8, 8, 6, 4]
    assert rounds[2].newly_dead == [1, 5]
    assert rounds[3].newly_dead == [3, 7]
    assert rounds[2].cells[0].is_decrease
    assert not rounds[1].newly_cast


def test_cast_on_detected_from_blank_below():
    rows = [["f", "", "f"], ["f", "b-co", "f"]]
    rounds = Chart(rows).rounds()
    assert rounds[1].newly_cast == [1]
    bundle = build_bundle(Chart(rows), repeats=1)
    assert bundle["increase_flag"] == [False, False, False, True, False]
    # The cast-on has no parent, so it contributes no column edge upward.
    parents = [e for e in bundle["column_edges"] if e[1] == 3]
    assert parents == []


def test_bad_cells_are_blank_and_reported():
    ch = Chart([["f", "W", "f"], ["f", "b", "f"]])
    assert ch.errors() == [(0, 1, "unknown color 'w' in cell 'W'")]
    assert ch.rounds()[0].count == 2


def test_legacy_conversion():
    rows = [["O", "B", "W", "B"],
            ["B", "B", "W", "B"],
            ["B", "D", "W", "B"],
            ["B", "D", "D", "B"]]
    ch = from_legacy(rows)
    assert ch.rows[0] == ["", "f", "b", "f"]
    assert ch.rows[1] == ["f-co", "f", "b", "f"]
    assert ch.rows[2][0] == "f-k2tog"
    assert ch.rows[3] == ["f", "", "", "f-k2tog"]


def test_small_cubes_reference_hat():
    ch = Chart.read_csv(CHART_CSV)
    assert not ch.errors()
    assert (ch.height, ch.width) == (76, 36)
    b = build_bundle(ch, repeats=4, horizontal_gauge=8.0, vertical_gauge=12.0)
    assert b["n_stitches"] == 8448
    assert b["n_rounds"] == 76
    assert b["stitch_counts"][0] == 136  # 2 columns/repeat cast on later
    assert b["stitch_counts"][-1] == 8
    assert sum(b["decrease_flag"]) == 136
    assert sum(b["increase_flag"]) == 32
    assert b["crown_start_round"] == 26
    assert sum(b["anchor_flag"]) == 136
    assert b["chart_cell"][0] == [0, 0]
    assert b["chart_cell"][34] == [0, 0]  # second repeat maps to same cell
    assert len(b["ops"]) == b["n_stitches"]


def test_cast_on_ring_is_gauge_exact_circle():
    ch = Chart([["f"] * 10] * 3)
    hg = 8.0
    b = build_bundle(ch, repeats=3, horizontal_gauge=hg, vertical_gauge=12.0)
    p = b["positions"]
    n0 = b["stitch_counts"][0]
    assert all(p[i][2] == 0.0 for i in range(n0))
    for i in range(n0):
        chord = math.dist(p[i], p[(i + 1) % n0])
        assert chord == pytest.approx(1.0 / hg, abs=2e-4)
    assert ring_radius(n0, hg) == pytest.approx(
        (1 / hg) / (2 * math.sin(math.pi / n0)))
    assert p[n0][2] > 0.0  # round 1 starts the helix


def test_optimizer_holds_anchor():
    ch = Chart([["f"] * 12] * 4)
    b = build_bundle(ch, repeats=2)
    opt = HatOptimizer(b, lr=0.05)
    n0 = b["stitch_counts"][0]
    before = opt.pos.detach().clone()
    opt.step(5)
    after = opt.pos.detach()
    assert (after[:n0] == before[:n0]).all()
    assert (after[n0:] != before[n0:]).any()
