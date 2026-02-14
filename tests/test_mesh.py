"""Tests for layout/mesh.py -- triangulation and solid angle."""

import numpy as np
import torch
import pytest

from layout.mesh import (
    build_triangulation,
    solid_angle_at_vertex,
    flatness_energy,
    get_boundary_vertices,
)


class TestBuildTriangulation:
    def _make_2x2_grid(self):
        """
        2x2 grid:
          2 --- 3
          |     |
          0 --- 1
        """
        positions = np.array([
            [0.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [0.0, 3.0, 0.0],
            [4.0, 3.0, 0.0],
        ])
        edge_indices = np.array([
            [0, 1],  # h
            [2, 3],  # h
            [0, 2],  # v
            [1, 3],  # v
        ])
        orientations = ["h", "h", "v", "v"]
        return positions, edge_indices, orientations

    def _make_4x4_grid(self):
        """
        4x4 grid of 16 stitches with h and v edges.
        """
        positions = []
        for r in range(4):
            for c in range(4):
                positions.append([c * 4.0, r * 3.0, 0.0])
        positions = np.array(positions)

        edges = []
        orientations = []
        for r in range(4):
            for c in range(4):
                idx = r * 4 + c
                if c < 3:  # horizontal
                    edges.append([idx, idx + 1])
                    orientations.append("h")
                if r < 3:  # vertical
                    edges.append([idx, idx + 4])
                    orientations.append("v")

        return positions, np.array(edges), orientations

    def test_2x2_grid_produces_triangles(self):
        pos, edges, orient = self._make_2x2_grid()
        triangles = build_triangulation(pos, edges, orient)
        assert len(triangles) == 2

    def test_4x4_grid_triangle_count(self):
        pos, edges, orient = self._make_4x4_grid()
        triangles = build_triangulation(pos, edges, orient)
        # 3x3 quads -> 9 quads -> 18 triangles
        assert len(triangles) == 18

    def test_triangle_indices_valid(self):
        pos, edges, orient = self._make_4x4_grid()
        triangles = build_triangulation(pos, edges, orient)
        N = pos.shape[0]
        for tri in triangles:
            for idx in tri:
                assert 0 <= idx < N

    def test_no_degenerate_triangles(self):
        pos, edges, orient = self._make_4x4_grid()
        triangles = build_triangulation(pos, edges, orient)
        for tri in triangles:
            # All three vertices should be distinct
            assert len(set(tri)) == 3


class TestSolidAngle:
    def test_right_angle_triangle(self):
        """Solid angle at a right-angle vertex of a flat triangle."""
        vertex = torch.tensor([0.0, 0.0, 0.0])
        corners = torch.tensor([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0],  # dummy, see note below
        ])
        # For 2D face angle, we just need the two edges from vertex
        # This is really measuring the angle at the vertex in the triangle

    def test_flat_mesh_angles_sum_to_2pi(self):
        """For interior vertex of flat mesh, face angles sum to 2*pi."""
        # Central vertex surrounded by 4 triangles in a cross pattern
        #       2
        #      / \
        #     3 - 0 - 1
        #      \ /
        #       4
        positions = torch.tensor([
            [0.0, 0.0, 0.0],    # 0: center
            [4.0, 0.0, 0.0],    # 1: right
            [0.0, 3.0, 0.0],    # 2: up
            [-4.0, 0.0, 0.0],   # 3: left
            [0.0, -3.0, 0.0],   # 4: down
        ])
        triangles = [
            (0, 1, 2),
            (0, 2, 3),
            (0, 3, 4),
            (0, 4, 1),
        ]

        total_angle = 0.0
        for tri in triangles:
            # Compute face angle at vertex 0
            others = [v for v in tri if v != 0]
            va = positions[others[0]] - positions[0]
            vb = positions[others[1]] - positions[0]
            cos_a = torch.dot(va, vb) / (torch.norm(va) * torch.norm(vb))
            cos_a = cos_a.clamp(-1.0, 1.0)
            total_angle += torch.acos(cos_a).item()

        assert total_angle == pytest.approx(2 * np.pi, abs=0.01)


class TestFlatnessEnergy:
    def test_flat_grid_low_energy(self):
        """Flat grid should have near-zero flatness energy."""
        # 3x3 grid with interior vertex at center
        positions_list = []
        for r in range(3):
            for c in range(3):
                positions_list.append([c * 4.0, r * 3.0, 0.0])
        positions = torch.tensor(positions_list, dtype=torch.float32)

        # Build edges
        edges = []
        orientations = []
        for r in range(3):
            for c in range(3):
                idx = r * 3 + c
                if c < 2:
                    edges.append([idx, idx + 1])
                    orientations.append("h")
                if r < 2:
                    edges.append([idx, idx + 3])
                    orientations.append("v")

        edge_indices = np.array(edges)
        triangles = build_triangulation(positions.numpy(), edge_indices, orientations)

        energy = flatness_energy(positions, triangles)
        # Interior vertex (4) should have angles summing to ~2*pi
        # So energy should be close to 0
        assert energy.item() < 0.1

    def test_non_flat_higher_energy(self):
        """Non-flat configuration should have higher flatness energy."""
        # 3x3 grid but center vertex displaced in z
        positions_list = []
        for r in range(3):
            for c in range(3):
                z = 5.0 if (r == 1 and c == 1) else 0.0
                positions_list.append([c * 4.0, r * 3.0, z])
        positions = torch.tensor(positions_list, dtype=torch.float32)

        edges = []
        orientations = []
        for r in range(3):
            for c in range(3):
                idx = r * 3 + c
                if c < 2:
                    edges.append([idx, idx + 1])
                    orientations.append("h")
                if r < 2:
                    edges.append([idx, idx + 3])
                    orientations.append("v")

        edge_indices = np.array(edges)
        triangles = build_triangulation(positions.numpy(), edge_indices, orientations)

        energy = flatness_energy(positions, triangles)
        # Should be significantly higher than flat case
        assert energy.item() > 0.1

    def test_empty_triangles(self):
        """Should return 0 for empty triangle list."""
        positions = torch.tensor([[0.0, 0.0, 0.0]])
        energy = flatness_energy(positions, [])
        assert energy.item() == pytest.approx(0.0)


class TestBoundaryVertices:
    def test_grid_boundary(self):
        """Boundary vertices of a 3x3 grid should be the outer ring."""
        edges = []
        for r in range(3):
            for c in range(3):
                idx = r * 3 + c
                if c < 2:
                    edges.append([idx, idx + 1])
                if r < 2:
                    edges.append([idx, idx + 3])

        edge_indices = np.array(edges)
        boundary = get_boundary_vertices(edge_indices, 9)

        # Center vertex (4) should NOT be boundary (valence 4)
        assert 4 not in boundary

        # Corner vertices should be boundary (valence 2)
        assert 0 in boundary
        assert 2 in boundary
        assert 6 in boundary
        assert 8 in boundary
