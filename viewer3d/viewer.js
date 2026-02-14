/**
 * WoolyGraphs 3D Viewer
 * Three.js-based visualization for knitting patterns
 */

import { ElasticSheetLayout } from './layout-engine.js';

export class WoolyGraphViewer {
    constructor(containerId, THREE, OrbitControls) {
        console.log("Initializing WoolyGraphViewer...");

        this.THREE = THREE;
        this.container = document.getElementById(containerId);

        if (!this.container) {
            console.error(`Container ${containerId} not found!`);
            return;
        }

        // Scene setup
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x1a1a2e);

        // Camera setup
        this.camera = new THREE.PerspectiveCamera(
            75,
            window.innerWidth / window.innerHeight,
            0.1,
            1000
        );
        this.camera.position.set(10, 10, 10);
        this.camera.lookAt(0, 0, 0);

        // Renderer setup
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.container.appendChild(this.renderer.domElement);

        console.log("Renderer created");

        // Controls
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;

        console.log("OrbitControls initialized");

        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        this.scene.add(ambientLight);

        const directionalLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight1.position.set(10, 10, 10);
        this.scene.add(directionalLight1);

        const directionalLight2 = new THREE.DirectionalLight(0xffffff, 0.4);
        directionalLight2.position.set(-10, -10, -10);
        this.scene.add(directionalLight2);

        // Graph data and layout
        this.graph = null;
        this.layout = null;

        // Visual groups
        this.nodeGroup = new THREE.Group();
        this.yarnGroup = new THREE.Group();
        this.edgeGroup = new THREE.Group();

        this.scene.add(this.nodeGroup);
        this.scene.add(this.yarnGroup);
        this.scene.add(this.edgeGroup);

        // Settings
        this.showYarn = true;
        this.showNodes = true;
        this.autoRotate = false;

        // Window resize handler
        window.addEventListener('resize', () => this.onWindowResize(), false);

        // Start animation
        this.animate();

