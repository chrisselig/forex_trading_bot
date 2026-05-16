# Python Best Practices Review

Review the code I'm working on against these standards. Flag violations with specific line references and provide corrected code.

---

## 1. Type Safety & Annotations

Every function signature must have type hints. Use `from __future__ import annotations` for forward references and `X | None` syntax.

**BAD** — untyped, caller has no idea what this returns or accepts:
```python
def calculate_position_size(balance, sl_pips, pair, risk_pct=None):
    pip_size = get_pip_size(pair)
    risk_amount = balance * (risk_pct / 100)
    return round(risk_amount / (sl_pips * pip_size) / 1000) * 1000
```

**GOOD** — types document the contract, IDE catches misuse, Pydantic validates:
```python
def calculate_position_size(
    account_balance: float,
    stop_loss_pips: float,
    pair: str,
    risk_pct: float | None = None,
) -> float:
    pip_size = get_pip_size(pair)
    if risk_pct is None:
        risk_pct = get_settings().risk.max_risk_per_trade_pct
    risk_amount = account_balance * (risk_pct / 100)
    units = risk_amount / (stop_loss_pips * pip_size)
    return max(round(units / 1000) * 1000, 1000)
```

**BAD** — stringly-typed data flowing through the system:
```python
def place_order(pair, side, qty, order_type, sl=None, tp=None):
    if side not in ("BUY", "SELL"):
        raise ValueError("bad side")
```

**GOOD** — enums catch typos at construction, not at runtime:
```python
def place_order(
    pair: str,
    side: OrderSide,       # StrEnum — "BYU" fails at creation
    quantity: float,
    order_type: OrderType,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> IBTrade:
```

---

## 2. Data Modeling

Use Pydantic models at system boundaries. Use them as the single source of truth for data shape.

**BAD** — dicts as data structures, keys are implicit, typos are silent:
```python
def get_account():
    return {
        "balance": 100000,
        "margin": 50000,
        "pnl": 250.0,
    }

summary = get_account()
print(summary["balence"])  # KeyError at runtime, no help from IDE
```

**GOOD** — Pydantic model validates on construction, IDE autocompletes fields:
```python
class AccountSummary(BaseModel):
    account_id: str = ""
    net_liquidation: float = 0.0
    buying_power: float = 0.0
    unrealized_pnl: float = 0.0

summary = AccountSummary(net_liquidation=100000)
print(summary.net_liquidation)  # autocomplete, typo caught at write-time
```

**BAD** — mutable default argument shared across all instances:
```python
class EventParser:
    def __init__(self, filters: list = []):
        self.filters = filters  # every instance shares the SAME list
```

**GOOD**:
```python
class EventParser:
    def __init__(self, filters: list[str] | None = None):
        self.filters = filters or []
# Or with Pydantic:
class EventsConfig(BaseModel):
    target_events: list[EventTarget] = Field(default_factory=list)
```

---

## 3. Async Discipline

This bot is async-first. Blocking the event loop freezes IB message processing, kills heartbeats, and can cause disconnects.

**BAD** — blocking call in async context, freezes the entire event loop:
```python
async def fetch_events(self):
    response = requests.get(FF_BASE_URL)  # blocks for seconds
    return self._parse(response.text)
```

**GOOD** — non-blocking HTTP, event loop stays responsive:
```python
async def fetch_events(self):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(FF_BASE_URL)
        return self._parse(response.text)
```

**BAD** — sequential awaits when operations are independent:
```python
async def reconcile(self):
    positions = await self._client.get_positions()
    orders = await self._client.get_open_orders()
    summary = await self._client.get_account_summary()
    # total time = sum of all three
```

**GOOD** — concurrent when no dependency between calls:
```python
async def reconcile(self):
    positions, orders, summary = await asyncio.gather(
        self._client.get_positions(),
        self._client.get_open_orders(),
        self._client.get_account_summary(),
    )
    # total time = max of the three
```

**BAD** — fire-and-forget task that silently swallows exceptions:
```python
async def on_event(self, event):
    asyncio.create_task(self._execute(event))  # exception vanishes
```

**GOOD** — track the task, log failures:
```python
async def on_event(self, event):
    task = asyncio.create_task(self._execute(event))
    task.add_done_callback(self._handle_task_exception)

def _handle_task_exception(self, task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.error(f"Task failed: {task.exception()}")
```

---

## 4. Error Handling

Errors should be specific, actionable, and never swallowed.

**BAD** — catches everything, logs nothing useful, hides bugs:
```python
async def place_order(self, order):
    try:
        trade = self.ib.placeOrder(contract, ib_order)
        return trade
    except Exception:
        return None  # caller has no idea what failed or why
```

