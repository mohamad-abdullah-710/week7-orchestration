# Part II — Generator–critic loop transcript (Task 3: ingredient scaling)

- **Generator:** Claude Code subagent (Claude Opus 5.5). Can edit and commit only in
  worktree `../recipe-task-c`, branch `task-c-scaling`. Received only the task text.
- **Critic:** a separate Claude Code subagent (Claude Opus 5.5). **Read-only**: may read code
  and run tests/scripts, may not edit or commit. Reviews against the rubric below.
- **Orchestrator:** Claude Code in the main session passes messages between them,
  supervised by Mohamad. Loop ends when the critic returns `VERDICT: APPROVED`.

### Rubric given to the critic
1. **Correctness:** the endpoint does what the task says for realistic ingredients; edge
   cases do not crash or silently give wrong answers.
2. **Tests:** behaviour and edge cases are covered by meaningful pytest tests.
3. **Clarity:** code and API are easy to understand; names, docstrings and responses are clear.

Each issue is tagged **blocking**, **major** or **minor**. The critic approves only when no
blocking or major issues remain.

---

## Round 1 — Generator (21:21:47 UTC start) → commit `20d04e2`

> Task given: *"Ingredient scaling — `GET /recipes/{id}/scaled?factor=2` returns the recipe
> with quantities scaled (assume ingredients like "200 g flour"). Implement it with tests."*

Generator report (summary):
- `GET /recipes/{recipe_id}/scaled?factor=...`, `factor: float = Query(..., gt=0, le=1000)`;
  read-only (reuses `get_recipe`, so unknown id → 404); response = recipe + `"factor"`.
- `scale_ingredient(ingredient, factor)`: regex for the **leading** quantity: whole
  numbers, decimals (`.` or `,`), fractions `a/b`, mixed numbers `a b/c`. No leading number →
  unchanged. `1/0` → unchanged. Result rounded to 2 decimals, trailing zeros dropped
  (`400.0` → `400`, `1/3 cup` × 1 → `0.33 cup`).
- Tests (5): doubling (whole / fraction / mixed / no number), stored recipe unchanged,
  unknown id 404, bad factors (`0`, `-1`, `abc`, `1001`, missing) → 422, unit tests of
  `scale_ingredient` formats.
- Limitations the generator itself listed: units don't change (`2 eggs` × 0.5 → `1 eggs`,
  `1 kg` stays kg), fractions shown as decimals, Unicode `½` not parsed, ranges `2-3` only
  scale the first number.
- Results: `pytest` → `16 passed`; `ruff` → `All checks passed!`

## Round 1 — Critic → `CHANGES_REQUESTED` (2 major, 4 minor)

```
VERDICT: CHANGES_REQUESTED

Checks run:
- pytest -> 16 passed;  ruff -> All checks passed!
- scale_ingredient("2-3 cloves garlic", 2) -> "4-3 cloves garlic" (expected "4-6 cloves garlic")
- scale_ingredient("2 to 3 apples", 2)     -> "4 to 3 apples"     (expected "4 to 6 apples")
- scale_ingredient("1/2-1 tsp chili", 2)   -> "1-1 tsp chili"     (expected "1-2 tsp chili")
- scale_ingredient("1,000 g sugar", 2)     -> "2 g sugar"         (expected "2000 g sugar")
- scale_ingredient("1½ cups flour", 2)     -> "2½ cups flour"     (expected "3 cups flour"); "½ cup milk" unchanged
- GET /scaled?factor=1e-9 on "200 g flour" -> "0 g flour"         (expected non-zero or 422)
- factor=nan / inf -> 422 (correct); "1 (400 g) can", "2 x 400 g tins", "1.5kg beef" scale correctly

Issues:
1. [major] Correctness — ranges silently wrong ("2-3" -> "4-3", "2 to 3" -> "4 to 3").
   Fix: optionally match a second quantity after "-", "–" or "to" and scale both.
2. [major] Correctness — comma always read as decimal: "1,000 g sugar" x2 -> "2 g sugar" (1000x off).
   Fix: treat \d{1,3}(,\d{3})+ as thousands before the decimal-comma branch, or drop decimal comma.
3. [minor] Correctness — Unicode fractions (½ ¼ ¾ ⅓ ⅔ ⅛) not handled.
4. [minor] Correctness — 2-decimal rounding turns small amounts into "0".
5. [minor] Tests — no tests for ranges, thousands separators, Unicode fractions.
6. [minor] Clarity — "0.33 cup" / "4.5 eggs" awkward; fine for scope, mention in docstring.

What is good:
- Read-only; 404 unknown id; 422 for bad/missing/nan/inf factor; stored recipe unchanged (tested).
- Handles plain/decimal/fraction/mixed numbers, attached units, parenthetical sizes, zero denominator.
- Small readable helpers, clear docstrings, ruff clean.
```

