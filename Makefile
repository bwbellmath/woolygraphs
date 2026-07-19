# WoolyGraphs pattern -> spiral layout -> web viewer pipeline.
#
#   make small_cubes    extract the Small_Cubes chart, compute the helical
#                       layout, and serve the viewer at http://localhost:8765
#
# The venv, chart CSV, layout JSON, and vendored three.js are all built
# on demand and cached; delete them (make clean) to force a rebuild.

PY      := .venv/bin/python
XLSX    := patterns/Necker_Birds_Hat.xlsx
CHART   := patterns/small_cubes.csv
LAYOUT  := web/data/small_cubes_layout.json
THREE   := web/lib/three.module.js
PORT    := 8765

.PHONY: small_cubes serve clean

small_cubes: $(LAYOUT) $(THREE)
	@( sleep 1 && open "http://localhost:$(PORT)/" ) &
	@$(PY) tools/serve_viewer.py --port $(PORT) --data $(LAYOUT)

$(PY):
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install torch "numpy<2" openpyxl

$(CHART): $(XLSX) tools/extract_small_cubes.py | $(PY)
	$(PY) tools/extract_small_cubes.py $(XLSX) Small_Cubes $@

$(LAYOUT): $(CHART) tools/spiral_layout.py | $(PY)
	$(PY) tools/spiral_layout.py $(CHART) $@ --repeats 4

$(THREE):
	mkdir -p web/lib
	curl -fsSL https://unpkg.com/three@0.160.0/build/three.module.js -o $@

serve: $(THREE)
	@$(PY) tools/serve_viewer.py --port $(PORT) --data $(LAYOUT)

clean:
	rm -f $(CHART) $(LAYOUT)
