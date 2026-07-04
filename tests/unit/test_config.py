"""Unit tests for configuration loading."""

from forex_bot.config import load_settings, BrokerConfig, RiskConfig, StrategyConfig


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


def test_straddle_pair_overrides():
    config = StrategyConfig(
        straddle_distance_pips=15,
        straddle_tp_pips=40,
        straddle_sl_pips=10,
        straddle_pair_overrides={
            "GBPJPY": {"distance_pips": 45, "tp_pips": 35, "sl_pips": 10},
            "USDZAR": {"distance_pips": 10, "tp_pips": 70, "sl_pips": 10},
        },
    )
    # Override pair
    d, tp, sl = config.get_straddle_params("GBPJPY")
    assert d == 45
    assert tp == 35
    assert sl == 10

    # Another override
    d, tp, sl = config.get_straddle_params("USDZAR")
    assert d == 10
    assert tp == 70

    # Non-override pair falls back to defaults
    d, tp, sl = config.get_straddle_params("EURUSD")
    assert d == 15
    assert tp == 40
    assert sl == 10


def test_straddle_pair_overrides_loaded_from_yaml():
    settings = load_settings()
    overrides = settings.strategy.straddle_pair_overrides
    assert "USDZAR" in overrides
    assert overrides["USDZAR"].distance_pips == 50
    assert overrides["USDZAR"].tp_pips == 70
    assert overrides["USDZAR"].sl_pips == 10
    assert "USDJPY" in overrides
    assert overrides["USDJPY"].distance_pips == 25
    assert overrides["USDJPY"].tp_pips == 15


def test_event_overrides():
    """USDTRY uses 50/70/10 for US events but 20/60/10 for TCMB."""
    config = StrategyConfig(
        straddle_pair_overrides={
            "USDTRY": {
                "distance_pips": 50,
                "tp_pips": 70,
                "sl_pips": 10,
                "event_overrides": {
                    "TCMB Interest Rate Decision": {
                        "distance_pips": 20, "tp_pips": 60, "sl_pips": 10,
                    },
                },
            },
        },
    )
    # US event — uses pair-level defaults
    d, tp, sl = config.get_straddle_params("USDTRY", "Non-Farm Employment Change")
    assert (d, tp, sl) == (50, 70, 10)

    # TCMB event — exact title match uses the event override
    d, tp, sl = config.get_straddle_params("USDTRY", "TCMB Interest Rate Decision")
    assert (d, tp, sl) == (20, 60, 10)

    # Alias resolution: an aliased title matches via event_names
    d, tp, sl = config.get_straddle_params(
        "USDTRY",
        "One-Week Repo Rate",
        event_names=["TCMB Interest Rate Decision", "TCMB Rate", "One-Week Repo Rate"],
    )
    assert (d, tp, sl) == (20, 60, 10)

    # Substring must NOT match — "CPI m/m" key vs "Trimmed Mean CPI m/m" title
    config2 = StrategyConfig(
        straddle_pair_overrides={
            "AUDUSD": {
                "distance_pips": 40,
                "tp_pips": 70,
                "sl_pips": 30,
                "event_overrides": {
                    "CPI m/m": {"distance_pips": 40, "tp_pips": 15, "sl_pips": 25},
                },
            },
        },
    )
    d, tp, sl = config2.get_straddle_params("AUDUSD", "Trimmed Mean CPI m/m")
    assert (d, tp, sl) == (40, 70, 30)  # AU params, NOT the US override

    # No event title — uses pair-level defaults
    d, tp, sl = config.get_straddle_params("USDTRY")
    assert (d, tp, sl) == (50, 70, 10)


def test_event_overrides_loaded_from_yaml():
    settings = load_settings()
    usdtry = settings.strategy.straddle_pair_overrides["USDTRY"]
    key = "TCMB Interest Rate Decision"
    assert key in usdtry.event_overrides
    assert usdtry.event_overrides[key].distance_pips == 20
    assert usdtry.event_overrides[key].tp_pips == 60
    assert usdtry.event_overrides[key].sl_pips == 10


def test_resolve_event_names_and_audusd_override_keys():
    """Every AUDUSD/USDTRY event_overrides key must resolve from a real FF
    title — a key that matches nothing is silently dead config."""
    settings = load_settings()

    # NFP title resolves to names containing the 'NFP' alias
    names = settings.resolve_event_names("Non-Farm Employment Change", "USD")
    assert "NFP" in names

    # Every configured override key must be reachable via some target's names
    all_names = {
        n.lower().strip()
        for t in settings.events.target_events
        for n in [t.name, *t.aliases]
    }
    for pair, override in settings.strategy.straddle_pair_overrides.items():
        for key in override.event_overrides:
            assert key.lower().strip() in all_names, (
                f"{pair} override key '{key}' matches no event target "
                f"name/alias — it would never apply"
            )


def test_events_config_loaded():
    settings = load_settings()
    assert len(settings.events.target_events) > 0
    nfp = next((e for e in settings.events.target_events if "Non-Farm" in e.name), None)
    assert nfp is not None
    assert nfp.fred_series == "PAYEMS"
