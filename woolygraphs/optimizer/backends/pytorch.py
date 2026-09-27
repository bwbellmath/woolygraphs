"""
PyTorch backend for layout optimization.

Uses automatic differentiation for gradient-based optimization
of vertex positions.
"""

import numpy as np
from typing import List, Optional, Callable, TYPE_CHECKING
import logging

try:
    import torch
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TYPE_CHECKING:
    from ...graph import KnitGraph
    from ...config import LayoutConfig

logger = logging.getLogger(__name__)


class PyTorchBackend:
    """
    PyTorch-based optimizer backend.

    Uses differentiable loss functions and gradient descent to
    optimize vertex positions.

    Attributes:
        device: PyTorch device ('cpu' or 'cuda')
        dtype: PyTorch dtype for positions
    """

    def __init__(self, device: str = 'cpu'):
        if not TORCH_AVAILABLE:
            raise ImportError(
                "PyTorch is required for PyTorchBackend. "
                "Install with: pip install torch"
            )
        self.device = torch.device(device)
        self.dtype = torch.float64

    def optimize(
        self,
        graph: 'KnitGraph',
        initial_positions: np.ndarray,
        config: 'LayoutConfig',
        callback: Optional[Callable[[int, np.ndarray, float], None]] = None
    ) -> np.ndarray:
        """
        Optimize positions using PyTorch gradient descent.

        Args:
            graph: The knit graph
            initial_positions: Starting positions from baseline
            config: Layout configuration with optimizer settings
            callback: Optional callback(epoch, positions, loss) for monitoring

        Returns:
            Optimized positions as numpy array
        """
        epochs = config.optimizer.epochs
        lr = config.optimizer.learning_rate
        force_weights = config.optimizer.forces

        # Convert to PyTorch tensors
        positions = torch.tensor(
            initial_positions,
            dtype=self.dtype,
            device=self.device,
            requires_grad=True
        )

        # Build edge tensors for efficient computation
        edge_i = torch.tensor(
            [e.i for e in graph.edges],
            dtype=torch.long,
            device=self.device
        )
        edge_j = torch.tensor(
            [e.j for e in graph.edges],
            dtype=torch.long,
            device=self.device
        )
        edge_lengths = torch.tensor(
            [e.length_mm for e in graph.edges],
            dtype=self.dtype,
            device=self.device
        )

        # Build neighbor lists for solid angle computation
        neighbor_lists = self._build_neighbor_lists(graph)

        # Create optimizer
        optimizer = optim.Adam([positions], lr=lr)

        # Optimization loop
        best_loss = float('inf')
        best_positions = initial_positions.copy()

        for epoch in range(epochs):
            optimizer.zero_grad()

            # Compute total loss
            loss = torch.tensor(0.0, dtype=self.dtype, device=self.device)

            # Edge spring loss
            if force_weights.get('edge_spring', 0) > 0:
                spring_loss = self._edge_spring_loss(
                    positions, edge_i, edge_j, edge_lengths
                )
                loss = loss + force_weights['edge_spring'] * spring_loss

            # Repulsion loss
            if force_weights.get('repulsion', 0) > 0:
                repulsion_loss = self._repulsion_loss(positions)
                loss = loss + force_weights['repulsion'] * repulsion_loss

            # Solid angle / planarity loss
            if force_weights.get('solid_angle', 0) > 0:
                planarity_loss = self._planarity_loss(positions, neighbor_lists)
                loss = loss + force_weights['solid_angle'] * planarity_loss

            # Backpropagate
            loss.backward()
            optimizer.step()

            # Track best
            loss_val = loss.item()
            if loss_val < best_loss:
                best_loss = loss_val
                best_positions = positions.detach().cpu().numpy().copy()

            # Callback for monitoring
            if callback and epoch % 100 == 0:
                callback(epoch, positions.detach().cpu().numpy(), loss_val)

            # Early stopping check
            if loss_val < 1e-6:
                logger.info(f"Converged at epoch {epoch}")
                break

        logger.info(f"Optimization complete. Final loss: {best_loss:.6f}")
        return best_positions

    def _edge_spring_loss(
        self,
        positions: 'torch.Tensor',
        edge_i: 'torch.Tensor',
        edge_j: 'torch.Tensor',
        target_lengths: 'torch.Tensor'
    ) -> 'torch.Tensor':
        """
        Compute edge spring loss: Σ (||p_i - p_j|| - L)²
        """
        pos_i = positions[edge_i]
        pos_j = positions[edge_j]

        diff = pos_i - pos_j
        distances = torch.norm(diff, dim=1)

        errors = distances - target_lengths
        return torch.sum(errors ** 2)

    def _repulsion_loss(
        self,
        positions: 'torch.Tensor',
        min_dist: float = 0.1
    ) -> 'torch.Tensor':
        """
        Compute repulsion loss: Σ_{i<j} 1/d_{ij}

        Uses efficient pairwise distance computation.
        """
        n = positions.shape[0]

        # Compute pairwise distances
        # More efficient than double loop
        diff = positions.unsqueeze(0) - positions.unsqueeze(1)
        distances = torch.norm(diff, dim=2)

        # Mask diagonal and lower triangle (avoid double counting)
        mask = torch.triu(torch.ones(n, n, device=self.device), diagonal=1)

        # Clamp minimum distance
        distances = torch.clamp(distances, min=min_dist)

        # Inverse distance with mask
        inv_dist = mask / distances

        return torch.sum(inv_dist)

    def _planarity_loss(
        self,
        positions: 'torch.Tensor',
        neighbor_lists: List[List[int]]
    ) -> 'torch.Tensor':
        """
        Compute planarity loss: deviation from local planes.

        For each vertex, measures distance to the best-fit plane
        of its neighbors.
        """
        n = positions.shape[0]
        total_loss = torch.tensor(0.0, dtype=self.dtype, device=self.device)

        for v in range(n):
            neighbors = neighbor_lists[v]
            if len(neighbors) < 3:
                continue

            neighbor_pos = positions[neighbors]
            centroid = neighbor_pos.mean(dim=0)

            # Vector from centroid to vertex
            v_to_centroid = positions[v] - centroid

            # Compute normal via cross products of neighbor edges
            edges = neighbor_pos - centroid
            normal = torch.zeros(3, dtype=self.dtype, device=self.device)

            for i in range(len(neighbors)):
                j = (i + 1) % len(neighbors)
                cross = torch.linalg.cross(edges[i], edges[j])
                normal = normal + cross

            norm_magnitude = torch.norm(normal)
            if norm_magnitude > 1e-10:
                normal = normal / norm_magnitude
                distance = torch.dot(v_to_centroid, normal)
                total_loss = total_loss + distance ** 2

        return total_loss

    def _build_neighbor_lists(self, graph: 'KnitGraph') -> List[List[int]]:
        """Build adjacency lists for each vertex."""
        n = graph.n_stitches
        neighbors = [[] for _ in range(n)]

        for edge in graph.edges:
            neighbors[edge.i].append(edge.j)
            neighbors[edge.j].append(edge.i)

        return neighbors


