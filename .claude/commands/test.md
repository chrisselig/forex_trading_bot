# Run Tests

Run the test suite, fix any failures, and verify coverage for recent changes.

---

## Commands

```bash
# All unit tests
pytest tests/unit/ -v

# Specific module
pytest tests/unit/test_risk.py -v

# Specific test
pytest tests/unit/test_risk.py::TestCircuitBreaker::test_halts_on_drawdown -v

# Integration tests (requires IB Gateway running)
pytest tests/integration/ -v -m integration

# With coverage report
pytest tests/unit/ --cov=forex_bot --cov-report=term-missing

# Stop on first failure (useful during debugging)
pytest tests/unit/ -x -v
```

---

## When Tests Fail

### Read the FULL traceback, not just the last line

**BAD** debugging:
```
AssertionError: assert None is not None
"Hmm, it's returning None. Let me add a None check."
```

**GOOD** debugging:
```
# Read the FULL traceback:
tests/unit/test_strategies.py:87: in test_generates_signal_on_surprise
    signals = await strategy.evaluate_post_event(event, price)
src/forex_bot/strategy/surprise.py:42: in evaluate_post_event
    surprise = event.surprise_pct
# → surprise_pct returns None because actual="250K" can't be parsed
# → the "K" suffix handling has a bug in the float conversion
# Root cause: parsing logic, not the test or the strategy
```

### Is the test wrong, or is the code wrong?

Ask yourself: "If I were a user calling this function with these inputs, what SHOULD happen?"

**BAD** — changing the test to match buggy code:
```python
# Test expected SELL for positive NFP surprise on EURUSD
# Code returns BUY
# "Fix": change test to expect BUY
# NO — the economics are wrong. Positive NFP = USD strength = SELL EURUSD.
```

**GOOD** — fixing the code to match correct behavior:
```python
# The code has the USD direction logic inverted
# Fix the code, keep the test assertion
```

---

## Writing Good Tests

### Test Structure: Arrange-Act-Assert

**BAD** — test does too many things, unclear what's being tested:
```python
async def test_stuff():
    event = EconomicEvent(title="NFP", scheduled_at=datetime.utcnow(), actual="250K", forecast="200K")
    price = PriceSnapshot(instrument="EURUSD", timestamp=datetime.utcnow(), bid=1.085, ask=1.0852)
    strategy = SurpriseStrategy()
    signals = await strategy.evaluate_post_event(event, price)
    assert len(signals) == 1
    assert signals[0].side == OrderSide.SELL
    assert signals[0].stop_loss is not None
    assert signals[0].take_profit is not None
    assert signals[0].instrument == "EURUSD"
    assert signals[0].strategy == "surprise"
    signals2 = await strategy.evaluate_pre_event(event, price)
    assert len(signals2) == 0
    # Now test with no actual...
    event2 = EconomicEvent(title="NFP", scheduled_at=datetime.utcnow(), forecast="200K")
    signals3 = await strategy.evaluate_post_event(event2, price)
    assert len(signals3) == 0
```

**GOOD** — one concept per test, descriptive names, clear structure:
```python
async def test_positive_nfp_surprise_sells_eurusd(event_with_positive_surprise, price):
    """Positive NFP = USD strength = SELL EURUSD (USD is quote currency)."""
    # Arrange — fixtures handle setup
    strategy = SurpriseStrategy()

    # Act
    signals = await strategy.evaluate_post_event(event_with_positive_surprise, price)

    # Assert
    assert len(signals) == 1
    assert signals[0].side == OrderSide.SELL
    assert signals[0].stop_loss is not None

async def test_no_signal_without_actual_data(price):
    """Strategy should not generate signals when actual data hasn't been released."""
    event = EconomicEvent(title="NFP", scheduled_at=datetime.utcnow(), forecast="200K")
    strategy = SurpriseStrategy()

    signals = await strategy.evaluate_post_event(event, price)

    assert len(signals) == 0

async def test_surprise_strategy_ignores_pre_event(event, price):
    """Surprise strategy is post-event only."""
    strategy = SurpriseStrategy()
    signals = await strategy.evaluate_pre_event(event, price)
    assert len(signals) == 0
```

