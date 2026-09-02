// Overlaid edge-length distributions as stepped outlines on shared bins.
//
// Three distributions on one axis: a saturated block per series would hide
// whichever is drawn underneath, so each series is a 2px step outline over
// a ~12% wash of its own hue, and the expected gauge length for each is a
// dashed rule in the same hue. Identity is never colour alone -- the
// legend and the stats table name every series.

import { CLASSES, strainCss } from "./metrics.js";

const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs = {}) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};
const fmt = (v, d = 4) => (v == null || !isFinite(v) ? "—" : v.toFixed(d));

export function renderHistogram(svg, hist, { width = 640, height = 300, logY = true } = {}) {
  const M = { top: 14, right: 14, bottom: 34, left: 46 };
  const w = width - M.left - M.right, h = height - M.top - M.bottom;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren();
  if (!hist || !isFinite(hist.lo) || !isFinite(hist.hi)) return;

  const x = (v) => M.left + ((v - hist.lo) / (hist.hi - hist.lo)) * w;
  // These distributions are extremely peaked -- tens of thousands of edges
  // in one bin and a tail of tens -- so a linear count axis erases the tail
  // that the research question is about. Log is the default, and labelled.
  const span = logY ? Math.log1p(hist.max) : hist.max;
  const y = (c) => M.top + h - ((logY ? Math.log1p(c) : c) / span) * h;

  // --- recessive grid + axes ---
  const g = el("g");
  let ticks;
  if (logY) {
    ticks = [0];
    for (let p = 1; p <= hist.max; p *= 10) ticks.push(p);
    if (ticks.at(-1) < hist.max) ticks.push(hist.max);
  } else {
    ticks = Array.from({ length: 5 }, (_, i) => (hist.max / 4) * i);
  }
  for (const c of ticks) {
    const yy = y(c);
    g.appendChild(el("line", { x1: M.left, x2: M.left + w, y1: yy, y2: yy,
      stroke: "#2c2c2a", "stroke-width": 1 }));
    const t = el("text", { x: M.left - 7, y: yy + 3.5, fill: "#898781",
      "font-size": 10, "text-anchor": "end" });
    t.textContent = Math.round(c).toLocaleString();
    g.appendChild(t);
  }
  const yl = el("text", { x: 11, y: M.top + h / 2, fill: "#898781", "font-size": 10,
    "text-anchor": "middle", transform: `rotate(-90 11 ${M.top + h / 2})` });
  yl.textContent = logY ? "edges per bin (log)" : "edges per bin";
  g.appendChild(yl);
  g.appendChild(el("line", { x1: M.left, x2: M.left + w, y1: M.top + h,
    y2: M.top + h, stroke: "#383835", "stroke-width": 1 }));
  for (let i = 0; i <= 5; i++) {
    const v = hist.lo + ((hist.hi - hist.lo) / 5) * i;
    const t = el("text", { x: x(v), y: M.top + h + 14, fill: "#898781",
      "font-size": 10, "text-anchor": "middle" });
    t.textContent = hist.mode === "error" ? `${(v * 100).toFixed(0)}%` : v.toFixed(3);
    g.appendChild(t);
  }
  const xl = el("text", { x: M.left + w / 2, y: height - 4, fill: "#898781",
    "font-size": 10, "text-anchor": "middle" });
  xl.textContent = hist.mode === "error"
    ? "edge length relative to gauge" : "edge length (inches)";
  g.appendChild(xl);
  svg.appendChild(g);

  // --- one stepped outline + wash per series ---
  CLASSES.forEach((cls, s) => {
    const counts = hist.counts[s];
    if (!counts.some((c) => c > 0)) return;
    const pts = [];
    for (let i = 0; i < hist.bins; i++) {
      const x0 = x(hist.lo + i * hist.width), x1 = x(hist.lo + (i + 1) * hist.width);
      pts.push(`${x0},${y(counts[i])}`, `${x1},${y(counts[i])}`);
    }
    const base = M.top + h;
    svg.appendChild(el("polygon", {
      points: `${x(hist.lo)},${base} ${pts.join(" ")} ${x(hist.hi)},${base}`,
      fill: cls.color, "fill-opacity": 0.12, stroke: "none",
    }));
    svg.appendChild(el("polyline", {
      points: pts.join(" "), fill: "none", stroke: cls.color,
      "stroke-width": 2, "stroke-linejoin": "round",
    }));
  });

  // --- expected length for each series ---
  if (hist.mode === "error") {
    svg.appendChild(el("line", { x1: x(0), x2: x(0), y1: M.top, y2: M.top + h,
      stroke: "#c3c2b7", "stroke-width": 2, "stroke-dasharray": "5 4" }));
    const t = el("text", { x: x(0) + 4, y: M.top + 10, fill: "#c3c2b7", "font-size": 10 });
    t.textContent = "on gauge";
    svg.appendChild(t);
  }
  const seen = new Map();
  CLASSES.forEach((cls, s) => {
    const rest = hist.stats[s].rest;
    if (!rest || !hist.stats[s].n) return;
    if (seen.has(rest.toFixed(6))) return;      // vertical & shaping share one
    seen.set(rest.toFixed(6), true);
    if (rest < hist.lo || rest > hist.hi) return;
    svg.appendChild(el("line", { x1: x(rest), x2: x(rest), y1: M.top, y2: M.top + h,
      stroke: cls.color, "stroke-width": 2, "stroke-dasharray": "5 4",
      "stroke-opacity": 0.9 }));
    const t = el("text", { x: x(rest) + 4, y: M.top + 10, fill: "#c3c2b7",
      "font-size": 10 });
    t.textContent = `gauge ${rest.toFixed(4)}"`;
    svg.appendChild(t);
  });

  // --- hover: crosshair + per-bin readout ---
  const hover = el("g", { visibility: "hidden" });
  const rule = el("line", { y1: M.top, y2: M.top + h, stroke: "#c3c2b7",
    "stroke-width": 1, "stroke-dasharray": "3 3" });
  hover.appendChild(rule);
  svg.appendChild(hover);
  // One tooltip per plot, reused across redraws.
  let tip = svg.parentElement.querySelector(".histtip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "histtip";
    svg.parentElement.appendChild(tip);
  }
  tip.hidden = true;

  const capture = el("rect", { x: M.left, y: M.top, width: w, height: h,
    fill: "transparent" });
  capture.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * width;
    const i = Math.max(0, Math.min(hist.bins - 1,
      Math.floor(((px - M.left) / w) * hist.bins)));
    const cx = x(hist.lo + (i + 0.5) * hist.width);
    rule.setAttribute("x1", cx); rule.setAttribute("x2", cx);
    hover.setAttribute("visibility", "visible");
    const rows = CLASSES.map((c, s) =>
      `<div><span class="sw" style="background:${c.color}"></span>${c.name}` +
      `<b>${hist.counts[s][i].toLocaleString()}</b></div>`).join("");
    const b0 = hist.lo + i * hist.width, b1 = b0 + hist.width;
    tip.innerHTML =
      `<div class="hd">` + (hist.mode === "error"
        ? `${(b0 * 100).toFixed(1)}% – ${(b1 * 100).toFixed(1)}%`
        : `${b0.toFixed(4)} – ${b1.toFixed(4)}"`) + `</div>${rows}`;
    tip.hidden = false;
    const local = svg.parentElement.getBoundingClientRect();
    tip.style.left = `${Math.min(e.clientX - local.left + 12, local.width - 160)}px`;
    tip.style.top = `${e.clientY - local.top + 12}px`;
  });
  capture.addEventListener("pointerleave", () => {
    hover.setAttribute("visibility", "hidden");
    tip.hidden = true;
  });
  svg.appendChild(capture);
}

