from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class BrokerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(4002, ge=1, le=65535)
    client_id: int = Field(1, ge=0)
    timeout: int = Field(30, gt=0)

    @property
    def account_type(self) -> str:
        """Derive account type from port: 4002/7497 = paper, 4001/7496 = live."""
        return "paper" if self.port in (4002, 7497) else "live"


class TradingConfig(BaseModel):
    # Fallback if settings.yaml is missing the trading key. Only pairs the
    # current MC analysis approves — never add walk-forward failures here.
    instruments: list[str] = Field(default_factory=lambda: ["USDZAR", "USDTRY"])
    default_timeframe: str = "5 mins"


class RiskConfig(BaseModel):
    # Bounds reject config typos (negative risk, 0-pip spreads) at startup
    # instead of corrupting position sizing at trade time.
    max_risk_per_trade_pct: float = Field(1.0, gt=0, le=10)
    max_daily_drawdown_pct: float = Field(3.0, gt=0, le=50)
    max_concurrent_positions: int = Field(3, ge=1)
    mandatory_stop_loss: bool = True
    max_spread_pips: float = Field(3.0, gt=0)
    max_spread_overrides: dict[str, float] = Field(default_factory=dict)


class StraddleParams(BaseModel):
    distance_pips: float = Field(gt=0)
    tp_pips: float = Field(gt=0)
    sl_pips: float = Field(gt=0)


class StraddlePairOverride(StraddleParams):
    event_overrides: dict[str, StraddleParams] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    pre_event_minutes: int = 30
    post_event_minutes: int = 60
    # Minimum lead time (seconds) before an event to still place a pre-event
    # straddle. On a late start (bot restart inside the pre-event window) the
    # straddle is placed as a catch-up as long as at least this much lead
    # remains; below it, placement is skipped and a "missed" alert is sent.
    min_pre_event_lead_seconds: int = Field(90, ge=0)
    straddle_distance_pips: float = Field(20.0, gt=0)
    straddle_tp_pips: float = Field(30.0, gt=0)
    straddle_sl_pips: float = Field(15.0, gt=0)
    straddle_pair_overrides: dict[str, StraddlePairOverride] = Field(default_factory=dict)
    surprise_threshold_pct: float = Field(10.0, gt=0)
    surprise_entry_delay_seconds: int = Field(5, ge=0)
    surprise_tp_pips: float = Field(25.0, gt=0)
    surprise_sl_pips: float = Field(15.0, gt=0)
    max_holding_minutes: int = Field(120, gt=0)

    def get_straddle_params(
        self,
        instrument: str,
        event_title: str = "",
        event_names: list[str] | None = None,
    ) -> tuple[float, float, float]:
        """Return (distance, tp, sl) in pips for the given instrument and event.

        Checks event_overrides first, then the pair-level override, then
        global defaults. Override keys match by case-insensitive EXACT
        equality against the event's canonical names (title, or the
        resolved target name + aliases via Settings.resolve_event_names) —
        substring matching applied US params to same-substring foreign
        events ("CPI m/m" matched "Trimmed Mean CPI m/m") and silently
        never matched abbreviations ("NFP" is not a substring of
        "Non-Farm Employment Change").
        """
        override = self.straddle_pair_overrides.get(instrument)
        if override:
            if override.event_overrides and (event_title or event_names):
                candidates = {
                    n.lower().strip() for n in (event_names or [event_title]) if n
                }
                for key, params in override.event_overrides.items():
                    if key.lower().strip() in candidates:
                        return params.distance_pips, params.tp_pips, params.sl_pips
            return override.distance_pips, override.tp_pips, override.sl_pips
        return self.straddle_distance_pips, self.straddle_tp_pips, self.straddle_sl_pips


