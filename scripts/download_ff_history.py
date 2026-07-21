#!/usr/bin/env python3
"""
Forex Factory Historical Forecast/Actual Acquisition (Spec 15, Phase 2a)
==========================================================================

Downloads historical forecast/actual/previous values for the US economic
events targeted by ``src/forex_bot/strategy/surprise.py`` /
``config/events.yaml``, covering 2020-01-01 through 2026-06-30.

Data sources
------------
Forex Factory itself (``forexfactory.com/calendar?week=...``) returns HTTP
403 (Cloudflare challenge) for every request from this environment -- both
the live site and the "fallback" Investing.com economic calendar do the
same (verified at development time). Headless-browser/JS-challenge solving
is not available in this environment, so neither of the two sources named
in the spec is directly scrapable here.

Two Forex-Factory-derived sources ARE reachable and are used instead:

1. **Primary (2020-01-01 .. ~2025-04-07)**: the ``Ehsanrs2/Forex_Factory_
   Calendar`` dataset on Hugging Face -- a third-party historical scrape of
   forexfactory.com (2007-2025-04-07, actual/forecast/previous columns,
   MIT-licensed, "for educational/research purposes"). Hugging Face's CDN
   is not Cloudflare-protected in this environment.
2. **Gap-fill (~2025-04-08 .. 2026-06-30)**: the Wayback Machine's archived
   snapshots of forexfactory.com pages (archive.org is not Cloudflare-
   protected either). Two archived FF page types are used:
     a. Per-indicator "History" pages (``/calendar/<id>-<slug>``), which
        render a static HTML table of the trailing ~8 releases for that
        indicator (actual/forecast/previous per date).
     b. The default ``/calendar`` (current week) page, which embeds a JSON
        payload per event (incl. a Unix ``dateline`` timestamp) for the
        crawl-time "current" week. Used as a supplement to fill dates the
        indicator-history pages don't reach (notably GDP, where no
        indicator-page snapshots exist after Jan 2025).

Both wayback sources are throttled to >=2s between requests and cached to
disk (``scripts/data/_cache/ff_history/``) so re-running this script is
resume-safe -- already-fetched CDX listings and pages are read from cache
and never re-requested.

Output: ``scripts/data/ff_history.csv`` with columns
``title,country,scheduled_utc,forecast,actual,previous`` (raw strings as
published, e.g. "200K", "3.4%"). Timestamps are UTC (naive ISO 8601).

Usage:
  ~/anaconda3/envs/forex-bot/bin/python scripts/download_ff_history.py
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from loguru import logger

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
CACHE_DIR = DATA_DIR / "_cache" / "ff_history"
WAYBACK_HTML_CACHE = CACHE_DIR / "wayback_html"
CDX_CACHE = CACHE_DIR / "cdx"
for _d in (DATA_DIR, CACHE_DIR, WAYBACK_HTML_CACHE, CDX_CACHE):
    _d.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV = DATA_DIR / "ff_history.csv"
HF_CACHE_CSV = CACHE_DIR / "hf_forex_factory_cache.csv"

START_DATE = date(2020, 1, 1)
END_DATE = date(2026, 6, 30)

RATE_LIMIT_SECONDS = 2.0  # >=2s between any web.archive.org / huggingface request
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 3.0

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

HF_DATASET_CSV_URL = (
    "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar/"
    "resolve/main/forex_factory_cache.csv"
)

FF_CALENDAR_BASE = "https://www.forexfactory.com/calendar"

# ---------------------------------------------------------------------------
# Target event registry
# ---------------------------------------------------------------------------
# `title` matches the canonical names/aliases in config/events.yaml exactly
# (Core CPI m/m has no dedicated target in events.yaml -- production trades
# "CPI m/m" only -- but the spec asks for "headline + core if available" so
# it is fetched too, for the secondary/informational analysis).
# `et_time` is the standard BLS/BEA/Fed release time (Eastern), used to
# reconstruct scheduled_utc precisely regardless of what time-of-day (if
# any) a given source row carries.

EVENTS: dict[str, dict] = {
    "Non-Farm Employment Change": {"ebase_id": 66, "slug": "66-us-non-farm-employment-change", "et_time": (8, 30), "hf_name": "Non-Farm Employment Change"},
    "CPI m/m": {"ebase_id": 78, "slug": "78-us-cpi-mm", "et_time": (8, 30), "hf_name": "CPI m/m"},
    "Core CPI m/m": {"ebase_id": 79, "slug": "79-us-core-cpi-mm", "et_time": (8, 30), "hf_name": "Core CPI m/m"},
    "Federal Funds Rate": {"ebase_id": 1, "slug": "1-us-federal-funds-rate", "et_time": (14, 0), "hf_name": "Federal Funds Rate"},
    "PPI m/m": {"ebase_id": 86, "slug": "86-us-ppi-mm", "et_time": (8, 30), "hf_name": "PPI m/m"},
    "Advance GDP q/q": {"ebase_id": 2, "slug": "2-us-advance-gdp-qq", "et_time": (8, 30), "hf_name": "Advance GDP q/q"},
    # Prelim/Final GDP vintages: production events.yaml's "GDP q/q" target
    # aliases all three vintages, and monte_carlo_dukascopy.py's GDP date
    # list includes all vintages -- so all three are fetched.
    "Prelim GDP q/q": {"ebase_id": 27, "slug": "27-us-prelim-gdp-qq", "et_time": (8, 30), "hf_name": "Prelim GDP q/q"},
    "Final GDP q/q": {"ebase_id": 28, "slug": "28-us-final-gdp-qq", "et_time": (8, 30), "hf_name": "Final GDP q/q"},
    "Core PCE Price Index m/m": {"ebase_id": 85, "slug": "85-us-core-pce-price-index-mm", "et_time": (8, 30), "hf_name": "Core PCE Price Index m/m"},
    "Unemployment Claims": {"ebase_id": 11, "slug": "11-us-unemployment-claims", "et_time": (8, 30), "hf_name": "Unemployment Claims"},
    "ISM Manufacturing PMI": {"ebase_id": 252, "slug": "252-us-ism-manufacturing-pmi", "et_time": (10, 0), "hf_name": "ISM Manufacturing PMI"},
    "Retail Sales m/m": {"ebase_id": 102, "slug": "102-us-retail-sales-mm", "et_time": (8, 30), "hf_name": "Retail Sales m/m"},
}
EBASE_TO_TITLE = {meta["ebase_id"]: title for title, meta in EVENTS.items()}


@dataclass
class Row:
    title: str
    country: str
    scheduled_utc: datetime  # naive UTC
    forecast: str | None
    actual: str | None
    previous: str | None
    source: str


# ---------------------------------------------------------------------------
# Throttled HTTP helper (shared by all web.archive.org / huggingface calls)
# ---------------------------------------------------------------------------

_last_request_time = 0.0


def _throttle() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.monotonic()


def fetch_text(url: str, *, params: dict | None = None, cache_path: Path | None = None) -> str | None:
    """Fetch a URL's text content, using an on-disk cache when available.

    Resume-safe: if `cache_path` already exists, no network request is made.
    Retries with exponential backoff on transient errors (503/timeout),
    respecting a >=2s delay between live requests.
    """
    if cache_path is not None and cache_path.exists():
        return cache_path.read_text()

    headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
                resp = client.get(url, params=params)
            if resp.status_code == 200:
                if cache_path is not None:
                    cache_path.write_text(resp.text)
                return resp.text
            logger.warning(f"GET {url} -> {resp.status_code} (attempt {attempt + 1}/{MAX_RETRIES})")
        except (httpx.TimeoutException, httpx.TransportError) as e:
            logger.warning(f"GET {url} -> {e!r} (attempt {attempt + 1}/{MAX_RETRIES})")
        time.sleep(RETRY_BACKOFF_BASE * (attempt + 1))
    logger.error(f"Giving up on {url} after {MAX_RETRIES} attempts")
    return None


def fetch_binary(url: str, cache_path: Path) -> bool:
    """Download a (potentially large) file to `cache_path`. Resume-safe."""
    if cache_path.exists():
        return True
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            with httpx.stream("GET", url, headers=headers, timeout=120.0, follow_redirects=True) as resp:
                if resp.status_code != 200:
                    logger.warning(f"GET {url} -> {resp.status_code}")
                    time.sleep(RETRY_BACKOFF_BASE * (attempt + 1))
                    continue
                tmp_path = cache_path.with_suffix(cache_path.suffix + ".part")
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
                tmp_path.rename(cache_path)
                return True
        except (httpx.TimeoutException, httpx.TransportError) as e:
            logger.warning(f"GET {url} -> {e!r} (attempt {attempt + 1}/{MAX_RETRIES})")
        time.sleep(RETRY_BACKOFF_BASE * (attempt + 1))
    return False


# ---------------------------------------------------------------------------
# Source 1: Hugging Face historical FF dataset (primary, 2020-01-01 .. cutoff)
# ---------------------------------------------------------------------------

def load_hf_dataset() -> pd.DataFrame:
    logger.info("Fetching Hugging Face Forex Factory historical dataset (cached if present)...")
    ok = fetch_binary(HF_DATASET_CSV_URL, HF_CACHE_CSV)
    if not ok:
        logger.error("Failed to download Hugging Face dataset")
        return pd.DataFrame()
    df = pd.read_csv(HF_CACHE_CSV)
    logger.info(f"Loaded HF dataset: {len(df):,} rows")
    return df


def build_primary_rows(hf_df: pd.DataFrame) -> tuple[list[Row], date]:
    """Build rows from the HF dataset for USD target events.

    The HF `DateTime` column carries an Asia/Tehran offset (+03:30, or
    +04:30 during Iran's pre-2023 DST). Many rows have a `T00:00:00`
    placeholder time-of-day rather than the true release time, so the
    time-of-day is NOT trusted. Instead: the Tehran *calendar date* (taken
    verbatim from the string) is used -- Tehran is far enough ahead of US
    Eastern that AM/early-afternoon ET releases always land on the same
    Tehran calendar date (verified for 8:30am, 10:00am, and 2:00pm ET) --
    combined with each event's known standard ET release time, converted to
    UTC via zoneinfo exactly as `parser.py` does for the live feed.
    """
    if hf_df.empty:
        return [], START_DATE

    hf_name_to_title = {meta["hf_name"]: title for title, meta in EVENTS.items()}
    df = hf_df[(hf_df["Currency"] == "USD") & (hf_df["Event"].isin(hf_name_to_title))].copy()
    # Take the local (Tehran) calendar date straight from the string's date
    # component. Do NOT round-trip through UTC arithmetic with a fixed
    # +03:30 offset: pre-2023 rows carry Iran DST (+04:30) offsets, and a
    # fixed-offset reconstruction shifts midnight-placeholder rows back one
    # calendar day for the entire Mar-Sep DST season.
    df["local_date"] = pd.to_datetime(df["DateTime"].str.slice(0, 10), errors="coerce").dt.date
    df = df.dropna(subset=["local_date"])

    df = df[(df["local_date"] >= START_DATE) & (df["local_date"] <= END_DATE)]

    rows: list[Row] = []
    for _, r in df.iterrows():
        title = hf_name_to_title[r["Event"]]
        et_h, et_m = EVENTS[title]["et_time"]
        local_dt_et = datetime(r["local_date"].year, r["local_date"].month, r["local_date"].day, et_h, et_m, tzinfo=ET)
        scheduled_utc = local_dt_et.astimezone(UTC).replace(tzinfo=None)
        rows.append(
            Row(
                title=title,
                country="USD",
                scheduled_utc=scheduled_utc,
                forecast=_clean(r.get("Forecast")),
                actual=_clean(r.get("Actual")),
                previous=_clean(r.get("Previous")),
                source="huggingface",
            )
        )

    cutoff = max((r.scheduled_utc.date() for r in rows), default=START_DATE)
    logger.info(f"HF primary rows: {len(rows)} (2020-01-01 .. {cutoff})")
    return rows, cutoff


def _clean(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    return s


# ---------------------------------------------------------------------------
# Source 2a: Wayback-archived FF per-indicator "History" pages (gap-fill)
# ---------------------------------------------------------------------------

def discover_cdx_snapshots(url_pattern: str, cache_key: str, from_date: date, to_date: date) -> list[str]:
    """Query the Wayback Machine CDX API for available snapshot timestamps."""
    cache_path = CDX_CACHE / f"{cache_key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    params = {
        "url": url_pattern,
        "from": from_date.strftime("%Y%m%d"),
        "to": to_date.strftime("%Y%m%d"),
        "output": "json",
        "filter": "statuscode:200",
    }
    text = fetch_text("https://web.archive.org/cdx/search/cdx", params=params)
    if not text:
        cache_path.write_text("[]")
        return []
    try:
        rows = json.loads(text)[1:]
    except (json.JSONDecodeError, IndexError):
        cache_path.write_text("[]")
        return []
    timestamps = sorted({row[1] for row in rows})
    cache_path.write_text(json.dumps(timestamps))
    return timestamps


def fetch_wayback_page(original_url: str, timestamp: str, cache_name: str) -> str | None:
    wayback_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
    cache_path = WAYBACK_HTML_CACHE / f"{cache_name}_{timestamp}.html"
    return fetch_text(wayback_url, cache_path=cache_path)


def parse_indicator_history_table(html: str, title: str) -> list[Row]:
    """Parse the 'History' table on a FF per-indicator page."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.calendarhistory")
    if table is None:
        return []

    et_h, et_m = EVENTS[title]["et_time"]
    rows: list[Row] = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        date_link = cells[0].find("a")
        if date_link is None:
            continue
        date_text = date_link.get_text(strip=True)
        try:
            d = datetime.strptime(date_text, "%b %d, %Y").date()
        except ValueError:
            continue
        actual = _clean(cells[1].get_text(strip=True))
        forecast = _clean(cells[2].get_text(strip=True))
        previous = _clean(cells[3].get_text(strip=True))
        if actual is None and forecast is None and previous is None:
            continue
        local_dt_et = datetime(d.year, d.month, d.day, et_h, et_m, tzinfo=ET)
        scheduled_utc = local_dt_et.astimezone(UTC).replace(tzinfo=None)
        rows.append(Row(title, "USD", scheduled_utc, forecast, actual, previous, "wayback_indicator"))
    return rows


