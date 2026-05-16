# Git & GitHub Workflow

Help me with Git/GitHub operations following these conventions:

---

## Branch Strategy

```
main                        # stable, always deployable
feature/<name>              # new capabilities
fix/<name>                  # bug fixes
refactor/<name>             # structural improvements, no behavior change
```

Create branches from `main`. Merge back via PR. Delete branch after merge.

---

## Commit Messages

Format: `<type>: <imperative description>`

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

**BAD** — past tense, vague, describes what the diff already shows:
```
Added some changes to the risk module
Updated files
Fixed stuff
feat: changed the circuit breaker to work differently
```

**GOOD** — imperative mood, specific, explains the WHY in body when needed:
```
feat: add surprise strategy post-event signal generation

Trade in the direction of economic data surprises when the
magnitude exceeds the configured threshold. Handles the
inverse relationship for unemployment-type indicators.
```

```
fix: handle IB Gateway daily disconnect at 11:45 PM ET

The health check now detects stale connections and triggers
reconnection instead of waiting for the next operation to fail.
```

```
refactor: extract position sizing into RiskManager

Centralizes the units = (balance * risk%) / (sl_pips * pip_value)
calculation so strategies don't duplicate this logic.
```

**BAD** — giant commit that touches everything:
```
feat: add strategies, risk management, execution engine, and tests
```
This is unreviewable. If one part has a bug, you can't revert without losing everything.

**GOOD** — atomic commits, one logical change each:
```
feat: add BaseStrategy ABC with pre/post event hooks
feat: implement straddle strategy for pre-event brackets
feat: implement surprise strategy for post-event direction
test: add straddle and surprise strategy unit tests
```

---

## Commit Scope Rules

Each commit should pass tests independently. Never commit code that breaks the build "because the next commit fixes it."

**BAD** — commit 1 breaks imports, commit 2 fixes them:
```
commit 1: feat: add new pricing module
commit 2: fix: add missing import for pricing module
```

**GOOD** — single commit that works:
```
commit 1: feat: add pricing module with real-time and historical bar support
```

---

## PR Conventions

**BAD** PR description:
```
## Changes
Changed some stuff in the broker module
```

**GOOD** PR description:
```
## Summary
- Add bracket order support for straddle strategy pre-event placement
- IB's OCA (One Cancels All) groups link the buy-stop and sell-stop legs

## What changed
- `broker/orders.py`: new `place_bracket_order()` using `ib.bracketOrder()`
- `strategy/straddle.py`: generates paired BUY/SELL stop signals
- `execution/engine.py`: routes bracket signals to bracket order placement

## How to test
1. Run `pytest tests/unit/test_strategies.py -v`
2. With IB Gateway: `forex-bot test-connection` then place a test bracket
```

---

## What NOT to Commit

| File/Pattern | Why |
|---|---|
| `.env` | Contains FRED_API_KEY and potentially sensitive config |
| `data/*.db` | Local SQLite databases with trade history |
| `data/*.log` | Runtime log files |
| `__pycache__/` | Bytecode cache, platform-specific |
| `.venv/` | Virtual environment, 500MB+ of packages |
| `*.pyc` | Compiled Python files |

All of these are in `.gitignore`. If you see them in `git status`, something is wrong.

**BAD** — staging everything blindly:
```bash
git add .
git add -A
```

**GOOD** — stage specific files you intend to commit:
```bash
git add src/forex_bot/strategy/straddle.py tests/unit/test_strategies.py
```

---

## Pre-Commit Mental Checklist

Before every commit, verify:

1. **Tests pass**: `pytest tests/unit/ -v`
2. **No secrets**: `git diff --cached | grep -i "api_key\|password\|secret"` returns nothing
3. **No debug leftovers**: `git diff --cached | grep -n "print(\|breakpoint()\|pdb\|import pdb"` returns nothing
4. **No unused imports**: scan the diff for imports that aren't used
5. **Diff makes sense**: `git diff --cached` — read every line, does it all belong together?

---

## Dangerous Commands — Think Twice

| Command | Risk | Alternative |
|---|---|---|
| `git push --force` | Destroys remote history, can lose others' work | `git push --force-with-lease` (safer, rejects if remote changed) |
| `git reset --hard` | Destroys uncommitted work permanently | `git stash` (saves work), then reset |
| `git checkout -- .` | Discards all unstaged changes | `git stash` first |
| `git clean -fd` | Deletes untracked files permanently | `git clean -fdn` (dry run first) |
| `git rebase main` on a shared branch | Rewrites history others depend on | `git merge main` for shared branches |

When I ask for Git help, follow these conventions. If I'm about to do something destructive, warn me first.
