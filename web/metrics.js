// Edge-length metrics: is the layout actually hitting gauge?
//
// One edge model serves both the histogram and the 3D strain heatmap, and
// it is deliberately the same set hat_optimizer.py optimizes: for every
// stitch, the edge to its right neighbour in the round (rest length
// 1/horizontal_gauge) and the edge to the stitch above it in its column
// (rest 1/vertical_gauge). Column edges whose endpoints carry a shaping
// flag are split out, because a k2tog or a cast-on has no reason to sit
// at plain column gauge and would otherwise smear the vertical bucket.

export const CLASSES = [
  { key: "h", name: "horizontal", short: "ring", color: "#3987e5" },
  { key: "v", name: "vertical", short: "column", color: "#d95926" },
  { key: "s", name: "shaping", short: "inc/dec", color: "#199e70" },
];

// Diverging poles for the strain heatmap: neutral near-black at gauge, warm
// where an edge is stretched, cool where it is compressed. The 3D view and
// the deviation histogram share this ramp so they cannot disagree.
export const STRAIN_ZERO = "#0a0c10";
export const STRAIN_LONG = "#ff8a3d";   // positive: longer than gauge
export const STRAIN_SHORT = "#2fd6ab";  // negative: shorter than gauge

const hex2rgb = (h) => [
  parseInt(h.slice(1, 3), 16) / 255,
  parseInt(h.slice(3, 5), 16) / 255,
  parseInt(h.slice(5, 7), 16) / 255,
];
const RGB_ZERO = hex2rgb(STRAIN_ZERO);
const RGB_LONG = hex2rgb(STRAIN_LONG);
const RGB_SHORT = hex2rgb(STRAIN_SHORT);

/** sRGB colour for a signed relative error, saturating at +-scale.
 *  err = length/gauge - 1, so 0 is exactly on gauge. */
export function strainColor(err, scale, out = [0, 0, 0]) {
  const t = Math.max(-1, Math.min(1, (scale > 0 ? err / scale : 0)));
  const pole = t >= 0 ? RGB_LONG : RGB_SHORT;
  const k = Math.abs(t);
  for (let i = 0; i < 3; i++) out[i] = RGB_ZERO[i] + (pole[i] - RGB_ZERO[i]) * k;
  return out;
}

export const strainCss = (err, scale) =>
  "rgb(" + strainColor(err, scale).map((v) => Math.round(v * 255)).join(",") + ")";

/** Single-series binning of signed values over an explicit range. */
export function binValues(values, bins, lo, hi) {
  const width = (hi - lo) / bins;
  const counts = new Int32Array(bins);
  let clipped = 0;
  for (const v of values) {
    const k = Math.floor((v - lo) / width);
    if (k < 0 || k >= bins) { clipped++; continue; }
    counts[k]++;
  }
  return { lo, hi, width, bins, counts, clipped, n: values.length,
           max: Math.max(1, ...counts) };
}

/** Edge list as flat arrays, ordered by the round the edge completes. */
export function buildEdges(bundle) {
  const nbr = bundle.neighbors;
  const counts = bundle.stitch_counts;
  const ri = bundle.round_index;
  const dec = bundle.decrease_flag, inc = bundle.increase_flag;
  const hRest = 1 / bundle.horizontal_gauge;
  const vRest = 1 / bundle.vertical_gauge;
  const a = [], b = [], rest = [], cls = [];

  for (let v = 0; v < bundle.n_stitches; v++) {
    const right = nbr[v][1], up = nbr[v][3];
    // Rings of 1 have no ring edge; rings of 2 would count theirs twice.
    const ring = counts[ri[v]];
    if (right >= 0 && right !== v && (ring > 2 || right > v)) {
      a.push(v); b.push(right); rest.push(hRest); cls.push(0);
    }
    if (up >= 0) {
      const shaping = dec[v] || dec[up] || inc[v] || inc[up];
      a.push(v); b.push(up); rest.push(vRest); cls.push(shaping ? 2 : 1);
    }
  }

  // Order by the later of the two rounds so the round slider can slice.
  const order = a.map((_, i) => i)
    .sort((i, j) => Math.max(ri[a[i]], ri[b[i]]) - Math.max(ri[a[j]], ri[b[j]]));
  const pairs = order.map((i) => [a[i], b[i]]);
  const restSorted = new Float64Array(order.map((i) => rest[i]));
  const clsSorted = new Uint8Array(order.map((i) => cls[i]));

  // Prefix count per round, for mesh.count when scrubbing.
  const endByRound = new Int32Array(counts.length);
  for (const i of order) endByRound[Math.max(ri[a[i]], ri[b[i]])]++;
  for (let r = 1; r < endByRound.length; r++) endByRound[r] += endByRound[r - 1];

  return { pairs, rest: restSorted, cls: clsSorted, endByRound };
}

