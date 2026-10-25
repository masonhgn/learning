"use strict";

const $ = (id) => document.getElementById(id);

const S = {
  levels: [], challenges: [], schema: {}, progress: null,
  index: 0, attempts: 0, hintsShown: 0, panel: null,
  tableCache: {},      // pristine table data, name -> grid
  modified: {},        // tables as they looked after the last run, name -> grid
  result: null, expected: null, after: null,
  extraTables: [],     // tables opened with the + button
  active: null,        // active sheet tab id
  sort: {},            // tab id -> {col, dir}
  view: null,          // rows currently drawn in the grid, after filter and sort
  sel: null,           // selected cell {r, c}
};

let cm;

//helpers

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const letters = (i) => { let s = ""; i += 1; while (i) { s = String.fromCharCode(65 + ((i - 1) % 26)) + s; i = Math.floor((i - 1) / 26); } return s; };
const current = () => S.challenges[S.index];
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { return null; }
}

//engine: sql runs in a web worker (engine.js) so a runaway query can be stopped by killing it

const QUERY_TIMEOUT = 5000;
let worker, workerReady, nextCall = 0;
const pending = new Map();

function startWorker() {
  worker = new Worker("engine.js");
  worker.onmessage = ({ data }) => {
    const p = pending.get(data.id);
    if (!p) return;
    pending.delete(data.id);
    clearTimeout(p.timer);
    if (data.error !== undefined) p.reject(new Error(data.error));
    else p.resolve(data.value);
  };
  workerReady = call("init", { dbUrl: "sqlquest.db", challenges: S.challenges });
}

function call(op, args, timeout) {
  return new Promise((resolve, reject) => {
    const id = nextCall++;
    const p = { resolve, reject };
    if (timeout) p.timer = setTimeout(() => {
      pending.delete(id);
      worker.terminate();
      for (const q of pending.values()) { clearTimeout(q.timer); q.reject(new Error("the engine was restarted")); }
      pending.clear();
      startWorker();
      reject(new Error(`query took longer than ${QUERY_TIMEOUT / 1000}s and was stopped`));
    }, timeout);
    pending.set(id, p);
    worker.postMessage({ id, op, args });
  });
}

async function engine(op, args, timeout) {
  await workerReady;
  return call(op, args, timeout);
}

//progress lives in this browser's localStorage, in the same format as the terminal version's progress.json

const PROGRESS_KEY = "sqlquest:progress";

function loadProgress() {
  let data = {};
  try { data = JSON.parse(storage(PROGRESS_KEY)) || {}; } catch (e) {}
  const keys = new Set(S.challenges.map((c) => c.key));
  const solved = new Set((data.solved || []).filter((k) => keys.has(k)));
  let index = Math.min(firstUnsolved(solved), S.challenges.length - 1);
  const i = S.challenges.findIndex((c) => c.key === data.current);
  if (i >= 0) index = i;
  return { solved, index };
}

function saveProgress(solved, index) {
  storage(PROGRESS_KEY, JSON.stringify({ solved: [...solved].sort(), current: S.challenges[index].key }, null, 2));
  return progressJson(solved, index);
}

function firstUnsolved(solved) {
  const i = S.challenges.findIndex((c) => !solved.has(c.key));
  return i < 0 ? S.challenges.length : i;
}

function progressJson(solved, index) {
  return { solved: [...solved].sort(), current: index, first_unsolved: firstUnsolved(solved) };
}

async function runChallenge(index, sql) {
  const out = await engine("run", { index, sql }, QUERY_TIMEOUT).catch((e) => ({
    result: null, after: null, changes: 0, modified: {}, status: "error", message: e.message,
    tip: "Usually a JOIN without an ON clause, which pairs every row with every other row.",
  }));
  if (out.status !== "correct") return out;
  const ch = S.challenges[index];
  const { solved } = loadProgress();
  const firstTime = !solved.has(ch.key);
  solved.add(ch.key);
  const levelDone = S.challenges.every((c) => c.level !== ch.level || solved.has(c.key));
  return {
    ...out,
    solution: ch.solution,
    level_complete: firstTime && levelDone,
    all_complete: solved.size === S.challenges.length,
    progress: saveProgress(solved, index),
  };
}

