"""Nightly currency sweep — convert residual FX balances back to CAD.

When the bot trades USDZAR or USDTRY, IB settles in the traded currencies.
After a round-trip trade, residual USD/ZAR/TRY/JPY balances remain in the
account. This module sweeps them back to CAD via market orders on IdealPro.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from ib_async import Forex, MarketOrder

from forex_bot.broker.client import IBClient


# Minimum balance (in units of foreign currency) worth sweeping.
# Below this, the conversion cost isn't worth it.
MIN_SWEEP_THRESHOLD = 1.0

# Currencies we expect to see residuals in, mapped to the IB pair
# used to convert back to CAD. Action is BUY or SELL depending on
# whether CAD is base or quote in the pair.
#
# IB Forex pairs are always in a canonical order. To convert:
#   USD -> CAD: SELL USDCAD (sell USD, receive CAD)
#   ZAR -> CAD: BUY CADCHF won't work — no direct pair.
#
# For exotics without a direct CAD cross, we do a two-leg sweep:
#   ZAR -> USD (BUY USDZAR) then USD -> CAD (SELL USDCAD)
# But at our account size, the residual ZAR/TRY balances are tiny
# and a direct USDZAR conversion is simpler.
#
# IB IdealPro conversion pairs to CAD:
SWEEP_PAIRS: dict[str, tuple[str, str]] = {
    # currency -> (IB pair, action to sell that currency for CAD)
    "USD": ("USDCAD", "SELL"),   # Sell USD, buy CAD
    "JPY": ("CADJPY", "BUY"),    # Buy CAD, sell JPY
    "EUR": ("EURCAD", "SELL"),   # Sell EUR, buy CAD
    "GBP": ("GBPCAD", "SELL"),   # Sell GBP, buy CAD
    "AUD": ("AUDCAD", "SELL"),   # Sell AUD, buy CAD
}

# Exotics without direct CAD pairs — convert to USD first, then USD->CAD
EXOTIC_TO_USD: dict[str, tuple[str, str]] = {
    "ZAR": ("USDZAR", "BUY"),    # Buy USD, sell ZAR
    "TRY": ("USDTRY", "BUY"),    # Buy USD, sell TRY
}


async def get_cash_balances(client: IBClient) -> dict[str, float]:
    """Return non-CAD cash balances from IB account.

    Returns a dict of currency -> balance (e.g., {"USD": 12.50, "ZAR": -340.0}).
    Only includes currencies with abs(balance) >= MIN_SWEEP_THRESHOLD.
    """
    await client.ensure_connected()
    account_values = client.ib.accountValues()

    balances: dict[str, float] = {}
    for av in account_values:
        if av.tag == "CashBalance" and av.currency not in ("CAD", "BASE"):
            bal = float(av.value)
            if abs(bal) >= MIN_SWEEP_THRESHOLD:
                balances[av.currency] = bal

    return balances


async def sweep_to_cad(
    client: IBClient,
    dry_run: bool = False,
    exclude_currencies: set[str] | None = None,
) -> list[str]:
    """Convert all non-CAD cash balances back to CAD.

    Args:
        client: Connected IBClient.
        dry_run: If True, log what would happen but don't place orders.
        exclude_currencies: Currencies to skip (e.g., carry position currencies).

    Returns:
        List of summary strings for each conversion placed.
    """
    def apply_exclusions(bals: dict[str, float]) -> dict[str, float]:
        if not exclude_currencies:
            return bals
        for ccy in exclude_currencies:
            if ccy in bals:
                logger.info(f"Currency sweep: skipping {ccy} (excluded by carry)")
                del bals[ccy]
        return bals

    balances = apply_exclusions(await get_cash_balances(client))

    if not balances:
        logger.info("Currency sweep: no non-CAD balances to convert")
        return []

    logger.info(f"Currency sweep: found {len(balances)} non-CAD balance(s): {balances}")
    results: list[str] = []

    # First pass: convert exotics to USD
    usd_from_exotics = 0.0
    for currency, balance in list(balances.items()):
        if currency not in EXOTIC_TO_USD:
            continue

        pair_str, action = EXOTIC_TO_USD[currency]
        # For USDZAR BUY: we're buying USD with ZAR.
        # Quantity is in units of base currency (USD).
        # We need to estimate how much USD our ZAR balance buys.
        # Use a small fixed amount — IB will reject if insufficient.
        # At our account size, exotic residuals are tiny.
        abs_balance = abs(balance)

        msg = f"Sweep {currency} {balance:.2f} -> USD via {action} {pair_str}"
        if dry_run:
            logger.info(f"[DRY RUN] {msg}")
            results.append(f"[DRY RUN] {msg}")
            del balances[currency]
            continue

        try:
            contract = Forex(pair_str)
            await client.ib.qualifyContractsAsync(contract)

            # For exotic->USD, we need to figure out quantity in base (USD).
            # Request current price to calculate.
            tickers = await client.ib.reqTickersAsync(contract)
            if not tickers or not tickers[0].midpoint():
                logger.warning(f"Sweep: no price for {pair_str}, skipping {currency}")
                continue

            mid = tickers[0].midpoint()
            # balance is in exotic currency units
            # USDZAR mid ~18.0 means 1 USD = 18 ZAR
            # So ZAR balance / mid = USD equivalent
            usd_qty = abs_balance / mid
            # IB forex minimum is typically 1 unit, round to whole units
            usd_qty = max(1, round(usd_qty))

            # If balance is positive (we hold ZAR), we want to sell ZAR = BUY USDZAR
            # If balance is negative (we owe ZAR), we want to buy ZAR = SELL USDZAR
            actual_action = action if balance > 0 else ("SELL" if action == "BUY" else "BUY")

            order = MarketOrder(action=actual_action, totalQuantity=usd_qty)
            order.tif = "IOC"  # Immediate or cancel
            client.ib.placeOrder(contract, order)
            logger.info(f"Sweep: {actual_action} {usd_qty} {pair_str} (converting {currency} {balance:.2f})")
            results.append(msg)
            usd_from_exotics += usd_qty if actual_action == "BUY" else -usd_qty
            del balances[currency]

        except Exception as e:
            logger.error(f"Sweep failed for {currency}: {e}")

    # Second pass: convert majors (including any new USD from exotic conversion) to CAD
    # Wait briefly for exotic fills
    if usd_from_exotics != 0:
        await asyncio.sleep(2)
        # Refresh balances to pick up USD from exotic conversions.
        # Exclusions MUST be reapplied — the refreshed balances would
        # otherwise re-include carry-position currencies and the second
        # pass would market-sell a live carry hedge.
        balances = apply_exclusions(await get_cash_balances(client))

    for currency, balance in balances.items():
        if currency not in SWEEP_PAIRS:
            logger.warning(f"Sweep: no CAD pair for {currency} ({balance:.2f}), skipping")
            continue

        pair_str, action = SWEEP_PAIRS[currency]
        abs_balance = abs(balance)

        msg = f"Sweep {currency} {balance:.2f} -> CAD via {action} {pair_str}"
        if dry_run:
            logger.info(f"[DRY RUN] {msg}")
            results.append(f"[DRY RUN] {msg}")
            continue

        try:
            contract = Forex(pair_str)
            await client.ib.qualifyContractsAsync(contract)

            # Quantity is in base currency units
            # USDCAD: base=USD, so qty = USD amount
            # CADJPY: base=CAD, need to convert JPY->CAD qty
            base = pair_str[:3]
            if base == currency:
                qty = round(abs_balance)
            else:
                # Currency is quote side — need price to convert
                tickers = await client.ib.reqTickersAsync(contract)
                if tickers and tickers[0].midpoint():
                    mid = tickers[0].midpoint()
                    qty = round(abs_balance / mid)
                else:
                    logger.warning(f"Sweep: no price for {pair_str}, skipping {currency}")
                    continue

            qty = max(1, qty)

            # Flip action if balance is negative (we owe the currency)
            actual_action = action if balance > 0 else ("SELL" if action == "BUY" else "BUY")

            order = MarketOrder(action=actual_action, totalQuantity=qty)
            order.tif = "IOC"
            client.ib.placeOrder(contract, order)
            logger.info(f"Sweep: {actual_action} {qty} {pair_str} (converting {currency} {balance:.2f} to CAD)")
            results.append(msg)

        except Exception as e:
            logger.error(f"Sweep failed for {currency}: {e}")

    if not results:
        logger.info("Currency sweep: nothing to convert")

    return results
