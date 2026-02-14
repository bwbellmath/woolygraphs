"""
WoolyGraphs Force Calculations (Vectorized)

Physically-realistic force curves for yarn mechanics in knitting.
All core computations are vectorized with PyTorch tensors.

Force model:
- Elastic region: ±40% stretch with low stiffness
- Plastic region: Beyond 40%, steep force increase + step penalty
- Topology-aware repulsion via adjacency matrix powers
- Normal coherence loss for smooth surfaces
- Out-of-plane flatness: neighbors in fabric plane
- In-plane angle: h/v edges at target angle (default 90°)
"""

import torch
import numpy as np


class YarnForceModel:
    """
    Piecewise elastic/plastic yarn energy model.

    Parameters:
        elastic_limit: fraction of rest length for elastic region (default 0.4)
        k_elastic: spring constant in elastic region
        k_plastic: spring constant beyond elastic limit
        step_penalty: force jump at elastic limit boundary
    """

    def __init__(self,
                 elastic_limit=0.4,
                 k_elastic=0.1,
                 k_plastic=10.0,
                 step_penalty=5.0):
        self.elastic_limit = elastic_limit
        self.k_elastic = k_elastic
        self.k_plastic = k_plastic
        self.step_penalty = step_penalty

    def total_edge_energy_vectorized(self, positions, edge_indices, rest_lengths):
        """
        Vectorized total edge energy.

        Args:
            positions:    (N, 3) tensor
            edge_indices: (E, 2) long tensor
            rest_lengths: (E,) tensor

        Returns:
            Scalar tensor: total edge energy
        """
        if edge_indices.shape[0] == 0:
            return torch.tensor(0.0, dtype=positions.dtype)

        src = positions[edge_indices[:, 0]]          # (E, 3)
        tgt = positions[edge_indices[:, 1]]          # (E, 3)
        diffs = tgt - src                            # (E, 3)
        dists = torch.norm(diffs, dim=1) + 1e-8      # (E,)

        delta = dists - rest_lengths                  # (E,)
        abs_delta = torch.abs(delta)
        threshold = self.elastic_limit * rest_lengths  # (E,)

        # Elastic energy: 0.5 * k_e * delta^2
        elastic = 0.5 * self.k_elastic * delta ** 2

        # Plastic energy
        overshoot = abs_delta - threshold
        plastic = (0.5 * self.k_elastic * threshold ** 2
                   + self.step_penalty * overshoot
                   + 0.5 * self.k_plastic * overshoot ** 2)

        energy = torch.where(abs_delta <= threshold, elastic, plastic)
        return energy.sum()

    def edge_energy_single(self, distance, rest_length):
        """Single-edge energy (for testing/debugging)."""
        delta = distance - rest_length
        abs_delta = torch.abs(delta)
        threshold = self.elastic_limit * rest_length

        elastic = 0.5 * self.k_elastic * delta ** 2
        overshoot = abs_delta - threshold
        plastic = (0.5 * self.k_elastic * threshold ** 2
                   + self.step_penalty * overshoot
                   + 0.5 * self.k_plastic * overshoot ** 2)

        return torch.where(abs_delta <= threshold, elastic, plastic)


