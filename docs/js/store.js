// Shared state and small helpers for the dashboard (everything decrypted lives here, in memory only).

export const S = {
  ctx: null, // page helpers handed over by dashboard.js: state, gh, snack, needToken, cfg, applyAction, dispatch, paintIcons, icon
  vault: { meta: null, key: null },
  jobs: [], // history entries, newest data last
  byId: new Map(),
  runs: [], suggestions: [],
  career: null, // the latest career report
  prepared: {}, // job id -> cover letter / interview preparation
  marks: { map: {}, sha: null, timer: 0, pending: false, saving: false, again: false },
  resume: { loaded: false, doc: null, sha: null },
  review: null, // { ids: [...], i } while reviewing one by one
  subs: new Set(),
};

const DEFAULT_UI = { tab: "focus", jobsTab: "inbox", period: 30, hideClosed: true, sort: "importance", dataDays: 30, skill: "" };
export const ui = (() => {
  try { return { ...DEFAULT_UI, ...JSON.parse(localStorage.getItem("jobot.ui") || "{}"), search: "" }; }
  catch { return { ...DEFAULT_UI, search: "" }; }
})();
export const saveUi = () => {
  try { const { search, ...keep } = ui; localStorage.setItem("jobot.ui", JSON.stringify(keep)); } catch {}
};

export const onChange = (fn) => S.subs.add(fn);
export const emit = () => { for (const fn of S.subs) fn(); };

// ---------------------------------------------------------------- dom
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "checked" || k === "value" || k === "disabled") node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== "" && c !== false) node.append(c);
  return node;
}
export const paintIcons = (root) => S.ctx.paintIcons(root);
export const iconEl = (name, cls = "") => el("span", { "data-icon": name, class: cls });

// ---------------------------------------------------------------- dates & numbers
const iso = (d) => d.toLocaleDateString("en-CA"); // YYYY-MM-DD in the viewer's own time zone
export const todayIso = () => iso(new Date());
export const addDays = (isoDate, n) => { const d = new Date(isoDate + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };
export const daysBetween = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 864e5);
export const dayFmt = (isoDate) => new Date(isoDate + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });
export const weekday = (isoDate) => new Date(isoDate + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" });
export const fmt = (n) => (n >= 10000 ? (n / 1000).toFixed(0) + "K" : n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(Math.round(n * 10) / 10));
export const pct = (x) => `${Math.round(x * 100)}%`;
export const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
export const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
export const cfgJS = () => S.ctx.cfg();

export function closingInfo(isoDate) {
  if (!isoDate) return null;
  const days = daysBetween(todayIso(), isoDate);
  if (Number.isNaN(days)) return null;
  if (days < 0) return { text: `Closed ${dayFmt(isoDate)}`, short: "Closed", days, late: true, closed: true };
  const text = days === 0 ? "Closes today" : days === 1 ? "Closes tomorrow" : `Closes ${dayFmt(isoDate)} · ${days} days left`;
  return { text, short: days === 0 ? "Today" : days === 1 ? "Tomorrow" : `${days} days`, days, late: days <= 2, closed: false };
}

// ---------------------------------------------------------------- jobs, marks, resume match
export const TIERS = [
  ["top", "Top picks", "Scored 8 or more by the AI", "star"],
  ["good", "Good fits", "Clear matches for your fields", "bolt"],
  ["maybe", "Worth a look", "Possible, but less certain", "search"],
  ["low", "Low priority", "Held back by the AI or a weak fit", "visibility_off"],
];
export const tierLabel = (key) => (TIERS.find((t) => t[0] === key) || TIERS[2])[1];
export const tierOf = (j) => j.importance || "maybe";
export const markOf = (j) => S.marks.map[j.id]?.s || "";
export const noteOf = (j) => S.marks.map[j.id]?.n || "";
export const isClosed = (j) => !!j.closing && j.closing < todayIso();

export function reindex() { S.byId = new Map(S.jobs.map((j) => [j.id, j])); }

export const resumeSkills = () => new Set(S.career?.resume_skills || []);
/** How much of what the advert asks for the resume shows: { pct, matched, missing } or null. */
export function matchOf(j) {
  if (!S.career) return null;
  const wanted = j.skills || [];
  if (wanted.length < 2) return null;
  const have = resumeSkills();
  const matched = wanted.filter((s) => have.has(s));
  return { pct: Math.round((100 * matched.length) / wanted.length), matched, missing: wanted.filter((s) => !have.has(s)) };
}

/** Jobs sorted for lists: best first. */
export const byImportance = (a, b) =>
  (b.ai_score ?? -1) - (a.ai_score ?? -1) || (a.date < b.date ? 1 : a.date > b.date ? -1 : 0) || a.title.localeCompare(b.title);
export const byNewest = (a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : byImportance(a, b));
export const byClosing = (a, b) => (a.closing || "9999") < (b.closing || "9999") ? -1 : (a.closing || "9999") > (b.closing || "9999") ? 1 : byImportance(a, b);

/** Jobs that are worth acting on now: not held back, not closed. */
export const live = (j) => tierOf(j) !== "low" && !isClosed(j);
