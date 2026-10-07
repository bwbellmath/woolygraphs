"""Tests for tools/chart_tex.py (LaTeX chart export)."""

import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from chart import Chart  # noqa: E402
from chart_tex import STYLES, chart_to_tex  # noqa: E402

PATTERNS = os.path.join(os.path.dirname(__file__), "..", "patterns")
ROWS = [["f", "b", "f", "b-p"],
        ["f-k2tog", "", "b", "f-weird"],
        ["f", "", "b-ssk", ""]]


def test_styles_differ_as_described():
    chart = Chart(ROWS, name="my_hat")
    words = chart_to_tex(chart, "words", repeats=4)
    symbols = chart_to_tex(chart, "symbols", repeats=4)
    color = chart_to_tex(chart, "color", repeats=4)
    assert r"my\_hat" in words
    # words: cell text, no symbol glyphs in the chart
    assert "f k2tog" in words and r"\ks[>]" not in words.split("tabular")[0]
    # symbols: glyphs and colour letters, no fills by colour
    assert r"\ks[>]" in symbols and r"\ks[<]" in symbols and r"\ks[=]" in symbols
    assert "p: purl" in symbols
    assert re.search(r"\{f\};", symbols) and r"\fill[fg]" not in symbols
    # color: fills and glyphs, no f / b letters in cells
    assert r"\fill[fg]" in color and r"\fill[bg]" in color
    assert r"\ks[>]" in color and not re.search(r"\{[fb]\};", color)
    # blank cells are "no stitch"; unknown ops stay as text
    for tex in (words, symbols, color):
        assert r"\fill[nostitch]" in tex
        assert "weird" in tex


def test_bad_style():
    with pytest.raises(ValueError):
        chart_to_tex(Chart(ROWS), "fancy")


@pytest.mark.skipif(shutil.which("pdflatex") is None
                    or shutil.which("kpsewhich") is None
                    or not subprocess.run(["kpsewhich", "knitting.sty"],
                                          capture_output=True).stdout,
                    reason="pdflatex with the knitting package not installed")
@pytest.mark.parametrize("style", STYLES)
def test_compiles_to_one_letter_page(tmp_path, style):
    chart = Chart.read_csv(os.path.join(PATTERNS, "small_cubes.csv"))
    chart.shaping_row = 40
    tex = tmp_path / "chart.tex"
    tex.write_text(chart_to_tex(chart, style, repeats=4))
    run = subprocess.run(["pdflatex", "-interaction=nonstopmode",
                          "-halt-on-error", tex.name],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-2000:]
    log = (tmp_path / "chart.log").read_text(errors="replace")
    assert "Output written on chart.pdf (1 page" in log


def test_vertical_repeat_and_alternating_lines():
    rows = [["f", "b"]] * 25
    chart = Chart(rows)
    chart.vertical_repeat = (3, 12, 4)
    tex = chart_to_tex(chart, "color", repeats=2)
    assert r"repeat $\times$4" in tex
    assert "work rounds 3--12 4 times" in tex
    assert "(0,2) rectangle (2,12)" in tex          # the outline
    white = next(l for l in tex.splitlines() if l.startswith(r"\draw[white"))
    assert "(0,2) --" in white and "(0,4) --" in white
    assert "(0,3) --" not in white and "(0,10) --" not in white
    plain = chart_to_tex(chart, "color", repeats=2, alt_lines=False)
    assert r"\draw[white" not in plain
    assert r"\draw[repeatbox, line width=3pt] (0,2) rectangle (2,12)" in tex
    assert "repeat (orange box)" in tex               # called out in the key
    chart.vertical_repeat = (3, 12, 1)               # worked once: still boxed
    once = chart_to_tex(chart, "color")
    assert "(0,2) rectangle (2,12)" in once and "work rounds 3--12 once" in once


def test_cdd_key_spells_out_the_construction():
    tex = chart_to_tex(Chart([["f", "f", "f"], ["", "b-cdd", ""]]), "color")
    assert r"\ks[A]" in tex
    assert "slip 2 stitches together knitwise, knit 1" in tex
