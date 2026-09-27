"""
Baseline layout computation.

Computes initial vertex positions for a knit graph using O(n) per-stitch
algorithms. Supports flat, circular, and mobius topologies.
"""

import numpy as np
from typing import Optional, Tuple, List
from dataclasses import dataclass

from .graph import KnitGraph, GraphEdge
from .config import LayoutConfig


@dataclass
class LayoutResult:
    """
    Result of baseline layout computation.

    Attributes:
        positions: (n_stitches, 3) array of xyz coordinates in mm
        graph: The input KnitGraph
        config: The configuration used
    """
    positions: np.ndarray
    graph: KnitGraph
    config: LayoutConfig


def compute_baseline_positions(
    graph: KnitGraph,
    config: Optional[LayoutConfig] = None
) -> np.ndarray:
    """
    Compute initial positions for all stitches.

    Uses O(n) per-stitch placement based on layout mode:
    - flat: Linear rows with alternating direction
    - circular: Stitches arranged around cylinder
    - mobius: Stitches arranged on mobius strip

    Args:
        graph: KnitGraph to lay out
        config: Layout configuration. If None, uses default flat config.

    Returns:
        (n_stitches, 3) array of xyz coordinates in millimeters.
    """
    if config is None:
        config = LayoutConfig.default_flat()

    if config.layout_mode == 'circular' or graph.topology in ('circular', 'mobius'):
        if config.topology.mobius or graph.topology == 'mobius':
            positions = _mobius_layout(graph, config)
        else:
            positions = _circular_layout(graph, config)
    else:
        positions = _flat_layout(graph, config)

    # Apply any local adjustments for edge length optimization
    positions = _adjust_for_edge_lengths(graph, positions, config)

    return positions


def _flat_layout(graph: KnitGraph, config: LayoutConfig) -> np.ndarray:
    """
    Compute flat back-and-forth knitting layout.

    Cast-on row along x-axis, subsequent rows offset in y.
    Stitches in each row are positioned to align vertically with
    the stitches they connect to below (proper column alignment).
    """
    h_len = config.edge_lengths.h_length_mm
    v_len = config.edge_lengths.v_length_mm

    positions = np.zeros((graph.n_stitches, 3))

    if not graph.row_indices:
        # Fallback: simple linear layout if no row info
        for i in range(graph.n_stitches):
            positions[i] = [i * h_len, 0, 0]
        return positions

    # First, position cast-on row
    y = 0.0
    for row_idx, row in enumerate(graph.row_indices):
        # Position stitches in order within the row
        # Each stitch gets x based on its position in the row
        for i, stitch_idx in enumerate(row):
            positions[stitch_idx] = [i * h_len, y, 0.0]
        y += v_len

    # Now adjust positions based on vertical edge connections
    # to ensure stitches stack correctly above their parent stitches
    v_edges = graph.get_edges_by_orientation('v')

    # Build a map of which row each stitch is in
    stitch_to_row = {}
    for row_idx, row in enumerate(graph.row_indices):
        for stitch_idx in row:
            stitch_to_row[stitch_idx] = row_idx

    # For each row after the first, position based on vertical connections
    for row_idx in range(1, len(graph.row_indices)):
        row = graph.row_indices[row_idx]

        for stitch_idx in row:
            # Find vertical edges connecting to this stitch
            parent_stitches = []
            for e in v_edges:
                if e.j == stitch_idx:  # This stitch is the child
                    parent_stitches.append(e.i)
                elif e.i == stitch_idx:  # Check reverse too
                    if stitch_to_row.get(e.j, row_idx) < row_idx:
                        parent_stitches.append(e.j)

            if parent_stitches:
                # Position this stitch above its parent(s)
                parent_x = np.mean([positions[p, 0] for p in parent_stitches])
                positions[stitch_idx, 0] = parent_x

    return positions


def _circular_layout(graph: KnitGraph, config: LayoutConfig) -> np.ndarray:
    """
    Compute circular in-the-round layout.

    Cast-on stitches distributed around circle in xy-plane.
    Subsequent rounds stacked in z direction.
    """
    h_len = config.edge_lengths.h_length_mm
    v_len = config.edge_lengths.v_length_mm

    positions = np.zeros((graph.n_stitches, 3))

    if not graph.row_indices:
        # Fallback for no row info
        n = graph.n_stitches
        radius = (n * h_len) / (2 * np.pi)
        for i in range(n):
            theta = (i / n) * 2 * np.pi
            positions[i] = [radius * np.cos(theta), radius * np.sin(theta), 0.0]
        return positions

    # First row determines circumference
    first_row = graph.row_indices[0]
    n_around = len(first_row)
    radius = (n_around * h_len) / (2 * np.pi)

    z = 0.0
    for row_idx, row in enumerate(graph.row_indices):
        n_in_row = len(row)
        for i, stitch_idx in enumerate(row):
            # Angle based on position in row
            theta = (i / n_in_row) * 2 * np.pi
            positions[stitch_idx] = [
                radius * np.cos(theta),
                radius * np.sin(theta),
                z
            ]
        z += v_len

    return positions


