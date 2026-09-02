import * as THREE from "three";
import { ChartGrid, parseCell, COLORS, DECREASE_OPS, INCREASE_OPS } from "./chart.js";
import { defaultParams, guideCells, idealWidths } from "./shaping.js";

const $ = (id) => document.getElementById(id);
const STATIC = new URLSearchParams(location.search).get("data");

const COLOR_DEC = new THREE.Color("#ff5c49");
const COLOR_INC = new THREE.Color("#ffd23f");
const COLOR_HL = new THREE.Color("#ff2fd0");
const SYNTH_FADE = 0.45; // darken synthesized crown rounds
const EDGE_RADIUS = 0.016;

// ---------- palette (fg / bg pickers) ----------
const palette = {
  fg: localStorage.getItem("wg.fg") ?? "#2f76c4",
  bg: localStorage.getItem("wg.bg") ?? "#e9e5da",
};
const paletteColor = [new THREE.Color(palette.bg), new THREE.Color(palette.fg)];
function applyPalette() {
  const root = document.body.style;
  root.setProperty("--fg", palette.fg);
  root.setProperty("--bg", palette.bg);
  const lum = (hex) => { const c = new THREE.Color(hex); return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b; };
  root.setProperty("--fg-text", lum(palette.fg) > 0.5 ? "#222" : "#fff");
  root.setProperty("--bg-text", lum(palette.bg) > 0.5 ? "#222" : "#fff");
  paletteColor[0].set(palette.bg);
  paletteColor[1].set(palette.fg);
  $("sw_fg").style.background = palette.fg;
  $("sw_bg").style.background = palette.bg;
  $("fgcolor").value = palette.fg;
  $("bgcolor").value = palette.bg;
  localStorage.setItem("wg.fg", palette.fg);
  localStorage.setItem("wg.bg", palette.bg);
  if (hat) paint();
}
$("fgcolor").oninput = (e) => { palette.fg = e.target.value; applyPalette(); };
$("bgcolor").oninput = (e) => { palette.bg = e.target.value; applyPalette(); };

// ---------- scene ----------
const canvas = $("canvas");
const view = $("view");
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
const hatGroup = new THREE.Group();
hatGroup.rotation.x = -Math.PI / 2;
scene.add(hatGroup);

const sphereGeo = new THREE.SphereGeometry(0.048, 10, 8);
const stitchMat = new THREE.MeshLambertMaterial();
// Edges are instanced cylinders (WebGL ignores line width): thick,
// near-black, semi-transparent, so the near side of the hat occludes
// the far side instead of both blending into visual noise.
const edgeGeo = new THREE.CylinderGeometry(1, 1, 1, 5, 1, true);
const edgeMat = new THREE.MeshBasicMaterial({
  color: 0x04060a, transparent: true, opacity: 0.65, depthWrite: true,
});

const m = new THREE.Matrix4();
const _a = new THREE.Vector3(), _b = new THREE.Vector3();
const _dir = new THREE.Vector3(), _mid = new THREE.Vector3();
const _q = new THREE.Quaternion(), _s = new THREE.Vector3();
const _up = new THREE.Vector3(0, 1, 0);

let d = null;     // current bundle
let hat = null;   // {mesh, yarnLine, colLines, yarnPairs, stitchEnd, colEdgeEnd, cellIndex}
let highlightCell = null; // "r,c" hovered in the grid
let zMax = 1;
let extent = 1; // max(height, diameter), for framing the camera

