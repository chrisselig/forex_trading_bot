from __future__ import annotations

import os
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


class TradingConfig(BaseModel):
    instruments: list[str] = Field(default_factory=lambda: ["USDZAR", "USDTRY", "GBPJPY", "GBPUSD", "USDCAD"])
    default_timeframe: str = "5 mins"


class RiskConfig(BaseModel):
    max_risk_per_trade_pct: float = 1.0
    max_daily_drawdown_pct: float = 3.0
    max_concurrent_positions: int = 3
    mandatory_stop_loss: bool = True
    max_spread_pips: float = 3.0


class StraddlePairOverride(BaseModel):
    distance_pips: float
    tp_pips: float
    sl_pips: float


class StrategyConfig(BaseModel):
    pre_event_minutes: int = 30
    post_event_minutes: int = 60
    straddle_distance_pips: float = 20.0
    straddle_tp_pips: float = 30.0
    straddle_sl_pips: float = 15.0
    straddle_pair_overrides: dict[str, StraddlePairOverride] = Field(default_factory=dict)
    surprise_threshold_pct: float = 10.0
    surprise_entry_delay_seconds: int = 5
    surprise_tp_pips: float = 25.0
    surprise_sl_pips: float = 15.0
    max_holding_minutes: int = 120

    def get_straddle_params(self, instrument: str) -> tuple[float, float, float]:
        """Return (distance, tp, sl) in pips for the given instrument."""
        override = self.straddle_pair_overrides.get(instrument)
        if override:
            return override.distance_pips, override.tp_pips, override.sl_pips
        return self.straddle_distance_pips, self.straddle_tp_pips, self.straddle_sl_pips


class EventTarget(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    fred_series: str = ""
    pairs: list[str] = Field(default_factory=list)
    impact: str = "high"


class EventFilters(BaseModel):
    country: str = "USD"
    min_impact: str = "high"


class EventsConfig(BaseModel):
    target_events: list[EventTarget] = Field(default_factory=list)
    filters: EventFilters = Field(default_factory=EventFilters)


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


class TelegramConfig(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = True


class Settings(BaseSettings):
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    fred_api_key: str = ""
    ib_host: str = ""
    ib_port: int = 0
    ib_client_id: int = 0
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

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


def load_settings() -> Settings:
    settings_data = _load_yaml(CONFIG_DIR / "settings.yaml")
    events_data = _load_yaml(CONFIG_DIR / "events.yaml")
    settings_data["events"] = events_data
    return Settings(**settings_data)


@lru_cache
def get_settings() -> Settings:
    return load_settings()
