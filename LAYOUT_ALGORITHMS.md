# WoolyGraphs Layout Algorithms

This document describes the layout algorithm system for converting knitting patterns into positioned graph representations.

## Overview

The WoolyGraphs system converts knitting patterns (sequences of stitch instructions) into:
1. **Adjacency matrices** representing stitch connectivity
2. **Initial vertex positions** computed during pattern traversal (O(n) per stitch)
3. **Optimized positions** refined through force-directed or formal optimization

### Pipeline Architecture

```
┌─────────────────┐     ┌─────────────────────┐     ┌────────────────────┐
│  Pattern File   │ ──▶ │  pattern2baseline   │ ──▶ │ baseline2optimized │
│  (stitch seq)   │     │  - adjacency matrix │     │  - force-directed  │
│                 │     │  - initial positions│     │  - constraint opt  │
│  Style JSON     │     │  - layout config    │     │  - shared optimizer│
└─────────────────┘     └─────────────────────┘     └────────────────────┘
                                                              │
                                                              ▼
                                                    ┌────────────────────┐
                                                    │   Visualization    │
                                                    │  - matplotlib 3D   │
                                                    │  - D3.js export    │
                                                    └────────────────────┘
```

## Edge Length Standards

All edge lengths are specified in millimeters for real-world correspondence:

| Edge Type | Standard Length | Notes |
|-----------|-----------------|-------|
| Horizontal (h) | 4.0 mm | Between adjacent stitches in same row |
| Vertical (v) | 3.0 mm | Between stitches in consecutive rows |
| Yarn-over (yo) | 4.8 mm | Creates eyelet, ~1.2x horizontal |
| Decrease (k2tog, ssk) | 4.2 mm vertical | ~1.4x for diagonal convergence |
| Triple decrease (k3tog) | 5.1 mm vertical | ~1.7x for steeper convergence |

For stitches with multiple edges connecting to a single vertex (e.g., k2tog, k3tog), horizontal and vertical edges maintain standard lengths, allowing the triangulation to naturally squeeze the fabric.

## Layout Configuration (Style JSON)

Each pattern can have an accompanying JSON style file that configures layout behavior:

```json
{
  "layout_mode": "flat",
  "edge_lengths": {
    "h_length_mm": 4.0,
    "v_length_mm": 3.0
  },
  "topology": {
    "circular": false,
    "mobius": false,
    "join_stitch": null
  },
  "shaping": {
    "allow_3d": true,
    "short_row_profile": "semicircle"
  },
  "cables": {
    "squeeze_factor": 0.8
  },
  "mannequin": {
    "enabled": false,
    "mesh_file": null,
    "anchors": []
  },
  "optimizer": {
    "method": "pytorch",
    "epochs": 1000,
    "learning_rate": 0.01,
    "forces": {
      "edge_spring": 1.0,
      "repulsion": 0.2,
      "solid_angle": 0.1
    }
  }
}
```

## Layout Mode Behaviors

The optimizer handles all layout modes through configuration, with mode-specific behaviors as submodules:

### 1. Flat Knitting (Default)

**Config:** `"layout_mode": "flat", "topology": {"circular": false}`

**Behavior:**
- Cast-on stitches placed linearly along x-axis with spacing = horizontal edge length
- Each subsequent row placed at y-offset = vertical edge length
- Odd rows progress left-to-right, even rows right-to-left
- New stitch position: minimize deviation from specified edge lengths to neighbor stitches

**Initial Position:**
```python
x = stitch_index_in_row * h_length * direction
y = row_number * v_length
z = 0  # flat in xy-plane
```

**O(n) Adjustment:** When short rows or shaping occurs, shift all dependent stitches (column below + all stitches opposite knitting direction) to minimize edge length deviation.

### 2. In-the-Round Knitting

**Config:** `"layout_mode": "circular", "topology": {"circular": true}`