function setEdgeMatrices(em, pairs) {
  const pos = d.positions;
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

function disposeHat() {
  if (!hat) return;
  for (const o of [hat.mesh, hat.yarnLine, hat.colLines]) hatGroup.remove(o);
  hat = null;
}

// Build (or rebuild) every scene object from a bundle.
function loadBundle(bundle) {
  disposeHat();
  d = bundle;
  const n = d.n_stitches;
  const pos = d.positions;
  zMax = Math.max(...pos.map((p) => p[2]));
  extent = Math.max(zMax, ...pos.map((p) => 2 * Math.hypot(p[0], p[1])));
  hatGroup.position.y = -zMax / 2;

  const mesh = new THREE.InstancedMesh(sphereGeo, stitchMat, n);
  for (let i = 0; i < n; i++) {
    m.makeTranslation(pos[i][0], pos[i][1], pos[i][2]);
    mesh.setMatrixAt(i, m);
  }
  mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3);
  hatGroup.add(mesh);

  const yarnPairs = Array.from({ length: n - 1 }, (_, i) => [i, i + 1]);
  const yarnLine = new THREE.InstancedMesh(edgeGeo, edgeMat, yarnPairs.length);
  const colLines = new THREE.InstancedMesh(edgeGeo, edgeMat, d.column_edges.length);
  hatGroup.add(yarnLine, colLines);
  yarnLine.visible = $("t_yarn").checked;
  colLines.visible = $("t_cols").checked;

  // Per-round prefix sums for the progress slider.
  const stitchEnd = [];
  let acc = 0;
  for (const c of d.stitch_counts) { acc += c; stitchEnd.push(acc); }
  const colEdgeEnd = d.stitch_counts.map(() => 0);
  d.column_edges.forEach(([a, b]) => {
    colEdgeEnd[Math.max(d.round_index[a], d.round_index[b])]++;
  });
  for (let r = 1; r < colEdgeEnd.length; r++) colEdgeEnd[r] += colEdgeEnd[r - 1];

  // Chart cell -> stitch indices (every repeat), for hover highlighting.
  const cellIndex = new Map();
  (d.chart_cell ?? []).forEach(([r, c], i) => {
    const k = `${r},${c}`;
    if (!cellIndex.has(k)) cellIndex.set(k, []);
    cellIndex.get(k).push(i);
  });

  hat = { mesh, yarnLine, colLines, yarnPairs, stitchEnd, colEdgeEnd, cellIndex };
  setEdgeMatrices(yarnLine, yarnPairs);
  setEdgeMatrices(colLines, d.column_edges);

  // ---- UI ----
  $("name").textContent = d.name;
  $("sub").textContent =
    `${d.horizontal_gauge} st/in × ${d.vertical_gauge} rnd/in · pattern repeat ×${d.repeats}`;
  const nSynth = d.n_rounds - d.n_chart_rounds;
  $("stats").innerHTML = [
    ["stitches", d.n_stitches.toLocaleString()],
    ["rounds", nSynth ? `${d.n_rounds} (${nSynth} synthesized)` : d.n_rounds],
    ["brim → crown", `${d.stitch_counts[0]} → ${d.stitch_counts.at(-1)}`],
    ["crown starts", d.crown_start_round < d.n_rounds ? `round ${d.crown_start_round + 1}` : "—"],
    ["cast-ons", d.increase_flag.filter(Boolean).length],
    ["decreases", d.decrease_flag.filter(Boolean).length],
  ].map(([k, v]) => `<div><span>${k}</span><span>${v}</span></div>`).join("");

  $("layoutsrc").textContent = d.layout_source ? `layout: ${d.layout_source}` : "layout: initial helix";

  const slider = $("round");
  const atEnd = +slider.max === 0 || +slider.value === +slider.max;
  slider.max = d.n_rounds;
  if (atEnd || +slider.value > d.n_rounds) slider.value = d.n_rounds;
  paint();
  applyRound();
}

function paint() {
  if (!hat) return;
  const showShaping = $("t_dec").checked;
  const c = new THREE.Color();
  const n = d.n_stitches;
  const hl = new Set(highlightCell ? hat.cellIndex.get(highlightCell) ?? [] : []);
  for (let i = 0; i < n; i++) {
    if (hl.has(i)) c.copy(COLOR_HL);
    else if (showShaping && d.decrease_flag[i]) c.copy(COLOR_DEC);
    else if (showShaping && d.increase_flag[i]) c.copy(COLOR_INC);
    else c.copy(paletteColor[d.colors[i] ? 1 : 0]);
    if (d.synthesized[i]) c.multiplyScalar(SYNTH_FADE);
    hat.mesh.setColorAt(i, c);
  }
  hat.mesh.instanceColor.needsUpdate = true;
}