def _mobius_layout(graph: KnitGraph, config: LayoutConfig) -> np.ndarray:
    """
    Compute mobius strip layout.

    Like circular, but with a half-twist as we go around.
    The surface normal rotates 180 degrees over one circuit.
    """
    h_len = config.edge_lengths.h_length_mm
    v_len = config.edge_lengths.v_length_mm

    positions = np.zeros((graph.n_stitches, 3))

    if not graph.row_indices:
        n = graph.n_stitches
        radius = (n * h_len) / (2 * np.pi)
        for i in range(n):
            theta = (i / n) * 2 * np.pi
            positions[i] = [radius * np.cos(theta), radius * np.sin(theta), 0.0]
        return positions

    first_row = graph.row_indices[0]
    n_around = len(first_row)
    major_radius = (n_around * h_len) / (2 * np.pi)

    # Minor radius is based on number of rows
    n_rows = len(graph.row_indices)
    strip_width = n_rows * v_len
    minor_radius = strip_width / 2

    for row_idx, row in enumerate(graph.row_indices):
        # v goes from -1 to 1 across the strip width
        v = (row_idx / max(1, n_rows - 1)) * 2 - 1  # -1 to 1

        n_in_row = len(row)
        for i, stitch_idx in enumerate(row):
            # u is the angle around the strip (0 to 2*pi)
            u = (i / n_in_row) * 2 * np.pi

            # Mobius parametric equations
            # The half-twist comes from u/2 in the minor circle
            x = (major_radius + minor_radius * v * np.cos(u / 2)) * np.cos(u)
            y = (major_radius + minor_radius * v * np.cos(u / 2)) * np.sin(u)
            z = minor_radius * v * np.sin(u / 2)

            positions[stitch_idx] = [x, y, z]

    return positions


def _adjust_for_edge_lengths(
    graph: KnitGraph,
    positions: np.ndarray,
    config: LayoutConfig
) -> np.ndarray:
    """
    Perform O(n) adjustments to better match target edge lengths.

    For each stitch in order, compute the optimal position given
    its neighbor positions and target edge lengths.
    """
    if not config.shaping.allow_3d:
        # For 2D layouts, we can't adjust much without breaking the structure
        return positions

    # For 3D layouts, we can perturb z to better match edge lengths
    positions = positions.copy()

    for i in range(graph.n_stitches):
        neighbors = graph.get_neighbors(i)
        if len(neighbors) < 2:
            continue

        # Compute current edge length errors
        total_error = 0.0
        z_adjustment = 0.0

        for j in neighbors:
            edge = graph.get_edge(i, j)
            if edge is None:
                continue

            current_dist = np.linalg.norm(positions[i] - positions[j])
            target_dist = edge.length_mm
            error = current_dist - target_dist

            if current_dist > 1e-8:
                # If we're too far, we'd need to move closer
                # If we're too close, we'd need to move away
                # Use z-perturbation to achieve this
                total_error += abs(error)

        # Simple heuristic: if there's significant error, try z-perturbation
        # This is a placeholder for more sophisticated adjustment
        if total_error > 0.5:  # 0.5mm threshold
            # Check if z-perturbation would help
            for delta_z in [-0.5, 0.5]:
                test_pos = positions[i].copy()
                test_pos[2] += delta_z

                new_error = 0.0
                for j in neighbors:
                    edge = graph.get_edge(i, j)
                    if edge is None:
                        continue
                    new_dist = np.linalg.norm(test_pos - positions[j])
                    new_error += abs(new_dist - edge.length_mm)

                if new_error < total_error:
                    z_adjustment = delta_z
                    total_error = new_error

            positions[i, 2] += z_adjustment

    return positions


def apply_short_row_shaping(
    positions: np.ndarray,
    short_row_indices: List[int],
    profile: str = 'semicircle'
) -> np.ndarray:
    """
    Apply 3D perturbation for short row shaping.

    Computes closed-form z-perturbation to create curvature
    in short row regions.

    Args:
        positions: Current positions array
        short_row_indices: Indices of stitches in short row region
        profile: Shaping profile ('semicircle' or 'catenary')

    Returns:
        Modified positions array
    """
    positions = positions.copy()

    if not short_row_indices:
        return positions

    if profile == 'semicircle':
        # Fit semicircle to short row region
        x_vals = positions[short_row_indices, 0]
        x_min, x_max = x_vals.min(), x_vals.max()
        x_center = (x_min + x_max) / 2
        radius = (x_max - x_min) / 2

        if radius > 1e-8:
            for idx in short_row_indices:
                x = positions[idx, 0]
                # Semicircle: z = sqrt(r^2 - (x - x_center)^2)
                arg = radius**2 - (x - x_center)**2
                if arg > 0:
                    positions[idx, 2] = np.sqrt(arg)

    elif profile == 'catenary':
        # Catenary: z = a * cosh((x - x0) / a) - a
        x_vals = positions[short_row_indices, 0]
        x_center = x_vals.mean()
        x_span = x_vals.max() - x_vals.min()

        if x_span > 1e-8:
            # a parameter controls the "sag"
            a = x_span / 2

            for idx in short_row_indices:
                x = positions[idx, 0]
                positions[idx, 2] = a * (np.cosh((x - x_center) / a) - 1)

    return positions


def compute_baseline_with_result(
    graph: KnitGraph,
    config: Optional[LayoutConfig] = None
) -> LayoutResult:
    """
    Compute baseline positions and return full result object.

    Args:
        graph: KnitGraph to lay out
        config: Layout configuration

    Returns:
        LayoutResult with positions, graph, and config
    """
    if config is None:
        config = LayoutConfig.default_flat()

    positions = compute_baseline_positions(graph, config)

    return LayoutResult(
        positions=positions,
        graph=graph,
        config=config
    )
