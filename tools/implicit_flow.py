"""Implicit, graph-Laplacian solvers for the hat layout.

Same objective as HatOptimizer (gauge + inflate + smooth, same weights),
but each outer iteration solves one sparse system over the whole graph
instead of taking a small explicit gradient step, so a correction at one
end of the fabric reaches the other in one iteration. See
docs/better_flow.tex, sections 4 and 7.

local_global
    Stress majorization. The gauge loss mean((r/l - 1)^2) is exactly the
    edge stress 1/2 sum w_e (r_e - l_e)^2 with w_e = 2 lambda_gauge /
    (m l_e^2), and its local/global step (project every edge onto its
    rest-length sphere, then solve L_W X = B^T W P) is the same as
    solving L_W dX = -grad. Inflate and smooth ride along explicitly on
    the right-hand side:
        (L_W + mu L_0) dX = -grad E.
    L_W is constant, so only its diagonal (the preconditioner) is kept.

gauss_newton
    Levenberg-Marquardt with a graph-Sobolev damping term. The gauge and
    smooth residuals are linearized together (J by forward-mode autodiff,
    never formed); the edge part of J^T J is the framework stiffness
    matrix and the solid-angle part couples two-hop neighbours. Inflate
    is long-range and stays explicit:
        (2 J^T J + mu L_0 (x) I_3) dX = -grad E.

Both work in float64 (a float32 objective is too coarse for the line
search once steps get small), solve with Jacobi-preconditioned conjugate
gradients in torch (no scipy) to a loose inexact-Newton tolerance, hold
the cast-on round fixed (Dirichlet rows), backtrack on the true
objective, and adapt mu like Levenberg-Marquardt: less damping after a
full step, more after a cut-back one.
"""

import torch

SCHEMES = {
    "direct": "direct loss optimization (Adam)",
    "local_global": "local/global Laplacian solve (stress majorization)",
    "gauss_newton": "Gauss-Newton, Laplacian-damped (Levenberg-Marquardt)",
}


def laplacian(n, edges, w):
    """Weighted graph Laplacian B^T diag(w) B as a sparse matrix."""
    i, j = edges[:, 0], edges[:, 1]
    rows = torch.cat([i, j, i, j])
    cols = torch.cat([i, j, j, i])
    vals = torch.cat([w, w, -w, -w])
    return torch.sparse_coo_tensor(torch.stack([rows, cols]), vals,
                                   (n, n)).coalesce()


def degree(n, edges, w):
    return (torch.zeros(n, dtype=w.dtype).index_add(0, edges[:, 0], w)
            .index_add(0, edges[:, 1], w))


def pcg(matvec, b, diag, tol=1e-2, maxit=150):
    """Solve A x = b (A SPD on the support of b) by Jacobi-preconditioned
    CG, stopping when the preconditioned residual norm has dropped by
    tol (scale-free, so a few stiff rows cannot end it early). Returns
    (x, iterations)."""
    x = torch.zeros_like(b)
    r = b.clone()
    z = r / diag
    p = z.clone()
    rz = (r * z).sum()
    rz0 = rz
    if rz0 == 0:
        return x, 0
    for k in range(1, maxit + 1):
        ap = matvec(p)
        alpha = rz / (p * ap).sum()
        x += alpha * p
        r -= alpha * ap
        z = r / diag
        rz_new = (r * z).sum()
        if rz_new <= tol ** 2 * rz0:
            return x, k
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x, maxit


