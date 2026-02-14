# WoolyGraphs Architecture

## Project Overview

WoolyGraphs converts knitting patterns into graph representations and optimizes their 3D layout for visualization, using physically-realistic yarn mechanics.

## Module Structure

```
woolygraphs/
├── Pattern Parsing & Graph Generation
│   ├── knit.py                 # Main: pattern → graph + initial positions
│   ├── stitches.txt            # Stitch definitions (JSON)
│   └── patterns/               # Input pattern files (.txt)
│
├── Layout Optimization
│   ├── optimize_layout.py      # NEW: PyTorch + ADAM optimizer
│   ├── forces.py               # NEW: Custom force calculations
│   └── show.py                 # OLD: Legacy simple physics (deprecated)
│
├── Data Export
│   ├── export_to_json.py       # Export graph + positions → JSON
│   └── matrices/               # Adjacency matrices (CSV)
│
├── 3D Visualization
│   └── viewer3d/
│       ├── index.html          # Web interface
│       ├── viewer.js           # Three.js visualization
│       ├── layout-engine.js    # Client-side physics (optional)
│       └── data/               # JSON graph files
│
└── Documentation
    ├── README.md               # Project overview
    ├── ARCHITECTURE.md         # This file
    └── TODO.org                # Task tracking
```

---

## Module 1: Pattern Parsing & Graph Generation

### `knit.py`

**Purpose**: Convert text-based knitting patterns into graph representations with physically-meaningful initial positions.

**Input**:
- Pattern file (e.g., `patterns/small_stockinette.txt`)
- Stitch definitions (`stitches.txt`)

**Output**:
- Adjacency matrix (CSV)
- Edge list with properties (weight, orientation)
- **Initial stitch positions** (based on knitting geometry)

**Key Classes**:
- `edge`: Connection between stitches (v, orient, bk, length)
- `stitch_tech`: Stitch type definition (character, kill, add, cursor_dir)

**Initial Position Calculation**:

When a pattern is converted to a graph, initial 3D positions should be calculated based on:

1. **Row-column layout**:
   - Each stitch has a (row, column) position in the pattern
   - Rows are stacked vertically (Y-axis)
   - Columns spread horizontally (X-axis)

2. **Physical spacing**:
   - Horizontal spacing: 4mm (gauge-dependent)
   - Vertical spacing: 3mm (row height)
   - Z-axis: Initially flat (z=0)

3. **Stitch-specific adjustments**:
   - Increases (kfb, yo): Slight offset in X
   - Decreases (k2tog, ssk): Slight inward shift
   - Short rows: Y-offset for partial rows

**Enhancement**: Add `calculate_initial_positions()` function that returns:
```python
{
  node_id: {
    'x': float,  # mm
    'y': float,  # mm
    'z': float,  # mm (initially 0)
    'row': int,
    'col': int
  }
}
```

---

## Module 2: Layout Optimization

### `optimize_layout.py` (NEW)

**Purpose**: Optimize stitch positions using PyTorch and ADAM optimizer with physically-realistic yarn mechanics.

**Dependencies**:
- PyTorch
- NumPy
- Scipy (for sparse matrix operations)

**Key Components**:

#### A. Optimizer Setup
```python
import torch
import torch.optim as optim

class YarnLayoutOptimizer:
    def __init__(self, graph, initial_positions, config):
        # Initialize positions as PyTorch tensors
        self.positions = torch.tensor(initial_positions, requires_grad=True)

        # ADAM optimizer
        self.optimizer = optim.Adam([self.positions], lr=0.01)

        # Configuration
        self.config = config
```

#### B. Loss Function
```python
def compute_loss(self):
    loss = 0.0

    # Edge attraction/repulsion (custom force curves)
    loss += self.edge_forces()

    # Node repulsion (adjacency matrix powers)
    loss += self.repulsion_forces()

    # Optional: Flatness penalty (solid angle)
    if self.config.use_flatness:
        loss += self.flatness_penalty()

    return loss
```

#### C. Optimization Loop
```python
def optimize(self, num_iterations=1000):
    for i in range(num_iterations):
        self.optimizer.zero_grad()
        loss = self.compute_loss()
        loss.backward()
        self.optimizer.step()

        if i % 100 == 0:
            print(f"Iteration {i}, Loss: {loss.item()}")
```

---

### `forces.py` (NEW)

**Purpose**: Calculate physically-realistic forces for yarn mechanics.

#### Edge Force Curves

**Vertical Edges** (between rows):
- Rest length: **3mm**
- Elastic region: ±40% stretch (1.8mm - 4.2mm)
- Force function:

