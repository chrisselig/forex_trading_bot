# Add Feature

Implement the following feature: $ARGUMENTS

## Implementation Checklist

Follow this process for any new feature:

1. **Understand** — Read existing related code before writing anything new
2. **Design** — Determine which module(s) the feature belongs in
3. **Implement** — Write the minimal code needed
4. **Test** — Add unit tests covering the happy path and edge cases
5. **Integrate** — Wire it into the existing system (CLI, scheduler, etc.)
6. **Document** — Update CLAUDE.md if it changes conventions or adds commands

## Architecture Rules
- New strategies: inherit `BaseStrategy`, register in `strategy/registry.py`
- New risk rules: inherit `RiskRule`, add to `RiskManager.__init__`
- New CLI commands: add to `cli.py` with async wrapper pattern
- New data models: add to `models/`, re-export from `models/__init__.py`
- New broker features: add to appropriate file in `broker/`

## Quality Gates
- [ ] Type hints on all new functions
- [ ] Pydantic models for new data structures
- [ ] Unit tests with mocks (no real IB/network calls)
- [ ] Errors use custom exception hierarchy
- [ ] Config values in settings.yaml (not hardcoded)
- [ ] Logging at appropriate levels (info for actions, debug for details, warning for concerns, error for failures)

## What NOT to Do
- Don't bypass the risk management pipeline
- Don't add synchronous blocking calls in async code
- Don't hardcode connection params or trading parameters
- Don't commit without running `pytest tests/unit/`
