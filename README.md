# woolygraphs
Comprehensive Computer Knitting Suite

## Hat editor (web app)

A browser editor for circular hat charts: a spreadsheet of one pattern
repeat on the right, and the 3D hat compiled from it on the left. Every
edit recompiles the hat, so the sheet and the hat are always 1-1.

### Requirements

- Python 3.12 (`python3.12` on your PATH)
- `make`, `curl`
- a modern browser with WebGL

### Run

```
make small_cubes
```

The first run creates `.venv/` (torch, numpy, openpyxl, pytest) and downloads
three.js into `web/lib/`; both are cached. It then starts the editor server
for `patterns/small_cubes.csv` and opens http://localhost:8765/ in your
browser. Stop the server with Ctrl-C.

Open a different file the same way:

```
make edit-<name>                       # patterns/<name>.csv (or .json)
make open FILE=web/data/my_layout.json # any chart CSV or layout JSON
```

Other targets:

| target              | what it does                                                     |
|---------------------|------------------------------------------------------------------|
| `make serve`        | start the server without opening a browser                       |
| `make test`         | run the unit tests                                               |
| `make layout`       | write `web/data/small_cubes_layout.json` for the static viewer   |
| `make alt_cubes`    | serve the editor for `patterns/alt_cubes.csv`                    |
| `make charts`       | re-extract `small_cubes.csv` and `alt_cubes.csv` from the workbook |
| `make layouts`      | write a layout JSON for every chart in `patterns/`               |
| `make clean`        | remove the generated layout JSON                                 |

Variables can be overridden on the command line, e.g.

```
make serve CHART=patterns/my_hat.csv REPEATS=6 HGAUGE=7.5 VGAUGE=12.5 PORT=9000
```

### Measuring edge lengths

The **Edges** tab plots three overlaid distributions on shared bins, with a
dashed rule at the gauge each one is aiming for:

| series | edges | target |
|---|---|---|
| horizontal | each stitch to its right-hand neighbour in the round | `1/hg` |
| vertical | each stitch to the one above it in its column | `1/vg` |
| shaping | column edges touching a decrease or a cast-on | `1/vg` |

Mean, median and standard deviation of the generated lengths are listed below
the plot. The count axis is logarithmic by default because these distributions
are extremely peaked and a linear axis erases the tail that matters; the x axis
can switch from inches to error relative to gauge, which puts all three series
on one reference line. `?tab=edges`, `?x=error` and `?strain=1` are linkable.

Ticking **edge strain heatmap** in the left panel replaces the stitches with
their edges, coloured by signed error against gauge: black on gauge, orange
too long, teal too short, with a slider for the full-scale value.

Both views read the same edge set the optimizer works on, so they measure the
layout rather than a separate approximation of it. As a baseline, 1000 Adam
iterations on `small_cubes` take the root-mean-square error from 36.8% to 9.1%
and the column-edge standard deviation from 0.0365 to 0.0056 inches, at the
cost of a small systematic stretch (the inflate term pulls every edge a few
percent long).

### Crown shaping

A hat closes correctly when each round's live stitch count follows the
sphere it is wrapping: with `R = N0 / (2*pi*hg)` the count at `r` rounds
above the equator is `N0 * cos(r / (vg*R))`, so the crown takes
`(pi/2)*vg*R` rounds. `tools/reshape_crown.py` re-times an existing
chart's decreases onto that curve, keeping its colours and its gore
geometry (dead slots growing outward from a centre column until one
spine column survives):

```
.venv/bin/python tools/reshape_crown.py patterns/alt_cubes.csv \
    --repeats 6 --centre 10 --spine 20 --dry-run
```

The shaping in a CSV is drawn for one repeat count, so the Makefile
carries a per-chart default (`REPEATS_alt_cubes := 6`). The **Shaping**
tab shows the same curve as a yellow overlay and an ideal-versus-chart
table.

### Chart format

One CSV per pattern, one line per round in knit order (cast-on first),
one cell per stitch slot of a single repeat. A blank cell means no stitch;
otherwise the cell is `<color>[-<op>...]`:

- `f` foreground colour, `b` background colour (pickers in the toolbar)
- ops such as `k2tog`, `ssk` (decrease), `co`, `kfb`, `m1` (increase);
  e.g. `f-k2tog`, `b-co`

The number of repeats knit around the hat is set in the toolbar, not in the
sheet. See `HAT_EDITOR_PLAN.md` for the architecture.

### Using the sheet

- Click a cell and type, or press Enter / F2 to edit. Arrow keys move,
  Delete clears, Shift-click or drag selects a range, Ctrl/Cmd-C copies and
  paste accepts TSV/CSV from Excel or Google Sheets.
- Rows are shown as worn: crown at the top, cast-on at the bottom.
- **Undo** / **Redo** buttons (or Ctrl/Cmd-Z, Ctrl/Cmd-Shift-Z, Ctrl-Y while
  the sheet has focus) step through every edit since the file was loaded.
- Right-click a cell or a row / column header to insert or delete rounds
  and columns (above, below, left, right).
- Hover a cell to light up its stitches in the 3D view, or hover a stitch
  to outline its cell.
- **Save CSV** writes the sheet back to the chart file; **Save as…** writes
  it to a new path under the repository.
- The file bar lists every chart in `patterns/` and layout in `web/data/`:
  pick one and **Load**. **Import…** opens a CSV or JSON from anywhere on
  your disk; **Export CSV** / **Export JSON** download the sheet or the full
  layout bundle. Loading a layout JSON keeps its optimized positions when
  they still match the chart.
- Editing only the text of cells (colours, `k2tog`, `co`) keeps the current
  3D layout and optimizer state. Adding or removing stitches restarts the
  layout from the helix.
- **Save layout** (under Optimize) writes the current positions to
  `patterns/<name>.layout.json`. That file becomes the default layout
  whenever the chart is opened again, as long as it still fits the chart,
  and Reset returns to it. **Export JSON** also carries the current
  positions, so an exported bundle can be re-imported with its layout.
- The **Edges** tab measures how uniform the layout's edge lengths actually
  are (see below).
- The **Shaping** tab overlays the ideal spherical decrease boundary in
  yellow and lists ideal versus actual width per round.

### Without the server

`web/` is plain static files, so after `make layout` you can serve it with
any static server (e.g. `cd web && python3 -m http.server 8000`) and open
http://localhost:8000/?data=data/small_cubes_layout.json. The sheet is then
read-only; it will not work from a `file://` URL because the page uses ES
modules and `fetch`.

## Older notes

```
# https://stitch-maps.com/patterns/display/continental-lace/
# stitch_map -- circles with stitch icons indicating what this stitch "is"
# stitches # describe the stitches
# patterns # describe the pa

# knit # convert a pattern consisting of stitches into a graph. #k2g  # needles
# class edge
# class stitch
#

# show # lay out the graph generated by "knit" #g2m  # models
# woolygraphs
#   goal : get sauron's southern gaze programmed
#   goal : get northern hemisphere pattern programmed.
```
