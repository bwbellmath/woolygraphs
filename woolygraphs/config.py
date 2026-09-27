"""
Configuration loading and validation for layout styles.

Loads style JSON files that configure layout behavior, optimizer settings,
and topology options.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import json
from pathlib import Path


@dataclass
class EdgeLengthConfig:
    """Edge length configuration in millimeters."""
    h_length_mm: float = 4.0
    v_length_mm: float = 3.0


@dataclass
class TopologyConfig:
    """Topology configuration for circular/mobius knitting."""
    circular: bool = False
    mobius: bool = False
    join_stitch: Optional[int] = None  # Index where circular join occurs


@dataclass
class ShapingConfig:
    """3D shaping configuration for short rows."""
    allow_3d: bool = False
    short_row_profile: Optional[str] = None  # 'semicircle', 'catenary', etc.


@dataclass
class CableConfig:
    """Cable layout configuration."""
    squeeze_factor: float = 0.8  # How much to compress cable regions


@dataclass
class MannequinConfig:
    """Mannequin-constrained layout configuration."""
    enabled: bool = False
    mesh_file: Optional[str] = None
    anchors: List[Dict[str, int]] = field(default_factory=list)


@dataclass
class OptimizerConfig:
    """Optimizer settings."""
    method: str = 'pytorch'  # 'pytorch' or 'pyomo'
    epochs: int = 1000
    learning_rate: float = 0.01
    forces: Dict[str, float] = field(default_factory=lambda: {
        'edge_spring': 1.0,
        'repulsion': 0.2,
        'solid_angle': 0.1
    })


@dataclass
class LayoutConfig:
    """
    Complete layout configuration.

    Combines all configuration aspects for the layout pipeline.
    """
    pattern_file: Optional[str] = None
    layout_mode: str = 'flat'  # 'flat', 'circular'
    edge_lengths: EdgeLengthConfig = field(default_factory=EdgeLengthConfig)
    topology: TopologyConfig = field(default_factory=TopologyConfig)
    shaping: ShapingConfig = field(default_factory=ShapingConfig)
    cables: CableConfig = field(default_factory=CableConfig)
    mannequin: MannequinConfig = field(default_factory=MannequinConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)

    @classmethod
    def from_dict(cls, data: dict) -> 'LayoutConfig':
        """Create LayoutConfig from dictionary (JSON parsed data)."""
        edge_lengths = EdgeLengthConfig(**data.get('edge_lengths', {}))

        topology_data = data.get('topology', {})
        topology = TopologyConfig(
            circular=topology_data.get('circular', False),
            mobius=topology_data.get('mobius', False),
            join_stitch=topology_data.get('join_stitch')
        )

        shaping_data = data.get('shaping', {})
        shaping = ShapingConfig(
            allow_3d=shaping_data.get('allow_3d', False),
            short_row_profile=shaping_data.get('short_row_profile')
        )

        cables_data = data.get('cables', {})
        cables = CableConfig(
            squeeze_factor=cables_data.get('squeeze_factor', 0.8)
        )

        mannequin_data = data.get('mannequin', {})
        mannequin = MannequinConfig(
            enabled=mannequin_data.get('enabled', False),
            mesh_file=mannequin_data.get('mesh_file'),
            anchors=mannequin_data.get('anchors', [])
        )

        optimizer_data = data.get('optimizer', {})
        optimizer = OptimizerConfig(
            method=optimizer_data.get('method', 'pytorch'),
            epochs=optimizer_data.get('epochs', 1000),
            learning_rate=optimizer_data.get('learning_rate', 0.01),
            forces=optimizer_data.get('forces', {
                'edge_spring': 1.0,
                'repulsion': 0.2,
                'solid_angle': 0.1
            })
        )

        return cls(
            pattern_file=data.get('pattern_file'),
            layout_mode=data.get('layout_mode', 'flat'),
            edge_lengths=edge_lengths,
            topology=topology,
            shaping=shaping,
            cables=cables,
            mannequin=mannequin,
            optimizer=optimizer
        )

    @classmethod
    def default_flat(cls) -> 'LayoutConfig':
        """Create default configuration for flat knitting."""
        return cls(layout_mode='flat')

    @classmethod
    def default_circular(cls, n_cast_on: int) -> 'LayoutConfig':
        """Create default configuration for circular knitting."""
        return cls(
            layout_mode='circular',
            topology=TopologyConfig(circular=True, join_stitch=n_cast_on)
        )

    @classmethod
    def default_mobius(cls, n_cast_on: int) -> 'LayoutConfig':
        """Create default configuration for mobius strip."""
        return cls(
            layout_mode='circular',
            topology=TopologyConfig(circular=True, mobius=True, join_stitch=n_cast_on)
        )


def load_config(path: str) -> LayoutConfig:
    """
    Load layout configuration from JSON file.

    Args:
        path: Path to style JSON file.

    Returns:
        LayoutConfig object.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, 'r') as f:
        data = json.load(f)

    return LayoutConfig.from_dict(data)


def infer_config_from_pattern(pattern_path: str) -> LayoutConfig:
    """
    Try to load config from pattern's companion style file,
    or return default config.

    Args:
        pattern_path: Path to pattern file (.txt)

    Returns:
        LayoutConfig from companion .style.json or default flat config.
    """
    pattern_path = Path(pattern_path)
    style_path = pattern_path.with_suffix('.style.json')

    if style_path.exists():
        return load_config(str(style_path))

    # Also try replacing .txt with .style.json
    if pattern_path.suffix == '.txt':
        style_path = pattern_path.parent / (pattern_path.stem + '.style.json')
        if style_path.exists():
            return load_config(str(style_path))

    # Return default flat config
    return LayoutConfig.default_flat()
