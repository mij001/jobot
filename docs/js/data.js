// Data view: numbers first. One filter row (range) scopes every tile, chart and the table below it.
import { S, ui, saveUi, el, iconEl, paintIcons, todayIso, addDays, daysBetween, dayFmt, weekday, fmt, pct, plural, markOf, noteOf, tierOf, tierLabel, TIERS, isClosed, cfgJS, safeUrl, resumeSkills } from "./store.js";
import { tile, delta, stackedColumns, barList, funnel, histogram, panel, redraw, hoverable } from "./charts.js";

const RANGES = [[7, "7 days"], [30, "30 days"], [90, "90 days"], [0, "All"]];
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
const countBy = (items, key) => { const m = new Map(); for (const i of items) { const k = key(i); if (k != null) m.set(k, (m.get(k) || 0) + 1); } return m; };
const rowsOf = (map, n = 99, labelOf = (k) => k) => [...map].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]))).slice(0, n).map(([k, v]) => ({ label: labelOf(k), value: v }));

/** The window being looked at and the one before it (same length), as ISO dates. */
function windows() {
  const today = todayIso();
  const first = S.jobs.reduce((a, j) => (j.date < a ? j.date : a), today);
  const days = ui.dataDays || Math.min(730, daysBetween(first, today) + 1);
  const from = addDays(today, -(days - 1));
  return { today, days, from, prevFrom: addDays(from, -days), prevTo: addDays(from, -1), all: !ui.dataDays };
}

function buckets(w, jobs) {
  // daily up to ~100 days, weekly beyond that
  const weekly = w.days > 100, size = weekly ? 7 : 1, out = [];
  for (let start = 0; start < w.days; start += size) {
    const a = addDays(w.from, start), b = addDays(w.from, Math.min(start + size, w.days) - 1);
    const inside = jobs.filter((j) => j.date >= a && j.date <= b);
    out.push({ a, b, label: weekly ? `${dayFmt(a)} – ${dayFmt(b)}` : `${weekday(a)}, ${dayFmt(a)}`, short: dayFmt(a), jobs: inside });
  }
  return out;
}
/** `n` equal slices of the window, each reduced by `fn` – the points of a tile's trend line. */
function slices(w, jobs, n, fn) {
  const count = Math.min(n, w.days), out = [];
  for (let i = 0; i < count; i++) {
    const a = addDays(w.from, Math.floor((i * w.days) / count)), b = addDays(w.from, Math.floor(((i + 1) * w.days) / count) - 1);
    out.push(fn(jobs.filter((j) => j.date >= a && j.date <= b)));
  }
  return out;
}

