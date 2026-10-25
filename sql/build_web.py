#!/usr/bin/env python3
"""builds the data the static web version needs: web/data.json (lessons, challenges, schema) and web/sqlquest.db"""

import json
import os
import re
import shutil

from challenges import CHALLENGES, LEVELS
from engine import Sandbox

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "sqlquest.db")
WEB = os.path.join(HERE, "web")


def tables_used(sql, names):
    """tables named in a piece of sql, in order of first appearance"""
    found = []
    for name in names:
        m = re.search(rf"\b{re.escape(name)}\b", sql, re.IGNORECASE)
        if m:
            found.append((m.start(), name))
    return [name for _, name in sorted(found)]


def main():
    sandbox = Sandbox(DB_PATH)
    names = sandbox.tables()
    data = {
        "levels": LEVELS,
        "challenges": [{
            "key": ch["key"],
            "level": ch["level"],
            "title": ch["title"],
            "prompt": ch["prompt"],
            "solution": ch["solution"],
            "check": ch.get("check"),
            "ordered": ch.get("ordered", False),
            "modifies": bool(ch.get("check")),
            "hints": ch["hints"],
            "tables": tables_used(ch["solution"] + "\n" + ch.get("check", ""), names),
        } for ch in CHALLENGES],
        "schema": {t: [{"name": n, "type": ty, "notes": no} for n, ty, no in sandbox.columns(t)] for t in names},
    }
    with open(os.path.join(WEB, "data.json"), "w") as f:
        json.dump(data, f)
    shutil.copyfile(DB_PATH, os.path.join(WEB, "sqlquest.db"))
    print(f"wrote web/data.json ({len(CHALLENGES)} challenges) and web/sqlquest.db")


if __name__ == "__main__":
    main()
