# WoolyGraphs Implementation Plan

This document provides a detailed implementation roadmap for the new layout algorithm system.

## Current State (Foundation)

### Existing Components

| File | Purpose | Key Elements |
|------|---------|--------------|
| `knit.py` | Pattern → Graph | `edge`, `stitch`, `stitch_tech` classes; needle simulation; edge list → adjacency matrix |
| `show.py` | Graph → Positions | Force-directed layout with progressive unfreezing; attraction/repulsion forces |
| `stitches.txt` | Stitch definitions | Now standardized with mm-based edge lengths (4mm h, 3mm v) |
| `stitches_2.txt` | Legacy definitions | Simpler format, used by current `knit.py` |

### Current Pipeline (knit.py:252-337)
```python
# Reads pattern file line by line
for line in contents:
    for s in strings:
        stitch_technique = stitch_techniques[s]
        # Manage needles (left_needle, right_needle)
        # Add edges based on stitch type
        edges.append([count, count-1, weight_h])  # horizontal
        edges.append([used_st, a, weight_v])      # vertical

# Export adjacency matrix
adj = np.matrix(np.zeros((count, count)))
for e in edges:
    adj[e[0], e[1]] = 1
```

### Current Force Model (show.py:104-134)
```python
# Universal repulsion
repel_mag = c_repel * (1/np.linalg.norm(right_complete - left_complete, 2, axis=1))

# Graph attraction
attract_mag = c_attract * np.linalg.norm(right - left, 2, axis=1)

# Position update
pos = pos + epsilon * pos_grad
```

## New Architecture

### Module Structure
```
woolygraphs/
├── __init__.py              # Package entry point
├── stitches.json            # Renamed from stitches.txt (proper JSON)
├── pattern.py               # Pattern parsing
├── graph.py                 # Graph construction (from knit.py)
├── baseline.py              # Initial layout computation
├── optimizer/
│   ├── __init__.py          # Optimizer orchestration
│   ├── config.py            # Style JSON loading
│   ├── forces/
│   │   ├── __init__.py
│   │   ├── edge_spring.py
│   │   ├── repulsion.py
│   │   ├── solid_angle.py
│   │   ├── surface.py
│   │   └── cable.py
│   └── backends/
│       ├── pytorch.py
│       └── pyomo.py
├── export/
│   ├── dot.py
│   ├── csv.py
│   └── d3.py
└── cli.py                   # Command-line interface
```

## Implementation Phases

### Phase 1: Refactor Foundation

**Goal:** Extract reusable components from `knit.py` into proper module structure.

#### 1.1 Create `woolygraphs/stitches.py`
Extract from `knit.py:48-104`:
```python
@dataclass
class Edge:
    v: Tuple[int, int]  # vertex indices
    orient: str         # 'h' or 'v'
    bk: str            # 'b' (bump) or 'k' (keep)
    length_mm: float   # target length in mm

@dataclass
class StitchTech:
    character: str
    cursor_inc: int
    keep: bool
    add: int
    extra: int
    edge_list: List[Edge]
    cursor_dir: bool
    topology: Optional[str] = None

def load_stitches(path: str = "stitches.json") -> Dict[str, StitchTech]:
    """Load stitch definitions from JSON."""
    with open(path) as f:
        data = json.load(f)
    # Skip _meta key
    return {k: StitchTech(**v) for k, v in data.items() if not k.startswith('_')}
```

#### 1.2 Create `woolygraphs/graph.py`
Extract from `knit.py:135-165, 252-337`:
```python
@dataclass
class KnitGraph:
    n_stitches: int
    edges: List[Tuple[int, int, float]]  # (i, j, length_mm)
    adjacency: np.ndarray
    edge_orientations: Dict[Tuple[int, int], str]  # 'h' or 'v'
    topology: str  # 'flat', 'circular', 'mobius'

def pattern_to_graph(pattern_path: str, stitch_defs: Dict[str, StitchTech]) -> KnitGraph:
    """Convert pattern file to graph structure."""
    # Needle simulation logic from knit.py
    left_needle, right_needle = [], []
    edges = []
    # ... pattern parsing ...
    return KnitGraph(...)
```

