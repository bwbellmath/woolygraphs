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
#   make doc            build docs/hat_layout_findings.pdf
#   make env            create/update the conda environment only
#   make clean-env      delete the conda environment
#
# The conda environment (environment.yml) and vendored three.js are built on
# demand and cached; the environment is updated whenever environment.yml
# changes.  If no conda is found, Miniforge is installed into ~/miniforge3.

ENV_NAME   := woolygraphs
MINIFORGE  := $(HOME)/miniforge3
CONDA      := $(or $(shell command -v conda 2>/dev/null),$(MINIFORGE)/bin/conda)
CONDA_BASE := $(or $(shell $(CONDA) info --base 2>/dev/null),$(MINIFORGE))
ENV        := $(CONDA_BASE)/envs/$(ENV_NAME)
ENV_STAMP  := $(ENV)/.woolygraphs-env-stamp
PY      := $(ENV)/bin/python
XLSX    := patterns/Necker_Birds_Hat.xlsx
CHART   := patterns/small_cubes.csv
LAYOUT  := web/data/small_cubes_layout.json
THREE   := web/lib/three.module.js
PORT    := 8765
REPEATS := 4
# Per-chart repeat count (the shaping in each CSV is drawn for one value).
REPEATS_alt_cubes := 6
CHART_REPEATS = $(or $(REPEATS_$(1)),$(REPEATS))
HGAUGE  := 8.75
VGAUGE  := 13

.PHONY: small_cubes alt_cubes open serve layout layouts chart charts test doc clean env clean-env

SERVE = $(PY) tools/serve_viewer.py --port $(PORT) --chart "$(1)" \
	    --repeats $(2) --horizontal-gauge $(HGAUGE) --vertical-gauge $(VGAUGE)
OPENER := $(if $(filter Darwin,$(shell uname -s)),open,xdg-open)
BROWSE = ( sleep 1 && $(OPENER) "http://localhost:$(PORT)/" >/dev/null 2>&1 ) &

small_cubes: $(THREE) | $(ENV_STAMP)
	@$(BROWSE)
	@$(call SERVE,$(CHART),$(call CHART_REPEATS,small_cubes))

alt_cubes: edit-alt_cubes

# make edit-small_cubes -> patterns/small_cubes.csv (falls back to .json)
edit-%: $(THREE) | $(ENV_STAMP)
	@f=patterns/$*.csv; [ -f "$$f" ] || f=patterns/$*.json; \
	  [ -f "$$f" ] || { echo "no patterns/$*.csv or .json"; exit 1; }; \
	  $(BROWSE) $(call SERVE,$$f,$(call CHART_REPEATS,$*))

# make open FILE=web/data/small_cubes_layout.json
open: $(THREE) | $(ENV_STAMP)
	@[ -n "$(FILE)" ] || { echo "usage: make open FILE=path/to/chart.csv|layout.json"; exit 1; }
	@$(BROWSE)
	@$(call SERVE,$(FILE),$(REPEATS))

serve: $(THREE) | $(ENV_STAMP)
	@$(call SERVE,$(CHART),$(call CHART_REPEATS,small_cubes))

env: $(ENV_STAMP)

$(ENV_STAMP): environment.yml | $(CONDA)
	@if [ -d "$(ENV)/conda-meta" ]; then \
	  echo "updating conda env $(ENV)"; \
	  $(CONDA) env update -p "$(ENV)" -f environment.yml --prune; \
	else \
	  echo "creating conda env $(ENV)"; \
	  $(CONDA) env create -p "$(ENV)" -f environment.yml; \
	fi
	@touch $@

$(CONDA):
	@echo "conda not found; installing Miniforge into $(MINIFORGE)"
	curl -fsSL -o /tmp/miniforge-$$$$.sh \
	    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$$(uname -s)-$$(uname -m).sh" \
	  && bash /tmp/miniforge-$$$$.sh -b -p "$(MINIFORGE)"; \
	  st=$$?; rm -f /tmp/miniforge-$$$$.sh; exit $$st

clean-env:
	$(CONDA) env remove -p "$(ENV)" -y

# The checked-in charts are the editable source of truth; re-extract from
# the workbook only on request.
chart: | $(ENV_STAMP)
	$(PY) tools/extract_chart.py $(XLSX) Small_Cubes patterns/small_cubes.csv

charts: chart | $(ENV_STAMP)
	$(PY) tools/extract_chart.py $(XLSX) Alt_Cubes patterns/alt_cubes.csv \
	    --first-col D --last-col AQ --last-row 70 --implicit-decreases

layout: $(LAYOUT)

layouts: $(patsubst patterns/%.csv,web/data/%_layout.json,$(wildcard patterns/*.csv))

web/data/%_layout.json: patterns/%.csv tools/spiral_layout.py tools/chart.py | $(ENV_STAMP)
	$(PY) tools/spiral_layout.py $< $@ --repeats $(call CHART_REPEATS,$*) \
	    --horizontal-gauge $(HGAUGE) --vertical-gauge $(VGAUGE)

$(THREE):
	mkdir -p web/lib
	curl -fsSL https://unpkg.com/three@0.160.0/build/three.module.js -o $@

doc: docs/hat_layout_findings.pdf

docs/%.pdf: docs/%.tex
	@command -v pdflatex >/dev/null || { echo "pdflatex not found; install TeX Live (e.g. sudo apt install texlive-latex-extra)"; exit 1; }
	cd docs && pdflatex -interaction=nonstopmode -halt-on-error $*.tex >/dev/null \
	    && pdflatex -interaction=nonstopmode -halt-on-error $*.tex >/dev/null
	@rm -f docs/$*.aux docs/$*.log docs/$*.out
	@echo "built $@"

test: | $(ENV_STAMP)
	$(PY) -m pytest -q tests

clean:
	rm -f $(LAYOUT)
