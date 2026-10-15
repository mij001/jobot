// Decryption, loading and saving of the password-protected data (data/history/*.enc.json).
// Key = PBKDF2-SHA256 of your password; files = AES-256-GCM over gzip(JSON). Nothing here is sent anywhere
// except back to your own repository (marks, notes, resume), encrypted.
import { S, emit, reindex } from "./store.js";

const HISTORY = "data/history";
const MARKS = `${HISTORY}/marks.enc.json`;
const RESUME = `${HISTORY}/resume.enc.json`;
const SAVE_DELAY = 1500;

// ---------------------------------------------------------------- crypto
export const fromB64 = (s) => Uint8Array.from(atob(s.replace(/\s/g, "")), (c) => c.charCodeAt(0));
export const toB64 = (u8) => { let bin = ""; for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode(...u8.subarray(i, i + 0x8000)); return btoa(bin); };
async function pbkdf2Key(password, meta) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: fromB64(meta.salt), iterations: meta.iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]);
}
async function openBlob(key, blob) {
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromB64(blob.iv) }, key, fromB64(blob.ct));
  return JSON.parse(await new Response(new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"))).text());
}
async function sealBlob(key, obj) {
  const gz = await new Response(new Blob([JSON.stringify(obj)]).stream().pipeThrough(new CompressionStream("gzip"))).arrayBuffer();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  return { v: 1, iv: toB64(iv), ct: toB64(new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, gz))) };
}
const isRightKey = async (key) => { try { return (await openBlob(key, S.vault.meta.check)) === "jobot-vault-v1"; } catch { return false; } };

// ---------------------------------------------------------------- GitHub reads
async function raw(path) {
  const st = S.ctx.state, headers = { Accept: "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28" };
  if (st.token) headers.Authorization = `Bearer ${st.token}`;
  const r = await fetch(`${S.ctx.API}/repos/${st.repo}/contents/${path}?ref=${encodeURIComponent(st.branch)}`, { headers });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${r.status}`);
  return r.text();
}
const ref = () => encodeURIComponent(S.ctx.state.branch);
const repo = () => S.ctx.state.repo;

// ---------------------------------------------------------------- unlock / lock
export const supported = () => !!(window.DecompressionStream && window.CompressionStream && crypto?.subtle);

/** What state is the vault in? { status: "setup" | "locked" | "open" | "error", message } */
export async function init() {
  if (!supported()) return { status: "error", message: "This browser can't decrypt the data – please use an up-to-date Chrome, Firefox, Safari or Edge." };
  try { S.vault.meta = JSON.parse((await raw(`${HISTORY}/vault.json`)) || "null"); }
  catch (err) { return { status: "error", message: `Couldn't reach GitHub (${err.message}). Reload to try again.` }; }
  if (!S.vault.meta) return { status: "setup" };
  let stored = null;
  try { stored = sessionStorage.getItem("jobot.vk") || localStorage.getItem("jobot.vk"); } catch {}
  if (stored) {
    try {
      const key = await crypto.subtle.importKey("raw", fromB64(stored), "AES-GCM", true, ["encrypt", "decrypt"]);
      if (await isRightKey(key)) { await open(key, false); return { status: "open" }; }
    } catch {}
    forgetKey();
  }
  return { status: "locked" };
}
export function forgetKey() { try { sessionStorage.removeItem("jobot.vk"); localStorage.removeItem("jobot.vk"); } catch {} }

export async function unlock(password, remember) {
  try {
    const key = await pbkdf2Key(password, S.vault.meta);
    if (!(await isRightKey(key))) return { ok: false, message: "That isn't the password – try again." };
    await open(key, remember);
    return { ok: true };
  } catch (err) { return { ok: false, message: `Couldn't unlock: ${err.message}` }; }
}

async function open(key, remember) {
  S.vault.key = key;
  await loadAll();
  try {
    const exported = toB64(new Uint8Array(await crypto.subtle.exportKey("raw", key)));
    sessionStorage.setItem("jobot.vk", exported);
    if (remember) localStorage.setItem("jobot.vk", exported);
  } catch {}
}

/** (Re)read every encrypted file; also used to pick up a fresh career report. */
export async function loadAll() {
  const key = S.vault.key;
  const names = S.vault.meta.shards || [];
  const parts = await Promise.all(names.map(async (name) => {
    const text = await raw(`${HISTORY}/${name}.enc.json`);
    return [name, text ? await openBlob(key, JSON.parse(text)) : null];
  }));
  S.jobs = []; S.runs = []; S.suggestions = []; S.career = null; S.prepared = {};
  for (const [name, data] of parts) {
    if (!data) continue;
    if (name === "stats") { S.runs = data.runs || []; S.suggestions = data.suggestions || []; }
    else if (name === "career") S.career = data;
    else if (name === "prepare") S.prepared = data;
    else if (name.startsWith("jobs-")) S.jobs.push(...data);
  }
  reindex();
  await loadMarks();
}
export async function refresh() {  // a new run finished? fetch the latest vault.json and everything under it
  S.vault.meta = JSON.parse((await raw(`${HISTORY}/vault.json`)) || "null") || S.vault.meta;
  await loadAll(); emit();
}

