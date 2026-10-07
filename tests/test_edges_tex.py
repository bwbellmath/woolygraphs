"""Tests for tools/edges_tex.py (Edges tab LaTeX export)."""

import io
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from edges_tex import build_zip, objective_tex, stats_tex  # noqa: E402

# 1 x 1 PNG
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
       "DUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
STATS = [
    {"name": "horizontal", "short": "ring", "color": "#3987e5", "n": 8448,
     "rest": 0.1143, "mean": 0.1150, "median": 0.1149, "std": 0.002},
    {"name": "vertical", "short": "column", "color": "#d95926", "n": 8000,
     "rest": 0.0769, "mean": 0.0760, "median": 0.0761, "std": 0.003},
    {"name": "shaping", "short": "inc/dec", "color": "#199e70", "n": 0},
]


def report(**kw):
    return {"name": "my hat_3", "images": {
                "histogram.png": PNG, "deviation.png": PNG, "view.png": PNG,
                "edges_tab.png": PNG, "histogram.svg": "<svg/>",
                "../evil.png": PNG},
            "stats": STATS, "mode": "length", "log": True, "clipped": 12,
            "strain_scale": 0.25, "gauge": {"horizontal": 8.75, "vertical": 13},
            "repeats": 4, "n_stitches": 8448,
            "optimizer": {"iterations": 1000, "lr": 0.001,
                          "weights": {"gauge": 1.0, "inflate": 0.02, "smooth": 0.1},
                          "last": {"total": 0.5, "gauge": 0.01,
                                   "inflate": 0.4, "smooth": 0.02}},
            **kw}


def test_zip_layout_and_contents():
    z = zipfile.ZipFile(io.BytesIO(build_zip(report())))
    names = set(z.namelist())
    d = "my_hat_3_edges/"
    assert {d + f for f in ("edges.tex", "objective.tex", "stats.tex",
                            "edges_report.tex", "histogram.png",
                            "view.png", "histogram.svg")} <= names
    assert not any("evil" in n for n in names)
    assert z.read(d + "view.png").startswith(b"\x89PNG")
    edges = z.read(d + "edges.tex").decode()
    assert r"\providecommand{\edgesdir}{my_hat_3_edges/}" in edges
    assert r"\includegraphics[width=\linewidth]{\edgesdir histogram.png}" in edges
    assert "1,000 iterations" in edges and "12 edges fall outside" in edges
    stats = z.read(d + "stats.tex").decode()
    assert "horizontal" in stats and "shaping" not in stats   # empty series
    assert r"+0.61\%" in stats


def test_objective_states_all_three_terms_and_weights():
    tex = objective_tex({"gauge": 1.0, "inflate": 0.02, "smooth": 0.1}, 0.001)
    for term in ("gauge", "inflate", "smooth"):
        assert rf"\lambda_{{\mathrm{{{term}}}}}\,\mathcal{{L}}_{{\mathrm{{{term}}}}}" in tex
    assert r"$\lambda_{\mathrm{inflate}}=0.02$" in tex and r"\eta=0.001" in tex
    assert r"\operatorname{atan2}" in tex
    assert "lambda" not in objective_tex().split(r"\end{equation}")[1]


def test_stats_without_rest_length():
    assert "--" in stats_tex([{"name": "x", "n": 1, "rest": None, "mean": 1}])


@pytest.mark.skipif(shutil.which("pdflatex") is None,
                    reason="pdflatex not installed")
def test_report_compiles(tmp_path):
    zipfile.ZipFile(io.BytesIO(build_zip(report()))).extractall(tmp_path)
    folder = tmp_path / "my_hat_3_edges"
    run = subprocess.run(["pdflatex", "-interaction=nonstopmode",
                          "-halt-on-error", "edges_report.tex"],
                         cwd=folder, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-2000:]
    # and as a drop-in section from the folder above
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\\usepackage{graphicx,booktabs,amsmath,xcolor}"
        "\\begin{document}\\input{my_hat_3_edges/edges.tex}\\end{document}\n")
    run = subprocess.run(["pdflatex", "-interaction=nonstopmode",
                          "-halt-on-error", "paper.tex"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-2000:]


def test_unoptimized_layout_reports_editor_settings():
    r = report(optimizer={"iterations": 0, "weights": {"gauge": 9}},
               settings={"lr": 0.002, "weights": {"gauge": 1.0, "inflate": 0.05,
                                                  "smooth": 0.1}})
    z = zipfile.ZipFile(io.BytesIO(build_zip(r)))
    obj = z.read("my_hat_3_edges/objective.tex").decode()
    assert "has not been optimized" in obj and r"\lambda_{\mathrm{inflate}}=0.05" in obj
    assert "=9$" not in obj


def test_objective_names_the_scheme():
    lg = objective_tex({"gauge": 1, "inflate": 0.02, "smooth": 0.1}, 0.001,
                       scheme="local_global")
    assert r"(L_W+\mu L_0)" in lg and r"\eta" not in lg
    assert "with Adam" in objective_tex(scheme="direct")
