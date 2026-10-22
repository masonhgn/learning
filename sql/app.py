"""sqlquest web: a flask front end for the same challenges, engine and progress file as the terminal version"""

import json
import os
import re
import threading

from flask import Flask, abort, jsonify, render_template, request

from challenges import CHALLENGES, LEVELS
from engine import QueryError, Sandbox, compare, error_tip, run_sql

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "sqlquest.db")
PROGRESS_PATH = os.environ.get("SQLQUEST_PROGRESS", os.path.join(HERE, "progress.json"))
MAX_ROWS_RETURNED = 2000

app = Flask(__name__)
sandbox = Sandbox(DB_PATH)
#the master connection is shared between request threads, so every use of it goes through this lock
lock = threading.Lock()
expected_cache = {}


#progress, same format as sqlquest.py so both front ends share it

def load_progress():
    try:
        with open(PROGRESS_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    keys = {c["key"] for c in CHALLENGES}
    solved = set(data.get("solved", [])) & keys
    index = min(first_unsolved(solved), len(CHALLENGES) - 1)
    for i, ch in enumerate(CHALLENGES):
        if ch["key"] == data.get("current"):
            index = i
    return solved, index


def save_progress(solved, index):
    with open(PROGRESS_PATH, "w") as f:
        json.dump({"solved": sorted(solved), "current": CHALLENGES[index]["key"]}, f, indent=2)


def first_unsolved(solved):
    for i, ch in enumerate(CHALLENGES):
        if ch["key"] not in solved:
            return i
    return len(CHALLENGES)


#helpers

def fresh():
    with lock:
        return sandbox.fresh()


def table_names():
    with lock:
        return sandbox.tables()


def tables_used(sql):
    """tables named in a piece of sql, in order of first appearance"""
    found = []
    for name in table_names():
        m = re.search(rf"\b{re.escape(name)}\b", sql, re.IGNORECASE)
        if m:
            found.append((m.start(), name))
    return [name for _, name in sorted(found)]


def challenge_tables(ch):
    return tables_used(ch["solution"] + "\n" + ch.get("check", ""))


def expected(ch):
    if ch["key"] not in expected_cache:
        conn = fresh()
        result, _ = run_sql(conn, ch["solution"])
        if ch.get("check"):
            result, _ = run_sql(conn, ch["check"])
        conn.close()
        expected_cache[ch["key"]] = result
    return expected_cache[ch["key"]]


def grid(result):
    """(cols, rows) to json, capped so a runaway cross join can't flood the browser"""
    if result is None:
        return None
    cols, rows = result
    return {"columns": cols, "rows": [list(r) for r in rows[:MAX_ROWS_RETURNED]], "total": len(rows)}


def dump_table(conn, name):
    cur = conn.execute(f'SELECT * FROM "{name}"')
    return grid(([d[0] for d in cur.description], cur.fetchall()))


def get_challenge(index):
    if not 0 <= index < len(CHALLENGES):
        abort(404)
    return CHALLENGES[index]


def progress_json(solved, index):
    return {"solved": sorted(solved), "current": index, "first_unsolved": first_unsolved(solved)}


#routes

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    solved, current = load_progress()
    with lock:
        schema = {t: sandbox.columns(t) for t in sandbox.tables()}
    challenges = [{
        "key": ch["key"],
        "level": ch["level"],
        "title": ch["title"],
        "prompt": ch["prompt"],
        "ordered": ch.get("ordered", False),
        "modifies": bool(ch.get("check")),
        "hints": ch["hints"],
        "tables": challenge_tables(ch),
    } for ch in CHALLENGES]
    return jsonify({
        "levels": LEVELS,
        "challenges": challenges,
        "schema": {t: [{"name": n, "type": ty, "notes": no} for n, ty, no in cols] for t, cols in schema.items()},
        "progress": progress_json(solved, current),
    })


@app.get("/api/table/<name>")
def table(name):
    if name not in table_names():
        abort(404)
    with lock:
        cur = sandbox.master.execute(f'SELECT * FROM "{name}"')
        return jsonify(grid(([d[0] for d in cur.description], cur.fetchall())))


@app.post("/api/goto")
def goto():
    index = int(request.json["index"])
    get_challenge(index)
    solved, _ = load_progress()
    save_progress(solved, index)
    return jsonify({"progress": progress_json(solved, index)})


@app.post("/api/run")
def run():
    index = int(request.json["index"])
    sql = request.json.get("sql", "")
    ch = get_challenge(index)
    solved, _ = load_progress()

    out = {"result": None, "after": None, "changes": 0, "modified": {}}
    conn = fresh()
    try:
        result, changes = run_sql(conn, sql)
        out["result"] = grid(result)
        out["changes"] = changes
        if ch.get("check"):
            result, _ = run_sql(conn, ch["check"])
            out["after"] = grid(result)
        if changes:
            #show the changed state of the tables this attempt touched, so the sheet tabs reflect it
            for name in tables_used(sql):
                out["modified"][name] = dump_table(conn, name)
    except QueryError as exc:
        #the tips mention terminal dot commands, point at the web equivalent instead
        tip = error_tip(str(exc)).replace("run .schema", "open Schema").replace("Run .tables", "Open Schema")
        out.update(status="error", message=str(exc), tip=tip)
        return jsonify(out)
    finally:
        conn.close()

    correct, feedback = compare(expected(ch), result, ch.get("ordered", False))
    if not correct:
        out.update(status="wrong", message=feedback)
        return jsonify(out)

    first_time = ch["key"] not in solved
    solved.add(ch["key"])
    level = ch["level"]
    level_done = all(c["key"] in solved for c in CHALLENGES if c["level"] == level)
    save_progress(solved, index)
    out.update(
        status="correct",
        solution=ch["solution"],
        level_complete=first_time and level_done,
        all_complete=len(solved) == len(CHALLENGES),
        progress=progress_json(solved, index),
    )
    return jsonify(out)


@app.get("/api/expected/<int:index>")
def expected_output(index):
    return jsonify(grid(expected(get_challenge(index))))


@app.get("/api/solution/<int:index>")
def solution(index):
    return jsonify({"solution": get_challenge(index)["solution"]})


@app.post("/api/reset")
def reset():
    save_progress(set(), 0)
    return jsonify({"progress": progress_json(set(), 0)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