export function edgeLengths(edges, positions) {
  const out = new Float64Array(edges.pairs.length);
  for (let i = 0; i < edges.pairs.length; i++) {
    const p = positions[edges.pairs[i][0]], q = positions[edges.pairs[i][1]];
    const dx = p[0] - q[0], dy = p[1] - q[1], dz = p[2] - q[2];
    out[i] = Math.hypot(dx, dy, dz);
  }
  return out;
}

/** Signed error relative to each edge's rest length. */
export function relativeError(edges, lengths) {
  const out = new Float64Array(lengths.length);
  for (let i = 0; i < lengths.length; i++) out[i] = lengths[i] / edges.rest[i] - 1;
  return out;
}

export function quantile(sorted, q) {
  if (!sorted.length) return 0;
  const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

export function summarize(values, rest) {
  const n = values.length;
  if (!n) return { n: 0 };
  let sum = 0;
  for (const v of values) sum += v;
  const mean = sum / n;
  let sq = 0;
  for (const v of values) sq += (v - mean) ** 2;
  const sorted = Float64Array.from(values).sort();
  return {
    n, mean, rest,
    median: quantile(sorted, 0.5),
    std: Math.sqrt(sq / n),
    min: sorted[0], max: sorted[n - 1],
    p2: quantile(sorted, 0.02), p98: quantile(sorted, 0.98),
  };
}

/** Split values by class, then bin all three series on one shared axis.
 *  mode "length" keeps each class's gauge for its reference line; mode
 *  "error" plots relative error, where every class shares the line at 0. */
export function histogram(edges, lengths, bins = 48, mode = "length") {
  const series = CLASSES.map(() => []);
  const restOf = CLASSES.map(() => 0);
  for (let i = 0; i < lengths.length; i++) {
    series[edges.cls[i]].push(lengths[i]);
    restOf[edges.cls[i]] = edges.rest[i];
  }

  const all = Float64Array.from(lengths).sort();
  let lo = quantile(all, 0.002), hi = quantile(all, 0.998);
  if (!(hi > lo)) { lo = Math.min(...all) * 0.9; hi = Math.max(...all) * 1.1 || 1; }
  const pad = (hi - lo) * 0.04;
  lo = mode === "error" ? lo - pad : Math.max(0, lo - pad);
  hi += pad;
  const width = (hi - lo) / bins;

  const counts = CLASSES.map(() => new Int32Array(bins));
  let clipped = 0;
  series.forEach((vals, s) => {
    for (const v of vals) {
      const k = Math.floor((v - lo) / width);
      if (k < 0 || k >= bins) { clipped++; continue; }
      counts[s][k]++;
    }
  });

  return {
    lo, hi, width, bins, counts, clipped,
    mode,
    stats: series.map((vals, s) => summarize(vals, mode === "error" ? 0 : restOf[s])),
    max: Math.max(1, ...counts.map((c) => Math.max(...c))),
  };
}
