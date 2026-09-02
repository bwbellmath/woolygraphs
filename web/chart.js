// Spreadsheet grid for one pattern repeat. Pure DOM, no three.js.
//
// Cell grammar mirrors tools/chart.py: blank = no stitch; otherwise
// "<color>[-<op>...]" with color f (foreground) or b (background).
// Rows are stored in knit order (round 0 first) but displayed as worn,
// crown at the top and cast-on at the bottom.

export const COLORS = ["b", "f"];
export const DECREASE_OPS = new Set(["k2tog", "ssk", "k3tog", "cdd", "p2tog"]);
export const INCREASE_OPS = new Set(["co", "kfb", "m1", "m1l", "m1r", "yo", "pfb"]);

export function parseCell(text) {
  const parts = String(text ?? "").trim().toLowerCase().split("-").map((p) => p.trim());
  if (parts.length === 1 && parts[0] === "") return null;
  const color = COLORS.indexOf(parts[0]);
  if (color < 0) return { bad: true, text };
  return { color, ops: parts.slice(1).filter(Boolean) };
}

const key = (r, c) => `${r},${c}`;

export class ChartGrid {
  constructor(container, { onChange, onHover } = {}) {
    this.container = container;
    this.onChange = onChange ?? (() => {});
    this.onHover = onHover ?? (() => {});
    this.cells = [];
    this.readOnly = false;
    this.guide = new Set();
    this.anchor = null; // {r, c}
    this.cur = null;
    this.editing = null; // input element
    this.hl = null;
    this.equator = -1;
    this.undoStack = [];
    this.redoStack = [];
    this.onHistory = () => {};
    this.el = document.createElement("div");
    this.el.className = "grid";
    container.appendChild(this.el);
    this.cellEls = new Map();
    this.#bind();
  }

  get height() { return this.cells.length; }
  get width() { return this.cells[0]?.length ?? 0; }

  setData(cells) {
    const w = Math.max(0, ...cells.map((r) => r.length));
    this.cells = cells.map((r) => [...r, ...Array(w - r.length).fill("")]);
    this.#render();
  }

  getData() { return this.cells.map((r) => [...r]); }

  setGuide(set) {
    for (const k of this.guide) this.cellEls.get(k)?.classList.remove("guide");
    this.guide = set;
    for (const k of this.guide) this.cellEls.get(k)?.classList.add("guide");
  }

  setEquator(r) {
    this.equator = r;
    this.el.querySelectorAll(".rh").forEach((h) => h.classList.toggle("eq", +h.dataset.r === r));
  }

  // Outline the cell that corresponds to a hovered stitch (or clear).
  highlight(r, c) {
    if (this.hl) this.cellEls.get(this.hl)?.classList.remove("hl");
    this.hl = r == null ? null : key(r, c);
    if (this.hl) this.cellEls.get(this.hl)?.classList.add("hl");
  }

