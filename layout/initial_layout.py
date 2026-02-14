"""
WoolyGraphs Phase 1: Initial Layout ("Compilation")

Converts a text-based knitting pattern into a LayoutGraph with
positioned and connected stitch instances.

The pattern is treated like source code that gets "compiled" into
a graph with 3D positions, normals, and edge connectivity.
"""

import ast
import numpy as np
from pathlib import Path

from layout.stitch_instance import StitchInstance, BackEdge, Gauge, LayoutGraph


def load_stitch_definitions(path: str = None) -> dict:
    """
    Load stitch definitions from stitches_2.txt.

    Returns dict mapping stitch name -> {character, kill, add, cursor_dir, offsets}
    """
    if path is None:
        # Search relative to this file, then cwd
        candidates = [
            Path(__file__).parent.parent / "stitches_2.txt",
            Path("stitches_2.txt"),
        ]
        for c in candidates:
            if c.exists():
                path = str(c)
                break
        else:
            raise FileNotFoundError("Cannot find stitches_2.txt")

    with open(path, "r") as f:
        contents = f.read()

    sdict = ast.literal_eval(contents)

    # Ensure all entries have offsets
    for key in sdict:
        if "offsets" not in sdict[key]:
            sdict[key]["offsets"] = {"normal": 0.0, "right_left": 0.0, "up_down": 0.0}

    return sdict


def parse_pattern(pattern_file: str) -> list:
    """
    Parse a pattern file into a flat list of stitch tokens.

    Each line is a row of stitches separated by spaces.
    Lines are concatenated with 'turn' tokens already embedded.

    Args:
        pattern_file: path to pattern .txt file

    Returns:
        list of stitch name strings
    """
    with open(pattern_file, "r") as f:
        lines = f.readlines()

    tokens = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # Filter empty strings
        parts = [p.strip() for p in parts if p.strip()]
        tokens.extend(parts)

    return tokens


def _normalize(v):
    """Normalize a vector, returning zero vector if input is zero."""
    n = np.linalg.norm(v)
    if n < 1e-10:
        return np.zeros_like(v)
    return v / n


def compile_pattern(tokens: list, stitch_defs: dict, gauge: Gauge = None) -> LayoutGraph:
    """
    Compile a pattern token list into a LayoutGraph.

    This is the core Phase 1 algorithm. It simulates the knitting process:
    - Manages left/right needles
    - Creates stitch instances with positions, normals, and edges
    - Handles turns (direction changes)
    - Wires up horizontal (h) and vertical (v) edges

    Args:
        tokens:      flat list of stitch name strings
        stitch_defs: dict from load_stitch_definitions()
        gauge:       Gauge instance (defaults to standard gauge)

    Returns:
        LayoutGraph with all stitches positioned and connected
    """
    if gauge is None:
        gauge = Gauge()

    stitches = []
    left_needle = []     # stitches on left needle (to be consumed)
    right_needle = []    # stitches on right needle (newly created)
    count = 0            # total stitch count
    edge_flag = True     # True = next stitch is first on a row (no h-edge)
    progression = 1      # +1 = knitting right-to-left, flips on turn
    row = 0
    col = 0

    # Default frame
    current_normal = np.array([0.0, 0.0, 1.0])

    for token in tokens:
        if token not in stitch_defs:
            raise ValueError(f"Unknown stitch type: {token}")

        sdef = stitch_defs[token]

        # --- TURN ---
        if sdef["cursor_dir"]:
            tmp = left_needle.copy()
            left_needle = right_needle.copy()
            right_needle = tmp.copy()
            progression *= -1
            edge_flag = True
            row += 1
            col = 0
            continue

        # --- ADD stitches ---
        added_indices = []
        for a in range(sdef["add"]):
            # Compute position
            pos = _compute_initial_position(
                count, stitches, left_needle, gauge,
                current_normal, progression, row, col
            )

            # Compute normal
            normal = _compute_initial_normal(
                count, stitches, sdef, current_normal
            )

            # Get offsets
            offsets = sdef.get("offsets", {"normal": 0.0, "right_left": 0.0, "up_down": 0.0})

            # Create instance
            inst = StitchInstance(
                index=count,
                stitch_type=token,
                character=sdef["character"],
                position=pos.copy(),
                normal=normal.copy(),
                back_edges=[],
                offset_normal=offsets["normal"] * gauge.stitch_height,
                offset_right_left=offsets["right_left"] * gauge.stitch_width,
                offset_up_down=offsets["up_down"] * gauge.stitch_height,
                row=row,
                col=col,
            )

            # Horizontal edge to previous stitch on same row
            if not edge_flag:
                inst.back_edges.append(BackEdge(
                    target_index=count - 1,
                    orientation="h",
                    rest_length=gauge.stitch_width,
                    bump=False,
                ))
            else:
                edge_flag = False

            right_needle.append(count)
            added_indices.append(count)
            stitches.append(inst)
            count += 1
            col += 1

        # --- KILL stitches (consume from left needle) ---
        for k in range(sdef["kill"]):
            if len(left_needle) == 0:
                break
            used_st = left_needle.pop()
            # Connect all added stitches to the consumed stitch (vertical edges)
            for added_idx in added_indices:
                stitches[added_idx].back_edges.append(BackEdge(
                    target_index=used_st,
                    orientation="v",
                    rest_length=gauge.stitch_height,
                    bump=True,
                ))

    # Compute derived vectors for all stitches
    _compute_derived_frames(stitches)

    return LayoutGraph(stitches)


