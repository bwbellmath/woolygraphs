# WoolyGraphs Layout Algorithm -- Implementation Plan

This document is the engineering blueprint for implementing the 3-phase layout
algorithm described in `Layout_algorithm.md`. It specifies every file, class,
method, data structure, and mathematical formulation needed.

---

## 0. Notation & Conventions

| Symbol | Meaning |
|--------|---------|
| $\mathbf{p}_i \in \mathbb{R}^3$ | Position of stitch $i$ |
| $\hat{\mathbf{n}}_i \in S^2$ | Unit normal vector of stitch $i$ |
| $\hat{\mathbf{r}}_i$ | Unit right-left vector of stitch $i$ (derived) |
| $\hat{\mathbf{u}}_i$ | Unit up-down vector of stitch $i$ (derived) |
| $\ell_{ij}$ | Specified rest length of edge $(i,j)$ |
| $d_{ij} = \|\mathbf{p}_j - \mathbf{p}_i\|$ | Current Euclidean distance between stitches $i,j$ |
| $h$ | Stitch height (vertical rest length, default 3 mm) |
| $w$ | Stitch width (horizontal rest length, default 4 mm) |

Derived frame at stitch $i$:

```
r_i = normalize(p_{left_neighbor} - p_{right_neighbor})   # right-left
u_i = n_i x r_i                                           # up-down
```

If a stitch has no horizontal neighbors yet (e.g. first cast-on), use the
default frame: $\hat{\mathbf{n}} = (0,0,1)$, $\hat{\mathbf{r}} = (1,0,0)$,
$\hat{\mathbf{u}} = (0,1,0)$.

---

## 1. File Tree (new / modified files)

```
woolygraphs/
├── layout/                          # NEW -- layout package
│   ├── __init__.py                  #   re-exports public API
│   ├── stitch_instance.py           #   Phase 1 data structures
│   ├── initial_layout.py            #   Phase 1 compilation algorithm
│   ├── forces.py                    #   Phase 2 force models (refactored)
│   ├── optimizer.py                 #   Phase 2 PyTorch optimizer (refactored)
│   └── mesh.py                      #   Triangulation + solid-angle helpers
│
├── knit.py                          # MODIFIED -- emit LayoutStitch list + JSON
├── stitches.txt                     # MODIFIED -- add offset fields (see below)
│
├── viewer3d/
│   ├── viewer.js                    # MODIFIED -- consume new JSON format
│   ├── yarn_renderer.js             # NEW -- Phase 3 tubular yarn path
│   └── stitch_editor.js             # NEW -- Phase 3 interactive editing
│
├── tests/                           # NEW -- unit & integration tests
│   ├── test_stitch_instance.py
│   ├── test_initial_layout.py
│   ├── test_forces.py
│   ├── test_optimizer.py
│   └── test_mesh.py
│
├── run_layout.py                    # NEW -- end-to-end CLI entry point
└── IMPLEMENTATION_PLAN.md           # this file
```

---

## 2. Phase 1: Initial Layout ("Compilation")

### 2.1 Extended Stitch Descriptions (`stitches.txt`)

Add per-stitch-type offset defaults to the existing JSON entries:

```jsonc
"k": {
  // ... existing fields ...
  "offsets": {
    "normal":  0.1,   // fraction of stitch_height (+bump for knit)
    "right_left": 0.0,
    "up_down": 0.0
  }
}
```

Offset conventions (all in units of `stitch_height`):
| Stitch Type | `normal` | `up_down` | Rationale |
|-------------|----------|-----------|-----------|
| k (knit)    | +0.1     | 0.0       | Slight outward bump on knit side |
| p (purl)    | -0.1     | 0.0       | Slight inward bump (bump on other side) |
| kfb         | +0.1     | +0.1      | Increase widens fabric upward |
| k2tog       | +0.1     | -0.1      | Decrease narrows fabric downward |
| k3tog       | +0.1     | -0.15     | Stronger decrease |
| yo          | 0.0      | +0.1      | Yarn-over opens a hole upward |
| co          | 0.0      | 0.0       | Cast-on is baseline |
| bo          | 0.0      | 0.0       | Bind-off is baseline |
| turn        | N/A      | N/A       | No stitch created, reverses cursor |

### 2.2 Data Structures

#### `layout/stitch_instance.py`

