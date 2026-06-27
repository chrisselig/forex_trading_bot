"""Historical event replay engine for backtesting."""

from __future__ import annotations

from datetime import datetime

from forex_bot.models.events import EconomicEvent
from forex_bot.models.market import PriceSnapshot, Candle
from forex_bot.strategy.base import BaseStrategy


class BacktestRunner:
    """Replays historical events against historical price data."""

    def __init__(self, strategy: BaseStrategy, initial_balance: float = 100000.0):
        self._strategy = strategy
        self._balance = initial_balance
        self._trades: list[dict] = []

    async def run(
        self,
        events: list[EconomicEvent],
        price_data: dict[str, list[Candle]],
    ) -> dict:
        """Run backtest over historical events and prices."""
        for event in events:
            for instrument, candles in price_data.items():
                # Find the candle closest to event time
                price_at_event = self._find_price_at_time(candles, event.scheduled_at)
                if price_at_event is None:
                    continue

                snapshot = PriceSnapshot(
                    instrument=instrument,
                    timestamp=event.scheduled_at,
                    bid=price_at_event.close - 0.00010,
                    ask=price_at_event.close + 0.00010,
                )

                # Pre-event signals
                pre_signals = await self._strategy.evaluate_pre_event(event, snapshot)
                # Post-event signals
                post_signals = await self._strategy.evaluate_post_event(event, snapshot)

                for signal in pre_signals + post_signals:
                    self._trades.append({
                        "event": event.title,
                        "instrument": instrument,
                        "side": signal.side.value,
                        "price": signal.price or snapshot.mid,
                        "sl": signal.stop_loss,
                        "tp": signal.take_profit,
                        "time": event.scheduled_at,
                    })

        return {
            "total_trades": len(self._trades),
            "strategy": self._strategy.name,
            "trades": self._trades,
        }

    @staticmethod
    def _find_price_at_time(candles: list[Candle], target: datetime) -> Candle | None:
        """Find the candle closest to a target time."""
        if not candles:
            return None
        closest = min(candles, key=lambda c: abs((c.timestamp - target).total_seconds()))
        return closest
