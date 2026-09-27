"""
Stitch definitions and loading utilities.

Provides dataclasses for stitch techniques and edge specifications,
plus functions to load stitch definitions from JSON.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union, Tuple
import json
from pathlib import Path


@dataclass
class Edge:
    """
    Represents an edge connection from a stitch.

    Attributes:
        v: Vertex offset as [row_offset, col_offset] or special string like 'first'
        orient: Edge orientation - 'h' (horizontal) or 'v' (vertical)
        bk: Edge type - 'b' (bump/consume) or 'k' (keep)
        length_mm: Target edge length in millimeters
    """
    v: Union[Tuple[int, int], str]
    orient: str
    bk: str
    length_mm: float

    def __post_init__(self):
        if self.orient not in ('h', 'v'):
            raise ValueError(f"orient must be 'h' or 'v', got '{self.orient}'")
        if self.bk not in ('b', 'k'):
            raise ValueError(f"bk must be 'b' or 'k', got '{self.bk}'")


@dataclass
class StitchTech:
    """
    Stitch technique definition.

    Attributes:
        character: Display character ('k' for knit, 'p' for purl)
        cursor_inc: How many stitches to advance cursor (1 for k, 2 for k2tog)
        keep: Whether the source stitch stays on needle after this stitch
        add: Number of new stitches created (1 for k, 2 for kfb, 0 for yo)
        extra: Additional stitches inserted after cursor
        edge_list: List of edges this stitch creates
        cursor_dir: Whether this stitch reverses knitting direction (True for 'turn')
        topology: Optional topology marker ('circular', 'mobius', None)
    """
    character: str
    cursor_inc: int
    keep: bool
    add: int
    extra: int
    edge_list: List[Edge]
    cursor_dir: bool
    topology: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'StitchTech':
        """Create StitchTech from dictionary (JSON parsed data)."""
        edge_list = []
        for e in data.get('edge_list', []):
            v = e['v']
            # Convert list to tuple if needed
            if isinstance(v, list):
                v = tuple(v)
            edge_list.append(Edge(
                v=v,
                orient=e['orient'],
                bk=e['bk'],
                length_mm=e.get('length_mm', e.get('length', 4.0))  # fallback to old 'length' key
            ))

        return cls(
            character=data['character'],
            cursor_inc=data.get('cursor_inc', 1),
            keep=data.get('keep', False),
            add=data.get('add', 1),
            extra=data.get('extra', 0),
            edge_list=edge_list,
            cursor_dir=data.get('cursor_dir', False),
            topology=data.get('topology', None)
        )


# Default edge lengths in mm
H_LENGTH_MM = 4.0  # horizontal (within row)
V_LENGTH_MM = 3.0  # vertical (between rows)


def load_stitches(path: Optional[str] = None) -> Dict[str, StitchTech]:
    """
    Load stitch definitions from JSON file.

    Args:
        path: Path to stitches JSON file. If None, uses default stitches.txt
              in the project root.

    Returns:
        Dictionary mapping stitch names to StitchTech objects.
    """
    if path is None:
        # Look for stitches.txt in common locations
        candidates = [
            Path(__file__).parent.parent / 'stitches.txt',
            Path(__file__).parent.parent / 'stitches.json',
            Path('stitches.txt'),
            Path('stitches.json'),
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break
        else:
            raise FileNotFoundError(
                f"Could not find stitches file. Searched: {[str(c) for c in candidates]}"
            )

    path = Path(path)
    with open(path, 'r') as f:
        data = json.load(f)

    stitches = {}
    for name, stitch_data in data.items():
        # Skip metadata keys
        if name.startswith('_'):
            continue
        stitches[name] = StitchTech.from_dict(stitch_data)

    return stitches


def get_default_lengths() -> Tuple[float, float]:
    """Return default (horizontal, vertical) edge lengths in mm."""
    return (H_LENGTH_MM, V_LENGTH_MM)
