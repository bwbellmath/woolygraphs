"""Tests for layout/stitch_instance.py -- data structures."""

import json
import tempfile
import numpy as np
import pytest

from layout.stitch_instance import StitchInstance, BackEdge, Gauge, LayoutGraph


class TestBackEdge:
    def test_creation(self):
        e = BackEdge(target_index=5, orientation="v", rest_length=3.0, bump=True)
        assert e.target_index == 5
        assert e.orientation == "v"
        assert e.rest_length == 3.0
        assert e.bump is True

    def test_horizontal_edge(self):
        e = BackEdge(target_index=2, orientation="h", rest_length=4.0, bump=False)
        assert e.orientation == "h"
        assert e.bump is False


class TestGauge:
    def test_defaults(self):
        g = Gauge()
        assert g.stitch_width == 4.0
        assert g.stitch_height == 3.0
        assert g.yarn_diameter == 0.5

    def test_custom(self):
        g = Gauge(stitch_width=5.0, stitch_height=4.0, yarn_diameter=1.0)
        assert g.stitch_width == 5.0
        assert g.stitch_height == 4.0


class TestStitchInstance:
    def test_creation(self):
        s = StitchInstance(index=0, stitch_type="k", character="k")
        assert s.index == 0
        assert s.stitch_type == "k"
        assert s.character == "k"
        np.testing.assert_array_equal(s.position, [0.0, 0.0, 0.0])
        np.testing.assert_array_equal(s.normal, [0.0, 0.0, 1.0])
        assert len(s.back_edges) == 0

    def test_with_edges(self):
        s = StitchInstance(index=5, stitch_type="k", character="k")
        s.back_edges.append(BackEdge(4, "h", 4.0, False))
        s.back_edges.append(BackEdge(1, "v", 3.0, True))
        assert len(s.back_edges) == 2
        assert s.back_edges[0].orientation == "h"
        assert s.back_edges[1].orientation == "v"

    def test_offsets(self):
        s = StitchInstance(
            index=0, stitch_type="k", character="k",
            offset_normal=0.3, offset_up_down=0.1
        )
        assert s.offset_normal == 0.3
        assert s.offset_up_down == 0.1


class TestLayoutGraph:
    def _make_small_graph(self):
        """Create a 2x2 grid graph for testing."""
        s0 = StitchInstance(index=0, stitch_type="co", character="k",
                            position=np.array([0.0, 0.0, 0.0]), row=0, col=0)
        s1 = StitchInstance(index=1, stitch_type="co", character="k",
                            position=np.array([4.0, 0.0, 0.0]), row=0, col=1)
        s1.back_edges.append(BackEdge(0, "h", 4.0, False))

        s2 = StitchInstance(index=2, stitch_type="k", character="k",
                            position=np.array([4.0, 3.0, 0.0]), row=1, col=0)
        s2.back_edges.append(BackEdge(1, "v", 3.0, True))

        s3 = StitchInstance(index=3, stitch_type="k", character="k",
                            position=np.array([0.0, 3.0, 0.0]), row=1, col=1)
        s3.back_edges.append(BackEdge(2, "h", 4.0, False))
        s3.back_edges.append(BackEdge(0, "v", 3.0, True))

        return LayoutGraph([s0, s1, s2, s3])

    def test_num_stitches(self):
        g = self._make_small_graph()
        assert g.num_stitches == 4

    def test_edge_list(self):
        g = self._make_small_graph()
        edges = g.edge_list()
        assert len(edges) == 4
        # Check format: (src, tgt, orient, rest_length)
        assert edges[0] == (1, 0, "h", 4.0)

    def test_adjacency_matrix(self):
        g = self._make_small_graph()
        A = g.adjacency_matrix()
        assert A.shape == (4, 4)
        # Should be symmetric
        np.testing.assert_array_equal(A, A.T)
        # s1 <-> s0 (h), s2 <-> s1 (v), s3 <-> s2 (h), s3 <-> s0 (v)
        assert A[0, 1] == 1.0
        assert A[1, 0] == 1.0
        assert A[1, 2] == 1.0

    def test_positions_array(self):
        g = self._make_small_graph()
        pos = g.positions_array()
        assert pos.shape == (4, 3)
        np.testing.assert_array_almost_equal(pos[0], [0, 0, 0])
        np.testing.assert_array_almost_equal(pos[1], [4, 0, 0])

    def test_normals_array(self):
        g = self._make_small_graph()
        norms = g.normals_array()
        assert norms.shape == (4, 3)

    def test_edge_indices(self):
        g = self._make_small_graph()
        ei = g.edge_indices()
        assert ei.shape == (4, 2)

    def test_edge_rest_lengths(self):
        g = self._make_small_graph()
        rl = g.edge_rest_lengths()
        assert len(rl) == 4

    def test_neighbor_indices(self):
        g = self._make_small_graph()
        nbrs = g.neighbor_indices()
        assert len(nbrs) == 4
        # s0 should have neighbors s1 and s3
        assert set(nbrs[0]) == {1, 3}

    def test_to_json_and_from_json_roundtrip(self):
        g = self._make_small_graph()

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            path = f.name

        g.to_json(path)

        # Read back
        g2 = LayoutGraph.from_json(path)
        assert g2.num_stitches == 4
        assert len(g2.edge_list()) == 4
        np.testing.assert_array_almost_equal(
            g2.positions_array(), g.positions_array()
        )

    def test_to_json_format(self):
        g = self._make_small_graph()
        data = g.to_json()
        assert "metadata" in data
        assert "nodes" in data
        assert "edges" in data
        assert "yarn_path" in data
        assert data["metadata"]["nodeCount"] == 4
        assert data["metadata"]["edgeCount"] == 4
        assert len(data["nodes"]) == 4
        assert "position" in data["nodes"][0]
        assert "normal" in data["nodes"][0]