```python
@dataclass
class StitchInstance:
    """A single instantiated stitch in the layout."""

    index: int                          # unique stitch id
    stitch_type: str                    # key into stitch descriptions ("k","p",...)
    character: str                      # "k" or "p"

    # Geometry -- the optimizable degrees of freedom
    position: np.ndarray                # (3,) float64  [x, y, z]
    normal: np.ndarray                  # (3,) float64  unit normal

    # Derived (recomputed from neighbors)
    right_left: np.ndarray              # (3,) float64  unit vector
    up_down: np.ndarray                 # (3,) float64  unit vector

    # Connectivity (populated during compilation)
    back_edges: list[BackEdge]          # edges to stitches below / behind
    # forward edges are NOT stored here; they are the back_edges
    # of stitches in the next row pointing back to this one.

    # Stitch-type-inherited offsets
    offset_normal: float                # e.g. +0.1 for knit
    offset_right_left: float
    offset_up_down: float


@dataclass
class BackEdge:
    """One directed edge from this stitch back to a neighbor."""

    target_index: int                   # index of connected stitch
    orientation: str                    # "h" or "v"
    rest_length: float                  # specified rest length (mm)
    bump: bool                          # True = "b" (bump off needle)
```

#### `layout/stitch_instance.py` -- helper

```python
class LayoutGraph:
    """Collection of StitchInstances + convenience accessors."""

    stitches: list[StitchInstance]
    edge_list: list[tuple[int, int, str, float]]
    # (src, tgt, orientation, rest_length)

    def adjacency_matrix(self) -> np.ndarray: ...
    def positions_array(self) -> np.ndarray:       # (N, 3)
    def normals_array(self) -> np.ndarray:         # (N, 3)
    def to_json(self, path: str) -> None: ...      # export for viewer
    def from_json(cls, path: str) -> "LayoutGraph": ...
```

### 2.3 Initial Layout Algorithm (`layout/initial_layout.py`)

**Input:** A pattern file (sequence of stitch names, e.g. `"co co co co turn k k k k turn ..."`) and the stitch description dictionary.

**Output:** A `LayoutGraph` with every stitch instance positioned and connected.

#### Algorithm: `compile_pattern`

```
function compile_pattern(pattern_tokens, stitch_defs, gauge):
    stitches = []
    left_needle = []          # stitches held on left needle
    right_needle = []         # stitches held on right needle
    count = 0
    edge = True               # first stitch on a row has no horizontal neighbor
    progression = +1          # +1 = knitting right-to-left, flips on turn

    # Default frame
    current_pos = [0, 0, 0]
    current_normal = [0, 0, 1]

    for token in pattern_tokens:
        sdef = stitch_defs[token]

        if sdef.cursor_dir:                           # --- TURN ---
            swap(left_needle, right_needle)
            progression *= -1
            edge = True
            continue

        for a in range(sdef.add):                     # --- ADD stitches ---
            # 1. Compute position from previous stitch + offsets
            pos = compute_initial_position(
                count, stitches, left_needle, right_needle,
                sdef, gauge, current_pos, current_normal, progression
            )

            # 2. Compute normal (average of neighbor normals + stitch offset)
            normal = compute_initial_normal(
                count, stitches, sdef, current_normal
            )

            # 3. Create instance
            inst = StitchInstance(
                index=count, stitch_type=token,
                character=sdef.character,
                position=pos, normal=normal,
                offset_normal=sdef.offsets.normal * gauge.stitch_height,
                offset_right_left=sdef.offsets.right_left * gauge.stitch_height,
                offset_up_down=sdef.offsets.up_down * gauge.stitch_height,
                ...
            )

            # 4. Horizontal edge to previous stitch on same row
            if not edge:
                inst.back_edges.append(BackEdge(
                    target_index=count - 1,
                    orientation="h",
                    rest_length=gauge.stitch_width,
                    bump=False
                ))
            else:
                edge = False

            right_needle.append(count)
            stitches.append(inst)
            count += 1

        for k in range(sdef.kill):                    # --- KILL stitches ---
            used = left_needle.pop()
            for added_idx in <newly added stitch indices>:
                stitches[added_idx].back_edges.append(BackEdge(
                    target_index=used,
                    orientation="v",
                    rest_length=gauge.stitch_height,
                    bump=True
                ))

    return LayoutGraph(stitches)
```

#### Sub-routine: `compute_initial_position`

Places each new stitch relative to its neighbors using the local frame:

```
function compute_initial_position(...):
    if count == 0:
        return [0, 0, 0]        # first stitch at origin

    # Horizontal placement: step along right_left vector
    prev = stitches[count - 1]
    r_hat = prev.right_left * progression
    base_pos = prev.position + gauge.stitch_width * r_hat

    # Vertical placement: if we have a below-neighbor, blend toward it
    if has_below_neighbor:
        below = stitches[below_idx]
        u_hat = below.up_down
        base_pos = below.position + gauge.stitch_height * u_hat

    # Apply stitch-type offsets
    n_hat = current_normal
    base_pos += sdef.offsets.normal    * gauge.stitch_height * n_hat
    base_pos += sdef.offsets.up_down   * gauge.stitch_height * u_hat
    base_pos += sdef.offsets.right_left * gauge.stitch_width * r_hat

    return base_pos
```

### 2.4 Gauge Configuration

```python
@dataclass
class Gauge:
    """Physical dimensions from yarn weight + needle size."""
    stitch_width: float = 4.0     # mm (horizontal rest length)
    stitch_height: float = 3.0    # mm (vertical rest length)
    yarn_diameter: float = 0.5    # mm (for tubular rendering)
```

---

## 3. Phase 2: Physics-Based Optimization

### 3.1 Degrees of Freedom

For $N$ stitches the optimizer solves for:

| Variable | Shape | Description |
|----------|-------|-------------|
| $\mathbf{P}$ | $(N, 3)$ | Stitch positions |
| $\mathbf{N}$ | $(N, 3)$ | Stitch normal vectors (unit-constrained) |

Total: $6N$ scalar DOFs (minus 3 for global translation, 3 for global rotation =
$6N - 6$ true DOFs, but we optimize all $6N$ and let the loss landscape handle
symmetry).

### 3.2 Loss Function

$$\mathcal{L} = \lambda_{\text{edge}} \mathcal{L}_{\text{edge}} + \lambda_{\text{normal}} \mathcal{L}_{\text{normal}} + \lambda_{\text{coherence}} \mathcal{L}_{\text{coherence}} + \lambda_{\text{offset}} \mathcal{L}_{\text{offset}} + \lambda_{\text{flat}} \mathcal{L}_{\text{flat}} + \lambda_{\text{repulsion}} \mathcal{L}_{\text{repulsion}}$$

Default weights (configurable per knit object):
| Term | $\lambda$ | Purpose |
|------|-----------|---------|
| edge | 10.0 | Strongest: edge lengths must be satisfied |
| normal | 1.0 | Normal vectors stay unit-length |
| coherence | 2.0 | Neighboring normals agree (smooth surface) |
| offset | 0.5 | Stitch-type offsets are soft preferences |
| flat | 1.0 | Fabric lies flat (solid-angle) |
| repulsion | 0.1 | Prevent self-intersection |

All $\lambda$ values are configurable per knit object. Different objects need
very different balances (e.g. a hat relaxes coherence at the crown; a blocked
shawl cranks up flatness and drops edge weight).

#### 3.2.1 Edge Length Loss

Piecewise elastic/plastic model (existing in `forces.py`, vectorized):

$$\mathcal{L}_{\text{edge}} = \sum_{(i,j) \in E} E_{\text{yarn}}(d_{ij}, \ell_{ij})$$

where:

$$E_{\text{yarn}}(d, \ell) = \begin{cases} \frac{1}{2} k_e \delta^2 & |\delta| \le \alpha \ell \\ \frac{1}{2} k_e (\alpha \ell)^2 + s (|\delta| - \alpha \ell) + \frac{1}{2} k_p (|\delta| - \alpha \ell)^2 & |\delta| > \alpha \ell \end{cases}$$

with $\delta = d - \ell$, elastic limit fraction $\alpha = 0.4$, elastic stiffness $k_e = 0.1$, plastic stiffness $k_p = 10.0$, step penalty $s = 5.0$.

**Vectorized implementation** (replaces the current per-edge Python loop):

```python
def total_edge_energy_vectorized(positions, edge_indices, rest_lengths, params):
    """
    positions:    (N, 3) tensor
    edge_indices: (E, 2) long tensor
    rest_lengths: (E,) tensor
    """
    src = positions[edge_indices[:, 0]]          # (E, 3)
    tgt = positions[edge_indices[:, 1]]          # (E, 3)
    diffs = tgt - src                            # (E, 3)
    dists = torch.norm(diffs, dim=1) + 1e-8      # (E,)

    delta = dists - rest_lengths                 # (E,)
    abs_delta = torch.abs(delta)
    threshold = params.elastic_limit * rest_lengths

    # Elastic energy
    elastic = 0.5 * params.k_elastic * delta ** 2

    # Plastic energy
    overshoot = abs_delta - threshold
    plastic = (0.5 * params.k_elastic * threshold ** 2
               + params.step_penalty * overshoot
               + 0.5 * params.k_plastic * overshoot ** 2)

    energy = torch.where(abs_delta <= threshold, elastic, plastic)
    return energy.sum()
```

