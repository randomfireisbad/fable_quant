"""Walk-forward sanity backtest.

Trades each signal on the ticker's own history using ONLY trailing data at
each point (signals are lagged one day before being applied), with a
transaction cost charged per unit of turnover. This is a sanity check on
whether the signals carried any edge on this instrument historically — not a
guarantee they will again (Cederburg et al. 2020 is the cautionary tale).

Strategies:
  tsmom   — long/short the sign of the trailing 252d excess return
            (Moskowitz-Ooi-Pedersen 2012)
  meanrev — fade the 20-day z-score with position = -tanh(z/2)
  buyHold — benchmark
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 252
WARMUP = 252


def _metrics(r: pd.Series, rf_d: float) -> dict:
    if len(r) < 30 or r.std(ddof=1) == 0:
        return {"annReturn": None, "sharpe": None, "maxDD": None}
    ex = r - rf_d
    sharpe = float(ex.mean() / ex.std(ddof=1) * np.sqrt(ANN))
    cum = (1 + r).cumprod()
    dd = float((cum / cum.cummax() - 1).min())
    return {"annReturn": round(float(r.mean() * ANN), 4),
            "sharpe": round(sharpe, 3),
            "maxDD": round(dd, 4)}


def run(close: pd.Series, rf: float = 0.04, cost_bps: float = 5.0) -> dict:
    close = close.dropna()
    r = close.pct_change().dropna()
    if len(r) < WARMUP + 100:
        return {"ok": False, "note": f"insufficient history ({len(r)} bars)"}
    rf_d = rf / ANN
    cost = cost_bps / 1e4

    # TSMOM: sign of trailing 12m excess return, applied next day
    excess12 = close.pct_change(WARMUP) - rf
    pos_ts = np.sign(excess12).shift(1).reindex(r.index).fillna(0.0)

    # Mean-reversion fade: -tanh(z20/2), applied next day
    m20 = close.rolling(20).mean()
    s20 = close.rolling(20).std(ddof=1)
    z = ((close - m20) / s20).clip(-4, 4)
    pos_mr = (-np.tanh(z / 2.0)).shift(1).reindex(r.index).fillna(0.0)

    # Vol-scaled TSMOM — the actual MOP (2012) construction: position size
    # = sign * (target vol / trailing EWMA vol), capped at 2x.
    ewma_var = r.pow(2).ewm(alpha=0.06).mean()
    ann_vol = (ewma_var * ANN) ** 0.5
    scale = (0.15 / ann_vol).clip(upper=2.0)
    pos_ts_vs = (np.sign(excess12).reindex(r.index) * scale).shift(1).fillna(0.0)

    out = {"ok": True, "costBps": cost_bps}
    for name, pos in (("tsmom", pos_ts), ("tsmomVolScaled", pos_ts_vs),
                      ("meanrev", pos_mr)):
        strat = (pos * r - cost * pos.diff().abs().fillna(0.0)).iloc[WARMUP:]
        out[name] = _metrics(strat.dropna(), rf_d)
    out["buyHold"] = _metrics(r.iloc[WARMUP:], rf_d)
    out["evalDays"] = int(len(r.iloc[WARMUP:]))
    return out