function applyPositions(newPositions) {
  const n = d.n_stitches;
  for (let i = 0; i < n; i++) {
    d.positions[i] = newPositions[i];
    m.makeTranslation(...newPositions[i]);
    hat.mesh.setMatrixAt(i, m);
  }
  hat.mesh.instanceMatrix.needsUpdate = true;
  setEdgeMatrices(hat.yarnLine, hat.yarnPairs);
  setEdgeMatrices(hat.colLines, d.column_edges);
}

function applyRound() {
  const slider = $("round");
  const r = +slider.value; // rounds knit so far
  $("roundval").textContent = `${r} / ${d.n_rounds}`;
  hat.mesh.count = hat.stitchEnd[r - 1];
  hat.yarnLine.count = Math.max(hat.stitchEnd[r - 1] - 1, 0);
  hat.colLines.count = hat.colEdgeEnd[r - 1];
}
$("round").oninput = applyRound;
$("t_yarn").onchange = (e) => (hat.yarnLine.visible = e.target.checked);
$("t_cols").onchange = (e) => (hat.colLines.visible = e.target.checked);
$("t_dec").onchange = paint;

// ---------- chart pane ----------
let serverOnline = false;
const grid = new ChartGrid($("gridwrap"), {
  onChange: (cells) => scheduleSync(cells),
  onHover: (r, c) => {
    highlightCell = r == null ? null : `${r},${c}`;
    paint();
  },
});

function setChartStatus(text, bad = false) {
  $("chartstat").textContent = text;
  $("chartstat").className = bad ? "bad" : "";
}

function chartSummary(cells) {
  let live = 0, dec = 0, inc = 0, bad = 0;
  for (const row of cells) for (const t of row) {
    const p = parseCell(t);
    if (!p) continue;
    if (p.bad) { bad++; continue; }
    live++;
    if (p.ops.some((o) => DECREASE_OPS.has(o))) dec++;
    if (p.ops.some((o) => INCREASE_OPS.has(o))) inc++;
  }
  return { live, dec, inc, bad };
}

function describeChart(chart) {
  const s = chartSummary(chart.cells);
  const base = `${chart.height} rounds × ${chart.width} columns · ${s.live} stitches/repeat` +
    ` · ${s.dec} decreases · ${s.inc} cast-ons`;
  if (s.bad) setChartStatus(`${base} · ${s.bad} unparsable cell(s) outlined red (use f / b)`, true);
  else setChartStatus(base + (chart.dirty ? " · unsaved" : ""));
  $("b_save").disabled = !serverOnline || !chart.dirty;
}

// Rebuild a chart from a static bundle (no server): repeat 0 of every round.
function chartFromBundle(bundle) {
  const H = bundle.chart_height ?? bundle.n_chart_rounds, W = bundle.chart_width ?? 0;
  const cells = Array.from({ length: H }, () => Array(W).fill(""));
  (bundle.chart_cell ?? []).forEach(([r, c], i) => {
    if (r < H && !cells[r][c]) cells[r][c] = [COLORS[bundle.colors[i]], ...(bundle.ops?.[i] ?? [])].join("-");
  });
  return { cells, width: W, height: H, name: bundle.name, repeats: bundle.repeats, dirty: false };
}

let syncTimer = null;
let syncing = false;
let pendingCells = null;
function scheduleSync(cells) {
  pendingCells = cells;
  setChartStatus("editing…");
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncChart, 250);
}

