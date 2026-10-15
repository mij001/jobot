// Coach view: your resume (stored encrypted), how it reads, the skills it lacks, project ideas, best-fit jobs.
import { S, el, iconEl, paintIcons, dayFmt, plural, fmt, pct, todayIso } from "./store.js";
import { loadResume, saveResume, deleteResume, refresh } from "./vault.js";
import { barList, redraw } from "./charts.js";
import { jobRow, preparedBlock } from "./jobui.js";

const MAX_FILE = 1_000_000;
const toB64 = (buf) => { const u8 = new Uint8Array(buf); let bin = ""; for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode(...u8.subarray(i, i + 0x8000)); return btoa(bin); };
const ul = (items, cls = "plain") => el("ul", { class: cls }, items.map((t) => el("li", {}, t)));
const card = (title, ic, ...kids) => el("div", { class: "panel-card coachcard" }, el("div", { class: "ph" }, iconEl(ic), el("h3", { class: "grow" }, title)), ...kids);

export function createCoachView(root) {
  // ---- the resume form (built once so typing is never wiped by a re-render)
  const status = el("p", { class: "hint", style: "margin:0 0 8px" });
  const text = el("textarea", { rows: "7", placeholder: "Paste your resume here – or choose a file below. Your name, e-mail, phone number and links are removed before anything is sent to the AI.", "aria-label": "Resume text" });
  const file = el("input", { type: "file", accept: ".pdf,.docx,.txt,.md,application/pdf", "aria-label": "Resume file" });
  const save = el("button", { class: "btn filled has-icon", type: "button" }, iconEl("save"), "Save encrypted");
  const remove = el("button", { class: "btn text danger", type: "button" }, "Remove");
  const analyse = el("button", { class: "btn tonal has-icon", type: "button" }, iconEl("smart_toy"), "Analyse");
  const refreshBtn = el("button", { class: "btn text", type: "button" }, "Refresh");
  const resumeCard = el("div", { class: "panel-card coachcard" },
    el("div", { class: "ph" }, iconEl("school"), el("h3", { class: "grow" }, "Your resume")), status,
    el("label", { class: "field" }, text, el("span", { class: "lbl" }, "Paste text")),
    el("div", { class: "filerow" }, el("span", { class: "hint", style: "margin:0" }, "or"), file, el("span", { class: "hint", style: "margin:0" }, "PDF, DOCX or text · up to 1 MB")),
    el("div", { class: "acts" }, save, analyse, remove, refreshBtn),
    el("p", { class: "support", style: "padding:8px 0 0" },
      "It is stored encrypted in your repository and read only by the daily run. Name, e-mail, phone, links and personal-detail lines are removed before any text goes to the AI. Google's free Gemini tier may use what it receives to improve its products – set coach.send_resume: false in the config to keep the text out of the AI entirely."));
  const report = el("div", { class: "coach-report" });
  root.append(resumeCard, report);
  paintIcons(root);

  const showStatus = () => {
    const d = S.resume.doc;
    status.textContent = !S.resume.loaded ? "Checking…" : d ? `Stored encrypted · ${d.kind === "file" ? d.name : "pasted text"} · updated ${d.updated ? dayFmt(d.updated) : "earlier"}` : "No resume saved yet.";
    remove.classList.toggle("hidden", !d);
  };
  const busy = (b, on, label) => { b.disabled = on; if (label != null) b.lastChild.textContent = label; };

  save.addEventListener("click", async () => {
    let doc = null;
    const f = file.files[0];
    if (f) {
      if (f.size > MAX_FILE) { S.ctx.snack("That file is over 1 MB – paste the text instead.", true); return; }
      doc = { kind: "file", name: f.name.slice(0, 120), mime: f.type, size: f.size, data: toB64(await f.arrayBuffer()), updated: todayIso() };
    } else if (text.value.trim().length >= 40) {
      doc = { kind: "text", name: "pasted text", text: text.value.slice(0, 40000), updated: todayIso() };
    } else { S.ctx.snack("Paste your resume text or choose a file first.", true); return; }
    busy(save, true, "Saving…");
    try {
      if (await saveResume(doc)) { file.value = ""; S.ctx.snack("Resume saved (encrypted). Press Analyse to update your report."); }
    } catch (err) { S.ctx.snack(`Couldn't save it (${err.message}). The token needs Contents: Read and write.`, true); }
    busy(save, false, "Save encrypted"); showStatus(); render();
  });
  remove.addEventListener("click", async () => {
    if (!confirm("Remove the saved resume? (The career report stays until the next one.)")) return;
    try { if (await deleteResume()) { text.value = ""; S.ctx.snack("Resume removed."); } } catch (err) { S.ctx.snack("Couldn't remove it: " + err.message, true); }
    showStatus(); render();
  });
  analyse.addEventListener("click", async () => {
    if (!S.resume.doc) { S.ctx.snack("Save your resume first.", true); return; }
    if (S.ctx.needToken()) return;
    busy(analyse, true);
    try { await S.ctx.dispatch({ career: "true" }); S.ctx.snack("Analysing – the report is ready in about 2 minutes. Then press Refresh."); }
    catch (err) { S.ctx.snack(`Couldn't start it (${err.message}). The token needs Actions: Read and write.`, true); }
    busy(analyse, false);
  });
  refreshBtn.addEventListener("click", async () => {
    busy(refreshBtn, true);
    try { await refresh(); S.ctx.snack(S.career ? `Report from ${dayFmt(S.career.date)} loaded.` : "No report yet."); }
    catch (err) { S.ctx.snack("Couldn't refresh: " + err.message, true); }
    busy(refreshBtn, false);
  });

  // ---- the report
  let loading = false;
  function render() {
    if (!S.resume.loaded && !loading) {
      loading = true;
      loadResume().catch(() => {}).finally(() => {
        loading = false; S.resume.loaded = true;
        if (S.resume.doc?.kind === "text" && !text.value) text.value = S.resume.doc.text || "";
        render();
      });
    }
    showStatus();
    report.replaceChildren();
    const c = S.career;
    if (!c) {
      report.append(card("Your career report", "smart_toy", el("p", { class: "hint", style: "margin:0" },
        "Save your resume, then press Analyse. You'll get: how the resume reads, the skills employers ask for that it doesn't show, portfolio projects that would close those gaps, and a resume match on every job. It also refreshes every Sunday.")));
      renderPrepared(report);
      paintIcons(report); return;
    }
    const stale = S.resume.doc?.updated && S.resume.doc.updated > c.date;
    report.append(el("div", { class: "reporthead" }, el("div", {}, el("b", {}, `Report from ${dayFmt(c.date)}`),
      el("span", { class: "hint", style: "margin-left:8px" }, c.ai ? `AI: ${c.model}` : "no AI – counted parts only")),
      stale ? el("span", { class: "tag warn" }, "Resume changed since – press Analyse") : ""));
    if (c.notes?.length) report.append(el("div", { class: "notes-list" }, c.notes.map((n) => el("p", {}, iconEl("warning"), n))));

    const a = c.analysis;
    if (a) {
      const level = S.ctx.cfg().experience_levels?.[a.level]?.label;
      const head = el("div", {}, el("p", { class: "lead" }, a.summary),
        level ? el("span", { class: "tag" }, `Reads as: ${level}`) : "");
      const kids = [head];
      if (a.headline) {
        const cp = el("button", { class: "btn text", type: "button" }, "Copy");
        cp.addEventListener("click", () => navigator.clipboard?.writeText(a.headline).then(() => S.ctx.snack("Headline copied.")));
        kids.push(el("div", { class: "headline" }, el("span", { class: "hint", style: "margin:0" }, "Suggested headline"), el("b", {}, a.headline), cp));
      }
      kids.push(el("div", { class: "grid2" },
        a.strengths?.length ? el("div", {}, el("h4", {}, "Strengths"), ul(a.strengths)) : "",
        a.gaps?.length ? el("div", {}, el("h4", {}, "Gaps"), ul(a.gaps)) : ""));
      if (a.improvements?.length) kids.push(el("h4", {}, "What to change"), el("ol", { class: "plain" }, a.improvements.map((i) =>
        el("li", {}, i.area ? el("span", { class: "tag" }, i.area) : "", " ", i.tip))));
      report.append(card("How your resume reads", "school", ...kids));
    }

    // skills: demand vs the resume
    const demand = c.demand?.skills || [];
    const have = new Set(c.resume_skills || []);
    const rows = demand.slice(0, 16).map((s) => ({ label: s.skill, value: s.jobs, muted: !s.have, extra: s.have ? "your resume shows it" : `not on your resume · ${s.category}` }));
    const skillsPanel = barList({ title: "Skills employers ask for", sub: `${c.demand?.jobs || 0} adverts, last ${c.demand?.days || 90} days`, rows, unit: "adverts", total: c.demand?.jobs || 0,
      legend: [["Your resume shows it", "var(--chart-accent)"], ["Not on your resume – a gap", "var(--chart-muted)"]], empty: "Not enough adverts with details yet." });
    report.append(skillsPanel);
    const shows = [...(c.resume_skills || []), ...(c.resume_extra_skills || [])];
    if (shows.length) report.append(card("Skills your resume shows", "check_circle", el("div", { class: "tags" }, shows.map((s) => el("span", { class: "tag have" }, "✓ " + s)))));

    // portfolio projects
    if (c.projects?.length) {
      const list = el("div", { class: "pgrid" }, c.projects.map((p) => el("div", { class: "pcard" },
        el("div", { class: "top" }, el("h4", {}, p.title), el("span", { class: "tag" }, [p.difficulty, p.weeks ? `${p.weeks} wk` : ""].filter(Boolean).join(" · "))),
        p.goal ? el("p", { class: "lead" }, p.goal) : "", p.why ? el("p", { class: "line" }, el("b", {}, "Why: "), p.why) : "",
        p.skills?.length ? el("div", { class: "tags" }, p.skills.map((s) => el("span", { class: "tag" + (have.has(s) ? " have" : "") }, s))) : "",
        p.steps?.length ? el("ol", { class: "plain" }, p.steps.map((s) => el("li", {}, s))) : "",
        p.deliverables?.length ? el("p", { class: "line" }, el("b", {}, "Publish: "), p.deliverables.join(" · ")) : "",
        p.show_it ? el("p", { class: "line" }, el("b", {}, "Show it: "), p.show_it) : "")));
      report.append(card("Portfolio projects to build", "science", list));
    }

    // best-fit open jobs
    const fits = (c.matches || []).map((m) => ({ m, j: S.byId.get(m.id) })).filter((x) => x.j).slice(0, 8);
    if (fits.length) {
      const box = el("div", { class: "jlist" });
      for (const { m, j } of fits) {
        const row = jobRow(j);
        const extra = el("div", { class: "fitnote" });
        if (m.verdict) extra.append(el("p", { class: "line" }, el("b", {}, m.verdict)));
        if (m.missing?.length) extra.append(el("p", { class: "line" }, "Missing: ", m.missing.join(", ")));
        for (const t of m.tips || []) extra.append(el("p", { class: "line" }, iconEl("lightbulb"), t));
        box.append(row, extra);
      }
      report.append(card("Best fits for your resume", "bolt", box));
    }
    renderPrepared(report);
    paintIcons(report); redraw(report);
  }

  function renderPrepared(host) {
    const items = Object.values(S.prepared || {}).sort((a, b) => (b.date || "").localeCompare(a.date || ""));
    if (!items.length) return;
    host.append(card("Prepared for these jobs", "school", ...items.map((p) => el("div", { class: "prepitem" },
      el("div", { class: "ph2" }, el("b", {}, p.title), el("span", { class: "hint", style: "margin:0" }, p.company || "")), preparedBlock(p)))));
  }

  return { render };
}