#### 3.2.2 Normal Unit-Length Loss

Keep normals on the unit sphere:

$$\mathcal{L}_{\text{normal}} = \sum_i (\|\hat{\mathbf{n}}_i\|^2 - 1)^2$$

This can also be enforced by hard projection after each optimizer step (or both
-- soft loss for smooth gradients, projection for hard guarantee):

```python
with torch.no_grad():
    normals.div_(normals.norm(dim=1, keepdim=True).clamp(min=1e-8))
```

#### 3.2.3 Normal Coherence Loss

**Neighboring stitches should follow the same surface.** For every edge $(i,j)$
in the graph, penalize divergence between the two normal vectors:

$$\mathcal{L}_{\text{coherence}} = \sum_{(i,j) \in E} (1 - \hat{\mathbf{n}}_i \cdot \hat{\mathbf{n}}_j)$$

When $\hat{\mathbf{n}}_i = \hat{\mathbf{n}}_j$ the dot product is 1 and the
contribution is 0. When they point in different directions the loss grows,
reaching a maximum of 2 when they are anti-parallel.

$\lambda_{\text{coherence}}$ is a **per-object configurable parameter**:
- **High** (e.g. 5.0) for flat stockinette, blocked shawls -- the whole fabric
  agrees on "up".
- **Medium** (e.g. 2.0, default) for general garments.
- **Low** (e.g. 0.5) for objects with intentional curvature (hat crowns, sock
  heels) where the normal field must be allowed to rotate.

**Vectorized implementation:**

```python
def normal_coherence_loss(normals, edge_indices):
    """
    normals:      (N, 3) tensor, assumed ~unit length
    edge_indices: (E, 2) long tensor
    """
    n_src = normals[edge_indices[:, 0]]    # (E, 3)
    n_tgt = normals[edge_indices[:, 1]]    # (E, 3)
    dots = (n_src * n_tgt).sum(dim=1)      # (E,)
    return (1.0 - dots).sum()
```

#### 3.2.4 Stitch-Type Offset Loss

For each stitch $i$ with specified offsets $(\delta_n^{(i)}, \delta_r^{(i)}, \delta_u^{(i)})$, penalize deviation from the desired micro-displacement relative to the local frame:

$$\mathcal{L}_{\text{offset}} = \sum_i \left[ (\mathbf{p}_i \cdot \hat{\mathbf{n}}_i - \bar{n}_i - \delta_n^{(i)})^2 + (\mathbf{p}_i \cdot \hat{\mathbf{r}}_i - \bar{r}_i - \delta_r^{(i)})^2 + (\mathbf{p}_i \cdot \hat{\mathbf{u}}_i - \bar{u}_i - \delta_u^{(i)})^2 \right]$$

where $\bar{n}_i, \bar{r}_i, \bar{u}_i$ are the projections of the average
neighbor position onto each axis, serving as the reference point.

In practice this is computed as:

```python
def offset_loss(positions, normals, stitch_offsets, neighbor_indices):
    """
    For each stitch, compute the displacement from the centroid of its
    neighbors and penalize deviation from the desired stitch-type offsets.
    """
    for i in range(N):
        nbrs = neighbor_indices[i]
        centroid = positions[nbrs].mean(dim=0)
        displacement = positions[i] - centroid

        n_hat = normals[i]
        r_hat = compute_right_left(positions, i, nbrs)
        u_hat = torch.cross(n_hat, r_hat)

        proj_n = torch.dot(displacement, n_hat)
        proj_r = torch.dot(displacement, r_hat)
        proj_u = torch.dot(displacement, u_hat)

        loss += (proj_n - stitch_offsets[i].normal) ** 2
        loss += (proj_r - stitch_offsets[i].right_left) ** 2
        loss += (proj_u - stitch_offsets[i].up_down) ** 2
```

#### 3.2.5 Flatness Loss (Solid-Angle)

As detailed in `SOLID_ANGLE_PLAN.md`. For each interior vertex $i$, the sum of
solid angles subtended by surrounding triangular faces should equal $2\pi$:

$$\mathcal{L}_{\text{flat}} = \sum_{i \in \text{interior}} \left( \sum_{t \in \text{adj}(i)} \Omega_t(\mathbf{p}_i) - 2\pi \right)^2$$

where $\Omega_t$ is the solid angle of triangle $t$ as seen from vertex $i$,
computed via the Van Oosterom-Strackee formula:

$$\Omega = 2 \arctan \frac{\hat{\mathbf{a}} \cdot (\hat{\mathbf{b}} \times \hat{\mathbf{c}})}{1 + \hat{\mathbf{a}} \cdot \hat{\mathbf{b}} + \hat{\mathbf{b}} \cdot \hat{\mathbf{c}} + \hat{\mathbf{c}} \cdot \hat{\mathbf{a}}}$$

with $\hat{\mathbf{a}}, \hat{\mathbf{b}}, \hat{\mathbf{c}}$ being unit vectors
from the vertex to the three triangle corners.

**Mesh construction**: Triangulate quads formed by adjacent horizontal/vertical
edges. For a grid region with stitches at $(r,c), (r,c+1), (r+1,c), (r+1,c+1)$:

```
(r+1,c) --- (r+1,c+1)
  | \           |
  |   \         |
  |     \       |
(r,c) --- (r,c+1)

Triangle 1: (r,c), (r,c+1), (r+1,c)
Triangle 2: (r,c+1), (r+1,c+1), (r+1,c)
```

For non-grid regions (increases/decreases), use constrained Delaunay
triangulation via `scipy.spatial.Delaunay`.

#### 3.2.6 Repulsion Loss

Topology-aware repulsion (existing, but vectorized):

$$\mathcal{L}_{\text{repulsion}} = \sum_{(i,j) \in R} \frac{k_r}{d_{ij}^2}$$

where $R = \text{sign}(A + A^2 + A^3)$ is the set of pairs within 3 hops.

### 3.3 Optimizer Configuration (`layout/optimizer.py`)

```python
@dataclass
class OptimizerConfig:
    # Optimizer
    optimizer: str = "adam"            # "adam" | "sgd" | "lbfgs"
    learning_rate: float = 0.01
    num_iterations: int = 2000
    convergence_tol: float = 1e-5     # stop when |dL/dt| < tol
    log_interval: int = 100

    # Loss weights  (all configurable per knit object)
    lambda_edge: float = 10.0
    lambda_normal: float = 1.0
    lambda_coherence: float = 2.0     # normal coherence between neighbors
    lambda_offset: float = 0.5
    lambda_flat: float = 1.0
    lambda_repulsion: float = 0.1

    # Edge force parameters
    elastic_limit: float = 0.4
    k_elastic: float = 0.1
    k_plastic: float = 10.0
    step_penalty: float = 5.0

    # Repulsion
    repulsion_powers: int = 3
    repulsion_strength: float = 50.0

    # Normal projection
    project_normals: bool = True       # re-normalize after each step

    # Physical domain
    domain: str = "free"               # "free" | "gravity" | "mannequin" | "blocked_flat"
    gravity_strength: float = 0.0      # only if domain == "gravity"
    anchored_stitches: list = field(default_factory=list)

    # Blocked-flat mode parameters (only if domain == "blocked_flat")
    blocked_flat_plane_z: float = 0.0  # z-coordinate of the blocking plane
    lambda_z: float = 100.0            # penalty for z-deviation from plane
    lambda_angular_uniformity: float = 1.0  # even angular spacing of edges
```

**Pre-built domain presets** (convenience constructors):

```python
@classmethod
def blocked_flat_preset(cls) -> "OptimizerConfig":
    """Config for blocking a shawl / lace flat."""
    cfg = cls()
    cfg.domain = "blocked_flat"
    cfg.lambda_edge = 0.5          # edge lengths are SOFT (yarn stretches)
    cfg.lambda_coherence = 5.0     # all normals point same way (flat!)
    cfg.lambda_flat = 10.0         # solid-angle flatness is HARD
    cfg.lambda_z = 100.0           # pin to z=0 plane
    cfg.lambda_angular_uniformity = 1.0
    return cfg
```

### 3.4 Optimizer Class (`layout/optimizer.py`)