        console.log("WoolyGraphViewer initialized successfully");
    }

    loadGraph(graphData) {
        console.log("Loading graph data:", graphData);

        if (!graphData.nodes || !graphData.edges) {
            console.error("Invalid graph data: missing nodes or edges");
            return;
        }

        this.graph = graphData;

        console.log(`Graph loaded: ${graphData.nodes.length} nodes, ${graphData.edges.length} edges`);

        // Create layout engine
        this.layout = new ElasticSheetLayout(this.graph, {
            springStrength: 0.01,
            springRestLength: 1.0,
            repulsionStrength: 50.0,
            damping: 0.95
        });

        // Update visuals
        this.updateVisuals();
        this.updateStats();

        // Center camera on graph
        this.centerCamera();

        console.log("Graph visualization complete");
    }

    updateVisuals() {
        if (!this.graph || !this.layout) {
            console.warn("No graph or layout to visualize");
            return;
        }

        console.log("Updating visuals...");

        // Clear existing
        this.clearGroup(this.nodeGroup);
        this.clearGroup(this.yarnGroup);
        this.clearGroup(this.edgeGroup);

        const positions = this.layout.getPositions();
        console.log("Got positions for", Object.keys(positions).length, "nodes");

        // Create nodes
        if (this.showNodes) {
            this.createNodes(positions);
        }

        // Create edges/yarn
        if (this.showYarn) {
            this.createYarnTubes(positions);
        } else {
            this.createSimpleEdges(positions);
        }

        console.log("Visuals updated");
    }

    createNodes(positions) {
        const geometry = new this.THREE.SphereGeometry(0.15, 16, 16);
        const material = new this.THREE.MeshPhongMaterial({
            color: 0x4ecdc4,
            emissive: 0x2a7a74,
            shininess: 30
        });

        let nodeCount = 0;
        this.graph.nodes.forEach(node => {
            const pos = positions[node.id];
            if (!pos) {
                console.warn(`No position for node ${node.id}`);
                return;
            }

            const mesh = new this.THREE.Mesh(geometry, material);
            mesh.position.set(pos.x, pos.y, pos.z);
            this.nodeGroup.add(mesh);
            nodeCount++;
        });

        console.log(`Created ${nodeCount} node spheres`);
    }

    createYarnTubes(positions) {
        let tubeCount = 0;

        this.graph.edges.forEach(edge => {
            const pos1 = positions[edge.source];
            const pos2 = positions[edge.target];

            if (!pos1 || !pos2) {
                console.warn(`Missing position for edge ${edge.source}-${edge.target}`);
                return;
            }

            // Create curved path
            const start = new this.THREE.Vector3(pos1.x, pos1.y, pos1.z);
            const end = new this.THREE.Vector3(pos2.x, pos2.y, pos2.z);

            // Midpoint with slight curve
            const mid = new this.THREE.Vector3()
                .addVectors(start, end)
                .multiplyScalar(0.5);

            const dir = new this.THREE.Vector3().subVectors(end, start);
            const perpendicular = new this.THREE.Vector3(-dir.y, dir.x, 0).normalize();
            mid.add(perpendicular.multiplyScalar(dir.length() * 0.05));

            // Create curve
            const curve = new this.THREE.QuadraticBezierCurve3(start, mid, end);

            // Tube geometry
            const tubeGeometry = new this.THREE.TubeGeometry(
                curve,
                20,    // segments
                0.05,  // radius
                8,     // radial segments
                false
            );

            // Color by orientation
            let color = 0xff6b6b;
            if (edge.orientation === 'h') {
                color = 0x4ecdc4; // cyan
            } else if (edge.orientation === 'v') {
                color = 0xffe66d; // yellow
            }

            const material = new this.THREE.MeshPhongMaterial({
                color: color,
                emissive: color,
                emissiveIntensity: 0.2,
                shininess: 30
            });

            const mesh = new this.THREE.Mesh(tubeGeometry, material);
            this.yarnGroup.add(mesh);
            tubeCount++;
        });

        console.log(`Created ${tubeCount} yarn tubes`);
    }

    createSimpleEdges(positions) {
        let edgeCount = 0;

        this.graph.edges.forEach(edge => {
            const pos1 = positions[edge.source];
            const pos2 = positions[edge.target];

            if (!pos1 || !pos2) return;

            const geometry = new this.THREE.BufferGeometry().setFromPoints([
                new this.THREE.Vector3(pos1.x, pos1.y, pos1.z),
                new this.THREE.Vector3(pos2.x, pos2.y, pos2.z)
            ]);

            const color = edge.orientation === 'h' ? 0x4ecdc4 : 0xffe66d;
            const material = new this.THREE.LineBasicMaterial({ color: color });

            const line = new this.THREE.Line(geometry, material);
            this.edgeGroup.add(line);
            edgeCount++;
        });

        console.log(`Created ${edgeCount} edge lines`);
    }

    clearGroup(group) {
        while (group.children.length > 0) {
            const child = group.children[0];
            if (child.geometry) child.geometry.dispose();
            if (child.material) child.material.dispose();
            group.remove(child);
        }
    }

    runSimulation(iterations = 100) {
        if (!this.layout) {
            console.warn("No layout to simulate");
            return;
        }

        console.log(`Running ${iterations} simulation iterations...`);

        let remaining = iterations;
        const step = () => {
            if (remaining > 0) {
                this.layout.step();
                remaining--;

                // Update every 10 iterations
                if (remaining % 10 === 0) {
                    this.updateVisuals();
                    this.updateStats();
                }

                requestAnimationFrame(step);
            } else {
                this.updateVisuals();
                this.updateStats();
                console.log("Simulation complete");
            }
        };

        step();
    }

    resetLayout() {
        if (!this.layout) return;

        console.log("Resetting layout");
        this.layout.initializePositions();
        this.updateVisuals();
        this.updateStats();
    }

    centerCamera() {
        if (!this.layout) return;

        // Calculate bounding box of nodes
        const positions = this.layout.getPositions();
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

        Object.values(positions).forEach(pos => {
            minX = Math.min(minX, pos.x);
            minY = Math.min(minY, pos.y);
            minZ = Math.min(minZ, pos.z);
            maxX = Math.max(maxX, pos.x);
            maxY = Math.max(maxY, pos.y);
            maxZ = Math.max(maxZ, pos.z);
        });

        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;
        const centerZ = (minZ + maxZ) / 2;

        const sizeX = maxX - minX;
        const sizeY = maxY - minY;
        const size = Math.max(sizeX, sizeY, 10);

        this.camera.position.set(
            centerX + size,
            centerY + size,
            centerZ + size
        );
        this.camera.lookAt(centerX, centerY, centerZ);
        this.controls.target.set(centerX, centerY, centerZ);
    }

    updateStats() {
        if (!this.graph) return;

        document.getElementById('node-count').textContent = this.graph.nodes.length;
        document.getElementById('edge-count').textContent = this.graph.edges.length;
        document.getElementById('energy').textContent = this.layout ? this.layout.energy.toFixed(2) : '0';
    }

    onWindowResize() {
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(window.innerWidth, window.innerHeight);
    }

    animate() {
        requestAnimationFrame(() => this.animate());

        if (this.autoRotate) {
            this.scene.rotation.y += 0.005;
        }

        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    setShowYarn(show) {
        this.showYarn = show;
        this.yarnGroup.visible = show;
        this.edgeGroup.visible = !show;
        console.log(`Yarn tubes: ${show ? 'visible' : 'hidden'}`);
    }

    setShowNodes(show) {
        this.showNodes = show;
        this.nodeGroup.visible = show;
        console.log(`Nodes: ${show ? 'visible' : 'hidden'}`);
    }

    setAutoRotate(rotate) {
        this.autoRotate = rotate;
        console.log(`Auto-rotate: ${rotate ? 'on' : 'off'}`);
    }

    setLayoutParameter(name, value) {
        if (this.layout) {
            this.layout.setParameter(name, value);
        }
    }
}
