// Key for the 3D view, drawn on a 2D canvas so the bar under the view and
// a saved image are the same pixels. A spec is
//   { swatches: [{ color, label }], ramp: { title, scale, lo, zero, hi } | null }
// swatches: the flat colours on screen (fg / bg, shaping, ...); ramp: an
// active heatmap, strainColor over -scale..+scale with labelled ticks.

import { strainColor } from "./metrics.js";

const FONT = '-apple-system, "Segoe UI", Helvetica, Arial, sans-serif';
const BG = "#14161a", TEXT = "#d7dae0", MUTED = "#8b93a1", RULE = "#2c313a";
const PAD = 10, SW_ROW = 22, RAMP_ROW = 50;

export function scaleBarHeight(spec) {
  const rows = (spec.swatches.length ? SW_ROW : 0) + (spec.ramp ? RAMP_ROW : 0);
  return rows ? rows + 2 * PAD - 4 : 0;
}

const pct = (v, scale) => {
  const s = (Math.abs(v) * 100).toFixed(scale < 0.1 ? 1 : 0);
  return v === 0 ? "0" : `${v < 0 ? "−" : "+"}${s}%`;
};

// Draw into ctx at (0, y0), width w in CSS pixels (ctx already scaled).
export function drawScaleBar(ctx, w, spec, y0 = 0) {
  const h = scaleBarHeight(spec);
  ctx.save();
  ctx.translate(0, y0);
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = RULE;
  ctx.fillRect(0, 0, w, 1);
  ctx.textBaseline = "middle";
  let y = PAD - 2;

  if (spec.swatches.length) {
    ctx.font = `12px ${FONT}`;
    let x = PAD;
    for (const { color, label } of spec.swatches) {
      ctx.fillStyle = color;
      ctx.fillRect(x, y + 5, 12, 12);
      ctx.strokeStyle = "rgba(255,255,255,0.25)";
      ctx.strokeRect(x + 0.5, y + 5.5, 11, 11);
      ctx.fillStyle = TEXT;
      ctx.fillText(label, x + 17, y + 11);
      x += 17 + ctx.measureText(label).width + 16;
    }
    y += SW_ROW;
  }

  const r = spec.ramp;
  if (r) {
    ctx.font = `600 12px ${FONT}`;
    ctx.fillStyle = TEXT;
    ctx.fillText(r.title, PAD, y + 7);
    const barX = PAD, barW = Math.max(120, w - 2 * PAD), barY = y + 17, barH = 10;
    const grad = ctx.createLinearGradient(barX, 0, barX + barW, 0);
    const rgb = [0, 0, 0];
    for (let i = 0; i <= 32; i++) {
      const t = i / 32;
      strainColor((2 * t - 1) * r.scale, r.scale, rgb);
      grad.addColorStop(t, `rgb(${rgb.map((v) => Math.round(v * 255)).join(",")})`);
    }
    ctx.fillStyle = grad;
    ctx.fillRect(barX, barY, barW, barH);
    ctx.strokeStyle = RULE;
    ctx.strokeRect(barX + 0.5, barY + 0.5, barW - 1, barH - 1);

    // Ticks at -s, -s/2, 0, +s/2, +s; the ends name what the sign means
    // and that the colour saturates beyond them.
    ctx.font = `11px ${FONT}`;
    const ticks = barW < 420 ? [-1, 0, 1] : [-1, -0.5, 0, 0.5, 1];
    ticks.forEach((f) => {
      const x = barX + (f + 1) / 2 * barW;
      ctx.fillStyle = MUTED;
      ctx.fillRect(Math.round(x) - (f === 1 ? 1 : 0), barY + barH, 1, 4);
      let label = pct(f * r.scale, r.scale);
      if (f === -1) label = `≤ ${label} ${r.lo}`;
      else if (f === 1) label = `≥ ${label} ${r.hi}`;
      else if (f === 0) label = `0 · ${r.zero}`;
      ctx.textAlign = f === -1 ? "left" : f === 1 ? "right" : "center";
      ctx.fillStyle = f === 0 ? TEXT : MUTED;
      ctx.fillText(label, x, barY + barH + 12);
    });
    ctx.textAlign = "left";
  }
  ctx.restore();
  return h;
}
