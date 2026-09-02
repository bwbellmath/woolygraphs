# Hat Editor Plan

Goal: turn the spiral hat viewer (`web/`, `tools/serve_viewer.py`) into an
editor. A spreadsheet pane on the right of the 3D view holds one pattern
repeat; the hat on the left is always the graph compiled from that sheet.
Every edit re-derives the graph, so the sheet and the hat are 1-1.

## 1. Chart format (the contract everything else keys off)

One CSV per pattern, one line per round in **knit order** (cast-on first),
one cell per stitch slot of a single pattern repeat. A cell is either
blank (no stitch exists in that slot on that round) or a token:

    <color>[-<op>[-<op>...]]

* `color` is `f` (foreground, default blue) or `b` (background, default
  white). Anything else is flagged as an error in the sheet and skipped.
* `op` is a stitch modifier. Recognised today: `k2tog` / `ssk` (this
  stitch consumes a neighbour: decrease), `co` (cast on mid-fabric: no
  parent below), `kfb` / `m1` (increase). Unknown ops are kept as text,
  displayed, and ignored by the graph builder so future stitch types do
  not need a format change.
* Tokens are case-insensitive; whitespace is trimmed.

Examples: `f`, `b`, `f-k2tog`, `b-co`, `f-kfb`.

Structural facts are derived from *which* cells are blank, not from the
ops: the live ring of a round is the ordered list of non-blank cells;
a slot that is live now and blank on the round below has no parent (a
cast-on); a slot live below and blank now was consumed. The ops just say
*where* the author put the k2tog / cast-on, which is what the renderer
and the optimizer need to know.

`patterns/small_cubes.csv` is rewritten in this format. The legacy
`B/W/O/D` chart that `tools/extract_small_cubes.py` pulls from the xlsx
is converted by `chart.from_legacy`, which places `k2tog` on the nearest
survivor of every killed slot and `co` on every newly live slot, i.e.
exactly the rules the old `resolve_rounds` used, so the compiled hat is
unchanged (8448 stitches, 76 rounds, 136 k2tog, 32 cast-ons).

## 2. Module layout

```
tools/chart.py           chart model: parse_cell, read/write CSV,
                         from_legacy, tile(repeats), rounds(...)
tools/spiral_layout.py   rounds -> positions/neighbors/edges bundle
                         (build_bundle(chart, repeats, gauges) is the one
                         entry point; the CLI is a thin wrapper)
tools/hat_optimizer.py   Adam smoothing over the bundle; round-0 anchor
tools/serve_viewer.py    static files + JSON API; owns one EditorSession
web/app.js               3D view; loadBundle(bundle) rebuilds the scene
web/chart.js             spreadsheet grid component (no three.js)
web/shaping.js           spherical-decrease guide (pure function)
web/index.html           two-pane layout, tabs, colour pickers
```

The bundle JSON stays the boundary between Python and the browser. New
fields: `anchor_flag` (round-0 stitches held on the gauge circle),
`chart_cell` (per stitch `[row, col]` into the single repeat, for
hover/highlight in both directions), `chart_width`, `ops` (per stitch
list of op strings, so the viewer never re-parses text).

A future layout-algorithm overhaul only has to keep producing this
bundle from `chart.rounds(...)`; the sheet, server, and viewer do not
care how positions are computed.

## 3. Server API (tools/serve_viewer.py)

    GET  /api/bundle             current compiled bundle (+ chart, repeats)
    GET  /api/chart              {"cells": [[...]], "repeats", "path",
                                  "horizontal_gauge", "vertical_gauge"}
    POST /api/chart              {"cells", "repeats"?} -> recompile,
                                  reset optimizer, return new bundle
    POST /api/chart/save         write the in-memory chart to its CSV
    GET  /api/state, POST /api/optimize|stop|reset   unchanged

The server starts from `--chart patterns/small_cubes.csv --repeats 4`
and compiles in-process; the static `web/data/*.json` remains an
optional fallback for viewing without a server (`make layout`).

## 4. Browser

* `web/index.html`: flex row. Left: canvas + existing control panel.
  Right: resizable pane with tabs **Chart** and **Shaping**.
* Chart tab toolbar: repeats, foreground / background colour pickers,
  cell zoom, Save, status line. Colours drive both the sheet (CSS
  variables) and the 3D instance colours.
* Grid: rows displayed as worn (crown at top, cast-on at bottom, round
  number in the row header); cells default 24x16 px, i.e. the
  `1/hg : 1/vg` stitch aspect. Conditional formatting: `f` / `b` fill,
  op text drawn small inside the cell, unparsable text outlined red,
  blank cells dark. Keyboard: arrows, Enter/Tab, type-to-edit, Delete
  clears, shift-click range, copy/paste as TSV (round-trips with
  Excel / Sheets). Every change debounces to `POST /api/chart`.
* Hover a cell: the matching stitches in every repeat light up; hover a
  stitch: its cell is outlined.
* Shaping tab: parameters auto-filled from the current chart and gauge
  (slices = repeats, width = chart columns, radius = brim circumference
  / 2pi, equator round = last full-width round) and editable. The
  guide follows the "Sphere Hat Decs" sheet: for each round above the
  equator, `theta = pi/2 - rows/(vg*R)`, ideal slice width
  `round(2*pi*R*sin(theta)*hg / slices)`, centred in the repeat. The
  leftmost and rightmost cells of that ideal width get a yellow outline
  (class only; text and fill untouched).

## 5. Layout / optimizer changes

* Cast-on ring: round 0 is placed on a flat circle at z = 0 whose chord
  spacing is exactly `1/hg`: `R0 = (1/hg) / (2 sin(pi/N0))`. Every other
  round keeps the helix. The same chord formula replaces the old
  `count/(2 pi hg)` radius for all rounds so ring spacing is exact
  everywhere in the initial layout.
* `HatOptimizer` keeps `anchor_flag` stitches fixed (their gradient is
  zeroed each step) so the whole hat hangs from the gauge-exact brim.

## 6. Sequence

1. `tools/chart.py` + tests (parse, legacy conversion reproduces the
   reference counts).                                         [today]
2. `spiral_layout.build_bundle`, anchor circle, new bundle fields, CSV
   regenerated in the new format, extractor emits it directly. [today]
3. Server session + chart endpoints.                          [today]
4. Two-pane UI, grid component, colour pickers, live sync.    [today]
5. Optimizer anchor.                                          [today]
6. Shaping tab and yellow guide overlay.                      [today if time]
7. Later: multiple charts / file picker, undo history, exporting the
   sheet back to xlsx, per-op rest lengths in the optimizer.