#### 1.3 Create `woolygraphs/baseline.py`
New implementation for initial positions:
```python
def compute_baseline_positions(
    graph: KnitGraph,
    config: LayoutConfig
) -> np.ndarray:
    """
    Compute initial positions using O(n) per-stitch algorithm.

    Returns:
        positions: (n_stitches, 3) array of xyz coordinates
    """
    positions = np.zeros((graph.n_stitches, 3))

    if config.layout_mode == 'flat':
        positions = _flat_layout(graph, config)
    elif config.layout_mode == 'circular':
        positions = _circular_layout(graph, config)

    return positions

def _flat_layout(graph: KnitGraph, config: LayoutConfig) -> np.ndarray:
    """Flat back-and-forth knitting layout."""
    h_len = config.edge_lengths['h_length_mm']
    v_len = config.edge_lengths['v_length_mm']

    # Cast-on row along x-axis
    # Subsequent rows offset by v_len in y
    # Alternating direction per row
    ...

def _circular_layout(graph: KnitGraph, config: LayoutConfig) -> np.ndarray:
    """Circular in-the-round layout."""
    h_len = config.edge_lengths['h_length_mm']
    v_len = config.edge_lengths['v_length_mm']

    # Compute radius from circumference
    n_cast_on = config.topology['join_stitch']
    radius = (n_cast_on * h_len) / (2 * np.pi)

    # Place cast-on stitches around circle
    for i in range(n_cast_on):
        theta = (i / n_cast_on) * 2 * np.pi
        if config.topology['mobius']:
            # Add half-twist: z varies with theta
            twist = (theta / (2 * np.pi)) * np.pi
            ...
        positions[i] = [radius * np.cos(theta), radius * np.sin(theta), 0]
    ...
```

### Phase 2: Optimizer Framework

**Goal:** Create shared optimizer with pluggable force components.

#### 2.1 Create `woolygraphs/optimizer/__init__.py`
```python
class LayoutOptimizer:
    def __init__(self, config: LayoutConfig):
        self.config = config
        self.forces = self._load_forces()
        self.backend = self._load_backend()

    def _load_forces(self) -> List[ForceComponent]:
        """Load force components based on config."""
        forces = []
        fc = self.config.optimizer['forces']

        if fc.get('edge_spring', 0) > 0:
            forces.append(EdgeSpringForce(weight=fc['edge_spring']))
        if fc.get('repulsion', 0) > 0:
            forces.append(RepulsionForce(weight=fc['repulsion']))
        if fc.get('solid_angle', 0) > 0:
            forces.append(SolidAngleForce(weight=fc['solid_angle']))

        # Mode-specific forces
        if self.config.mannequin.get('enabled'):
            forces.append(SurfaceForce(mesh=self.config.mannequin['mesh_file']))

        return forces

    def optimize(
        self,
        graph: KnitGraph,
        initial_positions: np.ndarray
    ) -> np.ndarray:
        """Run optimization to refine positions."""
        return self.backend.optimize(
            graph=graph,
            positions=initial_positions,
            forces=self.forces,
            epochs=self.config.optimizer['epochs'],
            lr=self.config.optimizer['learning_rate']
        )
```

#### 2.2 Create `woolygraphs/optimizer/forces/base.py`
```python
from abc import ABC, abstractmethod

class ForceComponent(ABC):
    def __init__(self, weight: float = 1.0):
        self.weight = weight

    @abstractmethod
    def compute(
        self,
        positions: np.ndarray,
        graph: KnitGraph
    ) -> np.ndarray:
        """
        Compute force contribution.

        Returns:
            forces: (n_stitches, 3) array of force vectors
        """
        pass

    @abstractmethod
    def energy(
        self,
        positions: np.ndarray,
        graph: KnitGraph
    ) -> float:
        """Compute energy contribution for this force."""
        pass
```