export function lock() {
  forgetKey();
  clearTimeout(S.marks.timer);
  S.vault.key = null;
  Object.assign(S, { jobs: [], byId: new Map(), runs: [], suggestions: [], career: null, prepared: {}, review: null });
  Object.assign(S.marks, { map: {}, sha: null, pending: false });
  Object.assign(S.resume, { loaded: false, doc: null, sha: null });
}

// ---------------------------------------------------------------- your marks and notes
async function loadMarks() {
  try {
    const file = await S.ctx.gh(`/repos/${repo()}/contents/${MARKS}?ref=${ref()}`);
    S.marks.sha = file.sha;
    const text = file.content ? S.ctx.b64decode(file.content) : await raw(MARKS);
    S.marks.map = await openBlob(S.vault.key, JSON.parse(text));
  } catch (err) {
    if (err.status !== 404) throw err;
    S.marks.map = {}; S.marks.sha = null;
  }
}
function mergeNewest(into, from) {
  for (const [id, m] of Object.entries(from)) if (!into[id] || (into[id].t || "") < (m.t || "")) into[id] = m;
}
async function saveMarks(retry = true) {
  const cutoff = new Date(Date.now() - 30 * 864e5).toISOString();
  for (const [id, m] of Object.entries(S.marks.map)) if (!m.s && !m.n && (m.t || "") < cutoff) delete S.marks.map[id];
  const body = { message: "Update job marks", branch: S.ctx.state.branch,
    content: S.ctx.b64encode(JSON.stringify(await sealBlob(S.vault.key, S.marks.map)) + "\n") };
  if (S.marks.sha) body.sha = S.marks.sha;
  try {
    const res = await S.ctx.gh(`/repos/${repo()}/contents/${MARKS}`, { method: "PUT", body: JSON.stringify(body) });
    S.marks.sha = res.content.sha;
  } catch (err) {
    if ((err.status === 409 || err.status === 422) && retry) {  // changed from another device: merge, newest wins
      const mine = S.marks.map;
      await loadMarks(); mergeNewest(S.marks.map, mine);
      return saveMarks(false);
    }
    throw err;
  }
}
const setState = (text, bad = false) => S.ctx.marksState?.(text, bad);

/** Saves are batched: tapping through a list of jobs makes one commit, not one per tap. */
function schedule() {
  S.marks.pending = true; setState("Unsaved");
  clearTimeout(S.marks.timer);
  S.marks.timer = setTimeout(flush, SAVE_DELAY);
}
export async function flush() {
  clearTimeout(S.marks.timer);
  if (!S.marks.pending) return;
  if (S.marks.saving) { S.marks.again = true; return; }
  S.marks.saving = true; S.marks.pending = false; setState("Saving…");
  try {
    await saveMarks();
    setState("Saved ✓");
    setTimeout(() => { if (!S.marks.pending && !S.marks.saving) setState(""); }, 2500);
  } catch (err) {
    S.marks.pending = true;
    setState("Couldn't save", true);
    S.ctx.snack([401, 403, 404].includes(err.status) ? `GitHub refused the token (${err.message}). It needs Contents: Read and write.` : "Couldn't save your marks: " + err.message, true);
  } finally {
    S.marks.saving = false;
    if (S.marks.again) { S.marks.again = false; flush(); }
  }
}
export function setMark(job, status) {
  if (S.ctx.needToken()) return false;
  const cur = S.marks.map[job.id];
  S.marks.map[job.id] = { s: status, t: new Date().toISOString(), ...(cur?.n ? { n: cur.n } : {}) };
  schedule(); emit();
  return true;
}
export function setNote(job, text) {
  if (S.ctx.needToken()) return false;
  const cur = S.marks.map[job.id];
  const n = text.trim().slice(0, 600);
  S.marks.map[job.id] = { s: cur?.s || "", t: new Date().toISOString(), ...(n ? { n } : {}) };
  schedule();  // no re-render: the note box keeps its cursor
  return true;
}

// ---------------------------------------------------------------- the resume (stored encrypted, read by the bot)
export async function loadResume() {
  try {
    const file = await S.ctx.gh(`/repos/${repo()}/contents/${RESUME}?ref=${ref()}`);
    S.resume.sha = file.sha;
    const text = file.content ? S.ctx.b64decode(file.content) : await raw(RESUME);  // >1 MB comes back empty from the JSON API
    S.resume.doc = await openBlob(S.vault.key, JSON.parse(text));
  } catch (err) {
    if (err.status !== 404) throw err;
    S.resume.doc = null; S.resume.sha = null;
  }
  S.resume.loaded = true;
}
export async function saveResume(doc) {
  if (S.ctx.needToken()) return false;
  const body = { message: "Update resume", branch: S.ctx.state.branch,
    content: S.ctx.b64encode(JSON.stringify(await sealBlob(S.vault.key, doc)) + "\n") };
  if (S.resume.sha) body.sha = S.resume.sha;
  const res = await S.ctx.gh(`/repos/${repo()}/contents/${RESUME}`, { method: "PUT", body: JSON.stringify(body) });
  S.resume.sha = res.content.sha; S.resume.doc = doc;
  return true;
}
export async function deleteResume() {
  if (S.ctx.needToken() || !S.resume.sha) return false;
  await S.ctx.gh(`/repos/${repo()}/contents/${RESUME}`, { method: "DELETE",
    body: JSON.stringify({ message: "Remove resume", sha: S.resume.sha, branch: S.ctx.state.branch }) });
  S.resume.doc = null; S.resume.sha = null;
  return true;
}
