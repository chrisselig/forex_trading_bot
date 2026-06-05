"""Unit tests for configuration loading."""

from forex_bot.config import load_settings, BrokerConfig, RiskConfig


def test_loads_settings_from_yaml():
    settings = load_settings()
    assert settings.broker.port in (4001, 4002, 7496, 7497)
    assert len(settings.trading.instruments) > 0


def test_broker_defaults():
    config = BrokerConfig()
    assert config.host == "127.0.0.1"
    assert config.port == 4002
    assert config.client_id == 1


def test_risk_defaults():
    config = RiskConfig()
    assert config.max_risk_per_trade_pct == 1.0
    assert config.mandatory_stop_loss is True


def test_events_config_loaded():
    settings = load_settings()
    assert len(settings.events.target_events) > 0
    nfp = next((e for e in settings.events.target_events if "Non-Farm" in e.name), None)
    assert nfp is not None
    assert nfp.fred_series == "PAYEMS"