function exportProgress() {
  const { solved, index } = loadProgress();
  const text = JSON.stringify({ solved: [...solved].sort(), current: S.challenges[index].key }, null, 2);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text + "\n"], { type: "application/json" }));
  a.download = "progress.json";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function importProgress(file) {
  let data;
  try { data = JSON.parse(await file.text()); } catch (e) { data = null; }
  if (!data || !Array.isArray(data.solved)) {
    setStatus("error", "✗ Import", "That file isn't a sqlquest progress.json.");
    return;
  }
  storage(PROGRESS_KEY, JSON.stringify(data));
  const { solved, index } = loadProgress();
  S.progress = progressJson(solved, index);
  renderProgress();
  enter(index);
  setStatus("info", "Imported", `${plural(solved.size, "challenge")} marked solved.`);
}

//drafts are a per-browser convenience, like progress

//S.draftFor is the challenge whose draft is in the editor, so switching never writes one challenge's text into another's slot
const draftKey = (key) => `sqlquest:draft:${key}`;
function saveDraft() { if (cm && S.draftFor) storage(draftKey(S.draftFor), cm.getValue()); }

//sidebar and progress

function renderProgress() {
  const done = S.progress.solved.length, total = S.challenges.length;
  $("progress-fill").style.width = `${(100 * done) / total}%`;
  $("progress-text").textContent = `${done} / ${total} solved`;
}

function renderSidebar() {
  const solved = new Set(S.progress.solved);
  let html = "";
  S.levels.forEach((lvl, li) => {
    const items = S.challenges.map((c, i) => [c, i]).filter(([c]) => c.level === li);
    const doneHere = items.filter(([c]) => solved.has(c.key)).length;
    html += `<div class="level-group"><h2><span>${li + 1}. ${esc(lvl.title)}</span><span>${doneHere}/${items.length}</span></h2>`;
    for (const [c, i] of items) {
      const cls = ["challenge-link", solved.has(c.key) ? "solved" : "", i === S.index ? "current" : ""].join(" ");
      const mark = solved.has(c.key) ? "✓" : "○";
      html += `<button class="${cls}" data-i="${i}"><span class="mark">${mark}</span><span class="num">${i + 1}</span><span>${esc(c.title)}</span></button>`;
    }
    html += "</div>";
  });
  $("sidebar").innerHTML = html;
  const cur = $("sidebar").querySelector(".current");
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

//task panel

function emphasize(text, ch) {
  const words = new Set(ch.tables);
  for (const t of ch.tables) for (const col of S.schema[t] || []) words.add(col.name);
  //a quoted string must not touch letters on either side, so apostrophes like order's aren't mistaken for one
  return esc(text).replace(/(?<![A-Za-z])'[^']*'(?![A-Za-z])|\b[A-Za-z_][A-Za-z0-9_]*\b/g, (m) =>
    m.startsWith("'") || words.has(m) ? `<code>${m}</code>` : m);
}

function renderLesson(text) {
  const out = [];
  let code = [], prose = [];
  const flushCode = () => {
    while (code.length && !code[code.length - 1].trim()) code.pop();
    if (code.length) out.push(`<pre>${esc(code.join("\n"))}</pre>`);
    code = [];
  };
  const flushProse = () => { if (prose.length) out.push(`<p>${esc(prose.join(" "))}</p>`); prose = []; };
  for (const line of text.split("\n")) {
    if (line.startsWith("  ")) { flushProse(); code.push(line.slice(2)); }
    else if (!line.trim()) { if (code.length) code.push(""); else flushProse(); }
    else { flushCode(); prose.push(line); }
  }
  flushCode(); flushProse();
  return out.join("");
}

