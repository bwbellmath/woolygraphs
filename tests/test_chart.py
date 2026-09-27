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


def test_k3tog_is_centred_on_its_middle_parent():
    # Slots 1-3 are worked together as a k3tog sitting in slot 2.
    rows = [["f", "b", "f", "b", "f"],
            ["f", "", "b-k3tog", "", "f"]]
    ch = Chart(rows)
    rd = ch.rounds()[1]
    assert rd.newly_dead == [1, 3]
    assert rd.merged_into == {1: 2, 3: 2}
    assert rd.cells[2].consumes == 2
    b = build_bundle(ch, repeats=1)
    # Round 0 is stitches 0-4, round 1 is 5 (slot 0), 6 (k3tog), 7 (slot 4).
    parents = sorted(e[0] for e in b["column_edges"] if e[1] == 6)
    assert parents == [1, 2, 3]
    assert b["neighbors"][2][3] == 6      # centre goes straight up
    assert b["neighbors"][1][3] == 6      # left and right lean in
    assert b["neighbors"][3][3] == 6
    assert b["neighbors"][6][2] == 2      # k3tog hangs over its centre
    assert b["stitch_counts"] == [5, 3]


def test_k3tog_claims_both_sides_even_on_a_tie():
    # Nearest-live would send slot 1 to slot 0 (ties go to the lower
    # slot); the k3tog in slot 2 must take it.
    rows = [["f"] * 6,
            ["f", "", "f-k3tog", "", "f", "f"]]
    rd = Chart(rows).rounds()[1]
    assert rd.merged_into == {1: 2, 3: 2}


def test_k2tog_takes_the_adjacent_dead_slot():
    rows = [["f"] * 4,
            ["f", "", "f", "f-k2tog"]]
    rd = Chart(rows).rounds()[1]
    # The k2tog in slot 3 is cut off from slot 1 by the live stitch in
    # slot 2, so the dead slot falls back to its nearest stitch.
    assert rd.merged_into == {1: 0}
    rows = [["f"] * 4,
            ["f", "", "f-k2tog", "f"]]
    assert Chart(rows).rounds()[1].merged_into == {1: 2}


def test_k3tog_across_repeat_boundary():
    # The k3tog in slot 0 takes the last slot of the previous repeat.
    rows = [["f"] * 4,
            ["f-k3tog", "", "f", ""]]
    rd = Chart(rows).rounds(repeats=2)[1]
    assert rd.merged_into == {1: 0, 3: 4, 5: 4, 7: 0}


def test_shaping_row_round_trips_through_csv(tmp_path):
    ch = Chart([["f", "b"], ["f", "b"], ["f", ""]], name="x")
    assert ch.shaping_row is None
    ch.shaping_row = 2
    path = tmp_path / "x.csv"
    ch.write_csv(path)
    assert path.read_text().splitlines()[0] == "# shaping_row: 2"
    back = Chart.read_csv(path)
    assert back.shaping_row == 2
    assert back.rows == ch.rows          # the meta line is not a round
    assert back.to_json()["shaping_row"] == 2
    assert build_bundle(back, repeats=1)["shaping_row"] == 2
    ch.shaping_row = None
    ch.write_csv(path)
    assert not path.read_text().startswith("#")


def test_shaping_row_out_of_range_is_ignored():
    ch = Chart.from_csv_text("# shaping_row: 9\nf,b\nf,b\n")
    assert ch.height == 2
    assert ch.shaping_row is None
    assert ch.meta == {"shaping_row": "9"}   # kept, just not applied