  // ---- rendering --------------------------------------------------
  #render() {
    const H = this.height, W = this.width;
    this.el.innerHTML = "";
    this.cellEls.clear();
    this.el.style.gridTemplateColumns = `32px repeat(${W}, var(--cw))`;
    const frag = document.createDocumentFragment();
    frag.appendChild(Object.assign(document.createElement("div"), { className: "hd" }));
    for (let c = 0; c < W; c++) {
      const h = document.createElement("div");
      h.className = "hd"; h.textContent = c + 1; h.dataset.c = c;
      frag.appendChild(h);
    }
    for (let r = H - 1; r >= 0; r--) {
      const rh = document.createElement("div");
      rh.className = "rh" + (r === this.equator ? " eq" : "");
      rh.dataset.r = r; rh.textContent = r + 1; rh.title = `round ${r + 1}`;
      frag.appendChild(rh);
      for (let c = 0; c < W; c++) {
        const d = document.createElement("div");
        d.dataset.r = r; d.dataset.c = c;
        this.cellEls.set(key(r, c), d);
        this.#paint(d, r, c);
        frag.appendChild(d);
      }
    }
    this.el.appendChild(frag);
    this.#paintSelection();
  }

  #paint(d, r, c) {
    const text = this.cells[r][c];
    const p = parseCell(text);
    let cls = "c";
    let label = text;
    if (p === null) { label = ""; }
    else if (p.bad) { cls += " bad"; }
    else {
      cls += " " + COLORS[p.color];
      if (p.ops.length) { cls += " op"; label = p.ops.join("-"); }
    }
    if (this.guide.has(key(r, c))) cls += " guide";
    d.className = cls;
    d.textContent = label;
    d.title = text ? `r${r + 1} c${c + 1}: ${text}` : `r${r + 1} c${c + 1}`;
  }

  #paintSelection() {
    this.el.querySelectorAll(".sel, .cur").forEach((e) => e.classList.remove("sel", "cur"));
    if (!this.cur) return;
    for (const [r, c] of this.#selectedCells()) this.cellEls.get(key(r, c))?.classList.add("sel");
    this.cellEls.get(key(this.cur.r, this.cur.c))?.classList.add("cur");
  }

  #selectedCells() {
    if (!this.cur) return [];
    const a = this.anchor ?? this.cur;
    const out = [];
    for (let r = Math.min(a.r, this.cur.r); r <= Math.max(a.r, this.cur.r); r++)
      for (let c = Math.min(a.c, this.cur.c); c <= Math.max(a.c, this.cur.c); c++)
        out.push([r, c]);
    return out;
  }

  // ---- mutation ---------------------------------------------------
  #set(r, c, text) {
    if (r < 0 || r >= this.height || c < 0 || c >= this.width) return false;
    text = String(text ?? "").trim();
    if (this.cells[r][c] === text) return false;
    this.cells[r][c] = text;
    this.#paint(this.cellEls.get(key(r, c)), r, c);
    return true;
  }

  #commit(before) {
    if (before) {
      this.undoStack.push(before);
      if (this.undoStack.length > 200) this.undoStack.shift();
      this.redoStack.length = 0;
    }
    this.onChange(this.getData());
    this.onHistory(this.undoStack.length > 0, this.redoStack.length > 0);
  }

  get canUndo() { return this.undoStack.length > 0; }
  get canRedo() { return this.redoStack.length > 0; }

  #restore(cells) {
    const cur = this.cur;
    this.cells = cells;
    this.#render();
    if (cur) this.select(Math.min(cur.r, this.height - 1), Math.min(cur.c, this.width - 1));
    this.#commit(null);
  }

  undo() {
    if (this.editing) this.endEdit(false);
    if (!this.undoStack.length) return;
    this.redoStack.push(this.getData());
    this.#restore(this.undoStack.pop());
  }

  redo() {
    if (this.editing) this.endEdit(false);
    if (!this.redoStack.length) return;
    this.undoStack.push(this.getData());
    this.#restore(this.redoStack.pop());
  }

  // Loading a new file starts a fresh history.
  clearHistory() {
    this.undoStack.length = 0;
    this.redoStack.length = 0;
    this.onHistory(false, false);
  }

  fillSelection(text) {
    if (this.readOnly) return;
    const before = this.getData();
    let changed = false;
    for (const [r, c] of this.#selectedCells()) changed = this.#set(r, c, text) || changed;
    this.#paintSelection();
    if (changed) this.#commit(before);
  }

  // Paste a TSV/CSV block with its top-left at the current cell. Rows in
  // the clipboard run top-to-bottom on screen, i.e. decreasing round.
  pasteBlock(text) {
    if (this.readOnly || !this.cur) return;
    const lines = text.replace(/\r/g, "").split("\n");
    if (lines.length && lines.at(-1) === "") lines.pop();
    const before = this.getData();
    let changed = false;
    lines.forEach((line, i) => {
      const vals = line.includes("\t") ? line.split("\t") : line.split(",");
      vals.forEach((v, j) => {
        changed = this.#set(this.cur.r - i, this.cur.c + j, v) || changed;
      });
    });
    if (changed) this.#commit(before);
  }

  copySelection() {
    if (!this.cur) return "";
    const a = this.anchor ?? this.cur;
    const rows = [];
    for (let r = Math.max(a.r, this.cur.r); r >= Math.min(a.r, this.cur.r); r--) {
      const row = [];
      for (let c = Math.min(a.c, this.cur.c); c <= Math.max(a.c, this.cur.c); c++) row.push(this.cells[r][c]);
      rows.push(row.join("\t"));
    }
    return rows.join("\n");
  }

  // ---- rows / columns -------------------------------------------------
  // r is a round index (0 = cast-on); "above" on screen is r + 1.
  insertRow(at) {
    if (this.readOnly) return;
    const before = this.getData();
    at = Math.max(0, Math.min(this.height, at));
    this.cells.splice(at, 0, Array(this.width).fill(""));
    this.#render();
    this.select(at, this.cur?.c ?? 0);
    this.#commit(before);
  }

  deleteRow(r) {
    if (this.readOnly || this.height <= 1 || r < 0 || r >= this.height) return;
    const before = this.getData();
    this.cells.splice(r, 1);
    this.#render();
    this.select(Math.min(r, this.height - 1), this.cur?.c ?? 0);
    this.#commit(before);
  }

  insertCol(at) {
    if (this.readOnly) return;
    const before = this.getData();
    at = Math.max(0, Math.min(this.width, at));
    for (const row of this.cells) row.splice(at, 0, "");
    this.#render();
    this.select(this.cur?.r ?? 0, at);
    this.#commit(before);
  }

  deleteCol(c) {
    if (this.readOnly || this.width <= 1 || c < 0 || c >= this.width) return;
    const before = this.getData();
    for (const row of this.cells) row.splice(c, 1);
    this.#render();
    this.select(this.cur?.r ?? 0, Math.min(c, this.width - 1));
    this.#commit(before);
  }

  #showMenu(x, y, r, c) {
    this.#hideMenu();
    const items = [
      ["Insert round above", () => this.insertRow(r + 1)],
      ["Insert round below", () => this.insertRow(r)],
      ["Delete round", () => this.deleteRow(r)],
      null,
      ["Insert column left", () => this.insertCol(c)],
      ["Insert column right", () => this.insertCol(c + 1)],
      ["Delete column", () => this.deleteCol(c)],
    ];
    const menu = document.createElement("div");
    menu.className = "ctxmenu";
    for (const it of items) {
      if (!it) { menu.appendChild(Object.assign(document.createElement("div"), { className: "sep" })); continue; }
      const b = document.createElement("button");
      b.textContent = it[0];
      b.onclick = () => { this.#hideMenu(); it[1](); };
      menu.appendChild(b);
    }
    menu.style.left = `${Math.min(x, innerWidth - 190)}px`;
    menu.style.top = `${Math.min(y, innerHeight - 200)}px`;
    document.body.appendChild(menu);
    this.menu = menu;
  }

  #hideMenu() {
    this.menu?.remove();
    this.menu = null;
  }

  // ---- selection & editing ------------------------------------------
  select(r, c, extend = false) {
    r = Math.max(0, Math.min(this.height - 1, r));
    c = Math.max(0, Math.min(this.width - 1, c));
    if (!extend || !this.cur) this.anchor = { r, c };
    this.cur = { r, c };
    this.#paintSelection();
    this.cellEls.get(key(r, c))?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  startEdit(initial) {
    if (this.readOnly || !this.cur || this.editing) return;
    const d = this.cellEls.get(key(this.cur.r, this.cur.c));
    const input = document.createElement("input");
    input.value = initial ?? this.cells[this.cur.r][this.cur.c];
    d.appendChild(input);
    this.editing = input;
    input.focus();
    if (initial == null) input.select();
    else input.setSelectionRange(input.value.length, input.value.length);
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); this.endEdit(true); this.select(this.cur.r - 1, this.cur.c); }
      else if (e.key === "Tab") { e.preventDefault(); this.endEdit(true); this.select(this.cur.r, this.cur.c + (e.shiftKey ? -1 : 1)); }
      else if (e.key === "Escape") { e.preventDefault(); this.endEdit(false); }
      else if (e.key.startsWith("Arrow") && initial != null) {
        // Typing then arrowing behaves like Excel: commit and move.
        e.preventDefault(); this.endEdit(true); this.#arrow(e.key, false);
      }
    });
    input.addEventListener("blur", () => this.endEdit(true));
  }

  endEdit(commit) {
    const input = this.editing;
    if (!input) return;
    this.editing = null;
    const { r, c } = this.cur;
    const value = input.value;
    const before = this.getData();
    input.remove();
    if (commit && this.#set(r, c, value)) this.#commit(before);
    else this.#paint(this.cellEls.get(key(r, c)), r, c);
    this.#paintSelection();
    this.container.focus({ preventScroll: true });
  }

  #arrow(k, extend) {
    const { r, c } = this.cur;
    // Screen "up" is a higher round number.
    if (k === "ArrowUp") this.select(r + 1, c, extend);
    else if (k === "ArrowDown") this.select(r - 1, c, extend);
    else if (k === "ArrowLeft") this.select(r, c - 1, extend);
    else if (k === "ArrowRight") this.select(r, c + 1, extend);
  }

  #bind() {
    const el = this.el, wrap = this.container;
    let dragging = false;
    el.addEventListener("pointerdown", (e) => {
      const d = e.target.closest(".c");
      if (!d || e.button !== 0) return;
      if (this.editing) this.endEdit(true);
      this.select(+d.dataset.r, +d.dataset.c, e.shiftKey);
      dragging = true;
      wrap.focus({ preventScroll: true });
      e.preventDefault();
    });
    el.addEventListener("pointerover", (e) => {
      const d = e.target.closest(".c");
      if (!d) return;
      if (dragging) this.select(+d.dataset.r, +d.dataset.c, true);
      this.onHover(+d.dataset.r, +d.dataset.c);
    });
    el.addEventListener("pointerleave", () => this.onHover(null, null));
    addEventListener("pointerup", () => (dragging = false));
    el.addEventListener("contextmenu", (e) => {
      const d = e.target.closest(".c, .rh, .hd");
      if (!d || this.readOnly) return;
      e.preventDefault();
      const r = d.dataset.r != null ? +d.dataset.r : (this.cur?.r ?? this.height - 1);
      const c = d.dataset.c != null ? +d.dataset.c : (this.cur?.c ?? 0);
      if (d.classList.contains("c")) this.select(r, c);
      this.#showMenu(e.clientX, e.clientY, r, c);
    });
    addEventListener("pointerdown", (e) => { if (this.menu && !this.menu.contains(e.target)) this.#hideMenu(); });
    addEventListener("keydown", (e) => { if (e.key === "Escape") this.#hideMenu(); });
    el.addEventListener("dblclick", (e) => {
      if (e.target.closest(".c")) this.startEdit();
    });
    wrap.addEventListener("keydown", (e) => {
      if (this.editing || !this.cur) return;
      const meta = e.metaKey || e.ctrlKey;
      if (e.key.startsWith("Arrow")) { e.preventDefault(); this.#arrow(e.key, e.shiftKey); }
      else if (e.key === "Enter" || e.key === "F2") { e.preventDefault(); this.startEdit(); }
      else if (e.key === "Tab") { e.preventDefault(); this.select(this.cur.r, this.cur.c + (e.shiftKey ? -1 : 1)); }
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); this.fillSelection(""); }
      else if (meta && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); }
      else if (meta && e.key.toLowerCase() === "y") { e.preventDefault(); this.redo(); }
      else if (meta && e.key.toLowerCase() === "a") {
        e.preventDefault(); this.anchor = { r: 0, c: 0 }; this.select(this.height - 1, this.width - 1, true);
      }
      else if (meta && e.key.toLowerCase() === "c") {
        e.preventDefault(); navigator.clipboard?.writeText(this.copySelection());
      }
      else if (!meta && e.key.length === 1) { e.preventDefault(); this.startEdit(e.key); }
    });
    wrap.addEventListener("paste", (e) => {
      if (this.editing) return;
      const text = e.clipboardData?.getData("text/plain");
      if (text) { e.preventDefault(); this.pasteBlock(text); }
    });
  }
}
