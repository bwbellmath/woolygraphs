import * as THREE from "three";

const DATA = new URLSearchParams(location.search).get("data")
  ?? "data/small_cubes_layout.json";

const COLOR_WHITE = new THREE.Color("#e9e5da");
const COLOR_BLUE = new THREE.Color("#2f76c4");
const COLOR_DEC = new THREE.Color("#ff5c49");
const COLOR_INC = new THREE.Color("#ffd23f");
const COLOR_YARN = new THREE.Color("#7d8494");
const COLOR_COL = new THREE.Color("#4a5160");
const SYNTH_FADE = 0.45; // darken synthesized crown rounds

let d;
try {
  d = await (await fetch(DATA)).json();
} catch (e) {
  const err = document.getElementById("err");
  err.style.display = "grid";
  err.textContent = `could not load ${DATA} — run \`make small_cubes\` first (${e})`;
  throw e;
}

// ---------- scene ----------
const canvas = document.getElementById("canvas");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color("#14161a");
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 200);

scene.add(new THREE.HemisphereLight(0xffffff, 0x30343c, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(4, 8, 6);
scene.add(sun);

// Hat data is z-up; rotate into three.js y-up and center vertically.
const hat = new THREE.Group();
const zMax = Math.max(...d.positions.map((p) => p[2]));
hat.rotation.x = -Math.PI / 2;
hat.position.y = -zMax / 2;
scene.add(hat);

const n = d.n_stitches;
const pos = d.positions;

// ---------- stitches ----------
const sphere = new THREE.SphereGeometry(0.048, 10, 8);
const mat = new THREE.MeshLambertMaterial();
const mesh = new THREE.InstancedMesh(sphere, mat, n);
const m = new THREE.Matrix4();
for (let i = 0; i < n; i++) {
  m.setPosition(pos[i][0], pos[i][1], pos[i][2]);
  mesh.setMatrixAt(i, m);
}
mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3);
hat.add(mesh);

function paint(showShaping) {
  const c = new THREE.Color();
  for (let i = 0; i < n; i++) {
    if (showShaping && d.decrease_flag[i]) c.copy(COLOR_DEC);
    else if (showShaping && d.increase_flag[i]) c.copy(COLOR_INC);
    else c.copy(d.colors[i] ? COLOR_BLUE : COLOR_WHITE);
    if (d.synthesized[i]) c.multiplyScalar(SYNTH_FADE);
    mesh.setColorAt(i, c);
  }
  mesh.instanceColor.needsUpdate = true;
}

// ---------- yarn spiral & column edges ----------
// Edges are instanced cylinders (WebGL ignores line width): thick,
// near-black, semi-transparent, so the near side of the hat occludes
// the far side instead of both blending into visual noise.
const EDGE_RADIUS = 0.016;
const edgeGeo = new THREE.CylinderGeometry(1, 1, 1, 5, 1, true);
const edgeMat = new THREE.MeshBasicMaterial({
  color: 0x04060a, transparent: true, opacity: 0.65, depthWrite: true,
});

function edgeMesh(pairs) {
  const em = new THREE.InstancedMesh(edgeGeo, edgeMat, pairs.length);
  hat.add(em);
  return em;
}

const _a = new THREE.Vector3(), _b = new THREE.Vector3();
const _dir = new THREE.Vector3(), _mid = new THREE.Vector3();
const _q = new THREE.Quaternion(), _s = new THREE.Vector3();
const _up = new THREE.Vector3(0, 1, 0);
function setEdgeMatrices(em, pairs) {
  for (let i = 0; i < pairs.length; i++) {
    _a.fromArray(pos[pairs[i][0]]);
    _b.fromArray(pos[pairs[i][1]]);
    _dir.subVectors(_b, _a);
    const len = _dir.length();
    _mid.addVectors(_a, _b).multiplyScalar(0.5);
    _q.setFromUnitVectors(_up, len > 1e-9 ? _dir.divideScalar(len) : _up);
    _s.set(EDGE_RADIUS, Math.max(len, 1e-9), EDGE_RADIUS);
    m.compose(_mid, _q, _s);
    em.setMatrixAt(i, m);
  }
  em.instanceMatrix.needsUpdate = true;
}

const yarnPairs = Array.from({ length: n - 1 }, (_, i) => [i, i + 1]);
const yarnLine = edgeMesh(yarnPairs);
const colLines = edgeMesh(d.column_edges);
setEdgeMatrices(yarnLine, yarnPairs);
setEdgeMatrices(colLines, d.column_edges);

function applyPositions(newPositions) {
  for (let i = 0; i < n; i++) {
    pos[i] = newPositions[i];
    m.makeTranslation(pos[i][0], pos[i][1], pos[i][2]);
    mesh.setMatrixAt(i, m);
  }
  mesh.instanceMatrix.needsUpdate = true;
  setEdgeMatrices(yarnLine, yarnPairs);
  setEdgeMatrices(colLines, d.column_edges);
}

// Per-round prefix sums for the progress slider.
const stitchEnd = [];
let acc = 0;
for (const c of d.stitch_counts) { acc += c; stitchEnd.push(acc); }
const colEdgeEnd = d.stitch_counts.map(() => 0);
d.column_edges.forEach(([a, b]) => {
  colEdgeEnd[Math.max(d.round_index[a], d.round_index[b])]++;
});
for (let r = 1; r < colEdgeEnd.length; r++) colEdgeEnd[r] += colEdgeEnd[r - 1];

// ---------- UI ----------
const $ = (id) => document.getElementById(id);
$("name").textContent = d.name;
$("sub").textContent =
  `${d.horizontal_gauge} st/in × ${d.vertical_gauge} rnd/in · pattern repeat ×${d.repeats}`;
const nSynth = d.n_rounds - d.n_chart_rounds;
$("stats").innerHTML = [
  ["stitches", d.n_stitches.toLocaleString()],
  ["rounds", nSynth ? `${d.n_rounds} (${nSynth} synthesized)` : d.n_rounds],
  ["brim → crown", `${d.stitch_counts[0]} → ${d.stitch_counts.at(-1)}`],
  ["crown starts", `round ${d.crown_start_round + 1}`],
  ["cast-ons", d.increase_flag.filter(Boolean).length],
  ["k2togs", d.decrease_flag.filter(Boolean).length],
].map(([k, v]) => `<div><span>${k}</span><span>${v}</span></div>`).join("");

const slider = $("round");
slider.max = d.n_rounds;
slider.value = d.n_rounds;

function applyRound() {
  const r = +slider.value; // rounds knit so far
  $("roundval").textContent = `${r} / ${d.n_rounds}`;
  mesh.count = stitchEnd[r - 1];
  yarnLine.count = Math.max(stitchEnd[r - 1] - 1, 0);
  colLines.count = colEdgeEnd[r - 1];
}
slider.oninput = applyRound;
$("t_yarn").onchange = (e) => (yarnLine.visible = e.target.checked);
$("t_cols").onchange = (e) => (colLines.visible = e.target.checked);
$("t_dec").onchange = (e) => paint(e.target.checked);
paint(true);

// ---------- smoothing (server-side Adam, background job) ----------
const pNum = (id) => parseFloat($(id).value.replace(/,/g, ""));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let version = 0;
let polling = false;

function showState(st) {
  $("b_opt").disabled = st.running;
  $("b_stop").disabled = !st.running;
  if (st.error) {
    $("optstat").textContent = `error: ${st.error}`;
    return;
  }
  const l = st.last;
  const iter = st.running
    ? `iter ${st.iterations_total} / ${st.target}`
    : st.iterations_total ? `iter ${st.iterations_total}` : "initial layout";
  $("optstat").textContent = l
    ? `${iter} · gauge ${l.gauge.toFixed(4)} · smooth ${l.smooth.toFixed(4)}` +
      ` · total ${l.total.toFixed(4)}`
    : iter;
}

async function refreshState() {
  const res = await fetch(`api/state?version=${version}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const st = await res.json();
  if (st.positions) {
    applyPositions(st.positions);
    version = st.version;
  }
  showState(st);
  return st;
}

async function pollUntilDone() {
  if (polling) return;
  polling = true;
  try {
    while ((await refreshState()).running) await sleep(400);
  } catch (e) {
    $("optstat").textContent =
      "optimizer unavailable — serve with `make small_cubes`";
    console.error(e);
  } finally {
    polling = false;
    $("b_opt").disabled = false;
  }
}

async function post(endpoint, body) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok && res.status !== 409) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

$("b_opt").onclick = async () => {
  $("b_opt").disabled = true;
  try {
    await post("api/optimize", {
      iterations: pNum("p_iters"),
      update_every: pNum("p_every"),
      lr: pNum("p_lr"),
      weights: {
        gauge: pNum("p_wg"),
        inflate: pNum("p_wi"),
        smooth: pNum("p_ws"),
      },
    });
    pollUntilDone();
  } catch (e) {
    $("optstat").textContent =
      "optimizer unavailable — serve with `make small_cubes`";
    $("b_opt").disabled = false;
    console.error(e);
  }
};
$("b_stop").onclick = () => post("api/stop").catch(console.error);
$("b_reset").onclick = async () => {
  try {
    const st = await post("api/reset");
    if (st.positions) {
      applyPositions(st.positions);
      version = st.version;
    }
    showState(st);
  } catch (e) {
    console.error(e);
  }
};

// Sync with any job already running on the server (e.g. after reload).
refreshState().then((st) => st.running && pollUntilDone()).catch(() => {});
applyRound();

// ---------- minimal orbit controls ----------
const target = new THREE.Vector3(0, 0, 0);
let theta = 0.6, phi = 1.15, dist = zMax * 2.2;
function updateCamera() {
  camera.position.set(
    target.x + dist * Math.sin(phi) * Math.sin(theta),
    target.y + dist * Math.cos(phi),
    target.z + dist * Math.sin(phi) * Math.cos(theta));
  camera.lookAt(target);
}
let drag = null;
canvas.addEventListener("pointerdown", (e) => {
  drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (drag.pan) {
    const s = dist * 0.0012;
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
    target.addScaledVector(right, -dx * s).addScaledVector(up, dy * s);
  } else {
    theta -= dx * 0.006;
    phi = Math.min(Math.PI - 0.05, Math.max(0.05, phi - dy * 0.006));
  }
  updateCamera();
});
canvas.addEventListener("pointerup", () => (drag = null));
canvas.addEventListener("contextmenu", (e) => e.preventDefault());
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  dist = Math.min(60, Math.max(0.4, dist * Math.exp(e.deltaY * 0.001)));
  updateCamera();
}, { passive: false });

function resize() {
  renderer.setSize(innerWidth, innerHeight, false);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();
updateCamera();
renderer.setAnimationLoop(() => renderer.render(scene, camera));
