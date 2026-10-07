#!/usr/bin/env python
"""Export a hat chart (one pattern repeat) as a one-page LaTeX chart.

The output is a complete document (letter paper, 0.5in margins) with a
title line, the chart as a TikZ grid sized to fill the page, and a key.
Stitch symbols come from the ``knitting`` package's chart font (CTAN:
knitting, in TeX Live), so the chart uses the same symbols as other
LaTeX-typeset patterns. Three styles:

  words    cell text, black and white: "f", "b", "f k2tog", ...
  symbols  chart symbols for decreases / increases, plus the f / b
           colour letter, black and white
  color    cells filled with the foreground / background colour and
           chart symbols on top; no letters

Blank cells (no stitch on that round) are grey, as in printed charts.
A vertical repeat (chart.vertical_repeat) is outlined in a heavy
orange box, called out in the key and bracketed "repeat xN" beside the
round numbers. With alt_lines, every other thin horizontal grid line is white,
pairing rounds into bands the eye can follow across the chart.
Cells keep the knitted proportions (stitch width : round height =
rounds per inch : stitches per inch) and are scaled so the whole chart
fits on the page.

    python tools/chart_tex.py patterns/alt_cubes.csv alt_cubes.tex --style color
    pdflatex alt_cubes.tex
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart import COLORS, DEFAULT_HORIZONTAL_GAUGE, DEFAULT_VERTICAL_GAUGE, Chart  # noqa: E402

STYLES = ("words", "symbols", "color")

# op -> (glyph in the knitting package's chart font, key text). Mirrors
# STITCHES in web/stitches.js.
GLYPHS = {
    "p": ("=", "p: purl"),
    "k2tog": (">", "k2tog: knit 2 together (right-leaning decrease)"),
    "ssk": ("<", "ssk: slip, slip, knit (left-leaning decrease)"),
    "cdd": ("A", "cdd: centred double decrease -- slip 2 stitches together "
                 "knitwise, knit 1, pass the 2 slipped stitches over (psso)"),
    "k3tog": ("R", "k3tog: knit 3 together (right-leaning double decrease)"),
    "p2tog": (";", "p2tog: purl 2 together"),
    "yo": ("O", "yo: yarn over"),
    "m1": ("m", "m1: make 1"),
    "m1l": ("m", "m1l: make 1 left"),
    "m1r": ("m", "m1r: make 1 right"),
    "kfb": ("y", "kfb: knit front and back"),
    "co": ("U", "co: cast on 1 stitch"),
}

PAGE_W, PAGE_H, MARGIN = 8.5, 11.0, 0.5    # inches
PT = 72.27                                   # TeX points per inch

PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[letterpaper,margin=%(margin)sin]{geometry}
\usepackage{tikz}
\usepackage{knitting}   %% chart symbol font (CTAN: knitting)
\usepackage{adjustbox}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\definecolor{fg}{HTML}{%(fg)s}
\definecolor{bg}{HTML}{%(bg)s}
\definecolor{fgtext}{HTML}{%(fgtext)s}
\definecolor{bgtext}{HTML}{%(bgtext)s}
\definecolor{nostitch}{gray}{0.62}
\definecolor{chartgrid}{gray}{0.45}
\definecolor{repeatbox}{HTML}{FF7A00}
%% A glyph from the knitting font's main layer (no purl-grey box, so it
%% sits cleanly on a coloured cell).
\newcommand\kg[1]{{\fontencoding{U}\fontfamily{knit}\fontseries{n}\fontshape{n}\selectfont #1}}
%% \ks[glyph]{width}{height}: a glyph stretched to fill a cell; the font
%% draws each symbol to the edges of its stitch box.
\newcommand\ks[3][]{\resizebox*{#2}{#3}{\kg{#1}}}
"""


def _hex(color):
    return color.lstrip("#").upper()


def _text_on(color):
    """Black or white text, whichever reads on this fill."""
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
           for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "222222" if lum > 0.25 else "FFFFFF"


def _tex_escape(s):
    return (s.replace("\\", r"\textbackslash{}").replace("_", r"\_")
            .replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")
            .replace("$", r"\$").replace("{", r"\{").replace("}", r"\}")
            .replace("~", r"\textasciitilde{}").replace("^", r"\^{}"))