#### 2.3 Create `woolygraphs/optimizer/forces/edge_spring.py`
Adapted from `show.py:121-127`:
```python
class EdgeSpringForce(ForceComponent):
    """Spring force pulling edges toward target lengths."""

    def compute(self, positions: np.ndarray, graph: KnitGraph) -> np.ndarray:
        forces = np.zeros_like(positions)

        for i, j, target_len in graph.edges:
            d = positions[j] - positions[i]
            dist = np.linalg.norm(d)
            if dist > 1e-8:
                # Spring force: F = k * (d - L) * d_hat
                magnitude = self.weight * (dist - target_len)
                f = magnitude * (d / dist)
                forces[i] += f
                forces[j] -= f

        return forces

    def energy(self, positions: np.ndarray, graph: KnitGraph) -> float:
        total = 0.0
        for i, j, target_len in graph.edges:
            d = positions[j] - positions[i]
            dist = np.linalg.norm(d)
            total += (dist - target_len) ** 2
        return self.weight * total
```

#### 2.4 Create `woolygraphs/optimizer/forces/solid_angle.py`
New component for manifold conformance:
```python
class SolidAngleForce(ForceComponent):
    """Force pushing vertices toward flat 2-manifold (solid angle → 2π)."""

    def compute(self, positions: np.ndarray, graph: KnitGraph) -> np.ndarray:
        forces = np.zeros_like(positions)

        for v in range(len(positions)):
            neighbors = graph.get_neighbors(v)
            if len(neighbors) < 3:
                continue

            # Compute solid angle at vertex v
            omega = self._solid_angle(positions, v, neighbors)

            # Target is 2π for flat surface
            deviation = omega - 2 * np.pi

            # Push outward to flatten
            normal = self._vertex_normal(positions, v, neighbors)
            forces[v] += self.weight * deviation * normal

        return forces

    def _solid_angle(self, positions, v, neighbors):
        """Compute solid angle subtended by neighbors at vertex v."""
        # Sum spherical excess of triangular faces
        omega = 0.0
        p = positions[v]
        for i in range(len(neighbors)):
            j = (i + 1) % len(neighbors)
            a = positions[neighbors[i]] - p
            b = positions[neighbors[j]] - p
            # Spherical excess formula
            omega += self._triangle_solid_angle(a, b)
        return omega
```

#### 2.5 Create `woolygraphs/optimizer/backends/pytorch.py`
```python
import torch

class PyTorchBackend:
    def optimize(
        self,
        graph: KnitGraph,
        positions: np.ndarray,
        forces: List[ForceComponent],
        epochs: int,
        lr: float
    ) -> np.ndarray:

        pos = torch.tensor(positions, dtype=torch.float32, requires_grad=True)
        optimizer = torch.optim.Adam([pos], lr=lr)

        # Convert graph to torch tensors
        edge_idx = torch.tensor([(e[0], e[1]) for e in graph.edges])
        edge_len = torch.tensor([e[2] for e in graph.edges])

        for epoch in range(epochs):
            optimizer.zero_grad()

            # Compute total loss from all force components
            loss = torch.tensor(0.0)
            for force in forces:
                loss += force.energy_torch(pos, edge_idx, edge_len)

            loss.backward()
            optimizer.step()

            if epoch % 100 == 0:
                print(f"Epoch {epoch}: loss = {loss.item():.4f}")

        return pos.detach().numpy()
```

### Phase 3: Integration & CLI

**Goal:** Create unified command-line interface.

