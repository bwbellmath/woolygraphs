#!/usr/bin/env python3
"""
Export WoolyGraphs data to JSON format for 3D viewer
"""

import json
import sys
import pandas as pd
import numpy as np
import os


def read_adjacency_matrix(csv_file):
    """Read adjacency matrix from CSV and convert to edge list"""
    try:
        print(f"Reading {csv_file}...")
        df = pd.read_csv(csv_file, index_col=0)

        edges = []
        nodes = set()

        # Convert to edge list
        for i in df.index:
            nodes.add(int(i))
            for j in df.columns:
                try:
                    j_int = int(j)
                    nodes.add(j_int)
                    weight = df.loc[i, j]

                    if pd.notna(weight) and weight > 0:
                        i_int = int(i)
                        # Only add each edge once (undirected)
                        if i_int < j_int:
                            # Heuristic: adjacent indices = horizontal, else vertical
                            orientation = 'h' if abs(i_int - j_int) == 1 else 'v'

                            edges.append({
                                'source': i_int,
                                'target': j_int,
                                'weight': float(weight),
                                'orientation': orientation
                            })
                except (ValueError, KeyError):
                    continue

        nodes = sorted(list(nodes))
        print(f"  Found {len(nodes)} nodes, {len(edges)} edges")

        return nodes, edges

    except Exception as e:
        print(f"Error reading adjacency matrix: {e}")
        import traceback
        traceback.print_exc()
        return [], []


def create_graph_json(nodes, edges, pattern_name="unknown"):
    """Create JSON structure"""

    node_objects = []
    for node_id in nodes:
        if isinstance(node_id, dict):
            node_objects.append(node_id)
        else:
            node_objects.append({
                'id': int(node_id),
                'label': f'stitch_{node_id}'
            })

    return {
        'metadata': {
            'pattern': pattern_name,
            'nodeCount': len(node_objects),
            'edgeCount': len(edges)
        },
        'nodes': node_objects,
        'edges': edges
    }


def export_pattern_to_json(csv_file, output_file):
    """Export CSV adjacency matrix to JSON"""

    pattern_name = os.path.basename(csv_file).replace('.csv', '')

    nodes, edges = read_adjacency_matrix(csv_file)

    if not nodes:
        print("ERROR: No graph data found!")
        return False

    graph_json = create_graph_json(nodes, edges, pattern_name)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(graph_json, f, indent=2)

    print(f"✓ Exported to {output_file}")
    return True


def create_simple_pattern(pattern_name, rows, cols):
    """Create a simple rectangular stockinette pattern"""

    nodes = []
    edges = []

    # Create nodes
    for i in range(rows * cols):
        nodes.append({
            'id': i,
            'label': f'stitch_{i}',
            'row': i // cols,
            'col': i % cols
        })

    # Horizontal edges (within row)
    for row in range(rows):
        for col in range(cols - 1):
            node_id = row * cols + col
            edges.append({
                'source': node_id,
                'target': node_id + 1,
                'weight': 1.0,
                'orientation': 'h'
            })

    # Vertical edges (between rows)
    for row in range(rows - 1):
        for col in range(cols):
            source = row * cols + col
            target = (row + 1) * cols + col
            edges.append({
                'source': source,
                'target': target,
                'weight': 1.5,
                'orientation': 'v'
            })

    return create_graph_json(nodes, edges, pattern_name)


def export_all_patterns():
    """Export all CSV files in matrices/ directory"""

    matrices_dir = 'matrices'
    output_dir = 'viewer3d/data'

    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(matrices_dir):
        csv_files = [f for f in os.listdir(matrices_dir) if f.endswith('.csv')]

        if csv_files:
            print(f"\nFound {len(csv_files)} CSV files in {matrices_dir}/")

            patterns_list = []

            for csv_file in csv_files:
                csv_path = os.path.join(matrices_dir, csv_file)
                pattern_name = csv_file.replace('.csv', '')
                output_path = os.path.join(output_dir, f'{pattern_name}.json')

                if export_pattern_to_json(csv_path, output_path):
                    patterns_list.append({
                        'name': pattern_name,
                        'file': f'{pattern_name}.json'
                    })

            # Create patterns.json index
            with open(os.path.join(output_dir, 'patterns.json'), 'w') as f:
                json.dump(patterns_list, f, indent=2)

            print(f"\n✓ Created patterns index: {output_dir}/patterns.json")

        else:
            print(f"No CSV files found in {matrices_dir}/")


if __name__ == '__main__':
    print("=" * 60)
    print("WoolyGraphs Pattern Exporter")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Export specific file
        csv_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else 'viewer3d/data/graph.json'
        export_pattern_to_json(csv_file, output_file)

    else:
        # Create test patterns
        print("\nCreating test patterns...")

        os.makedirs('viewer3d/data', exist_ok=True)

        # Simple 4x5 pattern
        test_pattern = create_simple_pattern('test_pattern', rows=5, cols=4)
        with open('viewer3d/data/test_pattern.json', 'w') as f:
            json.dump(test_pattern, f, indent=2)
        print(f"✓ Created test_pattern.json (4x5 stockinette)")

        # Larger 8x10 pattern
        large_pattern = create_simple_pattern('large_pattern', rows=10, cols=8)
        with open('viewer3d/data/large_pattern.json', 'w') as f:
            json.dump(large_pattern, f, indent=2)
        print(f"✓ Created large_pattern.json (8x10 stockinette)")

        # Export all CSV files from matrices/
        export_all_patterns()

        print("\n" + "=" * 60)
        print("Usage:")
        print("  python export_to_json.py                    # Create test patterns")
        print("  python export_to_json.py <csv> <output>     # Export specific file")
        print("=" * 60)