function renderTask() {
  const ch = current();
  $("level-chip").textContent = `Level ${ch.level + 1} · ${S.levels[ch.level].title}`;
  $("task-title").textContent = `${S.index + 1}. ${ch.title}`;
  const tags = [];
  if (ch.ordered) tags.push("row order matters");
  if (ch.modifies) tags.push("changes data · checked by the table state afterwards");
  $("task-tags").textContent = tags.join("  ·  ");
  $("task-prompt").innerHTML = emphasize(ch.prompt, ch);
  $("btn-hint").textContent = ch.hints.length ? `Hint (${S.hintsShown}/${ch.hints.length})` : "Hint";
  $("btn-hint").disabled = !ch.hints.length;
  $("btn-prev").disabled = S.index === 0;
  $("btn-next").disabled = S.index + 1 >= S.challenges.length;
  renderPanel();
}

function showPanel(kind) {
  S.panel = S.panel === kind ? null : kind;
  renderPanel();
}

function renderPanel() {
  const p = $("panel"), ch = current();
  for (const [id, kind] of [["btn-lesson", "lesson"], ["btn-hint", "hint"], ["btn-solution", "solution"], ["btn-schema", "schema"]]) {
    $(id).classList.toggle("on", S.panel === kind);
  }
  p.className = "panel";
  if (!S.panel) { p.hidden = true; return; }
  p.hidden = false;
  if (S.panel === "lesson") {
    p.innerHTML = `<h3>Lesson · ${esc(S.levels[ch.level].title)}</h3>${renderLesson(S.levels[ch.level].lesson)}`;
  } else if (S.panel === "hint") {
    p.classList.add("hint");
    const left = ch.hints.length - S.hintsShown;
    p.innerHTML = `<h3>Hints</h3><ol>${ch.hints.slice(0, S.hintsShown).map((h) => `<li>${emphasize(h, ch)}</li>`).join("")}</ol>` +
      (left ? `<button class="btn" id="more-hint">Show hint ${S.hintsShown + 1} of ${ch.hints.length}</button>` : `<p class="muted small">No more hints. Try Expected output, or the Solution.</p>`);
    const more = $("more-hint");
    if (more) more.onclick = nextHint;
  } else if (S.panel === "solution") {
    p.classList.add("solution");
    if (S.solution && S.solution.index === S.index) {
      p.innerHTML = `<h3>Solution</h3><pre>${esc(S.solution.sql)}</pre><p class="muted small">Type it in yourself to unlock the next one.</p>`;
    } else {
      p.innerHTML = `<h3>Solution</h3><p>Reveal a reference answer? You'll still need to type it in to pass.</p><button class="btn" id="reveal">Reveal solution</button>`;
      $("reveal").onclick = async () => {
        S.solution = { index: S.index, sql: current().solution };
        renderPanel();
      };
    }
  } else if (S.panel === "schema") {
    p.innerHTML = `<h3>Schema · click a table to open it as a sheet</h3><div class="schema-grid">${Object.entries(S.schema).map(([t, cols]) =>
      `<table><caption><a href="#" data-open="${esc(t)}">${esc(t)}</a></caption>${cols.map((c) =>
        `<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td>${esc(c.notes)}</td></tr>`).join("")}</table>`).join("")}</div>`;
    p.querySelectorAll("[data-open]").forEach((a) => a.onclick = (e) => { e.preventDefault(); openTable(a.dataset.open); });
  }
}

function nextHint() {
  const ch = current();
  if (S.hintsShown < ch.hints.length) S.hintsShown += 1;
  S.panel = "hint";
  renderTask();
}

//status line under the editor

function setStatus(kind, badge, html) {
  const el = $("status");
  if (!kind) { el.hidden = true; return; }
  el.hidden = false;
  el.className = `status ${kind}`;
  el.innerHTML = `<span class="badge">${esc(badge)}</span><div class="body">${html}</div>`;
}

//green flash and confetti on a correct answer

function flash(el) {
  el.classList.remove("flash");
  void el.offsetWidth;  //restart the animation if it is already applied
  el.classList.add("flash");
  el.addEventListener("animationend", () => el.classList.remove("flash"), { once: true });
}

function celebrate(big) {
  flash($("status"));
  flash(document.querySelector(".editor-wrap"));
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) confetti(big ? 260 : 120);
}