### Test Names Should Describe the Behavior

**BAD** names — what does "test_1" actually test?
```python
def test_circuit_breaker_1():
def test_risk():
def test_order_stuff():
def test_it_works():
```

**GOOD** names — readable as a spec of the system:
```python
def test_circuit_breaker_halts_on_daily_drawdown_exceeding_3_percent():
def test_rejects_order_without_stop_loss():
def test_winning_trade_resets_consecutive_loss_counter():
def test_straddle_places_buy_stop_above_and_sell_stop_below_mid():
```

### Mocking — Mock at the Boundary, Not Everywhere

**BAD** — mocking internals, test is coupled to implementation details:
```python
async def test_execute_signal():
    with patch("forex_bot.execution.engine.get_pip_size", return_value=0.0001):
        with patch("forex_bot.execution.engine.OrderService") as mock_os:
            with patch("forex_bot.execution.engine.PricingService") as mock_ps:
                with patch("forex_bot.execution.engine.RiskManager") as mock_rm:
                    # 4 layers of mocking = test breaks if any internal changes
```

**GOOD** — inject mocked dependencies, test the logic:
```python
async def test_execute_signal_with_risk_rejection(mock_ib_client):
    """ExecutionEngine should return None when risk manager rejects the signal."""
    journal = TradeJournal()
    circuit_breaker = CircuitBreaker()
    risk_manager = RiskManager(mock_ib_client, circuit_breaker, journal)

    # Make risk manager reject everything
    risk_manager.validate = AsyncMock(return_value=["Daily drawdown exceeded"])

    engine = ExecutionEngine(mock_ib_client, risk_manager, circuit_breaker, journal)
    signal = Signal(instrument="EURUSD", side=OrderSide.BUY, stop_loss=1.0800)

    result = await engine.execute_signal(signal)

    assert result is None  # rejected by risk
```

### Test Edge Cases That Actually Matter

**BAD** — only testing the happy path:
```python
def test_calculate_position_size():
    size = calculate_position_size(100000, 15, "EURUSD")
    assert size > 0  # great, it returns a number. but does it return the RIGHT number?
```

**GOOD** — test boundaries, inversions, zero/negative inputs:
```python
def test_position_size_standard_case():
    # $100K account, 1% risk, 15 pip SL, EURUSD
    # risk = $1000, pip_value = 0.0001, units = 1000 / (15 * 0.0001) = 666,666
    # rounded to nearest 1000 = 667,000
    size = calculate_position_size(100000, 15, "EURUSD", risk_pct=1.0)
    assert size == 667000

def test_position_size_jpy_pair():
    # JPY pairs have pip_size=0.01, so position size should be much smaller
    size = calculate_position_size(100000, 15, "USDJPY", risk_pct=1.0)
    assert size == 67000  # 1000 / (15 * 0.01) = 6,666 → 7,000

def test_position_size_minimum():
    # Tiny account should still get minimum lot size (1000 units)
    size = calculate_position_size(100, 50, "EURUSD", risk_pct=1.0)
    assert size == 1000  # minimum enforced

def test_position_size_respects_risk_percentage():
    size_1pct = calculate_position_size(100000, 15, "EURUSD", risk_pct=1.0)
    size_2pct = calculate_position_size(100000, 15, "EURUSD", risk_pct=2.0)
    assert size_2pct == pytest.approx(size_1pct * 2, rel=0.01)
```

---

## Test Organization

```
tests/
  conftest.py              # shared fixtures (sample events, prices, mock client)
  unit/                    # fast, mocked, run on every commit
    test_models.py         # Pydantic model validation, computed properties
    test_contracts.py      # contract creation, pip sizes
    test_risk.py           # risk rules, circuit breaker state machine
    test_strategies.py     # signal generation logic
    test_config.py         # YAML loading, defaults, overrides
  integration/             # slow, requires IB Gateway, run before deploy
    test_ib_connection.py  # connect, fetch summary, disconnect
    test_pricing.py        # fetch real bars, stream real quotes
    test_orders.py         # place and cancel on paper account
  backtest/                # historical replay
    runner.py              # event replay engine
    data_loader.py         # load historical events + prices
```

Run the tests now, report results, and fix any failures.
