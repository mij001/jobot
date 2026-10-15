// The password-protected dashboard: Focus · Jobs · Data · Coach. Index.html hands over the page helpers.
import { S, ui, saveUi, el, onChange, emit, paintIcons } from "./js/store.js";
import * as vault from "./js/vault.js";
import { renderFocus, reviewKey } from "./js/focus.js";
import { createJobsView } from "./js/jobs.js";
import { renderData } from "./js/data.js";
import { createCoachView } from "./js/coach.js";
import { redraw } from "./js/charts.js";

const TABS = [["focus", "Focus", "bolt"], ["jobs", "Jobs", "inbox"], ["data", "Data", "monitoring"], ["coach", "Coach", "school"]];

export function initDashboard(ctx) {
  S.ctx = ctx;
  const $ = ctx.$;
  let jobsView = null, coachView = null;
  const roots = { focus: $("viewFocus"), jobs: $("viewJobs"), data: $("viewData"), coach: $("viewCoach") };

  function gate(which, message = "") {
    for (const id of ["vaultLocked", "vaultSetup", "dashBody"]) $(id).classList.toggle("hidden", id !== which);
    $("vaultLock").classList.toggle("hidden", which !== "dashBody");
    const badge = $("dashBadge");
    badge.replaceChildren(); badge.dataset.iconDone = ""; badge.dataset.icon = which === "dashBody" ? "lock_open" : "lock";
    paintIcons(badge.parentNode);
    $("vaultMsg").textContent = message; $("vaultMsg").style.color = message ? "var(--error)" : "";
  }

  function tabs() {
    $("dashTabs").replaceChildren(...TABS.map(([key, label, ic]) => {
      const b = el("button", { type: "button", "aria-pressed": String(ui.tab === key), "data-tab": key, role: "tab" }, el("span", { "data-icon": ic }), el("span", { class: "tl" }, label));
      b.addEventListener("click", () => go(key));
      return b;
    }));
    paintIcons($("dashTabs"));
  }

  function render() {
    if (!S.vault.key) return;
    for (const [key, root] of Object.entries(roots)) root.classList.toggle("hidden", key !== ui.tab);
    if (ui.tab === "focus") renderFocus(roots.focus, { go });
    else if (ui.tab === "jobs") { jobsView ||= createJobsView(roots.jobs); jobsView.render(); }
    else if (ui.tab === "data") { renderData(roots.data); redraw(roots.data); }
    else if (ui.tab === "coach") { coachView ||= createCoachView(roots.coach); coachView.render(); }
    paintIcons($("dashBody"));
  }
  function go(tab, opts = {}) {
    if (opts.jobsTab) ui.jobsTab = opts.jobsTab;
    ui.tab = tab; saveUi(); tabs(); render();
    $("dashTabs").scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  onChange(render);

  async function open() {
    gate("dashBody"); tabs(); render();
  }
  async function start() {
    $("secretsLink").href = `https://github.com/${ctx.state.repo}/settings/secrets/actions`;
    const res = await vault.init();
    if (res.status === "setup") gate("vaultSetup");
    else if (res.status === "error") gate("vaultLocked", res.message);
    else if (res.status === "open") await open();
    else gate("vaultLocked");
  }

  // ---- wiring
  $("vaultForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = $("vaultPw").value;
    if (!pw) return;
    const btn = $("vaultUnlock"); btn.disabled = true; btn.lastChild.textContent = "Unlocking…";
    const res = await vault.unlock(pw, $("vaultRemember").checked);
    btn.disabled = false; btn.lastChild.textContent = "Unlock";
    if (res.ok) { $("vaultPw").value = ""; await open(); } else gate("vaultLocked", res.message);
  });
  $("vaultLock").addEventListener("click", async () => {
    await vault.flush();
    vault.lock();
    for (const r of Object.values(roots)) r.replaceChildren();  // nothing decrypted may stay on the page
    jobsView = coachView = null;
    $("vaultPw").value = "";
    gate("vaultLocked");
  });
  document.addEventListener("keydown", (e) => { if (S.vault.key && ui.tab === "focus") reviewKey(e); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) vault.flush(); });
  window.addEventListener("beforeunload", (e) => { if (S.marks.pending || S.marks.saving) e.preventDefault(); });
  let t = 0;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { if (S.vault.key && ui.tab === "data") redraw(roots.data); }, 150); });

  S.ctx.marksState = (text, bad) => { const n = $("marksState"); n.textContent = text; n.classList.toggle("bad", !!bad); };
  return { start, go };
}
