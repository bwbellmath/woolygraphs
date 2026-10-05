#!/usr/bin/env python
"""Static file server for the hat editor plus a chart + smoothing API.

Serves web/ like `python -m http.server` and owns one EditorSession:
the chart being edited, the bundle compiled from it, and a background
smoothing job the viewer can start, watch, and stop.

  GET  /api/bundle    current compiled bundle plus {"chart": {...}}
  GET  /api/chart     {"cells", "width", "height", "name", "repeats",
                       "horizontal_gauge", "vertical_gauge", "path",
                       "dirty"}
  POST /api/chart     {"cells": [[...]], "repeats"?: int,
                       "shaping_row"?: int (1-based; null clears it),
                       "vertical_repeat"?: {"start", "end", "count"} (1-based
                           sheet rows, inclusive; null clears it),
                       "horizontal_gauge"?: st/in, "vertical_gauge"?: rnd/in}
      Repeats and gauge are stored on the chart (``# key: value`` lines
      in the saved CSV) and reapplied when it is loaded again.
      Replace the chart and recompile; return the new bundle (400 with
      {"error"} if it cannot be compiled). If only cell text changed
      (same stitch counts and neighbour graph) the current positions
      and optimizer state are kept. A structural change (stitches added
      or removed, rounds / columns inserted or deleted) patches the
      layout locally (layout_patch.py): surviving stitches keep their
      positions and new ones are placed between their neighbours. Only a
      change of repeats or gauge restarts from the helix.
  POST /api/layout/save
      Write the current positions (plus the chart) to the chart's
      layout sidecar, patterns/<name>.layout.json (or back into the
      JSON the session was opened from). A CSV opened later picks the
      sidecar up as its default layout while it still fits the chart.
  POST /api/chart/save  {"path"?: "patterns/x.csv"}
      Write the in-memory chart to its CSV (or a new path under the repo).
  POST /api/save_version
      Save the chart and the current layout under the next version of
      the chart's name (the last number in it incremented, or "_1"
      appended), e.g. patterns/hat_3.csv + patterns/hat_3.layout.json
      -> patterns/hat_4.csv + patterns/hat_4.layout.json.
  POST /api/export_tex  {"cells", "style": "words"|"symbols"|"color",
                         "repeats", "horizontal_gauge", "vertical_gauge",
                         "shaping_row", "fg", "bg", "name"}
      {"tex": "..."} the chart as a one-page LaTeX document
      (chart_tex.py); does not touch the session.
  POST /api/export_edges  {"name", "images": {"x.png": data URL, ...},
                           "stats", "mode", "log", "strain_scale", "gauge",
                           "repeats", "n_stitches", "clipped"}
      application/zip: <name>_edges/ with the Edges tab as a LaTeX
      section (edges_tex.py), adding the optimizer's iterations, weights
      and last losses; does not touch the session.
  GET  /api/files     {"files": [{"path", "kind"}]} charts (patterns/*.csv,
                      *.json) and layouts (web/data/*.json) under the repo
  POST /api/load      {"path": "..."} load a chart CSV or a layout JSON
                      from the repo; a layout's positions are kept when
                      they still match the recompiled chart
  POST /api/import    {"name": "x.csv", "text": "..."} or
                      {"name": "x.json", "data": {...}} - same, from an
                      uploaded file
  POST /api/optimize  {"iterations": 10000, "update_every": 500,
                       "lr": 0.001, "weights": {"gauge": 1.0, ...}}
      Start a job (409 if one is already running). Positions are
      snapshotted every update_every iterations for the viewer to poll.
  POST /api/stop      stop the running job after the current iteration
  POST /api/reset     stop any job and restore the initial layout
  GET  /api/state?version=N
      {"running", "iterations_total", "target", "last", "version",
       "error", "positions"} - positions only included when the server's
       snapshot version is newer than N, so idle polls stay small.

The optimizer session (including Adam momentum) persists across jobs,
so a new Optimize press continues from where the last one ended; a
chart edit starts a fresh one.
"""

import argparse
import json
import os
import re
import sys
import threading

import torch
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart import DEFAULT_HORIZONTAL_GAUGE, DEFAULT_VERTICAL_GAUGE, Chart, from_bundle, strip_trailing_blank  # noqa: E402
from chart_tex import chart_to_tex  # noqa: E402
from edges_tex import build_zip as edges_zip  # noqa: E402
from hat_optimizer import HatOptimizer  # noqa: E402
from layout_patch import align, patch_positions  # noqa: E402
from spiral_layout import build_bundle, describe  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


