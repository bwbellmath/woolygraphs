"""
WoolyGraphs: Knitting pattern to graph layout system.

Converts knitting patterns into positioned graph representations
with adjacency matrices and 3D vertex coordinates.

Main workflow:
    1. Load stitch definitions: stitches = load_stitches()
    2. Parse pattern to graph: graph = pattern_to_graph(path, stitches)
    3. Compute baseline layout: positions = compute_baseline_positions(graph, config)
    4. Optimize layout: optimized = optimizer.optimize(graph, positions)

Quick usage:
    from woolygraphs import pattern_to_graph, compute_baseline_positions, quick_optimize

    graph = pattern_to_graph('pattern.txt')
    positions = compute_baseline_positions(graph)
    optimized = quick_optimize(graph, positions, verbose=True)
"""

__version__ = "0.1.0"

from .stitches import StitchTech, Edge, load_stitches
from .config import LayoutConfig, load_config, infer_config_from_pattern
from .graph import KnitGraph, pattern_to_graph
from .baseline import compute_baseline_positions, LayoutResult
from .optimizer import LayoutOptimizer, quick_optimize

__all__ = [
    # Stitches
    'StitchTech',
    'Edge',
    'load_stitches',
    # Config
    'LayoutConfig',
    'load_config',
    'infer_config_from_pattern',
    # Graph
    'KnitGraph',
    'pattern_to_graph',
    # Baseline
    'compute_baseline_positions',
    'LayoutResult',
    # Optimizer
    'LayoutOptimizer',
    'quick_optimize',
]
