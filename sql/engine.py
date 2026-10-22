"""database sandbox and answer checking for sqlquest, no ui code lives here"""

import itertools
import os
import sqlite3
import time

from dataset import build_database

QUERY_TIMEOUT = 5.0


class QueryError(Exception):
    pass


class Sandbox:
    """keeps a pristine copy of the database in memory and hands out fresh clones"""

    def __init__(self, path):
        if not os.path.exists(path):
            build_database(path)
        disk = sqlite3.connect(path)
        #check_same_thread off so the web app's request threads can share it (behind a lock)
        self.master = sqlite3.connect(":memory:", check_same_thread=False)
        disk.backup(self.master)
        disk.close()

    def fresh(self):
        conn = sqlite3.connect(":memory:", isolation_level=None)
        self.master.backup(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        deadline = time.monotonic() + QUERY_TIMEOUT
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
        return conn

    def query(self, sql, params=()):
        return self.master.execute(sql, params).fetchall()

    def tables(self):
        return [r[0] for r in self.query("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]

    def columns(self, table):
        """returns (name, type, notes) for each column of a table"""
        fks = {r[3]: f"-> {r[2]}.{r[4]}" for r in self.query(f'PRAGMA foreign_key_list("{table}")')}
        out = []
        for _, name, col_type, notnull, _, pk in self.query(f'PRAGMA table_info("{table}")'):
            notes = []
            if pk:
                notes.append("primary key")
            if name in fks:
                notes.append(fks[name])
            if not notnull and not pk:
                notes.append("nullable")
            out.append((name, col_type, ", ".join(notes)))
        return out


def split_statements(sql):
    statements, buf = [], ""
    for ch in sql:
        buf += ch
        if ch == ";" and sqlite3.complete_statement(buf):
            if buf.strip(" \t\n;"):
                statements.append(buf.strip())
            buf = ""
    if buf.strip(" \t\n;"):
        statements.append(buf.strip())
    return statements


def run_sql(conn, sql):
    """runs one or more statements and returns (result, changes) where result is (columns, rows) of the last result set"""
    result = None
    before = conn.total_changes
    for statement in split_statements(sql):
        try:
            cur = conn.execute(statement)
            if cur.description:
                result = ([d[0] for d in cur.description], cur.fetchall())
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise QueryError(f"query took longer than {QUERY_TIMEOUT:.0f}s and was stopped")
            raise QueryError(str(exc))
        except (sqlite3.DatabaseError, sqlite3.Warning, ValueError) as exc:
            raise QueryError(str(exc))
    return result, conn.total_changes - before


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def sort_key(row):
    key = []
    for v in row:
        if v is None:
            key.append((0, 0))
        elif is_number(v):
            key.append((1, round(float(v), 2)))
        elif isinstance(v, str):
            key.append((2, v))
        else:
            key.append((3, repr(v)))
    return key


def cells_match(expected, actual):
    if is_number(expected) and is_number(actual):
        return abs(expected - actual) <= max(0.011, abs(expected) * 1e-4)
    return expected == actual


def rows_match(expected, actual):
    return all(
        len(e) == len(a) and all(cells_match(x, y) for x, y in zip(e, a))
        for e, a in zip(expected, actual)
    )


def same_rows_any_order(expected, actual):
    return rows_match(sorted(expected, key=sort_key), sorted(actual, key=sort_key))


def compare(expected, actual, ordered):
    """returns (correct, feedback)"""
    if actual is None:
        return False, "Your SQL ran but returned no result set. Did you write a SELECT?"
    ecols, erows = expected
    acols, arows = actual
    if len(acols) != len(ecols):
        return False, f"Expected {len(ecols)} column(s), your query returned {len(acols)}."
    if len(arows) != len(erows):
        return False, f"Expected {len(erows)} row(s), your query returned {len(arows)}."
    if ordered and rows_match(erows, arows):
        return True, ""
    if same_rows_any_order(erows, arows):
        if not ordered:
            return True, ""
        return False, "Right rows, wrong order. Check your ORDER BY and tie breakers."
    if 1 < len(ecols) <= 6:
        for perm in itertools.permutations(range(len(acols))):
            shuffled = [tuple(r[i] for i in perm) for r in arows]
            if same_rows_any_order(erows, shuffled):
                return False, "Right data, but the columns are in a different order than asked."
    return False, "Right shape (rows and columns), but some values differ."


def error_tip(message):
    """a beginner friendly nudge for common sqlite errors"""
    msg = message.lower()
    if "no such column" in msg:
        return "Check the spelling, or run .schema to see each table's columns."
    if "no such table" in msg:
        return "Run .tables to see the table names."
    if "ambiguous column" in msg:
        return "Two joined tables share that column name. Prefix it with a table alias, like c.id."
    if "syntax error" in msg:
        return "Look just before the quoted word: a missing comma, a stray comma, or a misspelled keyword."
    if "incomplete input" in msg:
        return "Something is unclosed: a quote, a parenthesis, or a CASE without END."
    if "foreign key" in msg:
        return "Another table still points at the rows you are changing. Deal with those first."
    if "misuse of aggregate" in msg:
        return "Aggregates like COUNT or SUM can't go in WHERE. Use HAVING, or a subquery."
    if "longer than" in msg:
        return "Usually a JOIN without an ON clause, which pairs every row with every other row."
    return ""
