# Spec 16 — Dukascopy Timezone Fix + Re-validation of MC Reports 04-12

**Status**: URGENT (pipeline 1.5). **Branch**: `fix/dukascopy-timezone`.
**Deliverable report**: `docs/research/16-mc-revalidation.md`.

## Background

`scripts/download_dukascopy.py` passes **naive** datetimes to
`dukascopy_python.fetch()`, which interprets them as local time
(America/Edmonton). Every stored 1-min/5-min "event window" in
`scripts/data/dukascopy/` is therefore shifted ~+6h (MDT) / +7h (MST) and
does **not contain the event**. Verified 2026-07-21 on NFP 2023-02-03:
stored GBPUSD window covers 18:30-22:00 UTC (event 13:30 UTC), max 1-min
range 6.1 pips — no NFP burst.

Consequence: MC reports 04-12 — the empirical basis for every enabled
pair, event source, and parameter set in `config/settings.yaml` — were
simulated on wrong-time data. Report 15 is unaffected (fetched its own
correctly-timed windows).

## Phase A — Fix

1. In `download_dukascopy.py`: make all datetimes passed to `dp.fetch()`
   timezone-aware UTC (and audit any other naive-datetime use in the
   script). THIS script may be modified; nothing else outside scripts/.
2. Prove the fix on one window before bulk download: NFP 2023-02-03 —
   the fetched GBPUSD 1-min window must contain a >=30-pip 1-min bar
   within minutes of 13:30 UTC.
3. Preserve the old CSVs (rename dir to `dukascopy_SHIFTED_BAD/` or
   similar) — do not silently overwrite evidence.

## Phase B — Re-download

Full re-download of 1-min (and 5-min where the original script did) event
windows for all 11 pairs / all event groups, into the standard layout.
Foreground chunked runs ONLY (no background+watcher). Resume-safe.
Respect Dukascopy pacing; expect hours of runtime. Sanity gate after
download: for 10 randomly sampled high-impact events across pairs/years,
the window must contain an elevated-range bar near T0 vs the window
median (document the check).

## Phase C — Re-validation

Priority order (stop-the-bleeding first):

1. **Active production combos** at their exact configured params
   (`config/settings.yaml` straddle_pair_overrides + event_overrides):
   - USDZAR 50/70/10 on US events (NFP, CPI, FOMC, PPI, GDP) + SARB/SA CPI
   - USDTRY 50/70/10 on US events (incl. UC, ISM, Retail Sales, PCE); 20/60/10 on TCMB
   - AUDUSD 40/15/25 US events; 40/70/30 AU events
   - USDJPY 25/15/15 on BOJ
   For each: E[P&L], 95% CI, Sharpe, walk-forward (train 2020-2024, test
   2025-2026), spread sweep 1-4x — same methodology and pass bar as the
   original reports (rerun the existing scripts where possible:
   `monte_carlo_dukascopy.py`, `mc_non_us.py`, `mc_event_split.py`,
   `mc_remaining_us.py`, `mc_audusd_explore.py`).
2. **Fresh optimization grids** for any active combo whose configured
   params now FAIL — report the new optimum if one passes, or "no
   passing cell" honestly.
3. Disabled pairs (GBPUSD etc.): quick check only — note in the report
   whether the "avoid" verdicts still hold; no deep grids.

## Report

`docs/research/16-mc-revalidation.md`: per-combo table with OLD (shifted
data) vs NEW (corrected data) results side by side, verdict per combo
(param set survives / fails / new optimum), spread sensitivity, and a
"Production recommendation" section listing exactly which settings.yaml
entries are still justified and which are not. **Do NOT modify
`config/settings.yaml` or anything under `src/`** — config changes are a
user decision (Analysis-Driven Configuration rule).

## Constraints

- `~/anaconda3/envs/forex-bot/bin/python` only; repo code style.
- No commits/pushes; leave work uncommitted for review.
- Do not touch the running bot or TWS.
- If prior scripts hardcode paths/assumptions that fought the old data
  layout, prefer minimal patches and document every change.
