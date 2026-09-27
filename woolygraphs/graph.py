"""
Graph construction from knitting patterns.

Converts a pattern file (sequence of stitch instructions) into a graph
representation with adjacency matrix and edge metadata.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set
import numpy as np
from pathlib import Path
import re

from .stitches import StitchTech, load_stitches, H_LENGTH_MM, V_LENGTH_MM


@dataclass
class GraphEdge:
    """
    Represents an edge in the knit graph.

    Attributes:
        i: Source vertex index
        j: Target vertex index
        length_mm: Target edge length in millimeters
        orient: Edge orientation ('h' for horizontal, 'v' for vertical)
    """
    i: int
    j: int
    length_mm: float
    orient: str  # 'h' or 'v'


@dataclass
class KnitGraph:
    """
    Graph representation of a knit structure.

    Attributes:
        n_stitches: Total number of stitches (vertices)
        edges: List of GraphEdge objects
        adjacency: Adjacency matrix (n_stitches x n_stitches)
        topology: 'flat', 'circular', or 'mobius'
        row_indices: List of lists, where row_indices[r] contains stitch indices in row r
        stitch_characters: Character for each stitch ('k' or 'p')
    """
    n_stitches: int
    edges: List[GraphEdge]
    adjacency: np.ndarray
    topology: str
    row_indices: List[List[int]] = field(default_factory=list)
    stitch_characters: List[str] = field(default_factory=list)

    def get_neighbors(self, v: int) -> List[int]:
        """Get all vertices connected to vertex v."""
        neighbors = []
        for e in self.edges:
            if e.i == v:
                neighbors.append(e.j)
            elif e.j == v:
                neighbors.append(e.i)
        return neighbors

    def get_edge(self, i: int, j: int) -> Optional[GraphEdge]:
        """Get edge between vertices i and j, or None if not connected."""
        for e in self.edges:
            if (e.i == i and e.j == j) or (e.i == j and e.j == i):
                return e
        return None

    def get_edges_by_orientation(self, orient: str) -> List[GraphEdge]:
        """Get all edges with given orientation ('h' or 'v')."""
        return [e for e in self.edges if e.orient == orient]


def parse_pattern_file(path: str) -> List[List[str]]:
    """
    Parse a pattern file into list of rows, each row a list of stitch names.

    Args:
        path: Path to pattern file.

    Returns:
        List of rows, where each row is a list of stitch abbreviations.
    """
    path = Path(path)
    with open(path, 'r') as f:
        contents = f.readlines()

    rows = []
    for line in contents:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Split on whitespace
        stitches = line.split()
        # Filter empty strings
        stitches = [s.strip() for s in stitches if s.strip()]
        if stitches:
            rows.append(stitches)

    return rows


def pattern_to_graph(
    pattern_path: str,
    stitch_defs: Optional[Dict[str, StitchTech]] = None
) -> KnitGraph:
    """
    Convert a pattern file to a KnitGraph.

    This implements the needle simulation from knit.py, tracking stitches
    on left and right needles as we progress through the pattern.

    Args:
        pattern_path: Path to pattern file (.txt)
        stitch_defs: Optional stitch definitions. If None, loads from default.

    Returns:
        KnitGraph representing the pattern.
    """
    if stitch_defs is None:
        stitch_defs = load_stitches()

    rows = parse_pattern_file(pattern_path)

    # Needle state
    left_needle: List[int] = []   # Stitches waiting to be worked
    right_needle: List[int] = []  # Stitches already worked this row

    # Graph data
    edges: List[GraphEdge] = []
    stitch_characters: List[str] = []
    row_indices: List[List[int]] = []
    count = 0  # Total stitch count

    # Topology tracking
    topology = 'flat'
    first_stitch_of_row = 0
    at_row_edge = True

    current_row_stitches: List[int] = []

    for row_idx, row in enumerate(rows):
        for stitch_name in row:
            stitch_name = stitch_name.strip()

            if stitch_name in stitch_defs:
                st = stitch_defs[stitch_name]

                # Handle direction change (turn)
                if st.cursor_dir:
                    # Swap needles
                    left_needle, right_needle = right_needle.copy(), left_needle.copy()
                    at_row_edge = True
                    # Save this row's stitches
                    if current_row_stitches:
                        row_indices.append(current_row_stitches)
                    current_row_stitches = []
                    first_stitch_of_row = count
                    continue

                # Handle topology markers
                if st.topology == 'circular':
                    topology = 'circular'
                    # Connect last cast-on to first
                    if count > 0:
                        edges.append(GraphEdge(
                            i=count - 1,
                            j=0,
                            length_mm=H_LENGTH_MM,
                            orient='h'
                        ))
                    # Put all stitches on left needle for working in round
                    left_needle = list(range(count))
                    at_row_edge = True
                    first_stitch_of_row = 0
                    continue

                elif st.topology == 'mobius':
                    topology = 'mobius'
                    # Connect with half-twist (last to first)
                    if count > 0:
                        edges.append(GraphEdge(
                            i=count - 1,
                            j=0,
                            length_mm=H_LENGTH_MM,
                            orient='h'
                        ))
                    left_needle = list(range(count))
                    at_row_edge = True
                    first_stitch_of_row = 0
                    continue

                # Add new stitches
                added_stitches: List[int] = []
                for a in range(st.add):
                    stitch_idx = count
                    added_stitches.append(stitch_idx)
                    stitch_characters.append(st.character)
                    current_row_stitches.append(stitch_idx)

                    # Horizontal edge to previous stitch in row
                    if not at_row_edge and count > 0:
                        edges.append(GraphEdge(
                            i=stitch_idx,
                            j=stitch_idx - 1,
                            length_mm=H_LENGTH_MM,
                            orient='h'
                        ))
                    at_row_edge = False

                    # Add to right needle
                    right_needle.append(stitch_idx)
                    count += 1

                # Handle extra stitches (yarn-overs, etc.)
                for _ in range(st.extra):
                    stitch_idx = count
                    added_stitches.append(stitch_idx)
                    stitch_characters.append(st.character)
                    current_row_stitches.append(stitch_idx)

                    # Horizontal edge to previous
                    if not at_row_edge and count > 0:
                        # Get length from edge_list if specified
                        h_len = H_LENGTH_MM
                        for edge_spec in st.edge_list:
                            if edge_spec.orient == 'h':
                                h_len = edge_spec.length_mm
                                break
                        edges.append(GraphEdge(
                            i=stitch_idx,
                            j=stitch_idx - 1,
                            length_mm=h_len,
                            orient='h'
                        ))
                    at_row_edge = False

                    right_needle.append(stitch_idx)
                    count += 1

                # Consume stitches from left needle (vertical edges)
                # Use kill count from old format, or infer from cursor_inc
                kill_count = st.cursor_inc if not st.keep else 0

                # Find vertical edge lengths from edge_list
                v_lengths = [e.length_mm for e in st.edge_list if e.orient == 'v']

                for k in range(kill_count):
                    if left_needle:
                        used_stitch = left_needle.pop()
                        # Connect all added stitches to this consumed stitch
                        for idx, added in enumerate(added_stitches):
                            v_len = v_lengths[idx] if idx < len(v_lengths) else V_LENGTH_MM
                            # Avoid duplicate edges
                            if not any(e.i == used_stitch and e.j == added for e in edges):
                                if not any(e.i == added and e.j == used_stitch for e in edges):
                                    edges.append(GraphEdge(
                                        i=used_stitch,
                                        j=added,
                                        length_mm=v_len,
                                        orient='v'
                                    ))

            else:
                # Handle cable stitches (e.g., c4f, c6b)
                if stitch_name.startswith('c') and len(stitch_name) >= 2:
                    match = re.match(r'c(\d+)([fb]?)', stitch_name)
                    if match:
                        cable_count = int(match.group(1))
                        _process_cable(
                            cable_count,
                            left_needle, right_needle,
                            edges, stitch_characters, current_row_stitches,
                            count
                        )
                        count += cable_count
                        at_row_edge = False
                        continue

                print(f"Warning: Unknown stitch '{stitch_name}'")

    # Add final row if not empty
    if current_row_stitches:
        row_indices.append(current_row_stitches)

    # Build adjacency matrix
    adjacency = np.zeros((count, count), dtype=np.int32)
    for e in edges:
        adjacency[e.i, e.j] = 1
        adjacency[e.j, e.i] = 1

    return KnitGraph(
        n_stitches=count,
        edges=edges,
        adjacency=adjacency,
        topology=topology,
        row_indices=row_indices,
        stitch_characters=stitch_characters
    )


def _process_cable(
    cable_count: int,
    left_needle: List[int],
    right_needle: List[int],
    edges: List[GraphEdge],
    stitch_characters: List[str],
    current_row_stitches: List[int],
    start_count: int
) -> None:
    """
    Process a cable stitch (e.g., c4f, c6b).

    Cables cross half the stitches over the other half.
    """
    half = cable_count // 2

    # Hold first half of stitches
    held_stitches = []
    for _ in range(half):
        if left_needle:
            held_stitches.append(left_needle.pop())

    count = start_count

    # Work second half first
    for _ in range(half):
        if left_needle:
            used_stitch = left_needle.pop()
            stitch_characters.append('k')
            current_row_stitches.append(count)

            # Vertical edge
            edges.append(GraphEdge(
                i=used_stitch,
                j=count,
                length_mm=V_LENGTH_MM,
                orient='v'
            ))

            # Horizontal edge to previous
            if count > start_count:
                edges.append(GraphEdge(
                    i=count,
                    j=count - 1,
                    length_mm=H_LENGTH_MM,
                    orient='h'
                ))

            right_needle.append(count)
            count += 1

    # Then work held stitches
    for used_stitch in held_stitches:
        stitch_characters.append('k')
        current_row_stitches.append(count)

        # Vertical edge
        edges.append(GraphEdge(
            i=used_stitch,
            j=count,
            length_mm=V_LENGTH_MM,
            orient='v'
        ))

        # Horizontal edge to previous
        edges.append(GraphEdge(
            i=count,
            j=count - 1,
            length_mm=H_LENGTH_MM,
            orient='h'
        ))

        right_needle.append(count)
        count += 1
