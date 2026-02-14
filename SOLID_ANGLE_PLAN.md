# Solid Angle Repulsion Plan

## Overview

Replace topology-based repulsion with **solid angle-based flatness enforcement** to make fabric layouts physically realistic. Real knitted fabric wants to lie flat, and this can be modeled using solid angles subtended by neighboring stitches.

## Mathematical Background

### Solid Angle Definition

The **solid angle** Ω subtended by a surface at a point is the area of the projection of that surface onto a unit sphere centered at the point.

- Units: steradians (sr)
- Full sphere: 4π sr
- Hemisphere: 2π sr

### Flatness Criterion

For a **flat surface**, each interior vertex is surrounded by faces whose solid angles sum to **2π steradians**.

For a **curved surface**, the sum deviates from 2π:
- Convex curvature (bump): Ω < 2π
- Concave curvature (dip): Ω > 2π

## Application to Knitting

### Mesh Construction

Convert the knitting graph into a **triangular mesh**:

1. **Vertices**: Stitches (nodes)
2. **Faces**: Triangles formed by connected stitches

For a regular stockinette pattern with nodes arranged in a grid:
```
Row i+1:  o---o---o---o
          |\ /|\ /|\ /|
          | X | X | X |
          |/ \|/ \|/ \|
Row i:    o---o---o---o
```

Each interior vertex is surrounded by ~6 triangular faces (depends on pattern).

### Solid Angle Calculation

For each vertex `v`, compute the solid angle subtended by each adjacent triangle:

```python
def solid_angle_triangle(p, a, b, c):
    """
    Compute solid angle subtended by triangle (a, b, c) at point p

    Args:
        p: Observer point (vertex position)
        a, b, c: Triangle vertices

    Returns:
        Solid angle in steradians
    """
    # Vectors from p to triangle vertices
    pa = a - p
    pb = b - p
    pc = c - p

    # Normalize
    pa_norm = pa / np.linalg.norm(pa)
    pb_norm = pb / np.linalg.norm(pb)
    pc_norm = pc / np.linalg.norm(pc)

    # Spherical triangle formula (L'Huilier's theorem)
    numerator = np.dot(pa_norm, np.cross(pb_norm, pc_norm))
    denominator = (1 + np.dot(pa_norm, pb_norm) +
                   np.dot(pb_norm, pc_norm) +
                   np.dot(pc_norm, pa_norm))

    omega = 2 * np.arctan2(numerator, denominator)

    return omega
```

### Flatness Energy

Penalize deviation from flat configuration:

```python
def flatness_energy(positions, triangles):
    """
    Compute flatness energy for all vertices

    Args:
        positions: [N, 3] array of vertex positions
        triangles: List of triangle face indices

    Returns:
        Total flatness energy
    """
    energy = 0.0

    # For each vertex
    for vertex_idx in range(len(positions)):
        # Find triangles adjacent to this vertex
        adjacent_triangles = get_adjacent_triangles(vertex_idx, triangles)

        # Compute total solid angle
        total_solid_angle = 0.0
        for tri in adjacent_triangles:
            a, b, c = tri
            omega = solid_angle_triangle(
                positions[vertex_idx],
                positions[a],
                positions[b],
                positions[c]
            )
            total_solid_angle += omega

        # Target: 2π for flat interior vertex
        # For boundary vertices, target depends on number of neighbors
        target_angle = 2 * np.pi

        # Penalize deviation
        deviation = total_solid_angle - target_angle
        energy += deviation ** 2

    return energy
```

### PyTorch Implementation

For gradient-based optimization:

