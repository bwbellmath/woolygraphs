"""
WoolyGraphs Layout Optimizer

PyTorch + ADAM-based optimization for physically-realistic knitting layouts
"""

import torch
import torch.optim as optim
import numpy as np
import pandas as pd
import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from forces import YarnForceModel, RepulsionModel, FlatnessModel


class LayoutConfig:
    """Configuration for layout optimization"""

    def __init__(self):
        # Optimizer settings
        self.optimizer = 'adam'
        self.learning_rate = 0.01
        self.num_iterations = 1000
        self.log_interval = 100

        # Edge force parameters
        self.vertical_rest_length = 3.0    # mm
        self.horizontal_rest_length = 4.0  # mm
        self.elastic_limit_percent = 0.4   # 40% stretch
        self.k_elastic = 0.1               # Low stiffness
        self.k_plastic = 10.0              # High stiffness
        self.step_penalty = 5.0            # Force jump

        # Repulsion parameters
        self.repulsion_powers = 3          # Use A + A² + A³
        self.repulsion_strength = 50.0

        # Flatness (future)
        self.use_flatness = False
        self.flatness_weight = 0.1

        # Constraints
        self.freeze_boundary = False       # Freeze edge nodes

    @classmethod
    def from_dict(cls, config_dict):
        """Create config from dictionary"""
        config = cls()
        for key, value in config_dict.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config