class RepulsionModel:
    """
    Topology-aware repulsion using adjacency matrix powers.

    Only repels nodes within k hops in graph topology,
    avoiding expensive O(n^2) all-pairs computation.
    """

    def __init__(self, adjacency_matrix, num_powers=3, strength=50.0):
        """
        Args:
            adjacency_matrix: (N, N) numpy array (0/1)
            num_powers: number of adjacency powers to include
            strength: repulsion strength parameter
        """
        self.num_powers = num_powers
        self.strength = strength

        self.repulsion_matrix = self._compute_repulsion_matrix(adjacency_matrix)
        self.repulsion_pairs = self._get_repulsion_pairs()

        # Pre-compute pair indices as tensors for vectorized computation
        if len(self.repulsion_pairs) > 0:
            pairs_arr = np.array(self.repulsion_pairs, dtype=np.int64)
            self.pair_i = torch.tensor(pairs_arr[:, 0], dtype=torch.long)
            self.pair_j = torch.tensor(pairs_arr[:, 1], dtype=torch.long)
        else:
            self.pair_i = torch.zeros(0, dtype=torch.long)
            self.pair_j = torch.zeros(0, dtype=torch.long)

    def _compute_repulsion_matrix(self, A):
        """
        Compute repulsion matrix from adjacency powers.

        Excludes directly-connected pairs (1-hop): those already have edge
        forces and shouldn't also be repelled. Only 2-hop and beyond pairs
        get repulsion, preventing the optimizer from fighting itself.
        """
        if torch.is_tensor(A):
            A = A.numpy()

        N = A.shape[0]
        A_float = A.astype(float)

        # Accumulate powers starting at 2 (skip direct edges)
        repulsion = np.zeros((N, N))
        A_power = A_float.copy()

        for k in range(1, self.num_powers + 1):
            if k > 1:
                A_power = A_power @ A_float
            if k >= 2:  # only include 2-hop and beyond
                repulsion += (A_power != 0).astype(float)

        repulsion = (repulsion != 0).astype(float)

        # Remove direct edges -- they have edge forces already
        repulsion = repulsion * (1.0 - A_float)
        repulsion = repulsion * (1.0 - A_float.T)

        np.fill_diagonal(repulsion, 0)
        return repulsion

    def _get_repulsion_pairs(self):
        """Get (i, j) pairs with i < j to avoid double-counting."""
        rows, cols = np.nonzero(self.repulsion_matrix)
        return [(i, j) for i, j in zip(rows, cols) if i < j]

    def repulsion_energy(self, positions):
        """
        Vectorized repulsion energy: E = sum k / r^2

        Args:
            positions: (N, 3) tensor

        Returns:
            Scalar tensor
        """
        if len(self.repulsion_pairs) == 0:
            return torch.tensor(0.0, dtype=positions.dtype)

        pos_i = positions[self.pair_i]   # (P, 3)
        pos_j = positions[self.pair_j]   # (P, 3)

        distances = torch.norm(pos_j - pos_i, dim=1) + 1e-6  # (P,)
        energies = self.strength / (distances ** 2)

        return energies.sum()


def normal_coherence_loss(normals, edge_indices):
    """
    Normal coherence: neighboring stitches should agree on surface orientation.

    Loss = sum_{(i,j) in E} (1 - n_i . n_j)

    When normals are aligned: loss = 0
    When anti-parallel: loss = 2 per edge

    Args:
        normals:      (N, 3) tensor, assumed ~unit length
        edge_indices: (E, 2) long tensor

    Returns:
        Scalar tensor
    """
    if edge_indices.shape[0] == 0:
        return torch.tensor(0.0, dtype=normals.dtype)

    n_src = normals[edge_indices[:, 0]]    # (E, 3)
    n_tgt = normals[edge_indices[:, 1]]    # (E, 3)
    dots = (n_src * n_tgt).sum(dim=1)      # (E,)
    return (1.0 - dots).sum()


def normal_unit_loss(normals):
    """
    Penalty for normals deviating from unit length.

    Loss = sum_i (||n_i||^2 - 1)^2

    Args:
        normals: (N, 3) tensor

    Returns:
        Scalar tensor
    """
    norms_sq = (normals ** 2).sum(dim=1)  # (N,)
    return ((norms_sq - 1.0) ** 2).sum()


def out_of_plane_loss(positions, normals, neighbor_indices_list):
    """
    Out-of-plane flatness: neighbor vectors should lie in the fabric
    plane (perpendicular to the vertex normal).

    For each vertex i and each neighbor j, computes:
        sin(theta) = dot(pos_j - pos_i, n_i) / |pos_j - pos_i|
    where theta is the angle between the edge vector and the fabric plane.
    For a flat surface, sin(theta) = 0.

    Loss = sum_i sum_j sin(theta)^2

    Args:
        positions:             (N, 3) tensor
        normals:               (N, 3) tensor
        neighbor_indices_list: list of lists of neighbor indices per vertex

    Returns:
        Scalar tensor
    """
    N = positions.shape[0]
    loss = torch.tensor(0.0, dtype=positions.dtype)

    for i in range(N):
        n_hat = normals[i]
        n_hat = n_hat / (n_hat.norm() + 1e-8)

        for j in neighbor_indices_list[i]:
            v_ij = positions[j] - positions[i]
            v_len = v_ij.norm().clamp(min=1e-8)
            sin_angle = torch.dot(v_ij, n_hat) / v_len
            loss = loss + sin_angle ** 2

    return loss