```python
def vertical_edge_force(distance, rest_length=3.0):
    """
    Yarn-realistic force curve for vertical edges

    Args:
        distance: Current edge length (mm)
        rest_length: Equilibrium length (mm)

    Returns:
        Force magnitude (attraction if positive, repulsion if negative)
    """
    delta = distance - rest_length
    abs_delta = abs(delta)

    # Elastic limit: 40% of rest length
    elastic_limit = 0.4 * rest_length

    if abs_delta <= elastic_limit:
        # Linear elastic region (low stiffness)
        k_elastic = 0.1  # Low spring constant
        force = k_elastic * delta
    else:
        # Beyond elastic limit: steep increase
        overshoot = abs_delta - elastic_limit
        k_plastic = 10.0  # High spring constant

        # Optional: Step function jump at elastic limit
        step_penalty = 5.0

        force = (k_elastic * elastic_limit +
                step_penalty +
                k_plastic * overshoot) * torch.sign(delta)

    return force
```

**Horizontal Edges** (within row):
- Rest length: **4mm**
- Same force curve as vertical, different rest length

```python
def horizontal_edge_force(distance, rest_length=4.0):
    return vertical_edge_force(distance, rest_length)
```

**Edge Force Energy** (for loss function):
```python
def edge_force_energy(positions, edges, edge_types):
    """
    Compute total energy from edge forces

    Args:
        positions: [N, 3] tensor of node positions
        edges: [E, 2] array of edge indices
        edge_types: [E] array ('h' or 'v' for each edge)

    Returns:
        Total edge energy (scalar)
    """
    energy = 0.0

    for i, (src, tgt) in enumerate(edges):
        pos1 = positions[src]
        pos2 = positions[tgt]

        distance = torch.norm(pos2 - pos1)

        if edge_types[i] == 'v':
            force = vertical_edge_force(distance, rest_length=3.0)
        else:  # 'h'
            force = horizontal_edge_force(distance, rest_length=4.0)

        # Energy is integral of force
        # For optimization, we want to minimize deviation from rest length
        energy += force ** 2

    return energy
```

---

#### Adjacency Matrix Power-Based Repulsion

**Concept**: Instead of O(n²) all-pairs repulsion, only repel nodes that are "close" in the graph topology.

**Method**: Use powers of the adjacency matrix to determine repulsion neighborhoods.

```python
def compute_repulsion_matrix(adjacency_matrix, num_powers=3):
    """
    Compute which nodes should repel each other

    Args:
        adjacency_matrix: [N, N] sparse matrix (0/1 for edges)
        num_powers: How many hops to consider (default 3)

    Returns:
        repulsion_matrix: [N, N] binary matrix (1 = repel, 0 = don't)
    """
    import scipy.sparse as sp

    A = adjacency_matrix.astype(float)
    N = A.shape[0]

    # Start with zeros
    repulsion = sp.csr_matrix((N, N))

    # Add each power of A
    A_power = A.copy()
    for k in range(1, num_powers + 1):
        if k > 1:
            A_power = A_power @ A

        # Sign function: non-zero → 1
        repulsion += sp.csr_matrix((A_power != 0).astype(float))

    # Take sign: any connection → 1
    repulsion = (repulsion != 0).astype(float)

    # Set diagonal to 0 (no self-repulsion)
    repulsion.setdiag(0)

    return repulsion

def repulsion_energy(positions, repulsion_matrix, strength=50.0):
    """
    Compute repulsion energy for topology-local nodes

    Args:
        positions: [N, 3] tensor
        repulsion_matrix: [N, N] sparse binary matrix
        strength: Repulsion strength parameter

    Returns:
        Repulsion energy (scalar)
    """
    energy = 0.0

    # Get non-zero entries (i, j) that should repel
    rows, cols = repulsion_matrix.nonzero()

    for i, j in zip(rows, cols):
        if i < j:  # Only count each pair once
            pos1 = positions[i]
            pos2 = positions[j]

            distance = torch.norm(pos2 - pos1) + 1e-6  # Avoid division by zero

            # Inverse square repulsion
            energy += strength / (distance ** 2)

    return energy
```

**Configuration Parameter**:
```python
class LayoutConfig:
    def __init__(self):
        self.repulsion_powers = 3  # Default: A + A² + A³
        self.repulsion_strength = 50.0
        self.vertical_rest_length = 3.0  # mm
        self.horizontal_rest_length = 4.0  # mm
        self.elastic_limit_percent = 0.4  # 40% stretch
```

---

### Solid Angle Repulsion (Future Enhancement)

**Concept**: Use solid angles to enforce fabric flatness.

**Motivation**: Real knitted fabric wants to lie flat. Each stitch "sees" its neighbors and experiences a force that minimizes surface curvature.

**Approach**:

1. **Solid Angle Calculation**:
   - For each node, compute the solid angle subtended by its neighbor triangles
   - Flat fabric → solid angle = 2π
   - Curved fabric → deviation from 2π

2. **Flatness Energy**:
   ```python
   def solid_angle_energy(positions, edges):
       """
       Penalize deviation from flat configuration

       For each node, compute sum of solid angles from neighbor faces
       Flat fabric has solid angle = 2π at each interior node
       """
       energy = 0.0

       for node in nodes:
           neighbors = get_neighbors(node, edges)

           # Compute solid angle from triangles formed by node and neighbor pairs
           solid_angle = compute_solid_angle(positions[node],
                                             positions[neighbors])

           # Penalize deviation from 2π (flat)
           target_angle = 2 * np.pi
           energy += (solid_angle - target_angle) ** 2

       return energy
   ```