class YarnLayoutOptimizer:
    """
    Optimize stitch positions using PyTorch and ADAM

    Uses physically-realistic yarn mechanics:
    - Custom edge force curves (elastic + plastic regions)
    - Topology-aware repulsion (adjacency matrix powers)
    - Optional flatness constraints
    """

    def __init__(self, graph_data, initial_positions=None, config=None):
        """
        Args:
            graph_data: Dictionary with 'nodes', 'edges', 'metadata'
            initial_positions: [N, 3] array of initial positions (optional)
            config: LayoutConfig instance (optional)
        """
        self.graph_data = graph_data
        self.config = config or LayoutConfig()

        # Extract graph structure
        self.num_nodes = len(graph_data['nodes'])
        self.edges = self._extract_edges()
        self.edge_orientations = self._extract_edge_orientations()

        # Initialize positions
        if initial_positions is not None:
            self.positions = torch.tensor(initial_positions, dtype=torch.float32, requires_grad=True)
        else:
            self.positions = self._initialize_positions()

        # Build adjacency matrix
        self.adjacency_matrix = self._build_adjacency_matrix()

        # Initialize force models
        self.force_model = YarnForceModel(
            vertical_rest=self.config.vertical_rest_length,
            horizontal_rest=self.config.horizontal_rest_length,
            elastic_limit=self.config.elastic_limit_percent,
            k_elastic=self.config.k_elastic,
            k_plastic=self.config.k_plastic,
            step_penalty=self.config.step_penalty
        )

        self.repulsion_model = RepulsionModel(
            self.adjacency_matrix,
            num_powers=self.config.repulsion_powers,
            strength=self.config.repulsion_strength
        )

        if self.config.use_flatness:
            self.flatness_model = FlatnessModel(weight=self.config.flatness_weight)
        else:
            self.flatness_model = None

        # Setup optimizer
        if self.config.optimizer == 'adam':
            self.optimizer = optim.Adam([self.positions], lr=self.config.learning_rate)
        elif self.config.optimizer == 'sgd':
            self.optimizer = optim.SGD([self.positions], lr=self.config.learning_rate, momentum=0.9)
        else:
            raise ValueError(f"Unknown optimizer: {self.config.optimizer}")

        # History for plotting
        self.loss_history = []
        self.edge_energy_history = []
        self.repulsion_energy_history = []

        print(f"Initialized YarnLayoutOptimizer:")
        print(f"  Nodes: {self.num_nodes}")
        print(f"  Edges: {len(self.edges)}")
        print(f"  Repulsion pairs: {len(self.repulsion_model.repulsion_pairs)}")
        print(f"  Optimizer: {self.config.optimizer}")
        print(f"  Learning rate: {self.config.learning_rate}")

    def _extract_edges(self):
        """Extract edge list as tensor"""
        edges = []
        for edge in self.graph_data['edges']:
            edges.append([edge['source'], edge['target']])
        return torch.tensor(edges, dtype=torch.long)

    def _extract_edge_orientations(self):
        """Extract edge orientations"""
        return [edge['orientation'] for edge in self.graph_data['edges']]

    def _build_adjacency_matrix(self):
        """Build adjacency matrix from edges"""
        N = self.num_nodes
        A = np.zeros((N, N))

        for edge in self.graph_data['edges']:
            i, j = edge['source'], edge['target']
            A[i, j] = 1
            A[j, i] = 1

        return A

    def _initialize_positions(self):
        """Initialize positions in grid layout"""
        # Simple grid layout
        grid_size = int(np.ceil(np.sqrt(self.num_nodes)))
        positions = []

        for i in range(self.num_nodes):
            row = i // grid_size
            col = i % grid_size

            # Use physical spacing
            x = col * self.config.horizontal_rest_length
            y = row * self.config.vertical_rest_length
            z = 0.0

            positions.append([x, y, z])

        return torch.tensor(positions, dtype=torch.float32, requires_grad=True)

    def compute_loss(self):
        """
        Compute total loss function

        Returns:
            loss: Total loss (scalar)
            loss_dict: Dictionary with individual loss components
        """
        # Edge forces
        edge_energy = self.force_model.total_edge_energy(
            self.positions,
            self.edges,
            self.edge_orientations
        )

        # Repulsion
        repulsion_energy = self.repulsion_model.repulsion_energy_vectorized(self.positions)

        # Flatness (if enabled)
        flatness_energy = 0.0
        if self.flatness_model is not None:
            flatness_energy = self.flatness_model.flatness_energy(
                self.positions,
                self.edges
            )

        # Total loss
        loss = edge_energy + repulsion_energy + flatness_energy

        loss_dict = {
            'total': loss.item(),
            'edge': edge_energy.item(),
            'repulsion': repulsion_energy.item(),
            'flatness': flatness_energy if isinstance(flatness_energy, float) else flatness_energy.item()
        }

        return loss, loss_dict

    def optimize(self, num_iterations=None):
        """
        Run optimization loop

        Args:
            num_iterations: Number of iterations (overrides config)
        """
        if num_iterations is None:
            num_iterations = self.config.num_iterations

        print(f"\nStarting optimization for {num_iterations} iterations...")

        for iteration in range(num_iterations):
            # Zero gradients
            self.optimizer.zero_grad()

            # Compute loss
            loss, loss_dict = self.compute_loss()

            # Backward pass
            loss.backward()

            # Optimization step
            self.optimizer.step()

            # Record history
            self.loss_history.append(loss_dict['total'])
            self.edge_energy_history.append(loss_dict['edge'])
            self.repulsion_energy_history.append(loss_dict['repulsion'])

            # Log progress
            if iteration % self.config.log_interval == 0:
                print(f"Iteration {iteration:4d}: "
                      f"Loss={loss_dict['total']:8.3f}, "
                      f"Edge={loss_dict['edge']:8.3f}, "
                      f"Repulsion={loss_dict['repulsion']:8.3f}")

        print(f"\nOptimization complete!")
        print(f"Final loss: {self.loss_history[-1]:.3f}")

    def get_optimized_positions(self):
        """
        Get optimized positions as numpy array

        Returns:
            positions: [N, 3] numpy array
        """
        return self.positions.detach().numpy()

    def plot_optimization_history(self, save_path='optimization_history.png'):
        """Plot loss history"""
        fig, axes = plt.subplots(1, 3, figsize=(15, 4))

        # Total loss
        axes[0].plot(self.loss_history, 'b-', linewidth=2)
        axes[0].set_xlabel('Iteration')
        axes[0].set_ylabel('Total Loss')
        axes[0].set_title('Total Loss')
        axes[0].grid(True, alpha=0.3)

        # Edge energy
        axes[1].plot(self.edge_energy_history, 'g-', linewidth=2)
        axes[1].set_xlabel('Iteration')
        axes[1].set_ylabel('Edge Energy')
        axes[1].set_title('Edge Forces')
        axes[1].grid(True, alpha=0.3)

        # Repulsion energy
        axes[2].plot(self.repulsion_energy_history, 'r-', linewidth=2)
        axes[2].set_xlabel('Iteration')
        axes[2].set_ylabel('Repulsion Energy')
        axes[2].set_title('Repulsion')
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        print(f"Saved optimization history to {save_path}")
        plt.close()

    def visualize_layout(self, save_path='layout_3d.png', show_edges=True):
        """Visualize 3D layout"""
        positions = self.get_optimized_positions()

        fig = plt.figure(figsize=(10, 10))
        ax = fig.add_subplot(111, projection='3d')

        # Plot nodes
        ax.scatter(positions[:, 0],
                  positions[:, 1],
                  positions[:, 2],
                  c='cyan', s=50, alpha=0.6)

        # Plot edges
        if show_edges:
            for i, (src, tgt) in enumerate(self.edges.numpy()):
                pos1 = positions[src]
                pos2 = positions[tgt]

                color = 'cyan' if self.edge_orientations[i] == 'h' else 'yellow'

                ax.plot([pos1[0], pos2[0]],
                       [pos1[1], pos2[1]],
                       [pos1[2], pos2[2]],
                       color=color, alpha=0.3, linewidth=1)

        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_zlabel('Z (mm)')
        ax.set_title('Optimized Layout')

        plt.savefig(save_path, dpi=150)
        print(f"Saved layout visualization to {save_path}")
        plt.close()