async function syncChart() {
  if (syncing) { syncTimer = setTimeout(syncChart, 100); return; }
  if (!serverOnline) { setChartStatus("server offline — edits are not compiled (run `make small_cubes`)", true); return; }
  const cells = pendingCells ?? grid.getData();
  pendingCells = null;
  syncing = true;
  setChartStatus("compiling…");
  try {
    const res = await fetch("api/chart", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cells, repeats: +$("repeats").value || 4 }),
    });
    const body = await res.json();
    if (!res.ok) { setChartStatus(`error: ${body.error}`, true); return; }
    version = body.version;
    loadBundle(body);
    describeChart(body.chart);
    refreshShaping();
    await refreshState(); // layout + optimizer survive text-only edits
  } catch (e) {
    setChartStatus(`sync failed: ${e}`, true);
  } finally {
    syncing = false;
  }
}

$("repeats").onchange = () => scheduleSync(grid.getData());
grid.onHistory = (canUndo, canRedo) => {
  $("b_undo").disabled = !canUndo || !serverOnline;
  $("b_redo").disabled = !canRedo || !serverOnline;
};
$("b_undo").onclick = () => { grid.undo(); $("gridwrap").focus({ preventScroll: true }); };
$("b_redo").onclick = () => { grid.redo(); $("gridwrap").focus({ preventScroll: true }); };
$("b_save").onclick = async () => {
  try {
    const res = await fetch("api/chart/save", { method: "POST" });
    const chart = await res.json();
    describeChart(chart);
    setChartStatus(`saved to ${chart.path}`);
  } catch (e) { setChartStatus(`save failed: ${e}`, true); }
};
// ---------- file bar: load / import / export / save as ----------
function applyLoaded(body) {
  version = body.version;
  loadBundle(body);
  const chart = body.chart;
  $("repeats").value = chart.repeats;
  grid.setData(chart.cells);
  grid.clearHistory();
  describeChart(chart);
  autoShaping();
  refreshShaping();
  showState({ running: false, iterations_total: 0 });
  dist = extent * 1.8;
  updateCamera();
  refreshFiles(chart.path);
}

async function postJson(endpoint, body) {
  const res = await fetch(endpoint, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data;
}

async function refreshFiles(selected) {
  if (!serverOnline) return;
  try {
    const { files } = await (await fetch("api/files")).json();
    const sel = $("files");
    sel.innerHTML = files.map((f) =>
      `<option value="${f.path}">${f.path}${f.kind === "layout" ? " (layout)" : ""}</option>`).join("");
    if (selected && files.some((f) => f.path === selected)) sel.value = selected;
  } catch (e) { console.warn(e); }
}

$("b_load").onclick = async () => {
  const path = $("files").value;
  if (!path) return;
  setChartStatus(`loading ${path}…`);
  try { applyLoaded(await postJson("api/load", { path })); setChartStatus(`loaded ${path}`); }
  catch (e) { setChartStatus(`load failed: ${e.message}`, true); }
};

$("b_import").onclick = () => $("importfile").click();
$("importfile").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  setChartStatus(`importing ${file.name}…`);
  try {
    const text = await file.text();
    const body = file.name.toLowerCase().endsWith(".json")
      ? { name: file.name, data: JSON.parse(text) }
      : { name: file.name, text };
    applyLoaded(await postJson("api/import", body));
    setChartStatus(`imported ${file.name} · unsaved (Save as… to keep it)`);
  } catch (err) { setChartStatus(`import failed: ${err.message}`, true); }
};

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const csvEscape = (v) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
$("b_export_csv").onclick = () =>
  download(`${d.name}.csv`, grid.getData().map((r) => r.map(csvEscape).join(",")).join("\n") + "\n", "text/csv");
$("b_export_json").onclick = () => {
  const chart = { cells: grid.getData(), repeats: +$("repeats").value || d.repeats,
    horizontal_gauge: d.horizontal_gauge, vertical_gauge: d.vertical_gauge, name: d.name };
  download(`${d.name}_layout.json`, JSON.stringify({ ...d, chart }), "application/json");
};