export function renderData(root) {
  root.replaceChildren();
  if (!S.jobs.length && !S.runs.length) { root.append(el("div", { class: "empty" }, "No statistics yet – they appear after the next run.")); return; }
  const cfg = cfgJS(), w = windows();
  const cur = S.jobs.filter((j) => j.date >= w.from && j.date <= w.today);
  const prev = w.all ? null : S.jobs.filter((j) => j.date >= w.prevFrom && j.date <= w.prevTo);
  const vs = `vs previous ${w.days} days`;

  // ---- one filter row above everything it scopes
  const seg = el("div", { class: "seg", role: "group", "aria-label": "Time range", style: "max-width:340px" }, RANGES.map(([d, label]) => {
    const b = el("button", { type: "button", "aria-pressed": String(ui.dataDays === d) }, label);
    b.addEventListener("click", () => { ui.dataDays = d; saveUi(); renderData(root); redraw(root); });
    return b;
  }));
  root.append(el("div", { class: "rangebar" }, seg, el("span", { class: "hint" },
    w.all ? `Everything since ${dayFmt(w.from)} · ${plural(cur.length, "job")}` : `${dayFmt(w.from)} – ${dayFmt(w.today)} · ${plural(cur.length, "job")}, compared with the ${w.days} days before`)));

  // ---- tiles
  const scored = (xs) => xs.filter((j) => j.ai_score != null).map((j) => j.ai_score);
  const hidden = (xs) => xs.filter((j) => j.status === "hidden").length;
  const sent = cur.filter((j) => j.status === "sent");
  const reviewed = sent.filter((j) => markOf(j));
  const shortlisted = sent.filter((j) => ["shortlist", "applied"].includes(markOf(j)));
  const applied = sent.filter((j) => markOf(j) === "applied");
  let carry = 0;
  const avgSpark = slices(w, cur, 12, (xs) => { const s = scored(xs); if (s.length) carry = mean(s); return carry; });
  root.append(el("div", { class: "tiles" },
    tile({ label: "Jobs found", value: fmt(cur.length), change: prev && delta(cur.length, prev.length, { label: vs }), sub: w.all ? "all time" : "", spark: slices(w, cur, 12, (xs) => xs.length) }),
    tile({ label: "Top picks", value: fmt(cur.filter((j) => tierOf(j) === "top").length), change: prev && delta(cur.filter((j) => tierOf(j) === "top").length, prev.filter((j) => tierOf(j) === "top").length, { label: vs }),
      spark: slices(w, cur, 12, (xs) => xs.filter((j) => tierOf(j) === "top").length) }),
    tile({ label: "Average fit", value: scored(cur).length ? mean(scored(cur)).toFixed(1) + "/10" : "–", sub: `${scored(cur).length} scored`,
      change: prev && scored(cur).length && scored(prev).length ? delta(mean(scored(cur)), mean(scored(prev)), { relative: false, label: vs }) : null, spark: scored(cur).length ? avgSpark : null }),
    tile({ label: "Held back by the AI", value: cur.length ? pct(hidden(cur) / cur.length) : "–", sub: `${hidden(cur)} of ${cur.length}`,
      change: prev && cur.length && prev.length ? delta(hidden(cur) / cur.length, hidden(prev) / prev.length, { upIsGood: false, label: vs }) : null }),
    tile({ label: "Shortlisted", value: fmt(shortlisted.length), sub: `of ${sent.length} sent to you` }),
    tile({ label: "Applied", value: fmt(applied.length), sub: shortlisted.length ? `${pct(applied.length / shortlisted.length)} of your shortlist` : "" })));

  const insights = S.suggestions.filter((s) => s.kind === "insight");
  if (insights.length) root.append(el("div", { class: "insights" }, insights.map((s) => el("p", {}, iconEl("monitoring"), s.text))));

  // ---- jobs over time, by importance
  const parts = TIERS.map(([key, label]) => [key, label]);
  const colors = ["var(--ord-1)", "var(--ord-2)", "var(--ord-3)", "var(--chart-muted)"];
  const bk = buckets(w, cur);
  root.append(stackedColumns({
    title: `Jobs found per ${w.days > 100 ? "week" : "day"}, by importance`, sub: "Top picks sit at the bottom of each bar",
    buckets: bk.map((b) => ({ label: b.label, short: b.short, parts: parts.map(([key]) => b.jobs.filter((j) => tierOf(j) === key).length) })),
    series: parts.map(([, label], i) => ({ label, color: colors[i] })),
    ariaLabel: `Jobs found ${w.days > 100 ? "per week" : "per day"} by importance`,
  }));

  // ---- funnels
  const last = S.runs[S.runs.length - 1];
  const grid = el("div", { class: "grid2" });
  if (last) grid.append(funnel({ title: "Latest run", sub: dayFmt(last.date), stages: [
    { label: "Listings scanned", value: last.scanned || 0 }, { label: "Matched your filters", value: last.matched || 0 },
    { label: "New", value: last.new || 0 }, { label: "Sent", value: last.sent || 0 }] }));
  grid.append(funnel({ title: "Your pipeline", sub: `${w.all ? "all time" : `last ${w.days} days`}`, stages: [
    { label: "Found", value: cur.length }, { label: "Sent to you", value: sent.length }, { label: "Reviewed", value: reviewed.length },
    { label: "Shortlisted", value: shortlisted.length }, { label: "Applied", value: applied.length }],
    note: "Counts follow your marks: reviewed = shortlisted, applied or dismissed." }));
  root.append(grid);

  // ---- AI score distribution and when jobs appear
  const cutoff = cfg.ai?.min_score ?? 0, bins = Array.from({ length: 11 }, (_, s) => ({ label: String(s), value: cur.filter((j) => j.ai_score === s).length, muted: s < cutoff }));
  const second = el("div", { class: "grid2" });
  if (scored(cur).length) second.append(histogram({ title: "AI fit scores", sub: `${cur.length - scored(cur).length} without a score`, bins,
    legend: [["Shown", "var(--chart-accent)"], [`Held back (below ${cutoff})`, "var(--chart-muted)"]] }));
  const days7 = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], byDay = new Map(days7.map((d) => [d, 0]));
  for (const j of cur) { const d = new Date(j.date + "T00:00:00").getDay(); byDay.set(days7[(d + 6) % 7], byDay.get(days7[(d + 6) % 7]) + 1); }
  second.append(barList({ title: "Jobs by weekday", sub: "when postings appear", rows: days7.map((d) => ({ label: d, value: byDay.get(d) })), total: cur.length }));
  root.append(second);

  // ---- breakdowns
  const subLabel = (k) => cfg.subfields?.[k]?.label || k, levelLabel = (k) => cfg.experience_levels?.[k]?.label || "Not stated";
  const qualLabel = (k) => (cfg.qualifications?.[k]?.label || "Not stated").split(" (")[0];
  const breakdowns = el("div", { class: "grid2" },
    barList({ title: "By site", rows: rowsOf(countBy(cur, (j) => j.source), 10), total: cur.length }),
    barList({ title: "By sub-field", rows: rowsOf(countBy(cur, (j) => (j.subfields || [])[0] || null), 10, subLabel), total: cur.length }),
    barList({ title: "By experience level", rows: rowsOf(countBy(cur, (j) => j.level || "none"), 6, (k) => (k === "none" ? "Not stated" : levelLabel(k))), total: cur.length }),
    barList({ title: "By qualification", rows: rowsOf(countBy(cur, (j) => (!j.qual_guess && (j.qualifications || [])[0]) || "none"), 6, (k) => (k === "none" ? "Not stated" : qualLabel(k))), total: cur.length }),
    barList({ title: "Hiring the most", rows: rowsOf(countBy(cur, (j) => j.company || null), 8), total: cur.length }),
    barList({ title: "Where", rows: rowsOf(countBy(cur, (j) => (j.location || "").split(",")[0].trim() || null), 8), total: cur.length }));
  root.append(breakdowns);

  // ---- skills in demand (emphasis: what your resume shows vs not) and closing horizon
  const skillCounts = countBy(cur.flatMap((j) => [...new Set(j.skills || [])]), (s) => s);
  const have = resumeSkills(), withResume = S.career != null;
  const skillRows = rowsOf(skillCounts, 14).map((r) => ({ ...r, muted: withResume && !have.has(r.label), extra: withResume ? (have.has(r.label) ? "your resume shows it" : "not on your resume") : "" }));
  const open = S.jobs.filter((j) => tierOf(j) !== "low" && !isClosed(j));
  const horizon = [["Today", 0, 0], ["1–3 days", 1, 3], ["4–7 days", 4, 7], ["8–14 days", 8, 14], ["15+ days", 15, 9999]];
  const dated = open.filter((j) => j.closing), today = todayIso();
  const horizonRows = horizon.map(([label, lo, hi], i) => ({ label, value: dated.filter((j) => { const d = daysBetween(today, j.closing); return d >= lo && d <= hi; }).length, color: `var(--ord-${i + 1})` }));
  horizonRows.push({ label: "No closing date", value: open.length - dated.length, muted: true });
  root.append(el("div", { class: "grid2" },
    barList({ title: "Skills employers ask for", sub: `share of ${cur.length} adverts`, rows: skillRows, total: cur.length, unit: "adverts",
      legend: withResume ? [["Your resume shows it", "var(--chart-accent)"], ["Not on your resume", "var(--chart-muted)"]] : undefined,
      empty: "Skills appear once adverts with details have been read." }),
    barList({ title: "Open jobs by closing date", sub: `${open.length} open`, rows: horizonRows, total: open.length })));

  // ---- what's open right now across all fields (including ones you've switched off), and what your filters hide
  if (last?.open_by_subfield) {
    const subs = cfg.subfields || {};
    const openRows = Object.entries(last.open_by_subfield).filter(([k, n]) => subs[k] && n).sort((a, b) => b[1] - a[1]).slice(0, 12)
      .map(([k, n]) => ({ label: subs[k].label || k, value: n, muted: subs[k].enabled === false, extra: subs[k].enabled === false ? "switched off" : "" }));
    const hiddenRows = [
      ...Object.entries(last.open_level_filtered || {}).map(([k, n]) => ({ label: `${cfg.experience_levels?.[k]?.label || "Level not stated"} (level off)`, value: n })),
      ...Object.entries(last.open_qualification_filtered || {}).map(([k, n]) => ({ label: `${(cfg.qualifications?.[k]?.label || "Not stated").split(" (")[0]} only (qualification off)`, value: n })),
    ].sort((a, b) => b.value - a.value);
    const pair = el("div", { class: "grid2" },
      barList({ title: "Open jobs by sub-field", sub: `latest run, ${dayFmt(last.date)}`, rows: openRows, unit: "jobs",
        legend: [["Switched on", "var(--chart-accent)"], ["Switched off", "var(--chart-muted)"]] }));
    if (hiddenRows.length) pair.append(barList({ title: "Hidden by your filters", sub: "open jobs in your sub-fields", rows: hiddenRows, unit: "jobs" }));
    root.append(pair);
  }

  root.append(sourceHealth(w, cur), readerStats(w), jobsTable(cur, w));
  paintIcons(root);
}

