"""
WoolyGraphs Force Calculations

Physically-realistic force curves for yarn mechanics in knitting.

Force model:
- Vertical edges (between rows): 3mm rest length
- Horizontal edges (within row): 4mm rest length
- Elastic region: ±40% stretch with low stiffness
- Plastic region: Beyond 40%, steep increase in force
- Optional step function at elastic limit
"""

import torch
import numpy as np


class YarnForceModel:
    """
    Force model for knitted yarn behavior

    Parameters:
        vertical_rest: Rest length for vertical edges (mm)
        horizontal_rest: Rest length for horizontal edges (mm)
        elastic_limit: Fraction of rest length for elastic region (0.4 = 40%)
        k_elastic: Spring constant in elastic region (low stiffness)
        k_plastic: Spring constant beyond elastic limit (high stiffness)
        step_penalty: Force jump at elastic limit boundary
    """

    def __init__(self,
                 vertical_rest=3.0,
                 horizontal_rest=4.0,
                 elastic_limit=0.4,
                 k_elastic=0.1,
                 k_plastic=10.0,
                 step_penalty=5.0):

        self.vertical_rest = vertical_rest
        self.horizontal_rest = horizontal_rest
        self.elastic_limit = elastic_limit
        self.k_elastic = k_elastic
        self.k_plastic = k_plastic
        self.step_penalty = step_penalty

    def edge_force(self, distance, rest_length, use_torch=True):
        """
        Calculate force for a single edge given current distance

        Args:
            distance: Current edge length (mm)
            rest_length: Equilibrium/rest length (mm)
            use_torch: Whether to use PyTorch operations (for gradients)

        Returns:
            Force magnitude (positive = tension, negative = compression)
        """
        if use_torch:
            return self._edge_force_torch(distance, rest_length)
        else:
            return self._edge_force_numpy(distance, rest_length)

    def _edge_force_torch(self, distance, rest_length):
        """PyTorch version for gradient computation"""

        delta = distance - rest_length
        abs_delta = torch.abs(delta)

        elastic_threshold = self.elastic_limit * rest_length

        # Elastic region: linear spring
        elastic_force = self.k_elastic * delta

        # Plastic region: steep increase
        overshoot = abs_delta - elastic_threshold
        plastic_force = (self.k_elastic * elastic_threshold +
                        self.step_penalty +
                        self.k_plastic * overshoot) * torch.sign(delta)

        # Choose based on whether we're in elastic or plastic region
        force = torch.where(abs_delta <= elastic_threshold,
                           elastic_force,
                           plastic_force)

        return force

    def _edge_force_numpy(self, distance, rest_length):
        """NumPy version for non-gradient computations"""

        delta = distance - rest_length
        abs_delta = np.abs(delta)

        elastic_threshold = self.elastic_limit * rest_length

        if abs_delta <= elastic_threshold:
            # Elastic region
            force = self.k_elastic * delta
        else:
            # Plastic region
            overshoot = abs_delta - elastic_threshold
            force = (self.k_elastic * elastic_threshold +
                    self.step_penalty +
                    self.k_plastic * overshoot) * np.sign(delta)

        return force

    def edge_energy(self, distance, rest_length):
        """
        Calculate potential energy stored in edge

        Energy is integral of force over distance.
        We use squared deviation as a smooth approximation.

        Args:
            distance: Current edge length
            rest_length: Equilibrium length

        Returns:
            Energy (scalar)
        """
        delta = distance - rest_length
        abs_delta = torch.abs(delta)

        elastic_threshold = self.elastic_limit * rest_length

        # Elastic region: quadratic energy (U = 0.5 * k * x²)
        elastic_energy = 0.5 * self.k_elastic * delta ** 2

        # Plastic region: quadratic + step + high stiffness
        overshoot = abs_delta - elastic_threshold
        plastic_energy = (0.5 * self.k_elastic * elastic_threshold ** 2 +
                         self.step_penalty * overshoot +
                         0.5 * self.k_plastic * overshoot ** 2)

        energy = torch.where(abs_delta <= elastic_threshold,
                            elastic_energy,
                            plastic_energy)

        return energy

    def total_edge_energy(self, positions, edges, edge_orientations):
        """
        Calculate total energy from all edges

        Args:
            positions: [N, 3] tensor of node positions
            edges: [E, 2] tensor of edge indices (source, target)
            edge_orientations: [E] tensor or list ('h' or 'v')

        Returns:
            Total edge energy (scalar)
        """
        total_energy = 0.0

        for i in range(edges.shape[0]):
            src, tgt = edges[i]
            pos1 = positions[src]
            pos2 = positions[tgt]

            distance = torch.norm(pos2 - pos1)

            # Determine rest length based on orientation
            if edge_orientations[i] == 'v':
                rest_length = self.vertical_rest
            else:  # 'h'
                rest_length = self.horizontal_rest

            energy = self.edge_energy(distance, rest_length)
            total_energy += energy

        return total_energy


