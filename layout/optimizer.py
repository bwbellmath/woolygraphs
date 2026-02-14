"""
WoolyGraphs Phase 2: Physics-Based Optimization

Refines the initial layout from Phase 1 by optimizing stitch positions
and normal vectors using gradient descent (Adam/SGD/L-BFGS).

Loss terms:
  1. Edge length (piecewise elastic/plastic yarn energy)
  2. Normal unit-length (keep normals on unit sphere)
  3. Normal coherence (neighboring normals agree)
  4. Stitch-type offset (micro-displacement preferences)
  5. Out-of-plane flatness (neighbors in fabric plane)
  6. In-plane angle (h/v edges at 90° in fabric plane)
  7. Repulsion (topology-aware inverse-square)

Plus blocked-flat mode extras:
  8. Z-plane loss (pin to z=0)
  9. Angular uniformity (even edge spacing)
"""

from dataclasses import dataclass, field
import numpy as np
import torch
import torch.optim as optim

from layout.stitch_instance import LayoutGraph
from layout.forces import (
    YarnForceModel,
    RepulsionModel,
    normal_coherence_loss,
    normal_unit_loss,
    offset_loss,
    out_of_plane_loss,
    in_plane_angle_loss,
)


@dataclass
class OptimizerConfig:
    """Configuration for Phase 2 optimization."""

    # Optimizer
    optimizer: str = "adam"           # "adam" | "sgd" | "lbfgs"
    learning_rate: float = 0.01
    num_iterations: int = 2000
    convergence_tol: float = 1e-5    # stop when |dL/dt| < tol
    log_interval: int = 100

    # Loss weights (all configurable per knit object)
    lambda_edge: float = 10.0
    lambda_normal: float = 1.0
    lambda_coherence: float = 5.0     # strong: keeps normals aligned -> flat fabric
    lambda_offset: float = 0.0        # disabled for now; centroid biased at boundaries
    lambda_flat: float = 5.0          # out-of-plane: neighbors in fabric plane
    lambda_angle: float = 5.0         # in-plane: h/v edges at 90° in fabric plane
    lambda_repulsion: float = 0.0     # disabled: angular coherence handles separation

    # Edge force parameters
    elastic_limit: float = 0.4
    k_elastic: float = 0.1
    k_plastic: float = 10.0
    step_penalty: float = 5.0

    # Repulsion
    repulsion_powers: int = 3
    repulsion_strength: float = 50.0

    # Normal projection
    project_normals: bool = True

    # Physical domain
    domain: str = "free"             # "free" | "gravity" | "blocked_flat"
    gravity_strength: float = 0.0

    # Blocked-flat mode parameters
    blocked_flat_plane_z: float = 0.0
    lambda_z: float = 100.0
    lambda_angular_uniformity: float = 1.0

    @classmethod
    def blocked_flat_preset(cls) -> "OptimizerConfig":
        """Config for blocking a shawl / lace flat."""
        cfg = cls()
        cfg.domain = "blocked_flat"
        cfg.lambda_edge = 0.5
        cfg.lambda_coherence = 5.0
        cfg.lambda_flat = 10.0
        cfg.lambda_angle = 10.0
        cfg.lambda_z = 100.0
        cfg.lambda_angular_uniformity = 1.0
        return cfg


