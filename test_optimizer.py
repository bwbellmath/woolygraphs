#!/usr/bin/env python3
"""
Test script for the layout optimizer.
"""

import sys
import numpy as np

# Add package to path
sys.path.insert(0, '.')

from woolygraphs import (
    load_stitches,
    pattern_to_graph,
    compute_baseline_positions,
    LayoutConfig,
    LayoutOptimizer,
    quick_optimize,
)
from woolygraphs.config import OptimizerConfig
from woolygraphs.optimizer import TORCH_AVAILABLE
from woolygraphs.optimizer.forces import EdgeSpringForce


def test_force_components():
    """Test individual force components."""
    print("=" * 60)
    print("Testing Force Components")
    print("=" * 60)

    stitches = load_stitches('stitches.txt')
    graph = pattern_to_graph('patterns/small_stockinette.txt', stitches)
    positions = compute_baseline_positions(graph)

    print(f"Graph: {graph.n_stitches} stitches, {len(graph.edges)} edges")

    # Test EdgeSpringForce
    spring = EdgeSpringForce(weight=1.0)
    forces = spring.compute_forces(positions, graph)
    energy = spring.compute_energy(positions, graph)

    print(f"\nEdgeSpringForce:")
    print(f"  Energy: {energy:.6f}")
    print(f"  Max force magnitude: {np.max(np.linalg.norm(forces, axis=1)):.6f}")

    # For baseline layout, energy should be near zero (edges are correct)
    errors = spring.compute_edge_errors(positions, graph)
    h_errors = [e[2] for e in errors['h']]
    v_errors = [e[2] for e in errors['v']]
    print(f"  H edge mean error: {np.mean(np.abs(h_errors)):.6f} mm")
    print(f"  V edge mean error: {np.mean(np.abs(v_errors)):.6f} mm")

    return True


def test_optimizer_flat():
    """Test optimizer with flat stockinette."""
    print("\n" + "=" * 60)
    print("Testing Optimizer: Flat Stockinette")
    print("=" * 60)

    stitches = load_stitches('stitches.txt')
    graph = pattern_to_graph('patterns/small_stockinette.txt', stitches)

    # Start with baseline positions
    baseline = compute_baseline_positions(graph)

    # Add some perturbation to test optimization
    perturbed = baseline + np.random.randn(*baseline.shape) * 0.5
    print(f"Added random perturbation (std=0.5mm) to baseline positions")

    # Check initial edge errors
    spring = EdgeSpringForce()
    before_errors = spring.compute_edge_errors(perturbed, graph)
    before_h_rmse = np.sqrt(np.mean([e[2]**2 for e in before_errors['h']]))
    before_v_rmse = np.sqrt(np.mean([e[2]**2 for e in before_errors['v']]))
    print(f"\nBefore optimization:")
    print(f"  H edge RMSE: {before_h_rmse:.4f} mm")
    print(f"  V edge RMSE: {before_v_rmse:.4f} mm")

    # Configure optimizer
    opt_config = OptimizerConfig(
        method='pytorch' if TORCH_AVAILABLE else 'force_directed',
        epochs=500,
        learning_rate=0.05,
        forces={
            'edge_spring': 1.0,
            'repulsion': 0.05,
            'solid_angle': 0.0,
        }
    )
    config = LayoutConfig(optimizer=opt_config)

    print(f"\nBackend: {'PyTorch' if TORCH_AVAILABLE else 'ForceDirected'}")

    # Run optimizer
    optimizer = LayoutOptimizer(config)
    optimized = optimizer.optimize(graph, perturbed, verbose=True)

    # Check final edge errors
    after_errors = spring.compute_edge_errors(optimized, graph)
    after_h_rmse = np.sqrt(np.mean([e[2]**2 for e in after_errors['h']]))
    after_v_rmse = np.sqrt(np.mean([e[2]**2 for e in after_errors['v']]))
    print(f"\nAfter optimization:")
    print(f"  H edge RMSE: {after_h_rmse:.4f} mm")
    print(f"  V edge RMSE: {after_v_rmse:.4f} mm")

    # Verify improvement
    improved = after_h_rmse < before_h_rmse and after_v_rmse < before_v_rmse
    print(f"\nOptimization improved layout: {improved}")

    return graph, perturbed, optimized


def test_optimizer_circular():
    """Test optimizer with circular tube."""
    print("\n" + "=" * 60)
    print("Testing Optimizer: Circular Tube")
    print("=" * 60)

    stitches = load_stitches('stitches.txt')
    graph = pattern_to_graph('patterns/tube_round.txt', stitches)

    config = LayoutConfig.default_circular(8)
    baseline = compute_baseline_positions(graph, config)

    # Add perturbation
    perturbed = baseline + np.random.randn(*baseline.shape) * 1.0

    print(f"Graph: {graph.n_stitches} stitches")
    print(f"Added random perturbation (std=1.0mm)")

    # Use quick_optimize for convenience
    optimized = quick_optimize(
        graph, perturbed,
        epochs=500,
        edge_spring=1.0,
        repulsion=0.1,
        solid_angle=0.0,
        verbose=True
    )

    return graph, perturbed, optimized


def test_quick_optimize():
    """Test the quick_optimize convenience function."""
    print("\n" + "=" * 60)
    print("Testing quick_optimize")
    print("=" * 60)

    stitches = load_stitches('stitches.txt')
    graph = pattern_to_graph('patterns/small_stockinette.txt', stitches)
    baseline = compute_baseline_positions(graph)

    # Perturb
    perturbed = baseline + np.random.randn(*baseline.shape) * 0.3

    # Quick optimize
    optimized = quick_optimize(graph, perturbed, epochs=200, verbose=True)

    print("\nquick_optimize completed successfully")
    return True


def plot_comparison(graph, before, after, title="Optimization Comparison"):
    """Plot before/after comparison."""
    try:
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D

        fig, axes = plt.subplots(1, 2, figsize=(14, 6),
                                  subplot_kw={'projection': '3d'})

        for ax, pos, label in [(axes[0], before, 'Before'),
                               (axes[1], after, 'After')]:
            ax.scatter(pos[:, 0], pos[:, 1], pos[:, 2],
                      c='blue', s=50, alpha=0.8)

            for e in graph.edges:
                p1, p2 = pos[e.i], pos[e.j]
                color = 'red' if e.orient == 'h' else 'green'
                ax.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]],
                       color=color, alpha=0.5)

            ax.set_xlabel('X (mm)')
            ax.set_ylabel('Y (mm)')
            ax.set_zlabel('Z (mm)')
            ax.set_title(f'{title} - {label}')

        plt.tight_layout()
        plt.show()

    except Exception as e:
        print(f"Could not plot: {e}")


if __name__ == '__main__':
    print(f"PyTorch available: {TORCH_AVAILABLE}")
    print()

    # Run tests
    test_force_components()
    flat_graph, flat_before, flat_after = test_optimizer_flat()
    tube_graph, tube_before, tube_after = test_optimizer_circular()
    test_quick_optimize()

    print("\n" + "=" * 60)
    print("All optimizer tests completed!")
    print("=" * 60)

    # Try to plot
    try:
        plot_comparison(flat_graph, flat_before, flat_after, "Flat Stockinette")
        plot_comparison(tube_graph, tube_before, tube_after, "Circular Tube")
    except:
        print("\nPlotting skipped (no display)")