// ---------------------------------------------------------------- source health
function sourceHealth(w, cur) {
  const runs = S.runs.slice(-14);
  if (!runs.length) return el("div");
  const names = [];
  for (const r of [...runs].reverse()) for (const n of Object.keys(r.sources || {})) if (!names.includes(n)) names.push(n);
  const rows = names.map((name) => {
    const hist = runs.map((r) => r.sources?.[name]);
    const nums = hist.filter((h) => h && h.scanned != null).map((h) => h.scanned), lastS = hist[hist.length - 1];
    const status = !lastS ? "not run" : lastS.error ? `✕ ${lastS.error}` : lastS.skipped ? `○ skipped` : `✓ ${fmt(lastS.scanned)} scanned`;
    return { name, hist, avg: nums.length ? Math.round(mean(nums)) : null, status, bad: !!lastS?.error, news: cur.filter((j) => j.source === name).length };
  }).sort((a, b) => b.bad - a.bad || b.news - a.news || a.name.localeCompare(b.name));
  const { root, body } = panel({ title: "Site health", sub: `last ${runs.length} runs`, legend: [],
    tableHead: ["Site", "Last run", "Avg scanned", "New jobs", ...runs.map((r) => dayFmt(r.date))],
    tableRows: rows.map((r) => [r.name, r.status, r.avg ?? "–", r.news, ...r.hist.map((h) => (!h ? "–" : h.error ? "failed" : h.skipped ? "skipped" : "ok"))]) });
  root._draw = () => {
    body.replaceChildren();
    const table = el("table", { class: "dt" }, el("thead", {}, el("tr", {}, ["Site", "Last run", "Avg", "New", "Runs"].map((h, i) => el("th", { class: i === 2 || i === 3 ? "n" : "" }, h)))),
      el("tbody", {}, rows.map((r) => el("tr", {}, el("td", {}, r.name), el("td", { class: r.bad ? "bad" : "" }, r.status), el("td", { class: "n" }, r.avg ?? "–"), el("td", { class: "n" }, r.news),
        el("td", {}, strip(r.hist, runs))))));
    body.append(el("div", { class: "scroll-x" }, table), el("div", { class: "legend", style: "margin-top:10px" },
      el("span", {}, el("i", { class: "dotkey ok" }), "ok"), el("span", {}, el("i", { class: "dotkey bad" }, "✕"), "failed"), el("span", {}, el("i", { class: "dotkey skip" }), "skipped / not run")));
  };
  return root;
}
/** One mark per run: filled = ok, ✕ = failed, ring = skipped. Shape + colour + tooltip, never colour alone. */
function strip(hist, runs) {
  const box = el("span", { class: "strip" });
  hist.forEach((h, i) => {
    const kind = !h ? "skip" : h.error ? "bad" : h.skipped ? "skip" : "ok";
    const dot = el("i", { class: "dotkey " + kind }, kind === "bad" ? "✕" : "");
    const text = !h ? "not run" : h.error ? `failed: ${h.error}` : h.skipped ? `skipped: ${h.skipped}` : `ok, ${h.scanned} scanned`;
    dot.title = `${dayFmt(runs[i].date)} – ${text}`;
    box.append(dot);
  });
  return box;
}

