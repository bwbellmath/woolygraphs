// Spherical decrease guide (after patterns/Sphere Hat Decs.xlsx).
//
// For each round above the equator (the shaping row), the ideal number
// of live stitches per slice is what a sphere of the given radius has at
// that latitude.
// guideCells outlines the two ends of that ideal width, centred in the
// pattern repeat, so the author can see where the decrease line should
// be while placing k2togs (or centred k3togs) wherever the motif allows.

// The crown is a hemisphere whose equator is the shaping row. Its radius
// is either fitted to the layout (in app.js) or that row's circumference
// (stitches around all slices / st per inch) over 2pi; the leaves -- one per slice -- close it in a quarter
// meridian, (pi/2) R inches, i.e. round((pi/2) R vg) rounds.
export const sphereRadius = (stitchesAround, hg) => stitchesAround / hg / (2 * Math.PI);
export const leafRounds = (p) => Math.round((Math.PI / 2) * p.radius * p.vg);

// Default shaping row (1-based sheet row) for a chart that has not set
// one: the round before its first decrease.
export function defaultShapingRow(bundle, chart) {
  const H = chart?.cells?.length ?? bundle.n_chart_rounds;
  return Math.max(1, Math.min(H, bundle.crown_start_round));
}

// Widest round of the chart as knit: {round, stitches, inches} around all
// slices. perSlice[r] is the live count of one repeat on round r.
export function widestRound(perSlice, p) {
  let round = 0;
  perSlice.forEach((n, r) => { if (n > perSlice[round]) round = r; });
  const stitches = (perSlice[round] ?? 0) * p.slices;
  return { round, stitches, inches: stitches / p.hg };
}

// Stitches one decrease removes: a k2tog takes 2 to 1, a k3tog 3 to 1.
export const DECREASE_STEP = { k2tog: 1, k3tog: 2 };

// Per-round ideal slice widths from the equator up:
// [{round, width, theta, decs}], decs = decreases this round per slice.
// With k3tog every change is a multiple of 2, so the width keeps the
// equator width's parity and the outline narrows by one on each side.
export function idealWidths(p, height) {
  const step = DECREASE_STEP[p.dec] ?? 1;
  const perSlice = (theta) => 2 * Math.PI * p.radius * Math.sin(theta) * p.hg / p.slices;
  const w0 = Math.round(perSlice(Math.PI / 2));
  const out = [];
  let prev = w0;
  for (let r = p.equator; r < height; r++) {
    const theta = Math.PI / 2 - (r - p.equator) / (p.vg * p.radius);
    if (theta <= 0) break;
    const exact = perSlice(theta);
    const width = Math.min(prev, w0 - step * Math.round((w0 - exact) / step));
    if (width <= 0) break;
    out.push({ round: r, width, theta, decs: (prev - width) / step });
    prev = width;
  }
  return out;
}

// Set of "r,c" keys for the outlined boundary cells.
export function guideCells(p, height) {
  const set = new Set();
  const center = p.width / 2 + 0.5; // 1-based centreline
  for (const { round, width } of idealWidths(p, height)) {
    const left = center - width / 2, right = center + width / 2;
    const first = Math.floor(left) + 1, last = Math.floor(right); // 1-based inclusive
    if (first < 1 || last > p.width) continue;
    set.add(`${round},${first - 1}`);
    set.add(`${round},${last - 1}`);
  }
  return set;
}
