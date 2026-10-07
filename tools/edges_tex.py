#!/usr/bin/env python
"""LaTeX write-up of the editor's Edges tab: is the layout on gauge?

The browser sends what the tab shows -- the plots as PNG (and SVG), the
3D view with its colour key, a picture of the whole tab, and the
per-series edge statistics -- and the server adds the optimizer's own
state (iterations run, weights, last loss values). ``build_zip`` packs
it all into one folder, ``<name>_edges/``:

  edges.tex          drop-in section: \\input{<name>_edges/edges.tex}
                     (needs graphicx, booktabs, amsmath, xcolor)
  objective.tex      the optimizer's objective, with this run's weights
  stats.tex          the edge-length table
  edges_report.tex   a standalone document around edges.tex
  *.png, *.svg       the figures

The objective is stated to match hat_optimizer.HatOptimizer.losses.
"""

import base64
import io
import re
import zipfile

PREAMBLE_PACKAGES = (r"\usepackage{graphicx}", r"\usepackage{booktabs}",
                     r"\usepackage{amsmath}", r"\usepackage{xcolor}")


def tex_escape(s):
    s = str(s)
    return (s.replace("\\", r"\textbackslash{}").replace("_", r"\_")
            .replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")
            .replace("$", r"\$").replace("{", r"\{").replace("}", r"\}")
            .replace("~", r"\textasciitilde{}").replace("^", r"\^{}"))


def _num(v, fmt="{:g}"):
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return "--"


# How each optimizer scheme minimises the objective (hat_optimizer.py,
# implicit_flow.py; docs/better_flow.tex).
SCHEME_TEXT = {
    "direct": r"with Adam (one explicit gradient step per iteration)",
    "local_global": (r"by local/global Laplacian solves: each iteration "
                     r"solves $(L_W+\mu L_0)\,\Delta X=-\nabla\mathcal{L}$ with "
                     r"$L_W$ the edge-stress Laplacian, $w_e=2\lambda_{\mathrm{gauge}}"
                     r"/(|E|\,\ell_e^2)$, then line-searches $\mathcal{L}$"),
    "gauss_newton": (r"by Laplacian-damped Gauss--Newton: each iteration "
                     r"solves $(2J^\top J+\mu\,L_0\otimes I_3)\,\Delta x="
                     r"-\nabla\mathcal{L}$, $J$ the Jacobian of the gauge and "
                     r"smoothing residuals, then line-searches $\mathcal{L}$"),
}


def objective_tex(weights=None, lr=None, used=True, scheme="direct"):
    """The smoothing objective as a LaTeX block. With weights (and lr),
    a line giving the values: the ones this layout was optimized with
    (used), or the editor's settings when it has not been optimized."""
    out = [r"\begin{align}",
           r"  \mathcal{L} &= \lambda_{\mathrm{gauge}}\,\mathcal{L}_{\mathrm{gauge}}"
           r" + \lambda_{\mathrm{inflate}}\,\mathcal{L}_{\mathrm{inflate}}"
           r" + \lambda_{\mathrm{smooth}}\,\mathcal{L}_{\mathrm{smooth}}"
           r" \label{eq:objective}\\",
           r"  \mathcal{L}_{\mathrm{gauge}} &= \frac{1}{|E|}\sum_{(i,j)\in E}"
           r"\left(\frac{\lVert\mathbf{p}_i-\mathbf{p}_j\rVert}{\ell_{ij}}-1\right)^{2},"
           r" \qquad \ell_{ij}=\begin{cases}1/g_h & \text{ring edge}\\"
           r" 1/g_v & \text{column edge}\end{cases} \label{eq:gauge}\\",
           r"  \mathcal{L}_{\mathrm{inflate}} &= \frac{1}{N}\sum_{i=1}^{N}"
           r"\frac{1}{\lVert\mathbf{p}_i-\bar{\mathbf{p}}\rVert+\varepsilon},"
           r" \qquad \bar{\mathbf{p}}=\frac{1}{N}\sum_{i=1}^{N}\mathbf{p}_i,"
           r"\quad \varepsilon=10^{-3} \label{eq:inflate}\\",
           r"  \mathcal{L}_{\mathrm{smooth}} &= \frac{1}{|V|}\sum_{v\in V}"
           r"\left(\Omega_v-\bar{\Omega}_v\right)^{2},"
           r" \qquad \bar{\Omega}_v=\frac{1}{|N_v|}\sum_{u\in N_v}\Omega_u"
           r" \label{eq:smooth}",
           r"\end{align}",
           r"where $\mathbf{p}_i$ is the position of stitch $i$ (inches), "
           r"$g_h$ and $g_v$ are the horizontal (stitches per inch) and "
           r"vertical (rounds per inch) gauge, and $E$ holds, for every "
           r"stitch, the edge to its right-hand neighbour in the round and "
           r"the edge to the stitch above it in its column. The centroid "
           r"$\bar{\mathbf{p}}$ is held constant within each step (no "
           r"gradient flows through it). The solid angle at stitch $v$ is "
           r"that of the fan of unit vectors to its right, up, left and "
           r"down neighbours $\hat{\mathbf{r}},\hat{\mathbf{u}},"
           r"\hat{\mathbf{l}},\hat{\mathbf{d}}$, split into two triangles,",
           r"\begin{equation}",
           r"  \Omega_v = \bigl|\Omega(\hat{\mathbf{r}},\hat{\mathbf{u}},\hat{\mathbf{l}})\bigr|"
           r" + \bigl|\Omega(\hat{\mathbf{r}},\hat{\mathbf{l}},\hat{\mathbf{d}})\bigr|,"
           r" \qquad \Omega(\mathbf{a},\mathbf{b},\mathbf{c}) = 2\,\operatorname{atan2}"
           r"\bigl(\mathbf{a}\cdot(\mathbf{b}\times\mathbf{c}),\;"
           r"1+\mathbf{a}\cdot\mathbf{b}+\mathbf{b}\cdot\mathbf{c}+\mathbf{c}\cdot\mathbf{a}\bigr)",
           r"  \label{eq:solidangle}",
           r"\end{equation}",
           r"(Van Oosterom--Strackee). $V$ is the set of stitches with all "
           r"four neighbours and $N_v$ the neighbours of $v$ that are in $V$ "
           r"(stitches with none are left out). $\mathcal{L}$ is minimised "
           + SCHEME_TEXT.get(scheme, SCHEME_TEXT["direct"]) +
           r" over all $\mathbf{p}_i$ except the cast-on round, which is "
           r"held fixed so the fabric hangs from it."]
    if weights:
        vals = ", ".join(
            rf"$\lambda_{{\mathrm{{{k}}}}}={_num(weights.get(k))}$"
            for k in ("gauge", "inflate", "smooth"))
        lr_text = (rf", learning rate $\eta={_num(lr)}$"
                   if lr is not None and scheme == "direct" else "")
        out.append(rf"This layout used {vals}{lr_text}." if used else
                   rf"The layout has not been optimized; the editor's "
                   rf"settings are {vals}{lr_text}.")
    return "\n".join(out) + "\n"


