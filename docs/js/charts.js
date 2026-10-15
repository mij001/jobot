// Small chart toolkit (plain SVG/HTML, no libraries) following one set of mark specs:
// thin marks (<= 24px), 4px rounded data end, 2px gaps between touching fills, solid hairline grid,
// one tooltip per chart listing every series (values first), a table twin for every chart,
// and direct labels only where they help (peaks, bar tips).
import { el, fmt } from "./store.js";

const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}, ...kids) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v);
  for (const k of kids) if (k) n.append(k);
  return n;
};

// ---------------------------------------------------------------- tooltip (one for the whole page)
const tip = el("div", { class: "chart-tip hidden", role: "tooltip" });
document.body.append(tip);
export function showTip(x, y, { title, rows }) {
  tip.replaceChildren(
    title ? el("div", { class: "tt" }, title) : "",
    ...rows.map((r) => el("div", { class: "tr" }, r.color ? el("i", { class: "key", style: `background:${r.color}` }) : "",
      el("b", {}, String(r.value)), el("span", {}, r.label))));
  tip.classList.remove("hidden");
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, x - w / 2)) + "px";
  tip.style.top = (y - h - 10 < 8 ? y + 14 : y - h - 10) + "px";
}
export const hideTip = () => tip.classList.add("hidden");

/** Hover + keyboard focus show the same tooltip on a mark. */
export function hoverable(node, content, label) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("aria-label", label);
  const show = () => { const r = node.getBoundingClientRect(); showTip(r.left + r.width / 2, r.top, content()); };
  node.addEventListener("pointerenter", show); node.addEventListener("focus", show);
  node.addEventListener("pointerleave", hideTip); node.addEventListener("blur", hideTip);
}

// ---------------------------------------------------------------- panel with a table twin
/** A card with a title, optional legend, the chart body and a "Table" toggle showing the same numbers. */
export function panel({ title, sub, legend, tableHead, tableRows, className = "" }) {
  const body = el("div", { class: "body" });
  const legendBox = legend && legend.length ? el("div", { class: "legend" }, legend.map(([name, color]) =>
    el("span", {}, el("i", { style: `background:${color}` }), name))) : "";
  const table = el("table", { class: "tv" },
    el("thead", {}, el("tr", {}, tableHead.map((h, i) => el("th", { class: i ? "n" : "" }, h)))),
    el("tbody", {}, tableRows.map((r) => el("tr", {}, r.map((c, i) => el("td", { class: i ? "n" : "" }, String(c)))))));
  const tableBox = el("div", { class: "scroll-x hidden" }, table); // wide tables scroll inside the card
  const toggle = el("button", { class: "btn text tvbtn", type: "button", "aria-pressed": "false" }, "Table");
  toggle.addEventListener("click", () => {
    const on = tableBox.classList.toggle("hidden") === false;
    toggle.setAttribute("aria-pressed", String(on));
    body.classList.toggle("hidden", on); legendBox?.classList?.toggle("hidden", on);
  });
  const root = el("div", { class: "panel-card " + className },
    el("div", { class: "ph" }, el("h3", { class: "grow" }, title), sub ? el("span", { class: "hint" }, sub) : "", toggle),
    legendBox, body, tableBox);
  root._draw = () => {};
  return { root, body };
}
/** Re-draw every chart under `root` (after it is in the page, or after a resize). */
export const redraw = (root) => { for (const p of root.querySelectorAll(".panel-card")) p._draw?.(); };

// ---------------------------------------------------------------- scales
export function niceScale(max, ticks = 4) {
  if (max <= 0) return { top: 1, step: 1 };
  const raw = Math.max(1, max / ticks), mag = 10 ** Math.floor(Math.log10(raw)), norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  return { top: Math.ceil(max / step) * step, step };
}

// ---------------------------------------------------------------- stat tile + sparkline
export function sparkline(values, w = 104, h = 30) {
  const n = values.length, max = Math.max(...values, 1), pad = 5;
  const x = (i) => pad + (n === 1 ? (w - 2 * pad) / 2 : (i * (w - 2 * pad)) / (n - 1));
  const y = (v) => h - pad - (v / max) * (h - 2 * pad);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = svg("polyline", { points: pts.join(" "), fill: "none", stroke: "var(--chart-accent)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" });
  const area = svg("polygon", { points: `${x(0)},${h - pad} ${pts.join(" ")} ${x(n - 1)},${h - pad}`, fill: "var(--chart-accent)", opacity: ".1" });
  const dot = svg("circle", { cx: x(n - 1), cy: y(values[n - 1]), r: 4, fill: "var(--chart-accent)", stroke: "var(--panel, var(--surface))", "stroke-width": 2 });
  return svg("svg", { class: "spark", viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: "img", "aria-label": `Trend, ${n} points, latest ${values[n - 1]}` }, area, line, dot);
}

