"""Tests for the implicit optimizer schemes (tools/implicit_flow.py)."""

import os
import sys

import pytest
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from chart import Chart  # noqa: E402
from hat_optimizer import HatOptimizer  # noqa: E402
from implicit_flow import SCHEMES, laplacian, pcg  # noqa: E402
from spiral_layout import build_bundle  # noqa: E402


def bundle():
    rows = [["f", "b"] * 6] * 6 + [["f", "", "b", "f-k2tog", "b", "f"] * 2] * 3
    return build_bundle(Chart(rows), repeats=3)


def test_pcg_solves_a_grounded_laplacian():
    edges = torch.tensor([[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]])
    w = torch.tensor([1.0, 2.0, 1.0, 3.0, 0.5], dtype=torch.float64)
    A = laplacian(4, edges, w)
    free = torch.tensor([[0.0], [1.0], [1.0], [1.0]], dtype=torch.float64)
    b = free * torch.randn(4, 3, dtype=torch.float64)
    diag = torch.ones(4, 1, dtype=torch.float64) * 4
    x, _ = pcg(lambda v: free * (A @ (free * v)), b, diag, tol=1e-12, maxit=50)
    dense = A.to_dense()[1:, 1:]
    assert torch.allclose(x[1:], torch.linalg.solve(dense, b[1:]), atol=1e-8)
    assert torch.all(x[0] == 0)


@pytest.mark.parametrize("scheme", ["local_global", "gauss_newton"])
def test_implicit_scheme_lowers_the_same_objective(scheme):
    b = bundle()
    opt = HatOptimizer(b, scheme=scheme)
    start = float(opt.total()[0])
    anchors = opt.pos.detach()[opt.anchor].clone()
    last = opt.step(8)
    assert last["total"] < 0.5 * start
    assert set(last) >= {"total", "gauge", "inflate", "smooth", "alpha", "cg"}
    # history is monotone: every step is line-searched on the objective
    totals = [h["total"] for h in opt.history]
    assert all(b <= a + 1e-9 for a, b in zip(totals, totals[1:]))
    assert torch.equal(opt.pos.detach()[opt.anchor], anchors)
    assert float(opt.total()[0]) == pytest.approx(last["total"], rel=1e-5)


def test_switching_schemes_and_reset():
    opt = HatOptimizer(bundle())
    opt.step(3)
    opt.set_params(scheme="local_global")
    opt.step(2)
    assert opt.scheme == "local_global" and len(opt.history) == 5
    opt.set_params(scheme="direct")
    opt.step(1)
    opt.reset()
    assert opt.history == [] and torch.equal(opt.pos.detach(), opt.pos0)
    with pytest.raises(ValueError):
        opt.set_params(scheme="newtonish")
    assert set(SCHEMES) == {"direct", "local_global", "gauss_newton"}