class EventTarget(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    fred_series: str = ""
    pairs: list[str] = Field(default_factory=list)
    impact: str = "high"
    country: str = ""  # If set, only match events from this country


class EventFilters(BaseModel):
    country: str | list[str] = "USD"
    min_impact: str = "high"


class EventsConfig(BaseModel):
    target_events: list[EventTarget] = Field(default_factory=list)
    filters: EventFilters = Field(default_factory=EventFilters)


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


class CarryConfig(BaseModel):
    enabled: bool = False
    instruments: list[str] = Field(
        default_factory=lambda: ["USDZAR", "USDTRY", "USDMXN", "AUDJPY", "NZDJPY"],
    )
    min_differential_pct: float = Field(2.0, gt=0)
    risk_budget_pct: float = Field(5.0, gt=0, le=20)
    max_concurrent_carry: int = Field(5, ge=1)
    max_risk_per_carry_pct: float = Field(1.5, gt=0, le=10)
    stop_loss_pct: float = Field(5.0, gt=0)
    # Rebalance on Monday morning (UTC) when TWS is up and FX is liquid.
    # Weekend/Sunday-morning windows are unusable: TWS is not started until the
    # Sunday afternoon cron and FX spreads are wide at the Sunday open.
    rebalance_day_of_week: str = "mon"  # Day of week (mon-sun)
    rebalance_hour_utc: int = 14  # 14:00 UTC = 8 AM MT / 10 AM ET (London-NY overlap)
    fallback_rates: dict[str, float] = Field(default_factory=lambda: {"TRY": 50.0})
    max_spread_pips: float = 30.0
    max_spread_overrides: dict[str, float] = Field(default_factory=dict)


class MomentumConfig(BaseModel):
    """Time-series (absolute) currency momentum — trade each pair in the
    direction of its trailing return: long recent winners, short recent losers.

    UNVALIDATED: no Monte Carlo walk-forward analysis backs this strategy yet.
    Starts disabled; enable only for paper-trade evaluation.
    """

    enabled: bool = False
    instruments: list[str] = Field(
        default_factory=lambda: [
            "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDZAR", "USDTRY",
        ],
    )
    lookback_months: int = Field(3, ge=1, le=12)  # trailing-return window
    min_return_pct: float = Field(2.0, gt=0)  # min |trailing return| to trade
    max_concurrent_momentum: int = Field(4, ge=1)
    max_risk_per_momentum_pct: float = Field(1.0, gt=0, le=10)
    stop_loss_pct: float = Field(5.0, gt=0)
    # Rebalance weekly, AFTER the carry rebalance (carry fires at minute=7).
    rebalance_day_of_week: str = "mon"  # Day of week (mon-sun)
    rebalance_hour_utc: int = 14  # 14:00 UTC = 8 AM MT / 10 AM ET
    rebalance_minute: int = Field(22, ge=0, le=59)  # after carry (minute 7)
    max_spread_pips: float = 30.0
    max_spread_overrides: dict[str, float] = Field(default_factory=dict)


class TelegramConfig(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = True


class TursoConfig(BaseModel):
    database_url: str = ""
    auth_token: str = ""
    enabled: bool = True


class Settings(BaseSettings):
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    turso: TursoConfig = Field(default_factory=TursoConfig)
    carry: CarryConfig = Field(default_factory=CarryConfig)
    momentum: MomentumConfig = Field(default_factory=MomentumConfig)

    fred_api_key: str = ""
    ib_host: str = ""
    ib_port: int = 0
    ib_client_id: int = 0
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    turso_database_url: str = ""
    turso_auth_token: str = ""

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "env_file_encoding": "utf-8", "extra": "ignore"}

    def resolve_event_names(self, event_title: str, country: str = "") -> list[str]:
        """Return the canonical name + aliases of the event target whose
        name or aliases exactly match this title (case-insensitive).

        Falls back to [event_title] when no target matches, so callers can
        pass the result straight to get_straddle_params.
        """
        title = event_title.lower().strip()
        for target in self.events.target_events:
            if country and target.country and target.country != country:
                continue
            names = [target.name, *target.aliases]
            if any(title == n.lower().strip() for n in names):
                return names
        return [event_title]

    def model_post_init(self, __context: Any) -> None:
        if self.ib_host:
            self.broker.host = self.ib_host
        if self.ib_port:
            self.broker.port = self.ib_port
        if self.ib_client_id:
            self.broker.client_id = self.ib_client_id
        if self.telegram_bot_token:
            self.telegram.bot_token = self.telegram_bot_token
        if self.telegram_chat_id:
            self.telegram.chat_id = self.telegram_chat_id
        if self.turso_database_url:
            self.turso.database_url = self.turso_database_url
        if self.turso_auth_token:
            self.turso.auth_token = self.turso_auth_token


def load_settings() -> Settings:
    settings_data = _load_yaml(CONFIG_DIR / "settings.yaml")
    events_data = _load_yaml(CONFIG_DIR / "events.yaml")
    settings_data["events"] = events_data
    return Settings(**settings_data)


@lru_cache
def get_settings() -> Settings:
    return load_settings()
