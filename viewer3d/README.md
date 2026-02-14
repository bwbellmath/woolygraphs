# WoolyGraphs 3D Viewer

Interactive 3D visualization of knitting patterns using Three.js and elastic sheet physics.

## Quick Start

### 1. Start the Server

```bash
cd viewer3d
python -m http.server 8000
```

### 2. Open in Browser

Navigate to: **http://localhost:8000**

### 3. Load a Pattern

The viewer will show a dropdown with available patterns. Select one to load it automatically.

Or use the file upload to load any JSON graph file.

## What You Should See

When working correctly, you should see:

1. **A black canvas** filling the browser window
2. **Colored spheres** (nodes/stitches) arranged in a grid
3. **Colored tubes** connecting the spheres:
   - **Cyan tubes** = horizontal connections (within row)
   - **Yellow tubes** = vertical connections (between rows)
4. **Control panel** on the left with sliders and buttons
5. **Stats** at the bottom showing node/edge counts

## Controls

### Mouse Controls
- **Left drag**: Rotate camera
- **Right drag**: Pan camera
- **Scroll**: Zoom in/out

### Physics Parameters
- **Spring Strength**: How strongly edges pull nodes together
- **Repulsion**: How strongly nodes push apart
- **Damping**: How quickly motion slows down

### Actions
- **Reset Layout**: Return to initial grid positions
- **Run Simulation**: Execute 100 physics iterations to optimize layout

### Checkboxes
- **Show Yarn Tubes**: Toggle curved 3D tubes (realistic yarn)
- **Show Nodes**: Toggle node spheres visibility
- **Auto Rotate**: Slowly rotate the view automatically

## Troubleshooting

### Nothing Displays / Blank Screen

1. **Open Browser Console** (F12 or right-click → Inspect → Console)
   - Look for error messages
   - Should see: "Starting WoolyGraphs 3D Viewer..."
   - Should see: "Three.js loaded successfully"
   - Should see: "Viewer initialized successfully"

2. **Check the Network Tab**
   - Make sure all files loaded (index.html, viewer.js, layout-engine.js)
   - Make sure Three.js CDN loaded successfully
   - Check that data JSON files load without 404 errors

3. **Common Issues**:

   **"Failed to load module script"**
   - You must use a local server (http://localhost:8000)
   - Opening index.html directly as a file (file://) will NOT work due to CORS

   **"THREE is not defined"**
   - Three.js CDN may be blocked
   - Check browser console for specific CDN error
   - Try a different browser

   **"Cannot read property 'nodes' of undefined"**
   - JSON file failed to load or is malformed
   - Check the pattern file exists in data/
   - Validate JSON syntax

   **Canvas exists but nothing renders**
   - Check console for WebGL errors
   - Update graphics drivers
   - Try a different browser (Chrome/Firefox recommended)

### Pattern Loads But Looks Wrong

1. **All nodes in one spot**:
   - Click "Reset Layout" to initialize positions
   - Then "Run Simulation" to optimize

2. **Can't see anything**:
   - Zoom out (scroll wheel)
   - Click "Reset Layout"
   - Camera may be inside the graph

3. **Edges but no tubes**:
   - Check "Show Yarn Tubes" checkbox
   - If still lines, check console for geometry errors

## File Structure

```
viewer3d/
├── index.html          # Main HTML page with UI
├── viewer.js           # Three.js visualization code
├── layout-engine.js    # Physics simulation
├── data/              # Graph data files
│   ├── patterns.json  # Index of available patterns
│   ├── test_pattern.json
│   ├── large_pattern.json
│   └── small_stockinette.json
└── README.md          # This file
```

## Data Format

JSON files should have this structure:

```json
{
  "metadata": {
    "pattern": "pattern_name",
    "nodeCount": 20,
    "edgeCount": 31
  },
  "nodes": [
    { "id": 0, "label": "stitch_0" },
    { "id": 1, "label": "stitch_1" }
  ],
  "edges": [
    {
      "source": 0,
      "target": 1,
      "weight": 1.0,
      "orientation": "h"
    }
  ]
}
```

### Edge Orientations
- `"h"` = horizontal (cyan) - stitches in same row
- `"v"` = vertical (yellow) - stitches in different rows

## Creating New Patterns

### From CSV Adjacency Matrix

```bash
# From woolygraphs root directory
python export_to_json.py matrices/your_pattern.csv viewer3d/data/your_pattern.json
```

### Programmatically

See `export_to_json.py` for examples of creating patterns programmatically.

## Browser Compatibility

**Recommended**: Chrome, Firefox, Edge (latest versions)

**Required**:
- ES6 module support
- WebGL support
- Import maps support

**Not Supported**:
- Internet Explorer
- Very old browsers (pre-2020)

## Performance Tips

For large graphs (>100 nodes):

1. **Disable repulsion** (set slider to 0) - repulsion is O(n²)
2. **Use simple edges** instead of yarn tubes
3. **Hide nodes** if only interested in structure
4. **Update less frequently** during simulation

## Debug Mode

To see detailed logging, open browser console (F12). The viewer logs:
- Initialization steps
- Graph loading progress
- Node/edge creation counts
- Physics parameter changes
- Simulation progress

## Next Steps

Once the basic viewer works:

1. Run physics simulation to optimize layout
2. Adjust spring/repulsion to get desired structure
3. Try different patterns
4. Export layouts for documentation
5. Customize colors/materials in viewer.js
6. Add new physics forces in layout-engine.js

## Getting Help

If you're still having issues:

1. Check all console messages
2. Verify server is running on port 8000
3. Ensure data/ folder has JSON files
4. Try the simplest test pattern first
5. Disable browser extensions that might block CDNs
6. Try in incognito/private mode

## Technical Details

### Physics Engine

The layout uses a force-directed algorithm:
- **Spring forces**: Pull connected nodes together
- **Repulsion forces**: Push all nodes apart
- **Damping**: Stabilizes the system

### Rendering

- **Three.js**: WebGL-based 3D graphics
- **Tube geometry**: Curved Bezier paths for realistic yarn
- **Phong shading**: Lighting and material effects
- **OrbitControls**: Camera manipulation

### Performance

- Repulsion: O(n²) in number of nodes
- Springs: O(e) in number of edges
- Rendering: O(n + e) geometries
- 60 FPS target for <1000 nodes