#### 3.1 Create `woolygraphs/cli.py`
```python
import argparse
from woolygraphs import pattern, graph, baseline
from woolygraphs.optimizer import LayoutOptimizer
from woolygraphs.optimizer.config import load_config
from woolygraphs.export import dot, csv

def main():
    parser = argparse.ArgumentParser(description='WoolyGraphs layout system')
    parser.add_argument('pattern', help='Pattern file (.txt)')
    parser.add_argument('--style', help='Style config (.json)')
    parser.add_argument('--output', '-o', default='output', help='Output prefix')
    parser.add_argument('--skip-optimize', action='store_true')
    args = parser.parse_args()

    # Load configuration
    style_path = args.style or args.pattern.replace('.txt', '.style.json')
    config = load_config(style_path)

    # Load stitch definitions
    stitches = pattern.load_stitches()

    # Parse pattern to graph
    g = graph.pattern_to_graph(args.pattern, stitches)
    print(f"Graph: {g.n_stitches} stitches, {len(g.edges)} edges")

    # Compute baseline positions
    positions = baseline.compute_baseline_positions(g, config)
    print(f"Baseline positions computed")

    # Optimize (unless skipped)
    if not args.skip_optimize:
        optimizer = LayoutOptimizer(config)
        positions = optimizer.optimize(g, positions)
        print(f"Optimization complete")

    # Export
    dot.export(g, positions, f"{args.output}.dot")
    csv.export(g, positions, f"{args.output}.csv")
    print(f"Exported to {args.output}.dot and {args.output}.csv")

if __name__ == '__main__':
    main()
```

### Phase 4: Advanced Features

#### 4.1 Short Row 3D Shaping
Closed-form z-perturbation for short rows:
```python
def short_row_perturbation(
    positions: np.ndarray,
    short_row_indices: List[int],
    profile: str = 'semicircle'
) -> np.ndarray:
    """Apply 3D perturbation for short row shaping."""
    if profile == 'semicircle':
        # Fit semicircle to short row region
        x_vals = positions[short_row_indices, 0]
        x_min, x_max = x_vals.min(), x_vals.max()
        x_center = (x_min + x_max) / 2
        radius = (x_max - x_min) / 2

        for idx in short_row_indices:
            x = positions[idx, 0]
            z = np.sqrt(max(0, radius**2 - (x - x_center)**2))
            positions[idx, 2] = z

    elif profile == 'catenary':
        # Catenary curve: z = a * cosh((x - x0) / a)
        ...

    return positions
```

#### 4.2 Cable Squeeze
```python
def cable_squeeze(
    positions: np.ndarray,
    cable_start: int,
    cable_end: int,
    squeeze_factor: float = 0.8
) -> np.ndarray:
    """Squeeze stitches between cable crosses inward."""
    # Find column indices between cable points
    column_indices = get_column_between(cable_start, cable_end)

    # Compute center of cable region
    center = positions[column_indices].mean(axis=0)

    # Squeeze toward center
    for idx in column_indices:
        direction = positions[idx] - center
        positions[idx] = center + squeeze_factor * direction

    return positions
```

#### 4.3 Mannequin Projection
```python
def project_to_mannequin(
    positions: np.ndarray,
    mannequin_mesh: Mesh,
    anchors: Dict[int, int]  # stitch_idx -> mannequin_vertex_idx
) -> np.ndarray:
    """Project positions to mannequin surface."""
    # Fix anchor positions
    for stitch_idx, mesh_idx in anchors.items():
        positions[stitch_idx] = mannequin_mesh.vertices[mesh_idx]

    # Project non-anchored stitches to nearest surface point
    for i in range(len(positions)):
        if i not in anchors:
            positions[i] = mannequin_mesh.closest_point(positions[i])

    return positions
```

## Literature & Algorithm References

### Force-Directed Layout
- **Fruchterman-Reingold (1991)**: Simple spring-electric model
  - Attraction: `f_a = d²/k` for edges
  - Repulsion: `f_r = k²/d` for all pairs
  - Good baseline, O(n²) per iteration

