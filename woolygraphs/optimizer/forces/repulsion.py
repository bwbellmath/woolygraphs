"""
Universal repulsion force component.

Pushes all vertex pairs apart to prevent overlapping and tangling.
Uses inverse-square law similar to electrostatic repulsion.
"""

import numpy as np
from typing import TYPE_CHECKING, Optional

from .base import ForceComponent

if TYPE_CHECKING:
    from ...graph import KnitGraph


class RepulsionForce(ForceComponent):
    """
    Universal repulsion force between all vertex pairs.

    Prevents vertices from overlapping by applying inverse-square
    repulsion. This is essential for untangling initial layouts.

    Energy: E = Σ_{i<j} 1/d_{ij}
    Force: F = k / d² * (direction away)

    Attributes:
        weight: Force scaling factor
        min_distance: Minimum distance to prevent division by zero
        cutoff_distance: Optional maximum distance for force calculation
                        (improves performance for large graphs)
    """

    def __init__(
        self,
        weight: float = 1.0,
        min_distance: float = 0.1,
        cutoff_distance: Optional[float] = None
    ):
        super().__init__(weight=weight, name="repulsion")
        self.min_distance = min_distance
        self.cutoff_distance = cutoff_distance

    def compute_forces(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute repulsion forces for all vertices.

        Uses O(n²) pairwise calculation. For large graphs, consider
        using Barnes-Hut approximation.
        """
        n = len(positions)
        forces = np.zeros((n, 3), dtype=np.float64)

        for i in range(n):
            for j in range(i + 1, n):
                # Vector from j to i (repulsion pushes i away from j)
                d_vec = positions[i] - positions[j]
                d_norm = np.linalg.norm(d_vec)

                # Clamp minimum distance
                d_norm = max(d_norm, self.min_distance)

                # Skip if beyond cutoff
                if self.cutoff_distance and d_norm > self.cutoff_distance:
                    continue

                # Unit direction (from j toward i)
                d_hat = d_vec / d_norm

                # Inverse-square repulsion magnitude
                magnitude = self.weight / (d_norm ** 2)

                # Apply force
                forces[i] += magnitude * d_hat
                forces[j] -= magnitude * d_hat

        return forces

    def compute_energy(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> float:
        """
        Compute total repulsion energy.

        E = weight * Σ_{i<j} 1/d_{ij}
        """
        n = len(positions)
        total = 0.0

        for i in range(n):
            for j in range(i + 1, n):
                d_vec = positions[i] - positions[j]
                d_norm = np.linalg.norm(d_vec)
                d_norm = max(d_norm, self.min_distance)

                if self.cutoff_distance and d_norm > self.cutoff_distance:
                    continue

                total += 1.0 / d_norm

        return self.weight * total


class SoftRepulsionForce(ForceComponent):
    """
    Soft repulsion that only activates when vertices are too close.

    Unlike universal repulsion, this only applies force when the
    distance is below a threshold. Useful for preventing overlap
    without distorting the overall layout.

    Energy: E = Σ_{i<j} max(0, (threshold - d))²
    """

    def __init__(
        self,
        weight: float = 1.0,
        threshold: float = 2.0,  # mm
        min_distance: float = 0.1
    ):
        super().__init__(weight=weight, name="soft_repulsion")
        self.threshold = threshold
        self.min_distance = min_distance

    def compute_forces(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute soft repulsion forces.

        Only applies force when vertices are closer than threshold.
        """
        n = len(positions)
        forces = np.zeros((n, 3), dtype=np.float64)

        for i in range(n):
            for j in range(i + 1, n):
                d_vec = positions[i] - positions[j]
                d_norm = np.linalg.norm(d_vec)
                d_norm = max(d_norm, self.min_distance)

                # Only apply if below threshold
                if d_norm >= self.threshold:
                    continue

                d_hat = d_vec / d_norm

                # Linear force: stronger when closer
                magnitude = self.weight * (self.threshold - d_norm)

                forces[i] += magnitude * d_hat
                forces[j] -= magnitude * d_hat

        return forces

    def compute_energy(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> float:
        """
        Compute soft repulsion energy.

        E = weight * Σ_{i<j} max(0, threshold - d)²
        """
        n = len(positions)
        total = 0.0

        for i in range(n):
            for j in range(i + 1, n):
                d_vec = positions[i] - positions[j]
                d_norm = np.linalg.norm(d_vec)
                d_norm = max(d_norm, self.min_distance)

                if d_norm < self.threshold:
                    total += (self.threshold - d_norm) ** 2

        return self.weight * total