class LayoutOptimizer:
    """
    Phase 2 optimizer. Takes a LayoutGraph from Phase 1 and refines
    positions + normals using gradient descent.
    """

    def __init__(self, layout_graph: LayoutGraph, config: OptimizerConfig = None):
        self.graph = layout_graph
        self.config = config or OptimizerConfig()

        N = layout_graph.num_stitches

        # Initialize positions and normals as optimizable tensors
        pos_np = layout_graph.positions_array()
        norm_np = layout_graph.normals_array()

        self.positions = torch.tensor(pos_np, dtype=torch.float32, requires_grad=True)
        self.normals = torch.tensor(norm_np, dtype=torch.float32, requires_grad=True)

        # Edge data as tensors
        edges = layout_graph.edge_indices()
        self.edge_indices = torch.tensor(edges, dtype=torch.long)
        self.rest_lengths = torch.tensor(
            layout_graph.edge_rest_lengths(), dtype=torch.float32
        )

        # Offsets
        self.stitch_offsets = torch.tensor(
            layout_graph.offsets_array(), dtype=torch.float32
        )

        # Neighbor indices (for offset loss)
        self.neighbor_indices_list = layout_graph.neighbor_indices()

        # Adjacency matrix for repulsion
        adj = layout_graph.adjacency_matrix()

        # Force models
        self.force_model = YarnForceModel(
            elastic_limit=self.config.elastic_limit,
            k_elastic=self.config.k_elastic,
            k_plastic=self.config.k_plastic,
            step_penalty=self.config.step_penalty,
        )

        self.repulsion_model = RepulsionModel(
            adj,
            num_powers=self.config.repulsion_powers,
            strength=self.config.repulsion_strength,
        )

        # Build h/v neighbor lists for angle losses
        orientations = layout_graph.edge_orientations()
        self.h_neighbors = [[] for _ in range(N)]
        self.v_neighbors = [[] for _ in range(N)]
        for idx in range(edges.shape[0]):
            src, tgt = int(edges[idx, 0]), int(edges[idx, 1])
            if orientations[idx] == 'h':
                self.h_neighbors[src].append(tgt)
                self.h_neighbors[tgt].append(src)
            else:
                self.v_neighbors[src].append(tgt)
                self.v_neighbors[tgt].append(src)

        # Setup optimizer
        params = [self.positions, self.normals]
        if self.config.optimizer == "adam":
            self.optim = optim.Adam(params, lr=self.config.learning_rate)
        elif self.config.optimizer == "sgd":
            self.optim = optim.SGD(params, lr=self.config.learning_rate, momentum=0.9)
        elif self.config.optimizer == "lbfgs":
            self.optim = optim.LBFGS(params, lr=self.config.learning_rate)
        else:
            raise ValueError(f"Unknown optimizer: {self.config.optimizer}")

        # History
        self.loss_history = []
        self.component_history = []

        print(f"LayoutOptimizer initialized:")
        print(f"  Stitches: {N}")
        print(f"  Edges: {self.edge_indices.shape[0]}")
        print(f"  Repulsion pairs: {len(self.repulsion_model.repulsion_pairs)}")
        print(f"  Domain: {self.config.domain}")
        print(f"  Optimizer: {self.config.optimizer}, lr={self.config.learning_rate}")

    def compute_loss(self):
        """
        Evaluate all loss terms.

        Returns:
            (total_loss, component_dict)
        """
        cfg = self.config
        components = {}

        # 1. Edge length loss
        edge_loss = self.force_model.total_edge_energy_vectorized(
            self.positions, self.edge_indices, self.rest_lengths
        )
        components["edge"] = edge_loss.item()

        # 2. Normal unit-length loss
        norm_loss = normal_unit_loss(self.normals)
        components["normal"] = norm_loss.item()

        # 3. Normal coherence loss
        coh_loss = normal_coherence_loss(self.normals, self.edge_indices)
        components["coherence"] = coh_loss.item()

        # 4. Offset loss
        off_loss = offset_loss(
            self.positions, self.normals, self.edge_indices,
            self.stitch_offsets, self.neighbor_indices_list
        )
        components["offset"] = off_loss.item()

        # 5. Out-of-plane flatness
        flat_loss = out_of_plane_loss(
            self.positions, self.normals, self.neighbor_indices_list
        )
        components["flatness"] = flat_loss.item()

        # 6. In-plane angle regularity
        angle_loss = in_plane_angle_loss(
            self.positions, self.normals,
            self.h_neighbors, self.v_neighbors
        )
        components["angle"] = angle_loss.item()

        # 7. Repulsion loss
        rep_loss = self.repulsion_model.repulsion_energy(self.positions)
        components["repulsion"] = rep_loss.item()

        # Total
        total = (
            cfg.lambda_edge * edge_loss
            + cfg.lambda_normal * norm_loss
            + cfg.lambda_coherence * coh_loss
            + cfg.lambda_offset * off_loss
            + cfg.lambda_flat * flat_loss
            + cfg.lambda_angle * angle_loss
            + cfg.lambda_repulsion * rep_loss
        )

        # Domain-specific terms
        if cfg.domain == "blocked_flat":
            z_loss = self._z_plane_loss()
            components["z_plane"] = z_loss.item()
            total = total + cfg.lambda_z * z_loss

            ang_loss = self._angular_uniformity_loss()
            components["angular_uniformity"] = ang_loss.item()
            total = total + cfg.lambda_angular_uniformity * ang_loss

        elif cfg.domain == "gravity":
            grav_loss = cfg.gravity_strength * self.positions[:, 1].sum()
            components["gravity"] = grav_loss.item()
            total = total + grav_loss

        components["total"] = total.item()
        return total, components

    def step(self):
        """Single optimizer step. Returns loss components dict."""
        if self.config.optimizer == "lbfgs":
            def closure():
                self.optim.zero_grad()
                loss, _ = self.compute_loss()
                loss.backward()
                return loss
            self.optim.step(closure)
            _, components = self.compute_loss()
        else:
            self.optim.zero_grad()
            loss, components = self.compute_loss()
            loss.backward()
            # Clip gradients to prevent NaN from sharp loss landscapes
            torch.nn.utils.clip_grad_norm_([self.positions, self.normals], max_norm=10.0)
            self.optim.step()

        # Project normals to unit sphere
        if self.config.project_normals:
            self._project_normals()

        return components

    def optimize(self) -> LayoutGraph:
        """Run full optimization loop. Returns refined LayoutGraph."""
        print(f"\nOptimizing for up to {self.config.num_iterations} iterations...")

        for iteration in range(self.config.num_iterations):
            components = self.step()

            self.loss_history.append(components["total"])
            self.component_history.append(components)

            if iteration % self.config.log_interval == 0:
                parts = [f"{k}={v:.4f}" for k, v in components.items() if k != "total"]
                print(f"  [{iteration:5d}] total={components['total']:.4f}  {', '.join(parts)}")

            if self._check_convergence():
                print(f"  Converged at iteration {iteration}")
                break

        print(f"  Final loss: {self.loss_history[-1]:.4f}")
        return self.get_optimized_graph()

    def compute_per_point_diagnostics(self):
        """
        Compute per-point gradient vectors decomposed by loss component.

        For each loss term, computes d(lambda * L)/d(positions) to show
        which forces act on each stitch and their source. Uses
        torch.autograd.grad to avoid disturbing the optimizer state.

        Returns:
            dict mapping component name -> {
                'gradients': (N, 3) numpy array,
                'loss': float (unweighted component loss),
                'lambda': float (weight applied),
            }
        """
        N = self.positions.shape[0]
        cfg = self.config

        component_defs = [
            ('edge', lambda: self.force_model.total_edge_energy_vectorized(
                self.positions, self.edge_indices, self.rest_lengths), cfg.lambda_edge),
            ('normal', lambda: normal_unit_loss(self.normals), cfg.lambda_normal),
            ('coherence', lambda: normal_coherence_loss(
                self.normals, self.edge_indices), cfg.lambda_coherence),
            ('offset', lambda: offset_loss(
                self.positions, self.normals, self.edge_indices,
                self.stitch_offsets, self.neighbor_indices_list), cfg.lambda_offset),
            ('flatness', lambda: out_of_plane_loss(
                self.positions, self.normals, self.neighbor_indices_list), cfg.lambda_flat),
            ('angle', lambda: in_plane_angle_loss(
                self.positions, self.normals,
                self.h_neighbors, self.v_neighbors), cfg.lambda_angle),
            ('repulsion', lambda: self.repulsion_model.repulsion_energy(
                self.positions), cfg.lambda_repulsion),
        ]

        results = {}
        zeros = np.zeros((N, 3))

        for name, loss_fn, weight in component_defs:
            if weight == 0.0:
                results[name] = {
                    'gradients': zeros.copy(), 'loss': 0.0, 'lambda': weight,
                }
                continue

            loss_raw = loss_fn()
            loss_weighted = weight * loss_raw

            grads = torch.autograd.grad(
                loss_weighted, self.positions,
                retain_graph=False, create_graph=False,
                allow_unused=True,
            )
            grad = grads[0] if grads[0] is not None else torch.zeros(N, 3)

            results[name] = {
                'gradients': grad.detach().numpy().copy(),
                'loss': loss_raw.item(),
                'lambda': weight,
            }

        # Total
        total_loss, _ = self.compute_loss()
        total_grads = torch.autograd.grad(
            total_loss, self.positions,
            retain_graph=False, create_graph=False,
            allow_unused=True,
        )
        total_grad = (
            total_grads[0] if total_grads[0] is not None
            else torch.zeros(N, 3)
        )

        results['total'] = {
            'gradients': total_grad.detach().numpy().copy(),
            'loss': total_loss.item(),
            'lambda': 1.0,
        }

        return results

    def _z_plane_loss(self):
        """Penalty for deviation from the blocking plane."""
        z = self.positions[:, 2]
        z0 = self.config.blocked_flat_plane_z
        return ((z - z0) ** 2).sum()

    def _angular_uniformity_loss(self):
        """
        Penalize uneven angular spacing of edges around each vertex.
        Projects edges into the blocking plane (xy) and measures angular gaps.
        """
        N = self.positions.shape[0]
        loss = torch.tensor(0.0, dtype=self.positions.dtype)

        for i in range(N):
            nbrs = self.neighbor_indices_list[i]
            k = len(nbrs)
            if k < 2:
                continue

            # Project into xy plane
            p_i = self.positions[i, :2]  # (2,)
            angles = []
            for j in nbrs:
                p_j = self.positions[j, :2]
                diff = p_j - p_i
                angle = torch.atan2(diff[1], diff[0])
                angles.append(angle)

            angles = torch.stack(angles)
            angles_sorted, _ = torch.sort(angles)

            # Compute gaps between consecutive angles
            gaps = angles_sorted[1:] - angles_sorted[:-1]
            # Wrap-around gap
            wrap_gap = angles_sorted[0] + 2 * np.pi - angles_sorted[-1]
            all_gaps = torch.cat([gaps, wrap_gap.unsqueeze(0)])

            # Target: 2*pi / k
            target = 2 * np.pi / k
            loss = loss + ((all_gaps - target) ** 2).sum()

        return loss

    def _project_normals(self):
        """Re-normalize normal vectors to unit sphere."""
        with torch.no_grad():
            norms = self.normals.norm(dim=1, keepdim=True).clamp(min=1e-8)
            self.normals.div_(norms)

    def _check_convergence(self):
        """True if loss change < tol for last 50 iterations."""
        if len(self.loss_history) < 50:
            return False
        recent = self.loss_history[-50:]
        change = abs(recent[-1] - recent[0])
        return change < self.config.convergence_tol

    def get_optimized_graph(self) -> LayoutGraph:
        """Extract optimized positions/normals into a new LayoutGraph."""
        pos = self.positions.detach().numpy()
        norms = self.normals.detach().numpy()

        for i, s in enumerate(self.graph.stitches):
            s.position = pos[i].copy()
            s.normal = norms[i].copy()

        return self.graph

    def plot_history(self, path: str = "optimization_history.png"):
        """Plot loss component history."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not self.component_history:
            print("No history to plot.")
            return

        keys = [k for k in self.component_history[0].keys() if k != "total"]
        iterations = range(len(self.component_history))

        fig, axes = plt.subplots(2, 3, figsize=(15, 8))
        axes = axes.flatten()

        # Total loss
        axes[0].plot([c["total"] for c in self.component_history], "b-", linewidth=1.5)
        axes[0].set_title("Total Loss")
        axes[0].set_xlabel("Iteration")
        axes[0].grid(True, alpha=0.3)

        # Individual components
        for idx, key in enumerate(keys[:5]):
            ax = axes[idx + 1]
            vals = [c.get(key, 0) for c in self.component_history]
            ax.plot(vals, linewidth=1.5)
            ax.set_title(key.replace("_", " ").title())
            ax.set_xlabel("Iteration")
            ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(path, dpi=150)
        plt.close()
        print(f"  Saved optimization history to {path}")

    def visualize_3d(self, path: str = "layout_3d.png"):
        """3D scatter plot of optimized layout."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D

        pos = self.positions.detach().numpy()
        edges = self.edge_indices.numpy()
        orientations = self.graph.edge_orientations()

        fig = plt.figure(figsize=(10, 10))
        ax = fig.add_subplot(111, projection="3d")

        ax.scatter(pos[:, 0], pos[:, 1], pos[:, 2], c="cyan", s=30, alpha=0.7)

        for i in range(edges.shape[0]):
            src, tgt = edges[i]
            p1, p2 = pos[src], pos[tgt]
            color = "cyan" if orientations[i] == "h" else "gold"
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]],
                    color=color, alpha=0.3, linewidth=0.8)

        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_zlabel("Z (mm)")
        ax.set_title("Optimized Layout")

        plt.savefig(path, dpi=150)
        plt.close()
        print(f"  Saved 3D visualization to {path}")