class RepulsionModel:
    """
    Topology-aware repulsion using adjacency matrix powers

    Instead of O(n²) all-pairs repulsion, only repel nodes that are
    close in graph topology (within k hops).
    """

    def __init__(self, adjacency_matrix, num_powers=3, strength=50.0):
        """
        Args:
            adjacency_matrix: [N, N] sparse or dense matrix (0/1)
            num_powers: Number of adjacency powers to include (default 3)
            strength: Repulsion strength parameter
        """
        self.num_powers = num_powers
        self.strength = strength

        # Compute repulsion matrix
        self.repulsion_matrix = self._compute_repulsion_matrix(adjacency_matrix)

        # Get sparse indices for efficient computation
        self.repulsion_pairs = self._get_repulsion_pairs()

    def _compute_repulsion_matrix(self, A):
        """
        Compute repulsion matrix from adjacency powers

        Returns matrix where R[i,j] = 1 if nodes i and j should repel
        """
        if torch.is_tensor(A):
            A = A.numpy()

        N = A.shape[0]

        # Convert to float for matrix multiplication
        A_float = A.astype(float)

        # Accumulate powers
        repulsion = np.zeros((N, N))
        A_power = A_float.copy()

        for k in range(1, self.num_powers + 1):
            if k > 1:
                A_power = A_power @ A_float

            # Sign function: non-zero → 1
            repulsion += (A_power != 0).astype(float)

        # Take sign: any connection → 1
        repulsion = (repulsion != 0).astype(float)

        # Remove diagonal (no self-repulsion)
        np.fill_diagonal(repulsion, 0)

        return repulsion

    def _get_repulsion_pairs(self):
        """Get list of (i, j) pairs that should repel"""
        rows, cols = np.nonzero(self.repulsion_matrix)

        # Only keep i < j to avoid double-counting
        pairs = [(i, j) for i, j in zip(rows, cols) if i < j]

        return pairs

    def repulsion_energy(self, positions):
        """
        Calculate repulsion energy

        Uses inverse-square repulsion: E = k / r²

        Args:
            positions: [N, 3] tensor of node positions

        Returns:
            Total repulsion energy (scalar)
        """
        energy = 0.0

        for i, j in self.repulsion_pairs:
            pos1 = positions[i]
            pos2 = positions[j]

            distance = torch.norm(pos2 - pos1) + 1e-6  # Avoid division by zero

            # Inverse square repulsion
            energy += self.strength / (distance ** 2)

        return energy

    def repulsion_energy_vectorized(self, positions):
        """
        Vectorized version of repulsion energy (faster for large graphs)

        Args:
            positions: [N, 3] tensor

        Returns:
            Total repulsion energy
        """
        if len(self.repulsion_pairs) == 0:
            return torch.tensor(0.0)

        # Extract indices
        indices = torch.tensor(self.repulsion_pairs, dtype=torch.long)
        i_indices = indices[:, 0]
        j_indices = indices[:, 1]

        # Get positions
        pos_i = positions[i_indices]
        pos_j = positions[j_indices]

        # Compute distances
        distances = torch.norm(pos_j - pos_i, dim=1) + 1e-6

        # Inverse square repulsion
        energies = self.strength / (distances ** 2)

        return torch.sum(energies)


