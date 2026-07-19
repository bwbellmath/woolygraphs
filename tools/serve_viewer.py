#!/usr/bin/env python
"""Static file server for the hat viewer plus a smoothing API.

Serves web/ like `python -m http.server` and adds a background
optimization job the viewer can start, watch, and stop:

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
so a new Optimize press continues from where the last one ended.
"""

import argparse
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hat_optimizer import HatOptimizer

REPO = Path(__file__).resolve().parent.parent
LOCK = threading.Lock()
STATE = {
    "opt": None,
    "thread": None,
    "stop": False,
    "running": False,
    "target": 0,
    "version": 0,
    "snapshot": None,
    "last": None,
    "error": None,
}


def snapshot(opt):
    return [[round(v, 5) for v in p] for p in opt.pos.detach().tolist()]


def get_optimizer(data_path, lr):
    if STATE["opt"] is None:
        with open(data_path) as f:
            bundle = json.load(f)
        STATE["opt"] = HatOptimizer(bundle, lr=lr)
        STATE["snapshot"] = snapshot(STATE["opt"])
        STATE["version"] = 1
    return STATE["opt"]


def run_job(opt, iterations, update_every):
    try:
        done = 0
        last = STATE["last"]
        while done < iterations and not STATE["stop"]:
            chunk = min(update_every, iterations - done)
            for _ in range(chunk):
                if STATE["stop"]:
                    break
                last = opt.step(1)
                done += 1
            with LOCK:
                STATE["snapshot"] = snapshot(opt)
                STATE["last"] = last
                STATE["version"] += 1
    except Exception as e:  # surface optimizer failures to the viewer
        STATE["error"] = f"{type(e).__name__}: {e}"
    finally:
        STATE["running"] = False


def stop_job():
    STATE["stop"] = True
    thread = STATE["thread"]
    if thread is not None and thread.is_alive():
        thread.join()
    STATE["stop"] = False
    STATE["thread"] = None


def make_handler(web_dir, data_path, lr):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(web_dir), **kw)

        def log_message(self, fmt, *a):
            if not self.path.startswith(("/lib/", "/favicon", "/api/state")):
                super().log_message(fmt, *a)

        def send_json(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def state_payload(self, client_version):
            opt = STATE["opt"]
            payload = {
                "running": STATE["running"],
                "iterations_total": len(opt.history) if opt else 0,
                "target": STATE["target"],
                "last": STATE["last"],
                "version": STATE["version"],
                "error": STATE["error"],
            }
            if STATE["version"] > client_version:
                payload["positions"] = STATE["snapshot"]
            return payload

        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/api/state":
                return super().do_GET()
            with LOCK:
                get_optimizer(data_path, lr)
                client_version = int(
                    parse_qs(url.query).get("version", ["0"])[0])
                self.send_json(self.state_payload(client_version))

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"error": "bad json"}, 400)

            if self.path == "/api/stop":
                stop_job()
                with LOCK:
                    return self.send_json(self.state_payload(-1))

            if self.path == "/api/reset":
                stop_job()
                with LOCK:
                    opt = get_optimizer(data_path, lr)
                    opt.reset()
                    STATE.update(snapshot=snapshot(opt), last=None,
                                 error=None, target=0,
                                 version=STATE["version"] + 1)
                    return self.send_json(self.state_payload(-1))

            if self.path == "/api/optimize":
                with LOCK:
                    if STATE["running"]:
                        return self.send_json({"error": "already running"},
                                              409)
                    opt = get_optimizer(data_path, lr)
                    iterations = max(1, min(int(req.get("iterations", 1000)),
                                            1_000_000))
                    update_every = max(1, min(int(req.get("update_every",
                                                          500)), iterations))
                    opt.set_params(lr=req.get("lr"),
                                   weights=req.get("weights"))
                    STATE.update(running=True, stop=False, error=None,
                                 target=len(opt.history) + iterations)
                    STATE["thread"] = threading.Thread(
                        target=run_job, args=(opt, iterations, update_every),
                        daemon=True)
                    STATE["thread"].start()
                    return self.send_json(self.state_payload(0))

            self.send_json({"error": "unknown endpoint"}, 404)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--web", default=str(REPO / "web"))
    ap.add_argument("--data",
                    default=str(REPO / "web/data/small_cubes_layout.json"))
    ap.add_argument("--lr", type=float, default=1e-3)
    args = ap.parse_args()

    handler = make_handler(Path(args.web), Path(args.data), args.lr)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"viewer + optimizer at http://localhost:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