function confetti(count) {
  const canvas = document.createElement("canvas");
  canvas.id = "confetti";
  document.body.appendChild(canvas);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = innerWidth * dpr;
  canvas.height = innerHeight * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const colors = ["#1e7f45", "#3cb371", "#7fd49a", "#f4c542", "#e8573f", "#3b82f6", "#a855f7"];
  //two bursts from the bottom corners, aimed up and inward
  const bits = Array.from({ length: count }, (_, i) => {
    const left = i % 2 === 0;
    const angle = (left ? -60 : -120) * Math.PI / 180 + (Math.random() - 0.5) * 0.9;
    const speed = 9 + Math.random() * 9;
    return {
      x: left ? 0 : innerWidth, y: innerHeight * 0.9,
      vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
      w: 6 + Math.random() * 6, h: 8 + Math.random() * 8,
      rot: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3,
      color: colors[Math.floor(Math.random() * colors.length)],
    };
  });
  const start = performance.now();
  function frame(now) {
    const t = now - start;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    ctx.globalAlpha = Math.max(0, Math.min(1, (3000 - t) / 800));
    for (const b of bits) {
      b.vy += 0.25;
      b.vx *= 0.99;
      b.x += b.vx;
      b.y += b.vy;
      b.rot += b.vr;
      ctx.save();
      ctx.translate(b.x, b.y);
      ctx.rotate(b.rot);
      ctx.fillStyle = b.color;
      ctx.fillRect(-b.w / 2, -b.h / 2, b.w, b.h * Math.cos(b.rot * 2));
      ctx.restore();
    }
    if (t < 3000) requestAnimationFrame(frame);
    else canvas.remove();
  }
  requestAnimationFrame(frame);
}

//sheet tabs

function tabList() {
  const tabs = [{ id: "result", label: "Result", special: true }];
  if (S.after) tabs.push({ id: "after", label: "Checked state", special: true });
  if (S.expected) tabs.push({ id: "expected", label: "Expected", special: true });
  const seen = new Set();
  for (const t of current().tables) { seen.add(t); tabs.push({ id: `t:${t}`, label: t, table: t }); }
  for (const t of S.extraTables) if (!seen.has(t)) tabs.push({ id: `t:${t}`, label: t, table: t, closable: true });
  return tabs;
}

function renderTabs() {
  const tabs = tabList();
  if (!tabs.some((t) => t.id === S.active)) S.active = tabs[0].id;
  $("tabs").innerHTML = tabs.map((t) => {
    const dot = t.table && S.modified[t.table] ? `<span class="dot" title="changed by your last run">•</span>` : "";
    const close = t.closable ? `<span class="close" data-close="${esc(t.table)}" title="close">×</span>` : "";
    return `<button class="tab ${t.special ? "special" : ""} ${t.id === S.active ? "active" : ""}" data-tab="${esc(t.id)}">${esc(t.label)}${dot}${close}</button>`;
  }).join("");
  const open = new Set(tabs.filter((t) => t.table).map((t) => t.table));
  $("add-menu").innerHTML = Object.keys(S.schema).map((t) =>
    `<button data-open="${esc(t)}">${open.has(t) ? "✓ " : ""}${esc(t)}</button>`).join("");
}

function activate(id) {
  S.active = id;
  S.sel = null;
  renderTabs();
  renderSheet();
}

function openTable(name) {
  if (!current().tables.includes(name) && !S.extraTables.includes(name)) S.extraTables.push(name);
  activate(`t:${name}`);
}

function closeTable(name) {
  S.extraTables = S.extraTables.filter((t) => t !== name);
  if (S.active === `t:${name}`) S.active = null;
  renderTabs();
  renderSheet();
}

//the grid

function gridFor(id) {
  if (id === "result") return S.result;
  if (id === "after") return S.after;
  if (id === "expected") return S.expected;
  const name = id.slice(2);
  return S.modified[name] || S.tableCache[name];
}

function compareValues(a, b) {
  if (a === b) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number") return -1;
  if (typeof b === "number") return 1;
  return String(a).localeCompare(String(b));
}