def build_indicator_gapfill_rows(cutoff: date) -> list[Row]:
    rows: list[Row] = []
    for title, meta in EVENTS.items():
        url_pattern = f"forexfactory.com/calendar/{meta['slug']}"
        timestamps = discover_cdx_snapshots(
            url_pattern, f"indicator_{meta['ebase_id']}", cutoff, END_DATE + pd.Timedelta(days=30)
        )
        if not timestamps:
            logger.warning(f"No wayback snapshots found for indicator page: {title}")
            continue
        original_url = f"https://www.forexfactory.com/calendar/{meta['slug']}"
        for ts in timestamps:
            html = fetch_wayback_page(original_url, ts, f"indicator_{meta['ebase_id']}")
            if not html:
                continue
            parsed = parse_indicator_history_table(html, title)
            rows.extend(r for r in parsed if cutoff < r.scheduled_utc.date() <= END_DATE)
        logger.info(f"  {title}: wayback indicator pages -> {len(timestamps)} snapshots parsed")
    return rows


# ---------------------------------------------------------------------------
# Source 2b: Wayback-archived FF default /calendar page (JSON payload; supplement)
# ---------------------------------------------------------------------------

# Matches one flat JSON event object embedded in the page's Vue/SSR payload.
_EVENT_OBJ_RE = re.compile(r'\{"id":\d+,"ebaseId":\d+,.*?"soloUrl":"[^"]*"\}')