```python
import torch

def solid_angle_triangle_torch(p, a, b, c):
    """
    PyTorch version of solid angle calculation

    Args:
        p: [3] tensor - observer point
        a, b, c: [3] tensors - triangle vertices

    Returns:
        Solid angle (scalar tensor)
    """
    # Vectors from p to vertices
    pa = a - p
    pb = b - p
    pc = c - p

    # Normalize
    pa_norm = pa / torch.norm(pa)
    pb_norm = pb / torch.norm(pb)
    pc_norm = pc / torch.norm(pc)

    # Cross product and dot products
    cross_prod = torch.cross(pb_norm, pc_norm)
    numerator = torch.dot(pa_norm, cross_prod)

    denominator = (1 + torch.dot(pa_norm, pb_norm) +
                   torch.dot(pb_norm, pc_norm) +
                   torch.dot(pc_norm, pa_norm))

    # Avoid division by zero
    denominator = torch.clamp(denominator, min=1e-6)

    omega = 2 * torch.atan2(numerator, denominator)

    return omega


class SolidAngleFlatnessModel:
    """
    Solid angle-based flatness enforcement
    """

    def __init__(self, triangles, weight=1.0):
        """
        Args:
            triangles: List of [a, b, c] triangle indices
            weight: Weight of flatness term in loss function
        """
        self.triangles = triangles
        self.weight = weight

        # Precompute adjacency structure
        self.vertex_to_triangles = self._build_adjacency(triangles)

    def _build_adjacency(self, triangles):
        """Build map from vertex index to adjacent triangles"""
        vertex_to_tris = {}

        for tri_idx, (a, b, c) in enumerate(triangles):
            for vertex in [a, b, c]:
                if vertex not in vertex_to_tris:
                    vertex_to_tris[vertex] = []
                vertex_to_tris[vertex].append(tri_idx)

        return vertex_to_tris

    def flatness_energy(self, positions):
        """
        Compute flatness energy using solid angles

        Args:
            positions: [N, 3] tensor of vertex positions

        Returns:
            Energy (scalar tensor)
        """
        energy = torch.tensor(0.0)

        for vertex_idx, tri_indices in self.vertex_to_triangles.items():
            # Skip boundary vertices (different target angle)
            if len(tri_indices) < 3:
                continue

            # Compute total solid angle at this vertex
            total_solid_angle = torch.tensor(0.0)

            for tri_idx in tri_indices:
                a, b, c = self.triangles[tri_idx]
                p = positions[vertex_idx]

                # Get other two vertices of triangle (not vertex_idx)
                tri_verts = [a, b, c]
                tri_verts.remove(vertex_idx)
                v1, v2 = tri_verts

                omega = solid_angle_triangle_torch(
                    p,
                    positions[v1],
                    positions[v2],
                    positions[vertex_idx]  # Third point (closes triangle)
                )

                total_solid_angle += omega

            # Target for flat interior vertex
            target = 2 * torch.pi

            # Penalize deviation
            deviation = total_solid_angle - target
            energy += self.weight * deviation ** 2

        return energy
```

## Integration with Layout Optimizer

### 1. Mesh Construction from Graph

Add method to `YarnLayoutOptimizer`:

```python
def _build_mesh_triangles(self):
    """
    Construct triangular mesh from graph edges

    For regular grid-like knitting patterns, triangulate by:
    - Finding quads (4-cycles)
    - Splitting each quad into 2 triangles
    """
    # Find all quadrilaterals in graph
    quads = find_quadrilaterals(self.adjacency_matrix)

    triangles = []
    for a, b, c, d in quads:
        # Split quad into two triangles
        triangles.append([a, b, c])
        triangles.append([a, c, d])

    return triangles
```

### 2. Add to Loss Function

```python
def compute_loss(self):
    """Compute total loss with flatness term"""

    # Existing terms
    edge_energy = self.force_model.total_edge_energy(...)
    repulsion_energy = self.repulsion_model.repulsion_energy(...)

    # NEW: Solid angle flatness
    if self.config.use_solid_angle_flatness:
        flatness_energy = self.flatness_model.flatness_energy(self.positions)
    else:
        flatness_energy = 0.0

    total_loss = edge_energy + repulsion_energy + flatness_energy

    return total_loss
```

### 3. Configuration Parameters

Add to `LayoutConfig`:

```python
class LayoutConfig:
    def __init__(self):
        # ... existing parameters ...

        # Solid angle flatness
        self.use_solid_angle_flatness = False
        self.flatness_weight = 1.0
        self.flatness_target_angle = 2 * np.pi  # For interior vertices
```

## Advantages Over Topology Repulsion

1. **Physically Meaningful**: Directly models fabric's preference for flatness
2. **No Arbitrary Repulsion Radius**: Flatness is intrinsic property
3. **Handles Complex Geometries**: Works for non-planar fabric (hats, socks)
4. **Differentiable**: Smooth gradients for optimization