KEEP = object()   # set_chart: leave the chart's vertical repeat as it is


def snapshot(opt):
    return [[round(v, 5) for v in p] for p in opt.pos.detach().tolist()]


def base_name(stem):
    """Chart name without the ".layout" / "_layout" tails that saving a
    layout JSON as a chart (and exporting it again) piles up."""
    while True:
        trimmed = re.sub(r"[._]layout$", "", stem.rstrip(" "))
        if trimmed == stem or not trimmed:
            return stem
        stem = trimmed


def next_version(stem):
    """hat_3 -> hat_4, v2_hat -> v3_hat (the last number), hat -> hat_1."""
    stem = base_name(stem)
    m = None
    for m in re.finditer(r"\d+", stem):
        pass
    if m is None:
        return f"{stem}_1"
    n = str(int(m.group()) + 1).zfill(len(m.group()))
    return stem[:m.start()] + n + stem[m.end():]


class EditorSession:
    """Chart + compiled bundle + optimizer job, guarded by one lock."""

    def __init__(self, chart_path, repeats, horizontal_gauge, vertical_gauge,
                 lr, extend_crown=False):
        self.lock = threading.Lock()
        self.chart_path = None
        self.chart = None
        self.repeats = repeats
        self.hg = horizontal_gauge
        self.vg = vertical_gauge
        # Command-line values: what a chart without its own settings gets.
        self.defaults = (repeats, horizontal_gauge, vertical_gauge)
        self.lr = lr
        self.extend_crown = extend_crown
        self.dirty = False
        self.opt = None
        self.thread = None
        self.stop = False
        self.running = False
        self.target = 0
        self.version = 0
        self.snapshot = None
        self.last = None
        self.error = None
        self.bundle = None
        self.load_file(chart_path)

    # ---- chart -----------------------------------------------------
    def _install(self, chart, bundle, repeats, path=None, dirty=False):
        """Commit a successfully compiled chart + bundle as the session."""
        self.chart = chart
        self.bundle = bundle
        self.repeats = repeats
        if path is not None:
            self.chart_path = Path(path)
        self.dirty = dirty
        self.opt = HatOptimizer(bundle, lr=self.lr)
        self.snapshot = snapshot(self.opt)
        self.version += 1
        self.last = None
        self.error = None
        self.target = 0
        print(describe(bundle))

    def compile(self):
        bundle = build_bundle(self.chart, self.repeats, self.hg, self.vg,
                              self.extend_crown)
        self._install(self.chart, bundle, self.repeats)

    @staticmethod
    def same_structure(a, b):
        """True when two bundles describe the same stitch graph, so a
        layout for one is valid for the other."""
        return (a["stitch_counts"] == b["stitch_counts"]
                and a["neighbors"] == b["neighbors"]
                and a["column_edges"] == b["column_edges"]
                and a["horizontal_gauge"] == b["horizontal_gauge"]
                and a["vertical_gauge"] == b["vertical_gauge"])

    def layout_path(self, path=None):
        path = Path(path or self.chart_path)
        if path.suffix.lower() == ".json":
            return path
        return path.with_suffix(".layout.json")

    def _apply_saved_layout(self, bundle, path):
        """Use the sidecar layout next to a chart file when it fits."""
        side = self.layout_path(path)
        if side == Path(path) or not side.exists():
            return
        try:
            with open(side) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        pos = data.get("positions")
        if (pos and len(pos) == bundle["n_stitches"]
                and self.same_structure(data, bundle)):
            bundle["positions"] = pos
            bundle["layout_source"] = str(side.relative_to(REPO))

    def _from_json(self, data, name):
        """Chart + repeats/gauge + carried-over positions from a JSON."""
        chart = from_bundle(data)
        chart.name = name
        src = data.get("chart", data) if isinstance(data, dict) else {}
        repeats = int(src.get("repeats", data.get("repeats", self.repeats)))
        self.hg = float(src.get("horizontal_gauge",
                                data.get("horizontal_gauge", self.hg)))
        self.vg = float(src.get("vertical_gauge",
                                data.get("vertical_gauge", self.vg)))
        bundle = build_bundle(chart, repeats, self.hg, self.vg,
                              self.extend_crown)
        pos = data.get("positions")
        if pos and len(pos) == bundle["n_stitches"]:
            bundle["positions"] = pos  # keep an optimized layout
            bundle["layout_source"] = f"{name}.json"
        return chart, bundle, repeats

    def _csv_settings(self, chart):
        """Repeats and gauge a CSV chart carries in its meta lines, else
        the command-line values. Sets the session gauge; returns repeats."""
        def num(key, cast, default):
            try:
                v = cast(chart.meta[key])
                return v if v > 0 else default
            except (KeyError, TypeError, ValueError):
                return default
        repeats, hg, vg = self.defaults
        self.hg = num("horizontal_gauge", float, hg)
        self.vg = num("vertical_gauge", float, vg)
        return num("repeats", int, repeats)

    def _stamp_settings(self, chart, repeats):
        """Record repeats and gauge on the chart so they save with it."""
        chart.meta["repeats"] = str(repeats)
        chart.meta["horizontal_gauge"] = f"{self.hg:g}"
        chart.meta["vertical_gauge"] = f"{self.vg:g}"

    def load_file(self, path):
        path = self.resolve(path)
        name = path.stem
        if path.suffix.lower() == ".json":
            with open(path) as f:
                data = json.load(f)
            chart, bundle, repeats = self._from_json(data, name)
        else:
            chart = Chart.read_csv(path, name=name)
            repeats = self._csv_settings(chart)
            bundle = build_bundle(chart, repeats, self.hg, self.vg,
                                  self.extend_crown)
            self._apply_saved_layout(bundle, path)
        self._install(chart, bundle, repeats, path=path)

    def import_data(self, name, text=None, data=None):
        stem = Path(name or "imported").stem
        if data is not None:
            chart, bundle, repeats = self._from_json(data, stem)
        else:
            chart = Chart.from_csv_text(text or "", name=stem)
            repeats = self._csv_settings(chart)
            bundle = build_bundle(chart, repeats, self.hg, self.vg,
                                  self.extend_crown)
        # Imported files live in patterns/ once saved.
        path = REPO / "patterns" / f"{stem}.csv"
        if data is None:
            self._apply_saved_layout(bundle, path)
        self._install(chart, bundle, repeats, path=path, dirty=True)

    def resolve(self, path):
        """Absolute path under the repo, or ValueError."""
        p = (REPO / path).resolve() if not Path(path).is_absolute() \
            else Path(path).resolve()
        if REPO not in p.parents:
            raise ValueError(f"{path} is outside the repository")
        return p

    def list_files(self):
        files = []
        for pattern, kind in (("patterns/*.csv", "chart"),
                              ("patterns/*.json", "chart"),
                              ("web/data/*.json", "layout")):
            for p in sorted(REPO.glob(pattern)):
                k = "layout" if p.name.endswith(".layout.json") else kind
                files.append({"path": str(p.relative_to(REPO)), "kind": k})
        return files

    def chart_payload(self):
        path = self.chart_path
        if path is not None and REPO in path.parents:
            path = path.relative_to(REPO)
        return {**self.chart.to_json(), "repeats": self.repeats,
                "horizontal_gauge": self.hg, "vertical_gauge": self.vg,
                "path": str(path), "dirty": self.dirty,
                "errors": self.chart.errors()}

    def bundle_payload(self):
        payload = {**self.bundle, "chart": self.chart_payload(),
                   "version": self.version}
        # Hand back the layout as it stands now, not the positions the
        # chart last compiled to, so a reload picks up optimizer progress.
        if self.snapshot is not None:
            payload["positions"] = self.snapshot
            if self.opt is not None and self.opt.history:
                payload["layout_source"] = (
                    f"optimizer, {len(self.opt.history)} iterations")
        return payload

    def set_chart(self, cells, repeats=None, shaping_row=None,
                  horizontal_gauge=None, vertical_gauge=None,
                  vertical_repeat=KEEP):
        cells = [[str(c).strip() for c in row] for row in cells]
        chart = Chart(strip_trailing_blank(cells), name=self.chart.name,
                      meta=self.chart.meta)
        chart.shaping_row = shaping_row
        if vertical_repeat is not KEEP:
            chart.vertical_repeat = vertical_repeat
        repeats = (max(1, min(int(repeats), 64)) if repeats is not None
                   else self.repeats)
        hg = float(horizontal_gauge) if horizontal_gauge else self.hg
        vg = float(vertical_gauge) if vertical_gauge else self.vg
        if hg <= 0 or vg <= 0:
            raise ValueError("gauge must be positive")
        # Compile before committing so a bad edit leaves the old state.
        bundle = build_bundle(chart, repeats, hg, vg, self.extend_crown)
        self.hg, self.vg = hg, vg
        self._stamp_settings(chart, repeats)
        if self.bundle is not None and self.same_structure(self.bundle, bundle):
            # Only text (colour / ops) changed: keep the layout and the
            # optimizer, just swap the per-stitch metadata.
            bundle["positions"] = snapshot(self.opt)
            if "layout_source" in self.bundle:
                bundle["layout_source"] = self.bundle["layout_source"]
            self.chart = chart
            self.bundle = bundle
            self.dirty = True
            self.version += 1
            return
        if self.bundle is not None and self._patch_layout(chart, bundle):
            return
        self._install(chart, bundle, repeats, dirty=True)

    def _patch_layout(self, chart, bundle):
        """Install a structurally changed chart keeping the layout: the
        current positions and the Reset baseline are both carried over
        with a minimal local change. False if they cannot be (repeats or
        gauge changed, or nothing in common)."""
        old = self.bundle
        if (old["horizontal_gauge"] != bundle["horizontal_gauge"]
                or old["vertical_gauge"] != bundle["vertical_gauge"]):
            return False
        if self._vertical_repeat_changed(self.chart, chart):
            return False
        # Match rounds as knit, so the copies of a vertical repeat line up.
        args = (old, self.chart.expanded_rows())
        new_rows = chart.expanded_rows()
        current = patch_positions(*args, snapshot(self.opt), bundle, new_rows)
        base = patch_positions(*args, self.opt.pos0.tolist(), bundle,
                               new_rows)
        if current is None or base is None:
            return False
        source = (f"optimizer, {len(self.opt.history)} iterations"
                  if self.opt.history
                  else old.get("layout_source", "initial helix"))
        if not source.endswith(" + chart edits"):
            source += " + chart edits"
        bundle["positions"] = base
        bundle["layout_source"] = source
        self._install(chart, bundle, bundle["repeats"], dirty=True)
        with torch.no_grad():
            self.opt.pos.copy_(torch.tensor(current, dtype=self.opt.pos.dtype))
        self.snapshot = current
        return True

    @staticmethod
    def _vertical_repeat_changed(old, new):
        """True when the vertical repeat changed in a way that reshapes
        the whole hat (a new count, or a region moved other than by rows
        inserted / deleted around it), which deserves a fresh layout
        like any repeat change."""
        a, b = old.vertical_repeat, new.vertical_repeat
        count = a[2] if a else 1
        if count != (b[2] if b else 1):
            return True
        if count == 1:
            return False   # worked once: the region changes nothing
        rmap = align([tuple(r) for r in old.rows], [tuple(r) for r in new.rows])
        return (rmap.get(a[0] - 1) != b[0] - 1
                or rmap.get(a[1] - 1) != b[1] - 1)

    def save_layout(self):
        target = self.layout_path()
        with torch.no_grad():
            self.opt.pos0.copy_(self.opt.pos)  # Reset now returns here
        self.bundle["positions"] = snapshot(self.opt)
        self.bundle["layout_source"] = str(target.relative_to(REPO))
        with open(target, "w") as f:
            json.dump({**self.bundle, "chart": self.chart_payload()}, f)
        return self.bundle["layout_source"]

    def save_version(self):
        """Chart + layout under the next free version of the name."""
        folder = self.chart_path.parent
        if folder.name != "patterns" or REPO not in folder.parents:
            folder = REPO / "patterns"
        stem = self.chart.name
        while True:
            stem = next_version(stem)
            csv_path = folder / f"{stem}.csv"
            if not (csv_path.exists()
                    or self.layout_path(csv_path).exists()):
                break
        self.save(csv_path)
        self.bundle["name"] = stem
        return self.save_layout()

    def save(self, path=None):
        if path:
            p = self.resolve(path)
            if p.suffix.lower() != ".csv":
                p = p.with_suffix(".csv")
            self.chart_path = p
            self.chart.name = p.stem
        self.chart_path.parent.mkdir(parents=True, exist_ok=True)
        self.chart.write_csv(self.chart_path)
        self.dirty = False

    # ---- optimizer job ----------------------------------------------
    def state_payload(self, client_version):
        payload = {
            "running": self.running,
            "iterations_total": len(self.opt.history) if self.opt else 0,
            "target": self.target,
            "last": self.last,
            "version": self.version,
            "error": self.error,
        }
        if self.version > client_version:
            payload["positions"] = self.snapshot
        return payload

    def run_job(self, opt, iterations, update_every):
        try:
            done = 0
            last = self.last
            while done < iterations and not self.stop:
                chunk = min(update_every, iterations - done)
                for _ in range(chunk):
                    if self.stop:
                        break
                    last = opt.step(1)
                    done += 1
                with self.lock:
                    if self.opt is opt:  # chart may have been replaced
                        self.snapshot = snapshot(opt)
                        self.last = last
                        self.version += 1
        except Exception as e:  # surface optimizer failures to the viewer
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.running = False

    def stop_job(self):
        self.stop = True
        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join()
        self.stop = False
        self.thread = None

    def start_job(self, req):
        iterations = max(1, min(int(req.get("iterations", 1000)), 1_000_000))
        update_every = max(1, min(int(req.get("update_every", 500)),
                                  iterations))
        self.opt.set_params(lr=req.get("lr"), weights=req.get("weights"),
                            scheme=req.get("scheme"))
        self.running = True
        self.stop = False
        self.error = None
        self.target = len(self.opt.history) + iterations
        self.thread = threading.Thread(
            target=self.run_job, args=(self.opt, iterations, update_every),
            daemon=True)
        self.thread.start()

    def reset(self):
        self.opt.reset()
        self.snapshot = snapshot(self.opt)
        self.last = None
        self.error = None
        self.target = 0
        self.version += 1


