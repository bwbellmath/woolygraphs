/**
 * WoolyGraphs Elastic Sheet Layout Engine
 *
 * Physics-based graph layout using spring forces and repulsion
 */

export class ElasticSheetLayout {
    constructor(graph, options = {}) {
        console.log("Initializing ElasticSheetLayout with graph:", graph);

        this.graph = graph;

        // Physics parameters
        this.springStrength = options.springStrength || 0.01;
        this.springRestLength = options.springRestLength || 1.0;
        this.repulsionStrength = options.repulsionStrength || 50.0;
        this.damping = options.damping || 0.95;
        this.timeStep = options.timeStep || 0.1;

        // Node state
        this.positions = new Map();
        this.velocities = new Map();
        this.forces = new Map();

        // Simulation state
        this.running = false;
        this.iteration = 0;
        this.energy = 0;

        this.initializePositions();

        console.log(`Layout initialized with ${this.positions.size} nodes`);
    }

    initializePositions() {
        // Initialize nodes in a grid layout
        const n = this.graph.nodes.length;
        const gridSize = Math.ceil(Math.sqrt(n));

        console.log(`Initializing ${n} nodes in ${gridSize}x${gridSize} grid`);

        this.graph.nodes.forEach((node, index) => {
            const row = Math.floor(index / gridSize);
            const col = index % gridSize;

            this.positions.set(node.id, {
                x: (col - gridSize / 2) * 2,
                y: (row - gridSize / 2) * 2,
                z: 0
            });

            this.velocities.set(node.id, { x: 0, y: 0, z: 0 });
            this.forces.set(node.id, { x: 0, y: 0, z: 0 });
        });
    }

    resetForces() {
        this.graph.nodes.forEach(node => {
            this.forces.set(node.id, { x: 0, y: 0, z: 0 });
        });
    }

    applySpringForces() {
        // Spring forces between connected nodes
        this.graph.edges.forEach(edge => {
            const pos1 = this.positions.get(edge.source);
            const pos2 = this.positions.get(edge.target);

            if (!pos1 || !pos2) {
                console.warn(`Missing position for edge ${edge.source}-${edge.target}`);
                return;
            }

            const dx = pos2.x - pos1.x;
            const dy = pos2.y - pos1.y;
            const dz = pos2.z - pos1.z;

            const distance = Math.sqrt(dx*dx + dy*dy + dz*dz) || 0.001;

            const restLength = this.springRestLength * (edge.weight || 1.0);
            const forceMagnitude = this.springStrength * (distance - restLength);

            const fx = (dx / distance) * forceMagnitude;
            const fy = (dy / distance) * forceMagnitude;
            const fz = (dz / distance) * forceMagnitude;

            const force1 = this.forces.get(edge.source);
            const force2 = this.forces.get(edge.target);

            force1.x += fx;
            force1.y += fy;
            force1.z += fz;

            force2.x -= fx;
            force2.y -= fy;
            force2.z -= fz;
        });
    }

    applyRepulsionForces() {
        // Universal repulsion between all node pairs
        const nodes = this.graph.nodes;

        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const node1 = nodes[i];
                const node2 = nodes[j];

                const pos1 = this.positions.get(node1.id);
                const pos2 = this.positions.get(node2.id);

                const dx = pos2.x - pos1.x;
                const dy = pos2.y - pos1.y;
                const dz = pos2.z - pos1.z;

                const distanceSq = dx*dx + dy*dy + dz*dz || 0.001;
                const distance = Math.sqrt(distanceSq);

                const forceMagnitude = this.repulsionStrength / distanceSq;

                const fx = (dx / distance) * forceMagnitude;
                const fy = (dy / distance) * forceMagnitude;
                const fz = (dz / distance) * forceMagnitude;

                const force1 = this.forces.get(node1.id);
                const force2 = this.forces.get(node2.id);

                force1.x -= fx;
                force1.y -= fy;
                force1.z -= fz;

                force2.x += fx;
                force2.y += fy;
                force2.z += fz;
            }
        }
    }

    updatePositions() {
        let totalEnergy = 0;

        this.graph.nodes.forEach(node => {
            const pos = this.positions.get(node.id);
            const vel = this.velocities.get(node.id);
            const force = this.forces.get(node.id);

            if (node.frozen) return;

            vel.x += force.x * this.timeStep;
            vel.y += force.y * this.timeStep;
            vel.z += force.z * this.timeStep;

            vel.x *= this.damping;
            vel.y *= this.damping;
            vel.z *= this.damping;

            pos.x += vel.x * this.timeStep;
            pos.y += vel.y * this.timeStep;
            pos.z += vel.z * this.timeStep;

            const speedSq = vel.x*vel.x + vel.y*vel.y + vel.z*vel.z;
            totalEnergy += speedSq;
        });

        this.energy = totalEnergy;
    }

    step() {
        this.resetForces();
        this.applySpringForces();
        this.applyRepulsionForces();
        this.updatePositions();
        this.iteration++;

        return this.energy;
    }

    runIterations(count) {
        for (let i = 0; i < count; i++) {
            this.step();
        }
    }

    getPositions() {
        const result = {};
        this.positions.forEach((pos, id) => {
            result[id] = { ...pos };
        });
        return result;
    }

    setParameter(name, value) {
        if (name === 'springStrength') this.springStrength = value;
        else if (name === 'repulsionStrength') this.repulsionStrength = value;
        else if (name === 'damping') this.damping = value;
        else if (name === 'springRestLength') this.springRestLength = value;

        console.log(`Set ${name} = ${value}`);
    }
}