function renderSheet() {
  const id = S.active;
  const sheet = $("sheet");
  if (id.startsWith("t:") && !gridFor(id)) {
    const name = id.slice(2);
    sheet.innerHTML = `<div class="empty">Loading ${esc(name)}…</div>`;
    engine("table", { name }).then((g) => { S.tableCache[name] = g; if (S.active === id) renderSheet(); });
    return;
  }
  const g = gridFor(id);
  if (!g) {
    const msg = id === "result" ? (S.lastRunChanged ? "Your statements didn't return rows. Check the table tabs (• marks changed ones) or Checked state." : "Run a query to see its result here.") : "Nothing here yet.";
    sheet.innerHTML = `<div class="empty">${esc(msg)}</div>`;
    S.view = null;
    $("row-count").textContent = "";
    updateFormula();
    return;
  }

  const filter = $("filter").value.trim().toLowerCase();
  let rows = g.rows;
  if (filter) rows = rows.filter((r) => r.some((v) => v !== null && String(v).toLowerCase().includes(filter)));
  const sort = S.sort[id];
  if (sort) {
    rows = rows.map((r, i) => [r, i]).sort((a, b) => compareValues(a[0][sort.col], b[0][sort.col]) * sort.dir || a[1] - b[1]).map((x) => x[0]);
  }
  S.view = rows;

  //rows that aren't in the pristine table were inserted or updated by the last run
  let pristine = null;
  if (id.startsWith("t:") && S.modified[id.slice(2)] && S.tableCache[id.slice(2)]) {
    pristine = new Set(S.tableCache[id.slice(2)].rows.map((r) => JSON.stringify(r)));
  } else if (id.startsWith("t:") && S.modified[id.slice(2)]) {
    engine("table", { name: id.slice(2) }).then((t) => { S.tableCache[id.slice(2)] = t; if (S.active === id) renderSheet(); });
  }

  const types = {};
  if (id.startsWith("t:")) for (const c of S.schema[id.slice(2)] || []) types[c.name] = c;

  const parts = ['<table class="grid"><thead><tr class="letters"><th class="corner"></th>'];
  g.columns.forEach((_, c) => parts.push(`<th data-col="${c}">${letters(c)}</th>`));
  parts.push('</tr><tr class="names"><th class="corner"></th>');
  g.columns.forEach((name, c) => {
    const arrow = sort && sort.col === c ? `<span class="arrow">${sort.dir > 0 ? "▲" : "▼"}</span>` : "";
    const t = types[name];
    const title = t ? `${t.type}${t.notes ? " · " + t.notes : ""} — click to sort` : "click to sort";
    parts.push(`<th data-sort="${c}" title="${esc(title)}">${esc(name)}${arrow}</th>`);
  });
  parts.push("</tr></thead><tbody>");
  rows.forEach((r, ri) => {
    const changed = pristine && !pristine.has(JSON.stringify(r)) ? ' class="changed"' : "";
    parts.push(`<tr${changed}><th>${ri + 1}</th>`);
    r.forEach((v, ci) => {
      if (v === null) parts.push(`<td class="null" data-r="${ri}" data-c="${ci}">NULL</td>`);
      else parts.push(`<td${typeof v === "number" ? ' class="num"' : ""} data-r="${ri}" data-c="${ci}">${esc(v)}</td>`);
    });
    parts.push("</tr>");
  });
  parts.push("</tbody></table>");
  sheet.innerHTML = parts.join("");

  const total = g.total ?? g.rows.length;
  let count = filter ? `${rows.length} of ${g.rows.length} rows` : plural(g.rows.length, "row");
  if (total > g.rows.length) count += ` (first ${g.rows.length} of ${total})`;
  $("row-count").textContent = `${count} · ${plural(g.columns.length, "column")}`;
  if (S.sel && (S.sel.r >= rows.length || S.sel.c >= g.columns.length)) S.sel = null;
  drawSelection();
}

