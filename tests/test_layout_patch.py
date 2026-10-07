"""Tests for tools/layout_patch.py and the editor's save-version naming."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from chart import Chart  # noqa: E402
from layout_patch import align, patch_positions  # noqa: E402
from serve_viewer import next_version  # noqa: E402
from spiral_layout import build_bundle  # noqa: E402

ROWS = [["f", "b", "f", "b", "f", "b"],
        ["f", "b", "f", "b", "f", "b"],
        ["f", "b", "f", "b", "f", "b"],
        ["f", "b", "f", "b", "f", "b"]]


def bundle(rows, repeats=3):
    return build_bundle(Chart(rows), repeats)


def moved(positions, k=0.01):
    """A layout that is not the helix, so kept positions are visible."""
    return [[x + k * i, y - k * i, z + k] for i, (x, y, z) in enumerate(positions)]


def by_key(b, positions):
    return {(r, s): p for r, s, p in zip(b["round_index"], b["stitch_slot"],
                                         positions)}


def dist(a, b):
    return math.dist(a, b)


def test_align_rows():
    assert align([1, 2, 3], [1, 2, 3]) == {0: 0, 1: 1, 2: 2}
    assert align([1, 2, 3], [1, 9, 2, 3]) == {0: 0, 1: 2, 2: 3}
    assert align([1, 2, 3], [1, 3]) == {0: 0, 2: 1}


def test_removed_stitch_keeps_everything_else():
    old = bundle(ROWS)
    old_pos = moved(old["positions"])
    rows = [list(r) for r in ROWS]
    rows[2][1] = ""            # k2tog: the neighbour is worked into it
    rows[2][0] = "f-k2tog"
    new = bundle(rows)
    pos = patch_positions(old, ROWS, old_pos, new, rows)
    before, after = by_key(old, old_pos), by_key(new, pos)
    assert len(after) == len(before) - 3      # one per repeat
    for k, p in after.items():
        assert p == [round(v, 5) for v in before[k]]


def test_add_then_delete_is_identity():
    rows = [list(r) for r in ROWS]
    rows[2][3] = ""
    old = bundle(rows)
    old_pos = moved(old["positions"])
    new = bundle(ROWS)
    pos = patch_positions(old, rows, old_pos, new, ROWS)
    # The returning stitch sits half way between its round neighbours.
    after = by_key(new, pos)
    left, mid, right = after[(2, 2)], after[(2, 3)], after[(2, 4)]
    assert abs(dist(left, mid) - dist(mid, right)) < 1e-3
    assert dist(left, mid) < dist(left, right)
    # Deleting it again restores the original layout exactly.
    back = patch_positions(new, ROWS, pos, old, rows)
    assert back == [[round(v, 5) for v in p] for p in old_pos]


def test_inserted_round_sits_between_its_neighbours():
    old = bundle(ROWS)
    old_pos = moved(old["positions"])
    rows = ROWS[:2] + [["b", "f", "b", "f", "b", "f"]] + ROWS[2:]
    new = bundle(rows)
    pos = patch_positions(old, ROWS, old_pos, new, rows)
    before, after = by_key(old, old_pos), by_key(new, pos)
    for s in range(18):
        assert after[(1, s)] == [round(v, 5) for v in before[(1, s)]]
        assert after[(3, s)] == [round(v, 5) for v in before[(2, s)]]
        mid = [(a + b) / 2 for a, b in zip(before[(1, s)], before[(2, s)])]
        assert dist(after[(2, s)], mid) < 1e-4


def test_inserted_column_keeps_rows():
    old = bundle(ROWS)
    old_pos = moved(old["positions"])
    rows = [r[:3] + ["f-m1"] + r[3:] for r in ROWS]
    new = bundle(rows)
    pos = patch_positions(old, ROWS, old_pos, new, rows)
    before, after = by_key(old, old_pos), by_key(new, pos)
    assert after[(1, 7 + 5)] == [round(v, 5) for v in before[(1, 6 + 4)]]
    assert all(p is not None for p in pos)


def test_repeat_change_is_not_patched():
    old = bundle(ROWS, 3)
    new = bundle(ROWS, 4)
    assert patch_positions(old, ROWS, old["positions"], new, ROWS) is None


def test_next_version():
    assert next_version("hat") == "hat_1"
    assert next_version("hat_3") == "hat_4"
    assert next_version("hat_09") == "hat_10"
    assert next_version("v2_hat_7") == "v2_hat_8"
    assert next_version("alt_cubes_10.layout.layout_layout") == "alt_cubes_11"


# ---- vertical repeats ----------------------------------------------------

def vchart(rows, region=None):
    chart = Chart([list(r) for r in rows])
    chart.vertical_repeat = region
    return chart


def test_vertical_repeat_expands_rounds():
    rows = [["f", "b"], ["b", "f"], ["f", "f"], ["b", "b"]]
    chart = vchart(rows, (2, 3, 3))
    assert chart.vertical_repeat == (2, 3, 3)
    assert chart.round_rows() == [0, 1, 2, 1, 2, 1, 2, 3]
    b = build_bundle(chart, 2)
    assert b["n_rounds"] == b["n_chart_rounds"] == 8
    assert b["round_sheet_row"] == [0, 1, 2, 1, 2, 1, 2, 3]
    # every copy of a cell maps back to the sheet cell
    assert {tuple(c) for c in b["chart_cell"]} == {(r, c) for r in range(4) for c in range(2)}
    # meta round-trips through to_json / from_bundle
    from chart import from_bundle
    assert from_bundle(chart.to_json()).vertical_repeat == (2, 3, 3)
    # out of range regions are ignored
    assert vchart(rows, (3, 9, 2)).vertical_repeat is None


def session_with(rows, region):
    from serve_viewer import EditorSession
    import tempfile
    d = tempfile.mkdtemp(dir=os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(d, "v.csv")
    vchart(rows, region).write_csv(path)
    try:
        return EditorSession(path, 3, 8.0, 12.0, 1e-3)
    finally:
        os.remove(path)
        os.rmdir(d)


def test_vertical_repeat_count_change_rebuilds_but_row_edit_patches():
    s = session_with(ROWS, (2, 3, 2))
    s.opt.step(5)
    s.set_chart(ROWS, vertical_repeat={"start": 2, "end": 3, "count": 2})
    assert s.bundle["n_rounds"] == 6
    # inserting a round inside the region keeps the layout (patched)
    rows = ROWS[:2] + [["b", "f", "b", "f", "b", "f"]] + ROWS[2:]
    s.set_chart(rows, vertical_repeat={"start": 2, "end": 4, "count": 2})
    assert s.bundle["n_rounds"] == 8
    assert s.bundle["layout_source"].endswith("+ chart edits")
    # a new count is a new hat: fresh helix
    s.set_chart(rows, vertical_repeat={"start": 2, "end": 4, "count": 3})
    assert s.bundle["n_rounds"] == 11
    assert "layout_source" not in s.bundle