def stats_tex(stats, mode="length"):
    """Booktabs table of the per-series edge statistics (the Edges tab
    table): edges, gauge, mean, median, std, mean vs gauge."""
    unit = "" if mode == "error" else " (in)"
    rows = [r"\begin{tabular}{@{}lrrrrrr@{}}", r"\toprule",
            rf"series & edges & gauge{unit} & mean{unit} & median{unit} & "
            rf"std dev{unit} & mean vs gauge \\", r"\midrule"]
    for s in stats:
        if not s.get("n"):
            continue
        color = str(s.get("color", "#000000")).lstrip("#").upper()
        rest, mean = s.get("rest") or 0, s.get("mean") or 0
        off = (mean / rest - 1) * 100 if rest else 0.0
        swatch = (rf"\textcolor[HTML]{{{color}}}{{\rule{{0.7em}}{{0.7em}}}}\ "
                  if re.fullmatch(r"[0-9A-F]{6}", color) else "")
        rows.append(
            rf"{swatch}{tex_escape(s.get('name', ''))} "
            rf"{{\footnotesize ({tex_escape(s.get('short', ''))})}} & "
            rf"{int(s['n']):,} & {_num(rest, '{:.4f}')} & "
            rf"{_num(mean, '{:.4f}')} & {_num(s.get('median'), '{:.4f}')} & "
            rf"{_num(s.get('std'), '{:.4f}')} & ${off:+.2f}\%$ \\")
    rows += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(rows) + "\n"