function drawSelection() {
  const sheet = $("sheet");
  sheet.querySelectorAll(".sel, .hl").forEach((el) => el.classList.remove("sel", "hl"));
  if (S.sel) {
    const td = sheet.querySelector(`td[data-r="${S.sel.r}"][data-c="${S.sel.c}"]`);
    if (td) {
      td.classList.add("sel");
      td.parentElement.firstElementChild.classList.add("hl");
      const letter = sheet.querySelector(`tr.letters th[data-col="${S.sel.c}"]`);
      if (letter) letter.classList.add("hl");
      td.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }
  updateFormula();
}

function updateFormula() {
  const g = gridFor(S.active);
  if (!S.sel || !g || !S.view) { $("name-box").textContent = ""; $("formula-value").textContent = ""; return; }
  const v = S.view[S.sel.r][S.sel.c];
  $("name-box").textContent = `${letters(S.sel.c)}${S.sel.r + 1} · ${g.columns[S.sel.c]}`;
  $("name-box").title = $("name-box").textContent;
  $("formula-value").textContent = v === null ? "NULL" : String(v);
  $("formula-value").title = $("formula-value").textContent;
}

function sqlLiteral(v) {
  if (v === null) return "NULL";
  if (typeof v === "number") return String(v);
  return `'${String(v).replace(/'/g, "''")}'`;
}

function insertIntoEditor(text) {
  cm.replaceSelection(text);
  cm.focus();
}

//challenges

function enter(index, { lesson } = {}) {
  saveDraft();
  const prevLevel = S.challenges.length && S.index !== index ? current().level : null;
  S.index = index;
  S.attempts = 0;
  S.hintsShown = 0;
  S.result = S.after = S.expected = null;
  S.modified = {};
  S.lastRunChanged = false;
  S.sel = null;
  S.sort = {};
  const ch = current();
  const showLesson = lesson ?? (prevLevel !== null && prevLevel !== ch.level);
  S.panel = showLesson ? "lesson" : S.panel === "schema" ? "schema" : null;
  S.active = ch.tables.length ? `t:${ch.tables[0]}` : "result";
  cm.setValue(storage(draftKey(ch.key)) || "");
  S.draftFor = ch.key;
  cm.clearHistory();
  setStatus(null);
  renderTask();
  renderSidebar();
  renderTabs();
  renderSheet();
  cm.focus();
  S.progress = saveProgress(loadProgress().solved, index);
}

async function run() {
  const sql = cm.getValue();
  if (!sql.trim()) { setStatus("info", "Empty", "Type a query first."); return; }
  saveDraft();
  S.attempts += 1;
  $("btn-run").disabled = true;
  let d;
  try {
    d = await runChallenge(S.index, sql);
  } catch (e) {
    setStatus("error", "✗ Error", esc(e.message));
    return;
  } finally {
    $("btn-run").disabled = false;
  }
  const ch = current();
  S.result = d.result;
  S.after = d.after;
  S.modified = d.modified || {};
  S.lastRunChanged = d.changes > 0;
  S.sort.result = undefined;
  S.sort.after = undefined;
  for (const t of Object.keys(S.modified)) S.sort[`t:${t}`] = undefined;
  for (const t of Object.keys(S.modified)) if (!ch.tables.includes(t) && !S.extraTables.includes(t)) S.extraTables.push(t);

  const changedNote = d.changes ? `<div class="tip">${plural(d.changes, "row")} changed on a throwaway copy · tabs marked • show the changed tables</div>` : "";
  if (d.status === "error") {
    setStatus("error", "✗ Error", `${esc(d.message)}${d.tip ? `<div class="tip">${esc(d.tip)}</div>` : ""}`);
  } else if (d.status === "wrong") {
    const left = ch.hints.length - S.hintsShown;
    const tip = left ? `${plural(left, "hint")} left, or compare with Expected output` : "Expected output shows the target, Solution reveals an answer";
    setStatus("wrong", "✗ Not quite", `${esc(d.message)}<div class="tip">${tip}</div>${changedNote}`);
  } else {
    S.progress = d.progress;
    const tries = S.attempts === 1 ? "first try!" : `${S.attempts} attempts`;
    let html = `Correct, ${tries}`;
    if (d.all_complete && d.level_complete) html += `<div class="celebrate">All ${S.challenges.length} challenges cleared. You are officially dangerous with SQL.</div>`;
    else if (d.level_complete) html += `<div class="celebrate">Level ${ch.level + 1} complete! Up next: ${esc(S.levels[ch.level + 1].title)}</div>`;
    html += `<pre>${esc(d.solution)}</pre><div class="tip">One way to write it.</div>`;
    if (S.index + 1 < S.challenges.length) html += `<div style="margin-top:6px"><button class="btn primary" id="go-next">Next challenge ›</button></div>`;
    setStatus("correct", "✓ Correct", html);
    celebrate(d.level_complete);
    const goNext = $("go-next");
    if (goNext) goNext.onclick = () => enter(S.index + 1);
    renderSidebar();
    renderProgress();
    renderTask();
  }

  if (d.status !== "error") {
    if (d.result) S.active = "result";
    else if (Object.keys(S.modified).length) S.active = `t:${Object.keys(S.modified)[0]}`;
    else if (d.after) S.active = "after";
    else S.active = "result";
  }
  S.sel = null;
  renderTabs();
  renderSheet();
}

async function showExpected() {
  try {
    S.expected = await engine("expected", { index: S.index });
  } catch (e) {
    setStatus("error", "✗ Error", esc(e.message));
    return;
  }
  activate("expected");
}

//wiring

function bind() {
  $("btn-run").onclick = run;
  $("btn-prev").onclick = () => S.index > 0 && enter(S.index - 1);
  $("btn-next").onclick = () => enter(S.index + 1);
  $("btn-lesson").onclick = () => showPanel("lesson");
  $("btn-schema").onclick = () => showPanel("schema");
  $("btn-solution").onclick = () => showPanel("solution");
  $("btn-expected").onclick = showExpected;
  $("btn-hint").onclick = () => {
    if (S.panel === "hint" && S.hintsShown >= current().hints.length) showPanel("hint");
    else if (S.panel !== "hint" && S.hintsShown > 0) { S.panel = "hint"; renderPanel(); }
    else nextHint();
  };

  let resetArmed = null;
  $("btn-reset").onclick = async () => {
    const btn = $("btn-reset");
    if (!resetArmed) {
      btn.textContent = "Click again to erase";
      btn.classList.add("on");
      resetArmed = setTimeout(() => { resetArmed = null; btn.textContent = "Reset progress"; btn.classList.remove("on"); }, 3000);
      return;
    }
    clearTimeout(resetArmed);
    resetArmed = null;
    btn.textContent = "Reset progress";
    btn.classList.remove("on");
    S.progress = saveProgress(new Set(), 0);
    renderProgress();
    enter(0, { lesson: true });
  };

  $("btn-export").onclick = exportProgress;
  $("btn-import").onclick = () => $("import-file").click();
  $("import-file").onchange = (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) importProgress(file);
  };

  $("sidebar").onclick = (e) => {
    const b = e.target.closest("[data-i]");
    if (b) enter(Number(b.dataset.i));
  };

  $("tabs").onclick = (e) => {
    const close = e.target.closest("[data-close]");
    if (close) { e.stopPropagation(); closeTable(close.dataset.close); return; }
    const tab = e.target.closest("[data-tab]");
    if (tab) activate(tab.dataset.tab);
  };

  $("btn-add-tab").onclick = (e) => { e.stopPropagation(); $("add-menu").hidden = !$("add-menu").hidden; };
  $("add-menu").onclick = (e) => {
    const b = e.target.closest("[data-open]");
    if (b) { openTable(b.dataset.open); $("add-menu").hidden = true; }
  };
  document.addEventListener("click", (e) => { if (!e.target.closest(".add-tab")) $("add-menu").hidden = true; });

  $("filter").oninput = () => { S.sel = null; renderSheet(); };

  const sheet = $("sheet");
  sheet.tabIndex = 0;
  sheet.onclick = (e) => {
    const sortTh = e.target.closest("[data-sort]");
    if (sortTh) {
      const col = Number(sortTh.dataset.sort), s = S.sort[S.active];
      S.sort[S.active] = !s || s.col !== col ? { col, dir: 1 } : s.dir === 1 ? { col, dir: -1 } : undefined;
      renderSheet();
      return;
    }
    const td = e.target.closest("td[data-r]");
    if (td) { S.sel = { r: Number(td.dataset.r), c: Number(td.dataset.c) }; drawSelection(); }
  };
  sheet.ondblclick = (e) => {
    const td = e.target.closest("td[data-r]");
    if (td && S.view) insertIntoEditor(sqlLiteral(S.view[Number(td.dataset.r)][Number(td.dataset.c)]));
    const letter = e.target.closest("[data-col]");
    if (letter) insertIntoEditor(gridFor(S.active).columns[Number(letter.dataset.col)]);
  };
  sheet.onkeydown = (e) => {
    if (!S.sel || !S.view) return;
    const g = gridFor(S.active);
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Enter: [1, 0], Tab: [0, e.shiftKey ? -1 : 1] };
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    S.sel = {
      r: Math.max(0, Math.min(S.view.length - 1, S.sel.r + m[0])),
      c: Math.max(0, Math.min(g.columns.length - 1, S.sel.c + m[1])),
    };
    drawSelection();
  };

  //drag the splitter to trade editor height for grid height
  const splitter = $("splitter");
  splitter.onmousedown = (e) => {
    e.preventDefault();
    const startY = e.clientY, startH = cm.getWrapperElement().offsetHeight;
    splitter.classList.add("dragging");
    const move = (ev) => cm.setSize(null, Math.max(60, Math.min(window.innerHeight * 0.6, startH + ev.clientY - startY)));
    const up = () => {
      splitter.classList.remove("dragging");
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      storage("sqlquest:editor-h", String(cm.getWrapperElement().offsetHeight));
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };

  window.addEventListener("beforeunload", saveDraft);
}