/** Change vs the previous period, as text + arrow (never colour alone). */
export function delta(cur, prev, { upIsGood = true, relative = true, label = "" } = {}) {
  if (prev == null || cur == null) return null;
  const diff = cur - prev;
  if (Math.abs(diff) < 1e-9) return { dir: 0, tone: "flat", text: `no change ${label}`.trim() };
  const dir = diff > 0 ? 1 : -1;
  const size = relative ? (prev === 0 ? "new" : `${Math.abs(Math.round((diff / prev) * 100))}%`) : fmt(Math.abs(Math.round(diff * 10) / 10));
  return { dir, tone: (dir > 0) === upIsGood ? "good" : "bad", text: `${dir > 0 ? "▲" : "▼"} ${size} ${label}`.trim() };
}

/** KPI tile: label · value · change vs the previous period · 12-point trend. */
export function tile({ label, value, sub, change, spark }) {
  return el("div", { class: "tile" },
    el("div", { class: "k" }, label),
    el("div", { class: "v" }, value),
    change ? el("div", { class: "d " + change.tone }, change.text) : el("div", { class: "d flat" }, sub || " "),
    change && sub ? el("div", { class: "s" }, sub) : "",
    spark ? sparkline(spark) : "");
}

// ---------------------------------------------------------------- stacked columns over time
/** buckets: [{ label, short, parts: [v per series] }]; series: [{ label, color }] (bottom to top). */
export function stackedColumns({ title, sub, buckets, series, ariaLabel }) {
  const { root, body } = panel({
    title, sub, legend: series.map((s) => [s.label, s.color]),
    tableHead: ["Period", ...series.map((s) => s.label), "Total"],
    tableRows: buckets.map((b) => [b.label, ...b.parts, b.parts.reduce((a, c) => a + c, 0)]),
  });
  root._draw = () => {
    body.replaceChildren();
    const W = Math.max(260, body.clientWidth || 600), H = 196, padL = 34, padR = 4, padT = 20, padB = 24, plotH = H - padT - padB;
    const n = buckets.length, totals = buckets.map((b) => b.parts.reduce((a, c) => a + c, 0));
    const { top, step } = niceScale(Math.max(...totals, 1));
    const y = (v) => padT + plotH * (1 - v / top), band = (W - padL - padR) / n, bw = Math.max(2, Math.min(24, band - 2));
    const g = svg("svg", { class: "cols", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", tabindex: "0",
      "aria-label": ariaLabel || title });
    for (let v = 0; v <= top; v += step) {
      g.append(svg("line", { class: "grid", x1: padL, x2: W - padR, y1: y(v), y2: y(v) }));
      const t = svg("text", { class: "axis", x: padL - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = fmt(v); g.append(t);
    }
    const groups = buckets.map((b, i) => {
      const x = padL + i * band + (band - bw) / 2, grp = svg("g", { class: "col" });
      let base = y(0), lastIdx = -1;
      b.parts.forEach((v, k) => { if (v > 0) lastIdx = k; });
      b.parts.forEach((v, k) => {
        if (v <= 0) return;
        const h = (v / top) * plotH, trim = base < y(0) - 0.5 ? 2 : 0, rect = Math.max(1, h - trim);
        const r = k === lastIdx ? Math.min(4, bw / 2, rect) : 0, yTop = base - h;
        const d = r ? `M${x},${yTop + rect}V${yTop + r}Q${x},${yTop} ${x + r},${yTop}H${x + bw - r}Q${x + bw},${yTop} ${x + bw},${yTop + r}V${yTop + rect}Z`
          : `M${x},${yTop + rect}V${yTop}H${x + bw}V${yTop + rect}Z`;
        grp.append(svg("path", { d, fill: series[k].color }));
        base -= h;
      });
      g.append(grp);
      return grp;
    });
    const peak = totals.indexOf(Math.max(...totals));
    if (totals[peak] > 0) {  // one direct label: the busiest bucket
      const t = svg("text", { class: "axis", x: padL + peak * band + band / 2, y: y(totals[peak]) - 5, "text-anchor": "middle" });
      t.textContent = String(totals[peak]); g.append(t);
    }
    for (const i of new Set([0, Math.floor((n - 1) / 2), n - 1])) {
      const t = svg("text", { class: "axis", x: Math.min(Math.max(padL + i * band + band / 2, padL + 14), W - 16), y: H - 6, "text-anchor": "middle" });
      t.textContent = buckets[i].short; g.append(t);
    }
    const hair = svg("line", { class: "hair hidden", y1: padT, y2: y(0) });
    g.append(hair);
    let current = -1;
    const show = (i, clientX, clientY) => {
      current = i; const b = buckets[i];
      hair.classList.remove("hidden"); hair.setAttribute("x1", padL + i * band + band / 2); hair.setAttribute("x2", padL + i * band + band / 2);
      groups.forEach((gr, k) => gr.classList.toggle("lift", k === i));
      showTip(clientX, clientY, { title: b.label, rows: [
        ...series.map((s, k) => ({ color: s.color, value: b.parts[k], label: s.label })).reverse(),
        { value: totals[i], label: "total" }] });
    };
    const hit = svg("rect", { x: padL, y: padT, width: W - padL - padR, height: plotH, fill: "transparent" });
    hit.addEventListener("pointermove", (e) => {
      const r = g.getBoundingClientRect(), x = (e.clientX - r.left) * (W / r.width) - padL;
      show(Math.max(0, Math.min(n - 1, Math.floor(x / band))), e.clientX, r.top + (padT * r.height) / H);
    });
    hit.addEventListener("pointerleave", () => { hideTip(); hair.classList.add("hidden"); groups.forEach((gr) => gr.classList.remove("lift")); });
    g.append(hit);
    g.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight", "Escape"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "Escape") { hideTip(); hair.classList.add("hidden"); return; }
      const i = Math.max(0, Math.min(n - 1, (current < 0 ? n - 1 : current) + (e.key === "ArrowRight" ? 1 : -1)));
      const r = g.getBoundingClientRect();
      show(i, r.left + ((padL + i * band + band / 2) * r.width) / W, r.top + (padT * r.height) / H);
    });
    g.addEventListener("blur", () => { hideTip(); hair.classList.add("hidden"); groups.forEach((gr) => gr.classList.remove("lift")); });
    body.append(g);
  };
  return root;
}

