// Job cards and rows shared by the Focus, Jobs and Coach views.
import { S, el, paintIcons, iconEl, safeUrl, dayFmt, closingInfo, markOf, noteOf, matchOf, resumeSkills, tierOf, cfgJS } from "./store.js";
import { setMark, setNote, refresh } from "./vault.js";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const scorePill = (j) => el("span", { class: "score" + (tierOf(j) === "low" || j.ai_score == null ? " dim" : ""),
  title: j.ai_score == null ? "No AI score" : "AI fit score" }, j.ai_score == null ? "–" : `${j.ai_score}/10`);

export function titleLink(j) {
  const url = safeUrl(j.url);
  return url ? el("a", { href: url, target: "_blank", rel: "noopener" }, j.title) : document.createTextNode(j.title);
}
export const metaLine = (j) => [j.company, j.location, j.source].filter(Boolean).join(" · ") + (j.watched ? " 👀" : "");

// ---------------------------------------------------------------- the three marks
const MARKS = [["shortlist", "Shortlist", "bookmark", ""], ["applied", "Applied", "check_circle", ""], ["dismissed", "Dismiss", "block", "danger"]];
export function markButtons(j, { icons = false } = {}) {
  const current = markOf(j), box = el("div", { class: icons ? "mini-acts" : "acts" });
  for (const [status, label, ic, cls] of MARKS) {
    const b = icons
      ? el("button", { type: "button", class: "ibtn " + cls, "aria-pressed": String(current === status), "aria-label": label, title: label, "data-mark": status }, iconEl(ic))
      : el("button", { type: "button", class: "act " + cls, "aria-pressed": String(current === status), "data-mark": status }, iconEl(ic), label);
    b.addEventListener("click", () => setMark(j, current === status ? "" : status));
    box.append(b);
  }
  return box;
}

// ---------------------------------------------------------------- preparing for a job
const PENDING_KEY = "jobot.prep";
const pending = () => { try { return JSON.parse(sessionStorage.getItem(PENDING_KEY) || "{}"); } catch { return {}; } };
async function requestPrepare(j) {
  if (S.ctx.needToken()) return;
  try {
    await S.ctx.dispatch({ prepare: j.id });
    try { sessionStorage.setItem(PENDING_KEY, JSON.stringify({ ...pending(), [j.id]: Date.now() })); } catch {}
    S.ctx.snack("Preparing – the cover letter, interview questions and study plan are ready in about 2 minutes. Press Refresh on the Coach tab.");
  } catch (err) { S.ctx.snack(`Couldn't start it (${err.message}). The token needs Actions: Read and write.`, true); }
}
const copy = (text, what) => navigator.clipboard?.writeText(text).then(() => S.ctx.snack(`${what} copied.`), () => S.ctx.snack("Couldn't copy – select the text instead.", true));
const list = (items, tag = "ul") => el(tag, { class: "plain" }, items.map((t) => el("li", {}, t)));

export function preparedBlock(p, { open = false } = {}) {
  const sec = (title, body, copyText) => el("div", { class: "psec" },
    el("div", { class: "ph2" }, el("b", {}, title), copyText ? el("button", { class: "btn text", type: "button", onclick: null }, "Copy") : ""), body);
  const letter = sec("Cover letter", el("div", { class: "letter" }, p.letter), p.letter);
  const bullets = p.bullets?.length ? sec("Resume bullets for this job", list(p.bullets), p.bullets.map((b) => "• " + b).join("\n")) : "";
  const kws = p.keywords?.length ? sec("Words to echo", el("div", { class: "tags" }, p.keywords.map((k) => el("span", { class: "tag" }, k)))) : "";
  const qs = p.questions?.length ? sec("Likely interview questions", el("ol", { class: "plain" }, p.questions.map((q) =>
    el("li", {}, el("b", {}, q.q), q.tip ? el("div", { class: "line" }, q.tip) : "")))) : "";
  const study = p.study?.length ? sec("Study plan", list(p.study)) : "";
  const gaps = p.gaps?.length ? sec("Honest gaps", list(p.gaps)) : "";
  const wrap = el("details", { class: "prep", open: open ? "" : null },
    el("summary", {}, iconEl("school"), el("span", {}, `Preparation · ${dayFmt(p.date)}`), el("small", {}, p.model || "")),
    letter, bullets, kws, qs, study, gaps);
  // the "Copy" buttons were created without handlers; wire them to their text
  const texts = [p.letter, p.bullets?.length ? p.bullets.map((b) => "• " + b).join("\n") : null];
  wrap.querySelectorAll(".ph2 button").forEach((b, i) => b.addEventListener("click", () => copy(texts[i], i ? "Bullets" : "Cover letter")));
  return wrap;
}