3. **Integration**:
   - Add as optional term to loss function
   - Weight parameter to balance with edge forces
   - Useful for large fabric pieces where flatness matters

**Documentation Note**: Implement this after basic yarn mechanics are working. Will require:
- Triangle mesh construction from graph
- Solid angle calculation (can use `trimesh` library)
- Careful tuning of weight parameter

---

## Module 3: Data Export

### `export_to_json.py` (UPDATE)

**Current**: Exports graph structure (nodes, edges) to JSON.

**Enhancement**: Include initial positions from knit.py.

**New JSON Format**:
```json
{
  "metadata": {
    "pattern": "small_stockinette",
    "nodeCount": 20,
    "edgeCount": 31,
    "hasInitialPositions": true
  },
  "nodes": [
    {
      "id": 0,
      "label": "stitch_0",
      "position": {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0
      },
      "row": 0,
      "col": 0
    }
  ],
  "edges": [
    {
      "source": 0,
      "target": 1,
      "weight": 1.0,
      "orientation": "h",
      "restLength": 4.0
    }
  ],
  "config": {
    "verticalRestLength": 3.0,
    "horizontalRestLength": 4.0,
    "repulsionPowers": 3
  }
}
```

**Changes Needed**:
1. Read initial positions from knit.py output
2. Add `restLength` to each edge based on orientation
3. Include layout configuration in metadata

---

## Module 4: 3D Visualization

### `viewer3d/`

**Current**: JavaScript-based Three.js viewer with simple physics.

**Enhancement**: Support optimized layouts from PyTorch.

**Changes**:
1. **Load initial positions** from JSON
2. **Optional client-side refinement** using layout-engine.js
3. **Display rest lengths** visually (color edges by tension)

**Future Features**:
- Tension heatmap (edges colored by deviation from rest length)
- Animation of optimization process
- Interactive adjustment of rest lengths
- Real-time physics toggle

---

## Data Flow

```
Pattern File (.txt)
    ↓
[knit.py] Parse pattern + Calculate initial positions
    ↓
Adjacency Matrix + Edge List + Initial Positions
    ↓
[optimize_layout.py] PyTorch + ADAM optimization
    ↓
Optimized Positions
    ↓
[export_to_json.py] Export graph + positions
    ↓
JSON File
    ↓
[viewer3d/] 3D Visualization
```

---

## Configuration System

Create `config.yaml` for layout parameters:

```yaml
layout:
  optimizer: "adam"
  learning_rate: 0.01
  num_iterations: 1000

  # Edge forces
  vertical_rest_length: 3.0    # mm
  horizontal_rest_length: 4.0  # mm
  elastic_limit_percent: 0.4   # 40% stretch
  k_elastic: 0.1               # Low stiffness spring constant
  k_plastic: 10.0              # High stiffness beyond elastic limit
  step_penalty: 5.0            # Force jump at elastic limit

  # Repulsion
  repulsion_powers: 3          # Use A + A² + A³
  repulsion_strength: 50.0

  # Flatness (future)
  use_flatness: false
  flatness_weight: 0.1

visualization:
  show_rest_length: true
  color_by_tension: true
  tension_colormap: "viridis"
```

---

## Implementation Priority

1. ✅ **Current**: Basic graph visualization working
2. **Phase 1**: Initial positions in knit.py
3. **Phase 2**: PyTorch optimizer setup
4. **Phase 3**: Custom edge force curves
5. **Phase 4**: Adjacency power repulsion
6. **Phase 5**: Integration and testing
7. **Phase 6** (Future): Solid angle flatness

---

## Testing Strategy

**Unit Tests**:
- Force curve correctness (edge cases)
- Adjacency matrix power computation
- Initial position calculation

**Integration Tests**:
- Small patterns (4x4 stockinette)
- Patterns with increases/decreases
- Lace patterns (yo, k2tog)

**Validation**:
- Compare to real knitted swatches (measure with calipers)
- Visual inspection of layout quality
- Energy convergence plots

---

## Notes for Future Development

### Gauge Awareness
- Rest lengths should be configurable based on yarn weight and needle size
- Add gauge detection from pattern metadata
- Support multiple gauges in same pattern (different yarn weights)

### Stitch-Specific Mechanics
- Cables: Add cross-over constraints
- Ribbing: Slight compression in horizontal direction
- Lace: Yarnovers have lower rest force (looser)

### 3D Shaping
- Increase/decrease regions create natural curves
- Short rows create wedges (non-planar geometry)
- Circular knitting: Join first/last column with periodic boundary

### Performance
- Use sparse matrices for large patterns
- GPU acceleration for large optimizations
- Incremental optimization (freeze earlier rows)

### Visualization Features
- Animation of knitting process (row by row)
- Tension map overlay
- Stitch-by-stitch highlighting
- Export to STL for 3D printing of structure
