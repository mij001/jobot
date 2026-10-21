// Jobs view: every job the bot found, by importance, with filters, search, sort and your marks.
import { S, ui, saveUi, el, iconEl, paintIcons, todayIso, markOf, tierOf, TIERS, byImportance, byNewest, byClosing, matchOf, cfgJS, plural } from "./store.js";
import { jobCard } from "./jobui.js";

const TABS = [["inbox", "To review"], ["shortlist", "Shortlist"], ["applied", "Applied"], ["dismissed", "Dismissed"], ["all", "All"]];
const SORTS = [["importance", "Importance"], ["match", "Resume match"], ["newest", "Newest"], ["closing", "Closing soon"]];

export function createJobsView(root) {
  const tabs = el("div", { class: "tabs", role: "group", "aria-label": "Show" });
  const search = el("input", { type: "search", placeholder: " ", autocomplete: "off", "aria-label": "Search" });
  const period = el("select", { "aria-label": "Period" }, [["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["0", "All time"]].map(([v, t]) => el("option", { value: v }, t)));
  const sort = el("select", { "aria-label": "Sort by" }, SORTS.map(([v, t]) => el("option", { value: v }, t)));
  const hideClosed = el("input", { type: "checkbox" });
  const skillChip = el("div", { class: "chip-row" });
  const list = el("div", { id: "jobList" });
  const periodField = el("label", { class: "field", style: "min-width:150px" }, period, el("span", { class: "lbl" }, "Seen in"), el("span", { class: "caret", "data-icon": "keyboard_arrow_down" }));
  const sortField = el("label", { class: "field", style: "min-width:150px" }, sort, el("span", { class: "lbl" }, "Sort"), el("span", { class: "caret", "data-icon": "keyboard_arrow_down" }));
  const closedLabel = el("label", { class: "check" }, hideClosed, " Hide closed");
  const remoteOnly = el("input", { type: "checkbox" });
  const remoteLabel = el("label", { class: "check" }, remoteOnly, " Remote only");
  root.append(tabs, el("div", { class: "tools" },
    el("label", { class: "field grow" }, search, el("span", { class: "lbl" }, "Search title, company, field, skill…")), periodField, sortField, closedLabel, remoteLabel), skillChip, list);
  paintIcons(root);

  search.addEventListener("input", () => { ui.search = search.value; render(); });
  period.addEventListener("change", () => { ui.period = Number(period.value); saveUi(); render(); });
  sort.addEventListener("change", () => { ui.sort = sort.value; saveUi(); render(); });
  hideClosed.addEventListener("change", () => { ui.hideClosed = hideClosed.checked; saveUi(); render(); });
  remoteOnly.addEventListener("change", () => { ui.remoteOnly = remoteOnly.checked; saveUi(); render(); });

  const setSkill = (skill) => { ui.skill = ui.skill === skill ? "" : skill; saveUi(); render(); };

  function visible() {
    const q = ui.search.trim().toLowerCase(), today = todayIso(), subs = cfgJS().subfields || {};
    const cutoff = ui.period ? new Date(Date.now() - ui.period * 864e5).toLocaleDateString("en-CA") : "";
    const triaged = !["inbox", "all"].includes(ui.jobsTab);
    const words = (j) => [j.title, j.company, j.location, j.source, j.requirements, j.ai_reason, ...(j.skills || []), ...(j.subfields || []).map((k) => subs[k]?.label), S.marks.map[j.id]?.n];
    return S.jobs.filter((j) => {
      const m = markOf(j);
      if (ui.jobsTab === "inbox" ? m : ui.jobsTab !== "all" && m !== ui.jobsTab) return false;
      if (!triaged && cutoff && j.date < cutoff) return false;
      if (!triaged && ui.hideClosed && j.closing && j.closing < today) return false;
      if (ui.remoteOnly && !j.remote) return false;
      if (ui.skill && !(j.skills || []).includes(ui.skill)) return false;
      if (q && !words(j).some((t) => (t || "").toLowerCase().includes(q))) return false;
      return true;
    });
  }

  function render() {
    const count = (tab) => S.jobs.filter((j) => (tab === "all" ? true : tab === "inbox" ? !markOf(j) : markOf(j) === tab)).length;
    tabs.replaceChildren(...TABS.map(([key, label]) => {
      const b = el("button", { type: "button", class: "chip-btn", "aria-pressed": String(ui.jobsTab === key), "data-tab": key }, label, " ", el("span", { class: "n" }, String(count(key))));
      b.addEventListener("click", () => { ui.jobsTab = key; saveUi(); render(); });
      return b;
    }));
    const triaged = !["inbox", "all"].includes(ui.jobsTab);
    periodField.classList.toggle("hidden", triaged); closedLabel.classList.toggle("hidden", triaged);
    period.value = String(ui.period); hideClosed.checked = ui.hideClosed; sort.value = ui.sort;
    remoteLabel.classList.toggle("hidden", !S.jobs.some((j) => j.remote)); remoteOnly.checked = !!ui.remoteOnly;
    for (const o of sort.options) if (o.value === "match") o.disabled = !S.career;
    if (ui.sort === "match" && !S.career) { ui.sort = "importance"; sort.value = "importance"; }
    skillChip.replaceChildren(ui.skill ? (() => {
      const b = el("button", { class: "chip-btn", type: "button", "aria-pressed": "true" }, `Skill: ${ui.skill}  ✕`);
      b.addEventListener("click", () => setSkill(ui.skill));
      return b;
    })() : "");

    list.replaceChildren();
    const shown = visible();
    if (!S.jobs.length) { list.append(el("div", { class: "empty" }, "No jobs saved yet – they appear after the next run.")); return; }
    if (!shown.length) {
      list.append(el("div", { class: "empty" }, ui.search || ui.skill ? "Nothing matches that." : ui.jobsTab === "inbox" ? "All caught up – nothing left to review in this period." : "Nothing here yet."));
      return;
    }
    const cmp = ui.sort === "newest" ? byNewest : ui.sort === "closing" ? byClosing
      : ui.sort === "match" ? (a, b) => (matchOf(b)?.pct ?? -1) - (matchOf(a)?.pct ?? -1) || byImportance(a, b) : byImportance;
    shown.sort(cmp);
    const card = (j) => jobCard(j, { onSkill: setSkill });
    if (ui.sort === "importance") {
      for (const [key, label, about, ic] of TIERS) {
        const rows = shown.filter((j) => tierOf(j) === key);
        if (!rows.length) continue;
        const det = el("details", { class: "tier " + key }, el("summary", {},
          el("span", { class: "tb" }, iconEl(ic)), el("span", { class: "tt" }, label, el("small", {}, about)),
          el("span", { class: "cnt" }, String(rows.length)), el("span", { class: "chevwrap" }, iconEl("keyboard_arrow_down"))));
        if (key !== "low" || ui.search || ui.skill || triaged) det.setAttribute("open", "");
        for (const j of rows) det.append(card(j));
        list.append(det);
      }
    } else {
      list.append(el("p", { class: "hint", style: "margin:12px 0 0" }, `${plural(shown.length, "job")}, ${SORTS.find((s) => s[0] === ui.sort)[1].toLowerCase()} first`));
      for (const j of shown.slice(0, 80)) list.append(card(j));
      if (shown.length > 80) list.append(el("p", { class: "hint" }, `Showing the first 80 of ${shown.length} – narrow the search to see the rest.`));
    }
    paintIcons(list);
  }
  return { render, setSkill };
}