class FlatnessModel:
    """
    Solid angle-based flatness enforcement (FUTURE)

    Encourages fabric to lie flat by penalizing deviations from
    planar configuration using solid angles.
    """

    def __init__(self, weight=0.1):
        self.weight = weight

    def flatness_energy(self, positions, edges):
        """
        Calculate flatness energy using solid angles

        TODO: Implement solid angle calculation
        - For each node, compute solid angle subtended by neighbor faces
        - Flat configuration has solid angle = 2π
        - Penalize deviation from 2π

        Args:
            positions: [N, 3] tensor
            edges: [E, 2] tensor

        Returns:
            Flatness energy (scalar)
        """
        # Placeholder for future implementation
        return torch.tensor(0.0)


def visualize_force_curve(force_model, orientation='v', num_points=100):
    """
    Plot force curve for visualization/debugging

    Args:
        force_model: YarnForceModel instance
        orientation: 'v' or 'h'
        num_points: Number of points to plot
    """
    import matplotlib.pyplot as plt

    rest_length = (force_model.vertical_rest if orientation == 'v'
                  else force_model.horizontal_rest)

    # Distance range: 0.5x to 2x rest length
    distances = np.linspace(0.5 * rest_length, 2.0 * rest_length, num_points)

    forces = []
    energies = []

    for d in distances:
        d_torch = torch.tensor(d, dtype=torch.float32)
        force = force_model.edge_force(d_torch, rest_length, use_torch=False)
        energy = force_model.edge_energy(d_torch, rest_length)

        forces.append(force)
        energies.append(energy.item())

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Force curve
    ax1.plot(distances, forces, 'b-', linewidth=2)
    ax1.axvline(rest_length, color='r', linestyle='--', label='Rest length')
    ax1.axvline(rest_length * (1 + force_model.elastic_limit),
               color='orange', linestyle='--', label='Elastic limit')
    ax1.axvline(rest_length * (1 - force_model.elastic_limit),
               color='orange', linestyle='--')
    ax1.axhline(0, color='k', linestyle='-', alpha=0.3)
    ax1.set_xlabel('Distance (mm)')
    ax1.set_ylabel('Force')
    ax1.set_title(f'{"Vertical" if orientation == "v" else "Horizontal"} Edge Force Curve')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Energy curve
    ax2.plot(distances, energies, 'g-', linewidth=2)
    ax2.axvline(rest_length, color='r', linestyle='--', label='Rest length')
    ax2.axvline(rest_length * (1 + force_model.elastic_limit),
               color='orange', linestyle='--', label='Elastic limit')
    ax2.axvline(rest_length * (1 - force_model.elastic_limit),
               color='orange', linestyle='--')
    ax2.set_xlabel('Distance (mm)')
    ax2.set_ylabel('Energy')
    ax2.set_title('Edge Potential Energy')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('force_curve.png', dpi=150)
    print("Saved force curve to force_curve.png")
    plt.close()


if __name__ == '__main__':
    print("Testing YarnForceModel...")

    # Create force model with default parameters
    force_model = YarnForceModel(
        vertical_rest=3.0,
        horizontal_rest=4.0,
        elastic_limit=0.4,
        k_elastic=0.1,
        k_plastic=10.0,
        step_penalty=5.0
    )

    # Test force calculation at various distances
    test_distances = [1.5, 2.0, 3.0, 3.5, 4.0, 5.0]
    print("\nVertical edge forces (rest = 3.0mm):")
    for d in test_distances:
        d_torch = torch.tensor(d)
        force = force_model.edge_force(d_torch, 3.0)
        energy = force_model.edge_energy(d_torch, 3.0)
        print(f"  d={d:.1f}mm: force={force:.3f}, energy={energy:.3f}")

    # Visualize force curves
    visualize_force_curve(force_model, orientation='v')
    visualize_force_curve(force_model, orientation='h')

    print("\nForce curves saved to force_curve.png")
