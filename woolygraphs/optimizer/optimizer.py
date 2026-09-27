"""
Layout optimizer framework.

Provides shared optimizer that uses pluggable force components
and backends to refine baseline positions.
"""

import numpy as np
from typing import List, Optional, Callable
import logging

from ..graph import KnitGraph
from ..config import LayoutConfig
from .forces import (
    ForceComponent,
    EdgeSpringForce,
    RepulsionForce,
    SolidAngleForce,
    PlanarityForce,
)
from .backends import PyTorchBackend, ForceDirectedBackend, TORCH_AVAILABLE

logger = logging.getLogger(__name__)


class LayoutOptimizer:
    """
    Shared optimizer for refining graph layouts.

    Uses configurable force components and backends (PyTorch or
    force-directed numpy) to optimize vertex positions.

    Usage:
        config = LayoutConfig(...)
        optimizer = LayoutOptimizer(config)
        optimized_positions = optimizer.optimize(graph, baseline_positions)

    Attributes:
        config: Layout configuration
        forces: List of force components
        backend: Optimizer backend instance
    """

    def __init__(self, config: LayoutConfig):
        """
        Initialize optimizer with configuration.

        Args:
            config: Layout configuration specifying forces and backend
        """
        self.config = config
        self.forces = self._create_forces()
        self.backend = self._create_backend()
        self._callbacks: List[Callable] = []

    def _create_forces(self) -> List[ForceComponent]:
        """Create force components based on configuration."""
        forces = []
        fc = self.config.optimizer.forces

        if fc.get('edge_spring', 0) > 0:
            forces.append(EdgeSpringForce(weight=fc['edge_spring']))
            logger.debug(f"Added EdgeSpringForce with weight {fc['edge_spring']}")

        if fc.get('repulsion', 0) > 0:
            forces.append(RepulsionForce(weight=fc['repulsion']))
            logger.debug(f"Added RepulsionForce with weight {fc['repulsion']}")

        if fc.get('solid_angle', 0) > 0:
            # Use PlanarityForce as it's more stable
            forces.append(PlanarityForce(weight=fc['solid_angle']))
            logger.debug(f"Added PlanarityForce with weight {fc['solid_angle']}")

        return forces

    def _create_backend(self):
        """Create optimizer backend based on configuration."""
        method = self.config.optimizer.method

        if method == 'pytorch':
            if TORCH_AVAILABLE:
                return PyTorchBackend()
            else:
                logger.warning(
                    "PyTorch not available, falling back to force-directed"
                )
                return ForceDirectedBackend()
        elif method == 'force_directed':
            return ForceDirectedBackend()
        else:
            logger.warning(f"Unknown method '{method}', using force-directed")
            return ForceDirectedBackend()

    def add_callback(self, callback: Callable[[int, np.ndarray, float], None]):
        """
        Add a callback for monitoring optimization progress.

        Callback signature: callback(epoch, positions, loss)
        """
        self._callbacks.append(callback)

    def optimize(
        self,
        graph: KnitGraph,
        initial_positions: np.ndarray,
        verbose: bool = False
    ) -> np.ndarray:
        """
        Optimize positions starting from initial layout.

        Args:
            graph: The knit graph
            initial_positions: Starting positions from baseline
            verbose: Whether to print progress

        Returns:
            Optimized positions array
        """
        if verbose:
            print(f"Optimizing {graph.n_stitches} stitches with {len(graph.edges)} edges")
            print(f"Backend: {type(self.backend).__name__}")
            print(f"Forces: {[f.name for f in self.forces]}")
            print(f"Epochs: {self.config.optimizer.epochs}")

        # Create combined callback
        def combined_callback(epoch, positions, loss):
            if verbose and epoch % 100 == 0:
                print(f"  Epoch {epoch}: loss = {loss:.6f}")
            for cb in self._callbacks:
                cb(epoch, positions, loss)

        # Run optimization based on backend type
        if isinstance(self.backend, PyTorchBackend):
            optimized = self.backend.optimize(
                graph=graph,
                initial_positions=initial_positions,
                config=self.config,
                callback=combined_callback
            )
        else:
            # Force-directed backend
            optimized = self.backend.optimize(
                graph=graph,
                initial_positions=initial_positions,
                forces=self.forces,
                epochs=self.config.optimizer.epochs,
                learning_rate=self.config.optimizer.learning_rate,
                callback=combined_callback
            )

        if verbose:
            self._print_summary(graph, initial_positions, optimized)

        return optimized

    def _print_summary(
        self,
        graph: KnitGraph,
        before: np.ndarray,
        after: np.ndarray
    ):
        """Print optimization summary."""
        print("\nOptimization Summary:")

        # Edge length statistics
        spring = EdgeSpringForce()
        before_errors = spring.compute_edge_errors(before, graph)
        after_errors = spring.compute_edge_errors(after, graph)

        for orient in ['h', 'v']:
            if before_errors[orient]:
                before_rmse = np.sqrt(np.mean([e[2]**2 for e in before_errors[orient]]))
                after_rmse = np.sqrt(np.mean([e[2]**2 for e in after_errors[orient]]))
                orient_name = 'Horizontal' if orient == 'h' else 'Vertical'
                print(f"  {orient_name} edge RMSE: {before_rmse:.4f} -> {after_rmse:.4f} mm")

        # Energy comparison
        before_energy = sum(f.compute_energy(before, graph) for f in self.forces)
        after_energy = sum(f.compute_energy(after, graph) for f in self.forces)
        print(f"  Total energy: {before_energy:.4f} -> {after_energy:.4f}")


def quick_optimize(
    graph: KnitGraph,
    positions: np.ndarray,
    epochs: int = 500,
    edge_spring: float = 1.0,
    repulsion: float = 0.1,
    solid_angle: float = 0.05,
    verbose: bool = False
) -> np.ndarray:
    """
    Quick optimization with sensible defaults.

    Convenience function for one-off optimization without
    creating configuration objects.

    Args:
        graph: The knit graph
        positions: Initial positions
        epochs: Number of optimization epochs
        edge_spring: Weight for edge spring force
        repulsion: Weight for repulsion force
        solid_angle: Weight for planarity force
        verbose: Print progress

    Returns:
        Optimized positions
    """
    from ..config import LayoutConfig, OptimizerConfig

    opt_config = OptimizerConfig(
        method='pytorch' if TORCH_AVAILABLE else 'force_directed',
        epochs=epochs,
        learning_rate=0.01,
        forces={
            'edge_spring': edge_spring,
            'repulsion': repulsion,
            'solid_angle': solid_angle,
        }
    )

    config = LayoutConfig(optimizer=opt_config)
    optimizer = LayoutOptimizer(config)

    return optimizer.optimize(graph, positions, verbose=verbose)