def chart_to_tex(chart, style="color", repeats=None, horizontal_gauge=DEFAULT_HORIZONTAL_GAUGE,
                 vertical_gauge=DEFAULT_VERTICAL_GAUGE, fg="#2f76c4", bg="#e9e5da",
                 title=None, alt_lines=True):
    """The chart as a complete one-page LaTeX document (a string)."""
    if style not in STYLES:
        raise ValueError(f"style must be one of {', '.join(STYLES)}")
    grid = chart.parsed()
    H, W = chart.height, chart.width
    if not H or not W:
        raise ValueError("chart is empty")
    used = sorted({o for row in grid for c in row if c for o in c.ops},
                  key=lambda o: (o not in GLYPHS, list(GLYPHS).index(o)
                                 if o in GLYPHS else 0, o))
    has_blank = any(c is None for row in grid for c in row)
    vrep = chart.vertical_repeat

    # ---- key: [(swatch tikz, text)] ---------------------------------
    key = []
    if style == "color":
        key += [(r"\fill[fg] (0,0) rectangle (1,1);", "foreground colour"),
                (r"\fill[bg] (0,0) rectangle (1,1);", "background colour")]
    else:
        key += [(r"\node at (.5,.5) {\sffamily f};", "foreground colour"),
                (r"\node at (.5,.5) {\sffamily b};", "background colour")]
    if has_blank:
        key.append((r"\fill[nostitch] (0,0) rectangle (1,1);",
                    "no stitch (worked into a decrease, or not yet cast on)"))
    for op in used:
        glyph, text = GLYPHS.get(op, (None, op))
        if style == "words" or glyph is None:
            sw = rf"\node at (.5,.5) {{\adjustbox{{max width=.9\linewidth}}{{\sffamily\tiny {_tex_escape(op)}}}}};"
        else:
            sw = rf"\node[anchor=south west] at (0,0) {{\ks[{glyph}]{{.16in}}{{.16in}}}};"
        key.append((sw, _tex_escape(text if style != "words" or glyph is None
                                    else text.replace(f"{op}: ", f"{op} = "))))
    if vrep:
        v0, v1, vn = vrep
        times = "once" if vn == 1 else f"{vn} times"
        in_all = "once" if vn == 1 else f"{vn} times in all"
        key.append((r"\draw[repeatbox, line width=2.4pt] (0,0) rectangle (1,1);",
                    f"repeat (orange box): work rounds {v0}--{v1} {times}"))
    key_cols = 2
    key_rows = math.ceil(len(key) / key_cols)

    # ---- page budget (inches) -> cell size ----------------------------
    text_w, text_h = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
    title_h, numbers_h, safety = 0.45, 0.22, 0.3
    key_h = 0.25 + key_rows * 0.19
    gutter = 0.32                                   # row numbers each side
    bracket = 0.3 if vrep else 0.0                  # repeat bracket, left
    avail_w = text_w - 2 * gutter - 2 * bracket     # kept centred
    avail_h = text_h - title_h - numbers_h - key_h - safety
    aspect = min(2.0, max(1.0, vertical_gauge / horizontal_gauge))  # w / h
    ch = min(avail_h / H, avail_w / (W * aspect), 0.3)
    cw = aspect * ch
    ch_pt = ch * PT
    num_pt = max(3.0, min(7.0, 0.72 * ch_pt))
    letter_pt = max(2.5, min(8.0, 0.62 * ch_pt))

    def font(pt):
        return rf"\fontsize{{{pt:.2f}}}{{{pt * 1.1:.2f}}}\selectfont"

    # ---- chart body -----------------------------------------------------
    out = []
    add = out.append
    add(rf"\begin{{tikzpicture}}[x={cw:.4f}in, y={ch:.4f}in, "
        rf"every node/.style={{inner sep=0pt, outer sep=0pt}}]")
    fills = {"f": [], "b": [], "nostitch": []}
    nodes = []
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell is None:
                fills["nostitch"].append((c, r))
                continue
            if style == "color":
                fills[COLORS[cell.color]].append((c, r))
            nodes.append(_cell_node(cell, c, r, style, cw, ch, letter_pt,
                                    font))
    for name, cells in fills.items():
        if not cells:
            continue
        color = {"f": "fg", "b": "bg"}.get(name, name)
        add(rf"\fill[{color}] " + " ".join(
            f"({c},{r}) rectangle +(1,1)" for c, r in cells) + ";")
    out += [n for n in nodes if n]
    # Grid: thin lines, heavier every 10 rounds / columns. With
    # alt_lines the thin horizontals alternate grey / white.
    thin = [r for r in range(1, H) if r % 10]
    white = [r for r in thin if alt_lines and r % 2 == 0]
    grey = [r for r in thin if r not in white]
    add(r"\draw[chartgrid, line width=0.2pt] "
        + " ".join(f"(0,{r}) -- ({W},{r})" for r in grey)
        + " " + " ".join(f"({c},0) -- ({c},{H})" for c in range(1, W)) + ";")
    if white:
        add(r"\draw[white, line width=0.35pt] "
            + " ".join(f"(0,{r}) -- ({W},{r})" for r in white) + ";")
    for r in range(10, H, 10):
        add(rf"\draw[line width=0.6pt] (0,{r}) -- ({W},{r});")
    for c in range(10, W, 10):
        add(rf"\draw[line width=0.6pt] ({c},0) -- ({c},{H});")
    add(rf"\draw[line width=0.8pt] (0,0) rectangle ({W},{H});")
    # Round numbers on both sides, column numbers below.
    shaping = chart.shaping_row
    for r in range(H):
        n = rf"\textbf{{{r + 1}}}" if shaping == r + 1 else str(r + 1)
        add(rf"\node[anchor=east, font={{\sffamily{font(num_pt)}}}] "
            rf"at (-0.25,{r + 0.5}) {{{n}}};")
        add(rf"\node[anchor=west, font={{\sffamily{font(num_pt)}}}] "
            rf"at ({W + 0.25},{r + 0.5}) {{{n}}};")
    if shaping:
        y = shaping - 1
        add(rf"\draw[red!70!black, line width=1.2pt] (-0.12,{y}) -- (-0.12,{y + 1}) "
            rf"({W + 0.12},{y}) -- ({W + 0.12},{y + 1});")
    if vrep:
        y0, y1 = v0 - 1, v1
        add(rf"\draw[repeatbox, line width=3pt] (0,{y0}) rectangle ({W},{y1});")
        x = rf"[xshift=-{gutter + 0.06:.2f}in]"
        add(rf"\draw[repeatbox, line width=1pt] ({x}0,{y0}) -- ++(-0.07in,0) "
            rf"-- ([xshift=-{gutter + 0.13:.2f}in]0,{y1}) -- ({x}0,{y1});")
        add(rf"\node[rotate=90, anchor=south, text=repeatbox, font={{\sffamily\bfseries{font(max(num_pt, 6.5))}}}] "
            rf"at ([xshift=-{gutter + 0.16:.2f}in]0,{(y0 + y1) / 2}) "
            rf"{{repeat $\times${vn}}};")
    for c in range(W):
        add(rf"\node[anchor=north, font={{\sffamily{font(num_pt)}}}] "
            rf"at ({c + 0.5},-0.25) {{{c + 1}}};")
    add(r"\end{tikzpicture}")

    # ---- document --------------------------------------------------------
    name = _tex_escape(title or chart.name)
    reps = f"{repeats} repeats around" if repeats else "one repeat"
    rounds = (f"{H} chart rounds ({H + (vrep[2] - 1) * (vrep[1] - vrep[0] + 1)}"
              " knit)" if vrep else f"{H} rounds")
    sub = (f"{W} stitches $\\times$ {rounds} per repeat, worked {reps} "
           f"$\\cdot$ gauge {horizontal_gauge:g} st $\\times$ "
           f"{vertical_gauge:g} rnds per inch")
    notes = ("Rounds are numbered from the cast-on (bottom) up; "
             "each round is worked from column 1 to column "
             f"{W}, left to right, as in the editor.")
    if vrep:
        notes += (f" Work rounds {v0}--{v1} (orange box) {in_all}, "
                  f"then continue with round {v1 + 1}." if v1 < H else
                  f" Work rounds {v0}--{v1} (orange box) {in_all}.")
    if shaping:
        notes += (f" Crown shaping starts at round {shaping} "
                  "(marked in red beside the round numbers).")
    key_cells = []
    for sw, text in key:
        key_cells.append(
            rf"\tikz[x=0.16in,y=0.16in,baseline=0.03in,inner sep=0pt]{{\draw[chartgrid] (0,0) rectangle (1,1); {sw}}}"
            rf"~{text}")
    while len(key_cells) % key_cols:
        key_cells.append("")
    key_rows_tex = [" & ".join(key_cells[i:i + key_cols]) + r" \\"
                    for i in range(0, len(key_cells), key_cols)]

    doc = [PREAMBLE % {"margin": MARGIN, "fg": _hex(fg), "bg": _hex(bg),
                       "fgtext": _text_on(fg), "bgtext": _text_on(bg)},
           r"\begin{document}",
           rf"{{\large\bfseries {name}}}\hfill{{\small {sub}}}\par",
           r"\vspace{6pt}",
           r"\begin{center}",
           *out,
           r"\end{center}",
           r"\vspace{2pt}",
           r"{\small\sffamily",
           r"\begin{tabular}{@{}" + "p{0.48\\linewidth}" * key_cols + "@{}}",
           *key_rows_tex,
           r"\end{tabular}\par\vspace{3pt}",
           rf"\footnotesize {notes}}}",
           r"\end{document}", ""]
    return "\n".join(doc)