// ---------------------------------------------------------------- horizontal bars (one series, sorted)
/** rows: [{ label, value, extra?, color?, muted? }] – `color` only for ordered buckets (ordinal ramp). */
export function barList({ title, sub, rows, unit = "jobs", legend, total, empty = "Nothing yet for this period." }) {
  const sum = total ?? rows.reduce((a, r) => a + r.value, 0);
  const { root, body } = panel({
    title, sub, legend,
    tableHead: ["", unit[0].toUpperCase() + unit.slice(1), "Share"],
    tableRows: rows.map((r) => [r.label + (r.muted ? " (off)" : ""), r.value, sum ? `${Math.round((r.value / sum) * 100)}%` : ""]),
  });
  root._draw = () => {
    body.replaceChildren();
    if (!rows.length) { body.append(el("div", { class: "empty" }, empty)); return; }
    const max = Math.max(...rows.map((r) => r.value), 1), grid = el("div", { class: "bars" });
    for (const r of rows) {
      const bar = el("div", { class: "bar" + (r.muted ? " muted" : ""), style: `width:calc((100% - 44px) * ${r.value / max});${r.color ? `background:${r.color}` : ""}` });
      const trk = el("div", { class: "trk" }, bar, el("span", { class: "val" }, fmt(r.value)));
      hoverable(trk, () => ({ rows: [{ value: `${r.value} ${unit}`, label: r.label }, ...(sum ? [{ value: `${Math.round((r.value / sum) * 100)}%`, label: "of the total" }] : []),
        ...(r.extra ? [{ value: "", label: r.extra }] : [])] }), `${r.label}: ${r.value} ${unit}`);
      grid.append(el("div", { class: "lbl", title: r.label }, r.label), trk);
    }
    body.append(grid);
  };
  return root;
}

