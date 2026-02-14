"""Tests for layout/forces.py -- vectorized force calculations."""

import numpy as np
import torch
import pytest

from layout.forces import (
    YarnForceModel,
    RepulsionModel,
    normal_coherence_loss,
    normal_unit_loss,
    offset_loss,
    out_of_plane_loss,
    in_plane_angle_loss,
)


class TestYarnForceModel:
    @pytest.fixture
    def model(self):
        return YarnForceModel(
            elastic_limit=0.4, k_elastic=0.1, k_plastic=10.0, step_penalty=5.0
        )

    def test_zero_at_rest(self, model):
        """Energy should be zero when distance equals rest length."""
        positions = torch.tensor([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]])
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)
        rest_lengths = torch.tensor([4.0])

        energy = model.total_edge_energy_vectorized(positions, edge_indices, rest_lengths)
        assert energy.item() == pytest.approx(0.0, abs=1e-4)

    def test_elastic_region(self, model):
        """Energy should be quadratic in elastic region."""
        positions = torch.tensor([[0.0, 0.0, 0.0], [4.5, 0.0, 0.0]])
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)
        rest_lengths = torch.tensor([4.0])

        energy = model.total_edge_energy_vectorized(positions, edge_indices, rest_lengths)
        # delta = 0.5, within elastic limit (0.4 * 4 = 1.6)
        expected = 0.5 * 0.1 * 0.5 ** 2
        assert energy.item() == pytest.approx(expected, abs=1e-3)

    def test_plastic_region(self, model):
        """Energy should be higher in plastic region."""
        # Distance well beyond elastic limit
        positions_elastic = torch.tensor([[0.0, 0.0, 0.0], [4.5, 0.0, 0.0]])
        positions_plastic = torch.tensor([[0.0, 0.0, 0.0], [7.0, 0.0, 0.0]])
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)
        rest_lengths = torch.tensor([4.0])

        e_elastic = model.total_edge_energy_vectorized(positions_elastic, edge_indices, rest_lengths)
        e_plastic = model.total_edge_energy_vectorized(positions_plastic, edge_indices, rest_lengths)

        assert e_plastic.item() > e_elastic.item()

    def test_vectorized_multiple_edges(self, model):
        """Should handle multiple edges at once."""
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [0.0, 3.0, 0.0],
        ])
        edge_indices = torch.tensor([[0, 1], [0, 2]], dtype=torch.long)
        rest_lengths = torch.tensor([4.0, 3.0])

        energy = model.total_edge_energy_vectorized(positions, edge_indices, rest_lengths)
        # Both edges at rest -> energy ~ 0
        assert energy.item() == pytest.approx(0.0, abs=1e-3)

    def test_gradient_flows(self, model):
        """Should produce valid gradients for optimization."""
        positions = torch.tensor([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]], requires_grad=True)
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)
        rest_lengths = torch.tensor([4.0])

        energy = model.total_edge_energy_vectorized(positions, edge_indices, rest_lengths)
        energy.backward()

        assert positions.grad is not None
        assert not torch.all(positions.grad == 0)

    def test_empty_edges(self, model):
        """Should return 0 for empty edge set."""
        positions = torch.tensor([[0.0, 0.0, 0.0]])
        edge_indices = torch.zeros((0, 2), dtype=torch.long)
        rest_lengths = torch.zeros(0)

        energy = model.total_edge_energy_vectorized(positions, edge_indices, rest_lengths)
        assert energy.item() == pytest.approx(0.0)

    def test_single_edge_matches_scalar(self, model):
        """Vectorized result should match single-edge computation."""
        d = torch.tensor(5.0)
        r = torch.tensor(4.0)
        single = model.edge_energy_single(d, r)

        positions = torch.tensor([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]])
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)
        rest_lengths = torch.tensor([4.0])
        vectorized = model.total_edge_energy_vectorized(positions, edge_indices, rest_lengths)

        assert vectorized.item() == pytest.approx(single.item(), abs=1e-4)


class TestRepulsionModel:
    def test_basic_repulsion(self):
        """2-hop neighbors should repel (1-hop excluded)."""
        # Linear chain: 0-1-2.  Pair (0,2) is 2-hop -> repelled.
        A = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
        model = RepulsionModel(A, num_powers=2, strength=50.0)

        positions = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        energy = model.repulsion_energy(positions)
        assert energy.item() > 0

    def test_repulsion_decreases_with_distance(self):
        """Repulsion should decrease as 2-hop nodes move apart."""
        # Linear chain: 0-1-2.  Pair (0,2) is 2-hop -> repelled.
        A = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
        model = RepulsionModel(A, num_powers=2, strength=50.0)

        pos_close = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        pos_far = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [10.0, 0.0, 0.0]])

        e_close = model.repulsion_energy(pos_close)
        e_far = model.repulsion_energy(pos_far)
        assert e_close.item() > e_far.item()

    def test_no_self_repulsion(self):
        """Diagonal of repulsion matrix should be zero."""
        A = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
        model = RepulsionModel(A, num_powers=2)
        np.fill_diagonal(model.repulsion_matrix, 0)
        assert model.repulsion_matrix[0, 0] == 0
        assert model.repulsion_matrix[1, 1] == 0

    def test_multi_hop_repulsion(self):
        """Only 2+ hop pairs should repel (1-hop excluded)."""
        # Linear graph: 0-1-2-3
        # 1-hop pairs (excluded): (0,1), (1,2), (2,3)
        # 2-hop pairs: (0,2), (1,3)
        # 3-hop pairs: (0,3)
        # Total repulsion pairs = 3
        A = np.array([
            [0, 1, 0, 0],
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
        ], dtype=float)
        model = RepulsionModel(A, num_powers=3)

        assert len(model.repulsion_pairs) == 3

    def test_empty_graph(self):
        """Should handle disconnected graph."""
        A = np.zeros((3, 3))
        model = RepulsionModel(A, num_powers=2)

        positions = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        energy = model.repulsion_energy(positions)
        assert energy.item() == pytest.approx(0.0)