- **Kamada-Kawai (1989)**: Energy-based spring model
  - Uses graph-theoretic distances as target lengths
  - Better global layout, slower convergence

### Stress Majorization
- **SMACOF algorithm**: Iterative stress minimization
  - Provably convergent
  - Good for graphs with known target distances
  - Relevant: we have known edge lengths

### Spectral Methods
- **Laplacian eigenvectors**: Initial layout from graph spectrum
  - Very fast for initial positions
  - May provide better starting point than linear layout

### Finite Element Comparison
| Aspect | FEM | Our Approach |
|--------|-----|--------------|
| Domain | Continuous mesh | Discrete graph |
| Forces | Stress/strain tensors | Edge springs + repulsion |
| Solve | Linear system | Gradient descent |
| Complexity | O(n³) direct, O(n) iterative | O(n²) per epoch |

The key insight: knit structures are already discretized (stitches as nodes), so we bypass mesh generation entirely.

### Recommended Implementation Order

1. **Baseline (O(n) per stitch)**: Analytic placement
2. **Edge springs**: Direct from show.py, adapt to mm lengths
3. **Repulsion**: Direct from show.py
4. **PyTorch backend**: Enables auto-differentiation
5. **Solid angle**: New, enables manifold conformance
6. **Surface projection**: For mannequin mode

## Test Plan

### Unit Tests
```python
def test_flat_stockinette():
    """Verify flat layout produces expected grid."""
    g = load_pattern('patterns/small_stockinette.txt')
    pos = compute_baseline_positions(g, flat_config)

    # Check row spacing
    for row in range(4):
        row_y = pos[row_indices[row], 1]
        assert np.allclose(row_y, row * 3.0)  # 3mm vertical

    # Check stitch spacing within row
    for i in range(3):
        dx = pos[i+1, 0] - pos[i, 0]
        assert np.isclose(abs(dx), 4.0)  # 4mm horizontal

def test_circular_layout():
    """Verify circular layout produces tube."""
    g = load_pattern('patterns/tube_round.txt')
    pos = compute_baseline_positions(g, circular_config)

    # Check cast-on forms circle
    cast_on = pos[:8]
    center = cast_on.mean(axis=0)
    radii = np.linalg.norm(cast_on - center, axis=1)
    assert np.allclose(radii, radii[0], rtol=0.01)

def test_mobius_twist():
    """Verify mobius layout has half-twist."""
    g = load_pattern('patterns/mobius_strip.txt')
    pos = compute_baseline_positions(g, mobius_config)

    # After going around, orientation should be flipped
    # (specific test depends on twist implementation)
```

### Integration Tests
```bash
# Full pipeline test
python -m woolygraphs patterns/small_stockinette.txt -o test_flat
python -m woolygraphs patterns/tube_round.txt -o test_tube
python -m woolygraphs patterns/mobius_strip.txt -o test_mobius
```

## Performance Targets

| Pattern Size | Baseline Time | Optimization Time |
|--------------|---------------|-------------------|
| 20 stitches | < 1ms | < 1s |
| 200 stitches | < 10ms | < 10s |
| 2000 stitches | < 100ms | < 2min |
| 20000 stitches | < 1s | < 20min |

Key optimizations:
- Use sparse adjacency matrix for large graphs
- GPU acceleration via PyTorch for optimization
- Approximate repulsion with Barnes-Hut (O(n log n))

## Next Actions

1. [ ] Create `woolygraphs/` package directory
2. [ ] Move `stitches.txt` → `stitches.json` with proper JSON (no comments)
3. [ ] Implement `stitches.py` with dataclasses
4. [ ] Implement `graph.py` extracting from `knit.py`
5. [ ] Implement `baseline.py` with flat/circular layouts
6. [ ] Implement optimizer framework with edge spring force
7. [ ] Add PyTorch backend
8. [ ] Add solid angle force
9. [ ] Create CLI entry point
10. [ ] Add tests
