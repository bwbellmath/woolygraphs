"""
Generate TikZ code for knitting visualizations.

Produces three diagrams:
1. Stitch graph — one vertex per stitch, edges for horizontal (same row)
   and vertical (row-to-row) connections.
2. Yarn graph — directed multigraph following the continuous yarn path,
   edges labeled by sequential order along the yarn.
3. Crossing diagram — shows over/under crossings at each point where the
   yarn path crosses itself, suitable for extracting a knot diagram.
"""

from typing import List, Tuple, Dict, Optional
from ..graph import KnitGraph, GraphEdge, pattern_to_graph


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _stitch_coords(graph: KnitGraph, scale: float = 1.2) -> Dict[int, Tuple[float, float]]:
    """
    Assign (x, y) coordinates to every stitch in the graph.

    Layout: row 0 at the top (highest y).  In flat knitting the working
    direction alternates each row, so stitches in even rows run left→right
    and odd rows run right→left.  We place them so that vertically
    connected stitches line up (column position determined by the vertical
    edges in the stitch graph).
    """
    coords: Dict[int, Tuple[float, float]] = {}

    if not graph.row_indices:
        for sid in range(graph.n_stitches):
            coords[sid] = (sid * scale, 0)
        return coords

    # Find the maximum row width for alignment
    max_width = max(len(row) for row in graph.row_indices)

    # Build a map: for each stitch, which stitch is directly above/below it
    # via vertical edges.  This lets us align columns properly.
    v_child: Dict[int, List[int]] = {}  # old_stitch -> [new_stitches]
    v_parent: Dict[int, int] = {}       # new_stitch -> old_stitch
    for edge in graph.edges:
        if edge.orient == 'v':
            v_child.setdefault(edge.i, []).append(edge.j)
            v_parent[edge.j] = edge.i

    # Row 0 (cast-on): always left to right, columns 0..n-1
    for col_idx, stitch_id in enumerate(graph.row_indices[0]):
        coords[stitch_id] = (col_idx * scale, 0)

    # Subsequent rows: try to align each stitch below its parent
    for row_idx in range(1, len(graph.row_indices)):
        y = -row_idx * scale
        row_stitches = graph.row_indices[row_idx]

        # Try to inherit x from parent via vertical edge
        placed_in_row: Dict[int, float] = {}
        for stitch_id in row_stitches:
            parent = v_parent.get(stitch_id)
            if parent is not None and parent in coords:
                placed_in_row[stitch_id] = coords[parent][0]

        # For stitches without a parent match, interpolate
        if placed_in_row:
            # Fill in any gaps with sequential placement
            for col_idx, stitch_id in enumerate(row_stitches):
                if stitch_id not in placed_in_row:
                    placed_in_row[stitch_id] = col_idx * scale
        else:
            # Fallback: sequential placement
            for col_idx, stitch_id in enumerate(row_stitches):
                placed_in_row[stitch_id] = col_idx * scale

        for stitch_id, x in placed_in_row.items():
            coords[stitch_id] = (x, y)

    # Assign coords to any stitches not captured in row_indices
    placed = set(coords.keys())
    for sid in range(graph.n_stitches):
        if sid not in placed:
            coords[sid] = (sid * scale, -len(graph.row_indices) * scale)

    return coords


# ---------------------------------------------------------------------------
# Yarn path construction
# ---------------------------------------------------------------------------

def _build_yarn_path(graph: KnitGraph) -> List[int]:
    """
    Build the sequential yarn path through the stitches.

    In flat knitting the yarn visits stitches in creation order
    (the stitch index IS the yarn-visit order), since each stitch
    is formed exactly when the yarn arrives at it.

    Returns a list of stitch indices in the order the yarn visits them.
    """
    return list(range(graph.n_stitches))


# ---------------------------------------------------------------------------
# Crossing detection
# ---------------------------------------------------------------------------

class Crossing:
    """A crossing where the yarn passes over or under itself."""
    __slots__ = ('x', 'y', 'over_seg', 'under_seg', 'sign')

    def __init__(self, x: float, y: float,
                 over_seg: Tuple[int, int],
                 under_seg: Tuple[int, int],
                 sign: int):
        self.x = x
        self.y = y
        self.over_seg = over_seg    # (yarn_order_a, yarn_order_b)
        self.under_seg = under_seg  # (yarn_order_a, yarn_order_b)
        self.sign = sign            # +1 or -1 (crossing sign)


