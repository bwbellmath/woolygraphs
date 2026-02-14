#!/usr/bin/env python3
"""
WoolyGraphs End-to-End Layout Pipeline

Usage:
  python run_layout.py <pattern.txt> [--output <dir>] [--config <config.json>]
                                     [--domain free|blocked_flat]
                                     [--iterations N] [--lr FLOAT]

Steps:
  1. Parse pattern file -> token list
  2. Load stitch descriptions from stitches_2.txt
  3. Phase 1: compile_pattern -> LayoutGraph (initial positions + normals)
  4. Phase 2: LayoutOptimizer.optimize -> refined LayoutGraph
  5. Export to JSON (for viewer)
  6. Generate diagnostic plots (loss history, 3D layout)
"""

import argparse
import json
import sys
from pathlib import Path

from layout.stitch_instance import Gauge, LayoutGraph
from layout.initial_layout import compile_pattern, load_stitch_definitions, parse_pattern
from layout.optimizer import LayoutOptimizer, OptimizerConfig


def _format_diagnostics(diagnostics):
    """Convert diagnostics dict (numpy arrays) to JSON-serializable format."""
    result = {}
    for name, info in diagnostics.items():
        grads = info['gradients']
        result[name] = {
            'lambda': float(info['lambda']),
            'total_loss': float(info['loss']),
            'gradients': [
                {'x': float(grads[i, 0]), 'y': float(grads[i, 1]), 'z': float(grads[i, 2])}
                for i in range(grads.shape[0])
            ],
        }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="WoolyGraphs Layout Pipeline: pattern -> graph -> optimized 3D layout"
    )
    parser.add_argument("pattern", help="Path to pattern .txt file")
    parser.add_argument("--output", "-o", default=None,
                        help="Output directory (default: same dir as pattern)")
    parser.add_argument("--config", "-c", default=None,
                        help="JSON config file for optimizer parameters")
    parser.add_argument("--domain", "-d", default="free",
                        choices=["free", "gravity", "blocked_flat"],
                        help="Physical domain (default: free)")
    parser.add_argument("--iterations", "-n", type=int, default=2000,
                        help="Number of optimization iterations (default: 2000)")
    parser.add_argument("--lr", type=float, default=0.01,
                        help="Learning rate (default: 0.01)")
    parser.add_argument("--stitch-width", type=float, default=4.0,
                        help="Stitch width in mm (default: 4.0)")
    parser.add_argument("--stitch-height", type=float, default=3.0,
                        help="Stitch height in mm (default: 3.0)")
    parser.add_argument("--skip-optimize", action="store_true",
                        help="Skip Phase 2 optimization (export Phase 1 only)")
    parser.add_argument("--stitches", default=None,
                        help="Path to stitch definitions file (default: stitches_2.txt)")

    args = parser.parse_args()

    pattern_path = Path(args.pattern)
    if not pattern_path.exists():
        print(f"Error: pattern file not found: {pattern_path}")
        sys.exit(1)

    # Output directory
    if args.output:
        out_dir = Path(args.output)
    else:
        out_dir = pattern_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern_name = pattern_path.stem

    print("=" * 60)
    print("WoolyGraphs Layout Pipeline")
    print("=" * 60)
    print(f"  Pattern: {pattern_path}")
    print(f"  Output:  {out_dir}")
    print(f"  Domain:  {args.domain}")
    print()

    # ------------------------------------------------------------------
    # Step 1: Parse pattern
    # ------------------------------------------------------------------
    print("[Phase 1] Parsing pattern...")
    tokens = parse_pattern(str(pattern_path))
    print(f"  Tokens: {len(tokens)} ({', '.join(set(tokens))})")

    # ------------------------------------------------------------------
    # Step 2: Load stitch definitions
    # ------------------------------------------------------------------
    stitch_defs = load_stitch_definitions(args.stitches)
    print(f"  Stitch types defined: {len(stitch_defs)}")

    # ------------------------------------------------------------------
    # Step 3: Phase 1 - Compile pattern
    # ------------------------------------------------------------------
    gauge = Gauge(
        stitch_width=args.stitch_width,
        stitch_height=args.stitch_height,
    )

    graph = compile_pattern(tokens, stitch_defs, gauge)
    print(f"  Compiled: {graph.num_stitches} stitches, {len(graph.edge_list())} edges")

    # ------------------------------------------------------------------
    # Step 4: Phase 2 - Optimize (or just compute diagnostics)
    # ------------------------------------------------------------------

    # Build config (needed even for --skip-optimize diagnostics)
    if args.domain == "blocked_flat":
        config = OptimizerConfig.blocked_flat_preset()
    else:
        config = OptimizerConfig()

    config.domain = args.domain
    config.num_iterations = args.iterations
    config.learning_rate = args.lr

    # Override from JSON config if provided
    if args.config:
        with open(args.config, "r") as f:
            overrides = json.load(f)
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

    # Always create optimizer to compute diagnostics
    optimizer = LayoutOptimizer(graph, config)
    initial_positions = optimizer.positions.detach().numpy().copy()

    print("  Computing initial diagnostics...")
    initial_diagnostics = _format_diagnostics(
        optimizer.compute_per_point_diagnostics()
    )

    # Export initial layout with diagnostics
    initial_json = out_dir / f"{pattern_name}_initial.json"
    initial_data = graph.to_json()
    initial_data['diagnostics'] = initial_diagnostics
    with open(str(initial_json), 'w') as f:
        json.dump(initial_data, f, indent=2)
    print(f"  Initial layout saved to {initial_json}")

    if args.skip_optimize:
        print("\n  Skipping Phase 2 (--skip-optimize)")
        final_json = out_dir / f"{pattern_name}.json"
        with open(str(final_json), 'w') as f:
            json.dump(initial_data, f, indent=2)
        print(f"  Final output: {final_json}")
        _print_viewer_command(out_dir, final_json)
        return

    # Run optimization
    print(f"\n[Phase 2] Optimizing layout ({args.domain} domain)...")
    optimized_graph = optimizer.optimize()

    # Compute optimized diagnostics
    print("  Computing optimized diagnostics...")
    opt_diagnostics = _format_diagnostics(
        optimizer.compute_per_point_diagnostics()
    )

    # ------------------------------------------------------------------
    # Step 5: Export results
    # ------------------------------------------------------------------
    final_json = out_dir / f"{pattern_name}.json"
    final_data = optimized_graph.to_json()
    final_data['diagnostics'] = opt_diagnostics
    final_data['initial_positions'] = [
        {'x': float(p[0]), 'y': float(p[1]), 'z': float(p[2])}
        for p in initial_positions
    ]
    with open(str(final_json), 'w') as f:
        json.dump(final_data, f, indent=2)
    print(f"\n  Optimized layout saved to {final_json}")

    # ------------------------------------------------------------------
    # Step 6: Diagnostic plots
    # ------------------------------------------------------------------
    history_path = str(out_dir / f"{pattern_name}_history.png")
    layout_path = str(out_dir / f"{pattern_name}_3d.png")
    optimizer.plot_history(history_path)
    optimizer.visualize_3d(layout_path)

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print(f"  JSON:    {final_json}")
    print(f"  History: {history_path}")
    print(f"  3D Plot: {layout_path}")
    print("=" * 60)

    _print_viewer_command(out_dir, final_json)


def _print_viewer_command(out_dir, json_path):
    """Print the command to launch the 3D viewer."""
    viewer_dir = Path(__file__).parent / "viewer"
    json_name = Path(json_path).name

    # Copy the JSON into the viewer directory if it's not already there
    viewer_json = viewer_dir / json_name
    if viewer_dir.exists() and out_dir.resolve() != viewer_dir.resolve():
        import shutil
        shutil.copy2(json_path, viewer_json)

    print()
    print("To view in 3D:")
    print(f"  cd {viewer_dir} && python -m http.server 8080")
    print(f"  open http://localhost:8080?file={json_name}")


if __name__ == "__main__":
    main()