def load_graph_from_json(json_path):
    """Load graph data from JSON file"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    return data


def save_optimized_graph(graph_data, optimized_positions, output_path):
    """Save graph with optimized positions to JSON"""

    # Add positions to nodes
    for i, node in enumerate(graph_data['nodes']):
        node['position'] = {
            'x': float(optimized_positions[i, 0]),
            'y': float(optimized_positions[i, 1]),
            'z': float(optimized_positions[i, 2])
        }

    # Add metadata flag
    if 'metadata' not in graph_data:
        graph_data['metadata'] = {}
    graph_data['metadata']['hasOptimizedPositions'] = True

    # Save
    with open(output_path, 'w') as f:
        json.dump(graph_data, f, indent=2)

    print(f"Saved optimized graph to {output_path}")


def main():
    """Command-line interface"""
    if len(sys.argv) < 2:
        print("Usage: python optimize_layout.py <input.json> [output.json]")
        print("\nOptimize graph layout using PyTorch + ADAM")
        print("\nExample:")
        print("  python optimize_layout.py viewer3d/data/small_stockinette.json")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path.replace('.json', '_optimized.json')

    print("=" * 60)
    print("WoolyGraphs Layout Optimizer")
    print("=" * 60)

    # Load graph
    print(f"\nLoading graph from {input_path}...")
    graph_data = load_graph_from_json(input_path)

    # Create optimizer
    config = LayoutConfig()
    config.num_iterations = 1000
    config.log_interval = 100

    optimizer = YarnLayoutOptimizer(graph_data, config=config)

    # Optimize
    optimizer.optimize()

    # Get optimized positions
    optimized_positions = optimizer.get_optimized_positions()

    # Save results
    save_optimized_graph(graph_data, optimized_positions, output_path)

    # Plot results
    optimizer.plot_optimization_history()
    optimizer.visualize_layout()

    print("\n" + "=" * 60)
    print("Optimization complete!")
    print(f"  Output: {output_path}")
    print(f"  History: optimization_history.png")
    print(f"  Layout: layout_3d.png")
    print("=" * 60)


if __name__ == '__main__':
    main()