**Behavior:**
- Cast-on stitches distributed evenly around a circle in the xy-plane
- Radius determined by: `r = (n_stitches * h_length) / (2π)`
- Each round placed at incrementing z-height
- Join stitch connects last cast-on to first

**Initial Position:**
```python
theta = (stitch_index / n_stitches) * 2 * pi
x = radius * cos(theta)
y = radius * sin(theta)
z = round_number * v_length
```

**O(n) Adjustment:** When joining or during cast-on, redistribute all horizontally-matching stitches at current level into even circular distribution, then propagate to column dependents.

**Pattern Syntax:**
```
co co co co co co join  # 'join' connects last to first
k k k k k k             # continues in round (no 'turn')
```

### 3. Non-Flat Shaping (Short Rows)

**Config:** `"shaping": {"allow_3d": true, "short_row_profile": "semicircle"}`

**Behavior:**
- When a `turn` occurs before row completion, wrapped stitches create 3D curvature
- Solve for z-perturbation analytically using configured profile (semicircle, catenary)
- Minimize sum of squared edge length deviations

**Closed-Form Solution (semicircle):**
```python
z(i) = sqrt(r² - (x(i) - x_center)²) - r
where r = s * h_length / (2 * sin(theta/2))
```

**O(n) Adjustment:** Each new stitch can shift all stitches in its dependency column and opposite the knitting direction, plus apply vertical perturbation.

### 4. Cabling

**Config:** `"cables": {"squeeze_factor": 0.8}`

**Behavior:**
- Cable stitches physically cross over/under each other
- Creates mandatory edge length deviations (stretched edges)
- Squeeze stitches inward between cable crosses

**Cable Geometry:**
```
      ╱╲
     ╱  ╲     Cable cross creates
    ╱    ╲    diagonal edges longer
   ●      ●   than standard h_length
   │      │
```

**O(n) Adjustment:** From cable stitch to next column-wise dependent cable, squeeze intermediate stitches by `squeeze_factor`.

**Pattern Syntax:**
```
k k c4f k k    # c4f = cable 4 front
```

### 5. Mannequin-Constrained Layout

**Config:** `"mannequin": {"enabled": true, "mesh_file": "body.obj", "anchors": [...]}`

**Behavior:**
- Fixed 3D mannequin mesh defines target surface
- Anchor stitches pinned to mannequin vertices
- All other stitches conform to surface while minimizing edge deviation
- Uses closest-point projection to mannequin surface

**Constraint System:**
```python
for stitch s:
    if s.anchor_id is not None:
        position[s] = mannequin.anchor_points[s.anchor_id]
    else:
        position[s] = mannequin.project(computed_position[s])
```

## Initial Layout Algorithm (pattern2baseline)

### Per-Stitch Placement

When adding stitch `s` with index `i`:

1. **Identify neighbor stitches** from edge_list specification
2. **Compute candidate position** that minimizes:
   ```
   Σ (||pos[i] - pos[neighbor]|| - target_length)²
   ```
3. **For 2D cases:** Solve analytically using circle intersection
4. **For 3D cases:** If 2D solution is infeasible, solve for z-perturbation

### Dependency Propagation

After placing stitch `s`, propagate adjustments:
1. Column dependents: all stitches directly below in the knitting structure
2. Row dependents: all stitches opposite the current knitting direction
3. Apply adjustment that minimizes total edge length deviation

## Optimization Phase (baseline2optimized)

The optimizer is shared across all layout modes, with mode-specific behaviors loaded as submodules based on configuration.

### Force Components (Submodules)

All force components plug into the shared optimizer:

| Submodule | Force | Description |
|-----------|-------|-------------|
| `edge_spring` | `F = k * (d - L) * n̂` | Pull edges toward target length |
| `repulsion` | `F = k / d²` | Universal repulsion prevents overlap |
| `solid_angle` | `F = k * (Ω - 2π)` | Flatten toward 2-manifold |
| `surface` | `F = project(p)` | Mannequin surface constraint |
| `cable_squeeze` | `F = squeeze(cable_region)` | Cable inward compression |

