// Stitch constructions the editor offers. A cell is "<color>[-<op>...]";
// the construction op (none for a plain knit) says how the stitch is
// worked, independent of its colour. This list drives the Chart tab's
// stitch buttons, the chart symbols and the Stitches tab, and mirrors
// GLYPHS in tools/chart_tex.py.
//
// symbol: SVG path in a 10 x 10 box, stroked in the cell's text colour.
// Decreases lean the way the stitch does (k2tog right "/", ssk left "\").
export const STITCHES = [
  {
    op: null, abbr: "k", name: "knit", kind: "basic",
    symbol: "",
    construction: "Knit 1. The default stitch: an empty cell on the chart.",
  },
  {
    op: "p", abbr: "p", name: "purl", kind: "basic",
    symbol: "M2.5 5 L7.5 5",
    construction: "Purl 1.",
  },
  {
    op: "k2tog", abbr: "k2tog", name: "knit 2 together", kind: "decrease",
    symbol: "M2 9 L8 1",
    construction: "Insert the right needle knitwise into the next 2 stitches at once and knit them " +
      "together. Right-leaning single decrease (−1).",
  },
  {
    op: "ssk", abbr: "ssk", name: "slip, slip, knit", kind: "decrease",
    symbol: "M2 1 L8 9",
    construction: "Slip the next 2 stitches knitwise, one at a time; insert the left needle into " +
      "the fronts of both and knit them together through the back loops. Left-leaning single " +
      "decrease (−1).",
  },
  {
    op: "cdd", abbr: "cdd", name: "centred double decrease", kind: "decrease",
    symbol: "M2 9 L5 1 L8 9 M5 9 L5 1",
    construction: "Slip 2 stitches together knitwise, knit 1, pass the 2 slipped stitches over " +
      "(psso). Vertical double decrease (−2); the centre stitch stays on top.",
  },
  {
    op: "co", abbr: "co", name: "cast on", kind: "increase",
    symbol: "M2.5 2 L2.5 6 A2.5 2.5 0 0 0 7.5 6 L7.5 2",
    construction: "Cast on 1 new stitch (e.g. backward loop) in a slot with no stitch below it; " +
      "starts a new column.",
  },
];

// Ops from older charts or typed by hand: drawn, but not offered as buttons.
export const LEGACY_SYMBOLS = {
  k3tog: "M2 9 L8 1 M5 9 L8 1",
  p2tog: "M2 9 L8 1 M2.6 3.4 h0.01",
  yo: "M5 2.2 a2.8 2.8 0 1 0 0.01 0",
};

export const SYMBOLS = {
  ...LEGACY_SYMBOLS,
  ...Object.fromEntries(STITCHES.filter((s) => s.op && s.symbol).map((s) => [s.op, s.symbol])),
};

export function symbolSvg(ops) {
  const d = ops.map((o) => SYMBOLS[o]).filter(Boolean).join(" ");
  return `<svg viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet" aria-hidden="true">` +
    `<path d="${d}" fill="none" stroke="currentColor" stroke-width="1.3" ` +
    `stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`;
}
