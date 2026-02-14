# WoolyGraphs Buildout Tracker

Active issues and features for the layout engine.

---

## Issues

### 1. Initial normals relationship to stitch plane [BUG]
**Status:** Open
**Priority:** High

The normal vectors should be orthogonal to the plane in which stitches are
laid out. If normals are (0,0,1), then stitches should vary in x and y
(the plane orthogonal to the normal). The up-down displacement between rows
should be orthogonal to both the normal and the right-left direction.

**Current behavior:** Initial layout places stitches in XY plane with
normals along Z -- this part is correct. However, the derived frame
(right_left, up_down) and the optimizer's offset/coherence losses don't
properly enforce that the up-down direction remains orthogonal to the
normal-right_left plane. During optimization, normals drift and the fabric
warps instead of staying flat for stockinette.

**Expected behavior:** For stockinette, the initial layout should be a
regular grid. The optimizer should maintain (or improve toward) that grid.
Normals should remain coherent and perpendicular to the fabric surface.

**Root causes to investigate:**
- Repulsion force may be too strong relative to coherence/flatness
- Flatness energy interior_mask may exclude too many vertices for small grids
- Offset loss may create spurious forces
- Lambda weight balance needs tuning for the stockinette case

### 2. Stockinette should optimize to regular rectangular grid [TEST]
**Status:** Open
**Priority:** High

For the default `small_stockinette.txt` pattern (4 cast-on + 3 rows of 4k),
the optimized layout should converge to a perfectly regular rectangular grid
with:
- All horizontal edge lengths ≈ stitch_width (4mm)
- All vertical edge lengths ≈ stitch_height (3mm)
- All z-coordinates ≈ 0 (flat)
- All normals ≈ (0,0,1) (aligned)

This is the simplest possible case and should be a unit test that
validates the optimizer is working correctly end-to-end.

---

## Features (Planned)

### Viewer improvements
- Color picker for stitch editing
- Stitch type editing (click to change k/p)
- Yarn path tubular rendering refinements

### Pattern support
- Circular knitting (knitting in the round)
- Cable stitches (c4f, c4b, etc.)
- Short rows

### Optimizer
- L-BFGS benchmarking vs Adam
- Per-object lambda presets
- Mannequin draping mode

---

## Completed

- [x] Phase 1: pattern compilation (initial_layout.py)
- [x] Phase 2: optimizer with 6 loss terms + blocked-flat extras
- [x] Phase 3: Three.js browser viewer with drag-drop JSON loading
- [x] 70 unit tests passing
- [x] CLI pipeline (run_layout.py)
- [x] Stitch definitions with offset fields (stitches_2.txt)