Orchestrator check: reproduced issues 1 and 2 myself (`"2-3 cloves garlic"` x2 → `"4-3 cloves garlic"`,
`"1,000 g sugar"` x2 → `"2 g sugar"`) before sending the review to the generator.

---

## Round 2 — Generator (21:24:06 UTC start) → commit `f74aed2`

Changes per critic issue:
1. **[major] Ranges** — pattern optionally matches a second quantity after `-`, `–` or ` to `
   and scales both: `"2-3 cloves garlic"` ×2 → `"4-6 cloves garlic"`, `"2 to 3 apples"` →
   `"4 to 6 apples"`, `"1/2-1 tsp chili"` → `"1-2 tsp chili"`. `"2 tomatoes"` → `"4 tomatoes"`
   (" to " only counts when a number follows).
2. **[major] Thousands** — `\d{1,3}(,\d{3})+` is read as thousands before the decimal-comma
   case: `"1,000 g sugar"` ×2 → `"2000 g sugar"`. `"1,5"` is still 1.5. Tradeoff (in
   docstring): `"1,500"` now means 1500, not 1.5.
3. **[minor] Unicode fractions** — `¼ ½ ¾ ⅓ ⅔ ⅛ ⅜ ⅝ ⅞`, alone, attached (`1½`), spaced (`1 ½`),
   in ranges: `"1½ cups flour"` ×2 → `"3 cups flour"`, `"½ cup milk"` → `"1 cup milk"`.
4. **[minor] Small amounts** — if 2-dp rounding gives "0" for a positive value, use 2
   significant figures: `"1 pinch salt"` ×0.001 → `"0.001 pinch salt"`.
5. **[minor] Tests** — 5 new tests (ranges, thousands, Unicode fractions, small amounts,
   end-to-end through the endpoint).
6. **[minor] Clarity** — "Known limits" added to the docstring (decimal output, units and
   plurals not adjusted, "4.5 eggs" possible).

Results: `pytest` → `21 passed`; `ruff` → `All checks passed!`

**Supervision note (reported by the generator itself):** its first round-2 commit
(`c5d473c`) was made while one test was failing, because the commit command was chained
after `ruff` instead of after `pytest`. It fixed the test (expected `"0.012"`, code correctly
gives `"0.01"`) and amended the local, unpushed commit to `f74aed2`.
Orchestrator check: history is `20d04e2` → `f74aed2`, `21 passed`, ruff clean, and the
critic's failing inputs now give the expected output.

## Round 2 — Critic → `APPROVED` (0 major, 4 minor)

```
VERDICT: APPROVED

Checks run:
- pytest -> 21 passed;  ruff -> All checks passed!
- Ranges: "2-3 cloves garlic" -> "4-6"; "2 to 3 apples" -> "4 to 6"; "1/2-1 tsp" -> "1-2";
  "2 – 3 carrots" -> "4 – 6"; "1/2 - 3/4 cup" -> "1 - 1.5"; "2 tomatoes" / "2 to taste" not ranges. Verified.
- Thousands: "1,000 g" -> "2000 g"; "1,000,000 g" -> "2000000 g"; "1,5 kg" -> "3 kg";
  "1,25 l" -> "2.5 l"; "1,500 g" -> "3000 g" (documented tradeoff). Verified.
- Unicode: "1½ cups" -> "3 cups"; "1 ½ cups" -> "3 cups"; "½ cup" -> "1 cup"; "½-1 tsp" -> "1-2 tsp". Verified.
- Tiny: "1 pinch salt" x0.001 -> "0.001 pinch salt"; "200 g flour" x1e-9 -> "0.0000002 g flour". Verified.
- No regressions: "1-inch piece ginger" -> "2-inch ...", "1 12-ounce can" -> "2 12-ounce can",
  "2 x 400 g" -> "4 x 400 g"; "2-1/0 cup", "1 1/0 cup" unchanged.

Issues (all minor):
1. [minor] Correctness — em dash and "or" ranges not recognised: "2—3 eggs" -> "4—3 eggs", "2 or 3 eggs" -> "4 or 3 eggs".
2. [minor] Correctness — absurd stored input: 5000-digit numerator raises ValueError (int conversion
   limit) -> endpoint 500; 400-digit integer -> "inf g". Existed in round 1 too.
   Fix: bound digit runs (e.g. \d{1,9}) or catch ValueError/OverflowError and leave the line unchanged.
3. [minor] Correctness — hyphen ambiguity ("3 1/2-ounce bar" -> "7-ounce bar"); dot thousands
   ("1.000 g") read as decimal. Could be noted in docstring.
4. [minor] Tests — no test locking in "1-inch piece ginger", em dash or "or".

What is good:
- All six round-1 issues fixed and verified by probing.
- Clean split _NUMBER / _parse_quantity / _format_quantity, commented regex, honest "Known limits".
- Small-amount rule well chosen and tested; endpoint behaviour (404/422/read-only/factor echo) kept.
```