class _Implicit:
    def __init__(self, opt):
        self.opt = opt
        self.n = opt.pos.shape[0]
        self.free = (~opt.anchor).double().unsqueeze(1)  # (n, 1)
        self.edges = opt.edges
        self.m = self.edges.shape[0]
        self.rest = opt.rest.double()
        ones = torch.ones(self.m, dtype=torch.float64)
        self.L0 = laplacian(self.n, self.edges, ones)
        self.deg0 = degree(self.n, self.edges, ones).unsqueeze(1)

    def gradient(self):
        x = self.opt.pos.detach().double().requires_grad_(True)
        total, parts = self.opt.total(x)
        (g,) = torch.autograd.grad(total, x)
        return x.detach(), total.detach(), g * self.free

    def line_search(self, x0, e0, g, dx, tries=12):
        """Backtrack on the true objective (Armijo). Returns (alpha, parts)
        with alpha 0 if no step decreased it."""
        slope = float((g * dx).sum())
        alpha = 1.0
        with torch.no_grad():
            for _ in range(tries):
                total, parts = self.opt.total(x0 + alpha * dx)
                if float(total) <= float(e0) + 1e-4 * alpha * slope:
                    return alpha, total, parts
                alpha *= 0.5
            total, parts = self.opt.total(x0)
        return 0.0, total, parts

    def apply(self, x0, alpha, dx):
        with torch.no_grad():
            self.opt.pos.copy_((x0 + alpha * dx).to(self.opt.pos.dtype))

    def adapt(self, alpha, mu, base):
        """Levenberg-Marquardt damping update, kept within [1e-8, 1e4] x
        the mean edge stiffness."""
        mu = mu / 3 if alpha == 1.0 else mu * 4
        return min(max(mu, 1e-8 * base), 1e4 * base)


class LocalGlobal(_Implicit):
    def __init__(self, opt):
        super().__init__(opt)
        self.mu = None

    def step(self):
        x0, e0, g = self.gradient()
        w = 2.0 * self.opt.weights["gauge"] / (self.m * self.rest ** 2)
        base = float(w.mean())
        if self.mu is None:
            self.mu = 1e-2 * base
        A = laplacian(self.n, self.edges, w + self.mu)
        diag = degree(self.n, self.edges, w + self.mu).unsqueeze(1)
        dx, its = pcg(lambda v: self.free * (A @ (self.free * v)),
                      -g, diag)
        alpha, total, parts = self.line_search(x0, e0, g, dx)
        self.apply(x0, alpha, dx)
        self.mu = self.adapt(alpha, self.mu, base)
        return total, parts, {"alpha": alpha, "cg": its, "mu": self.mu}


class GaussNewton(_Implicit):
    def __init__(self, opt):
        super().__init__(opt)
        self.mu = None

    def residuals(self, x):
        o = self.opt
        rg = o.gauge_residual(x)
        rs = o.smooth_residual(x)
        parts = [(o.weights["gauge"] / rg.numel()) ** 0.5 * rg]
        if rs.numel():
            parts.append((o.weights["smooth"] / rs.numel()) ** 0.5 * rs)
        return torch.cat(parts)

    def step(self):
        x0, e0, g = self.gradient()
        o = self.opt
        # Jacobi preconditioner from the edge (framework stiffness) part:
        # each edge adds c_e u_e u_e^T to both endpoints' diagonal blocks.
        d = x0[self.edges[:, 0]] - x0[self.edges[:, 1]]
        u2 = (d / d.norm(dim=1, keepdim=True).clamp_min(1e-12)) ** 2
        c = 2.0 * o.weights["gauge"] / (self.m * self.rest ** 2)
        if self.mu is None:
            self.mu = 1e-2 * float(c.mean())
        edge_diag = (torch.zeros_like(x0).index_add(0, self.edges[:, 0], c[:, None] * u2)
                     .index_add(0, self.edges[:, 1], c[:, None] * u2))

        y, jvp = torch.func.linearize(self.residuals, x0)
        _, vjp = torch.func.vjp(self.residuals, x0)
        # diag(2 J^T J) by Hutchinson probes (E[(J^T z)^2] for random
        # signs z), so the solid-angle rows are scaled as well as edges.
        probes = 8
        hutch = sum(vjp(torch.randint(0, 2, y.shape, dtype=y.dtype) * 2 - 1)[0] ** 2
                    for _ in range(probes)) * (2.0 / probes)
        diag = torch.maximum(hutch, edge_diag) + self.mu * self.deg0 + 1e-12

        def matvec(v):
            v = self.free * v
            jtj = vjp(jvp(v))[0]
            return self.free * (2.0 * jtj + self.mu * (self.L0 @ v))

        # Truncated: each CG step costs a forward and a backward pass.
        dx, its = pcg(matvec, -g, diag, maxit=60)
        alpha, total, parts = self.line_search(x0, e0, g, dx)
        self.apply(x0, alpha, dx)
        self.mu = self.adapt(alpha, self.mu, float(c.mean()))
        return total, parts, {"alpha": alpha, "cg": its, "mu": self.mu}


SOLVERS = {"local_global": LocalGlobal, "gauss_newton": GaussNewton}
