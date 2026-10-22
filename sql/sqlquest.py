#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13", "prompt_toolkit>=3"]
# ///
"""sqlquest: a progressive sql challenge sandbox backed by a real sqlite database"""

import json
import os
import re
import sqlite3
import sys

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.lexers import PygmentsLexer
    from prompt_toolkit.shortcuts import confirm
    from prompt_toolkit.styles import Style, merge_styles, style_from_pygments_cls
    from pygments.lexers.sql import SqlLexer
    from pygments.styles import get_style_by_name
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.exit(
        "sqlquest needs the rich and prompt_toolkit packages.\n"
        "Run it with ./sqlquest.py (uv installs them automatically),\n"
        "or: pip install rich prompt_toolkit"
    )

from challenges import CHALLENGES, LEVELS
from engine import QueryError, Sandbox, compare, error_tip, is_number, run_sql

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "sqlquest.db")
PROGRESS_PATH = os.environ.get("SQLQUEST_PROGRESS", os.path.join(HERE, "progress.json"))
HISTORY_PATH = os.path.join(HERE, ".sqlquest_history")
MAX_ROWS_SHOWN = 15
CODE_THEME = "monokai"

LEVEL_COLORS = [
    "deep_sky_blue1", "medium_purple1", "orchid", "gold1", "dark_orange",
    "spring_green2", "turquoise2", "hot_pink", "light_coral", "red1",
]

KEYWORDS = """SELECT FROM WHERE AND OR NOT IN IS NULL LIKE BETWEEN ORDER BY GROUP HAVING
LIMIT OFFSET DISTINCT AS JOIN LEFT INNER ON CASE WHEN THEN ELSE END WITH OVER PARTITION
INSERT INTO VALUES UPDATE SET DELETE EXISTS UNION ALL INTERSECT EXCEPT DESC ASC CAST INTEGER""".split()
FUNCTIONS = """COUNT SUM AVG MIN MAX ROUND COALESCE ROW_NUMBER RANK DENSE_RANK LAG LEAD
strftime julianday substr instr upper lower length trim replace""".split()

COMMANDS = [
    (".hint", "next hint"),
    (".expected", "peek at the target output"),
    (".solution", "reveal a solution"),
    (".lesson", "re-read this level's lesson"),
    (".prompt", "show the challenge again"),
    (".tables", "list tables"),
    (".schema", "columns of a table, e.g. .schema orders"),
    (".list", "progress and all challenges"),
    (".goto", "jump to a challenge, e.g. .goto 3"),
    (".clear", "clear the screen"),
    (".reset", "wipe progress"),
    (".help", "show commands"),
    (".quit", "save and leave"),
]

console = Console(highlight=False)


def width():
    return min(console.width, 96)


def badge(text, style):
    return Text(f" {text} ", style=style)


def sql_block(code):
    return Syntax(code.strip(), "sql", theme=CODE_THEME, background_color="default", word_wrap=True)


def fmt(v):
    if v is None:
        return Text("NULL", style="dim italic")
    if isinstance(v, float):
        text = f"{v:.4f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.1f}"
        return Text(text, style="cyan")
    if is_number(v):
        return Text(str(v), style="cyan")
    return Text(str(v).replace("\n", " "))


def result_table(cols, rows, title=None, limit=MAX_ROWS_SHOWN):
    shown = rows[:limit]
    table = Table(
        box=box.ROUNDED, border_style="grey35", header_style="bold",
        title=title, title_justify="left", title_style="dim italic",
        caption_justify="left", caption_style="dim",
    )
    for i, col in enumerate(cols):
        numeric = bool(shown) and all(is_number(r[i]) or r[i] is None for r in shown)
        table.add_column(col, justify="right" if numeric else "left", max_width=36, overflow="ellipsis", no_wrap=True)
    for row in shown:
        table.add_row(*(fmt(v) for v in row))
    count = f"{len(rows)} row{'' if len(rows) == 1 else 's'}"
    table.caption = f"showing {limit} of {count}" if len(rows) > limit else count
    return Padding(table, (0, 0, 0, 1))


def progress_line(done, total, bar_width=30):
    grid = Table.grid(padding=(0, 2))
    grid.add_column()
    grid.add_column()
    grid.add_row(
        ProgressBar(total=total, completed=done, width=bar_width, complete_style="bright_green", finished_style="bright_green"),
        Text(f"{done}/{total} solved", style="dim"),
    )
    return grid


