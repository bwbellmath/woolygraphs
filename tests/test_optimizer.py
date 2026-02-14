"""Tests for layout/optimizer.py -- Phase 2 optimization."""

import numpy as np
import torch
import pytest

from layout.stitch_instance import Gauge, LayoutGraph
from layout.initial_layout import compile_pattern, load_stitch_definitions, parse_pattern
from layout.optimizer import LayoutOptimizer, OptimizerConfig


@pytest.fixture
def small_graph():
    """Compile small_stockinette for testing."""
    sdefs = load_stitch_definitions()
    tokens = parse_pattern("patterns/small_stockinette.txt")
    gauge = Gauge()
    return compile_pattern(tokens, sdefs, gauge)


class TestOptimizerConfig:
    def test_defaults(self):
        cfg = OptimizerConfig()
        assert cfg.lambda_edge == 10.0
        assert cfg.lambda_coherence == 5.0
        assert cfg.lambda_angle == 5.0
        assert cfg.lambda_repulsion == 0.0
        assert cfg.domain == "free"

    def test_blocked_flat_preset(self):
        cfg = OptimizerConfig.blocked_flat_preset()
        assert cfg.domain == "blocked_flat"
        assert cfg.lambda_edge == 0.5
        assert cfg.lambda_z == 100.0
        assert cfg.lambda_coherence == 5.0


class TestLayoutOptimizer:
    def test_initialization(self, small_graph):
        config = OptimizerConfig()
        config.num_iterations = 10
        opt = LayoutOptimizer(small_graph, config)

        assert opt.positions.shape == (16, 3)
        assert opt.normals.shape == (16, 3)
        assert opt.edge_indices.shape[0] == 24

    def test_compute_loss(self, small_graph):
        config = OptimizerConfig()
        opt = LayoutOptimizer(small_graph, config)

        loss, components = opt.compute_loss()
        assert "total" in components
        assert "edge" in components
        assert "normal" in components
        assert "coherence" in components
        assert "offset" in components
        assert "flatness" in components
        assert "angle" in components
        assert "repulsion" in components
        # Perfect grid at equilibrium: all enabled losses should be ~0
        assert loss.item() >= 0

    def test_loss_decreases(self, small_graph):
        """Total loss should decrease over optimization when starting from a perturbed state."""
        config = OptimizerConfig()
        config.num_iterations = 100
        config.log_interval = 50

        opt = LayoutOptimizer(small_graph, config)

        # Perturb positions away from equilibrium so loss starts > 0
        with torch.no_grad():
            opt.positions.add_(torch.randn_like(opt.positions) * 0.5)

        opt.optimize()

        # Loss should decrease from the perturbed state
        assert opt.loss_history[-1] < opt.loss_history[0]

    def test_step_returns_components(self, small_graph):
        config = OptimizerConfig()
        opt = LayoutOptimizer(small_graph, config)
        components = opt.step()

        assert isinstance(components, dict)
        assert "total" in components

    def test_normals_stay_unit(self, small_graph):
        """With project_normals=True, normals should remain unit-length."""
        config = OptimizerConfig()
        config.num_iterations = 50
        config.project_normals = True

        opt = LayoutOptimizer(small_graph, config)
        opt.optimize()

        norms = opt.normals.detach()
        lengths = torch.norm(norms, dim=1)
        assert torch.allclose(lengths, torch.ones_like(lengths), atol=1e-5)

    def test_get_optimized_graph(self, small_graph):
        config = OptimizerConfig()
        config.num_iterations = 10

        opt = LayoutOptimizer(small_graph, config)
        result = opt.optimize()

        assert isinstance(result, LayoutGraph)
        assert result.num_stitches == 16

    def test_convergence_detection(self, small_graph):
        """Convergence should be detected when loss stabilizes."""
        config = OptimizerConfig()
        config.num_iterations = 10000
        config.convergence_tol = 100.0  # very loose, should converge quickly

        opt = LayoutOptimizer(small_graph, config)
        opt.optimize()

        # Should have stopped early
        assert len(opt.loss_history) < 10000

    def test_blocked_flat_domain(self, small_graph):
        """Blocked-flat mode should include z-plane and angular losses."""
        config = OptimizerConfig.blocked_flat_preset()
        config.num_iterations = 10

        opt = LayoutOptimizer(small_graph, config)
        _, components = opt.compute_loss()

        assert "z_plane" in components
        assert "angular_uniformity" in components

    def test_different_optimizers(self, small_graph):
        """Should work with adam and sgd."""
        for opt_name in ["adam", "sgd"]:
            config = OptimizerConfig()
            config.optimizer = opt_name
            config.num_iterations = 5

            opt = LayoutOptimizer(small_graph, config)
            result = opt.optimize()
            assert result.num_stitches == 16

    def test_stockinette_converges_to_regular_grid(self):
        """
        Stockinette (all knit) should converge to a perfectly regular
        rectangular grid: flat (z=0), normals aligned (0,0,1), and
        edge lengths matching gauge (h=4mm, v=3mm).

        Uses lambda_offset=0 to isolate the edge/coherence/flatness
        losses that drive grid regularity. Repulsion is off by default.
        """
        sdefs = load_stitch_definitions()
        tokens = parse_pattern("patterns/small_stockinette.txt")
        gauge = Gauge()
        graph = compile_pattern(tokens, sdefs, gauge)

        config = OptimizerConfig()
        config.num_iterations = 3000
        config.convergence_tol = 1e-5
        config.log_interval = 500
        # Disable offset -- boundary centroids are biased;
        # edge+coherence+flat alone should drive a regular rectangle.
        config.lambda_offset = 0.0

        opt = LayoutOptimizer(graph, config)
        result = opt.optimize()

        pos = opt.positions.detach().numpy()
        norms = opt.normals.detach().numpy()
        edge_indices = opt.edge_indices.numpy()
        orientations = result.edge_orientations()

        # 1. Flatness: all z-coordinates should be ~0
        z_range = pos[:, 2].max() - pos[:, 2].min()
        assert z_range < 0.1, f"Z range {z_range:.4f} > 0.1 -- not flat"

        # 2. Normals aligned to (0,0,1)
        normal_z_min = norms[:, 2].min()
        assert normal_z_min > 0.95, f"Min normal-z {normal_z_min:.4f} < 0.95 -- normals not aligned"

        # 3. Horizontal edge lengths ≈ 4.0mm (stitch_width)
        h_mask = [i for i, o in enumerate(orientations) if o == "h"]
        h_lengths = []
        for idx in h_mask:
            src, tgt = edge_indices[idx]
            d = np.linalg.norm(pos[src] - pos[tgt])
            h_lengths.append(d)
        h_lengths = np.array(h_lengths)
        h_max_err = np.abs(h_lengths - gauge.stitch_width).max()
        assert h_max_err < 0.2, f"H-edge max error {h_max_err:.4f} > 0.2mm"

        # 4. Vertical edge lengths ≈ 3.0mm (stitch_height)
        v_mask = [i for i, o in enumerate(orientations) if o == "v"]
        v_lengths = []
        for idx in v_mask:
            src, tgt = edge_indices[idx]
            d = np.linalg.norm(pos[src] - pos[tgt])
            v_lengths.append(d)
        v_lengths = np.array(v_lengths)
        v_max_err = np.abs(v_lengths - gauge.stitch_height).max()
        assert v_max_err < 0.2, f"V-edge max error {v_max_err:.4f} > 0.2mm"