/** Legend + stats: mean, median, std of the generated lengths per series. */
export function renderStats(container, hist) {
  const rows = CLASSES.map((cls, s) => {
    const st = hist.stats[s];
    if (!st.n) return "";
    const off = st.rest ? (st.mean / st.rest - 1) * 100 : 0;
    return `<tr>
      <td class="name"><span class="sw" style="background:${cls.color}"></span>${cls.name}
        <span class="sub">${cls.short}</span></td>
      <td>${st.n.toLocaleString()}</td>
      <td>${fmt(st.rest)}</td>
      <td>${fmt(st.mean)}</td>
      <td>${fmt(st.median)}</td>
      <td>${fmt(st.std)}</td>
      <td class="${Math.abs(off) < 1 ? "ok" : Math.abs(off) < 5 ? "" : "miss"}">${off >= 0 ? "+" : ""}${off.toFixed(2)}%</td>
    </tr>`;
  }).join("");
  container.innerHTML = `<table>
    <tr><th>series</th><th>edges</th><th>gauge</th><th>mean</th><th>median</th>
        <th>std dev</th><th>mean vs gauge</th></tr>${rows}</table>` +
    (hist.clipped ? `<div class="note">${hist.clipped.toLocaleString()} edges outside the plotted range (axis clipped at the 0.2 / 99.8 percentiles); statistics use every edge.</div>` : "");
}

/** All edges on one axis, each bar painted with the 3D view's strain ramp.
 *  This is the legend for that ramp: it says what the colours mean in
 *  numbers, and shows how much of the fabric sits at each deviation. */