def _compute_initial_position(count, stitches, left_needle, gauge,
                               current_normal, progression, row, col):
    """
    Place each new stitch relative to its neighbors.

    First stitch at origin. Subsequent stitches step along the row
    (horizontal) and are offset vertically if they have below-neighbors.
    """
    if count == 0:
        return np.array([0.0, 0.0, 0.0])

    # Horizontal placement: step from previous stitch
    prev = stitches[count - 1]
    r_hat = np.array([1.0, 0.0, 0.0]) * progression

    # If we have a previous stitch on the same row, step from it
    base_pos = prev.position + gauge.stitch_width * r_hat

    # If we have a below-neighbor (from the left needle), blend toward it
    if len(left_needle) > 0:
        below_idx = left_needle[-1]
        below = stitches[below_idx]
        # Use the below stitch position + height offset
        u_hat = np.array([0.0, 1.0, 0.0])
        below_pos = below.position + gauge.stitch_height * u_hat

        # Blend: prefer the below position for vertical alignment,
        # but keep horizontal spacing from the previous stitch
        base_pos[1] = below_pos[1]  # y from below
        # x from horizontal stepping
        if col == 0:
            # First stitch in row: use below's x position
            base_pos[0] = below.position[0]

    return base_pos


def _compute_initial_normal(count, stitches, sdef, current_normal):
    """
    Compute initial normal for a new stitch.

    Starts with the current normal and adjusts slightly based on stitch type.
    """
    normal = current_normal.copy()

    # For purl stitches, flip the normal slightly
    if sdef["character"] == "p":
        normal[2] = -abs(normal[2])
    else:
        normal[2] = abs(normal[2])

    return _normalize(normal)


def _compute_derived_frames(stitches):
    """
    Compute right_left and up_down vectors for all stitches
    based on their neighbors.
    """
    for s in stitches:
        # Find horizontal neighbors
        h_targets = [e.target_index for e in s.back_edges if e.orientation == "h"]

        if len(h_targets) > 0:
            # right_left = direction to horizontal neighbor
            h_pos = stitches[h_targets[0]].position
            r = h_pos - s.position
            r_norm = np.linalg.norm(r)
            if r_norm > 1e-10:
                s.right_left = r / r_norm
            else:
                s.right_left = np.array([1.0, 0.0, 0.0])
        else:
            s.right_left = np.array([1.0, 0.0, 0.0])

        # up_down = normal x right_left
        s.up_down = np.cross(s.normal, s.right_left)
        ud_norm = np.linalg.norm(s.up_down)
        if ud_norm > 1e-10:
            s.up_down = s.up_down / ud_norm
        else:
            s.up_down = np.array([0.0, 1.0, 0.0])