def emphasize(text, column_names):
    """highlights quoted values, keywords in caps and column names inside prose"""
    out = Text(text)
    out.highlight_regex(r"'[^']*'", "yellow")
    out.highlight_regex(r"\b[A-Z][A-Z_]{1,}(?: [A-Z]{2,})*\b", "bold")
    out.highlight_regex(r"(?<![\w.])\.[a-z]+\b", "bold cyan")
    if column_names:
        pattern = r"\b(?:" + "|".join(sorted(map(re.escape, column_names), key=len, reverse=True)) + r")\b"
        out.highlight_regex(pattern, "bold bright_white")
    return out


def render_lesson(text):
    """turns lesson text into prose paragraphs and highlighted sql blocks"""
    blocks, prose, code = [], [], []

    def flush():
        if prose:
            blocks.append(emphasize(" ".join(prose), ()))
            prose.clear()
        if code:
            blocks.append(Padding(sql_block("\n".join(code)), (0, 0, 0, 2)))
            code.clear()

    for line in text.splitlines():
        if line.startswith("  "):
            if prose:
                flush()
            code.append(line[2:])
        elif not line.strip():
            flush()
        else:
            if code:
                flush()
            prose.append(line.strip())
    flush()
    spaced = []
    for block in blocks:
        if spaced:
            spaced.append(Text(""))
        spaced.append(block)
    return Group(*spaced)


class SqlCompleter(Completer):
    def __init__(self, sandbox):
        owners = {}
        tables = sandbox.tables()
        for table in tables:
            for name, _, _ in sandbox.columns(table):
                owners.setdefault(name, []).append(table)
        self.words = [(t, "table") for t in tables]
        self.words += [(c, "column in " + ", ".join(ts)) for c, ts in sorted(owners.items())]
        self.words += [(k, "keyword") for k in KEYWORDS]
        self.words += [(f, "function") for f in FUNCTIONS]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        stripped = text.lstrip()
        if stripped.startswith(".") and " " not in stripped and "\n" not in stripped:
            for cmd, desc in COMMANDS:
                if cmd.startswith(stripped) and cmd != stripped:
                    yield Completion(cmd, start_position=-len(stripped), display_meta=desc)
            return
        match = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", text)
        if not match:
            return
        word = match.group(0)
        if len(word) < 2 and not complete_event.completion_requested:
            return
        for candidate, meta in self.words:
            if candidate.lower().startswith(word.lower()) and candidate.lower() != word.lower():
                if meta in ("keyword", "function") and word.islower():
                    candidate = candidate.lower()
                yield Completion(candidate, start_position=-len(word), display_meta=meta)