def make_handler(web_dir, session):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(web_dir), **kw)

        def log_message(self, fmt, *a):
            if not self.path.startswith(("/lib/", "/favicon", "/api/state")):
                super().log_message(fmt, *a)

        def end_headers(self):
            # Make the browser revalidate the page and its JS modules on
            # every load (a 304 when unchanged), so edits to web/ show up
            # on a plain reload instead of running a cached copy.
            if not self.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        # "./app.js" -> "./app.js?v=<mtime>" in the page and its modules,
        # so a changed module gets a new URL and a browser can never pair
        # a fresh app.js with a stale cached chart.js.
        MODULE_REF = re.compile(r"""(["'])\./([\w./-]+\.js)\1""")

        def send_versioned(self, path):
            f = web_dir / (path.lstrip("/") or "index.html")
            if f.is_dir():
                f = f / "index.html"
            if not f.is_file() or web_dir.resolve() not in f.resolve().parents:
                return super().do_GET()

            def stamp(m):
                dep = f.parent / m.group(2)
                if not dep.is_file():
                    return m.group(0)
                q = m.group(1)
                return f"{q}./{m.group(2)}?v={int(dep.stat().st_mtime)}{q}"

            body = self.MODULE_REF.sub(stamp, f.read_text()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8"
                             if f.suffix == ".html" else "text/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_bytes(self, body, content_type, filename):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition",
                             f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                if url.path == "/" or url.path.endswith((".html", ".js")):
                    return self.send_versioned(url.path)
                return super().do_GET()
            with session.lock:
                if url.path == "/api/state":
                    client_version = int(
                        parse_qs(url.query).get("version", ["0"])[0])
                    return self.send_json(session.state_payload(client_version))
                if url.path == "/api/bundle":
                    return self.send_json(session.bundle_payload())
                if url.path == "/api/chart":
                    return self.send_json(session.chart_payload())
                if url.path == "/api/files":
                    return self.send_json({"files": session.list_files()})
            self.send_json({"error": "unknown endpoint"}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"error": "bad json"}, 400)

            if self.path == "/api/chart":
                session.stop_job()
                with session.lock:
                    try:
                        session.set_chart(req.get("cells") or [],
                                          req.get("repeats"),
                                          req.get("shaping_row"),
                                          req.get("horizontal_gauge"),
                                          req.get("vertical_gauge"),
                                          req.get("vertical_repeat", KEEP))
                    except (ValueError, IndexError, TypeError) as e:
                        return self.send_json({"error": str(e)}, 400)
                    return self.send_json(session.bundle_payload())

            if self.path == "/api/chart/save":
                with session.lock:
                    try:
                        session.save(req.get("path"))
                    except (ValueError, OSError) as e:
                        return self.send_json({"error": str(e)}, 400)
                    return self.send_json(session.chart_payload())

            if self.path == "/api/export_tex":
                try:
                    cells = [[str(c).strip() for c in row]
                             for row in req.get("cells") or []]
                    chart = Chart(strip_trailing_blank(cells),
                                  name=req.get("name") or "chart")
                    chart.shaping_row = req.get("shaping_row")
                    chart.vertical_repeat = req.get("vertical_repeat")
                    tex = chart_to_tex(
                        chart, req.get("style", "color"),
                        repeats=req.get("repeats"),
                        horizontal_gauge=float(req.get("horizontal_gauge")
                                               or DEFAULT_HORIZONTAL_GAUGE),
                        vertical_gauge=float(req.get("vertical_gauge")
                                             or DEFAULT_VERTICAL_GAUGE),
                        fg=req.get("fg") or "#2f76c4",
                        bg=req.get("bg") or "#e9e5da")
                except (ValueError, TypeError) as e:
                    return self.send_json({"error": str(e)}, 400)
                return self.send_json({"tex": tex})

            if self.path == "/api/export_edges":
                with session.lock:
                    opt = session.opt
                    req["optimizer"] = {
                        "iterations": len(opt.history) if opt else 0,
                        "weights": dict(opt.weights) if opt else None,
                        "scheme": opt.scheme if opt else None,
                        "lr": opt.lr if opt else None,
                        "last": opt.history[-1] if opt and opt.history else None,
                    }
                try:
                    body = edges_zip(req)
                except (ValueError, TypeError) as e:
                    return self.send_json({"error": str(e)}, 400)
                name = (req.get("name") or "hat").replace('"', "")
                return self.send_bytes(body, "application/zip",
                                       f"{name}_edges.zip")

            if self.path == "/api/save_version":
                with session.lock:
                    try:
                        src = session.save_version()
                    except (ValueError, OSError) as e:
                        return self.send_json({"error": str(e)}, 400)
                    return self.send_json({**session.chart_payload(),
                                           "layout_source": src})

            if self.path in ("/api/load", "/api/import"):
                session.stop_job()
                with session.lock:
                    try:
                        if self.path == "/api/load":
                            session.load_file(req.get("path") or "")
                        else:
                            session.import_data(req.get("name"),
                                                req.get("text"),
                                                req.get("data"))
                    except (ValueError, KeyError, IndexError, TypeError,
                            OSError, json.JSONDecodeError) as e:
                        return self.send_json(
                            {"error": f"{type(e).__name__}: {e}"}, 400)
                    return self.send_json(session.bundle_payload())

            if self.path == "/api/layout/save":
                with session.lock:
                    try:
                        src = session.save_layout()
                    except OSError as e:
                        return self.send_json({"error": str(e)}, 400)
                    return self.send_json({"layout_source": src,
                                           **session.state_payload(-1)})

            if self.path == "/api/stop":
                session.stop_job()
                with session.lock:
                    return self.send_json(session.state_payload(-1))

            if self.path == "/api/reset":
                session.stop_job()
                with session.lock:
                    session.reset()
                    return self.send_json(session.state_payload(-1))

            if self.path == "/api/optimize":
                with session.lock:
                    if session.running:
                        return self.send_json({"error": "already running"},
                                              409)
                    session.start_job(req)
                    return self.send_json(session.state_payload(0))

            self.send_json({"error": "unknown endpoint"}, 404)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--web", default=str(REPO / "web"))
    ap.add_argument("--chart", default=str(REPO / "patterns/small_cubes.csv"),
                    help="chart CSV or layout JSON to open")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--horizontal-gauge", type=float, default=DEFAULT_HORIZONTAL_GAUGE)
    ap.add_argument("--vertical-gauge", type=float, default=DEFAULT_VERTICAL_GAUGE)
    ap.add_argument("--extend-crown", action="store_true")
    ap.add_argument("--lr", type=float, default=1e-3)
    args = ap.parse_args()

    session = EditorSession(args.chart, args.repeats, args.horizontal_gauge,
                            args.vertical_gauge, args.lr, args.extend_crown)
    handler = make_handler(Path(args.web), session)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"editor + optimizer at http://localhost:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
