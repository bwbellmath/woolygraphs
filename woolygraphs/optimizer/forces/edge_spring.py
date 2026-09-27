"""
Edge spring force component.

Pulls edges toward their target lengths using spring-like forces.
This is the primary force for maintaining correct stitch geometry.
"""

import numpy as np
from typing import TYPE_CHECKING

from .base import ForceComponent

if TYPE_CHECKING:
    from ...graph import KnitGraph


class EdgeSpringForce(ForceComponent):
    """
    Spring force that pulls edges toward target lengths.

    For each edge (i, j) with target length L:
    - If current distance d > L: attractive force pulls vertices together
    - If current distance d < L: repulsive force pushes vertices apart

    Energy: E = Σ_edges (d - L)²
    Force: F = k * (d - L) * (direction)
    """

    def __init__(self, weight: float = 1.0):
        super().__init__(weight=weight, name="edge_spring")

    def compute_forces(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute spring forces for all vertices.

        Each edge contributes a force that pulls/pushes the connected
        vertices toward the target edge length.
        """
        n = len(positions)
        forces = np.zeros((n, 3), dtype=np.float64)

        for edge in graph.edges:
            i, j = edge.i, edge.j
            target_len = edge.length_mm

            # Vector from i to j
            d_vec = positions[j] - positions[i]
            d_norm = np.linalg.norm(d_vec)

            if d_norm < 1e-10:
                # Vertices are coincident, apply small random force
                d_vec = np.random.randn(3) * 0.01
                d_norm = np.linalg.norm(d_vec)

            # Unit direction
            d_hat = d_vec / d_norm

            # Spring force magnitude: k * (d - L)
            # Positive when too far (attractive), negative when too close (repulsive)
            magnitude = self.weight * (d_norm - target_len)

            # Force on i points toward j (if too far) or away (if too close)
            force = magnitude * d_hat

            forces[i] += force
            forces[j] -= force

        return forces

    def compute_energy(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> float:
        """
        Compute total spring energy.

        E = weight * Σ_edges (d - L)²
        """
        total = 0.0

        for edge in graph.edges:
            i, j = edge.i, edge.j
            target_len = edge.length_mm

            d_vec = positions[j] - positions[i]
            d_norm = np.linalg.norm(d_vec)

            total += (d_norm - target_len) ** 2

        return self.weight * total

    def compute_edge_errors(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> dict:
        """
        Compute per-edge length errors for analysis.

        Returns:
            Dictionary with 'h' and 'v' keys containing lists of
            (actual_length, target_length, error) tuples.
        """
        errors = {'h': [], 'v': []}

        for edge in graph.edges:
            i, j = edge.i, edge.j
            target_len = edge.length_mm

            d_vec = positions[j] - positions[i]
            d_norm = np.linalg.norm(d_vec)
            error = d_norm - target_len

            errors[edge.orient].append((d_norm, target_len, error))

        return errors
