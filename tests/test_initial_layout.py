"""Tests for layout/initial_layout.py -- pattern compilation."""

import numpy as np
import pytest

from layout.stitch_instance import Gauge, LayoutGraph
from layout.initial_layout import (
    compile_pattern,
    load_stitch_definitions,
    parse_pattern,
)


@pytest.fixture
def stitch_defs():
    return load_stitch_definitions()


@pytest.fixture
def gauge():
    return Gauge()


class TestLoadStitchDefinitions:
    def test_loads_all_types(self, stitch_defs):
        assert "k" in stitch_defs
        assert "p" in stitch_defs
        assert "co" in stitch_defs
        assert "bo" in stitch_defs
        assert "turn" in stitch_defs
        assert "kfb" in stitch_defs
        assert "k2tog" in stitch_defs

    def test_offsets_present(self, stitch_defs):
        assert "offsets" in stitch_defs["k"]
        assert stitch_defs["k"]["offsets"]["normal"] == 0.1
        assert stitch_defs["p"]["offsets"]["normal"] == -0.1

    def test_stitch_fields(self, stitch_defs):
        k = stitch_defs["k"]
        assert k["character"] == "k"
        assert k["kill"] == 1
        assert k["add"] == 1
        assert k["cursor_dir"] is False


class TestParsePattern:
    def test_small_stockinette(self):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        assert len(tokens) == 25  # 4co + turn + 4k + turn + 4k + turn + 4k + turn + 4bo + turn
        assert tokens[0] == "co"
        assert tokens[4] == "turn"
        assert tokens[5] == "k"


class TestCompilePattern:
    def test_small_stockinette_stitch_count(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        # 4 cast-on + 12 knit (3 rows x 4) = 16 stitches
        # (bo has add=0, so no stitches from bind-off)
        assert graph.num_stitches == 16

    def test_small_stockinette_edge_count(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        edges = graph.edge_list()
        h_edges = [e for e in edges if e[2] == "h"]
        v_edges = [e for e in edges if e[2] == "v"]

        # Horizontal: 3 per row x 4 rows = 12
        assert len(h_edges) == 12

        # Vertical: 4 per row transition x 3 transitions = 12
        # (co->k1, k1->k2, k2->k3) plus bind-off kills consume stitches
        # bo kills 4 stitches but adds 0, so 4 more v-edges from bo
        assert len(v_edges) == 12

    def test_cast_on_positions(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        # Cast-on stitches should be at y=0, spaced by stitch_width
        for i in range(4):
            s = graph.stitches[i]
            assert s.stitch_type == "co"
            assert s.row == 0
            assert s.position[1] == pytest.approx(0.0)
            assert s.position[0] == pytest.approx(i * gauge.stitch_width)

    def test_first_knit_row(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        # Row 1 (after turn): stitches 4-7 should be at y = stitch_height
        for s in graph.stitches[4:8]:
            assert s.stitch_type == "k"
            assert s.row == 1
            assert s.position[1] == pytest.approx(gauge.stitch_height)

    def test_zigzag_x_positions(self, stitch_defs, gauge):
        """Rows should alternate direction due to turns."""
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        # Row 0 (co): x = 0, 4, 8, 12
        # Row 1 (k, reversed): x = 12, 8, 4, 0
        assert graph.stitches[4].position[0] == pytest.approx(12.0)
        assert graph.stitches[7].position[0] == pytest.approx(0.0)

        # Row 2: x = 0, 4, 8, 12
        assert graph.stitches[8].position[0] == pytest.approx(0.0)
        assert graph.stitches[11].position[0] == pytest.approx(12.0)

    def test_normals_are_unit(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        for s in graph.stitches:
            norm = np.linalg.norm(s.normal)
            assert norm == pytest.approx(1.0, abs=1e-6)

    def test_adjacency_symmetric(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        A = graph.adjacency_matrix()
        np.testing.assert_array_equal(A, A.T)

    def test_json_export(self, stitch_defs, gauge):
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        data = graph.to_json()
        assert data["metadata"]["nodeCount"] == 16
        assert data["metadata"]["edgeCount"] == 24

    def test_unknown_stitch_raises(self, stitch_defs, gauge):
        with pytest.raises(ValueError, match="Unknown stitch"):
            compile_pattern(["xyz"], stitch_defs, gauge)

    def test_offsets_propagated(self, stitch_defs, gauge):
        """Stitch-type offsets should be set on instances."""
        tokens = parse_pattern("patterns/small_stockinette.txt")
        graph = compile_pattern(tokens, stitch_defs, gauge)

        # Knit stitches should have offset_normal = 0.1 * stitch_height
        for s in graph.stitches:
            if s.stitch_type == "k":
                assert s.offset_normal == pytest.approx(0.1 * gauge.stitch_height)
            elif s.stitch_type == "co":
                assert s.offset_normal == pytest.approx(0.0)
