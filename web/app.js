import * as THREE from "three";
import { ChartGrid, SideSheet, parseCell, COLORS, DECREASE_OPS, INCREASE_OPS } from "./chart.js";
import { STITCHES, symbolSvg } from "./stitches.js";
import { defaultShapingRow, guideCells, idealWidths, widestRound, sphereRadius, leafRounds } from "./shaping.js";
import { buildEdges, edgeLengths, relativeError, histogram, binValues,
         strainColor, quantile, CLASSES } from "./metrics.js";
import { renderHistogram, renderStats, renderDeviation } from "./histogram.js";
import { drawScaleBar, scaleBarHeight } from "./scalebar.js";

const $ = (id) => document.getElementById(id);
const PARAMS = new URLSearchParams(location.search);
const STATIC = PARAMS.get("data");

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
// The strain mesh replaces dots and plain edges with one instanced
// cylinder per measured edge, coloured by how far it is off gauge.
const strainMat = new THREE.MeshBasicMaterial();
const STRAIN_RADIUS = 0.022;

// Sphere-distance troubleshooting overlay: the target hemisphere (radius R
// on the shaping row, pole along the hat's axis) drawn see-through with a
// wireframe, plus a marker at its centre. Unit geometry, scaled per paint.
const SPHERE_GUIDE_COLOR = 0x9fd0ff;
const hemiGeo = new THREE.SphereGeometry(1, 48, 16, 0, 2 * Math.PI, 0, Math.PI / 2).rotateX(Math.PI / 2);
const sphereGuide = new THREE.Group();
sphereGuide.add(
  new THREE.Mesh(hemiGeo, new THREE.MeshBasicMaterial({
    color: SPHERE_GUIDE_COLOR, transparent: true, opacity: 0.08, depthWrite: false, side: THREE.DoubleSide })),
  new THREE.Mesh(hemiGeo, new THREE.MeshBasicMaterial({
    color: SPHERE_GUIDE_COLOR, transparent: true, opacity: 0.22, wireframe: true, depthWrite: false })));
const sphereCentre = new THREE.Mesh(new THREE.SphereGeometry(0.09, 16, 12),
  new THREE.MeshBasicMaterial({ color: 0xff2fd0, depthTest: false }));
sphereCentre.renderOrder = 10;
sphereGuide.visible = sphereCentre.visible = false;
hatGroup.add(sphereGuide, sphereCentre);
const _zAxis = new THREE.Vector3(0, 0, 1);

const m = new THREE.Matrix4();
const _a = new THREE.Vector3(), _b = new THREE.Vector3();
const _dir = new THREE.Vector3(), _mid = new THREE.Vector3();
const _q = new THREE.Quaternion(), _s = new THREE.Vector3();
const _up = new THREE.Vector3(0, 1, 0);

// Chart parameters shared by the Chart and Shaping tabs. One value each;
// every input bound to a parameter (PARAM_INPUTS) shows it and edits it.
// repeats, gauge and shapingRow live on the server (sent with every chart
// sync, saved with the chart); radiusFrom is a view setting.
const params = {
  repeats: 4, hg: 8.75, vg: 13,   // gauge: 17.5 st and 26 rnds in 2"
  shapingRow: null,     // 1-based sheet row; null = default (round before the first decrease), not saved
  radiusFrom: "layout", // "layout": fitted to the shaping row's stitches; "gauge": circumference / 2 pi
  vcount: 1,            // times the vertical repeat region (grid.vrepeat) is worked
};

// The vertical repeat as the server takes it, or null.
function vrepeatPayload() {
  return grid.vrepeat ? { ...grid.vrepeat, count: params.vcount } : null;
}

// Round (0-based) knit from a sheet row: its last copy when the row is in
// a vertical repeat, so the crown sphere sits on the round actually knit.
function roundOfRow(row) {
  const i = d?.round_sheet_row?.lastIndexOf(row) ?? -1;
  return i >= 0 ? i : row;
}

let d = null;     // current bundle
let hat = null;   // {mesh, yarnLine, colLines, yarnPairs, stitchEnd, colEdgeEnd, cellIndex}
let highlightCell = null; // "r,c" hovered in the grid
let zMax = 1;
let extent = 1; // max(height, diameter), for framing the camera

function setEdgeMatrices(em, pairs, radius = EDGE_RADIUS) {
  const pos = d.positions;
  for (let i = 0; i < pairs.length; i++) {
    _a.fromArray(pos[pairs[i][0]]);
    _b.fromArray(pos[pairs[i][1]]);
    _dir.subVectors(_b, _a);
    const len = _dir.length();
    _mid.addVectors(_a, _b).multiplyScalar(0.5);
    _q.setFromUnitVectors(_up, len > 1e-9 ? _dir.divideScalar(len) : _up);
    _s.set(radius, Math.max(len, 1e-9), radius);
    m.compose(_mid, _q, _s);
    em.setMatrixAt(i, m);
  }
  em.instanceMatrix.needsUpdate = true;
}