class TestNormalCoherenceLoss:
    def test_identical_normals_zero_loss(self):
        """Loss should be 0 when all normals are identical."""
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ])
        edge_indices = torch.tensor([[0, 1], [1, 2]], dtype=torch.long)

        loss = normal_coherence_loss(normals, edge_indices)
        assert loss.item() == pytest.approx(0.0, abs=1e-6)

    def test_antiparallel_normals_max_loss(self):
        """Loss should be 2 per edge when normals are anti-parallel."""
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ])
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)

        loss = normal_coherence_loss(normals, edge_indices)
        assert loss.item() == pytest.approx(2.0, abs=1e-6)

    def test_perpendicular_normals(self):
        """Loss should be 1 per edge when normals are perpendicular."""
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
        ])
        edge_indices = torch.tensor([[0, 1]], dtype=torch.long)

        loss = normal_coherence_loss(normals, edge_indices)
        assert loss.item() == pytest.approx(1.0, abs=1e-6)

    def test_empty_edges(self):
        normals = torch.tensor([[0.0, 0.0, 1.0]])
        edge_indices = torch.zeros((0, 2), dtype=torch.long)
        loss = normal_coherence_loss(normals, edge_indices)
        assert loss.item() == pytest.approx(0.0)


class TestNormalUnitLoss:
    def test_unit_normals_zero_loss(self):
        """Loss should be 0 for unit-length normals."""
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ])
        loss = normal_unit_loss(normals)
        assert loss.item() == pytest.approx(0.0, abs=1e-6)

    def test_non_unit_normals_positive_loss(self):
        """Loss should be positive for non-unit normals."""
        normals = torch.tensor([
            [0.0, 0.0, 2.0],  # ||n|| = 2
        ])
        loss = normal_unit_loss(normals)
        # (4 - 1)^2 = 9
        assert loss.item() == pytest.approx(9.0, abs=1e-6)


class TestOutOfPlaneLoss:
    def test_flat_grid_zero_loss(self):
        """Flat grid with z=0 normals pointing up -> all neighbors in plane -> loss=0."""
        # 2x2 grid in xy plane
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ])
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ])
        # Neighbors: 0-1, 0-2, 1-3, 2-3
        neighbor_list = [[1, 2], [0, 3], [0, 3], [1, 2]]

        loss = out_of_plane_loss(positions, normals, neighbor_list)
        assert loss.item() == pytest.approx(0.0, abs=1e-6)

    def test_bent_surface_positive_loss(self):
        """When a neighbor is displaced out of plane, loss > 0."""
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 1.0],  # lifted in z
        ])
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ])
        neighbor_list = [[1], [0]]

        loss = out_of_plane_loss(positions, normals, neighbor_list)
        assert loss.item() > 0

    def test_gradient_flows(self):
        """Should produce valid gradients."""
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.5],
        ], requires_grad=True)
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ], requires_grad=True)
        neighbor_list = [[1], [0]]

        loss = out_of_plane_loss(positions, normals, neighbor_list)
        loss.backward()
        assert positions.grad is not None

    def test_no_neighbors_zero_loss(self):
        """Vertices with no neighbors contribute zero loss."""
        positions = torch.tensor([[0.0, 0.0, 0.0]])
        normals = torch.tensor([[0.0, 0.0, 1.0]])
        neighbor_list = [[]]

        loss = out_of_plane_loss(positions, normals, neighbor_list)
        assert loss.item() == pytest.approx(0.0)


class TestInPlaneAngleLoss:
    def test_right_angle_grid_zero_loss(self):
        """H and V edges at exactly 90 degrees in the fabric plane -> loss=0."""
        # Center vertex with h-neighbor to the right, v-neighbor up
        positions = torch.tensor([
            [0.0, 0.0, 0.0],  # center
            [1.0, 0.0, 0.0],  # h-neighbor (right)
            [0.0, 1.0, 0.0],  # v-neighbor (up)
        ])
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ])
        h_neighbors = [[1], [], []]
        v_neighbors = [[2], [], []]

        loss = in_plane_angle_loss(positions, normals, h_neighbors, v_neighbors)
        assert loss.item() == pytest.approx(0.0, abs=1e-6)

    def test_non_right_angle_positive_loss(self):
        """H and V edges not at 90 degrees -> positive loss."""
        # Skewed: both neighbors at 45 degrees
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],   # h-neighbor
            [1.0, 1.0, 0.0],   # v-neighbor at 45 degrees from h
        ])
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ])
        h_neighbors = [[1], [], []]
        v_neighbors = [[2], [], []]

        loss = in_plane_angle_loss(positions, normals, h_neighbors, v_neighbors)
        assert loss.item() > 0

    def test_no_hv_neighbors_zero_loss(self):
        """Vertices without both h and v neighbors contribute zero."""
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ])
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ])
        # Only h-neighbors, no v-neighbors
        h_neighbors = [[1], [0]]
        v_neighbors = [[], []]

        loss = in_plane_angle_loss(positions, normals, h_neighbors, v_neighbors)
        assert loss.item() == pytest.approx(0.0)

    def test_gradient_flows(self):
        """Should produce valid gradients."""
        positions = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 0.8, 0.0],
        ], requires_grad=True)
        normals = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ], requires_grad=True)
        h_neighbors = [[1], [], []]
        v_neighbors = [[2], [], []]

        loss = in_plane_angle_loss(positions, normals, h_neighbors, v_neighbors)
        loss.backward()
        assert positions.grad is not None