def edges_tex(report, files):
    """The drop-in section. ``files``: names of the figures in the zip."""
    name = tex_escape(report.get("name", "hat"))
    folder = f"{report.get('name', 'hat')}_edges/"
    opt = report.get("optimizer") or {}
    gauge = report.get("gauge") or {}
    hg, vg = gauge.get("horizontal"), gauge.get("vertical")
    scale = float(report.get("strain_scale") or 0.25)
    iters = opt.get("iterations")
    source = ("the initial helix" if not iters and not report.get("layout_source")
              else f"{iters:,} optimizer iterations" if iters
              else tex_escape(report["layout_source"]))
    out = [
        "% Edge-length report for " + str(report.get("name", "hat")) +
        ", exported from the WoolyGraphs hat editor.",
        "% Needs \\usepackage{graphicx,booktabs,amsmath,xcolor}.",
        "% From the folder above this one: \\input{" + folder + "edges.tex}",
        r"\providecommand{\edgesdir}{" + folder + "}",
        rf"\subsection{{Edge lengths: {name}}}",
        rf"The layout ({source}) has {int(report.get('n_stitches') or 0):,} "
        rf"stitches in {int(report.get('repeats') or 1)} pattern repeats at a "
        rf"gauge of $g_h={_num(hg)}$ stitches and $g_v={_num(vg)}$ rounds per "
        r"inch. Every edge the optimizer works on is measured: ring edges "
        r"(each stitch to its right-hand neighbour, rest length $1/g_h$), "
        r"column edges (each stitch to the one above it, $1/g_v$), and column "
        r"edges touching a decrease or a cast-on, counted separately as "
        r"shaping since they have no reason to sit at plain column gauge.",
        "",
    ]
    if "view.png" in files:
        out += [r"\begin{figure}[htbp]", r"  \centering",
                r"  \includegraphics[width=\linewidth]{\edgesdir view.png}",
                r"  \caption{The layout as shown in the editor, with its colour key.}",
                r"  \label{fig:edges-view}", r"\end{figure}", ""]
    if "histogram.png" in files:
        what = ("relative to its own gauge" if report.get("mode") == "error"
                else "in inches, with each series' gauge dashed")
        log = " Counts are on a log scale." if report.get("log") else ""
        clipped = int(report.get("clipped") or 0)
        clip = (f" {clipped:,} edges fall outside the plotted range (clipped "
                "at the 0.2/99.8 percentiles); the statistics use every edge."
                if clipped else "")
        out += [r"\begin{figure}[htbp]", r"  \centering",
                r"  \includegraphics[width=\linewidth]{\edgesdir histogram.png}",
                rf"  \caption{{Distribution of edge lengths by series, {what}.{log}{clip}}}",
                r"  \label{fig:edges-hist}", r"\end{figure}", ""]
    if "deviation.png" in files:
        out += [r"\begin{figure}[htbp]", r"  \centering",
                r"  \includegraphics[width=\linewidth]{\edgesdir deviation.png}",
                r"  \caption{All edges by deviation from gauge, "
                r"$\lVert\mathbf{p}_i-\mathbf{p}_j\rVert/\ell_{ij}-1$, each bar "
                r"coloured as the 3D strain heatmap colours that deviation "
                rf"(saturating at $\pm{scale * 100:g}\%$).}}",
                r"  \label{fig:edges-dev}", r"\end{figure}", ""]
    out += [r"\begin{table}[htbp]", r"  \centering", r"  \small",
            r"  \input{\edgesdir stats.tex}",
            r"  \caption{Edge lengths by series: generated mean, median and "
            r"standard deviation against the gauge length.}",
            r"  \label{tab:edges}", r"\end{table}", "",
            r"\paragraph{Optimizer objective.}",
            r"\input{\edgesdir objective.tex}"]
    last = opt.get("last") or {}
    if iters and last:
        parts = ", ".join(rf"$\mathcal{{L}}_{{\mathrm{{{k}}}}}={_num(last[k], '{:.4g}')}$"
                          for k in ("gauge", "inflate", "smooth") if k in last)
        out.append(rf"After {iters:,} iterations, {parts}"
                   + (rf" and $\mathcal{{L}}={_num(last['total'], '{:.4g}')}$"
                      if "total" in last else "") + ".")
    return "\n".join(out) + "\n"


def report_tex():
    return "\n".join([
        r"\documentclass[11pt]{article}",
        r"\usepackage[letterpaper,margin=1in]{geometry}",
        *PREAMBLE_PACKAGES,
        r"\newcommand{\edgesdir}{}",
        r"\begin{document}",
        r"\input{edges.tex}",
        r"\end{document}", ""])


def _decode(data):
    """A data: URL or raw text -> bytes."""
    if isinstance(data, str) and data.startswith("data:"):
        head, _, body = data.partition(",")
        return base64.b64decode(body) if ";base64" in head else body.encode()
    return data.encode() if isinstance(data, str) else bytes(data)


def build_zip(report):
    """report: the browser's payload plus "optimizer"; returns zip bytes."""
    name = re.sub(r"[^\w.-]+", "_", str(report.get("name") or "hat"))
    report = {**report, "name": name}
    folder = f"{name}_edges/"
    images = {k: v for k, v in (report.get("images") or {}).items()
              if re.fullmatch(r"[\w.-]+\.(png|svg)", k)}
    opt = report.get("optimizer") or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, data in images.items():
            z.writestr(folder + fname, _decode(data))
        if opt.get("iterations"):
            weights, lr, used = opt.get("weights"), opt.get("lr"), True
            scheme = opt.get("scheme") or "direct"
        else:
            form = report.get("settings") or {}
            weights, lr, used = form.get("weights"), form.get("lr"), False
            scheme = form.get("scheme") or "direct"
        z.writestr(folder + "objective.tex",
                   objective_tex(weights, lr, used, scheme))
        z.writestr(folder + "stats.tex",
                   stats_tex(report.get("stats") or []))
        z.writestr(folder + "edges.tex", edges_tex(report, set(images)))
        z.writestr(folder + "edges_report.tex", report_tex())
    return buf.getvalue()