def _cell_node(cell, c, r, style, cw, ch, letter_pt, font):
    """TikZ for what is drawn inside one live cell."""
    x, y = c + 0.5, r + 0.5
    letter = COLORS[cell.color]
    glyphs = [GLYPHS[o][0] for o in cell.ops if o in GLYPHS]
    other = [o for o in cell.ops if o not in GLYPHS]
    fit = rf"\adjustbox{{max width={0.9 * cw:.4f}in}}"
    if style == "words":
        text = " ".join([letter, *cell.ops])
        return (rf"\node[font={{\sffamily{font(letter_pt)}}}] at ({x},{y}) "
                rf"{{{fit}{{{_tex_escape(text)}}}}};")
    parts = []
    color = ("fgtext" if cell.color else "bgtext") if style == "color" \
        else "black"
    if glyphs:
        parts.append(rf"\node[anchor=south west, text={color}] at ({c},{r}) "
                     rf"{{\colorlet{{forecolor}}{{{color}}}\ks[{glyphs[0]}]{{{cw:.4f}in}}{{{ch:.4f}in}}}};")
    if other:
        parts.append(rf"\node[text={color}, font={{\sffamily{font(letter_pt * 0.7)}}}] "
                     rf"at ({x},{y - (0.3 if glyphs else 0)}) "
                     rf"{{{fit}{{{_tex_escape(' '.join(other))}}}}};")
    if style == "symbols":
        if glyphs or other:
            # Colour letter tucked in the corner of a symbol cell.
            parts.append(rf"\node[anchor=north west, font={{\sffamily{font(letter_pt * 0.55)}}}] "
                         rf"at ({c + 0.05},{r + 0.97}) {{{letter}}};")
        else:
            parts.append(rf"\node[font={{\sffamily{font(letter_pt)}}}] "
                         rf"at ({x},{y}) {{{letter}}};")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chart_csv")
    ap.add_argument("output_tex")
    ap.add_argument("--style", choices=STYLES, default="color")
    ap.add_argument("--repeats", type=int)
    ap.add_argument("--horizontal-gauge", type=float)
    ap.add_argument("--vertical-gauge", type=float)
    ap.add_argument("--fg", default="#2f76c4")
    ap.add_argument("--bg", default="#e9e5da")
    args = ap.parse_args()
    chart = Chart.read_csv(args.chart_csv)

    def meta(key, cast, given, default):
        if given is not None:
            return given
        try:
            return cast(chart.meta[key])
        except (KeyError, ValueError):
            return default
    tex = chart_to_tex(
        chart, args.style,
        repeats=meta("repeats", int, args.repeats, None),
        horizontal_gauge=meta("horizontal_gauge", float, args.horizontal_gauge, DEFAULT_HORIZONTAL_GAUGE),
        vertical_gauge=meta("vertical_gauge", float, args.vertical_gauge, DEFAULT_VERTICAL_GAUGE),
        fg=args.fg, bg=args.bg)
    with open(args.output_tex, "w") as f:
        f.write(tex)
    print(f"{chart.name} ({args.style}) -> {args.output_tex}")


if __name__ == "__main__":
    main()