```python
class LayoutOptimizer:
    """
    Phase 2 optimizer. Takes a LayoutGraph from Phase 1 and refines
    positions + normals using gradient descent.
    """

    def __init__(self, layout_graph: LayoutGraph, config: OptimizerConfig):
        ...

    # ---- Core API ----

    def optimize(self) -> LayoutGraph:
        """Run the full optimization loop. Returns refined LayoutGraph."""

    def step(self) -> dict[str, float]:
        """Single optimizer step. Returns loss components."""

    def compute_loss(self) -> tuple[torch.Tensor, dict[str, float]]:
        """Evaluate all loss terms. Returns (total_loss, component_dict).
        Includes: edge, normal, coherence, offset, flatness, repulsion,
        plus z_plane and angular_uniformity when domain == 'blocked_flat'."""

    # ---- Loss terms ----

    def _edge_loss(self) -> torch.Tensor:
        """Vectorized piecewise yarn energy."""

    def _normal_loss(self) -> torch.Tensor:
        """Unit-length penalty on normal vectors."""

    def _coherence_loss(self) -> torch.Tensor:
        """Normal coherence: sum of (1 - n_i . n_j) over all edges.
        Keeps neighboring stitches on the same smooth surface."""

    def _offset_loss(self) -> torch.Tensor:
        """Stitch-type micro-displacement penalty."""

    def _flatness_loss(self) -> torch.Tensor:
        """Solid-angle flatness energy."""

    def _repulsion_loss(self) -> torch.Tensor:
        """Topology-aware inverse-square repulsion."""

    # ---- Blocked-flat mode loss terms ----

    def _z_plane_loss(self) -> torch.Tensor:
        """Penalty for deviation from the blocking plane: sum_i (z_i - z0)^2.
        Only active when domain == 'blocked_flat'."""

    def _angular_uniformity_loss(self) -> torch.Tensor:
        """Penalize uneven angular spacing of edges around each vertex.
        Encourages regular fan-out (important for shawls).
        Only active when domain == 'blocked_flat'."""

    # ---- Utilities ----

    def _build_triangulation(self) -> list[tuple[int,int,int]]:
        """Construct triangle mesh for flatness computation."""

    def _project_normals(self):
        """Re-normalize normal vectors to unit sphere."""

    def _check_convergence(self) -> bool:
        """True if loss change < convergence_tol for last 50 iterations."""

    def get_optimized_graph(self) -> LayoutGraph:
        """Extract optimized positions/normals into a new LayoutGraph."""

    def plot_history(self, path: str): ...
    def visualize_3d(self, path: str): ...
```

### 3.5 Physical Domain Options

| Domain | Description | Extra Loss Terms |
|--------|-------------|-----------------|
| `"free"` | Zero-gravity relaxation | None (default) |
| `"gravity"` | Fabric hangs under gravity | $\mathcal{L}_{\text{grav}} = g \sum_i y_i$ (penalize height) |
| `"mannequin"` | Drape over fixed surface | Pin anchored stitches; add collision penalty with mannequin mesh |
| `"blocked_flat"` | Pinned flat on a blocking board | $\mathcal{L}_z$, $\mathcal{L}_{\text{angular}}$; edge loss softened; coherence maximized |

For `"mannequin"` mode, anchored stitches have their positions frozen
(`requires_grad=False`) and a signed-distance-field collision term prevents
fabric from penetrating the mannequin surface.

#### 3.5.1 Blocked-Flat Mode Details

Blocked-flat mode models the process of **wet-blocking** knitted lace and
shawls: the fabric is soaked, pinned flat to a board, and allowed to dry.
The yarn stretches to accommodate the desired shape. This is the appropriate
mode for pi-shawls, lace shawls, and any item where the finished shape is
determined by blocking rather than by relaxed yarn tension.

**Loss priority inversion** compared to `"free"` mode:

| Term | Free mode $\lambda$ | Blocked-flat $\lambda$ | Why |
|------|---------------------|----------------------|-----|
| edge | 10.0 (hard) | 0.5 (soft) | Yarn stretches during blocking |
| coherence | 2.0 | 5.0 | Entire surface agrees on normal = (0,0,1) |
| flat (solid-angle) | 1.0 | 10.0 | Flatness is the whole point |
| z-plane | 0 (off) | 100.0 | Pin all stitches to z=0 |
| angular uniformity | 0 (off) | 1.0 | Even fan-out for shawl wedges |

**Z-plane loss:**

$$\mathcal{L}_z = \sum_i (z_i - z_0)^2$$

This is effectively a hard constraint -- with $\lambda_z = 100$, the optimizer
quickly learns to keep everything on the plane.