function disposeHat() {
  if (!hat) return;
  for (const o of [hat.mesh, hat.yarnLine, hat.colLines, hat.strain]) hatGroup.remove(o);
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

  // Measured-edge model, shared by the strain heatmap and the Edges tab.
  const edges = buildEdges(d);
  const strain = new THREE.InstancedMesh(edgeGeo, strainMat, edges.pairs.length);
  strain.instanceColor = new THREE.InstancedBufferAttribute(
    new Float32Array(edges.pairs.length * 3), 3);
  strain.visible = false;
  hatGroup.add(strain);

  hat = { mesh, yarnLine, colLines, strain, edges, yarnPairs, stitchEnd,
          colEdgeEnd, cellIndex };
  setEdgeMatrices(yarnLine, yarnPairs);
  setEdgeMatrices(colLines, d.column_edges);
  setEdgeMatrices(strain, edges.pairs, STRAIN_RADIUS);
  paintStrain();

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
  const sphere = sphereMode() ? sphereError() : null;
  const scale = sphere ? sphereScale(sphere) : strainScale();
  const rgb = [0, 0, 0];
  for (let i = 0; i < n; i++) {
    if (hl.has(i)) c.copy(COLOR_HL);
    else if (sphere) {
      // Crown: signed distance off the sphere, on the strain ramp. Below
      // the shaping row is not part of the sphere: its own colour, dimmed.
      if (Number.isNaN(sphere.err[i])) c.copy(paletteColor[d.colors[i] ? 1 : 0]).multiplyScalar(0.25);
      else c.setRGB(...strainColor(sphere.err[i], scale, rgb), THREE.SRGBColorSpace);
    }
    else if (showShaping && d.decrease_flag[i]) c.copy(COLOR_DEC);
    else if (showShaping && d.increase_flag[i]) c.copy(COLOR_INC);
    else c.copy(paletteColor[d.colors[i] ? 1 : 0]);
    if (d.synthesized[i]) c.multiplyScalar(SYNTH_FADE);
    hat.mesh.setColorAt(i, c);
  }
  hat.mesh.instanceColor.needsUpdate = true;
  updateSphereGuide(sphere);
  updateScaleBar(sphere, scale);
  if (sphere) {
    rampLabels(scale, true);
    const f = (v) => v.toFixed(2);
    const pc = (v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
    $("spherestat").innerHTML = sphere.n
      ? `R ${f(sphere.radius)} in (${params.radiusFrom === "layout" ? "fitted to layout" : "from gauge"}) · ` +
        `shaping-row ring ${f(sphere.ringRadius)} in<br>` +
        `centre (${sphere.centre.map(f).join(", ")}) in · axis tilt ${sphere.tilt.toFixed(1)}°<br>` +
        `crown RMS ${(sphere.rms * 100).toFixed(1)}% · range ${pc(sphere.min)} to ${pc(sphere.max)}`
      : "no stitches at or above the shaping row";
  }
}

// Colour full scale for the sphere heatmap: fitted to the data (the larger
// of the 2nd/98th percentile magnitudes, symmetric so black stays on the
// sphere) or the slider's manual value.
function sphereScale(sphere) {
  if (!$("s_fit").checked || !sphere.n) return strainScale();
  return Math.max(0.005, Math.abs(sphere.q02), Math.abs(sphere.q98));
}

function rampLabels(scale, sphere) {
  const pct = (scale * 100).toFixed(scale < 0.1 ? 1 : 0);
  $("strainval").textContent = `±${pct}%`;
  $("rampmin").textContent = sphere ? `−${pct}% inside` : `−${pct}% shorter`;
  $("rampmid").textContent = sphere ? "0 · on sphere" : "0 · on gauge";
  $("rampmax").textContent = sphere ? `+${pct}% outside` : `+${pct}% longer`;
}

// ---------- colour key under the 3D view ----------
// What the stitches / edges on screen are coloured by: flat colours as
// swatches, an active heatmap as an annotated ramp.
let legend = { swatches: [], ramp: null };
function legendSpec(sphere, scale) {
  const hex = (c) => `#${c.getHexString()}`;
  const swatches = [], strain = strainMode();
  if (!strain) {
    swatches.push({ color: palette.bg, label: "background (b)" }, { color: palette.fg, label: "foreground (f)" });
    if (sphere) {
      swatches.push({ color: hex(paletteColor[1].clone().multiplyScalar(0.25)), label: "below shaping row (dimmed)" });
    } else if ($("t_dec").checked) {
      swatches.push({ color: hex(COLOR_DEC), label: "decrease" }, { color: hex(COLOR_INC), label: "cast-on" });
    }
    if (d?.synthesized?.some(Boolean)) {
      swatches.push({ color: hex(paletteColor[1].clone().multiplyScalar(SYNTH_FADE)), label: "extended crown (darkened)" });
    }
  }
  let ramp = null;
  if (strain) {
    ramp = { title: "Edge strain: edge length vs gauge (length / gauge − 1)", scale: strainScale(),
             lo: "shorter", zero: "on gauge", hi: "longer" };
  } else if (sphere) {
    const how = $("s_fit").checked ? "scale fitted to data" : "manual scale";
    ramp = { title: `Distance from crown sphere: |p − c| / R − 1  (R ${sphere.radius.toFixed(2)} in, ` +
                    `${params.radiusFrom === "layout" ? "fitted to layout" : "from gauge"}; ${how})`,
             scale, lo: "inside", zero: "on sphere", hi: "outside" };
  }
  return { swatches, ramp };
}

function updateScaleBar(sphere, scale) {
  legend = legendSpec(sphere, scale);
  const bar = $("scalebar"), w = view.clientWidth, h = scaleBarHeight(legend);
  const dpr = renderer.getPixelRatio();
  bar.hidden = !h;
  view.style.setProperty("--barh", `${h}px`);
  if (!h) return;
  bar.style.height = `${h}px`;
  bar.width = Math.round(w * dpr);
  bar.height = Math.round(h * dpr);
  const ctx = bar.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawScaleBar(ctx, w, legend);
}

// The view as shown plus its key, as one PNG. Rendering right before the
// copy keeps the WebGL frame readable without preserveDrawingBuffer.
function viewImage() {
  renderer.render(scene, camera);
  const dpr = renderer.getPixelRatio();
  const w = canvas.clientWidth, h = canvas.clientHeight, bh = scaleBarHeight(legend);
  const out = document.createElement("canvas");
  out.width = canvas.width;
  out.height = canvas.height + Math.round(bh * dpr);
  const ctx = out.getContext("2d");
  ctx.drawImage(canvas, 0, 0);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (bh) drawScaleBar(ctx, w, legend, h);
  return out;
}
const pngBlob = (c) => new Promise((res) => c.toBlob(res, "image/png"));
$("b_saveimg").onclick = async () => {
  const mode = strainMode() ? "strain" : sphereMode() ? "sphere" : "colors";
  download(`${d?.name ?? "hat"}_${mode}.png`, await pngBlob(viewImage()), "image/png");
};

function updateSphereGuide(sphere) {
  const on = !!sphere?.n && $("t_guide").checked;
  sphereGuide.visible = sphereCentre.visible = on;
  if (!on) return;
  const c = new THREE.Vector3(...sphere.centre);
  sphereCentre.position.copy(c);
  sphereGuide.position.copy(c);
  sphereGuide.scale.setScalar(sphere.radius);
  sphereGuide.quaternion.setFromUnitVectors(_zAxis, new THREE.Vector3(...sphere.axis));
}

function sphereMode() { return $("t_sphere").checked; }

// Each stitch's distance from the centre of the crown sphere relative to
// its radius, minus 1: 0 on the sphere, + outside, - inside. Centre and
// radius are the shared shaping sphere (centre = mean of the shaping row's
// stitches in the current layout; radius fitted to them or from gauge), so
// the check follows the optimizer. Rounds below the shaping row are NaN.
// The axis (for drawing the hemisphere) runs from the cast-on ring's
// centroid to the shaping row's.
function sphereError() {
  const p = readShaping();
  const pos = d.positions, ri = d.round_index, n = d.n_stitches;
  const ctr = p.centre;
  const ring = fitRing(p.equatorRound);
  const err = new Float64Array(n).fill(NaN);
  const out = { err, radius: p.radius, n: 0, rms: 0, min: 0, max: 0, q02: 0, q98: 0,
                centre: ctr, axis: [0, 0, 1], tilt: 0, ringRadius: ring?.radius ?? 0 };
  if (!ring) return out;

  const base = fitRing(0);
  const ax = new THREE.Vector3(...ctr).sub(new THREE.Vector3(...base.centre));
  if (p.equatorRound > 0 && ax.lengthSq() > 1e-12) {
    ax.normalize();
    out.axis = ax.toArray();
    out.tilt = THREE.MathUtils.radToDeg(ax.angleTo(_zAxis));
  }

  const vals = [];
  let sq = 0;
  for (let i = 0; i < n; i++) {
    if (ri[i] < p.equatorRound) continue;
    const e = Math.hypot(pos[i][0] - ctr[0], pos[i][1] - ctr[1], pos[i][2] - ctr[2]) / p.radius - 1;
    err[i] = e;
    vals.push(e);
    sq += e * e;
  }
  vals.sort((a, b) => a - b);
  Object.assign(out, {
    n: vals.length, rms: Math.sqrt(sq / vals.length),
    min: vals[0], max: vals.at(-1),
    q02: quantile(vals, 0.02), q98: quantile(vals, 0.98),
  });
  return out;
}

function strainScale() { return (+$("strainscale").value || 25) / 100; }

function paintStrain() {
  if (!hat) return;
  const lengths = edgeLengths(hat.edges, d.positions);
  const err = relativeError(hat.edges, lengths);
  const scale = strainScale();
  const c = new THREE.Color();
  const rgb = [0, 0, 0];
  for (let i = 0; i < err.length; i++) {
    strainColor(err[i], scale, rgb);   // shared with the deviation plot
    c.setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
    hat.strain.setColorAt(i, c);
  }
  hat.strain.instanceColor.needsUpdate = true;
}

function strainMode() { return $("t_strain").checked; }

function applyStrainMode() {
  const on = strainMode(), sphere = sphereMode();
  $("strainbox").hidden = !on && !sphere;
  $("spherestat").hidden = $("sphereopts").hidden = !sphere;
  $("strainscale").disabled = sphere && $("s_fit").checked;
  rampLabels(strainScale(), sphere);
  paint();   // in sphere mode this relabels the ramp with the fitted scale
  if (!hat) return;
  hat.strain.visible = on;
  hat.mesh.visible = !on;
  hat.yarnLine.visible = !on && $("t_yarn").checked;
  hat.colLines.visible = !on && $("t_cols").checked;
  applyRound();
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
  setEdgeMatrices(hat.strain, hat.edges.pairs, STRAIN_RADIUS);
  paintStrain();
  // A layout-fitted sphere moves with the stitches: refit and repaint.
  if (params.radiusFrom === "layout") refreshShaping();
  else if (sphereMode()) paint();
  if ($("e_live").checked) refreshEdges();
}

function applyRound() {
  const slider = $("round");
  const r = +slider.value; // rounds knit so far
  $("roundval").textContent = `${r} / ${d.n_rounds}`;
  hat.mesh.count = hat.stitchEnd[r - 1];
  hat.yarnLine.count = Math.max(hat.stitchEnd[r - 1] - 1, 0);
  hat.colLines.count = hat.colEdgeEnd[r - 1];
  hat.strain.count = hat.edges.endByRound[r - 1];
}
$("round").oninput = applyRound;
$("t_yarn").onchange = (e) => (hat.yarnLine.visible = e.target.checked && !strainMode());
$("t_cols").onchange = (e) => (hat.colLines.visible = e.target.checked && !strainMode());
$("t_dec").onchange = paint;
// The two heatmaps are exclusive: strain draws edges, sphere colours stitches.
$("t_strain").onchange = () => { if (strainMode()) $("t_sphere").checked = false; applyStrainMode(); };
$("t_sphere").onchange = () => { if (sphereMode()) $("t_strain").checked = false; applyStrainMode(); };
$("s_fit").onchange = applyStrainMode;
$("t_guide").onchange = paint;
$("strainscale").oninput = () => { paintStrain(); applyStrainMode(); refreshEdges(); };

// ---------- chart pane ----------
let serverOnline = false;
const shapingSheet = new SideSheet($("sidewrap"));
$("gridwrap").addEventListener("scroll", () => { $("sidewrap").scrollTop = $("gridwrap").scrollTop; });
$("sidewrap").addEventListener("wheel", (e) => {
  e.preventDefault();
  $("gridwrap").scrollTop += e.deltaY;
}, { passive: false });
const grid = new ChartGrid($("gridwrap"), {
  onChange: (cells) => scheduleSync(cells),
  onHover: (r, c) => {
    highlightCell = r == null ? null : `${r},${c}`;
    paint();
  },
});

// Ops as chart symbols or text; a view setting, remembered per browser.
$("c_symbols").checked = localStorage.getItem("wg.symbols") === "1";
grid.setSymbols($("c_symbols").checked);
$("c_symbols").onchange = (e) => {
  grid.setSymbols(e.target.checked);
  localStorage.setItem("wg.symbols", e.target.checked ? "1" : "0");
};

// Stitch buttons: one on at a time; while it is, clicking or dragging
// over cells swaps their construction (grid.setBrush).
function setBrush(stitch) {
  grid.setBrush(stitch);
  $("stitchbar").querySelectorAll("button").forEach((b) => b.classList.toggle("on", stitch?.abbr === b.dataset.abbr));
}
const stsym = (s) => `<span class="stsym">${s.symbol ? symbolSvg([s.op]) : ""}</span>`;
for (const s of STITCHES) {
  const b = document.createElement("button");
  b.className = "alt";
  b.dataset.abbr = s.abbr;
  b.title = `${s.abbr}: ${s.name}`;
  b.innerHTML = `${stsym(s)}${s.abbr}`;
  b.onclick = () => setBrush(grid.brush === s ? null : s);
  $("stitchbar").appendChild(b);
}
addEventListener("keydown", (e) => { if (e.key === "Escape" && grid.brush && !grid.editing) setBrush(null); });

// Stitches tab: what each construction is and how it is worked.
$("stitchlist").innerHTML = `<table><thead><tr><th></th><th>stitch</th><th>name</th><th>type</th>` +
  `<th>construction</th></tr></thead><tbody>` +
  STITCHES.map((s) => `<tr><td>${stsym(s)}</td><td class="abbr">${s.abbr}</td><td>${s.name}</td>` +
    `<td class="kind">${s.kind}</td><td>${s.construction}</td></tr>`).join("") +
  `</tbody></table>`;

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
      body: JSON.stringify({
        cells, repeats: params.repeats, shaping_row: params.shapingRow,
        horizontal_gauge: params.hg, vertical_gauge: params.vg,
        vertical_repeat: vrepeatPayload(),
      }),
    });
    const body = await res.json();
    if (!res.ok) { setChartStatus(`error: ${body.error}`, true); return; }
    version = body.version;
    loadBundle(body);
    describeChart(body.chart);
    refreshShaping();
    // The server keeps the layout across edits (text-only: as is;
    // structural: patched locally), so pick up its positions.
    await refreshState();
  } catch (e) {
    setChartStatus(`sync failed: ${e}`, true);
  } finally {
    syncing = false;
  }
}

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
// Vertical repeat region from the sheet selection.
$("b_vrepeat").onclick = () => {
  const rows = grid.selectedRows();
  if (!rows) { setChartStatus("select the rounds to repeat on the sheet first"); return; }
  grid.setRepeatRegion(...rows);
  showParams();
  $("gridwrap").focus({ preventScroll: true });
};
$("b_vclear").onclick = () => { grid.setRepeatRegion(null); showParams(); };

