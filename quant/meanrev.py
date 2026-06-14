"""Mean-reversion & pairs models.

Methods grounded in:
- Dickey & Fuller (1979) / said-Dickey ADF unit-root test for stationarity.
- Lo & MacKinlay (1988), "Stock Market Prices Do Not Follow Random Walks" —
  heteroskedasticity-robust variance-ratio test.
- Ornstein-Uhlenbeck half-life via AR(1) regression (e.g. Avellaneda & Lee
  2010, "Statistical Arbitrage in the US Equities Market").
- Engle & Granger (1987) cointegration; pairs trading per Gatev, Goetzmann &
  Rouwenhorst (2006), Review of Financial Studies.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint


def variance_ratio(logp: np.ndarray, q: int = 5) -> dict:
    """Lo-MacKinlay variance ratio with heteroskedasticity-robust z (z*)."""
    r = np.diff(logp)
    n = len(r)
    if n < q * 10:
        return {"q": q, "vr": None, "z": None, "pValue": None}
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / n
    rq = logp[q:] - logp[:-q]
    m = (n - q + 1) * (1 - q / n)
    varq = np.sum((rq - q * mu) ** 2) / m
    vr = varq / (q * var1)
    # heteroskedasticity-consistent asymptotic variance (Lo-MacKinlay 1988)
    theta = 0.0
    dsq = (r - mu) ** 2
    denom = (np.sum(dsq)) ** 2
    for j in range(1, q):
        delta = n * np.sum(dsq[j:] * dsq[:-j]) / denom
        theta += (2 * (q - j) / q) ** 2 * delta
    z = (vr - 1) / np.sqrt(theta) if theta > 0 else 0.0
    from scipy.stats import norm
    p = 2 * (1 - norm.cdf(abs(z)))
    return {"q": q, "vr": round(float(vr), 4), "z": round(float(z), 3),
            "pValue": round(float(p), 4)}


def half_life(logp: np.ndarray) -> float | None:
    """OU half-life from AR(1): Δp_t = a + λ p_{t-1} + ε."""
    y = np.diff(logp)
    x = logp[:-1]
    x = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    lam = beta[1]
    if lam >= 0:
        return None  # not mean-reverting
    return float(-np.log(2) / lam)


def analyze(close: pd.Series) -> dict:
    close = close.dropna()
    logp = np.log(close.values)
    out = {}

    adf_stat, adf_p, *_ = adfuller(logp, autolag="AIC")
    out["adf"] = {"stat": round(float(adf_stat), 3), "pValue": round(float(adf_p), 4),
                  "stationary": bool(adf_p < 0.05)}

    out["varianceRatio"] = variance_ratio(logp, q=5)

    hl = half_life(logp)
    out["halfLifeDays"] = round(hl, 1) if hl is not None and hl < 5 * len(logp) else None

    # Bollinger-style z-score vs 20-bar mean
    w = close.rolling(20)
    m, s = w.mean().iloc[-1], w.std(ddof=1).iloc[-1]
    z = float((close.iloc[-1] - m) / s) if s and s > 0 else 0.0
    out["zScore20"] = round(z, 3)
    out["mean20"] = round(float(m), 2)

    # Long-run anchor for reversion target: 200-bar (or full-sample) mean of log price
    anchor = float(np.exp(np.mean(logp[-200:])))
    out["anchor200"] = round(anchor, 2)

    # Mean-reversion score in [-1, 1]: fade the z-score, credited in
    # proportion to the statistical evidence of reversion from BOTH tests:
    # ADF (1 - p) and the VR test's robust z-statistic (negative z = VR < 1
    # = reversion; z/-3 maps a strongly significant test to full weight).
    vr_z = out["varianceRatio"]["z"]
    ev_adf = max(0.0, 1 - adf_p)
    ev_vr = float(np.clip(-(vr_z or 0.0) / 3.0, 0.0, 1.0))
    # Equal weight on the two tests (no evidence basis to prefer either).
    evidence = float(np.clip(0.5 * ev_adf + 0.5 * ev_vr, 0.0, 1.0))
    raw = -np.tanh(z / 2.0)
    out["score"] = round(float(np.clip(raw * evidence, -1, 1)), 3)
    significant = adf_p < 0.10 or (vr_z or 0.0) < -1.645
    out["regimeWeight"] = round(float(evidence if significant else 0.2 * evidence), 3)
    return out


def pairs(close_a: pd.Series, close_b: pd.Series, a: str, b: str) -> dict:
    """Engle-Granger cointegration + spread z-score for a candidate pair."""
    df = pd.concat([close_a.rename("a"), close_b.rename("b")], axis=1).dropna()
    if len(df) < 60:
        raise ValueError("Not enough overlapping history for pair analysis")
    la, lb = np.log(df["a"].values), np.log(df["b"].values)

    t_stat, p_value, _ = coint(la, lb)

    X = np.column_stack([np.ones_like(lb), lb])
    beta, *_ = np.linalg.lstsq(X, la, rcond=None)
    hedge = float(beta[1])
    spread = la - (beta[0] + hedge * lb)
    z = float((spread[-1] - spread.mean()) / spread.std(ddof=1))
    hl = half_life(spread)

    return {
        "pair": f"{a.upper()}/{b.upper()}",
        "engleGranger": {"tStat": round(float(t_stat), 3),
                         "pValue": round(float(p_value), 4),
                         "cointegrated": bool(p_value < 0.05)},
        "hedgeRatio": round(hedge, 4),
        "spreadZ": round(z, 3),
        "spreadHalfLifeDays": round(hl, 1) if hl else None,
        "signal": ("short A / long B" if z > 1 else
                   "long A / short B" if z < -1 else "no entry (|z| < 1)"),
    }
