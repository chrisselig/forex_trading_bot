# Add Feature

Implement the following feature: $ARGUMENTS

---

## Process

Do NOT start writing code immediately. Follow this sequence:

### 1. Understand the Context
- Read existing code in the module(s) you'll touch
- Understand how the feature connects to the existing architecture
- Identify what changes and what stays the same

### 2. Design the Interface First
- What does the caller see? Define the function signatures / class API
- What data flows in and out? Define or reuse Pydantic models
- Where does it live in the module structure?

### 3. Implement
- Write the minimal code that works
- Follow existing patterns in the codebase

### 4. Test
- Unit test the happy path and at least one failure path
- Mock external dependencies

### 5. Integrate
- Wire into CLI / scheduler / execution pipeline as appropriate
- Update config if new tunables are needed

---

## Architecture Decision Guide

### Adding a New Strategy

**BAD** — standalone function, no interface contract, can't be discovered:
```python
# my_strategy.py
async def run_my_strategy(event, price):
    if event.surprise_pct and event.surprise_pct > 5:
        return {"side": "BUY", "pair": price.instrument}
```

**GOOD** — inherits BaseStrategy, plugs into registry, returns typed Signal:
```python
# strategy/momentum.py
class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self):
        settings = get_settings()
        self._lookback_bars = settings.strategy.momentum_lookback_bars

    async def evaluate_pre_event(self, event, price) -> list[Signal]:
        return []  # momentum is post-event only

    async def evaluate_post_event(self, event, price) -> list[Signal]:
        # ... analysis logic ...
        return [Signal(
            instrument=price.instrument,
            side=side,
            order_type=OrderType.MARKET,
            stop_loss=sl,
            take_profit=tp,
            event_id=event.id,
            strategy=self.name,
            reason=f"Momentum {direction} after {event.title}",
        )]

    async def should_close_positions(self, event, price) -> list[CloseSignal]:
        return []

# strategy/registry.py — register it:
def create_default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(StraddleStrategy())
    registry.register(SurpriseStrategy())
    registry.register(MomentumStrategy())  # new
    return registry
```

### Adding a New Risk Rule

**BAD** — inline check buried in execution engine:
```python
# execution/engine.py
async def execute_signal(self, signal):
    if signal.quantity > 500000:  # magic number, untestable, easy to bypass
        return None
```

**GOOD** — proper rule class, tested independently, impossible to bypass:
```python
# risk/rules.py
class MaxPositionSize(RiskRule):
    def __init__(self, max_units: float = 500_000):
        self.max_units = max_units

    def validate(self, signal, account, price=None, **kwargs) -> str | None:
        if signal.quantity > self.max_units:
            return f"Position {signal.quantity:,.0f} exceeds max {self.max_units:,.0f} units"
        return None

# risk/manager.py — add to rules list:
self._rules.append(MaxPositionSize(settings.risk.max_position_size))

# config/settings.yaml — new tunable:
risk:
  max_position_size: 500000
```

### Adding a New CLI Command

**BAD** — synchronous, no error handling, raw print:
```python
@app.command()
def positions():
    client = IBClient()
    # how do you run async from sync? asyncio.run? what about cleanup?
    import asyncio
    positions = asyncio.run(client.get_positions())
    for p in positions:
        print(f"{p}")
```

**GOOD** — follows the established async wrapper pattern, Rich output, proper cleanup:
```python
@app.command()
def positions():
    """Show current open positions."""
    async def _positions():
        async with IBClient() as client:
            account_service = AccountService(client)
            positions = await account_service.get_positions()
            if positions:
                dashboard = Dashboard()
                dashboard.show_positions(positions)  # Rich table
            else:
                console.print("[dim]No open positions[/dim]")

    asyncio.run(_positions())
```

### Adding a New Data Model

**BAD** — Pydantic model but not integrated:
```python
# Created models/alerts.py but:
# - not re-exported from models/__init__.py
# - no corresponding ORM schema in data/schemas.py
# - not used in any trade journal method
```

**GOOD** — full integration:
```python
# 1. models/alerts.py — define the Pydantic model
class Alert(BaseModel):
    instrument: str
    message: str
    severity: str = "info"
    created_at: datetime = Field(default_factory=datetime.utcnow)

# 2. models/__init__.py — re-export
from forex_bot.models.alerts import Alert

# 3. data/schemas.py — ORM schema (if persisted)
class AlertRecord(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

---

## Configuration Discipline

Every tunable value belongs in config, not in code.

**BAD** — magic numbers scattered in source:
```python
class MomentumStrategy:
    async def evaluate(self, event, price):
        if len(bars) < 20:    # why 20?
            return []
        if change > 0.003:     # what is 0.003?
            sl = price - 15 * 0.0001   # what is 15? what is 0.0001?
```

**GOOD** — all tunables in config with descriptive names:
```yaml
# config/settings.yaml
strategy:
  momentum_lookback_bars: 20
  momentum_threshold: 0.003
  momentum_sl_pips: 15
```
```python
class MomentumStrategy:
    def __init__(self):
        s = get_settings().strategy
        self._lookback = s.momentum_lookback_bars
        self._threshold = s.momentum_threshold
        self._sl_pips = s.momentum_sl_pips
```

---

## Quality Checklist

Before considering the feature done:

- [ ] Type hints on every new function/method
- [ ] Pydantic model for any new data structure
- [ ] At least one unit test for the happy path
- [ ] At least one unit test for a failure/edge case
- [ ] All external calls mocked in unit tests
- [ ] Custom exceptions used (not bare `raise Exception`)
- [ ] Config values in `settings.yaml`, not hardcoded
- [ ] Logging: `info` for significant actions, `debug` for details, `warning` for recoverable issues, `error` for failures
- [ ] No new `# type: ignore` or `# noqa` without justification
- [ ] `pytest tests/unit/ -v` passes with the new code