**Angular uniformity loss:**

For each vertex $i$ with neighbors $j_1, \ldots, j_k$, project edges into the
blocking plane and compute the angles $\theta_1, \ldots, \theta_k$ between
consecutive edges (sorted by angle). The ideal spacing is $2\pi / k$ for
interior vertices. Penalize deviation:

$$\mathcal{L}_{\text{angular}} = \sum_i \sum_{m=1}^{k_i} \left(\theta_m^{(i)} - \frac{2\pi}{k_i}\right)^2$$

This prevents stitches from bunching up on one side, which is important for
shawls where increases create a wedge or circular shape.

**2D reduction**: In blocked-flat mode, with $\lambda_z$ very high, the problem
effectively becomes a 2D layout: find $(x, y)$ positions such that the graph
is regular in the plane, with edge lengths allowed to stretch as needed. The
rest lengths from stitch descriptions serve as soft guides rather than hard
targets.

---

## 4. Phase 3: Display

### 4.1 Enhanced JSON Schema

The viewer consumes JSON produced by `LayoutGraph.to_json()`:

```jsonc
{
  "metadata": {
    "pattern": "acorn-3",
    "nodeCount": 120,
    "edgeCount": 210,
    "hasOptimizedPositions": true,
    "hasNormals": true,
    "gauge": { "stitch_width": 4.0, "stitch_height": 3.0, "yarn_diameter": 0.5 }
  },
  "nodes": [
    {
      "id": 0,
      "label": "stitch_0",
      "stitch_type": "co",
      "character": "k",
      "position": { "x": 0.0, "y": 0.0, "z": 0.0 },
      "normal": { "x": 0.0, "y": 0.0, "z": 1.0 }
    }
  ],
  "edges": [
    {
      "source": 0,
      "target": 1,
      "orientation": "h",
      "rest_length": 4.0,
      "weight": 1.0
    }
  ],
  "yarn_path": [0, 1, 2, 3, ...]   // directed stitch order for yarn rendering
}
```

### 4.2 Viewer Enhancements (`viewer3d/`)

#### Iteration 1: Consume new format
- Update `viewer.js` to read `position`, `normal`, `stitch_type` fields
- Color nodes by stitch type (knit=cyan, purl=magenta, yo=yellow, etc.)
- Orient node geometry (small discs or cubes) along normal vector

#### Iteration 2: Color editing (`stitch_editor.js`)
- Raycasting click on stitch spheres
- Color picker popup
- Export modified colors back to JSON

#### Iteration 3: Stitch editing (`stitch_editor.js`)
- Change stitch type via dropdown on click
- Add/remove stitches with connectivity dialog
- Re-run Phase 1 + Phase 2 on modified pattern (server-side)

#### Iteration 4: Yarn path rendering (`yarn_renderer.js`)
- Follow `yarn_path` array to generate a directed path
- For each consecutive pair, draw a Catmull-Rom spline
- Render as `THREE.TubeGeometry` with `yarn_diameter` radius
- Color by yarn strand (support multi-color yarns)

---

## 5. End-to-End Pipeline (`run_layout.py`)

```
Usage:
  python run_layout.py <pattern.txt> [--output <dir>] [--config <config.json>]
                                     [--domain free|gravity|mannequin|blocked_flat]

Steps:
  1. Parse pattern file → token list
  2. Load stitch descriptions from stitches.txt
  3. Phase 1: compile_pattern → LayoutGraph (initial positions + normals)
  4. Phase 2: LayoutOptimizer.optimize → refined LayoutGraph
     (domain flag selects preset lambda weights, overridable via config.json)
  5. Export to JSON (for viewer) + CSV (adjacency matrix)
  6. Generate diagnostic plots (loss history, 3D layout)
  7. Optionally launch viewer3d HTTP server
```

---

## 6. Migration from Existing Code

| Existing File | Action |
|---------------|--------|
| `forces.py` | Refactor into `layout/forces.py`. Keep `YarnForceModel` API but add vectorized `total_edge_energy_vectorized`. Move `RepulsionModel` and `FlatnessModel` into same file. |
| `optimize_layout.py` | Replace with `layout/optimizer.py`. Port `LayoutConfig` → `OptimizerConfig`, `YarnLayoutOptimizer` → `LayoutOptimizer`. Add normal/offset/flatness loss terms. |
| `knit.py` | Keep pattern-parsing logic. Replace the raw edge-list / adjacency-matrix output with calls to `layout/initial_layout.py::compile_pattern`. Still emit CSV for backward compatibility. |
| `export_to_json.py` | Absorb into `LayoutGraph.to_json()`. Deprecate standalone script. |
| `viewer3d/layout-engine.js` | Keep as fallback client-side physics. Primary layout now comes pre-computed from Python. |