def parse_general_calendar_json(html: str) -> list[Row]:
    rows: list[Row] = []
    for match in _EVENT_OBJ_RE.finditer(html):
        raw = match.group(0).replace("\\/", "/")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ebase_id = obj.get("ebaseId")
        title = EBASE_TO_TITLE.get(ebase_id)
        if title is None or obj.get("country") != "US":
            continue
        actual = _clean(obj.get("actual"))
        if actual is None:
            continue  # not yet released as of crawl time -- skip (avoid partial rows)
        dateline = obj.get("dateline")
        if not dateline:
            continue
        scheduled_utc = datetime.fromtimestamp(int(dateline), tz=UTC).replace(tzinfo=None)
        rows.append(
            Row(
                title=title,
                country="USD",
                scheduled_utc=scheduled_utc,
                forecast=_clean(obj.get("forecast")),
                actual=actual,
                previous=_clean(obj.get("previous")),
                source="wayback_calendar_json",
            )
        )
    return rows


def build_general_calendar_gapfill_rows(cutoff: date) -> list[Row]:
    timestamps = discover_cdx_snapshots(
        "forexfactory.com/calendar", "general_calendar", cutoff, END_DATE + pd.Timedelta(days=30)
    )
    logger.info(f"General /calendar wayback snapshots in gap window: {len(timestamps)}")
    rows: list[Row] = []
    for ts in timestamps:
        html = fetch_wayback_page("https://www.forexfactory.com/calendar", ts, "general_calendar")
        if not html:
            continue
        parsed = parse_general_calendar_json(html)
        rows.extend(r for r in parsed if cutoff < r.scheduled_utc.date() <= END_DATE)
    return rows


