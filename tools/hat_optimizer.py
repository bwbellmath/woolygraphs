#!/usr/bin/env python
"""Interactive smoothing optimizer for a spiral hat layout.

Loads the layout JSON bundle produced by spiral_layout.py and refines
stitch positions with Adam against three losses:

1. gauge:      every left-right edge should be exactly 1/horizontal_gauge
               long and every up-down edge 1/vertical_gauge (squared
               relative error, so both gauges weigh equally).
2. inflate:    a uniform 1/r repulsion of every stitch from the centroid,
               which keeps the surface from collapsing inward while the
               edge springs pull it taut.
3. smooth:     at each vertex with a full [left, right, down, up] ring,
               the solid angle subtended by the fan of its neighbors
               (Van Oosterom-Strackee, batched); the loss penalizes the
               squared difference between a vertex's solid angle and the
               mean over its neighbors', encouraging locally uniform
               curvature.
"""

import json

import torch


def batched_solid_angle(a, b, c):
    """Solid angle of triangles (a_i, b_i, c_i) seen from the origin.

    a, b, c: (M, 3) unit vectors. Van Oosterom-Strackee, vectorized.
    """
    num = (a * torch.cross(b, c, dim=1)).sum(dim=1)
    den = (1.0 + (a * b).sum(dim=1) + (b * c).sum(dim=1)
           + (c * a).sum(dim=1))
    return 2.0 * torch.atan2(num, den)


class HatOptimizer:
    def __init__(self, bundle, lr=1e-3, device="cpu",
                 w_gauge=1.0, w_inflate=0.02, w_smooth=0.1):
        self.weights = {"gauge": w_gauge, "inflate": w_inflate,
                        "smooth": w_smooth}
        self.pos0 = torch.tensor(bundle["positions"], dtype=torch.float32,
                                 device=device)
        self.pos = self.pos0.clone().requires_grad_(True)
        self.lr = lr

        nbr = torch.tensor(bundle["neighbors"], dtype=torch.long,
                           device=device)  # (N, 4): left, right, down, up
        self.neighbors = nbr

        # Edge lists with per-edge rest lengths (each undirected edge
        # appears once: v -> right, v -> up).
        idx = torch.arange(nbr.shape[0], device=device)
        h = nbr[:, 1] >= 0
        v = nbr[:, 3] >= 0
        self.edges = torch.cat([
            torch.stack([idx[h], nbr[h, 1]], dim=1),
            torch.stack([idx[v], nbr[v, 3]], dim=1)])
        self.rest = torch.cat([
            torch.full((int(h.sum()),), 1.0 / bundle["horizontal_gauge"]),
            torch.full((int(v.sum()),), 1.0 / bundle["vertical_gauge"])
        ]).to(device)

        # Vertices with a complete neighbor ring, for the smoothness term.
        self.full_ring = (nbr >= 0).all(dim=1)

        # Anchored stitches never move (see module docstring).
        anchor = bundle.get("anchor_flag") or [False] * nbr.shape[0]
        self.anchor = torch.tensor(anchor, dtype=torch.bool, device=device)
        self.pos.register_hook(
            lambda g: g.masked_fill(self.anchor.unsqueeze(1), 0.0))
        self.history = []
        self._opt = torch.optim.Adam([self.pos], lr=lr)

    def losses(self):
        p = self.pos
        out = {}

        d = p[self.edges[:, 0]] - p[self.edges[:, 1]]
        length = torch.norm(d, dim=1)
        out["gauge"] = ((length / self.rest - 1.0) ** 2).mean()

        center = p.detach().mean(dim=0)
        r = torch.norm(p - center, dim=1)
        out["inflate"] = (1.0 / (r + 1e-3)).mean()

        omega = self.solid_angles()
        nbr = self.neighbors[self.full_ring]  # (M, 4)
        # Mean solid angle over the neighbors that themselves have a
        # defined solid angle.
        nbr_valid = (nbr >= 0) & self.full_ring[nbr.clamp(min=0)]
        nbr_omega = omega[nbr.clamp(min=0)] * nbr_valid
        counts = nbr_valid.sum(dim=1)
        has_nbr = counts > 0
        mean_nbr = nbr_omega.sum(dim=1)[has_nbr] / counts[has_nbr]
        out["smooth"] = ((omega[self.full_ring][has_nbr] - mean_nbr) ** 2).mean()
        return out

    def solid_angles(self):
        """Per-vertex solid angle of the neighbor fan; 0 where undefined."""
        p = self.pos
        mask = self.full_ring
        v = p[mask]
        left, right, down, up = (p[self.neighbors[mask, k]] for k in range(4))
        unit = lambda x: torch.nn.functional.normalize(x - v, dim=1, eps=1e-8)
        # Counterclockwise fan right -> up -> left -> down, split into
        # two triangles sharing the (right, left) diagonal. Each near-
        # planar half sits at the +-pi branch cut of atan2 (a flat fan
        # subtends exactly 2*pi), so take magnitudes per triangle to keep
        # omega continuous around flat regions.
        r_, u_, l_, d_ = unit(right), unit(up), unit(left), unit(down)
        omega_fan = (batched_solid_angle(r_, u_, l_).abs()
                     + batched_solid_angle(r_, l_, d_).abs())
        omega = torch.zeros(p.shape[0], device=p.device)
        omega[mask] = omega_fan
        return omega

    def step(self, iterations=30):
        for _ in range(iterations):
            self._opt.zero_grad()
            parts = self.losses()
            total = sum(self.weights[k] * v for k, v in parts.items())
            total.backward()
            self._opt.step()
            self.history.append(
                {"total": float(total),
                 **{k: float(v) for k, v in parts.items()}})
        return self.history[-1]

    def set_params(self, lr=None, weights=None):
        if lr is not None:
            self.lr = lr
            for group in self._opt.param_groups:
                group["lr"] = lr
        if weights:
            self.weights.update({k: float(v) for k, v in weights.items()
                                 if k in self.weights})

    def reset(self):
        with torch.no_grad():
            self.pos.copy_(self.pos0)
        self._opt = torch.optim.Adam([self.pos], lr=self.lr)
        self.history = []


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("layout_json")
    ap.add_argument("--iterations", type=int, default=100)
    ap.add_argument("--lr", type=float, default=2e-3)
    args = ap.parse_args()

    with open(args.layout_json) as f:
        bundle = json.load(f)
    opt = HatOptimizer(bundle, lr=args.lr)
    first = None
    for i in range(0, args.iterations, 10):
        last = opt.step(10)
        first = first or opt.history[0]
        print(f"iter {i + 10:4d}: " + "  ".join(
            f"{k}={v:.5f}" for k, v in last.items()))
    print("start:      " + "  ".join(f"{k}={v:.5f}" for k, v in first.items()))


if __name__ == "__main__":
    main()
