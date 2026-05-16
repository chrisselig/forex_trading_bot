# Run Tests

Run the test suite and fix any failures.

## Test Commands

```bash
# All unit tests (fast, no external deps)
pytest tests/unit/ -v

# Specific test file
pytest tests/unit/test_risk.py -v

# Specific test
pytest tests/unit/test_risk.py::TestCircuitBreaker::test_halts_on_drawdown -v

# Integration tests (requires IB Gateway running)
pytest tests/integration/ -v -m integration

# With coverage
pytest tests/unit/ --cov=forex_bot --cov-report=term-missing
```

## When Tests Fail

1. Read the full error/traceback
2. Identify if it's a test issue or a code issue
3. If code issue: fix the source, verify test passes
4. If test issue: update the test to match correct behavior (not the other way around, unless the test was wrong)

## Writing New Tests

- Place in `tests/unit/` for mocked tests, `tests/integration/` for live
- Use fixtures from `tests/conftest.py`
- Mock external services (IB, HTTP) — never hit real services in unit tests
- Test both success and failure paths
- Name tests descriptively: `test_rejects_order_without_stop_loss`

Run the tests now and report results.