// ---------- file bar: load / import / export / save as ----------
function applyLoaded(body) {
  version = body.version;
  loadBundle(body);
  const chart = body.chart;
  grid.setData(chart.cells);
  grid.clearHistory();
  describeChart(chart);
  paramsFromChart(chart, body);
  refreshShaping();
  refreshEdges();
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
  const chart = { cells: grid.getData(), repeats: params.repeats,
    horizontal_gauge: params.hg, vertical_gauge: params.vg,
    shaping_row: params.shapingRow, vertical_repeat: vrepeatPayload(), name: d.name };
  download(`${d.name}_layout.json`, JSON.stringify({ ...d, chart }), "application/json");
};

$("b_export_tex").onclick = async () => {
  const style = $("texstyle").value;
  try {
    const { tex } = await postJson("api/export_tex", {
      cells: grid.getData(), style, name: d.name,
      repeats: params.repeats, horizontal_gauge: params.hg, vertical_gauge: params.vg,
      shaping_row: params.shapingRow, vertical_repeat: vrepeatPayload(),
      fg: palette.fg, bg: palette.bg,
    });
    download(`${d.name}_${style}.tex`, tex, "application/x-tex");
  } catch (e) { setChartStatus(`LaTeX export failed: ${e.message}`, true); }
};

$("b_saveversion").onclick = async () => {
  try {
    const chart = await postJson("api/save_version");
    describeChart(chart);
    d.name = chart.name;
    d.layout_source = chart.layout_source;
    $("name").textContent = chart.name;
    $("layoutsrc").textContent = `layout: ${chart.layout_source} (saved)`;
    setChartStatus(`saved ${chart.path} and ${chart.layout_source}`);
    refreshFiles(chart.path);
  } catch (e) { setChartStatus(`save new version failed: ${e.message}`, true); }
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
  $("sidewrap").scrollTop = $("gridwrap").scrollTop;
};

