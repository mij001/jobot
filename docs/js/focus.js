// Focus view: what needs your attention right now – and a one-by-one review mode.
import { S, el, iconEl, paintIcons, todayIso, daysBetween, plural, markOf, tierOf, live, isClosed, byNewest, byClosing, byImportance, TIERS, tierLabel, fmt } from "./store.js";
import { jobRow, jobCard, closingChip } from "./jobui.js";
import { setMark } from "./vault.js";
import { emit } from "./store.js";

const RANK = { top: 0, good: 1, maybe: 2, low: 3 };

function section(title, icon, jobs, { more, chip, empty, max = 6 } = {}) {
  const box = el("div", { class: "sect" }, el("div", { class: "sh" }, iconEl(icon), el("h3", {}, title), el("span", { class: "cnt" }, String(jobs.length))));
  if (!jobs.length) { if (empty) box.append(el("div", { class: "empty" }, empty)); return empty ? box : null; }
  const list = el("div", { class: "jlist" });
  for (const j of jobs.slice(0, max)) list.append(jobRow(j, { chip: chip?.(j) }));
  box.append(list);
  if (jobs.length > max && more) box.append(el("button", { class: "btn text", type: "button", onclick: null }, `See all ${jobs.length}`));
  if (jobs.length > max && more) box.lastChild.addEventListener("click", more);
  return box;
}

export function renderFocus(root, { go }) {
  root.replaceChildren();
  if (!S.jobs.length) { root.append(el("div", { class: "empty" }, "No jobs saved yet – they appear after the next run.")); return; }
  if (S.review) { renderReview(root, go); return; }

  const today = todayIso();
  const inbox = S.jobs.filter((j) => live(j) && !markOf(j));
  const topInbox = inbox.filter((j) => tierOf(j) === "top").sort(byNewest);
  const closing = S.jobs.filter((j) => live(j) && ["", "shortlist"].includes(markOf(j)) && j.closing && daysBetween(today, j.closing) <= 3).sort(byClosing);
  const fresh = S.jobs.filter((j) => j.date === today).length;
  const shortlist = S.jobs.filter((j) => markOf(j) === "shortlist" && !isClosed(j)).sort(byClosing);
  const applied = S.jobs.filter((j) => markOf(j) === "applied").sort((a, b) => (S.marks.map[b.id]?.t || "").localeCompare(S.marks.map[a.id]?.t || ""));

  // the one headline number
  const parts = [plural(topInbox.length, "top pick"), `${closing.length} closing within 3 days`, `${fresh} new today`];
  const review = el("button", { class: "btn filled has-icon", type: "button", disabled: inbox.length ? null : "" }, iconEl("bolt"), "Review one by one");
  review.addEventListener("click", () => startReview());
  const seeAll = el("button", { class: "btn tonal", type: "button" }, "Open the list");
  seeAll.addEventListener("click", () => go("jobs"));
  root.append(el("div", { class: "hero" },
    el("div", { class: "n" }, String(inbox.length)), el("div", { class: "t" }, inbox.length === 1 ? "job to review" : "jobs to review"),
    el("div", { class: "s" }, parts.join(" · ")), el("div", { class: "acts" }, review, seeAll)));

  const blocks = [
    section("Closing soon", "event", closing, { chip: closingChip, empty: "Nothing you care about closes in the next 3 days." }),
    section("Top picks to review", "star", topInbox, { more: () => go("jobs"), empty: inbox.length ? "No top picks waiting – check the good fits." : "You're all caught up." }),
    section("Your shortlist", "bookmark", shortlist, { chip: closingChip, more: () => go("jobs", { jobsTab: "shortlist" }) }),
    section("Applied", "check_circle", applied, { max: 4, more: () => go("jobs", { jobsTab: "applied" }) }),
  ];
  for (const b of blocks) if (b) root.append(b);

  // a nudge toward the coach, or a glance at what it found
  if (S.career) {
    const gaps = (S.career.demand?.skills || []).filter((s) => !s.have && s.jobs >= 2).slice(0, 3);
    if (gaps.length) {
      const btn = el("button", { class: "btn text", type: "button" }, "Open the coach");
      btn.addEventListener("click", () => go("coach"));
      root.append(el("div", { class: "sect" }, el("div", { class: "sh" }, iconEl("school"), el("h3", {}, "Skills to build")),
        el("p", { class: "hint", style: "margin:0 0 4px" }, gaps.map((g) => `${g.skill} (${g.jobs} adverts)`).join(" · ")), btn));
    }
  } else if (!S.resume.doc) {
    const btn = el("button", { class: "btn tonal", type: "button" }, "Add your resume");
    btn.addEventListener("click", () => go("coach"));
    root.append(el("div", { class: "sect" }, el("div", { class: "sh" }, iconEl("school"), el("h3", {}, "Career coach")),
      el("p", { class: "hint", style: "margin:0 0 8px" }, "Add your resume (stored encrypted) to see which skills employers ask for that it doesn't show, get portfolio project ideas and a resume match on every job."), btn));
  }

  // suggestions about your settings
  const tips = S.suggestions.filter((s) => s.kind !== "insight");
  if (tips.length) {
    const box = el("div", { class: "sect" }, el("div", { class: "sh" }, iconEl("lightbulb"), el("h3", {}, "Suggestions")));
    const icons = { tip: "lightbulb", warning: "warning" };
    for (const sg of tips) {
      const row = el("div", { class: "sugg " + sg.kind }, el("div", { class: "ic" }, iconEl(icons[sg.kind] || "lightbulb")), el("div", { class: "t" }, sg.text));
      if (sg.action) {
        const target = S.ctx.actionTarget(sg.action);
        const b = el("button", { class: "btn tonal", type: "button" }, sg.action.label || "Apply");
        if (!target || target.done()) { b.disabled = true; b.textContent = target ? "Done" : "Not available"; }
        b.addEventListener("click", () => { target.apply(); b.disabled = true; b.textContent = "Applied"; S.ctx.snack("Applied – press Save to keep it."); });
        row.append(b);
      }
      box.append(row);
    }
    root.append(box);
  }
  paintIcons(root);
}

