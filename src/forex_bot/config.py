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
    port: int = 4002
    client_id: int = 1
    timeout: int = 30

    @property
    def account_type(self) -> str:
        """Derive account type from port: 4002/7497 = paper, 4001/7496 = live."""
        return "paper" if self.port in (4002, 7497) else "live"


class TradingConfig(BaseModel):
    instruments: list[str] = Field(default_factory=lambda: ["USDZAR", "USDTRY", "GBPJPY", "GBPUSD", "USDCAD"])
    default_timeframe: str = "5 mins"


class RiskConfig(BaseModel):
    max_risk_per_trade_pct: float = 1.0
    max_daily_drawdown_pct: float = 3.0
    max_concurrent_positions: int = 3
    mandatory_stop_loss: bool = True
    max_spread_pips: float = 3.0
    max_spread_overrides: dict[str, float] = {}


class StraddleParams(BaseModel):
    distance_pips: float
    tp_pips: float
    sl_pips: float


class StraddlePairOverride(StraddleParams):
    event_overrides: dict[str, StraddleParams] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    pre_event_minutes: int = 30
    post_event_minutes: int = 60
    # Minimum lead time (seconds) before an event to still place a pre-event
    # straddle. On a late start (bot restart inside the pre-event window) the
    # straddle is placed as a catch-up as long as at least this much lead
    # remains; below it, placement is skipped and a "missed" alert is sent.
    min_pre_event_lead_seconds: int = 90
    straddle_distance_pips: float = 20.0
    straddle_tp_pips: float = 30.0
    straddle_sl_pips: float = 15.0
    straddle_pair_overrides: dict[str, StraddlePairOverride] = Field(default_factory=dict)
    surprise_threshold_pct: float = 10.0
    surprise_entry_delay_seconds: int = 5
    surprise_tp_pips: float = 25.0
    surprise_sl_pips: float = 15.0
    max_holding_minutes: int = 120

    def get_straddle_params(
        self, instrument: str, event_title: str = ""
    ) -> tuple[float, float, float]:
        """Return (distance, tp, sl) in pips for the given instrument and event.

        Checks event_overrides first (substring match on event title),
        then falls back to the pair-level override, then global defaults.
        """
        override = self.straddle_pair_overrides.get(instrument)
        if override:
            if event_title and override.event_overrides:
                title_lower = event_title.lower()
                for key, params in override.event_overrides.items():
                    if key.lower() in title_lower:
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
    min_differential_pct: float = 2.0
    risk_budget_pct: float = 5.0
    max_concurrent_carry: int = 5
    max_risk_per_carry_pct: float = 1.5
    stop_loss_pct: float = 5.0
    rebalance_day_of_week: str = "sun"  # Day of week (mon-sun)
    rebalance_hour_utc: int = 14  # 8 AM MT
    fallback_rates: dict[str, float] = Field(default_factory=lambda: {"TRY": 50.0})
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

    fred_api_key: str = ""
    ib_host: str = ""
    ib_port: int = 0
    ib_client_id: int = 0
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    turso_database_url: str = ""
    turso_auth_token: str = ""

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "env_file_encoding": "utf-8", "extra": "ignore"}

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
