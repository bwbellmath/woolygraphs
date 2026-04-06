#!/usr/bin/env python3
"""
Test script for baseline layout computation.
"""

import sys
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# Add package to path
sys.path.insert(0, '.')

from woolygraphs import (
    load_stitches,
    load_config,
    pattern_to_graph,
    compute_baseline_positions,
    LayoutConfig,
)


def test_flat_stockinette():
    """Test flat layout with small stockinette pattern."""
    print("=" * 60)
    print("Testing flat stockinette layout")
    print("=" * 60)

    # Load stitches
    stitches = load_stitches('stitches.txt')
    print(f"Loaded {len(stitches)} stitch definitions")

    # Parse pattern
    graph = pattern_to_graph('patterns/small_stockinette.txt', stitches)
    print(f"Graph: {graph.n_stitches} stitches, {len(graph.edges)} edges")
    print(f"Topology: {graph.topology}")
    print(f"Rows: {len(graph.row_indices)}")
    for i, row in enumerate(graph.row_indices):
        print(f"  Row {i}: {len(row)} stitches, indices {row}")

    # Compute baseline positions
    config = LayoutConfig.default_flat()
    positions = compute_baseline_positions(graph, config)
    print(f"\nPositions shape: {positions.shape}")
    print(f"X range: {positions[:,0].min():.1f} to {positions[:,0].max():.1f} mm")
    print(f"Y range: {positions[:,1].min():.1f} to {positions[:,1].max():.1f} mm")
    print(f"Z range: {positions[:,2].min():.1f} to {positions[:,2].max():.1f} mm")

    # Check edge lengths
    print("\nEdge length analysis:")
    h_edges = graph.get_edges_by_orientation('h')
    v_edges = graph.get_edges_by_orientation('v')

    h_lengths = []
    for e in h_edges:
        dist = np.linalg.norm(positions[e.i] - positions[e.j])
        h_lengths.append(dist)
        if abs(dist - e.length_mm) > 0.1:
            print(f"  H-edge ({e.i},{e.j}): {dist:.2f}mm (target: {e.length_mm}mm)")

    v_lengths = []
    for e in v_edges:
        dist = np.linalg.norm(positions[e.i] - positions[e.j])
        v_lengths.append(dist)
        if abs(dist - e.length_mm) > 0.1:
            print(f"  V-edge ({e.i},{e.j}): {dist:.2f}mm (target: {e.length_mm}mm)")

    if h_lengths:
        print(f"\nHorizontal edges: mean={np.mean(h_lengths):.2f}mm, std={np.std(h_lengths):.2f}mm")
    if v_lengths:
        print(f"Vertical edges: mean={np.mean(v_lengths):.2f}mm, std={np.std(v_lengths):.2f}mm")

    return graph, positions


def test_circular_tube():
    """Test circular layout with tube pattern."""
    print("\n" + "=" * 60)
    print("Testing circular tube layout")
    print("=" * 60)

    stitches = load_stitches('stitches.txt')

    graph = pattern_to_graph('patterns/tube_round.txt', stitches)
    print(f"Graph: {graph.n_stitches} stitches, {len(graph.edges)} edges")
    print(f"Topology: {graph.topology}")

    config = LayoutConfig.default_circular(8)
    positions = compute_baseline_positions(graph, config)
    print(f"\nPositions shape: {positions.shape}")
    print(f"X range: {positions[:,0].min():.1f} to {positions[:,0].max():.1f} mm")
    print(f"Y range: {positions[:,1].min():.1f} to {positions[:,1].max():.1f} mm")
    print(f"Z range: {positions[:,2].min():.1f} to {positions[:,2].max():.1f} mm")

    # Check that first row forms a circle
    if graph.row_indices:
        first_row = graph.row_indices[0]
        first_row_pos = positions[first_row]
        center = first_row_pos.mean(axis=0)
        radii = np.linalg.norm(first_row_pos - center, axis=1)
        print(f"\nFirst row circle check:")
        print(f"  Center: ({center[0]:.2f}, {center[1]:.2f}, {center[2]:.2f})")
        print(f"  Radius: mean={radii.mean():.2f}mm, std={radii.std():.4f}mm")

    return graph, positions


def test_mobius():
    """Test mobius layout."""
    print("\n" + "=" * 60)
    print("Testing mobius strip layout")
    print("=" * 60)

    stitches = load_stitches('stitches.txt')

    graph = pattern_to_graph('patterns/mobius_strip.txt', stitches)
    print(f"Graph: {graph.n_stitches} stitches, {len(graph.edges)} edges")
    print(f"Topology: {graph.topology}")

    config = LayoutConfig.default_mobius(12)
    positions = compute_baseline_positions(graph, config)
    print(f"\nPositions shape: {positions.shape}")
    print(f"X range: {positions[:,0].min():.1f} to {positions[:,0].max():.1f} mm")
    print(f"Y range: {positions[:,1].min():.1f} to {positions[:,1].max():.1f} mm")
    print(f"Z range: {positions[:,2].min():.1f} to {positions[:,2].max():.1f} mm")

    return graph, positions


def plot_layout(graph, positions, title="Layout"):
    """Plot the graph layout in 3D."""
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    # Plot vertices
    ax.scatter(positions[:, 0], positions[:, 1], positions[:, 2],
               c='blue', s=50, alpha=0.8)

    # Plot edges
    for e in graph.edges:
        p1 = positions[e.i]
        p2 = positions[e.j]
        color = 'red' if e.orient == 'h' else 'green'
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]],
                color=color, alpha=0.6, linewidth=1)

    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_zlabel('Z (mm)')
    ax.set_title(title)

    # Equal aspect ratio
    max_range = max(
        positions[:, 0].max() - positions[:, 0].min(),
        positions[:, 1].max() - positions[:, 1].min(),
        max(1, positions[:, 2].max() - positions[:, 2].min())
    ) / 2

    mid_x = (positions[:, 0].max() + positions[:, 0].min()) / 2
    mid_y = (positions[:, 1].max() + positions[:, 1].min()) / 2
    mid_z = (positions[:, 2].max() + positions[:, 2].min()) / 2

    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)

    return fig, ax


if __name__ == '__main__':
    # Run tests
    flat_graph, flat_pos = test_flat_stockinette()
    tube_graph, tube_pos = test_circular_tube()
    mobius_graph, mobius_pos = test_mobius()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)

    # Plot if matplotlib display is available
    try:
        fig1, ax1 = plot_layout(flat_graph, flat_pos, "Flat Stockinette")
        fig2, ax2 = plot_layout(tube_graph, tube_pos, "Circular Tube")
        fig3, ax3 = plot_layout(mobius_graph, mobius_pos, "Mobius Strip")
        plt.show()
    except Exception as e:
        print(f"\nCould not display plots: {e}")
        print("Run with a display to see visualizations.")
