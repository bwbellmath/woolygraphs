"""
Force components for layout optimization.

Available forces:
- EdgeSpringForce: Pull edges toward target lengths
- RepulsionForce: Universal inverse-square repulsion
- SoftRepulsionForce: Repulsion only when too close
- SolidAngleForce: Encourage flat 2-manifold
- PlanarityForce: Simpler local flatness
"""

from .base import ForceComponent
from .edge_spring import EdgeSpringForce
from .repulsion import RepulsionForce, SoftRepulsionForce
from .solid_angle import SolidAngleForce, PlanarityForce

__all__ = [
    'ForceComponent',
    'EdgeSpringForce',
    'RepulsionForce',
    'SoftRepulsionForce',
    'SolidAngleForce',
    'PlanarityForce',
]
