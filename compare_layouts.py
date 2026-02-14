"""
Compare original and optimized layouts side-by-side
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import sys


def load_graph(json_path):
    """Load graph from JSON"""
    with open(json_path, 'r') as f:
        return json.load(f)


def extract_positions(graph):
    """Extract positions from graph data"""
    positions = []
    for node in graph['nodes']:
        if 'position' in node:
            pos = node['position']
            positions.append([pos['x'], pos['y'], pos['z']])
        else:
            # No position - return None
            return None
    return np.array(positions)


def calculate_edge_lengths(positions, edges):
    """Calculate current edge lengths"""
    lengths = []
    for edge in edges:
        src = edge['source']
        tgt = edge['target']
        pos1 = positions[src]
        pos2 = positions[tgt]
        dist = np.linalg.norm(pos2 - pos1)
        lengths.append({
            'distance': dist,
            'orientation': edge['orientation'],
            'target': 3.0 if edge['orientation'] == 'v' else 4.0
        })
    return lengths


def plot_comparison(original_graph, optimized_graph, save_path='comparison.png'):
    """Create side-by-side comparison plot"""

    # Extract data
    orig_pos = extract_positions(original_graph)
    opt_pos = extract_positions(optimized_graph)
    edges = original_graph['edges']

    # Check if we have positions
    if orig_pos is None:
        print("WARNING: Original graph has no positions, using grid layout")
        # Create grid positions
        n = len(original_graph['nodes'])
        grid_size = int(np.ceil(np.sqrt(n)))
        orig_pos = []
        for i in range(n):
            row = i // grid_size
            col = i % grid_size
            orig_pos.append([col * 4.0, row * 3.0, 0.0])
        orig_pos = np.array(orig_pos)

    # Calculate edge statistics
    orig_lengths = calculate_edge_lengths(orig_pos, edges)
    opt_lengths = calculate_edge_lengths(opt_pos, edges)

    # Create figure
    fig = plt.figure(figsize=(18, 12))

    # 3D layouts (top row)
    ax1 = fig.add_subplot(2, 3, 1, projection='3d')
    ax2 = fig.add_subplot(2, 3, 2, projection='3d')

    # Plot original
    ax1.scatter(orig_pos[:, 0], orig_pos[:, 1], orig_pos[:, 2],
               c='cyan', s=50, alpha=0.6, label='Nodes')
    for edge in edges:
        src, tgt = edge['source'], edge['target']
        pos1, pos2 = orig_pos[src], orig_pos[tgt]
        color = 'cyan' if edge['orientation'] == 'h' else 'yellow'
        ax1.plot([pos1[0], pos2[0]], [pos1[1], pos2[1]], [pos1[2], pos2[2]],
                color=color, alpha=0.3, linewidth=1)
    ax1.set_title('Original Layout', fontsize=14, fontweight='bold')
    ax1.set_xlabel('X (mm)')
    ax1.set_ylabel('Y (mm)')
    ax1.set_zlabel('Z (mm)')

    # Plot optimized
    ax2.scatter(opt_pos[:, 0], opt_pos[:, 1], opt_pos[:, 2],
               c='cyan', s=50, alpha=0.6, label='Nodes')
    for edge in edges:
        src, tgt = edge['source'], edge['target']
        pos1, pos2 = opt_pos[src], opt_pos[tgt]
        color = 'cyan' if edge['orientation'] == 'h' else 'yellow'
        ax2.plot([pos1[0], pos2[0]], [pos1[1], pos2[1]], [pos1[2], pos2[2]],
                color=color, alpha=0.3, linewidth=1)
    ax2.set_title('Optimized Layout', fontsize=14, fontweight='bold')
    ax2.set_xlabel('X (mm)')
    ax2.set_ylabel('Y (mm)')
    ax2.set_zlabel('Z (mm)')

    # Edge length distributions (bottom row)
    ax3 = fig.add_subplot(2, 3, 4)
    ax4 = fig.add_subplot(2, 3, 5)
    ax5 = fig.add_subplot(2, 3, 3)

    # Original edge lengths
    orig_h = [e['distance'] for e in orig_lengths if e['orientation'] == 'h']
    orig_v = [e['distance'] for e in orig_lengths if e['orientation'] == 'v']

    ax3.hist(orig_h, bins=20, alpha=0.7, color='cyan', label='Horizontal')
    ax3.hist(orig_v, bins=20, alpha=0.7, color='yellow', label='Vertical')
    ax3.axvline(4.0, color='cyan', linestyle='--', linewidth=2, label='H target (4mm)')
    ax3.axvline(3.0, color='yellow', linestyle='--', linewidth=2, label='V target (3mm)')
    ax3.set_xlabel('Edge Length (mm)')
    ax3.set_ylabel('Count')
    ax3.set_title('Original Edge Lengths')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    # Optimized edge lengths
    opt_h = [e['distance'] for e in opt_lengths if e['orientation'] == 'h']
    opt_v = [e['distance'] for e in opt_lengths if e['orientation'] == 'v']

    ax4.hist(opt_h, bins=20, alpha=0.7, color='cyan', label='Horizontal')
    ax4.hist(opt_v, bins=20, alpha=0.7, color='yellow', label='Vertical')
    ax4.axvline(4.0, color='cyan', linestyle='--', linewidth=2, label='H target (4mm)')
    ax4.axvline(3.0, color='yellow', linestyle='--', linewidth=2, label='V target (3mm)')
    ax4.set_xlabel('Edge Length (mm)')
    ax4.set_ylabel('Count')
    ax4.set_title('Optimized Edge Lengths')
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    # Statistics table
    ax5.axis('off')

    # Calculate statistics
    orig_h_mean = np.mean(orig_h) if orig_h else 0
    orig_h_std = np.std(orig_h) if orig_h else 0
    orig_v_mean = np.mean(orig_v) if orig_v else 0
    orig_v_std = np.std(orig_v) if orig_v else 0

    opt_h_mean = np.mean(opt_h) if opt_h else 0
    opt_h_std = np.std(opt_h) if opt_h else 0
    opt_v_mean = np.mean(opt_v) if opt_v else 0
    opt_v_std = np.std(opt_v) if opt_v else 0

    # Calculate error from targets
    orig_h_error = abs(orig_h_mean - 4.0) if orig_h else 0
    orig_v_error = abs(orig_v_mean - 3.0) if orig_v else 0
    opt_h_error = abs(opt_h_mean - 4.0) if opt_h else 0
    opt_v_error = abs(opt_v_mean - 3.0) if opt_v else 0

    stats_text = f"""
    EDGE LENGTH STATISTICS

    Horizontal Edges (target: 4.0mm)
    ─────────────────────────────────
    Original:   {orig_h_mean:.3f} ± {orig_h_std:.3f} mm
                Error: {orig_h_error:.3f} mm

    Optimized:  {opt_h_mean:.3f} ± {opt_h_std:.3f} mm
                Error: {opt_h_error:.3f} mm

    Improvement: {((orig_h_error - opt_h_error)/orig_h_error*100):.1f}%


    Vertical Edges (target: 3.0mm)
    ─────────────────────────────────
    Original:   {orig_v_mean:.3f} ± {orig_v_std:.3f} mm
                Error: {orig_v_error:.3f} mm

    Optimized:  {opt_v_mean:.3f} ± {opt_v_std:.3f} mm
                Error: {opt_v_error:.3f} mm

    Improvement: {((orig_v_error - opt_v_error)/orig_v_error*100):.1f}%
    """

    ax5.text(0.1, 0.5, stats_text, fontsize=11, family='monospace',
            verticalalignment='center',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))

    # Overall title
    pattern_name = original_graph.get('metadata', {}).get('pattern', 'Unknown')
    fig.suptitle(f'Layout Comparison: {pattern_name}',
                fontsize=16, fontweight='bold')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"Saved comparison to {save_path}")
    plt.close()

    # Print summary
    print("\n" + "="*60)
    print("COMPARISON SUMMARY")
    print("="*60)
    print(f"Pattern: {pattern_name}")
    print(f"Nodes: {len(original_graph['nodes'])}")
    print(f"Edges: {len(edges)}")
    print()
    print("Horizontal edges (target: 4.0mm):")
    print(f"  Original:  {orig_h_mean:.3f} ± {orig_h_std:.3f} mm (error: {orig_h_error:.3f})")
    print(f"  Optimized: {opt_h_mean:.3f} ± {opt_h_std:.3f} mm (error: {opt_h_error:.3f})")
    print(f"  Improvement: {((orig_h_error - opt_h_error)/orig_h_error*100):.1f}%")
    print()
    print("Vertical edges (target: 3.0mm):")
    print(f"  Original:  {orig_v_mean:.3f} ± {orig_v_std:.3f} mm (error: {orig_v_error:.3f})")
    print(f"  Optimized: {opt_v_mean:.3f} ± {opt_v_std:.3f} mm (error: {opt_v_error:.3f})")
    print(f"  Improvement: {((orig_v_error - opt_v_error)/orig_v_error*100):.1f}%")
    print("="*60)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python compare_layouts.py <original.json> <optimized.json> [output.png]")
        print("\nExample:")
        print("  python compare_layouts.py viewer3d/data/small_stockinette.json \\")
        print("                            viewer3d/data/small_stockinette_optimized.json")
        sys.exit(1)

    original_path = sys.argv[1]
    optimized_path = sys.argv[2]
    output_path = sys.argv[3] if len(sys.argv) > 3 else 'comparison.png'

    print(f"Loading graphs...")
    print(f"  Original:  {original_path}")
    print(f"  Optimized: {optimized_path}")

    original = load_graph(original_path)
    optimized = load_graph(optimized_path)

    plot_comparison(original, optimized, output_path)