---

## 7. Testing Strategy

### Unit Tests (`tests/`)

| Test | What it Verifies |
|------|-----------------|
| `test_stitch_instance.py` | StitchInstance creation, BackEdge wiring, frame computation |
| `test_initial_layout.py` | `compile_pattern` on `"co co co co turn k k k k turn"` produces correct positions, edges, normals |
| `test_forces.py` | Vectorized edge energy matches loop version; elastic/plastic boundary correct; coherence loss is 0 for identical normals and 2 for anti-parallel |
| `test_optimizer.py` | Loss decreases monotonically on a 4x4 grid; convergence detection works; coherence loss drives normals to align |
| `test_mesh.py` | Triangulation of 4x4 grid yields 18 triangles; solid angle of flat mesh ≈ 2π per interior vertex |
| `test_blocked_flat.py` | Blocked-flat preset: z-plane loss drives all z→0; angular uniformity loss produces even spacing on a fan pattern; edge lengths are allowed to stretch |

### Integration Tests

1. Full pipeline on `small_stockinette.txt` → JSON → viewer loads without error
2. Full pipeline on `acorn-3.txt` (complex pattern with increases)
3. Compare optimized edge lengths to rest lengths (mean error < 15%)
4. Verify normal vectors remain unit-length after optimization (max deviation < 0.01)
5. Coherence test: after optimization, mean $(1 - \hat{n}_i \cdot \hat{n}_j)$ across all edges < 0.05 for flat stockinette
6. Blocked-flat test on a pi-shawl pattern: all z-coordinates within 0.01 mm of plane; edge lengths may deviate > 40% from rest (this is correct -- yarn stretches)

### Regression

- Keep `optimize_layout.py` functional during migration via import shim
- Viewer must still load old-format JSON files (backward compat)

---

## 8. Implementation Order

| Step | Deliverable | Depends On |
|------|-------------|------------|
| **A** | `layout/stitch_instance.py` -- data structures | Nothing |
| **B** | Extended `stitches.txt` with offset fields | Nothing |
| **C** | `layout/initial_layout.py` -- `compile_pattern` | A, B |
| **D** | `layout/forces.py` -- vectorized edge energy + coherence loss | Nothing |
| **E** | `layout/mesh.py` -- triangulation + solid angle | Nothing |
| **F** | `layout/optimizer.py` -- full optimizer with all 7 loss terms (edge, normal, coherence, offset, flat, repulsion, + blocked-flat terms) | A, C, D, E |
| **F.1** | Domain presets (`blocked_flat_preset`, etc.) + z-plane / angular uniformity losses | F |
| **G** | `run_layout.py` -- CLI entry point with `--domain` flag | C, F |
| **H** | `tests/` -- unit + integration tests | A-G |
| **I** | Modify `knit.py` to call `compile_pattern` | C |
| **J** | Update `viewer3d/viewer.js` for new JSON format | G |
| **K** | `viewer3d/yarn_renderer.js` -- tubular yarn | J |
| **L** | `viewer3d/stitch_editor.js` -- interactive editing | J |

Critical path: **A → C → F → G → J**

---

## 9. Open Questions & Decisions Needed

1. **Normal vector DOF**: Should normals be free-floating optimized variables, or should they always be derived from neighbor positions (like a mesh vertex normal)? Free-floating gives more flexibility but adds DOFs.

2. **Boundary vertex target angle**: For the solid-angle flatness term, what should the target be for boundary vertices? Options: (a) skip them, (b) use $\pi$ for edge vertices and $\pi/2$ for corners, (c) compute expected angle from valence.

3. **Cable stitches**: The current `knit.py` has a special case for cables (`c4f`, etc.). Need to decide how cables affect the local frame and offsets.

4. **Circular knitting**: `Layout_algorithm.md` mentions "TODO: figure out how to work in the round." Periodic boundary conditions for cast-on row would connect first and last stitch. This affects Phase 1 initial positioning (layout on a cylinder rather than a plane).

5. **L-BFGS vs Adam**: For Phase 2, L-BFGS typically converges faster on smooth objectives but requires more memory. Worth benchmarking both.
