# WoolyGraphs chart -> spiral layout -> web editor pipeline.
#
#   make small_cubes    serve the hat editor for patterns/small_cubes.csv at
#                       http://localhost:8765 (the chart is compiled in-process
#                       and recompiled on every edit in the browser)
#   make edit-<name>    same, for patterns/<name>.csv (or .json)
#   make open FILE=p    same, for any chart CSV / layout JSON path
#   make layout         write web/data/small_cubes_layout.json for the static
#                       viewer (make web/data/<name>_layout.json for others)
#   make alt_cubes      serve the editor for patterns/alt_cubes.csv
#   make charts         re-extract patterns/small_cubes.csv and alt_cubes.csv
#                       from the workbook
#   make layouts        write web/data/<name>_layout.json for every chart
#   make test           run the unit tests
#
# The venv and vendored three.js are built on demand and cached.

PY      := .venv/bin/python
XLSX    := patterns/Necker_Birds_Hat.xlsx
CHART   := patterns/small_cubes.csv
LAYOUT  := web/data/small_cubes_layout.json
THREE   := web/lib/three.module.js
PORT    := 8765
REPEATS := 4
# Per-chart repeat count (the shaping in each CSV is drawn for one value).
REPEATS_alt_cubes := 6
CHART_REPEATS = $(or $(REPEATS_$(1)),$(REPEATS))
HGAUGE  := 8
VGAUGE  := 12

.PHONY: small_cubes alt_cubes open serve layout layouts chart charts test clean

SERVE = $(PY) tools/serve_viewer.py --port $(PORT) --chart "$(1)" \
	    --repeats $(2) --horizontal-gauge $(HGAUGE) --vertical-gauge $(VGAUGE)
BROWSE = ( sleep 1 && open "http://localhost:$(PORT)/" ) &

small_cubes: $(THREE) | $(PY)
	@$(BROWSE)
	@$(call SERVE,$(CHART),$(call CHART_REPEATS,small_cubes))

alt_cubes: edit-alt_cubes

# make edit-small_cubes -> patterns/small_cubes.csv (falls back to .json)
edit-%: $(THREE) | $(PY)
	@f=patterns/$*.csv; [ -f "$$f" ] || f=patterns/$*.json; \
	  [ -f "$$f" ] || { echo "no patterns/$*.csv or .json"; exit 1; }; \
	  $(BROWSE) $(call SERVE,$$f,$(call CHART_REPEATS,$*))

# make open FILE=web/data/small_cubes_layout.json
open: $(THREE) | $(PY)
	@[ -n "$(FILE)" ] || { echo "usage: make open FILE=path/to/chart.csv|layout.json"; exit 1; }
	@$(BROWSE)
	@$(call SERVE,$(FILE),$(REPEATS))

serve: $(THREE) | $(PY)
	@$(call SERVE,$(CHART),$(call CHART_REPEATS,small_cubes))

$(PY):
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install torch "numpy<2" openpyxl pytest

# The checked-in charts are the editable source of truth; re-extract from
# the workbook only on request.
chart: | $(PY)
	$(PY) tools/extract_chart.py $(XLSX) Small_Cubes patterns/small_cubes.csv

charts: chart | $(PY)
	$(PY) tools/extract_chart.py $(XLSX) Alt_Cubes patterns/alt_cubes.csv \
	    --first-col D --last-col AQ --last-row 70 --implicit-decreases

layout: $(LAYOUT)

layouts: $(patsubst patterns/%.csv,web/data/%_layout.json,$(wildcard patterns/*.csv))

web/data/%_layout.json: patterns/%.csv tools/spiral_layout.py tools/chart.py | $(PY)
	$(PY) tools/spiral_layout.py $< $@ --repeats $(call CHART_REPEATS,$*) \
	    --horizontal-gauge $(HGAUGE) --vertical-gauge $(VGAUGE)

$(THREE):
	mkdir -p web/lib
	curl -fsSL https://unpkg.com/three@0.160.0/build/three.module.js -o $@

test: | $(PY)
	$(PY) -m pytest -q tests

clean:
	rm -f $(LAYOUT)