// ---------------------------------------------------------------- funnel (ordered stages, one-hue ramp)
export function funnel({ title, sub, stages, note }) {
  const rows = stages.map((s, i) => [s.label, s.value, i && stages[i - 1].value ? `${Math.round((s.value / stages[i - 1].value) * 100)}%` : ""]);
  const { root, body } = panel({ title, sub, tableHead: ["Stage", "Count", "of previous"], tableRows: rows });
  root._draw = () => {
    body.replaceChildren();
    const max = Math.max(...stages.map((s) => s.value), 1), grid = el("div", { class: "bars" });
    stages.forEach((s, i) => {
      const conv = i && stages[i - 1].value ? Math.round((s.value / stages[i - 1].value) * 100) : null;
      const bar = el("div", { class: "bar", style: `width:calc((100% - 92px) * ${s.value / max});background:var(--ord-${Math.min(i + 1, 5)})` });
      const trk = el("div", { class: "trk" }, bar, el("span", { class: "val" }, fmt(s.value) + (conv != null ? ` · ${conv}%` : "")));
      hoverable(trk, () => ({ rows: [{ value: s.value, label: s.label }, ...(conv != null ? [{ value: `${conv}%`, label: `of ${stages[i - 1].label.toLowerCase()}` }] : [])] }), `${s.label}: ${s.value}`);
      grid.append(el("div", { class: "lbl", title: s.label }, s.label), trk);
    });
    body.append(grid, note ? el("p", { class: "support", style: "padding:8px 0 0" }, note) : "");
  };
  return root;
}

// ---------------------------------------------------------------- columns for a distribution (histogram)
/** bins: [{ label, value, muted? }] – one series; `muted` bins are the emphasis contrast (gray). */
export function histogram({ title, sub, bins, legend, unit = "jobs" }) {
  const { root, body } = panel({
    title, sub, legend,
    tableHead: ["Score", "Jobs"], tableRows: bins.map((b) => [b.label + (b.muted ? " (held back)" : ""), b.value]),
  });
  root._draw = () => {
    body.replaceChildren();
    const W = Math.max(240, body.clientWidth || 400), H = 170, padL = 30, padR = 4, padT = 18, padB = 22, plotH = H - padT - padB;
    const { top, step } = niceScale(Math.max(...bins.map((b) => b.value), 1), 3);
    const y = (v) => padT + plotH * (1 - v / top), band = (W - padL - padR) / bins.length, bw = Math.min(24, band - 4);
    const g = svg("svg", { class: "cols", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": title });
    for (let v = 0; v <= top; v += step) {
      g.append(svg("line", { class: "grid", x1: padL, x2: W - padR, y1: y(v), y2: y(v) }));
      const t = svg("text", { class: "axis", x: padL - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = fmt(v); g.append(t);
    }
    const peak = bins.reduce((a, b, i) => (b.value > bins[a].value ? i : a), 0);
    bins.forEach((b, i) => {
      const x = padL + i * band + (band - bw) / 2, h = (b.value / top) * plotH, r = Math.min(4, bw / 2, h);
      const hit = svg("rect", { class: "hit", x: padL + i * band, y: padT, width: band, height: plotH });
      const d = h > 0 ? `M${x},${y(0)}V${y(0) - h + r}Q${x},${y(0) - h} ${x + r},${y(0) - h}H${x + bw - r}Q${x + bw},${y(0) - h} ${x + bw},${y(0) - h + r}V${y(0)}Z` : "";
      g.append(hit, svg("path", { class: "col", d, fill: b.muted ? "var(--chart-muted)" : "var(--chart-accent)" }));
      hoverable(hit, () => ({ title: b.label, rows: [{ value: b.value, label: `${unit}${b.muted ? " · held back by the AI" : ""}` }] }), `${b.label}: ${b.value} ${unit}`);
      const t = svg("text", { class: "axis", x: x + bw / 2, y: H - 6, "text-anchor": "middle" }); t.textContent = b.label; g.append(t);
      if (i === peak && b.value) { const v = svg("text", { class: "axis", x: x + bw / 2, y: y(0) - h - 5, "text-anchor": "middle" }); v.textContent = String(b.value); g.append(v); }
    });
    body.append(g);
  };
  return root;
}
