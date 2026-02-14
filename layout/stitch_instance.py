"""
WoolyGraphs Data Structures for Layout

Core data structures:
- BackEdge: directed edge from a stitch to a neighbor behind/below
- StitchInstance: a single instantiated stitch with position, normal, connectivity
- Gauge: physical dimensions (stitch width/height, yarn diameter)
- LayoutGraph: collection of StitchInstances with convenience accessors
"""

from dataclasses import dataclass, field
import numpy as np
import json


@dataclass
class BackEdge:
    """One directed edge from a stitch back to a neighbor (behind or below)."""

    target_index: int       # index of connected stitch
    orientation: str        # "h" (horizontal / behind) or "v" (vertical / below)
    rest_length: float      # specified rest length in mm
    bump: bool              # True = stitch was bumped off needle ("b")


@dataclass
class Gauge:
    """Physical dimensions from yarn weight + needle size."""

    stitch_width: float = 4.0      # mm (horizontal rest length)
    stitch_height: float = 3.0     # mm (vertical rest length)
    yarn_diameter: float = 0.5     # mm (for tubular rendering)


@dataclass
class StitchInstance:
    """A single instantiated stitch in the layout."""

    index: int                              # unique stitch id
    stitch_type: str                        # key into stitch descriptions ("k","p",...)
    character: str                          # "k" or "p"

    # Geometry -- the optimizable degrees of freedom
    position: np.ndarray = field(default_factory=lambda: np.zeros(3))   # (3,) float64
    normal: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))  # (3,) unit normal

    # Derived (recomputed from neighbors)
    right_left: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    up_down: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 0.0]))

    # Connectivity (populated during compilation)
    back_edges: list = field(default_factory=list)  # list[BackEdge]

    # Stitch-type-inherited offsets (in mm, after multiplying by stitch_height)
    offset_normal: float = 0.0
    offset_right_left: float = 0.0
    offset_up_down: float = 0.0

    # Row tracking for mesh construction
    row: int = 0
    col: int = 0


class LayoutGraph:
    """Collection of StitchInstances with convenience accessors."""

    def __init__(self, stitches: list = None):
        self.stitches: list[StitchInstance] = stitches or []

    @property
    def num_stitches(self) -> int:
        return len(self.stitches)

    def edge_list(self) -> list:
        """
        Flat list of (src, tgt, orientation, rest_length) tuples
        extracted from all back_edges.
        """
        edges = []
        for s in self.stitches:
            for e in s.back_edges:
                edges.append((s.index, e.target_index, e.orientation, e.rest_length))
        return edges

    def adjacency_matrix(self) -> np.ndarray:
        """Build symmetric adjacency matrix (N x N)."""
        N = self.num_stitches
        A = np.zeros((N, N), dtype=float)
        for s in self.stitches:
            for e in s.back_edges:
                A[s.index, e.target_index] = 1.0
                A[e.target_index, s.index] = 1.0
        return A

    def positions_array(self) -> np.ndarray:
        """(N, 3) array of stitch positions."""
        return np.array([s.position for s in self.stitches], dtype=np.float64)

    def normals_array(self) -> np.ndarray:
        """(N, 3) array of stitch normal vectors."""
        return np.array([s.normal for s in self.stitches], dtype=np.float64)

    def offsets_array(self) -> np.ndarray:
        """(N, 3) array of [offset_normal, offset_right_left, offset_up_down]."""
        return np.array([
            [s.offset_normal, s.offset_right_left, s.offset_up_down]
            for s in self.stitches
        ], dtype=np.float64)

    def edge_indices(self) -> np.ndarray:
        """(E, 2) array of edge (src, tgt) pairs."""
        edges = self.edge_list()
        if not edges:
            return np.zeros((0, 2), dtype=int)
        return np.array([(e[0], e[1]) for e in edges], dtype=int)

    def edge_orientations(self) -> list:
        """List of 'h'/'v' for each edge."""
        return [e[2] for e in self.edge_list()]

    def edge_rest_lengths(self) -> np.ndarray:
        """(E,) array of rest lengths."""
        edges = self.edge_list()
        if not edges:
            return np.zeros(0)
        return np.array([e[3] for e in edges], dtype=np.float64)

    def neighbor_indices(self) -> list:
        """For each stitch, list of neighbor stitch indices."""
        N = self.num_stitches
        neighbors = [[] for _ in range(N)]
        for s in self.stitches:
            for e in s.back_edges:
                neighbors[s.index].append(e.target_index)
                neighbors[e.target_index].append(s.index)
        # deduplicate
        return [list(set(nbrs)) for nbrs in neighbors]

    def yarn_path(self) -> list:
        """Directed stitch order for yarn rendering (creation order)."""
        return [s.index for s in self.stitches]

    def to_json(self, path: str = None) -> dict:
        """
        Export to JSON format for the viewer.

        Returns the dict, and optionally writes to file.
        """
        edges = self.edge_list()

        data = {
            "metadata": {
                "nodeCount": self.num_stitches,
                "edgeCount": len(edges),
                "hasOptimizedPositions": True,
                "hasNormals": True,
                "gauge": {
                    "stitch_width": 4.0,
                    "stitch_height": 3.0,
                    "yarn_diameter": 0.5,
                },
            },
            "nodes": [
                {
                    "id": s.index,
                    "label": f"stitch_{s.index}",
                    "stitch_type": s.stitch_type,
                    "character": s.character,
                    "row": s.row,
                    "col": s.col,
                    "position": {
                        "x": float(s.position[0]),
                        "y": float(s.position[1]),
                        "z": float(s.position[2]),
                    },
                    "normal": {
                        "x": float(s.normal[0]),
                        "y": float(s.normal[1]),
                        "z": float(s.normal[2]),
                    },
                }
                for s in self.stitches
            ],
            "edges": [
                {
                    "source": int(e[0]),
                    "target": int(e[1]),
                    "orientation": e[2],
                    "rest_length": float(e[3]),
                    "weight": 1.0,
                }
                for e in edges
            ],
            "yarn_path": self.yarn_path(),
        }

        if path is not None:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

        return data

    @classmethod
    def from_json(cls, path: str) -> "LayoutGraph":
        """Load a LayoutGraph from JSON file."""
        with open(path, "r") as f:
            data = json.load(f)

        stitches = []
        for node in data["nodes"]:
            pos = node.get("position", {"x": 0, "y": 0, "z": 0})
            nrm = node.get("normal", {"x": 0, "y": 0, "z": 1})

            s = StitchInstance(
                index=node["id"],
                stitch_type=node.get("stitch_type", "k"),
                character=node.get("character", "k"),
                position=np.array([pos["x"], pos["y"], pos["z"]], dtype=np.float64),
                normal=np.array([nrm["x"], nrm["y"], nrm["z"]], dtype=np.float64),
                row=node.get("row", 0),
                col=node.get("col", 0),
            )
            stitches.append(s)

        # Reconstruct back_edges from edge list
        for edge in data.get("edges", []):
            src = edge["source"]
            tgt = edge["target"]
            orient = edge.get("orientation", "h")
            rest_len = edge.get("rest_length", 4.0)

            stitches[src].back_edges.append(BackEdge(
                target_index=tgt,
                orientation=orient,
                rest_length=rest_len,
                bump=(orient == "v"),
            ))

        graph = cls(stitches)
        return graph