class ForceDirectedBackend:
    """
    Simple force-directed backend using numpy.

    Uses explicit force computation and gradient descent without
    automatic differentiation. Useful as a fallback when PyTorch
    is not available.
    """

    def __init__(self):
        pass

    def optimize(
        self,
        graph: 'KnitGraph',
        initial_positions: np.ndarray,
        forces: List,  # List of ForceComponent
        epochs: int = 1000,
        learning_rate: float = 0.01,
        callback: Optional[Callable[[int, np.ndarray, float], None]] = None
    ) -> np.ndarray:
        """
        Optimize using explicit force computation.

        Args:
            graph: The knit graph
            initial_positions: Starting positions
            forces: List of ForceComponent instances
            epochs: Number of iterations
            learning_rate: Step size
            callback: Optional monitoring callback

        Returns:
            Optimized positions
        """
        positions = initial_positions.copy()
        epsilon = learning_rate

        for epoch in range(epochs):
            # Compute total force
            total_force = np.zeros_like(positions)
            for force in forces:
                total_force += force.compute_forces(positions, graph)

            # Compute total energy for monitoring
            total_energy = sum(f.compute_energy(positions, graph) for f in forces)

            # Update positions
            positions = positions + epsilon * total_force

            # Decay learning rate
            epsilon = learning_rate * (1 - epoch / epochs)

            # Callback
            if callback and epoch % 100 == 0:
                callback(epoch, positions, total_energy)

            # Convergence check
            force_magnitude = np.linalg.norm(total_force)
            if force_magnitude < 1e-6:
                logger.info(f"Converged at epoch {epoch}")
                break

        return positions