def in_plane_angle_loss(positions, normals, h_neighbors, v_neighbors,
                        target_angle=np.pi / 2):
    """
    In-plane angular regularity: h and v edges should meet at the target
    angle (default 90 deg) when projected onto the fabric plane.

    For each vertex with both h and v neighbors, projects edge vectors
    onto the plane perpendicular to the vertex normal, then penalizes
    angle deviation from target.

    Args:
        positions:    (N, 3) tensor
        normals:      (N, 3) tensor
        h_neighbors:  list of lists, h-neighbors per vertex
        v_neighbors:  list of lists, v-neighbors per vertex
        target_angle: target angle in radians (default pi/2)

    Returns:
        Scalar tensor
    """
    N = positions.shape[0]
    loss = torch.tensor(0.0, dtype=positions.dtype)

    for i in range(N):
        h_nbrs = h_neighbors[i]
        v_nbrs = v_neighbors[i]
        if len(h_nbrs) == 0 or len(v_nbrs) == 0:
            continue

        n_hat = normals[i]
        n_hat = n_hat / (n_hat.norm() + 1e-8)

        for hj in h_nbrs:
            h_vec = positions[hj] - positions[i]
            # Project onto fabric plane
            h_proj = h_vec - torch.dot(h_vec, n_hat) * n_hat
            h_len = h_proj.norm().clamp(min=1e-8)
            h_dir = h_proj / h_len

            for vj in v_nbrs:
                v_vec = positions[vj] - positions[i]
                v_proj = v_vec - torch.dot(v_vec, n_hat) * n_hat
                v_len = v_proj.norm().clamp(min=1e-8)
                v_dir = v_proj / v_len

                cos_val = torch.dot(h_dir, v_dir)
                cross = torch.cross(h_dir, v_dir)
                sin_val = cross.norm().clamp(min=1e-8)
                angle = torch.atan2(sin_val, cos_val)

                loss = loss + (angle - target_angle) ** 2

    return loss


def offset_loss(positions, normals, edge_indices, stitch_offsets, neighbor_indices_list):
    """
    Stitch-type micro-displacement penalty.

    For each INTERIOR stitch (surrounded on all sides), compute
    displacement from centroid of neighbors and penalize deviation
    from desired offsets along local frame axes.

    Boundary/corner stitches are excluded because the centroid of
    their neighbors is biased toward the interior, producing bogus
    forces.

    Args:
        positions:       (N, 3) tensor
        normals:         (N, 3) tensor
        edge_indices:    (E, 2) long tensor
        stitch_offsets:  (N, 3) tensor [offset_normal, offset_rl, offset_ud]
        neighbor_indices_list: list of lists of neighbor indices per stitch

    Returns:
        Scalar tensor
    """
    N = positions.shape[0]
    loss = torch.tensor(0.0, dtype=positions.dtype)

    # Build edge-set for quick orientation lookup
    edge_set = set()
    for idx in range(edge_indices.shape[0]):
        edge_set.add((int(edge_indices[idx, 0]), int(edge_indices[idx, 1])))
        edge_set.add((int(edge_indices[idx, 1]), int(edge_indices[idx, 0])))

    for i in range(N):
        nbrs = neighbor_indices_list[i]
        # Only apply to interior stitches surrounded on all sides.
        # Need >= 4 neighbors for the centroid to be unbiased
        # (edge/corner stitches have biased centroids).
        if len(nbrs) < 4:
            continue

        nbr_positions = positions[nbrs]          # (K, 3)
        centroid = nbr_positions.mean(dim=0)      # (3,)
        displacement = positions[i] - centroid     # (3,)

        n_hat = normals[i]
        n_hat = n_hat / (torch.norm(n_hat) + 1e-8)

        # Compute right_left from horizontal neighbors
        h_nbrs = [n_idx for n_idx in nbrs if abs(n_idx - i) <= 2]

        if len(h_nbrs) >= 2:
            r_hat = positions[h_nbrs[0]] - positions[h_nbrs[-1]]
        elif len(h_nbrs) == 1:
            r_hat = positions[i] - positions[h_nbrs[0]]
        else:
            r_hat = torch.tensor([1.0, 0.0, 0.0], dtype=positions.dtype)

        r_hat = r_hat / (torch.norm(r_hat) + 1e-8)

        u_hat = torch.cross(n_hat, r_hat)
        u_hat = u_hat / (torch.norm(u_hat) + 1e-8)

        proj_n = torch.dot(displacement, n_hat)
        proj_r = torch.dot(displacement, r_hat)
        proj_u = torch.dot(displacement, u_hat)

        loss = loss + (proj_n - stitch_offsets[i, 0]) ** 2
        loss = loss + (proj_r - stitch_offsets[i, 1]) ** 2
        loss = loss + (proj_u - stitch_offsets[i, 2]) ** 2

    return loss
