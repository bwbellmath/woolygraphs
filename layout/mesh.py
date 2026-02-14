"""
WoolyGraphs Mesh Construction & Solid-Angle Flatness

Builds a triangle mesh from the stitch graph for solid-angle-based
flatness computation.

Key concepts:
- Quad faces formed by adjacent horizontal/vertical edges are split into triangles
- Solid angle at each interior vertex should sum to 2*pi for a flat surface
- Van Oosterom-Strackee formula for solid angle computation
"""

import torch
import numpy as np
from collections import defaultdict


def build_triangulation(positions, edge_indices, edge_orientations, rows=None, cols=None):
    """
    Build triangle mesh from the stitch graph.

    For grid-like regions, quads formed by adjacent h/v edges are split
    into two triangles. For non-grid regions, falls back to neighbor-based
    triangulation.

    Args:
        positions:         (N, 3) numpy array
        edge_indices:      (E, 2) numpy array
        edge_orientations: list of 'h'/'v' per edge
        rows:              optional (N,) array of row indices per stitch
        cols:              optional (N,) array of col indices per stitch

    Returns:
        triangles: list of (i, j, k) index triples
    """
    N = positions.shape[0]

    # Build adjacency by orientation
    h_neighbors = defaultdict(set)  # horizontal neighbors
    v_neighbors = defaultdict(set)  # vertical neighbors

    for idx in range(edge_indices.shape[0]):
        i, j = int(edge_indices[idx, 0]), int(edge_indices[idx, 1])
        orient = edge_orientations[idx]
        if orient == 'h':
            h_neighbors[i].add(j)
            h_neighbors[j].add(i)
        else:  # 'v'
            v_neighbors[i].add(j)
            v_neighbors[j].add(i)

    triangles = []
    seen_quads = set()

    # For each node, try to find quads: (i, h_neighbor, v_neighbor, diagonal)
    for i in range(N):
        for h_nbr in h_neighbors[i]:
            for v_nbr in v_neighbors[i]:
                # Look for the diagonal: node that is both h-neighbor of v_nbr
                # and v-neighbor of h_nbr
                diag_candidates = h_neighbors[v_nbr] & v_neighbors[h_nbr]
                for diag in diag_candidates:
                    if diag == i:
                        continue
                    # Found a quad: (i, h_nbr, diag, v_nbr)
                    quad = tuple(sorted([i, h_nbr, diag, v_nbr]))
                    if quad not in seen_quads:
                        seen_quads.add(quad)
                        # Split into two triangles
                        # Triangle 1: i, h_nbr, v_nbr
                        # Triangle 2: h_nbr, diag, v_nbr
                        triangles.append((i, h_nbr, v_nbr))
                        triangles.append((h_nbr, diag, v_nbr))

    # If no quads found (degenerate case), create triangles from all edge triples
    if len(triangles) == 0:
        all_neighbors = defaultdict(set)
        for idx in range(edge_indices.shape[0]):
            i, j = int(edge_indices[idx, 0]), int(edge_indices[idx, 1])
            all_neighbors[i].add(j)
            all_neighbors[j].add(i)

        seen_tris = set()
        for i in range(N):
            nbrs_i = list(all_neighbors[i])
            for a_idx in range(len(nbrs_i)):
                for b_idx in range(a_idx + 1, len(nbrs_i)):
                    a, b = nbrs_i[a_idx], nbrs_i[b_idx]
                    if b in all_neighbors[a]:
                        tri = tuple(sorted([i, a, b]))
                        if tri not in seen_tris:
                            seen_tris.add(tri)
                            triangles.append(tri)

    return triangles


def solid_angle_at_vertex(vertex_pos, triangle_positions):
    """
    Compute solid angle subtended by a triangle as seen from a vertex,
    using the Van Oosterom-Strackee formula.

    Omega = 2 * atan2(a . (b x c), 1 + a.b + b.c + c.a)

    where a, b, c are unit vectors from vertex to triangle corners.

    Args:
        vertex_pos:         (3,) tensor - the vertex position
        triangle_positions: (3, 3) tensor - positions of the three triangle corners

    Returns:
        Scalar tensor: solid angle in radians
    """
    # Unit vectors from vertex to triangle corners
    vecs = triangle_positions - vertex_pos.unsqueeze(0)  # (3, 3)
    norms = torch.norm(vecs, dim=1, keepdim=True).clamp(min=1e-8)  # (3, 1)
    unit_vecs = vecs / norms  # (3, 3)

    a, b, c = unit_vecs[0], unit_vecs[1], unit_vecs[2]

    # Van Oosterom-Strackee
    numerator = torch.dot(a, torch.cross(b, c))
    denominator = 1.0 + torch.dot(a, b) + torch.dot(b, c) + torch.dot(c, a)

    # Use atan2 for numerical stability
    omega = 2.0 * torch.atan2(numerator, denominator)
    return omega