def _detect_crossings(
    graph: KnitGraph,
    yarn_path: List[int],
    coords: Dict[int, Tuple[float, float]]
) -> List[Crossing]:
    """
    Detect crossings from the yarn path through the stitch graph.

    At each knit stitch the working yarn comes from behind the work,
    passes through the loop of the stitch below, and exits in front.
    The two legs of the old loop cross the working yarn, producing
    two crossings per stitch (one on each side of the old loop).

    For a knit stitch the working yarn goes UNDER the right leg of
    the old loop and OVER the left leg (when viewed from the front).
    For a purl stitch the crossings are reversed.

    We model one crossing per vertical edge (each vertical edge
    represents the yarn passing through an old loop).
    """
    crossings: List[Crossing] = []

    # Map stitch index to its position in the yarn path
    yarn_order = {s: i for i, s in enumerate(yarn_path)}

    for edge in graph.edges:
        if edge.orient != 'v':
            continue

        # edge.i is the old (lower) stitch, edge.j is the new (upper) stitch
        old_s = edge.i
        new_s = edge.j

        if old_s not in coords or new_s not in coords:
            continue

        ox, oy = coords[old_s]
        nx, ny = coords[new_s]

        # Crossing location: midpoint of the vertical edge
        cx = (ox + nx) / 2
        cy = (oy + ny) / 2

        # Determine over/under based on stitch character
        char = graph.stitch_characters[new_s] if new_s < len(graph.stitch_characters) else 'k'

        # The "working yarn" segment: the horizontal movement arriving at new_s
        # The "old loop" segment: the vertical connection from old_s
        old_order = yarn_order.get(old_s, old_s)
        new_order = yarn_order.get(new_s, new_s)

        if char == 'k':
            # Knit: working yarn goes under old loop (old loop is over)
            crossings.append(Crossing(
                x=cx, y=cy,
                over_seg=(old_order, old_order),
                under_seg=(new_order, new_order),
                sign=+1
            ))
        else:
            # Purl: working yarn goes over old loop
            crossings.append(Crossing(
                x=cx, y=cy,
                over_seg=(new_order, new_order),
                under_seg=(old_order, old_order),
                sign=-1
            ))

    return crossings


# ---------------------------------------------------------------------------
# TikZ generation
# ---------------------------------------------------------------------------

def _tikz_header() -> str:
    return r"""\usetikzlibrary{arrows.meta, decorations.markings, calc, positioning}

\tikzset{
  stitch node/.style={circle, draw, fill=white, inner sep=2pt,
                      minimum size=14pt, font=\footnotesize},
  knit node/.style={stitch node, fill=blue!10},
  purl node/.style={stitch node, fill=red!10},
  h edge/.style={thick, blue!60},
  v edge/.style={thick, red!60},
  yarn/.style={very thick, orange!80!black,
               decoration={markings,
                 mark=at position 0.55 with {\arrow{Stealth[length=4pt]}}},
               postaction={decorate}},
  yarn label/.style={font=\tiny, fill=white, inner sep=1pt, opacity=0.9,
                     text opacity=1},
  crossing over/.style={line width=3pt, white, line cap=round},
  crossing strand/.style={very thick, purple!70!black},
  over marker/.style={circle, fill=green!20, draw=green!60!black,
                      minimum size=8pt, inner sep=0pt, font=\tiny},
  under marker/.style={circle, fill=yellow!20, draw=yellow!60!black,
                       minimum size=8pt, inner sep=0pt, font=\tiny},
}
"""