// Tabs. ?tab=edges|shaping|chart opens one directly (linkable view state).
function showTab(name) {
  const btn = $("tabs").querySelector(`button[data-tab="${name}"]`);
  if (btn) btn.onclick ? btn.onclick() : btn.click();
}
$("tabs").querySelectorAll("button").forEach((b) => {
  b.onclick = () => {
    $("tabs").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${b.dataset.tab}`));
    if (b.dataset.tab === "edges") refreshEdges();
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
const HAT_TARGET_IN = [22, 23];
// Inputs bound to each shared parameter, and when an edit is committed:
// repeats and gauge recompile the hat (and may reset its layout), so they
// apply on change; the shaping row is cheap and follows every keystroke.
const PARAM_INPUTS = {
  repeats: { ids: ["repeats", "s_slices"], event: "change", parse: (v) => Math.round(v), min: 1, max: 64 },
  hg: { ids: ["c_hg", "s_hg"], event: "change", parse: Number, min: 0.5, max: 40 },
  vg: { ids: ["c_vg", "s_vg"], event: "change", parse: Number, min: 0.5, max: 60 },
  shapingRow: { ids: ["c_row", "s_eq"], event: "input", parse: (v) => Math.round(v), min: 1 },
  radiusFrom: { ids: ["c_rfrom", "s_rfrom"], event: "change" },
  vcount: { ids: ["c_vcount"], event: "change", parse: (v) => Math.round(v), min: 1, max: 99 },
};

// Take the server's values (on load; syncs never write back, so typing is
// not overwritten by a response to an older edit).
function paramsFromChart(chart, bundle) {
  params.repeats = chart.repeats ?? bundle.repeats ?? params.repeats;
  params.hg = chart.horizontal_gauge ?? bundle.horizontal_gauge ?? params.hg;
  params.vg = chart.vertical_gauge ?? bundle.vertical_gauge ?? params.vg;
  params.shapingRow = chart.shaping_row ?? bundle.shaping_row ?? null;
  const vr = chart.vertical_repeat ?? bundle.vertical_repeat ?? null;
  params.vcount = vr?.count ?? 1;
  grid.setVRepeat(vr && { start: vr.start, end: vr.end }, params.vcount);
  showParams();
}

function currentShapingRow() {
  return params.shapingRow ?? (d ? defaultShapingRow(d, { cells: grid.getData() }) : 1);
}

// Write the shared values into every bound input (except the one being
// typed in) and the derived read-outs.
function showParams() {
  for (const [key, spec] of Object.entries(PARAM_INPUTS)) {
    const v = key === "shapingRow" ? currentShapingRow() : params[key];
    for (const id of spec.ids) if (document.activeElement !== $(id)) $(id).value = v;
  }
  $("s_width").value = grid.width;
  const v = grid.vrepeat;
  $("c_vrows").textContent = v ? `rounds ${v.start}–${v.end}` : "";
  $("b_vclear").disabled = !v || !serverOnline;
  if (!d) return;
  const sph = shapingSphere();
  const text = sph.fit
    ? `${sph.radius.toFixed(3)}`
    : `${sph.gaugeRadius.toFixed(3)}`;
  $("c_radius").value = $("s_radius").value = text;
  const tip = `fitted to the layout: ${sph.fit ? sph.fit.radius.toFixed(3) + " in" : "—"} · ` +
    `from gauge (circumference / 2π): ${sph.gaugeRadius.toFixed(3)} in`;
  $("c_radius").title = $("s_radius").title = tip;
}

function setParam(key, value) {
  if (params[key] === value) return;
  params[key] = value;
  if (key === "vcount") grid.setVCount(value);
  showParams();
  refreshShaping();
  if (key !== "radiusFrom") scheduleSync(grid.getData());
}

for (const [key, spec] of Object.entries(PARAM_INPUTS)) {
  for (const id of spec.ids) {
    $(id).addEventListener(spec.event, () => {
      const raw = $(id).value;
      if (!spec.parse) return setParam(key, raw);
      if (raw === "") return;
      const v = spec.parse(+raw);
      const max = key === "shapingRow" ? grid.height : spec.max;
      if (!Number.isFinite(v) || v < spec.min || (max && v > max)) return;
      setParam(key, v);
    });
    // Leaving an input shows the parameter's value again (e.g. after an
    // out-of-range entry that was ignored).
    $(id).addEventListener("blur", showParams);
  }
}

// Live stitches per repeat on every round, from the sheet.
function sheetCounts() {
  return grid.getData().map((row) => row.filter((t) => { const q = parseCell(t); return q && !q.bad; }).length);
}

// Mean position and mean distance to it of the shaping row's stitches in
// the current layout, or null if the round has none. Follows the optimizer.
function fitRing(round) {
  const pos = d.positions, ri = d.round_index, n = d.n_stitches;
  const c = [0, 0, 0];
  let k = 0;
  for (let i = 0; i < n; i++) {
    if (ri[i] !== round) continue;
    for (let j = 0; j < 3; j++) c[j] += pos[i][j];
    k++;
  }
  if (!k) return null;
  for (let j = 0; j < 3; j++) c[j] /= k;
  let r = 0;
  for (let i = 0; i < n; i++) {
    if (ri[i] === round) r += Math.hypot(pos[i][0] - c[0], pos[i][1] - c[1], pos[i][2] - c[2]);
  }
  return { centre: c, radius: r / k };
}

// The crown sphere on the shaping row: centre from the layout, radius
// from the layout fit or from the gauge (params.radiusFrom).
function shapingSphere(actual = sheetCounts()) {
  const row = Math.max(1, Math.min(Math.max(1, actual.length), currentShapingRow()));
  const gaugeRadius = sphereRadius((actual[row - 1] ?? 0) * params.repeats, params.hg) || 1;
  const eqRound = roundOfRow(row - 1);
  const fit = d && eqRound < d.stitch_counts.length ? fitRing(eqRound) : null;
  const radius = params.radiusFrom === "layout" && fit ? fit.radius : gaugeRadius;
  return { row, eqRound, radius, gaugeRadius, fit, centre: fit?.centre ?? [0, 0, 0] };
}

// Everything the shaping guide needs, from the shared parameters.
function readShaping(actual = sheetCounts()) {
  const sph = shapingSphere(actual);
  return {
    slices: params.repeats, width: grid.width,
    hg: params.hg, vg: params.vg,
    shapingRow: sph.row, equator: sph.row - 1, // sheet rows
    equatorRound: sph.eqRound,                 // the round knit from it
    radius: sph.radius, centre: sph.centre,
    dec: $("s_dec").value,
  };
}

function refreshShaping() {
  if (!d) return;
  showParams();
  const actual = sheetCounts();
  const p = readShaping(actual);
  const H = grid.height;
  grid.setEquator(p.equator);
  grid.setGuide($("s_show").checked ? guideCells(p, H) : new Set());

  // The crown as a hemisphere on the shaping row: how tall the leaves
  // must be, and whether the chart has room for them.
  const leaves = leafRounds(p);
  const above = H - p.shapingRow;
  const fit = above - leaves;
  const circ = (actual[p.equator] ?? 0) * p.slices;
  const sph = shapingSphere(actual);
  $("s_leaves").innerHTML =
    `shaping row <b>${p.shapingRow}</b>: ${circ} st = ${(circ / p.hg).toFixed(1)} in around &rarr; ` +
    `R = <b>${p.radius.toFixed(3)} in</b> ` +
    `(layout fit ${sph.fit ? sph.fit.radius.toFixed(3) : "—"} · gauge ${sph.gaugeRadius.toFixed(3)})<br>` +
    `leaves: <b>${leaves} rounds</b> tall (rows ${p.shapingRow + 1}&ndash;${p.shapingRow + leaves}, ` +
    `${((Math.PI / 2) * p.radius).toFixed(2)} in); the chart has ${above} rows above the shaping row ` +
    (fit === 0 ? `<b class="ok">(exact)</b>`
      : `<b class="warn">(${Math.abs(fit)} ${fit > 0 ? "extra" : "short"})</b>`);

  // Informational only: hats usually land at 22-23 in around.
  const w = widestRound(actual, p);
  const inRange = w.inches >= HAT_TARGET_IN[0] && w.inches <= HAT_TARGET_IN[1];
  $("s_widest").innerHTML =
    `widest round <b>${w.round + 1}</b>: ${w.stitches} st = ` +
    `<b class="${inRange ? "ok" : "warn"}">${w.inches.toFixed(1)} in</b> around ` +
    `(target ${HAT_TARGET_IN[0]}&ndash;${HAT_TARGET_IN[1]} in)`;
  // The table runs through the whole leaf, past the end of the chart if
  // the chart is short, so the full decrease schedule is visible.
  const planH = Math.max(H, p.equator + leaves + 1);
  const rows = idealWidths(p, planH).map(({ round, width, decs }) => {
    if (round >= H) {
      return `<tr class="beyond"><td>${round + 1}</td><td>${width}</td><td>${decs || ""}</td><td>&mdash;</td><td></td></tr>`;
    }
    const a = actual[round] ?? 0;
    const cls = a === width ? "ok" : Math.abs(a - width) > 1 ? "miss" : "";
    return `<tr><td>${round + 1}</td><td>${width}</td><td>${decs || ""}</td><td class="${cls}">${a}</td><td>${a - width > 0 ? "+" : ""}${a - width}</td></tr>`;
  });
  $("shapingtable").innerHTML =
    `<table><tr><th>round</th><th>ideal / slice</th><th>${p.dec}s</th><th>chart</th><th>Δ</th></tr>${rows.join("")}</table>`;
  const { headers, rows: sideRows } = sideColumns(p, H, actual);
  shapingSheet.set(headers, sideRows, H);
  if (sphereMode()) paint();   // the sphere heatmap follows these inputs
}

// I / S / C sheet beside the chart, from the shaping inputs (which "Auto
// from chart & gauge" fills) and the chart's live counts.
function sideColumns(p, H, actual) {
  const rows = {};
  for (let r = 0; r < H; r++) {
    rows[r] = [null, null, { text: String(actual[r] ?? 0), title: `round ${r + 1}: ${actual[r] ?? 0} stitches in the chart` }];
  }
  for (const { round, width, decs } of idealWidths(p, H)) {
    const a = actual[round] ?? 0;
    rows[round][0] = { text: String(width), title: `round ${round + 1}: ideal ${width} stitches per slice` };
    if (decs) {
      rows[round][1] = { text: decs > 1 ? `${decs}×${p.dec}` : p.dec, cls: "dec",
                         title: `round ${round + 1}: work ${decs} ${p.dec}${decs > 1 ? "s" : ""} per slice` };
    }
    rows[round][2].cls = a === width ? "ok" : Math.abs(a - width) > 1 ? "miss" : "";
  }
  return {
    headers: [
      { name: "I", title: "ideal stitches per slice (shaping guide)" },
      { name: "S", title: "recommended decrease this round", width: "40px" },
      { name: "C", title: "stitches per slice in the chart" },
    ],
    rows,
  };
}

$("s_show").onchange = refreshShaping;
$("s_dec").onchange = refreshShaping;
// Shaping row back to the round before the chart's first decrease.
$("s_auto").onclick = () => {
  setParam("shapingRow", defaultShapingRow(d, { cells: grid.getData() }));
};

// ---------- edges tab ----------
function edgesVisible() {
  return $("tab-edges").classList.contains("on");
}

function refreshEdges() {
  if (!hat || !edgesVisible()) return;
  const bins = +$("e_bins").value || 48;
  const lengths = edgeLengths(hat.edges, d.positions);
  // The table always reports the generated lengths; the plot can show
  // those or the same edges relative to their own gauge.
  const byLength = histogram(hat.edges, lengths, bins);
  const plotted = $("e_mode").value === "error"
    ? histogram(hat.edges, relativeError(hat.edges, lengths), bins, "error")
    : byLength;
  renderHistogram($("edgesvg"), plotted, { logY: $("e_log").checked });
  renderStats($("edgestats"), byLength);

  // Every edge on one axis, painted with the 3D heatmap's own ramp, so the
  // colour scale is stated in numbers next to the data it describes.
  const err = relativeError(hat.edges, lengths);
  const scale = strainScale();
  const sorted = Float64Array.from(err).sort();
  const lo = Math.min(quantile(sorted, 0.002), -scale * 1.15);
  const hi = Math.max(quantile(sorted, 0.998), scale * 1.15);
  renderDeviation($("devsvg"), binValues(err, bins, lo, hi),
                  { scale, logY: $("e_log").checked });
  lastEdges = { byLength, plotted, scale };
}
let lastEdges = null;   // what the Edges tab last drew, for its exports
// ---------- Edges tab export: image and LaTeX ----------
const PLOT_BG = "#181b21";
const UI_FONT = '-apple-system, "Segoe UI", Helvetica, Arial, sans-serif';

// A plot's SVG as standalone markup: hover layers dropped, sized, and
// given the page font so it renders the same outside the page.
function plotSvgText(svg) {
  const c = svg.cloneNode(true);
  c.querySelectorAll('rect[fill="transparent"], g[visibility="hidden"]').forEach((n) => n.remove());
  const [, , w, h] = c.getAttribute("viewBox").split(" ").map(Number);
  c.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  c.setAttribute("width", w); c.setAttribute("height", h);
  c.setAttribute("style", `font-family: ${UI_FONT}; background: ${PLOT_BG}`);
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  for (const [k, v] of Object.entries({ width: "100%", height: "100%", fill: PLOT_BG })) bg.setAttribute(k, v);
  c.insertBefore(bg, c.firstChild);
  return { text: new XMLSerializer().serializeToString(c), w, h };
}

// The plot as an image (for drawing onto a canvas).
function plotImage(svg) {
  const { text, w, h } = plotSvgText(svg);
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res({ img, w, h });
    img.onerror = rej;
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
  });
}

// One plot rasterised at `scale` x its viewBox.
async function plotCanvas(svg, scale = 3) {
  const { img, w, h } = await plotImage(svg);
  const c = document.createElement("canvas");
  c.width = w * scale; c.height = h * scale;
  const ctx = c.getContext("2d");
  ctx.scale(scale, scale);
  ctx.drawImage(img, 0, 0, w, h);
  return c;
}

// The stats table, as on the tab, onto a canvas at (x, y); returns height.
function drawStatsTable(ctx, x, y, w, hist) {
  const cols = ["series", "edges", "gauge", "mean", "median", "std dev", "mean vs gauge"];
  const at = [0, 0.3, 0.42, 0.54, 0.66, 0.78, 1].map((f) => x + f * w);
  const f4 = (v) => (v == null || !isFinite(v) ? "—" : v.toFixed(4));
  ctx.font = `12px ${UI_FONT}`;
  ctx.textBaseline = "middle";
  const row = (cells, yy, colour) => cells.forEach((t, i) => {
    ctx.textAlign = i === 0 ? "left" : "right";
    ctx.fillStyle = Array.isArray(colour) ? colour[i] : colour;
    ctx.fillText(t, i === 0 ? at[0] + (cells.swatch ? 15 : 0) : at[i], yy);
  });
  row(cols, y + 9, "#898781");
  ctx.fillStyle = "#383835"; ctx.fillRect(x, y + 19, w, 1);
  let yy = y + 33;
  CLASSES.forEach((cls, s) => {
    const st = hist.stats[s];
    if (!st.n) return;
    const off = st.rest ? (st.mean / st.rest - 1) * 100 : 0;
    const offCol = Math.abs(off) < 1 ? "#7bd88f" : Math.abs(off) < 5 ? "#d7dae0" : "#ff8a80";
    ctx.fillStyle = cls.color; ctx.fillRect(x, yy - 5, 10, 10);
    const cells = [`${cls.name} (${cls.short})`, st.n.toLocaleString(), f4(st.rest), f4(st.mean),
      f4(st.median), f4(st.std), `${off >= 0 ? "+" : ""}${off.toFixed(2)}%`];
    cells.swatch = true;
    row(cells, yy, [...Array(6).fill("#d7dae0"), offCol]);
    ctx.fillStyle = "#23272e"; ctx.fillRect(x, yy + 11, w, 1);
    yy += 24;
  });
  ctx.textAlign = "left";
  return yy - y;
}

// Wrap text to width; returns the lines.
function wrapText(ctx, text, width) {
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const t = line ? `${line} ${word}` : word;
    if (ctx.measureText(t).width > width && line) { lines.push(line); line = word; }
    else line = t;
  }
  if (line) lines.push(line);
  return lines;
}

// The tab's content -- title, histogram, stats table, deviation plot and
// its note -- composed as one picture at `scale` x.
async function edgesTabCanvas(scale = 2) {
  const W = 680, pad = 20, inner = W - 2 * pad;
  const hist = await plotImage($("edgesvg")), dev = await plotImage($("devsvg"));
  const hh = inner * hist.h / hist.w, dh = inner * dev.h / dev.w;
  const meas = document.createElement("canvas").getContext("2d");
  meas.font = `11px ${UI_FONT}`;
  const note = wrapText(meas, $("e_note").textContent, inner);
  const rows = CLASSES.filter((_, s) => lastEdges.byLength.stats[s].n).length;
  const H = pad + 40 + hh + 16 + 24 * rows + 30 + 30 + dh + 10 + note.length * 15 + pad;
  const c = document.createElement("canvas");
  c.width = W * scale; c.height = Math.ceil(H * scale);
  const ctx = c.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = PLOT_BG; ctx.fillRect(0, 0, W, H);
  ctx.textBaseline = "alphabetic";
  let y = pad + 14;
  ctx.fillStyle = "#fff"; ctx.font = `600 14px ${UI_FONT}`;
  ctx.fillText(`${d.name} — edge lengths`, pad, y);
  ctx.fillStyle = "#8b93a1"; ctx.font = `12px ${UI_FONT}`;
  ctx.fillText(`${d.n_stitches.toLocaleString()} stitches · gauge ${params.hg} st × ${params.vg} rnd per inch` +
    ` · ${$("layoutsrc").textContent || "layout"}`, pad, y + 18);
  y += 26;
  ctx.drawImage(hist.img, pad, y, inner, hh);
  y += hh + 16;
  y += drawStatsTable(ctx, pad, y, inner, lastEdges.byLength) + 12;
  ctx.fillStyle = "#c3c2b7"; ctx.font = `12px ${UI_FONT}`;
  ctx.fillText($("tab-edges").querySelector(".plothead").textContent, pad, y + 12);
  y += 24;
  ctx.drawImage(dev.img, pad, y, inner, dh);
  y += dh + 14;
  ctx.fillStyle = "#6f7785"; ctx.font = `11px ${UI_FONT}`;
  note.forEach((l, i) => ctx.fillText(l, pad, y + i * 15));
  return c;
}

const dataUrl = (blob) => new Promise((res) => {
  const r = new FileReader();
  r.onload = () => res(r.result);
  r.readAsDataURL(blob);
});

$("e_saveimg").onclick = async () => {
  refreshEdges();
  download(`${d.name}_edges.png`, await pngBlob(await edgesTabCanvas()), "image/png");
};

$("e_tex").onclick = async () => {
  const btn = $("e_tex");
  btn.disabled = true;
  try {
    refreshEdges();
    const images = {
      "histogram.png": await dataUrl(await pngBlob(await plotCanvas($("edgesvg")))),
      "deviation.png": await dataUrl(await pngBlob(await plotCanvas($("devsvg")))),
      "view.png": await dataUrl(await pngBlob(viewImage())),
      "edges_tab.png": await dataUrl(await pngBlob(await edgesTabCanvas())),
      "histogram.svg": plotSvgText($("edgesvg")).text,
      "deviation.svg": plotSvgText($("devsvg")).text,
    };
    const res = await fetch("api/export_edges", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: d.name, images,
        stats: lastEdges.byLength.stats.map((st, s) => ({ ...st, ...CLASSES[s] })),
        clipped: lastEdges.plotted.clipped, mode: lastEdges.plotted.mode,
        log: $("e_log").checked, strain_scale: lastEdges.scale,
        gauge: { horizontal: params.hg, vertical: params.vg },
        repeats: params.repeats, n_stitches: d.n_stitches,
        layout_source: d.layout_source ?? null,
        settings: { lr: pNum("p_lr"), scheme: $("p_scheme").value,
                    weights: { gauge: pNum("p_wg"), inflate: pNum("p_wi"), smooth: pNum("p_ws") } },
      }),
    });
    if (!res.ok) throw new Error((await res.json()).error ?? `HTTP ${res.status}`);
    download(`${d.name}_edges.zip`, await res.blob(), "application/zip");
  } catch (e) {
    alert(`LaTeX export failed: ${e.message}`);
  } finally {
    btn.disabled = !serverOnline;
  }
};

$("e_bins").oninput = refreshEdges;
$("e_mode").onchange = refreshEdges;
$("e_log").onchange = refreshEdges;
$("e_refresh").onclick = refreshEdges;

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

// ---------- smoothing (server-side optimizer, background job) ----------
// Iteration counts suited to each scheme: an implicit iteration is a
// whole sparse solve, so far fewer are needed. Learning rate is Adam's.
const SCHEME_DEFAULTS = {
  direct: { iters: 1000, every: 500 },
  local_global: { iters: 200, every: 10 },
  gauss_newton: { iters: 30, every: 2 },
};
$("p_scheme").onchange = () => {
  const s = $("p_scheme").value, def = SCHEME_DEFAULTS[s];
  $("p_iters").value = def.iters;
  $("p_every").value = def.every;
  $("p_lr").disabled = s !== "direct";
};
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
  // Implicit schemes also report the line-search step and CG iterations.
  const solve = l?.cg != null ? ` · step ${+l.alpha.toPrecision(2)} · cg ${l.cg}` : "";
  $("optstat").textContent = l
    ? `${iter} · gauge ${l.gauge.toFixed(4)} · smooth ${l.smooth.toFixed(4)}` +
      ` · total ${l.total.toFixed(4)}${solve}`
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
      scheme: $("p_scheme").value,
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
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
// The key's height changes with what is shown; the canvas follows it.
new ResizeObserver(resize).observe(canvas);
// Redraw the key at the view's new width.
new ResizeObserver(() => { if (hat) paint(); }).observe(view);

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

  grid.readOnly = !serverOnline;
  grid.setData(chart.cells);
  describeChart(chart);
  if (!serverOnline) setChartStatus("server offline — sheet is read-only (run `make small_cubes`)", true);
  $("filebar").querySelectorAll("button, select").forEach((b) => (b.disabled = !serverOnline));
  $("b_export_csv").disabled = $("b_export_json").disabled = false;
  $("b_savelayout").disabled = $("b_saveversion").disabled = !serverOnline;
  $("b_vrepeat").disabled = !serverOnline;
  $("e_tex").disabled = !serverOnline;
  refreshFiles(chart.path);
  paramsFromChart(chart, bundle);
  refreshShaping();
  if (PARAMS.get("strain") === "1") $("t_strain").checked = true;
  else if (PARAMS.get("sphere") === "1") $("t_sphere").checked = true;
  if (PARAMS.get("x")) $("e_mode").value = PARAMS.get("x");
  applyStrainMode();
  if (PARAMS.get("tab")) showTab(PARAMS.get("tab"));
  dist = extent * 1.8;
  resize();
  updateCamera();
  if (serverOnline) refreshState().then((st) => st.running && pollUntilDone()).catch(() => {});
  renderer.setAnimationLoop(() => { hoverTick(); renderer.render(scene, camera); });
}
boot();
