"""
Optimizer module for refining graph layouts.

Main classes:
- LayoutOptimizer: Configure and run optimization
- quick_optimize: Convenience function for simple cases

Force components:
- EdgeSpringForce: Pull edges toward target lengths
- RepulsionForce: Universal repulsion
- SolidAngleForce: Manifold conformance
- PlanarityForce: Local flatness

Backends:
- PyTorchBackend: Gradient-based (recommended)
- ForceDirectedBackend: Numpy fallback
"""

from .optimizer import LayoutOptimizer, quick_optimize
from .forces import (
    ForceComponent,
    EdgeSpringForce,
    RepulsionForce,
    SoftRepulsionForce,
    SolidAngleForce,
    PlanarityForce,
)
from .backends import PyTorchBackend, ForceDirectedBackend, TORCH_AVAILABLE

__all__ = [
    'LayoutOptimizer',
    'quick_optimize',
    'ForceComponent',
    'EdgeSpringForce',
    'RepulsionForce',
    'SoftRepulsionForce',
    'SolidAngleForce',
    'PlanarityForce',
    'PyTorchBackend',
    'ForceDirectedBackend',
    'TORCH_AVAILABLE',
]