**GOOD** — catches specific errors, logs context, re-raises or returns meaningful result:
```python
async def place_order(self, order: Order) -> IBTrade:
    try:
        trade = self.ib.placeOrder(contract, ib_order)
        return trade
    except ConnectionError as e:
        logger.error(f"IB disconnected while placing {order.side} {order.instrument}: {e}")
        raise
    except Exception as e:
        raise OrderError(
            f"Failed to place {order.order_type} {order.side} "
            f"{order.quantity} {order.instrument}: {e}"
        ) from e
```

**BAD** — using exceptions for control flow:
```python
def get_pip_size(pair):
    try:
        return PIP_SIZES[pair]
    except KeyError:
        return 0.0001
```

**GOOD** — dict.get() is the right tool, exceptions are for exceptional things:
```python
def get_pip_size(pair: str) -> float:
    return PIP_SIZES.get(pair.upper(), 0.0001)
```

**BAD** — nested try/except pyramid:
```python
async def execute(self, signal):
    try:
        price = await self._get_price(signal.instrument)
        try:
            violations = await self._risk_manager.validate(signal, price)
            if not violations:
                try:
                    order = await self._place(signal)
                except OrderError:
                    logger.error("order failed")
        except Exception:
            logger.error("risk check failed")
    except DataError:
        logger.error("price fetch failed")
```

**GOOD** — early returns flatten the structure, each failure handled at the right level:
```python
async def execute(self, signal: Signal) -> Order | None:
    try:
        price = await self._get_price(signal.instrument)
    except DataError as e:
        logger.error(f"No price for {signal.instrument}: {e}")
        return None

    violations = await self._risk_manager.validate(signal, price)
    if violations:
        logger.warning(f"Risk rejected {signal.instrument}: {violations}")
        return None

    try:
        return await self._place(signal)
    except OrderError as e:
        logger.error(f"Order failed for {signal.instrument}: {e}")
        return None
```

---

## 5. Dependency Injection & Testability

Code that creates its own dependencies is impossible to test in isolation.

**BAD** — creates its own client, can't inject a mock:
```python
class ExecutionEngine:
    def __init__(self):
        self._client = IBClient()             # hardwired, untestable
        self._risk = RiskManager()            # also hardwired
        self._journal = TradeJournal()        # and again
```

**GOOD** — accepts dependencies, tests pass in mocks:
```python
class ExecutionEngine:
    def __init__(
        self,
        client: IBClient,
        risk_manager: RiskManager,
        circuit_breaker: CircuitBreaker,
        journal: TradeJournal,
    ):
        self._client = client
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._journal = journal
```

**BAD** — module-level state that leaks between tests:
```python
# pricing.py
_cache = {}  # module global, survives across test runs

async def get_price(pair):
    if pair in _cache:
        return _cache[pair]
```

**GOOD** — state owned by instance, each test gets a clean one:
```python
class PricingService:
    def __init__(self, client: IBClient):
        self._client = client
        self._request_timestamps: list[float] = []  # instance state
```

---

## 6. Resource Management

Connections, sessions, and file handles must be cleaned up — even when exceptions occur.

**BAD** — connection leak on exception:
```python
async def check():
    client = IBClient()
    await client.connect()
    summary = await client.get_account_summary()  # if this throws...
    await client.disconnect()  # ...this never runs
    return summary
```

**GOOD** — context manager guarantees cleanup:
```python
async def check():
    async with IBClient() as client:  # __aexit__ calls disconnect even on error
        return await client.get_account_summary()
```

**BAD** — SQLAlchemy session left open on error:
```python
async def save_events(self, events):
    session = get_session()
    for event in events:
        session.add(EventRecord(...))
    await session.commit()  # if this throws, session is abandoned
```

**GOOD** — context manager with rollback:
```python
async def save_events(self, events):
    async with get_session() as session:  # auto-rollback on exception
        for event in events:
            session.add(EventRecord(...))
        await session.commit()
```

---

## 7. Naming & Readability

Code is read 10x more than it's written. Optimize for the reader.

**BAD** — abbreviations, unclear intent:
```python
def calc_ps(b, sl, p, r=None):
    ps = get_pip_size(p)
    ra = b * (r / 100)
    u = ra / (sl * ps)
    return max(round(u / 1000) * 1000, 1000)
```

**GOOD** — the code reads like prose:
```python
def calculate_position_size(
    account_balance: float,
    stop_loss_pips: float,
    pair: str,
    risk_pct: float | None = None,
) -> float:
    pip_size = get_pip_size(pair)
    risk_amount = account_balance * (risk_pct / 100)
    units = risk_amount / (stop_loss_pips * pip_size)
    return max(round(units / 1000) * 1000, 1000)
```

**BAD** — boolean parameter changes behavior invisibly at the call site:
```python
await pricing.get_data("EURUSD", True, False, True)  # what do these mean?
```

**GOOD** — keyword arguments make intent clear:
```python
await pricing.get_historical_bars(
    pair="EURUSD",
    duration="1 D",
    bar_size="5 mins",
    what_to_show="MIDPOINT",
)
```

---

Review the current changes against all of the above. For each violation found: quote the offending code, explain why it's a problem, and provide the corrected version.
