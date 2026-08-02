from __future__ import annotations

import statistics
from datetime import datetime

import httpx
from loguru import logger

from forex_bot.models.cot import CotCrowdingReading

# CFTC Traders in Financial Futures (Futures Only) report, Socrata dataset
# gpe5-46if. Public, no auth required for this request volume (carry
# rebalances weekly and fetches at most a handful of currencies).
TFF_ENDPOINT = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

# cftc_contract_market_code per currency's CME future, verified against the
# live dataset. Not every carry-universe currency is listed: TRY and NZD have
# no CME future in this report at all (too illiquid to require CFTC
# reporting), so crowding can never be computed for them — callers must treat
# an absent currency as "no signal available", never as "not crowded".
CFTC_CONTRACT_CODES: dict[str, str] = {
    "JPY": "097741",
    "AUD": "232741",
    "ZAR": "122741",
    "MXN": "095741",
}

# Below this many usable weekly observations, a z-score is noise, not signal.
MIN_WEEKS_FOR_ZSCORE = 52


class CotClient:
    """Fetches CFTC Commitments of Traders data and scores speculative
    crowding per currency.

    Used as carry's crash-risk filter: when leveraged funds already hold an
    extreme net position (long or short, relative to their own trailing
    history) in a currency future, that trade is crowded — vulnerable to a
    fast, disorderly unwind once it reverses (the mechanism behind carry
    blowups like the Aug 2024 JPY unwind). Adding a new carry position that
    deepens the same crowd increases exposure to exactly that risk.
    """

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout

    async def get_crowding(
        self, currency: str, lookback_weeks: int = 156,
    ) -> CotCrowdingReading | None:
        """Latest crowding z-score for a currency, or None if unavailable.

        None covers three distinct cases (all handled identically by
        design — callers fail open on any of them): the currency has no
        CFTC-listed future, the API request failed, or there isn't enough
        history yet to standardize against.
        """
        code = CFTC_CONTRACT_CODES.get(currency)
        if code is None:
            logger.debug(f"COT: no CFTC-listed future for {currency}, skipping crowding check")
            return None

        params = {
            "$where": f"cftc_contract_market_code='{code}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$select": (
                "report_date_as_yyyy_mm_dd,lev_money_positions_long,"
                "lev_money_positions_short,open_interest_all"
            ),
            "$limit": str(lookback_weeks),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                resp = await http.get(TFF_ENDPOINT, params=params)
                resp.raise_for_status()
                rows = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"COT: fetch failed for {currency}: {e}")
            return None

        net_pct_series: list[float] = []
        latest_date: datetime | None = None
        for row in rows:
            try:
                oi = float(row["open_interest_all"])
                if oi <= 0:
                    continue
                long = float(row["lev_money_positions_long"])
                short = float(row["lev_money_positions_short"])
            except (KeyError, TypeError, ValueError):
                continue
            net_pct_series.append((long - short) / oi)
            if latest_date is None:
                latest_date = datetime.fromisoformat(row["report_date_as_yyyy_mm_dd"])

        if len(net_pct_series) < MIN_WEEKS_FOR_ZSCORE:
            logger.warning(
                f"COT: only {len(net_pct_series)} usable weeks for {currency} "
                f"(need {MIN_WEEKS_FOR_ZSCORE}) — skipping crowding check"
            )
            return None

        latest = net_pct_series[0]
        mean = statistics.fmean(net_pct_series)
        stdev = statistics.pstdev(net_pct_series)
        if stdev == 0:
            logger.warning(f"COT: zero variance in {currency} net positioning history — skipping")
            return None

        return CotCrowdingReading(
            currency=currency,
            report_date=latest_date,
            net_pct_oi=latest,
            z_score=(latest - mean) / stdev,
            n_weeks=len(net_pct_series),
        )
