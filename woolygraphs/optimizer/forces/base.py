"""
Base class for force components in the layout optimizer.

All force components inherit from ForceComponent and implement
compute() for force vectors and energy() for scalar energy.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from ...graph import KnitGraph


class ForceComponent(ABC):
    """
    Abstract base class for force components.

    Force components contribute to the optimization objective by:
    1. Computing forces on vertices (for force-directed methods)
    2. Computing scalar energy (for gradient-based optimization)

    Attributes:
        weight: Scaling factor for this force component
        name: Human-readable name for logging
    """

    def __init__(self, weight: float = 1.0, name: str = "force"):
        self.weight = weight
        self.name = name

    @abstractmethod
    def compute_forces(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> np.ndarray:
        """
        Compute force vectors for all vertices.

        Args:
            positions: (n, 3) array of vertex positions
            graph: The knit graph structure

        Returns:
            (n, 3) array of force vectors
        """
        pass

    @abstractmethod
    def compute_energy(
        self,
        positions: np.ndarray,
        graph: 'KnitGraph'
    ) -> float:
        """
        Compute scalar energy for this force component.

        Args:
            positions: (n, 3) array of vertex positions
            graph: The knit graph structure

        Returns:
            Scalar energy value
        """
        pass

    def __repr__(self):
        return f"{self.__class__.__name__}(weight={self.weight})"