// ---------------------------------------------------------------- the full card
/** onSkill(skill) lets a skill tag filter the list. */
export function jobCard(j, { onSkill } = {}) {
  const cfg = cfgJS(), card = el("div", { class: "jobcard", "data-id": j.id });
  card.append(el("div", { class: "top" }, el("h4", {}, titleLink(j)), scorePill(j)),
    el("div", { class: "meta" }, metaLine(j) + ` · seen ${dayFmt(j.date)}`));

  const tags = el("div", { class: "tags" });
  const quals = (j.qualifications || []).map((k) => (cfg.qualifications?.[k]?.label || k).split(" (")[0]);
  if (j.remote) tags.append(el("span", { class: "tag" }, "🌍 Remote"));
  if (quals.length) tags.append(el("span", { class: "tag", title: j.qual_guess ? "The advert doesn't say; guessed from the job title" : "" }, "🎓 " + quals.join(" or ") + (j.qual_guess ? " (guess)" : "")));
  if (j.level && cfg.experience_levels?.[j.level]) tags.append(el("span", { class: "tag" }, cfg.experience_levels[j.level].label));
  if (j.min_years) tags.append(el("span", { class: "tag" }, `${j.min_years}+ yrs`));
  const m = matchOf(j);
  if (m) tags.append(el("span", { class: "tag match" + (m.pct >= 70 ? " hi" : "") }, `Resume match ${m.pct}%`));
  for (const k of (j.subfields || []).slice(0, 2)) if (cfg.subfields?.[k]) tags.append(el("span", { class: "tag" }, cfg.subfields[k].label));
  if (j.status === "hidden") tags.append(el("span", { class: "tag warn" }, "hidden by AI"));
  if (tags.children.length) card.append(tags);

  if (j.skills?.length) {
    const have = resumeSkills(), box = el("div", { class: "tags skills", "aria-label": "Skills the advert mentions" });
    for (const s of j.skills.slice(0, 8)) {
      const owned = have.has(s), b = el("button", { type: "button", class: "tag skill" + (S.career ? (owned ? " have" : " miss") : ""),
        title: S.career ? (owned ? "Your resume shows this" : "Not on your resume") : "Show jobs with this skill" }, (S.career && owned ? "✓ " : "") + s);
      if (onSkill) b.addEventListener("click", () => onSkill(s));
      box.append(b);
    }
    card.append(box);
  }
  if (j.requirements) card.append(el("div", { class: "line" }, el("b", {}, "Asks for: "), j.requirements));
  if (j.ai_reason) card.append(el("div", { class: "line" }, el("b", {}, "AI: "), j.ai_reason));
  if (j.ai_note) card.append(el("div", { class: "line" }, el("b", {}, "Note: "), j.ai_note));
  const closing = closingInfo(j.closing), extra = el("div", { class: "line" + (closing?.late ? " late" : "") });
  if (closing) extra.append(closing.text);
  if (j.contact && EMAIL.test(j.contact)) { if (closing) extra.append(" · "); extra.append("apply: ", el("a", { href: "mailto:" + j.contact }, j.contact)); }
  if (extra.childNodes.length) card.append(extra);

  const acts = markButtons(j);
  const prep = S.prepared[j.id], asked = pending()[j.id];
  if (!prep) {
    const b = el("button", { type: "button", class: "act" }, iconEl("school"), asked ? "Preparing…" : "Prepare");
    b.title = "Cover letter, resume bullets, interview questions and a study plan for this job";
    b.addEventListener("click", () => requestPrepare(j));
    acts.append(b);
  }
  const also = (j.also_on || []).filter(([, u]) => safeUrl(u));
  if (also.length) {
    const box = el("span", { class: "also" }, "also on");
    for (const [site, u] of also) box.append(el("a", { href: u, target: "_blank", rel: "noopener" }, site));
    acts.append(box);
  }
  card.append(acts);

  const note = el("textarea", { class: "note", rows: "2", placeholder: "Your note – contact, interview date, what to ask…", maxlength: "600", "aria-label": "Your note" });
  note.value = noteOf(j);
  let t = 0;
  note.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => setNote(j, note.value), 600); });
  card.append(el("details", { class: "notes", open: noteOf(j) ? "" : null }, el("summary", {}, iconEl("event"), noteOf(j) ? "Your note" : "Add a note"), note));
  if (prep) card.append(preparedBlock(prep));
  paintIcons(card);
  return card;
}

// ---------------------------------------------------------------- the compact row
/** One line per job for the Focus view: title, who/where, a chip (closing / match), score, quick marks. */
export function jobRow(j, { chip } = {}) {
  const row = el("div", { class: "jrow", "data-id": j.id });
  const main = el("div", { class: "main" }, el("div", { class: "t" }, titleLink(j)), el("div", { class: "m" }, metaLine(j)));
  const chips = el("div", { class: "chips" });
  if (chip) chips.append(chip);
  const m = matchOf(j);
  if (m) chips.append(el("span", { class: "tag match" + (m.pct >= 70 ? " hi" : "") }, `${m.pct}% match`));
  if (chips.children.length) main.append(chips);
  row.append(main, scorePill(j), markButtons(j, { icons: true }));
  paintIcons(row);
  return row;
}
export const closingChip = (j) => {
  const c = closingInfo(j.closing);
  if (!c) return null;
  const text = c.closed ? c.short : c.days === 0 ? "Closes today" : c.days === 1 ? "Closes tomorrow" : `Closes in ${c.days} days`;
  return el("span", { class: "tag" + (c.late ? " warn" : "") }, iconEl("event"), text);
};

export { refresh };
