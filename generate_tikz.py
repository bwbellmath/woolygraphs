#!/usr/bin/env python3
"""
Generate TikZ knitting visualizations from pattern files.

Usage:
    python generate_tikz.py patterns/small_stockinette.txt [-o output.tex] [--scale 1.2]
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from woolygraphs.export.tikz import generate_tikz_from_pattern


def main():
    parser = argparse.ArgumentParser(
        description="Generate TikZ knitting visualizations from pattern files."
    )
    parser.add_argument("pattern", help="Path to pattern .txt file")
    parser.add_argument("-o", "--output", help="Output .tex file path (default: <pattern_name>_tikz.tex)")
    parser.add_argument("--scale", type=float, default=1.2, help="Spacing scale (default: 1.2)")
    args = parser.parse_args()

    pattern_path = args.pattern
    if args.output:
        output_path = args.output
    else:
        stem = Path(pattern_path).stem
        output_path = f"{stem}_tikz.tex"

    tex = generate_tikz_from_pattern(pattern_path, output_path, args.scale)
    print(f"Generated {output_path} ({len(tex)} bytes)")
    print(f"Compile with: pdflatex {output_path}")


if __name__ == "__main__":
    main()
