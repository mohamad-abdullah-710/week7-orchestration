# Week 7 — Agent Orchestration: Recipe Box Sprint

**Student:** Mohamad Abdullah (2409115735)
**Repo:** https://github.com/mohamad-abdullah-710/week7-orchestration
**Tooling:** Claude Code (Claude Opus 5.5) as orchestrator, running Claude Code subagents
as the parallel workers, the generator and the critic. Isolation with **git worktrees**.

Full evidence: [`docs/part1-agent-reports.md`](docs/part1-agent-reports.md) and
[`docs/part2-generator-critic.md`](docs/part2-generator-critic.md) (generator–critic transcript).

---

## 1. Part I — Concurrent agents

### Tasks
| | Agent A | Agent B |
|---|---|---|
| Task | 2 — Tag filter `GET /recipes?tag=` | 4 — Favorites `favorite` + `POST /recipes/{id}/favorite` |
| Worktree / branch | `../recipe-task-a` / `task-a` | `../recipe-task-b` / `task-b` |
| Ran (UTC) | **21:19:32 → 21:20:20** | **21:19:32 → 21:20:18** |
| Commit | `6a908b6` | `f58b96b` |
| Tests in own worktree | 7 passed | 7 passed |

Both agents were launched in the same message and ran at the same time (identical start
second, finished 2 seconds apart).

### Worktree setup
```bash
git worktree add ../recipe-task-a -b task-a
git worktree add ../recipe-task-b -b task-b
# 3 passed in each worktree before the agents started
```

### How they were kept from colliding
- **Separate folders and branches:** each worktree has its own files, and its own
  `recipes.db` (the DB path is next to `main.py`), so the agents could not overwrite each
  other's files or data while running.
- **Strict instructions:** "work only in your own worktree", no branch switching, push,
  merge, rebase or installs. Each agent could only commit on its own branch.
- **Orchestrator merges, not the agents:** after both finished I checked that each branch
  had exactly one new commit, tests passed in each worktree and `master` was untouched.

### Collisions and risks actually seen
- `git merge task-a` → clean. `git merge task-b` → `main.py` **auto-merged** (the agents
  edited different functions), but `test_main.py` had **2 conflicts**: the import lines at
  the top (`import uuid` vs `import sqlite3`) and the tests both agents appended at the end.
  Both agents had predicted exactly these spots in their reports.
- Resolved by keeping both sides → `ruff` clean, `pytest` **11 passed**.
- **Risk git can't see:** a merge without conflicts can still break behaviour. I checked
  that a favorited recipe filtered by tag still comes back with `"favorite": true`.
- **Shared database after merge:** once merged, all tests share one `recipes.db`. Agent A
  used unique tag names and Agent B used a temporary DB for its migration test, so leftover
  rows do not break them.
- **Schema change by one agent:** Agent B added a column; it wrote a migration
  (`PRAGMA table_info` → `ALTER TABLE`) so old `recipes.db` files keep working.

---

## 2. Part II — Generator–critic loop (Task 3: ingredient scaling)

Generator and critic were two **separate** subagents. The generator only got the task text;
the critic got a rubric (**correctness, tests, clarity**) and tagged issues
blocking / major / minor, approving only when no blocking or major issues remained.
Full transcript: [`docs/part2-generator-critic.md`](docs/part2-generator-critic.md).

| Round | Commit | Tests | Critic verdict | Issues (blocking / major / minor) |
|---|---|---|---|---|
| 1 | `20d04e2` | 16 passed | **CHANGES_REQUESTED** | 0 / 2 / 4 |
| 2 (revision 1) | `f74aed2` | 21 passed | APPROVED | 0 / 0 / 4 |
| 3 (revision 2) | `79383bb` | 25 passed | **APPROVED** (final) | 0 / 0 / 2 cosmetic |

What each review found:
- **Round 1 → 2:** ranges were silently wrong (`"2-3 cloves garlic"` ×2 → `"4-3"`), and a
  thousands comma was read as a decimal (`"1,000 g sugar"` ×2 → `"2 g sugar"`, 1000× too
  small). Also Unicode fractions (`½`), tiny amounts rounding to `"0"`, missing tests.
- **Round 2 → 3:** the critic approved, but one "minor" issue was a real crash: a stored
  ingredient with a 5000-digit number made the endpoint return **HTTP 500**. I reproduced it
  and sent all four minors back for a second revision (also `"2 or 3 eggs"` → `"4 or 3"`).
- **Round 3:** HTTP 500 fixed (now 200, line left unchanged), `or` / em-dash ranges work,
  ambiguities documented, 4 more tests. Final approval.

Merged into `master` (`0a6f29c`): `pytest` **25 passed**, `ruff` clean.

---

## 3. Autonomy levels and supervision

| Agent | Allowed | Not allowed | How I supervised |
|---|---|---|---|
| Agent A / Agent B (Part I) | Edit + test + commit in **own worktree** only | Other folders, branch switch, push, merge, installs | Checked each branch, test results and that `master` was untouched before merging myself |
| Generator (Part II) | Edit + test + commit in `../recipe-task-c` | Push, merge, installs | Re-ran tests and reproduced the critic's failing inputs after every revision |
| Critic (Part II) | **Read-only**: read code, run tests and probe scripts | Any edit or commit | Reproduced its two major findings and its HTTP 500 finding before passing them on |
| Orchestrator (main session) | Create worktrees, merge, write docs, commit locally | Push or open PRs without my OK | I approved creating the repo and every push |

**Supervision mattered:** in round 2 the generator committed while one test was
**failing**, because its commit command was chained after `ruff` instead of `pytest`. It
reported this itself and amended the commit; for round 3 I told it to run pytest first and
only commit if it passes.

---

## 4. What I learned

Running two agents at the same time was worth it: it saved time, and the two merge
conflicts were easy to fix, but it works best when the agents work on different files so
conflicts don't happen at all. The critic found bugs the generator missed because it looked
at the code with fresh eyes and tested real examples, while the generator only tested what
it expected to work, so it missed important edge cases. AI agents can work independently,
but they shouldn't have complete freedom: we should give them small tasks, make sure they
run all the tests, and always have a human review the code before merging, because AI can
make mistakes, like committing with a failing test or calling a crash "minor".