def flatness_energy(positions, triangles, interior_mask=None):
    """
    Solid-angle-based flatness energy.

    For each interior vertex, the sum of solid angles of adjacent triangles
    should equal 2*pi (flat surface).

    Loss = sum_{i in interior} (sum_t Omega_t(p_i) - 2*pi)^2

    Args:
        positions:     (N, 3) tensor
        triangles:     list of (i, j, k) index triples
        interior_mask: optional (N,) bool tensor - True for interior vertices
                       If None, all vertices with >= 3 adjacent triangles
                       are considered interior.

    Returns:
        Scalar tensor: flatness energy
    """
    N = positions.shape[0]

    if len(triangles) == 0:
        return torch.tensor(0.0, dtype=positions.dtype)

    # Build vertex -> adjacent triangles mapping
    vertex_triangles = defaultdict(list)
    for tri_idx, (i, j, k) in enumerate(triangles):
        vertex_triangles[i].append(tri_idx)
        vertex_triangles[j].append(tri_idx)
        vertex_triangles[k].append(tri_idx)

    # Determine interior vertices using boundary detection.
    # A vertex is interior if the face angles around it form a full ring
    # (sum ~2pi). Boundary vertices have fewer adjacent triangles and
    # their angles sum to less than 2pi, so we exclude them.
    if interior_mask is None:
        # Use edge valence to detect boundary: boundary vertices have
        # fewer edge connections. Build full adjacency for valence count.
        all_adj = defaultdict(set)
        for idx in range(len(triangles)):
            i, j, k = triangles[idx]
            all_adj[i].update([j, k])
            all_adj[j].update([i, k])
            all_adj[k].update([i, j])

        # Interior vertices: those with enough adjacent triangles that
        # form a closed fan. Heuristic: valence >= 4 in the mesh.
        interior_mask = torch.zeros(N, dtype=torch.bool)
        for v in range(N):
            # Need at least as many triangles as edges (closed fan)
            if len(vertex_triangles[v]) >= 4 and len(all_adj[v]) >= 4:
                interior_mask[v] = True

    triangles_tensor = torch.tensor(triangles, dtype=torch.long)  # (T, 3)

    loss = torch.tensor(0.0, dtype=positions.dtype)
    two_pi = 2.0 * np.pi

    for v in range(N):
        if not interior_mask[v]:
            continue

        adj_tris = vertex_triangles[v]
        if len(adj_tris) == 0:
            continue

        total_angle = torch.tensor(0.0, dtype=positions.dtype)

        for tri_idx in adj_tris:
            tri = triangles_tensor[tri_idx]
            # Get the other two vertices of this triangle
            others = [int(idx) for idx in tri if int(idx) != v]
            if len(others) != 2:
                continue

            tri_positions = positions[others + [others[0]]]  # dummy, won't use
            # Actually get the 3 corner positions excluding vertex v
            corner_positions = positions[torch.tensor(others, dtype=torch.long)]  # (2, 3)

            # For solid angle, we need the triangle corners (not the vertex itself)
            # But solid_angle_at_vertex expects positions of the 3 corners
            # and the vertex is the "observer"
            # The triangle has corners: the 2 "others" plus... actually the vertex IS
            # one corner. The solid angle is measured at the vertex, looking at the
            # opposite edge. This is actually a 2D angle (face angle), not solid angle.
            # For a planar surface, the sum of face angles around a vertex = 2*pi.

            # Compute the face angle at vertex v in this triangle
            # using atan2(|cross|, dot) for numerical stability
            # (acos has infinite gradient at ±1)
            p_v = positions[v]
            p_a = positions[others[0]]
            p_b = positions[others[1]]

            va = p_a - p_v
            vb = p_b - p_v

            cross = torch.cross(va, vb)
            sin_val = torch.norm(cross).clamp(min=1e-8)
            cos_val = torch.dot(va, vb)
            angle = torch.atan2(sin_val, cos_val)

            total_angle = total_angle + angle

        deviation = total_angle - two_pi
        loss = loss + deviation ** 2

    return loss


def get_boundary_vertices(edge_indices, num_vertices):
    """
    Identify boundary vertices (vertices on the edge of the mesh).

    A vertex is on the boundary if it has fewer connections or
    if its adjacent edges don't form a closed fan.

    Simple heuristic: vertices with valence < 4 are boundary.

    Args:
        edge_indices: (E, 2) numpy array
        num_vertices: int

    Returns:
        boundary: set of vertex indices
    """
    valence = np.zeros(num_vertices, dtype=int)
    for i in range(edge_indices.shape[0]):
        valence[edge_indices[i, 0]] += 1
        valence[edge_indices[i, 1]] += 1

    # Boundary = low valence (< 4 for a grid-like mesh)
    boundary = set(np.where(valence < 4)[0])
    return boundary
