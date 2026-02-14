"""
WoolyGraphs Layout Package

Phase 1: Initial layout (pattern compilation)
Phase 2: Physics-based optimization
Phase 3: Display / export
"""

from layout.stitch_instance import StitchInstance, BackEdge, Gauge, LayoutGraph
from layout.initial_layout import compile_pattern, load_stitch_definitions
from layout.forces import (
    YarnForceModel,
    RepulsionModel,
    normal_coherence_loss,
    normal_unit_loss,
    out_of_plane_loss,
    in_plane_angle_loss,
    offset_loss,
)
from layout.mesh import build_triangulation, solid_angle_at_vertex, flatness_energy
from layout.optimizer import LayoutOptimizer, OptimizerConfig

__all__ = [
    "StitchInstance",
    "BackEdge",
    "Gauge",
    "LayoutGraph",
    "compile_pattern",
    "load_stitch_definitions",
    "YarnForceModel",
    "RepulsionModel",
    "normal_coherence_loss",
    "normal_unit_loss",
    "out_of_plane_loss",
    "in_plane_angle_loss",
    "offset_loss",
    "build_triangulation",
    "solid_angle_at_vertex",
    "flatness_energy",
    "LayoutOptimizer",
    "OptimizerConfig",
]
