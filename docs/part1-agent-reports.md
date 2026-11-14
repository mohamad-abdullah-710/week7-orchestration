# Part I — Concurrent agent reports

Two Claude Code subagents (Claude Opus 5.5) were launched **in the same message**, each in
its own git worktree. Orchestrator: Claude Code, supervised by Mohamad.

| | Agent A | Agent B |
|---|---|---|
| Task | 2 — Tag filter | 4 — Favorites |
| Worktree / branch | `../recipe-task-a` / `task-a` | `../recipe-task-b` / `task-b` |
| Start → end (UTC) | 21:19:32 → 21:20:20 | 21:19:32 → 21:20:18 |
| Commit | `6a908b6 Add tag filter to GET /recipes` | `f58b96b Add favorite flag and toggle endpoint` |
| Diff | `main.py`, `test_main.py`: +52 / −2 | `main.py`, `test_main.py`: +84 / −2 |
| pytest (own worktree) | `7 passed` | `7 passed` |
| ruff | `All checks passed!` | `All checks passed!` |
| black `--check` | fails, only on starter lines (verified by stashing) | fails, only on starter lines (verified by stashing) |

Worktree setup (orchestrator, 21:19:05 UTC):
```bash
git worktree add ../recipe-task-a -b task-a
git worktree add ../recipe-task-b -b task-b
# 3 passed in each worktree before the agents started
```

Rules given to both agents (autonomy level): edit and run tests **only inside your own
worktree**; commit on your own branch; **no** branch switching, push, merge, rebase, PRs
or package installs. After both finished, the orchestrator checked: each branch has exactly
one new commit, tests pass in each worktree, `master` unchanged and clean.

---

## Agent A — Tag filter (summary of its report)
- `list_recipes(tag: str | None = None)`: same query; if a non-empty tag is given, filters
  in Python after decoding the JSON tags. No schema change.
- Decisions: **case-insensitive**, surrounding whitespace stripped; `tag=` (empty) = no
  filter; unknown tag → `200 []`; exact match only (`break` ≠ `breakfast`).
- Tests (4): only-matching, no-match → `[]`, no param / empty param → all,
  case-insensitive. Uses unique tags (`uuid`) so leftover rows in `recipes.db` can't break them.
- Predicted collisions: edits `list_recipes`; appends tests at end of `test_main.py`;
  changes test imports (`import uuid`); merged tests will share one `recipes.db`.

## Agent B — Favorites (summary of its report)
- `init_db()`: `favorite INTEGER NOT NULL DEFAULT 0` in `CREATE TABLE`, plus a migration
  (`PRAGMA table_info` → `ALTER TABLE ... ADD COLUMN` if missing) for old databases.
- `_row_to_recipe` returns `"favorite": bool(...)`; `create_recipe` returns `favorite: False`.
- `POST /recipes/{id}/favorite`: one atomic `UPDATE ... SET favorite = 1 - favorite`;
  `rowcount == 0` → 404; returns the updated recipe.
- Tests (4): default false, toggle on/off (visible in GET and list), unknown id 404,
  migration of an old-style table in `tmp_path` (run twice to show it is safe to repeat).
- Predicted collisions: `create_recipe` return line and `_row_to_recipe`; appends endpoint
  and tests at end of both files; changes test imports (`import sqlite3`, `import main`).

---

## Merging (orchestrator)
```bash
git merge --no-ff task-a   # clean
git merge --no-ff task-b   # main.py auto-merged; CONFLICT in test_main.py
```
`main.py` merged automatically even though both agents edited it (different functions).
`test_main.py` had **2 textual conflicts**, exactly where both agents predicted:

1. Imports at the top of the file:
```
<<<<<<< HEAD
import uuid
=======
import sqlite3
>>>>>>> task-b
```
2. New tests appended at the end of the file (Agent A's tag tests vs Agent B's favorite
   tests, ~90 lines).

Resolution: keep both sides (`import sqlite3` + `import uuid`; both test blocks).
After resolving: `ruff` → `All checks passed!`, `pytest` → `11 passed`.
Extra check that git cannot do: a recipe that is favorited and then filtered by tag
(upper case) comes back with `"favorite": true`, so the two features work together.
