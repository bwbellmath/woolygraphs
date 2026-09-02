// Spherical decrease guide (after patterns/Sphere Hat Decs.xlsx).
//
// For each round above the equator, the ideal number of live stitches
// per slice is what a sphere of the given radius has at that latitude.
// guideCells outlines the two ends of that ideal width, centred in the
// pattern repeat, so the author can see where the decrease line should
// be while placing k2togs wherever the motif allows.

export function defaultParams(bundle) {
  const hg = bundle.horizontal_gauge, vg = bundle.vertical_gauge;
  const brim = bundle.stitch_counts[0];
  return {
    slices: bundle.repeats,
    width: bundle.chart_width,
    hg, vg,
    radius: +(brim / hg / (2 * Math.PI)).toFixed(3),
    equator: Math.max(0, bundle.crown_start_round - 1),
  };
}

// Per-round ideal slice widths from the equator up: [{round, width, theta}].
export function idealWidths(p, height) {
  const out = [];
  for (let r = p.equator; r < height; r++) {
    const theta = Math.PI / 2 - (r - p.equator) / (p.vg * p.radius);
    if (theta <= 0) break;
    const width = Math.round(2 * Math.PI * p.radius * Math.sin(theta) * p.hg / p.slices);
    if (width <= 0) break;
    out.push({ round: r, width, theta });
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
