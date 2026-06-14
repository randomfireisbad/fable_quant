# Changelog

All notable changes to Fable Quant are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com).

## [Unreleased] — 2026-06-14

### Added — agent-driven experiments

Two batch tools for the research agent (Agent tab), built entirely on the
existing analysis/backtest — no new evaluation model:

- **`compare_tickers(tickers, horizon)`** — runs the full statistical analysis
  across up to 12 names and returns one ranked table (rating, composite +
  component scores, 3-month expected return, each name's in-sample backtest
  Sharpe). Replaces issuing many separate `analyze_ticker` calls.
- **`backtest_experiment(tickers)`** — runs the walk-forward backtest across up
  to 15 names and aggregates per strategy (tsmom / tsmomVolScaled / meanrev vs
  buy-and-hold): mean/median Sharpe, mean annual return, and how many names each
  strategy beat buy-and-hold on.

The agent's system prompt now directs it to design and report experiments
(hypothesis → run across the universe → comparison table), with explicit
reminders that these backtests are in-sample sanity checks, not out-of-sample
proof. Surfaced in the Agent tab placeholder/hint and the README.

### Changed — performance & cleanup

Commit `9d2a210`. All changes are **behavior-preserving** and were verified
offline on synthetic price series (see *Verification* below).

- **Eliminated a redundant market-data fetch on every analysis.**
  `quant/pipeline.py::run_analysis` previously called `data.quote(ticker)`,
  which downloaded a *separate* 6-month history just to read the latest two
  closing prices — prices already present in the `close` series fetched one
  line earlier. It now derives the quote from that series via a new helper,
  `data.quote_from_closes(ticker, close)`. Result: one fewer Yahoo Finance
  round-trip per analyze. The standalone `data.quote()` is unchanged for
  callers that don't already hold the data (e.g. the `/api/quote` endpoint and
  the watchlist).
  Files: `quant/data.py`, `quant/pipeline.py`.

- **Vectorized the variance-ratio log-return differences.**
  `quant/meanrev.py::variance_ratio` built the q-period differences with a
  Python list comprehension; replaced with a NumPy slice
  `logp[q:] - logp[:-q]`. Output is byte-identical (verified for q = 2, 5, 10,
  21).
  File: `quant/meanrev.py`.

- **Removed a redundant local import.**
  `quant/rating.py::_bootstrap_band` re-imported NumPy even though it is already
  imported at module top.
  File: `quant/rating.py`.

- **Removed dead code.**
  `server.py` defined `_analysis_cache` / `_ANALYSIS_TTL` that were never
  referenced — the live analysis cache lives in `quant/pipeline.py`.
  File: `server.py`.

### Verification

- Every module compiles (`py_compile`).
- Offline checks on synthetic GBM data (no network) all pass:
  - `quote_from_closes` returns the correct `price` / `change` / `changePct` /
    `asOf`.
  - The variance-ratio vectorization is byte-identical to the previous loop.
  - `rating._bootstrap_band` still returns a valid 80% band.
  - `momentum`, `volatility` (EWMA fallback path), `backtest`,
    `rating.composite`, and `rating.price_target` all produce valid, in-range
    outputs.
- **Not** verifiable in the sandbox (require live data and the scientific
  stack): `quant/meanrev.py`, `quant/factors.py`, and the full live
  `quant/pipeline.py` path. The sandbox blocks Yahoo Finance and could not
  install `scipy`/`statsmodels`/`arch`. Run the project's own end-to-end check
  on a machine with network access:

  ```bash
  pip install -r requirements.txt
  python selftest.py
  ```

### Notes / pending

- **Larger efficiency opportunity (not yet done):** each analysis still issues
  separate daily fetches for the 2Y, 5Y, and (via the standalone quote path) 6M
  windows. Because these are all daily bars, a single 5Y fetch could be sliced
  to serve the shorter windows, removing further round-trips. Held back because
  slicing vs. yfinance period boundaries can subtly change which bars are
  included, so it needs a careful before/after output comparison first.

## [0.1.0] — initial import

Commit `8af722d`. First import of the Fable Quant platform: FastAPI + vanilla-JS
dashboard, the statistical model suite (momentum, mean reversion, pairs,
volatility/GARCH, factor regression), composite rating + price target, PDF
research reports, the paper/Robinhood broker layer, and the Claude Desktop MCP
connector. Research/education only.