def _generate_graph_tikz(
    prefix: str,
    title: str,
    graph: KnitGraph,
    coords: Dict[int, Tuple[float, float]],
    x_off: float,
    y_off: float,
    draw_edges: bool = True,
    draw_yarn: bool = False,
    draw_crossings: bool = False,
    scale: float = 1.2,
) -> List[str]:
    """
    Core renderer used by all three diagrams.

    prefix: node name prefix (e.g. 's', 'y', 'c') to avoid TikZ name clashes.
    """
    lines: List[str] = []
    lines.append(f"  % --- {title} ---")
    lines.append(
        f"  \\node[anchor=south west, font=\\bfseries] "
        f"at ({x_off - 0.5:.2f},{y_off + 0.8:.2f}) {{{title}}};"
    )

    def c(sid: int) -> Tuple[float, float]:
        x, y = coords[sid]
        return (x + x_off, y + y_off)

    # 1. Stitch-graph edges (undirected, horizontal + vertical)
    if draw_edges:
        for edge in graph.edges:
            if edge.i in coords and edge.j in coords:
                style = "h edge" if edge.orient == 'h' else "v edge"
                xi, yi = c(edge.i)
                xj, yj = c(edge.j)
                lines.append(
                    f"  \\draw[{style}] ({xi:.2f},{yi:.2f})"
                    f" -- ({xj:.2f},{yj:.2f});"
                )

    # 2. Yarn path (directed, sequential)
    if draw_yarn:
        yarn_path = _build_yarn_path(graph)
        for seg_idx in range(len(yarn_path) - 1):
            s_from = yarn_path[seg_idx]
            s_to = yarn_path[seg_idx + 1]
            if s_from not in coords or s_to not in coords:
                continue
            x1, y1 = c(s_from)
            x2, y2 = c(s_to)

            # If the two stitches are in different rows, the yarn wraps
            # around the fabric edge — draw as a curved edge
            same_row = False
            for row in graph.row_indices:
                if s_from in row and s_to in row:
                    same_row = True
                    break

            if same_row:
                lines.append(
                    f"  \\draw[yarn] ({x1:.2f},{y1:.2f}) -- ({x2:.2f},{y2:.2f})"
                    f"    node[yarn label, midway] {{{seg_idx + 1}}};"
                )
            else:
                # Curved wrap-around edge at the fabric selvage
                # Bend direction based on whether wrapping left or right
                bend = "right" if x1 > x2 else "left"
                lines.append(
                    f"  \\draw[yarn, bend {bend}=40] ({x1:.2f},{y1:.2f})"
                    f" to node[yarn label, near start] {{{seg_idx + 1}}}"
                    f" ({x2:.2f},{y2:.2f});"
                )

    # 3. Crossing diagram overlays
    if draw_crossings:
        yarn_path = _build_yarn_path(graph)

        # Draw yarn path (no labels, just the path)
        for seg_idx in range(len(yarn_path) - 1):
            s_from = yarn_path[seg_idx]
            s_to = yarn_path[seg_idx + 1]
            if s_from not in coords or s_to not in coords:
                continue
            x1, y1 = c(s_from)
            x2, y2 = c(s_to)
            same_row = any(
                s_from in row and s_to in row
                for row in graph.row_indices
            )
            if same_row:
                lines.append(
                    f"  \\draw[yarn] ({x1:.2f},{y1:.2f}) -- ({x2:.2f},{y2:.2f});"
                )
            else:
                bend = "right" if x1 > x2 else "left"
                lines.append(
                    f"  \\draw[yarn, bend {bend}=40] ({x1:.2f},{y1:.2f})"
                    f" to ({x2:.2f},{y2:.2f});"
                )

        # Draw old-loop strands (vertical edges as purple)
        for edge in graph.edges:
            if edge.orient != 'v':
                continue
            if edge.i not in coords or edge.j not in coords:
                continue
            xi, yi = c(edge.i)
            xj, yj = c(edge.j)
            lines.append(
                f"  \\draw[crossing strand] ({xi:.2f},{yi:.2f})"
                f" -- ({xj:.2f},{yj:.2f});"
            )

        # Mark crossing points
        crossings = _detect_crossings(graph, yarn_path, coords)
        for ci, cr in enumerate(crossings):
            cx_pos = cr.x + x_off
            cy_pos = cr.y + y_off
            marker = "over marker" if cr.sign > 0 else "under marker"
            label = "+" if cr.sign > 0 else "$-$"
            lines.append(
                f"  \\node[{marker}] (cr{ci}) at ({cx_pos:.2f},{cy_pos:.2f}) {{{label}}};"
            )

    # Draw stitch nodes on top of everything
    for sid in range(graph.n_stitches):
        if sid not in coords:
            continue
        x, y = c(sid)
        char = graph.stitch_characters[sid] if sid < len(graph.stitch_characters) else 'k'
        style = "knit node" if char == 'k' else "purl node"
        lines.append(
            f"  \\node[{style}] ({prefix}{sid}) at ({x:.2f},{y:.2f}) {{{sid}}};"
        )

    return lines