export function renderDeviation(svg, hist, { width = 640, height = 200,
                                             scale = 0.25, logY = true } = {}) {
  const M = { top: 14, right: 14, bottom: 42, left: 46 };
  const w = width - M.left - M.right, h = height - M.top - M.bottom;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren();
  if (!hist || !isFinite(hist.lo) || !isFinite(hist.hi)) return;

  const x = (v) => M.left + ((v - hist.lo) / (hist.hi - hist.lo)) * w;
  const span = logY ? Math.log1p(hist.max) : hist.max;
  const y = (c) => M.top + h - ((logY ? Math.log1p(c) : c) / span) * h;
  const base = M.top + h;

  const g = el("g");
  const ticks = logY
    ? [0, ...(() => { const a = []; for (let p = 1; p <= hist.max; p *= 10) a.push(p); return a; })()]
    : Array.from({ length: 5 }, (_, i) => (hist.max / 4) * i);
  for (const c of ticks) {
    g.appendChild(el("line", { x1: M.left, x2: M.left + w, y1: y(c), y2: y(c),
      stroke: "#2c2c2a", "stroke-width": 1 }));
    const t = el("text", { x: M.left - 7, y: y(c) + 3.5, fill: "#898781",
      "font-size": 10, "text-anchor": "end" });
    t.textContent = Math.round(c).toLocaleString();
    g.appendChild(t);
  }
  svg.appendChild(g);

  // Bars, coloured exactly as the 3D heatmap colours that deviation.
  for (let i = 0; i < hist.bins; i++) {
    if (!hist.counts[i]) continue;
    const x0 = x(hist.lo + i * hist.width), x1 = x(hist.lo + (i + 1) * hist.width);
    svg.appendChild(el("rect", {
      x: x0, y: y(hist.counts[i]), width: Math.max(1, x1 - x0 - 1),
      height: base - y(hist.counts[i]),
      fill: strainCss(hist.lo + (i + 0.5) * hist.width, scale),
      stroke: "#5a6270", "stroke-width": 1, "stroke-linejoin": "round",
    }));
  }

  // Reference marks: on gauge, and where the ramp saturates.
  const mark = (v, label, colour, dash) => {
    if (v < hist.lo || v > hist.hi) return;
    svg.appendChild(el("line", { x1: x(v), x2: x(v), y1: M.top, y2: base,
      stroke: colour, "stroke-width": 2, "stroke-dasharray": dash }));
    const t = el("text", { x: x(v), y: M.top - 3, fill: colour, "font-size": 10,
      "text-anchor": "middle" });
    t.textContent = label;
    svg.appendChild(t);
  };
  mark(0, "on gauge", "#c3c2b7", "5 4");
  mark(-scale, "full scale", "#2fd6ab", "3 3");
  mark(scale, "full scale", "#ff8a3d", "3 3");

  svg.appendChild(el("line", { x1: M.left, x2: M.left + w, y1: base, y2: base,
    stroke: "#383835", "stroke-width": 1 }));
  for (let i = 0; i <= 6; i++) {
    const v = hist.lo + ((hist.hi - hist.lo) / 6) * i;
    const t = el("text", { x: x(v), y: base + 14, fill: "#898781",
      "font-size": 10, "text-anchor": "middle" });
    t.textContent = `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`;
    svg.appendChild(t);
  }
  const xl = el("text", { x: M.left + w / 2, y: height - 6, fill: "#898781",
    "font-size": 10, "text-anchor": "middle" });
  xl.textContent = "edge length minus gauge, as a share of gauge";
  svg.appendChild(xl);

  // Hover readout.
  let tip = svg.parentElement.querySelector(".histtip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "histtip";
    svg.parentElement.appendChild(tip);
  }
  tip.hidden = true;
  const capture = el("rect", { x: M.left, y: M.top, width: w, height: h,
    fill: "transparent" });
  capture.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * width;
    const i = Math.max(0, Math.min(hist.bins - 1,
      Math.floor(((px - M.left) / w) * hist.bins)));
    const b0 = hist.lo + i * hist.width, c = hist.counts[i];
    tip.innerHTML =
      `<div class="hd">${(b0 * 100).toFixed(1)}% – ${((b0 + hist.width) * 100).toFixed(1)}%</div>` +
      `<div><span class="sw" style="background:${strainCss(b0 + hist.width / 2, scale)}"></span>` +
      `edges<b>${c.toLocaleString()}</b></div>` +
      `<div><span class="sw" style="background:transparent"></span>share` +
      `<b>${(100 * c / hist.n).toFixed(2)}%</b></div>`;
    tip.hidden = false;
    const local = svg.parentElement.getBoundingClientRect();
    tip.style.left = `${Math.min(e.clientX - local.left + 12, local.width - 170)}px`;
    tip.style.top = `${e.clientY - local.top + 12}px`;
  });
  capture.addEventListener("pointerleave", () => (tip.hidden = true));
  svg.appendChild(capture);
}
