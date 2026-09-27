"""
Solid angle force component for manifold conformance.

Pushes vertices toward flat 2-manifold configuration by penalizing
deviation from 2π solid angle at each vertex.
"""

import numpy as np
from typing import TYPE_CHECKING, List, Tuple

from .base import ForceComponent

if TYPE_CHECKING:
    from ...graph import KnitGraph


class SolidAngleForce(ForceComponent):
    """
    Force that encourages vertices to lie on a flat 2-manifold.

    At each vertex, the solid angle subtended by neighboring vertices
    should be 2π for a flat surface. Deviation from this indicates
    curvature (positive = bowl, negative = saddle).

    This force pushes vertices to reduce curvature, helping the
    knit structure conform to a 2D surface.

    Energy: E = Σ_v (Ω_v - 2π)²
    """

    def __init__(self, weight: float = 1.0, target_angle: float = None):
        super().__init__(weight=weight, name="solid_angle")
        # Target solid angle: 2π for flat, can be adjusted for curved surfaces
        self.target_angle = target_angle if target_angle is not None else 2 * np.pi

    def compute_forces(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute forces pushing vertices toward flat configuration.

        For each vertex, compute the solid angle and push outward
        (along vertex normal) if too curved.
        """
        n = len(positions)
        forces = np.zeros((n, 3), dtype=np.float64)

        for v in range(n):
            neighbors = graph.get_neighbors(v)
            if len(neighbors) < 3:
                # Need at least 3 neighbors to define solid angle
                continue

            # Get neighbor positions
            neighbor_pos = positions[neighbors]

            # Compute solid angle at this vertex
            omega = self._compute_solid_angle(positions[v], neighbor_pos)

            # Deviation from target
            deviation = omega - self.target_angle

            if abs(deviation) < 1e-6:
                continue

            # Compute vertex normal (average of face normals)
            normal = self._compute_vertex_normal(positions[v], neighbor_pos)

            if np.linalg.norm(normal) < 1e-10:
                continue

            normal = normal / np.linalg.norm(normal)

            # Push along normal to flatten
            # Positive deviation (too convex) -> push outward
            # Negative deviation (too concave) -> push inward
            force_magnitude = self.weight * deviation
            forces[v] += force_magnitude * normal

        return forces

    def compute_energy(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> float:
        """
        Compute total solid angle energy.

        E = weight * Σ_v (Ω_v - 2π)²
        """
        n = len(positions)
        total = 0.0

        for v in range(n):
            neighbors = graph.get_neighbors(v)
            if len(neighbors) < 3:
                continue

            neighbor_pos = positions[neighbors]
            omega = self._compute_solid_angle(positions[v], neighbor_pos)
            deviation = omega - self.target_angle
            total += deviation ** 2

        return self.weight * total

    def _compute_solid_angle(
        self,
        center: np.ndarray,
        neighbors: np.ndarray
    ) -> float:
        """
        Compute solid angle subtended by neighbors at center vertex.

        Uses the formula for solid angle of a spherical polygon:
        Ω = Σ angles - (n-2)π

        For a flat surface, this should be 2π.
        """
        n = len(neighbors)
        if n < 3:
            return 2 * np.pi  # Assume flat if not enough neighbors

        # Vectors from center to each neighbor
        vectors = neighbors - center
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        unit_vectors = vectors / norms

        # Sum of angles between consecutive neighbor pairs
        angle_sum = 0.0
        for i in range(n):
            j = (i + 1) % n
            # Angle between unit vectors
            dot = np.clip(np.dot(unit_vectors[i], unit_vectors[j]), -1.0, 1.0)
            angle_sum += np.arccos(dot)

        # Solid angle approximation using spherical excess
        # For a polygon on unit sphere: Ω = angle_sum - (n-2)π
        solid_angle = angle_sum - (n - 2) * np.pi

        return solid_angle

    def _compute_vertex_normal(
        self,
        center: np.ndarray,
        neighbors: np.ndarray
    ) -> np.ndarray:
        """
        Compute approximate normal vector at vertex.

        Uses average of cross products of consecutive edge pairs.
        """
        n = len(neighbors)
        if n < 3:
            return np.array([0.0, 0.0, 1.0])

        # Vectors from center to neighbors
        edges = neighbors - center

        # Average normal from cross products
        normal = np.zeros(3)
        for i in range(n):
            j = (i + 1) % n
            cross = np.cross(edges[i], edges[j])
            normal += cross

        norm = np.linalg.norm(normal)
        if norm > 1e-10:
            normal = normal / norm

        return normal

    def compute_curvature_map(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute per-vertex curvature (solid angle deviation).

        Useful for visualization - positive values indicate convex
        regions, negative indicate concave.

        Returns:
            (n,) array of curvature values
        """
        n = len(positions)
        curvature = np.zeros(n)

        for v in range(n):
            neighbors = graph.get_neighbors(v)
            if len(neighbors) < 3:
                continue

            neighbor_pos = positions[neighbors]
            omega = self._compute_solid_angle(positions[v], neighbor_pos)
            curvature[v] = omega - self.target_angle

        return curvature


class PlanarityForce(ForceComponent):
    """
    Simpler planarity force that encourages local flatness.

    Instead of computing solid angles, this measures how far
    vertices deviate from the plane defined by their neighbors.

    Energy: E = Σ_v d(v, plane(neighbors))²
    """

    def __init__(self, weight: float = 1.0):
        super().__init__(weight=weight, name="planarity")

    def compute_forces(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute planarity forces.

        Pushes each vertex toward the best-fit plane of its neighbors.
        """
        n = len(positions)
        forces = np.zeros((n, 3), dtype=np.float64)

        for v in range(n):
            neighbors = graph.get_neighbors(v)
            if len(neighbors) < 3:
                continue

            neighbor_pos = positions[neighbors]

            # Compute centroid of neighbors
            centroid = neighbor_pos.mean(axis=0)

            # Compute best-fit plane normal using SVD
            centered = neighbor_pos - centroid
            try:
                _, _, vh = np.linalg.svd(centered)
                normal = vh[-1]  # Normal is last right singular vector
            except np.linalg.LinAlgError:
                continue

            # Distance from vertex to plane
            v_to_centroid = positions[v] - centroid
            distance = np.dot(v_to_centroid, normal)

            # Force pushes vertex toward plane
            forces[v] -= self.weight * distance * normal

        return forces

    def compute_energy(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> float:
        """
        Compute total planarity energy.
        """
        n = len(positions)
        total = 0.0

        for v in range(n):
            neighbors = graph.get_neighbors(v)
            if len(neighbors) < 3:
                continue

            neighbor_pos = positions[neighbors]
            centroid = neighbor_pos.mean(axis=0)
            centered = neighbor_pos - centroid

            try:
                _, _, vh = np.linalg.svd(centered)
                normal = vh[-1]
            except np.linalg.LinAlgError:
                continue

            v_to_centroid = positions[v] - centroid
            distance = np.dot(v_to_centroid, normal)
            total += distance ** 2

        return self.weight * total
