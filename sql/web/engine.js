/* sqlquest engine: a web worker that runs sql with sql.js and checks answers, a port of engine.py.
   it lives in a worker so the page can kill it when a query runs too long */
"use strict";

const SQLJS = "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.12.0/";
importScripts(SQLJS + "sql-wasm.js");

const MAX_ROWS_RETURNED = 2000;

let SQL, pristine, tableNames, challenges;
const expectedCache = {};

class QueryError extends Error {}

//database

function fresh() {
  const db = new SQL.Database(pristine);
  db.run("PRAGMA foreign_keys = ON");
  return db;
}

function totalChanges(db) {
  return db.exec("SELECT total_changes()")[0].values[0][0];
}

//runs one or more statements and returns [result, changes] where result is [columns, rows] of the last result set
function runSql(db, sql) {
  let result = null;
  const before = totalChanges(db);
  try {
    for (const stmt of db.iterateStatements(sql)) {
      try {
        const cols = stmt.getColumnNames();
        const rows = [];
        while (stmt.step()) rows.push(stmt.get());
        if (cols.length) result = [cols, rows];
      } finally {
        stmt.free();
      }
    }
  } catch (e) {
    throw new QueryError(e.message);
  }
  return [result, totalChanges(db) - before];
}

function tablesUsed(sql) {
  const found = [];
  for (const name of tableNames) {
    const m = new RegExp(`\\b${name}\\b`, "i").exec(sql);
    if (m) found.push([m.index, name]);
  }
  return found.sort((a, b) => a[0] - b[0]).map(([, name]) => name);
}

//(cols, rows) to the grid shape the page draws, capped so a runaway cross join can't flood it
function grid(result) {
  if (!result) return null;
  const [cols, rows] = result;
  return { columns: cols, rows: rows.slice(0, MAX_ROWS_RETURNED), total: rows.length };
}

function dumpTable(db, name) {
  const [result] = runSql(db, `SELECT * FROM "${name}"`);
  return grid(result);
}

function expected(index) {
  if (!(index in expectedCache)) {
    const ch = challenges[index];
    const db = fresh();
    let [result] = runSql(db, ch.solution);
    if (ch.check) [result] = runSql(db, ch.check);
    db.close();
    expectedCache[index] = result;
  }
  return expectedCache[index];
}

//comparing results

const isNumber = (v) => typeof v === "number";

function sortKey(v) {
  if (v === null) return [0, 0];
  if (isNumber(v)) return [1, Math.round(v * 100) / 100];
  if (typeof v === "string") return [2, v];
  return [3, String(v)];
}

function compareRows(a, b) {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const [ra, va] = sortKey(a[i]), [rb, vb] = sortKey(b[i]);
    if (ra !== rb) return ra - rb;
    if (va < vb) return -1;
    if (va > vb) return 1;
  }
  return a.length - b.length;
}

function cellsMatch(e, a) {
  if (isNumber(e) && isNumber(a)) return Math.abs(e - a) <= Math.max(0.011, Math.abs(e) * 1e-4);
  return e === a;
}

function rowsMatch(expected, actual) {
  return expected.every((e, i) => {
    const a = actual[i];
    return e.length === a.length && e.every((x, j) => cellsMatch(x, a[j]));
  });
}

function sameRowsAnyOrder(expected, actual) {
  return rowsMatch([...expected].sort(compareRows), [...actual].sort(compareRows));
}

function* permutations(items) {
  if (items.length <= 1) { yield items; return; }
  for (let i = 0; i < items.length; i++) {
    const rest = [...items.slice(0, i), ...items.slice(i + 1)];
    for (const p of permutations(rest)) yield [items[i], ...p];
  }
}

//returns [correct, feedback]
function compare(expected, actual, ordered) {
  if (!actual) return [false, "Your SQL ran but returned no result set. Did you write a SELECT?"];
  const [ecols, erows] = expected;
  const [acols, arows] = actual;
  if (acols.length !== ecols.length) return [false, `Expected ${ecols.length} column(s), your query returned ${acols.length}.`];
  if (arows.length !== erows.length) return [false, `Expected ${erows.length} row(s), your query returned ${arows.length}.`];
  if (ordered && rowsMatch(erows, arows)) return [true, ""];
  if (sameRowsAnyOrder(erows, arows)) {
    if (!ordered) return [true, ""];
    return [false, "Right rows, wrong order. Check your ORDER BY and tie breakers."];
  }
  if (ecols.length > 1 && ecols.length <= 6) {
    for (const perm of permutations([...acols.keys()])) {
      const shuffled = arows.map((r) => perm.map((i) => r[i]));
      if (sameRowsAnyOrder(erows, shuffled)) return [false, "Right data, but the columns are in a different order than asked."];
    }
  }
  return [false, "Right shape (rows and columns), but some values differ."];
}

//a beginner friendly nudge for common sqlite errors
function errorTip(message) {
  const msg = message.toLowerCase();
  if (msg.includes("no such column")) return "Check the spelling, or open Schema to see each table's columns.";
  if (msg.includes("no such table")) return "Open Schema to see the table names.";
  if (msg.includes("ambiguous column")) return "Two joined tables share that column name. Prefix it with a table alias, like c.id.";
  if (msg.includes("syntax error")) return "Look just before the quoted word: a missing comma, a stray comma, or a misspelled keyword.";
  if (msg.includes("incomplete input")) return "Something is unclosed: a quote, a parenthesis, or a CASE without END.";
  if (msg.includes("foreign key")) return "Another table still points at the rows you are changing. Deal with those first.";
  if (msg.includes("misuse of aggregate")) return "Aggregates like COUNT or SUM can't go in WHERE. Use HAVING, or a subquery.";
  return "";
}

//operations the page can ask for

function run({ index, sql }) {
  const ch = challenges[index];
  const out = { result: null, after: null, changes: 0, modified: {} };
  const db = fresh();
  let result;
  try {
    let changes;
    [result, changes] = runSql(db, sql);
    out.result = grid(result);
    out.changes = changes;
    if (ch.check) {
      [result] = runSql(db, ch.check);
      out.after = grid(result);
    }
    //show the changed state of the tables this attempt touched, so the sheet tabs reflect it
    if (changes) for (const name of tablesUsed(sql)) out.modified[name] = dumpTable(db, name);
  } catch (e) {
    if (!(e instanceof QueryError)) throw e;
    return { ...out, status: "error", message: e.message, tip: errorTip(e.message) };
  } finally {
    db.close();
  }
  const [correct, feedback] = compare(expected(index), result, ch.ordered);
  return correct ? { ...out, status: "correct" } : { ...out, status: "wrong", message: feedback };
}

const ops = {
  async init({ dbUrl, challenges: list }) {
    SQL = await initSqlJs({ locateFile: (f) => SQLJS + f });
    const res = await fetch(dbUrl);
    if (!res.ok) throw new Error(`couldn't download the database (${res.status})`);
    pristine = new Uint8Array(await res.arrayBuffer());
    challenges = list;
    const db = fresh();
    tableNames = db.exec("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")[0].values.map((r) => r[0]);
    db.close();
    return true;
  },
  table: ({ name }) => {
    if (!tableNames.includes(name)) throw new Error(`no table named ${name}`);
    const db = fresh();
    try { return dumpTable(db, name); } finally { db.close(); }
  },
  expected: ({ index }) => grid(expected(index)),
  run,
};

self.onmessage = async ({ data: { id, op, args } }) => {
  try {
    postMessage({ id, value: await ops[op](args) });
  } catch (e) {
    postMessage({ id, error: e.message || String(e) });
  }
};