async function init() {
  const res = await fetch("data.json");
  if (!res.ok) throw new Error(`data.json (${res.status})`);
  Object.assign(S, await res.json());
  startWorker();
  const { solved, index } = loadProgress();
  S.progress = progressJson(solved, index);
  S.index = index;

  const hintTables = {};
  for (const [t, cols] of Object.entries(S.schema)) hintTables[t] = cols.map((c) => c.name);
  cm = CodeMirror($("editor"), {
    mode: "text/x-sqlite",
    lineNumbers: true,
    matchBrackets: true,
    indentUnit: 4,
    smartIndent: true,
    extraKeys: {
      "Ctrl-Enter": run,
      "Cmd-Enter": run,
      "Ctrl-Space": "autocomplete",
      Tab: (c) => c.replaceSelection("    "),
    },
    hintOptions: { tables: hintTables, completeSingle: false },
  });
  const savedH = Number(storage("sqlquest:editor-h"));
  if (savedH) cm.setSize(null, savedH);
  let draftTimer;
  cm.on("change", () => { clearTimeout(draftTimer); draftTimer = setTimeout(saveDraft, 400); });
  cm.on("inputRead", (c, change) => { if (change.text[0] === ".") c.showHint(); });

  bind();
  renderProgress();
  const first = S.challenges.findIndex((c) => c.level === current().level);
  enter(S.index, { lesson: first === S.index && !S.progress.solved.includes(current().key) });
}

//password gate. this only keeps casual visitors out: the site's files are public, so it is not real security
const PASSWORD_SHA256 = "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4";
const UNLOCK_KEY = "sqlquest:unlocked";

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function unlock() {
  if (storage(UNLOCK_KEY) === PASSWORD_SHA256) return Promise.resolve();
  const gate = $("gate");
  gate.hidden = false;
  $("gate-password").focus();
  return new Promise((resolve) => {
    $("gate-form").onsubmit = async (e) => {
      e.preventDefault();
      if (await sha256($("gate-password").value) === PASSWORD_SHA256) {
        storage(UNLOCK_KEY, PASSWORD_SHA256);
        gate.hidden = true;
        resolve();
      } else {
        $("gate-error").hidden = false;
        $("gate-password").select();
      }
    };
  });
}

unlock()
  .then(init)
  .catch((e) => setStatus("error", "✗ Error", `Couldn't load: ${esc(e.message)}`));
