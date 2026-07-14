from __future__ import annotations

import math

from loguru import logger

from forex_bot.config import get_settings
from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import get_pip_size
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.market import PriceSnapshot
from forex_bot.risk.rules import (
    RiskRule,
    MaxRiskPerTrade,
    MaxDailyDrawdown,
    MaxConcurrentPositions,
    MandatoryStopLoss,
    MaxOrderSize,
    MaxSpread,
    PositiveQuantity,
)
from forex_bot.risk.circuit_breaker import CircuitBreaker
from forex_bot.strategy.signals import Signal


class RiskManager:
    """Validates all trades against risk rules. No bypass possible."""

    def __init__(self, client: IBClient, circuit_breaker: CircuitBreaker, journal: TradeJournal):
        self._client = client
        self._circuit_breaker = circuit_breaker
        self._journal = journal
        settings = get_settings()

        if not settings.risk.mandatory_stop_loss:
            # The mandatory-stop-loss invariant is NON-NEGOTIABLE for this
            # bot. The toggle exists only for backtest tooling — make any
            # live use of it impossible to miss.
            logger.critical(
                "risk.mandatory_stop_loss is DISABLED in settings.yaml — "
                "orders without stop losses will pass risk validation. "
                "This violates a non-negotiable project invariant."
            )

        # Straddle rules (existing behavior)
        self._straddle_rules: list[RiskRule] = [
            MandatoryStopLoss() if settings.risk.mandatory_stop_loss else None,
            PositiveQuantity(),
            MaxOrderSize(settings.risk.max_order_units),
            MaxRiskPerTrade(settings.risk.max_risk_per_trade_pct),
            MaxDailyDrawdown(settings.risk.max_daily_drawdown_pct),
            MaxConcurrentPositions(settings.risk.max_concurrent_positions),
            MaxSpread(settings.risk.max_spread_pips, settings.risk.max_spread_overrides),
        ]
        self._straddle_rules = [r for r in self._straddle_rules if r is not None]

        # Carry rules (wider limits, separate position count)
        carry = settings.carry
        self._carry_rules: list[RiskRule] = [
            MandatoryStopLoss(),
            PositiveQuantity(),
            MaxOrderSize(settings.risk.max_order_units),
            MaxRiskPerTrade(carry.max_risk_per_carry_pct),
            MaxDailyDrawdown(settings.risk.max_daily_drawdown_pct),
            MaxConcurrentPositions(carry.max_concurrent_carry),
            MaxSpread(carry.max_spread_pips, carry.max_spread_overrides),
        ]

        # Value / PPP rules (own limits, separate position count)
        value = settings.value
        self._value_rules: list[RiskRule] = [
            MandatoryStopLoss(),
            PositiveQuantity(),
            MaxOrderSize(settings.risk.max_order_units),
            MaxRiskPerTrade(value.max_risk_per_value_pct),
            MaxDailyDrawdown(settings.risk.max_daily_drawdown_pct),
            MaxConcurrentPositions(value.max_concurrent_value),
            MaxSpread(value.max_spread_pips, value.max_spread_overrides),
        ]

    async def validate(
        self, signal: Signal, price: PriceSnapshot | None = None, quote_to_cad: float = 1.0,
    ) -> list[str]:
        """Validate a signal against all risk rules. Returns list of violations."""
        # Check circuit breaker first
        cb_error = self._circuit_breaker.check()
        if cb_error:
            return [cb_error]

        account = await self._client.get_account_summary()
        daily_pnl = await self._journal.get_daily_pnl()

        # Strategy-aware position counting and rule selection
        if signal.strategy == "carry":
            rules = self._carry_rules
            open_count = await self._journal.count_open_by_strategy("carry")
        elif signal.strategy == "value":
            rules = self._value_rules
            open_count = await self._journal.count_open_by_strategy("value")
        else:
            rules = self._straddle_rules
            positions = await self._client.get_positions()
            open_count = len(positions)

        violations = []
        for rule in rules:
            error = rule.validate(
                signal=signal,
                account=account,
                price=price,
                open_position_count=open_count,
                daily_pnl=daily_pnl,
                quote_to_cad=quote_to_cad,
            )
            if error:
                violations.append(error)

        if violations:
            logger.warning(f"Risk violations for {signal.instrument}: {violations}")
        else:
            logger.debug(f"Risk check passed for {signal.instrument}")

        return violations

    def calculate_position_size(
        self,
        account_balance: float,
        stop_loss_pips: float,
        pair: str,
        risk_pct: float | None = None,
        quote_to_cad: float = 1.0,
    ) -> float:
        """Calculate position size based on risk percentage and stop loss distance.

        Formula: units = (balance * risk%) / (sl_pips * pip_size * quote_to_cad)

        The quote_to_cad conversion factor converts the pip value from quote
        currency to account currency (CAD). Without it, pairs like USDTRY
        (quote=TRY) are massively undersized because pip_size alone doesn't
        reflect the TRY→CAD exchange rate.
        """
        if risk_pct is None:
            risk_pct = get_settings().risk.max_risk_per_trade_pct

        if stop_loss_pips <= 0 or quote_to_cad <= 0:
            raise ValueError(
                f"Cannot size position for {pair}: stop_loss_pips="
                f"{stop_loss_pips}, quote_to_cad={quote_to_cad} "
                f"(both must be positive)"
            )

        pip_size = get_pip_size(pair)
        risk_amount = account_balance * (risk_pct / 100)
        units = risk_amount / (stop_loss_pips * pip_size * quote_to_cad)
        # Floor to a whole mini lot (1000 units). Flooring — not rounding to the
        # nearest — guarantees the sized position never exceeds the risk budget.
        # Rounding up could push the position's risk a fraction of a cent over
        # the limit and trip the strict `>` check in MaxRiskPerTrade, which
        # silently rejected every such trade (e.g. USDTRY straddles: computed
        # risk $246.92 vs $246.91 cap).
        units = math.floor(units / 1000) * 1000
        return max(units, 1000)  # Minimum 1 micro lot (1000 units)
