"""Momentum & trend models.

Methods grounded in:
- Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers",
  Journal of Finance — 12-1 month momentum (skip most recent month).
- Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", JFE — sign of an
  asset's own trailing 12-month excess return predicts its next-month return;
  signal strength proxied by the t-statistic of mean daily returns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACKS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


def _ret(close: pd.Series, n: int) -> float | None:
    if len(close) <= n:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def analyze(close: pd.Series, rf_annual: float = 0.04,
            bench_close: pd.Series | None = None) -> dict:
    close = close.dropna()
    r = close.pct_change().dropna()
    out = {"lookbackReturns": {}}

    for label, n in LOOKBACKS.items():
        out["lookbackReturns"][label] = _ret(close, n)

    # Jegadeesh-Titman 12-1: trailing 12m return excluding the most recent month
    if len(close) > 252:
        out["mom12_1"] = float(close.iloc[-22] / close.iloc[-253] - 1)
    else:
        out["mom12_1"] = None

    # Time-series momentum (MOP 2012): trailing 12m excess return sign + t-stat
    n = min(252, len(r))
    window = r.iloc[-n:]
    rf_daily = rf_annual / 252
    excess = window - rf_daily
    mu, sd = float(excess.mean()), float(excess.std(ddof=1))
    tstat = mu / (sd / np.sqrt(n)) if sd > 0 else 0.0
    out["tsmom"] = {
        "excess12m": float(excess.sum()),
        "tStat": round(tstat, 3),
        "signal": int(np.sign(excess.sum())) if excess.sum() != 0 else 0,
        "nObs": n,
    }

    # Trend state via EMA crossover
    if len(close) >= 200:
        e50 = float(close.ewm(span=50).mean().iloc[-1])
        e200 = float(close.ewm(span=200).mean().iloc[-1])
        out["trend"] = {
            "ema50": round(e50, 2), "ema200": round(e200, 2),
            "state": "uptrend" if e50 > e200 else "downtrend",
        }
    else:
        out["trend"] = None

    # Market-relative 12-1 momentum (cross-sectional flavor, closer to the
    # original Jegadeesh-Titman construction). Absolute momentum alone is
    # buy-biased because equities drift upward; relative momentum centers
    # the signal on the market.
    out["rel12_1"] = None
    if bench_close is not None and out["mom12_1"] is not None:
        b = bench_close.dropna()
        if len(b) > 252:
            bench12_1 = float(b.iloc[-22] / b.iloc[-253] - 1)
            out["rel12_1"] = round(out["mom12_1"] - bench12_1, 4)

    # Composite momentum score in [-1, 1]: EQUAL-weighted blend of the three
    # momentum legs (TSMOM t-stat capped via tanh, sign of 12-1, sign of
    # market-relative 12-1), renormalized when a leg is unavailable.
    # Equal weights deliberately: DeMiguel, Garlappi & Uppal (2009) show 1/N
    # is hard to beat out of sample, and unequal weights here would be
    # discretionary parameters with no supporting evidence.
    legs = [(1.0, float(np.tanh(tstat / 2.0)))]
    if out["mom12_1"] is not None:
        legs.append((1.0, float(np.sign(out["mom12_1"]))))
    if out["rel12_1"] is not None:
        legs.append((1.0, float(np.sign(out["rel12_1"]))))
    wsum = sum(w for w, _ in legs)
    score = sum(w * v for w, v in legs) / wsum
    out["score"] = round(float(np.clip(score, -1, 1)), 3)
    out["annualizedDrift"] = round(mu * 252 + rf_annual, 4)
    return out