def generate_full_tikz(
    graph: KnitGraph,
    scale: float = 1.2
) -> str:
    """
    Generate a complete TikZ document with all three diagrams
    arranged in a single tikzpicture.

    Layout:
      - Stitch graph at top-left  (x=0)
      - Yarn graph at top-right   (x offset by fabric width + gap)
      - Crossing diagram below    (y offset below the stitch graph)
    """
    coords = _stitch_coords(graph, scale)
    n_rows = len(graph.row_indices)
    max_cols = max(len(row) for row in graph.row_indices) if graph.row_indices else 1

    fabric_w = (max_cols - 1) * scale + 2  # width of one diagram + padding
    fabric_h = (n_rows - 1) * scale + 2

    header = _tikz_header()

    all_lines: List[str] = []
    all_lines.append(r"\begin{tikzpicture}[scale=1]")

    # 1. Stitch graph (top-left)
    all_lines.extend(_generate_graph_tikz(
        prefix="s", title="Stitch Graph",
        graph=graph, coords=coords,
        x_off=0, y_off=0,
        draw_edges=True, draw_yarn=False, draw_crossings=False,
        scale=scale,
    ))

    # 2. Yarn graph (top-right, offset horizontally)
    all_lines.extend(_generate_graph_tikz(
        prefix="y", title="Yarn Graph",
        graph=graph, coords=coords,
        x_off=fabric_w + 2, y_off=0,
        draw_edges=False, draw_yarn=True, draw_crossings=False,
        scale=scale,
    ))

    # 3. Crossing diagram (below, centered)
    cross_y_off = -(fabric_h + 2)
    all_lines.extend(_generate_graph_tikz(
        prefix="c", title="Crossing Diagram (Yarn Crossing Presentation)",
        graph=graph, coords=coords,
        x_off=0, y_off=cross_y_off,
        draw_edges=False, draw_yarn=False, draw_crossings=True,
        scale=scale,
    ))

    # Legend below crossing diagram
    legend_y = cross_y_off - n_rows * scale - 1
    all_lines.append(
        f"  \\node[anchor=north west, font=\\footnotesize] at (-0.5,{legend_y:.1f}) {{"
    )
    all_lines.append(
        r"    \textcolor{green!60!black}{$+$} = knit (working yarn under old loop) \quad"
    )
    all_lines.append(
        r"    \textcolor{yellow!60!black}{$-$} = purl (working yarn over old loop)"
    )
    all_lines.append(r"  };")

    all_lines.append(r"\end{tikzpicture}")
    body = "\n".join(all_lines)

    doc = rf"""\documentclass[border=10pt]{{standalone}}
\usepackage{{tikz}}
{header}
\begin{{document}}

% ============================================================
% Knitting Visualization: Three Graph Layers
% Pattern: {graph.n_stitches} stitches, {n_rows} rows, topology: {graph.topology}
% ============================================================
%
% 1. STITCH GRAPH: one vertex per stitch, undirected edges
%    - Blue (h) edges: horizontal (within-row adjacency)
%    - Red (v) edges: vertical (row-to-row, through old loop)
%
% 2. YARN GRAPH: directed multigraph following the continuous yarn
%    - Orange arrows: yarn path in sequential creation order
%    - Curved edges: yarn wrapping around fabric selvage between rows
%    - Edge labels: position along the yarn
%
% 3. CROSSING DIAGRAM: yarn crossing presentation
%    - Orange: working yarn path
%    - Purple: old-loop strands (vertical connections)
%    - Green (+): knit crossing (working yarn under old loop)
%    - Yellow (-): purl crossing (working yarn over old loop)

{body}

\end{{document}}
"""
    return doc


def generate_tikz_from_pattern(
    pattern_path: str,
    output_path: Optional[str] = None,
    scale: float = 1.2
) -> str:
    """
    End-to-end: pattern file -> TikZ LaTeX document.

    Args:
        pattern_path: Path to .txt pattern file.
        output_path: If provided, writes the .tex file here.
        scale: Spacing between stitches.

    Returns:
        The generated LaTeX string.
    """
    graph = pattern_to_graph(pattern_path)
    tex = generate_full_tikz(graph, scale)

    if output_path is not None:
        with open(output_path, 'w') as f:
            f.write(tex)
        print(f"Wrote TikZ to {output_path}")

    return tex