class Game:
    def __init__(self):
        self.sandbox = Sandbox(DB_PATH)
        self.expected_cache = {}
        self.solved = set()
        self.index = 0
        self.hints_shown = 0
        self.attempts = 0
        self.column_names = {c for t in self.sandbox.tables() for c, _, _ in self.sandbox.columns(t)}
        self.load_progress()

    #progress

    def load_progress(self):
        try:
            with open(PROGRESS_PATH) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        keys = {c["key"] for c in CHALLENGES}
        self.solved = set(data.get("solved", [])) & keys
        self.index = min(self.first_unsolved(), len(CHALLENGES) - 1)
        current = data.get("current")
        for i, ch in enumerate(CHALLENGES):
            if ch["key"] == current and self.unlocked(i):
                self.index = i

    def save_progress(self):
        data = {"solved": sorted(self.solved), "current": CHALLENGES[self.index]["key"]}
        with open(PROGRESS_PATH, "w") as f:
            json.dump(data, f, indent=2)

    def first_unsolved(self):
        for i, ch in enumerate(CHALLENGES):
            if ch["key"] not in self.solved:
                return i
        return len(CHALLENGES)

    def unlocked(self, i):
        return True

    def level_challenges(self, level):
        return [ch for ch in CHALLENGES if ch["level"] == level]

    @property
    def challenge(self):
        return CHALLENGES[self.index]

    #presentation

    def show_banner(self):
        title = Text("S Q L Q U E S T", style="bold bright_white")
        tagline = Text("learn SQL by doing, one unlock at a time", style="dim")
        keys = Text.assemble(
            (";", "bold cyan"), (" + Enter runs   ", "dim"),
            ("Tab", "bold cyan"), (" completes   ", "dim"),
            (".help", "bold cyan"), (" commands   ", "dim"),
            ("Ctrl-C", "bold cyan"), (" saves + quits", "dim"),
        )
        body = Group(title, tagline, Text(""), progress_line(len(self.solved), len(CHALLENGES)), Text(""), keys)
        console.print(Panel(body, box=box.HEAVY, border_style="bright_green", padding=(1, 3), width=width()))

    def show_lesson(self, level):
        color = LEVEL_COLORS[level]
        title = Text.assemble(badge(f"LEVEL {level + 1}", f"bold black on {color}"), " ", (LEVELS[level]["title"], f"bold {color}"))
        console.print()
        console.print(Panel(
            render_lesson(LEVELS[level]["lesson"]),
            title=title, title_align="left",
            subtitle=Text(f" lesson {level + 1} of {len(LEVELS)} ", style="dim"), subtitle_align="right",
            border_style=color, box=box.ROUNDED, padding=(1, 2), width=width(),
        ))

    def show_prompt(self):
        ch = self.challenge
        color = LEVEL_COLORS[ch["level"]]
        title = Text.assemble(badge(f"{self.index + 1}/{len(CHALLENGES)}", f"bold black on {color}"), " ", (ch["title"], "bold"))
        if ch["key"] in self.solved:
            title.append("  ")
            title.append_text(badge("solved", "bold black on bright_green"))
        body = [emphasize(ch["prompt"], self.column_names)]
        if ch.get("check"):
            body += [Text(""), Text("this one changes data, and every attempt runs on a fresh copy", style="dim italic")]
        subtitle = Text(f" level {ch['level'] + 1} · {LEVELS[ch['level']]['title']} ", style="dim")
        console.print()
        console.print(Panel(
            Group(*body), title=title, title_align="left", subtitle=subtitle, subtitle_align="right",
            border_style=color, box=box.ROUNDED, padding=(1, 2), width=width(),
        ))
        console.print()

    def enter(self, index, with_lesson=None):
        previous_level = self.challenge["level"]
        self.index = index
        self.hints_shown = 0
        self.attempts = 0
        level = self.challenge["level"]
        if with_lesson or (with_lesson is None and level != previous_level):
            self.show_lesson(level)
        self.show_prompt()
        self.save_progress()

    def verdict(self, label, style, message, tip=""):
        line = Text.assemble(" ", badge(label, style), "  ", message)
        console.print()
        console.print(line)
        if tip:
            console.print(Padding(Text(tip, style="dim"), (0, 0, 0, 3)))
        console.print()

    #checking

    def expected(self, ch):
        if ch["key"] not in self.expected_cache:
            conn = self.sandbox.fresh()
            result, _ = run_sql(conn, ch["solution"])
            if ch.get("check"):
                result, _ = run_sql(conn, ch["check"])
            conn.close()
            self.expected_cache[ch["key"]] = result
        return self.expected_cache[ch["key"]]

    def attempt(self, sql):
        ch = self.challenge
        self.attempts += 1
        conn = self.sandbox.fresh()
        try:
            result, changes = run_sql(conn, sql)
            if ch.get("check"):
                if result:
                    console.print(result_table(*result))
                console.print(Text(f" {changes} row{'' if changes == 1 else 's'} changed", style="dim"))
                result, _ = run_sql(conn, ch["check"])
                console.print(result_table(*result, title="table state after your statements", limit=8))
            elif result:
                console.print(result_table(*result))
            elif changes:
                console.print(Text(f" {changes} row(s) changed on a throwaway copy", style="dim"))
        except QueryError as exc:
            self.verdict("✗ ERROR", "bold bright_white on red", Text(str(exc), style="red"), error_tip(str(exc)))
            return
        finally:
            conn.close()

        correct, feedback = compare(self.expected(ch), result, ch.get("ordered", False))
        if not correct:
            left = len(ch["hints"]) - self.hints_shown
            tip = f"{left} hint{'' if left == 1 else 's'} left with .hint, or .expected to see the target" if left else ".expected shows the target output, .solution reveals an answer"
            self.verdict("✗ NOT QUITE", "bold black on yellow", Text(feedback), tip)
            return
        self.succeed(ch)

    def succeed(self, ch):
        first_time = ch["key"] not in self.solved
        self.solved.add(ch["key"])
        self.save_progress()
        tries = "first try" if self.attempts == 1 else f"{self.attempts} attempts"
        console.print()
        console.print(Text.assemble(" ", badge("✓ CORRECT!", "bold black on bright_green"), "  ", (tries, "bright_green")))
        console.print()
        console.print(Panel(
            sql_block(ch["solution"]), title=Text(" one way to write it ", style="dim"), title_align="left",
            border_style="grey35", box=box.ROUNDED, padding=(0, 2), width=width(),
        ))

        level = ch["level"]
        level_done = all(c["key"] in self.solved for c in self.level_challenges(level))
        is_last = self.index + 1 >= len(CHALLENGES)
        if first_time and level_done:
            self.celebrate(level)
        if not is_last:
            console.print()
            console.print(Rule(style="grey23"))
            self.enter(self.index + 1)

    def celebrate(self, level):
        done_all = len(self.solved) == len(CHALLENGES)
        if done_all:
            headline = f"ALL {len(CHALLENGES)} CHALLENGES CLEARED"
            sub = "You are officially dangerous with SQL. Next: Postgres, EXPLAIN query plans, and indexes."
        else:
            headline = f"LEVEL {level + 1} COMPLETE"
            sub = f"Up next: {LEVELS[level + 1]['title']}"
        body = Group(
            Align.center(Text(headline, style="bold bright_green")),
            Align.center(Text(sub, style="dim")),
            Text(""),
            Align.center(progress_line(len(self.solved), len(CHALLENGES))),
        )
        console.print()
        console.print(Panel(body, box=box.DOUBLE, border_style="bright_green", padding=(1, 2), width=width()))

    #commands

    def cmd_hint(self, _):
        hints = self.challenge["hints"]
        if self.hints_shown >= len(hints):
            console.print(Text(" No more hints. Try .expected or .solution.", style="dim"))
            return
        self.hints_shown += 1
        console.print(Panel(
            emphasize(hints[self.hints_shown - 1], self.column_names),
            title=Text(f" hint {self.hints_shown} of {len(hints)} ", style="bold yellow"), title_align="left",
            border_style="yellow", box=box.ROUNDED, padding=(0, 2), width=width(),
        ))

    def cmd_expected(self, _):
        cols, rows = self.expected(self.challenge)
        console.print(result_table(cols, rows, title="expected output", limit=10))

    def cmd_solution(self, _):
        try:
            if not confirm(" Reveal the solution? You will still need to type it in."):
                return
        except (KeyboardInterrupt, EOFError):
            return
        console.print(Panel(
            sql_block(self.challenge["solution"]), title=Text(" solution ", style="bold magenta"), title_align="left",
            subtitle=Text(" type it in yourself to unlock the next one ", style="dim"), subtitle_align="right",
            border_style="magenta", box=box.ROUNDED, padding=(1, 2), width=width(),
        ))

    def cmd_lesson(self, _):
        self.show_lesson(self.challenge["level"])

    def cmd_prompt(self, _):
        self.show_prompt()

    def cmd_clear(self, _):
        console.clear()
        self.show_prompt()

    def cmd_tables(self, _):
        table = Table(box=box.ROUNDED, border_style="grey35", header_style="bold")
        table.add_column("table", style="bold")
        table.add_column("rows", justify="right", style="cyan")
        table.add_column("columns", style="dim", overflow="fold")
        for name in self.sandbox.tables():
            count = self.sandbox.query(f'SELECT COUNT(*) FROM "{name}"')[0][0]
            cols = ", ".join(c for c, _, _ in self.sandbox.columns(name))
            table.add_row(name, str(count), cols)
        console.print(Padding(table, (0, 0, 0, 1)))
        console.print(Text(" .schema <table> shows column types and sample rows", style="dim"))

    def schema_panel(self, name, sample=False):
        grid = Table.grid(padding=(0, 3))
        grid.add_column(style="bold")
        grid.add_column(style="dim")
        grid.add_column(style="cyan")
        for col, col_type, notes in self.sandbox.columns(name):
            grid.add_row(col, col_type, notes)
        body = [grid]
        if sample:
            cur = self.sandbox.master.execute(f'SELECT * FROM "{name}" LIMIT 3')
            body += [Text(""), result_table([d[0] for d in cur.description], cur.fetchall(), title="sample rows")]
        return Panel(Group(*body), title=Text(f" {name} ", style="bold"), title_align="left",
                     border_style="grey50", box=box.ROUNDED, padding=(0, 2), width=width())

    def cmd_schema(self, arg):
        tables = self.sandbox.tables()
        if arg:
            if arg not in tables:
                console.print(Text(f" No table named {arg!r}. Tables: {', '.join(tables)}", style="red"))
                return
            console.print(self.schema_panel(arg, sample=True))
            return
        for name in tables:
            console.print(self.schema_panel(name))

    def cmd_list(self, _):
        rows = [progress_line(len(self.solved), len(CHALLENGES)), Text("")]
        for level, info in enumerate(LEVELS):
            color = LEVEL_COLORS[level]
            members = [(i, ch) for i, ch in enumerate(CHALLENGES) if ch["level"] == level]
            done = sum(ch["key"] in self.solved for _, ch in members)
            open_level = self.unlocked(members[0][0])
            dots = Text("●" * done, style="bright_green") + Text("○" * (len(members) - done), style="grey42")
            header = Text.assemble(
                badge(f"{level + 1:>2}", f"bold black on {color}" if open_level else "black on grey35"), " ",
                (info["title"], "bold" if open_level else "grey50"), "  ", dots,
            )
            rows.append(header)
            if not open_level:
                continue
            for i, ch in members:
                if i == self.index:
                    mark, style = "▸", "bold cyan"
                elif ch["key"] in self.solved:
                    mark, style = "✓", "bright_green"
                elif self.unlocked(i):
                    mark, style = "○", "yellow"
                else:
                    mark, style = "·", "grey42"
                label = ch["title"] if self.unlocked(i) else "locked"
                rows.append(Text.assemble(("      " + mark, style), (f"  {i + 1:>2}  ", "dim"), (label, style if i == self.index or not self.unlocked(i) else "")))
        console.print(Panel(Group(*rows), title=Text(" progress ", style="bold"), title_align="left",
                            border_style="grey50", box=box.ROUNDED, padding=(1, 2), width=width()))
        console.print(Text(" .goto N jumps to any unlocked challenge", style="dim"))

    def cmd_goto(self, arg):
        try:
            target = int(arg) - 1
        except ValueError:
            console.print(Text(" usage: .goto N", style="red"))
            return
        if not 0 <= target < len(CHALLENGES):
            console.print(Text(f" Pick a number from 1 to {len(CHALLENGES)}.", style="red"))
        elif not self.unlocked(target):
            console.print(Text(f" Challenge {target + 1} is locked. Solve challenge {self.first_unsolved() + 1} first.", style="red"))
        else:
            self.enter(target, with_lesson=CHALLENGES[target]["level"] != self.challenge["level"])

    def cmd_reset(self, _):
        try:
            if not confirm(" Erase all progress?"):
                return
        except (KeyboardInterrupt, EOFError):
            return
        self.solved.clear()
        self.enter(0, with_lesson=True)

    def cmd_help(self, _):
        table = Table.grid(padding=(0, 3))
        table.add_column(style="bold cyan")
        table.add_column()
        for cmd, desc in COMMANDS:
            table.add_row(cmd, desc)
        intro = Text("Type SQL ending in ; and press Enter. Wrong answers cost nothing, so explore freely: "
                     "every query shows its output, then a verdict. Tab completes table names, column names and keywords.", style="dim")
        console.print(Panel(Group(intro, Text(""), table), title=Text(" help ", style="bold"), title_align="left",
                            border_style="grey50", box=box.ROUNDED, padding=(1, 2), width=width()))

    HANDLERS = {
        "hint": cmd_hint, "expected": cmd_expected, "solution": cmd_solution,
        "lesson": cmd_lesson, "prompt": cmd_prompt, "clear": cmd_clear, "tables": cmd_tables,
        "schema": cmd_schema, "list": cmd_list, "goto": cmd_goto,
        "reset": cmd_reset, "help": cmd_help,
    }

    #input

    def toolbar(self):
        ch = self.challenge
        hints = f"{len(ch['hints']) - self.hints_shown} hints left"
        return HTML(
            f" <key>{self.index + 1}/{len(CHALLENGES)}</key> {escape_html(ch['title'])}"
            f"  <sep>|</sep>  {hints}"
            f"  <sep>|</sep>  <key>;</key> then Enter runs"
            f"  <sep>|</sep>  <key>.help</key>"
            f"  <sep>|</sep>  <key>Ctrl-C</key> quit "
        )

    def make_session(self):
        bindings = KeyBindings()

        @bindings.add("enter")
        def _(event):
            buf = event.current_buffer
            state = buf.complete_state
            if state and state.current_completion is not None:
                buf.apply_completion(state.current_completion)
                return
            text = buf.text.strip()
            if not text or text.startswith(".") or text.lower() in ("quit", "exit") or sqlite3.complete_statement(buf.text):
                buf.validate_and_handle()
            else:
                buf.insert_text("\n")

        style = merge_styles([
            style_from_pygments_cls(get_style_by_name(CODE_THEME)),
            Style.from_dict({
                "prompt": "#5fd75f bold",
                "continuation": "#585858",
                "bottom-toolbar": "noreverse bg:#262626 #9e9e9e",
                "bottom-toolbar key": "#5fd7ff bold",
                "bottom-toolbar sep": "#4e4e4e",
                "completion-menu.completion": "bg:#303030 #d0d0d0",
                "completion-menu.completion.current": "bg:#5fd75f #000000 bold",
                "completion-menu.meta.completion": "bg:#262626 #808080",
                "completion-menu.meta.completion.current": "bg:#5fd75f #000000",
                "auto-suggestion": "#585858",
            }),
        ])
        return PromptSession(
            message=[("class:prompt", "sql ❯ ")],
            prompt_continuation=lambda *_: [("class:continuation", "    │ ")],
            multiline=True,
            key_bindings=bindings,
            lexer=PygmentsLexer(SqlLexer),
            completer=SqlCompleter(self.sandbox),
            complete_while_typing=True,
            auto_suggest=AutoSuggestFromHistory(),
            history=FileHistory(HISTORY_PATH),
            bottom_toolbar=self.toolbar,
            style=style,
            include_default_pygments_style=False,
        )

    #main loop

    def run(self):
        self.show_banner()
        level = self.challenge["level"]
        started_level = any(c["key"] in self.solved for c in self.level_challenges(level))
        if started_level:
            console.print(Text(f" Welcome back. You are on level {level + 1}, {LEVELS[level]['title']}. .lesson re-reads it.", style="dim"))
        else:
            self.show_lesson(level)
        self.show_prompt()
        try:
            self.loop(self.make_session())
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self.save_progress()
            console.print()
            console.print(Text.assemble(" ", badge("saved", "bold black on bright_green"), "  ",
                                        (f"{len(self.solved)}/{len(CHALLENGES)} solved. See you next time.", "dim")))
            console.print()

    def loop(self, session):
        while True:
            text = session.prompt().strip()
            if text.rstrip(";").strip().lower() in ("quit", "exit", ".quit", ".exit", ".q"):
                return
            if text.startswith("."):
                name, _, arg = text[1:].partition(" ")
                handler = self.HANDLERS.get(name)
                if handler is None:
                    console.print(Text(f" Unknown command .{name}. Try .help", style="red"))
                else:
                    console.print()
                    handler(self, arg.strip())
                    console.print()
                continue
            self.attempt(text)


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def selftest():
    """runs every solution through the checker to make sure the challenge set is sound"""
    game = Game.__new__(Game)
    game.sandbox, game.expected_cache = Sandbox(DB_PATH), {}
    failures = 0
    for i, ch in enumerate(CHALLENGES, start=1):
        try:
            expected = game.expected(ch)
        except QueryError as exc:
            console.print(f"[red]{i:>2} {ch['key']}: solution error: {exc}[/red]")
            failures += 1
            continue
        rows = len(expected[1]) if expected else 0
        failures += not rows
        flag = "" if rows else "  [red]EMPTY RESULT[/red]"
        console.print(f"{i:>2} {ch['key']:<22} {rows:>4} rows{flag}")
    console.print("[green]all good[/green]" if not failures else f"[red]{failures} problem(s)[/red]")
    return failures


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--rebuild" in sys.argv and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    Game().run()