**Orchestrator decision:** the critic approved, but I reproduced issue 2 myself and the
endpoint really returns **HTTP 500** for a stored ingredient with a 5000-digit number, and
`"2 or 3 eggs"` ×2 → `"4 or 3 eggs"`. A server crash on stored data is worth fixing, and the
assignment asks for ≥2 revision rounds, so I sent the four minor issues back for **round 3**
and asked the critic to review once more.

---

## Round 3 — Generator (21:27:21 UTC start) → commit `79383bb`

This time pytest ran **before** the commit, and the commit only ran if it passed.

1. **Range separators** — em dash `—` and ` or ` added: `"2—3 eggs"` ×2 → `"4—6 eggs"`,
   `"2 or 3 eggs"` → `"4 or 6 eggs"`; `"2 or more eggs"` → `"4 or more eggs"` (not a range).
2. **HTTP 500 / "inf"** — catches `ValueError` (huge digit strings) and `OverflowError`;
   checks every scaled value with `math.isfinite`; also found and fixed an **underflow** case
   itself (`"1/111…1"` with 400 digits printed `"0 g"`). All of these leave the line unchanged.
   Through the endpoint: HTTP 200, bad lines unchanged, `"200 g butter"` → `"400 g butter"`.
3. **Ambiguities** — documented in the docstring: a dash is a range only if a number follows
   (`"1-inch piece"` is one quantity, `"3 1/2-ounce bar"` → `"7-ounce bar"`); a dot is
   always decimal (`"1.000 g"` = 1.0).
4. **Tests** — 4 new: more range separators, hyphen-not-a-range, huge numbers left
   unchanged (5 cases), endpoint does not return 500.

Results: `pytest` → `25 passed`; `ruff` → `All checks passed!`
Orchestrator check: history `20d04e2` → `f74aed2` → `79383bb`; 5000-digit numerator through
the endpoint now gives **HTTP 200** (was 500); `"2 or 3 eggs"` → `"4 or 6 eggs"`.

## Round 3 — Critic → `APPROVED` (final; 2 cosmetic minors left)

```
VERDICT: APPROVED

Checks run:
- git status clean; HEAD 79383bb;  pytest -> 25 passed;  ruff -> All checks passed!
- Separators: "2—3 eggs" -> "4—6"; "2 or 3 eggs" -> "4 or 6"; "2 or more eggs" -> "4 or more"; "2 oranges" -> "4 oranges". Verified.
- Huge numbers: 5000-digit integer + "½" -> unchanged, no exception; 400/399-digit mixed number -> "22 x" (correct);
  "2 or 1/0 x" -> unchanged; endpoint test with 5000-digit numerator -> 200. Verified.
- Docstring covers hyphen ambiguity, dot = decimal, huge-number behaviour; 4 meaningful new tests. Verified.
- No regressions: "2-3 cloves" -> "4-6"; "2 to 3 apples" -> "4 to 6"; "½-1 tsp" -> "1-2"; "1,000 g" -> "2000 g";
  "1½ cups" -> "3 cups"; "1 pinch" x0.001 -> "0.001 pinch"; "0 g sugar" unchanged; "salt to taste", "1/0 cup" unchanged;
  "200 g flour" x1000 -> "200000 g flour".

Issues:
1. [minor] Clarity — huge-but-finite amounts show float noise ("1" + 300 zeros g x2 -> "2000…0000105009…").
   Cosmetic; optional fix: use .15g above ~1e15.
2. [minor] Clarity — guard logic is split between _parse_quantity and scale_ingredient; could be simplified later.

What is good:
- All round-2 minors fixed and re-verified; new guards fail safe with no regressions.
- Docstring states parsing rules, ambiguities and limits clearly.
- Tests cover main path, ranges, separators, thousands vs decimal comma, Unicode fractions,
  tiny/huge amounts, 404/422 and read-only behaviour, at unit and endpoint level.
```

**Loop ended:** `APPROVED` with no blocking/major issues. The two remaining minors are
cosmetic and were accepted as known limitations.

---

## Summary

| Round | Generator commit | Tests | Critic verdict | Issues (blocking / major / minor) |
|---|---|---|---|---|
| 1 | `20d04e2` | 16 passed | CHANGES_REQUESTED | 0 / 2 / 4 |
| 2 (revision 1) | `f74aed2` | 21 passed | APPROVED | 0 / 0 / 4 |
| 3 (revision 2) | `79383bb` | 25 passed | APPROVED | 0 / 0 / 2 (cosmetic) |

Two revision rounds, each one driven by the critic's review and verified by the
orchestrator (reproducing the critic's failing inputs before and after each revision).