## Challenges & Solutions

### Challenge 1: Mesh Construction

**Problem**: Knitting graphs are not always regular grids.

**Solution**:
- Use Delaunay triangulation for irregular patterns
- Or constrained triangulation respecting edge structure
- Library: `scipy.spatial.Delaunay` or `triangle` package

### Challenge 2: Boundary Vertices

**Problem**: Boundary vertices don't have 2π solid angle in flat config.

**Solution**:
- Compute expected solid angle based on number of neighbors
- For boundary with k neighbors: target ≈ π (half-space)
- Or exclude boundary vertices from flatness penalty

### Challenge 3: Non-Planar Fabric

**Problem**: Some knitting (hats, socks) is inherently 3D.

**Solution**:
- Make flatness penalty **adaptive**:
  - Strong for stockinette (wants to be flat)
  - Weak for shaping regions (increases/decreases)
- Detect curvature intent from pattern structure
- Or let user specify "flat" vs "shaped" regions

### Challenge 4: Computational Cost

**Problem**: Solid angle calculation is more expensive than simple repulsion.

**Solution**:
- Vectorize calculations using PyTorch
- Use sparse adjacency structure (only local triangles)
- Hierarchical optimization: coarse → fine

## Implementation Timeline

### Phase 1: Basic Solid Angle (2-3 days)
- Implement `solid_angle_triangle_torch()`
- Test on simple planar meshes
- Verify gradient correctness

### Phase 2: Mesh Construction (3-5 days)
- Implement quad detection for grid patterns
- Triangulation for irregular patterns
- Test on various knitting patterns

### Phase 3: Integration (2-3 days)
- Add to `YarnLayoutOptimizer`
- Tune weight parameter
- Compare with topology repulsion

### Phase 4: Validation (3-5 days)
- Test on complex patterns (lace, cables)
- Compare with real fabric photos
- Performance optimization

## References

1. **Solid Angle Calculation**:
   - Van Oosterom & Strackee (1983) - "The Solid Angle of a Plane Triangle"
   - L'Huilier's Theorem for spherical triangles

2. **Mesh Processing**:
   - Botsch et al. - "Polygon Mesh Processing" (textbook)
   - `trimesh` Python library documentation

3. **Discrete Differential Geometry**:
   - Crane - "Discrete Differential Geometry: An Applied Introduction"
   - Meyer et al. - "Discrete Differential-Geometry Operators for Triangulated 2-Manifolds"

## Testing Strategy

### Unit Tests

```python
def test_solid_angle_flat_triangle():
    """Test solid angle for triangle in plane"""
    p = torch.tensor([0., 0., 1.])  # Above triangle
    a = torch.tensor([1., 0., 0.])
    b = torch.tensor([0., 1., 0.])
    c = torch.tensor([-1., 0., 0.])

    omega = solid_angle_triangle_torch(p, a, b, c)

    # Should be positive and less than 2π
    assert omega > 0
    assert omega < 2 * np.pi


def test_flatness_planar_mesh():
    """Test that planar mesh has near-zero flatness energy"""
    # Create planar grid
    positions = create_planar_grid(4, 4)
    triangles = triangulate_grid(4, 4)

    model = SolidAngleFlatnessModel(triangles)
    energy = model.flatness_energy(positions)

    # Should be near zero for planar configuration
    assert energy < 1e-3
```

### Integration Tests

- Compare layouts with/without solid angle term
- Verify that fabric becomes flatter with higher weight
- Test on non-planar patterns (should still work)

## Future Enhancements

1. **Gaussian Curvature**: Use solid angle deficit to compute discrete Gaussian curvature
2. **Mean Curvature Flow**: Smooth surface using curvature-based energy
3. **Minimal Surfaces**: Find minimal-energy fabric shapes
4. **Stress Analysis**: Combine with material mechanics for stress visualization

## Conclusion

Solid angle-based flatness enforcement provides a **physically principled** alternative to arbitrary repulsion forces. It directly models the geometric preference of knitted fabric and should produce more realistic layouts, especially for complex patterns with shaping.

Implementation requires careful handling of mesh construction and boundary conditions, but the mathematical foundation is well-established and the gradient computation is straightforward in PyTorch.