# ---------------------------------------------------------------------------
# Source 2c: Wayback-archived FF week/month/day calendar pages (gap supplement)
# ---------------------------------------------------------------------------

def discover_cdx_prefix(cutoff: date) -> list[tuple[str, str]]:
    """CDX prefix query: every archived forexfactory.com/calendar* URL in the
    gap window. Returns (timestamp, original_url) pairs, one per urlkey."""
    cache_path = CDX_CACHE / "prefix_calendar.json"
    if cache_path.exists():
        return [tuple(x) for x in json.loads(cache_path.read_text())]
    params = {
        "url": "forexfactory.com/calendar*",
        "from": cutoff.strftime("%Y%m%d"),
        "to": (END_DATE + pd.Timedelta(days=30)).strftime("%Y%m%d"),
        "output": "json",
        "filter": "statuscode:200",
        "collapse": "urlkey",
    }
    text = fetch_text("https://web.archive.org/cdx/search/cdx", params=params)
    if not text:
        return []
    try:
        raw = json.loads(text)[1:]
    except (json.JSONDecodeError, IndexError):
        return []
    pairs = [(row[1], row[2]) for row in raw]
    cache_path.write_text(json.dumps(pairs))
    return pairs


def build_period_page_gapfill_rows(cutoff: date) -> list[Row]:
    """Fetch archived ?week= / ?month= / ?day= calendar pages and parse the
    same embedded JSON blobs as the default /calendar page. Month and week
    pages cover whole periods, so they fill dates the current-week snapshots
    miss."""
    pairs = discover_cdx_prefix(cutoff)
    month_pages = [(ts, u) for ts, u in pairs if "?month=" in u]
    week_pages = [(ts, u) for ts, u in pairs if "?week=" in u]
    day_pages = [(ts, u) for ts, u in pairs if "?day=" in u]
    logger.info(
        f"Prefix CDX: {len(month_pages)} month, {len(week_pages)} week, "
        f"{len(day_pages)} day pages archived in gap window"
    )
    rows: list[Row] = []
    for ts, url in month_pages + week_pages + day_pages:
        safe = re.sub(r"[^A-Za-z0-9]+", "_", url.split("calendar", 1)[-1])[:60]
        html = fetch_text(
            f"https://web.archive.org/web/{ts}id_/{url}",
            cache_path=WAYBACK_HTML_CACHE / f"period_{safe}_{ts}.html",
        )
        if not html:
            continue
        parsed = parse_general_calendar_json(html)
        rows.extend(r for r in parsed if cutoff < r.scheduled_utc.date() <= END_DATE)
    return rows