$("b_saveas").onclick = async () => {
  const cur = $("files").value || `patterns/${d.name}.csv`;
  const path = prompt("Save chart as (path under the repository):", cur.endsWith(".csv") ? cur : `patterns/${d.name}.csv`);
  if (!path) return;
  try {
    const chart = await postJson("api/chart/save", { path });
    describeChart(chart);
    setChartStatus(`saved to ${chart.path}`);
    refreshFiles(chart.path);
  } catch (e) { setChartStatus(`save failed: ${e.message}`, true); }
};

$("zoom").oninput = (e) => {
  const z = +e.target.value;
  document.body.style.setProperty("--cw", `${24 * z}px`);
  document.body.style.setProperty("--ch", `${16 * z}px`);
  $("gridwrap").style.fontSize = `${Math.round(8 * z)}px`;
};

// Tabs
$("tabs").querySelectorAll("button").forEach((b) => {
  b.onclick = () => {
    $("tabs").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${b.dataset.tab}`));
  };
});

// Splitter
const splitter = $("splitter"), side = $("side");
splitter.addEventListener("pointerdown", (e) => {
  splitter.setPointerCapture(e.pointerId);
  const move = (ev) => {
    side.style.width = `${Math.max(260, innerWidth - ev.clientX - 3)}px`;
    resize();
  };
  const up = () => { splitter.removeEventListener("pointermove", move); splitter.removeEventListener("pointerup", up); };
  splitter.addEventListener("pointermove", move);
  splitter.addEventListener("pointerup", up);
});

// ---------- shaping tab ----------
const S = ["slices", "width", "hg", "vg", "radius", "eq"];
function readShaping() {
  return {
    slices: +$("s_slices").value || 1, width: +$("s_width").value || 1,
    hg: +$("s_hg").value || 8, vg: +$("s_vg").value || 12,
    radius: +$("s_radius").value || 1, equator: +$("s_eq").value || 0,
  };
}
function autoShaping() {
  const p = defaultParams(d);
  $("s_slices").value = p.slices; $("s_width").value = p.width;
  $("s_hg").value = p.hg; $("s_vg").value = p.vg;
  $("s_radius").value = p.radius; $("s_eq").value = p.equator;
}
function refreshShaping() {
  if (!d) return;
  const p = readShaping();
  const H = grid.height;
  grid.setEquator(p.equator);
  grid.setGuide($("s_show").checked ? guideCells(p, H) : new Set());
  // Actual live count per repeat per round, from the sheet.
  const actual = grid.getData().map((row) => row.filter((t) => { const q = parseCell(t); return q && !q.bad; }).length);
  const rows = idealWidths(p, H).map(({ round, width }) => {
    const a = actual[round] ?? 0;
    const cls = a === width ? "ok" : Math.abs(a - width) > 1 ? "miss" : "";
    return `<tr><td>${round + 1}</td><td>${width}</td><td class="${cls}">${a}</td><td>${a - width > 0 ? "+" : ""}${a - width}</td></tr>`;
  });
  $("shapingtable").innerHTML =
    `<table><tr><th>round</th><th>ideal / slice</th><th>chart</th><th>Δ</th></tr>${rows.join("")}</table>`;
}
S.forEach((k) => ($(`s_${k}`).oninput = refreshShaping));
$("s_show").onchange = refreshShaping;
$("s_auto").onclick = () => { autoShaping(); refreshShaping(); };

// ---------- 3D hover -> chart cell ----------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let hoverPending = null;
canvas.addEventListener("pointermove", (e) => {
  if (drag || !hat) return;
  hoverPending = e;
});
function hoverTick() {
  if (!hoverPending || !hat) return;
  const e = hoverPending; hoverPending = null;
  const rect = canvas.getBoundingClientRect();
  pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObject(hat.mesh, false)[0];
  if (hit && hit.instanceId != null && d.chart_cell) grid.highlight(...d.chart_cell[hit.instanceId]);
  else grid.highlight(null);
}

// ---------- smoothing (server-side Adam, background job) ----------
const pNum = (id) => parseFloat($(id).value.replace(/,/g, ""));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let version = 0;
let polling = false;

function showState(st) {
  $("b_opt").disabled = st.running || !serverOnline;
  $("b_stop").disabled = !st.running;
  if (st.error) { $("optstat").textContent = `error: ${st.error}`; return; }
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
  if (st.positions && st.positions.length === d.n_stitches) {
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
    $("optstat").textContent = "optimizer unavailable — serve with `make small_cubes`";
    console.error(e);
  } finally {
    polling = false;
    $("b_opt").disabled = !serverOnline;
  }
}

async function post(endpoint, body) {
  const res = await fetch(endpoint, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok && res.status !== 409) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

$("b_opt").onclick = async () => {
  $("b_opt").disabled = true;
  try {
    await post("api/optimize", {
      iterations: pNum("p_iters"), update_every: pNum("p_every"), lr: pNum("p_lr"),
      weights: { gauge: pNum("p_wg"), inflate: pNum("p_wi"), smooth: pNum("p_ws") },
    });
    pollUntilDone();
  } catch (e) {
    $("optstat").textContent = "optimizer unavailable — serve with `make small_cubes`";
    $("b_opt").disabled = false;
    console.error(e);
  }
};
$("b_stop").onclick = () => post("api/stop").catch(console.error);
$("b_savelayout").onclick = async () => {
  try {
    const st = await post("api/layout/save");
    if (st.error) throw new Error(st.error);
    d.layout_source = st.layout_source;
    $("layoutsrc").textContent = `layout: ${st.layout_source} (saved)`;
    refreshFiles($("files").value);
  } catch (e) { $("optstat").textContent = `save layout failed: ${e.message}`; }
};
$("b_reset").onclick = async () => {
  try {
    const st = await post("api/reset");
    if (st.positions) { applyPositions(st.positions); version = st.version; }
    showState(st);
  } catch (e) { console.error(e); }
};

// ---------- orbit controls ----------
const target = new THREE.Vector3(0, 0, 0);
let theta = 0.6, phi = 1.15, dist = 5;
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
canvas.addEventListener("pointerleave", () => grid.highlight(null));
canvas.addEventListener("contextmenu", (e) => e.preventDefault());
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  dist = Math.min(60, Math.max(0.4, dist * Math.exp(e.deltaY * 0.001)));
  updateCamera();
}, { passive: false });

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);

// ---------- boot ----------
async function boot() {
  let bundle;
  if (!STATIC) {
    try {
      const res = await fetch("api/bundle");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      bundle = await res.json();
      serverOnline = true;
      version = bundle.version;
    } catch (e) {
      console.warn("no editor server, falling back to static bundle", e);
    }
  }
  if (!bundle) {
    const path = STATIC ?? "data/small_cubes_layout.json";
    try {
      bundle = await (await fetch(path)).json();
    } catch (e) {
      const err = $("err");
      err.style.display = "grid";
      err.textContent = `could not load ${path} — run \`make small_cubes\` first (${e})`;
      throw e;
    }
  }
  applyPalette();
  loadBundle(bundle);
  const chart = bundle.chart ?? chartFromBundle(bundle);
  $("repeats").value = chart.repeats ?? bundle.repeats;
  grid.readOnly = !serverOnline;
  grid.setData(chart.cells);
  describeChart(chart);
  if (!serverOnline) setChartStatus("server offline — sheet is read-only (run `make small_cubes`)", true);
  $("filebar").querySelectorAll("button, select").forEach((b) => (b.disabled = !serverOnline));
  $("b_export_csv").disabled = $("b_export_json").disabled = false;
  $("b_savelayout").disabled = !serverOnline;
  refreshFiles(chart.path);
  autoShaping();
  refreshShaping();
  dist = extent * 1.8;
  resize();
  updateCamera();
  if (serverOnline) refreshState().then((st) => st.running && pollUntilDone()).catch(() => {});
  renderer.setAnimationLoop(() => { hoverTick(); renderer.render(scene, camera); });
}
boot();