### Objective Function

```python
E = Σ_edges (||pos[i] - pos[j]|| - L_ij)²      # Edge length preservation
  + λ_repel * Σ_pairs 1/||pos[i] - pos[j]||    # Universal repulsion
  + λ_flat * Σ_vertices (solid_angle - 2π)²    # Manifold conformance
  + mode_specific_terms                         # From config
```

### Implementation Options

**PyTorch (preferred for differentiability):**
```python
positions = torch.tensor(initial_positions, requires_grad=True)
optimizer = torch.optim.Adam([positions], lr=config['learning_rate'])

for epoch in range(config['epochs']):
    loss = compute_loss(positions, edges, config)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
```

**Pyomo (for constrained optimization):**
```python
model = ConcreteModel()
model.x = Var(range(n), range(3), domain=Reals)
model.obj = Objective(expr=total_energy, sense=minimize)
# Add constraints from config (mannequin surface, etc.)
```

### Solid Angle Manifold Conformance

To encourage flat 2-manifold structure:
- Target: 2π steradians (flat surface)
- Penalty: `(solid_angle - 2π)²`

```python
def solid_angle(v, neighbors):
    omega = 0
    for triangle in faces_around(v):
        omega += spherical_excess(triangle)
    return omega
```

## Test Patterns

### Flat Stockinette (existing)
```
# patterns/small_stockinette.txt
co co co co turn
k k k k turn
k k k k turn
k k k k turn
bo bo bo bo turn
```

### In-the-Round Tube
```
# patterns/tube_round.txt
co co co co co co co co join
k k k k k k k k
k k k k k k k k
k k k k k k k k
bo bo bo bo bo bo bo bo
```

### Mobius Strip
```
# patterns/mobius.txt
co co co co co co co co mobius
k k k k k k k k
k k k k k k k k
```

## Module Structure

```
woolygraphs/
├── __init__.py
├── stitches.json            # Stitch definitions with edge lengths
├── pattern.py               # Pattern parsing and validation
├── graph.py                 # Graph/adjacency matrix construction
├── baseline.py              # Initial layout (pattern2baseline)
├── optimizer/
│   ├── __init__.py          # Shared optimizer framework
│   ├── forces/
│   │   ├── __init__.py
│   │   ├── edge_spring.py   # Edge length preservation
│   │   ├── repulsion.py     # Universal repulsion
│   │   ├── solid_angle.py   # Manifold conformance
│   │   ├── surface.py       # Mannequin surface constraint
│   │   └── cable.py         # Cable squeeze forces
│   ├── backends/
│   │   ├── pytorch.py       # PyTorch optimizer backend
│   │   └── pyomo.py         # Pyomo constrained backend
│   └── config.py            # Style JSON loading/validation
├── export/
│   ├── dot.py               # GraphViz DOT export
│   ├── csv.py               # Adjacency matrix CSV
│   └── d3.py                # D3.js visualization export
└── visualization/
    └── plot3d.py            # Matplotlib 3D visualization
```

## Literature References

### Force-Directed Graph Layout
- Fruchterman-Reingold algorithm (1991)
- Kamada-Kawai spring embedding (1989)

### Finite Element Approaches
- Stress majorization for graph drawing
- Spectral methods for initial layout

### Manifold Optimization
- Riemannian optimization for surface constraints
- Projected gradient descent

### Knitting-Specific
- Discrete differential geometry for knit structures
- Yarn-level simulation methods

## Next Steps

1. Standardize all stitch definitions with mm-based edge lengths
2. Implement `pattern2baseline` with O(n) per-stitch adjustment
3. Create test patterns for each layout type
4. Implement shared optimizer with force submodules
5. Add solid angle computation for manifold conformance
6. Benchmark against FEM-based approaches
