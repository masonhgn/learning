# sqlquest

A terminal SQL trainer backed by a real SQLite database (a small online store: customers, orders, products, employees). Each challenge asks for a specific result. Your query runs against the data, and the next challenge unlocks only when your output matches.

```
./sqlquest.py
```

It runs through [uv](https://docs.astral.sh/uv/), which installs its two UI libraries (rich and prompt_toolkit) automatically on first run. Without uv: `pip install rich prompt_toolkit` and `python3 sqlquest.py`. The database (`sqlquest.db`) is built on first run, and your progress is saved in `progress.json`. Quit any time with Ctrl-C, Ctrl-D or `quit`: progress is always saved.

The prompt highlights SQL as you type, Tab completes table names, column names and keywords, and Enter runs the query once it ends with `;` (otherwise it starts a new line).

## How it works

- 78 challenges across 10 levels, from `SELECT *` to window functions, data changes and multi-step boss problems. Each level starts with a short lesson.
- Your query is checked by comparing its result to a reference solution's result, so any correct query passes. Column names and aliases are not checked. Column order is, and so is row order when the challenge asks for sorting.
- Every attempt runs on a fresh in-memory copy of the data, so `DELETE FROM customers;` can't break anything. Queries that take longer than 5 seconds are stopped.
- Wrong answers cost nothing and still show their output, so exploratory queries work as normal attempts.

## Commands

`.hint` `.expected` `.solution` `.lesson` `.prompt` `.tables` `.schema [table]` `.list` `.goto N` `.clear` `.reset` `.help` `.quit`

## Other entry points

- `./sqlquest.py --rebuild` regenerates the database
- `./sqlquest.py --selftest` runs every reference solution through the checker
- `sqlite3 sqlquest.db` opens the same data in the plain sqlite shell or any GUI (DB Browser for SQLite, TablePlus) for free exploration

Challenges live in `challenges.py`, checking logic in `engine.py`, and the data generator in `dataset.py`. To add a challenge, append a dict with a prompt and a solution.

## Web version

```
pip install flask
python app.py
```

Then open http://localhost:5000. It uses the same challenges, checker and `progress.json` as the terminal version, so you can switch between them. The page has the challenge list on the left, a SQL editor (Ctrl+Enter runs, Ctrl+Space autocompletes), and a spreadsheet-style grid with sheet tabs along the bottom: `Result`, the tables the current challenge uses, and `+` to open any other table. Click a column header to sort, click a cell to see its full value in the formula bar, double-click a cell to paste its value into the editor, and use "Filter rows…" to search the active sheet. For challenges that change data, the tables your statements touched show their changed state (marked •, changed rows highlighted). Unsent query drafts are kept per challenge in your browser.