# ---------------------------------------------------------------------------
# Merge + write
# ---------------------------------------------------------------------------

def merge_rows(*row_lists: list[Row]) -> list[Row]:
    """Merge multiple sources, de-duplicating by (title, calendar date).

    Earlier lists take priority (HF primary > indicator gap-fill > general
    calendar gap-fill), but a later source's value is used to fill any
    field left blank by an earlier source for the same (title, date).
    """
    merged: dict[tuple[str, date], Row] = {}
    for rows in row_lists:
        for r in rows:
            key = (r.title, r.scheduled_utc.date())
            if key not in merged:
                merged[key] = r
            else:
                existing = merged[key]
                if existing.actual is None and r.actual is not None:
                    existing.actual = r.actual
                if existing.forecast is None and r.forecast is not None:
                    existing.forecast = r.forecast
                if existing.previous is None and r.previous is not None:
                    existing.previous = r.previous
    return sorted(merged.values(), key=lambda r: (r.scheduled_utc, r.title))


def write_csv(rows: list[Row]) -> None:
    df = pd.DataFrame(
        [
            {
                "title": r.title,
                "country": r.country,
                "scheduled_utc": r.scheduled_utc.isoformat(),
                "forecast": r.forecast,
                "actual": r.actual,
                "previous": r.previous,
            }
            for r in rows
        ]
    )
    df.to_csv(OUTPUT_CSV, index=False)
    logger.info(f"Wrote {len(df)} rows -> {OUTPUT_CSV}")


def main() -> None:
    hf_df = load_hf_dataset()
    primary_rows, cutoff = build_primary_rows(hf_df)

    logger.info(f"Gap-filling {cutoff} .. {END_DATE} via Wayback Machine archives...")
    indicator_rows = build_indicator_gapfill_rows(cutoff)
    logger.info(f"Indicator-page gap-fill rows: {len(indicator_rows)}")

    general_rows = build_general_calendar_gapfill_rows(cutoff)
    logger.info(f"General-calendar gap-fill rows: {len(general_rows)}")

    period_rows = build_period_page_gapfill_rows(cutoff)
    logger.info(f"Week/month/day-page gap-fill rows: {len(period_rows)}")

    all_rows = merge_rows(primary_rows, indicator_rows, general_rows, period_rows)
    logger.info(f"Total merged rows: {len(all_rows)}")

    by_title = pd.Series([r.title for r in all_rows]).value_counts()
    logger.info(f"Rows per event:\n{by_title.to_string()}")

    write_csv(all_rows)


if __name__ == "__main__":
    main()
