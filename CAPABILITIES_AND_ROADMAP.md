# WoolyGraphs: Capabilities & Roadmap

## Current Capabilities

```mermaid
graph TD
    Root[WoolyGraphs Suite]
    
    subgraph Core["1. Core Engine (knit.py)"]
        Root --> Core
        P1[Pattern Parsing] --- P1a[Support for .txt patterns]
        P1 --- P1b[Stitch definitions from stitches.txt]
        P2[Graph Generation] --- P2a[Stitch-to-node mapping]
        P2 --- P2b[Adjacency matrix generation]
        P3[Initial Layout] --- P3a[Row/Column geography]
        P3 --- P3b[Physical gauge-aware spacing]
        Core --> P1
        Core --> P2
        Core --> P3
    end
    
    subgraph Opt["2. Layout Optimization (optimize_layout.py)"]
        Root --> Opt
        O1[Optimizer] --- O1a[PyTorch + ADAM]
        O2[Yarn Mechanics] --- O2a[forces.py: Custom force curves]
        O2 --- O2b[Elastic & Plastic regions]
        O2 --- O2c[Physical constants mm/tension]
        O3[Repulsion] --- O3a[Topology-local repulsion]
        O3 --- O3b[Matrix Power-based A^k]
        Opt --> O1
        Opt --> O2
        Opt --> O3
    end
    
    subgraph Vis["3. Visualization & Export"]
        Root --> Vis
        V1[Data Export] --- V1a[JSON schema for nodes/edges]
        V2[3D Viewer] --- V2a[viewer3d: Three.js web interface]
        V2 --- V2b[Interactive node layout]
        V3[Analysis] --- V3a[Loss history plotting]
        V3 --- V3b[Layout comparison tools]
        Vis --> V1
        Vis --> V2
        Vis --> V3
    end
```

### Detailed Functional Breakdown

- **Pattern Conversion**:
    - Translates knitting-specific logic (knit, purl, increases, decreases) into a mathematical graph.
    - Handles complex topologies like lace and short rows.
- **Physical Simulation**:
    - Models yarn as a spring-like system with non-linear forces.
    - Vertices repel each other within a topological neighborhood to prevent collapse.
- **High-Performance Optimization**:
    - Leverages automatic differentiation (PyTorch) for fast convergence.
    - Scalable repulsion calculations compared to naive $O(N^2)$ approaches.
- **Web-Based Visualization**:
    - Cross-platform 3D rendering of the resulting fabric structure.

---

## Project Roadmap

The following roadmap is synthesized from the latest project planning documents and `TODO.org`.

### Phase 1: Mathematical Foundations (High Priority)
- [ ] **Solid Angle Flatness**: Implement geometric flatness enforcement to replace topological repulsion.
    - *Goal*: Better physical realism and support for complex 3D shapes.
- [ ] **Improved Initial Positioning**: Enhancing `knit.py` to handle increases/decreases more naturally in the initial X-Y plane.

### Phase 2: Advanced Pattern Programming
- [ ] **Sauron's Southern Gaze**: Program and simulate the complex "Southern Gaze" pattern.
- [ ] **Northern Hemisphere**: Program and simulate the "Northern Hemisphere" pattern.

### Phase 3: Physical Refinement & Mechanics
- [ ] **Gauge Awareness**: Full support for yarn weight and needle size impact on rest lengths and forces.
- [ ] **Stitch-Specific Forces**:
    - Custom constraints for Cables (cross-overs).
    - Compression behavior for Ribbing.
    - High-elasticity modeling for Yarnovers.

### Phase 4: Complex Geometry & 3D Shaping
- [ ] **Non-Planar Support**: Improved optimization for inherently 3D items (hats, socks, sleeves).
- [ ] **Periodic Boundaries**: Support for circular knitting (connecting left/right edges).

### Phase 5: Tooling & Analysis
- [ ] **Tension Heatmaps**: Color edges in the 3D viewer based on their deviation from rest length.
- [ ] **Optimization Animation**: Record and display the "knitting-into-shape" process.
- [ ] **STL Export**: Export the underlying structure for 3D printing.

---

*Last Updated: 2026-02-05*