// ---------------------------------------------------------------- review one by one
export function startReview() {
  const ids = S.jobs.filter((j) => live(j) && !markOf(j)).sort((a, b) => RANK[tierOf(a)] - RANK[tierOf(b)] || byImportance(a, b)).map((j) => j.id);
  if (!ids.length) return;
  S.review = { ids, i: 0, marked: 0, skipped: 0 };
  emit();
}
const stopReview = () => { S.review = null; emit(); };

function renderReview(root, go) {
  const r = S.review;
  if (r.i >= r.ids.length) {
    root.append(el("div", { class: "hero" }, el("div", { class: "n" }, "✓"), el("div", { class: "t" }, "All caught up"),
      el("div", { class: "s" }, `${plural(r.marked, "job")} sorted, ${r.skipped} skipped`),
      el("div", { class: "acts" }, el("button", { class: "btn filled", type: "button", onclick: null }, "Done"))));
    root.querySelector("button").addEventListener("click", stopReview);
    return;
  }
  const j = S.byId.get(r.ids[r.i]);
  const exit = el("button", { class: "btn text", type: "button" }, "Exit");
  exit.addEventListener("click", stopReview);
  root.append(el("div", { class: "review-head" },
    el("div", {}, el("b", {}, `${r.i + 1} of ${r.ids.length}`), el("span", { class: "tag" }, tierLabel(tierOf(j)))), exit),
    el("div", { class: "prog", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(r.ids.length), "aria-valuenow": String(r.i) },
      el("i", { style: `width:${(r.i / r.ids.length) * 100}%` })));
  const card = jobCard(j);
  card.querySelector(".acts")?.remove();  // the big buttons below replace the small ones
  root.append(card);
  const mk = (label, ic, cls, fn) => { const b = el("button", { class: "btn big " + cls, type: "button" }, iconEl(ic), label); b.addEventListener("click", fn); return b; };
  root.append(el("div", { class: "bigacts" },
    mk("Dismiss", "block", "tonal danger", () => advance(j, "dismissed")),
    mk("Skip", "history", "outlined", () => advance(j, null)),
    mk("Shortlist", "bookmark", "filled", () => advance(j, "shortlist"))),
    el("p", { class: "support", style: "text-align:center" }, "Keys: S shortlist · D dismiss · N or → skip · ← back · Esc exit"));
  paintIcons(root);
}
function advance(job, status) {
  const r = S.review;
  if (!r) return;
  if (status) { r.marked++; r.i++; if (!setMark(job, status)) { r.marked--; r.i--; } }
  else { r.skipped++; r.i++; emit(); }
}
export function reviewKey(e) {
  const r = S.review;
  if (!r || e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return false;
  const job = r.i < r.ids.length ? S.byId.get(r.ids[r.i]) : null;
  const k = e.key.toLowerCase();
  if (k === "escape") stopReview();
  else if (!job) return false;
  else if (k === "s") advance(job, "shortlist");
  else if (k === "d") advance(job, "dismissed");
  else if (k === "n" || k === "arrowright" || k === " ") advance(job, null);
  else if (k === "arrowleft" && r.i > 0) { r.i--; emit(); }
  else return false;
  e.preventDefault();
  return true;
}
