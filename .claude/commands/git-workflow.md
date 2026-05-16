# Git & GitHub Workflow

Help me with Git/GitHub operations following these conventions:

## Branch Strategy
- `main` — stable, deployable code
- `feature/<name>` — new features
- `fix/<name>` — bug fixes
- `refactor/<name>` — code improvements

## Commit Messages
- Format: `<type>: <description>` (lowercase, imperative mood)
- Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
- Keep subject under 72 chars
- Body explains WHY, not WHAT (the diff shows what)
- Examples:
  - `feat: add surprise strategy post-event signal generation`
  - `fix: handle IB Gateway daily disconnect at 11:45 PM ET`
  - `test: add circuit breaker state transition tests`

## PR Conventions
- Title matches the primary commit type
- Description includes: Summary, What changed, How to test
- Link related issues
- Keep PRs focused — one logical change per PR

## What NOT to Commit
- `.env` files (secrets)
- `data/` directory (SQLite DBs, logs)
- `__pycache__/`, `.venv/`
- IDE configs (`.idea/`, `.vscode/` unless shared settings)

## Pre-Commit Checks
Before committing, verify:
1. `pytest tests/unit/` passes
2. No secrets in staged files
3. No debug print statements left behind
4. Imports are clean (no unused)

When I ask for Git help, follow these conventions and suggest the appropriate commands.