// ---------------------------------------------------------------- how adverts were read
function readerStats(w) {
  const runs = S.runs.filter((r) => r.date >= w.from && r.postings);
  const sum = (k) => runs.reduce((a, r) => a + (r.postings[k] || 0), 0);
  if (!runs.length || !sum("opened")) return el("div");
  return barList({ title: "How adverts were read", sub: plural(runs.length, "run"), unit: "adverts", total: sum("opened") + sum("cached"),
    rows: [{ label: "Opened", value: sum("opened") }, { label: "Poster images (OCR)", value: sum("posters") }, { label: "PDFs", value: sum("pdfs") },
      { label: "Read by the AI", value: sum("ai") }, { label: "Failed", value: sum("failed"), muted: true }, { label: "Remembered from before", value: sum("cached"), muted: true }] });
}

// ---------------------------------------------------------------- the table + exports
const COLS = [
  ["date", "Seen", (j) => j.date], ["tier", "Importance", (j) => TIERS.findIndex((t) => t[0] === tierOf(j))], ["ai_score", "Fit", (j) => j.ai_score ?? -1],
  ["mark", "Mark", (j) => markOf(j)], ["title", "Title", (j) => j.title.toLowerCase()], ["company", "Company", (j) => (j.company || "").toLowerCase()],
  ["location", "Place", (j) => (j.location || "").toLowerCase()], ["source", "Site", (j) => j.source], ["closing", "Closes", (j) => j.closing || "9999"],
];
const table = { key: "date", dir: -1, shown: 100 };
function jobsTable(cur, w) {
  const { root, body } = panel({ title: "All jobs in this period", sub: plural(cur.length, "job"), tableHead: ["Seen", "Importance", "Fit", "Mark", "Title", "Company"], tableRows: [] });
  root.querySelector(".tvbtn").remove(); root.querySelector("table.tv").parentElement.remove();
  const actions = el("div", { class: "export" },
    el("button", { class: "btn tonal has-icon", type: "button" }, iconEl("open_in_new"), "Download CSV"),
    el("button", { class: "btn text", type: "button" }, "Download everything (JSON)"));
  actions.children[0].addEventListener("click", () => download(`jobot-jobs-${todayIso()}.csv`, "text/csv", csv(cur)));
  actions.children[1].addEventListener("click", () => download(`jobot-everything-${todayIso()}.json`, "application/json",
    JSON.stringify({ exported: todayIso(), jobs: S.jobs, marks: S.marks.map, runs: S.runs, career: S.career, prepared: S.prepared }, null, 1)));
  root.querySelector(".ph").append(actions);
  root._draw = () => {
    body.replaceChildren();
    if (!cur.length) { body.append(el("div", { class: "empty" }, "No jobs in this period.")); return; }
    const col = COLS.find((c) => c[0] === table.key) || COLS[0];
    const rows = [...cur].sort((a, b) => { const x = col[2](a), y = col[2](b); return (x < y ? -1 : x > y ? 1 : 0) * table.dir || a.title.localeCompare(b.title); });
    const head = el("tr", {}, COLS.map(([key, label]) => {
      const b = el("button", { type: "button", class: "sortbtn", "aria-label": `Sort by ${label}` }, label, table.key === key ? (table.dir > 0 ? " ▲" : " ▼") : "");
      b.addEventListener("click", () => { table.dir = table.key === key ? -table.dir : key === "date" || key === "ai_score" ? -1 : 1; table.key = key; root._draw(); });
      return el("th", { "aria-sort": table.key === key ? (table.dir > 0 ? "ascending" : "descending") : "none" }, b);
    }));
    const tb = el("tbody", {}, rows.slice(0, table.shown).map((j) => {
      const url = safeUrl(j.url);
      return el("tr", {}, el("td", {}, dayFmt(j.date)), el("td", {}, tierLabel(tierOf(j))), el("td", { class: "n" }, j.ai_score ?? "–"),
        el("td", {}, ({ shortlist: "★ shortlist", applied: "✓ applied", dismissed: "✕ dismissed" })[markOf(j)] || ""),
        el("td", { class: "ttl" }, url ? el("a", { href: url, target: "_blank", rel: "noopener" }, j.title) : j.title),
        el("td", {}, j.company || ""), el("td", {}, (j.location || "").split(",")[0]), el("td", {}, j.source), el("td", {}, j.closing ? dayFmt(j.closing) : ""));
    }));
    body.append(el("div", { class: "scroll-x" }, el("table", { class: "dt wide" }, el("thead", {}, head), tb)));
    if (rows.length > table.shown) {
      const more = el("button", { class: "btn text", type: "button" }, `Show more (${rows.length - table.shown} left)`);
      more.addEventListener("click", () => { table.shown += 100; root._draw(); });
      body.append(more);
    }
  };
  return root;
}

const CSV_COLS = ["date", "status", "importance", "ai_score", "mark", "note", "title", "company", "location", "source", "level", "qualifications", "min_years", "skills", "closing", "requirements", "contact", "ai_reason", "url"];
function cell(v) {
  let s = Array.isArray(v) ? v.join("; ") : v == null ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;  // a spreadsheet must never read data as a formula
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function csv(jobs) {
  const rows = [...jobs].sort((a, b) => (a.date < b.date ? 1 : -1)).map((j) => CSV_COLS.map((c) => cell(c === "mark" ? markOf(j) : c === "note" ? noteOf(j) : j[c])).join(","));
  return "﻿" + [CSV_COLS.join(","), ...rows].join("\n");
}
function download(name, type, text) {
  const url = URL.createObjectURL(new Blob([text], { type: type + ";charset=utf-8" }));
  const a = el("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
