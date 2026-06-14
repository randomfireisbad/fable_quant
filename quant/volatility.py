"""Volatility & risk models.

Methods grounded in:
- Bollerslev (1986) GARCH; Hansen & Lunde (2005), "Does anything beat a
  GARCH(1,1)?" Journal of Applied Econometrics — GARCH(1,1) is a hard-to-beat
  daily volatility forecaster.
- Moreira & Muir (2017), "Volatility-Managed Portfolios", Journal of Finance —
  scaling exposure by inverse forecast variance; we surface the caveats of
  Cederburg et al. (2020) on out-of-sample robustness in reports.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 252


def realized_vols(r: pd.Series) -> dict:
    out = {}
    for label, n in (("21d", 21), ("63d", 63), ("252d", 252)):
        if len(r) >= n:
            out[label] = round(float(r.iloc[-n:].std(ddof=1) * np.sqrt(ANN)), 4)
        else:
            out[label] = None
    return out


def garch_forecast(r: pd.Series) -> dict:
    """Forecast next-21-day annualized volatility.

    Preferred spec: GJR-GARCH(1,1)-t — asymmetric response to negative
    returns (leverage effect, Glosten-Jagannathan-Runkle 1993) with
    Student-t errors for fat tails. Hansen & Lunde (2005) found plain
    GARCH(1,1) hard to beat for FX but inferior to leverage models for
    equities. Falls back to GARCH(1,1)-normal, then EWMA.
    """
    try:
        from arch import arch_model
        for o, dist, label in ((1, "t", "GJR-GARCH(1,1)-t"),
                               (0, "normal", "GARCH(1,1)")):
            try:
                am = arch_model(r * 100, mean="Constant", vol="GARCH",
                                p=1, o=o, q=1, dist=dist, rescale=False)
                res = am.fit(disp="off", show_warning=False)
                f = res.forecast(horizon=21, reindex=False)
                var_path = f.variance.values[-1]  # daily variances (pct^2)
                if not np.all(np.isfinite(var_path)) or var_path.mean() <= 0:
                    continue
                p = res.params
                alpha = float(p.get("alpha[1]", np.nan))
                beta = float(p.get("beta[1]", np.nan))
                gamma = float(p.get("gamma[1]", 0.0)) if o else 0.0
                ann_vol = float(np.sqrt(var_path.mean() * ANN) / 100)
                return {
                    "ok": True, "model": label,
                    "annVolForecast21d": round(ann_vol, 4),
                    "nextDayVol": round(float(np.sqrt(var_path[0] * ANN) / 100), 4),
                    "omega": round(float(p.get("omega", np.nan)), 6),
                    "alpha": round(alpha, 4), "beta": round(beta, 4),
                    "gamma": round(gamma, 4) if o else None,
                    "persistence": round(alpha + beta + gamma / 2, 4),
                }
            except Exception:
                continue
        raise RuntimeError("all GARCH specs failed to converge")
    except Exception as e:  # fall back to EWMA (RiskMetrics lambda=0.94)
        lam = 0.94
        var = float(r.var(ddof=1))
        for x in r.values:
            var = lam * var + (1 - lam) * x * x
        return {"ok": False, "model": "EWMA(0.94)", "fallback": "EWMA(0.94)", "error": str(e),
                "annVolForecast21d": round(float(np.sqrt(var * ANN)), 4),
                "nextDayVol": round(float(np.sqrt(var * ANN)), 4)}


def risk_metrics(r: pd.Series, rf_annual: float = 0.04) -> dict:
    rf_d = rf_annual / ANN
    ex = r - rf_d
    mu, sd = float(ex.mean()), float(ex.std(ddof=1))
    downside = float(ex[ex < 0].std(ddof=1)) if (ex < 0).any() else np.nan
    sharpe = mu / sd * np.sqrt(ANN) if sd > 0 else 0.0
    sortino = mu / downside * np.sqrt(ANN) if downside and downside > 0 else None

    cum = (1 + r).cumprod()
    dd = cum / cum.cummax() - 1
    var95 = float(np.percentile(r, 5))
    cvar95 = float(r[r <= var95].mean()) if (r <= var95).any() else var95

    return {
        "sharpe": round(float(sharpe), 3),
        "sortino": round(float(sortino), 3) if sortino else None,
        "maxDrawdown": round(float(dd.min()), 4),
        "var95Daily": round(var95, 4),
        "cvar95Daily": round(cvar95, 4),
        "annReturn": round(float(r.mean() * ANN), 4),
    }


def analyze(close: pd.Series, target_vol: float = 0.15,
            bench_sharpe: float | None = None) -> dict:
    r = close.dropna().pct_change().dropna()
    out = {"realized": realized_vols(r)}
    g = garch_forecast(r)
    out["garch"] = g
    out.update({"risk": risk_metrics(r)})

    fv = g["annVolForecast21d"]
    weight = min(target_vol / fv, 2.0) if fv and fv > 0 else 1.0
    out["volManaged"] = {"targetVol": target_vol, "weight": round(float(weight), 3)}

    # Risk score in [-1, 1]: Sharpe measured RELATIVE to the market's Sharpe
    # over the same sample (apples-to-apples; removes the structural buy bias
    # that absolute Sharpe has when the whole market is rising or falling).
    # Falls back to the long-run equity baseline ~0.4 when no benchmark given.
    sharpe = out["risk"]["sharpe"]
    baseline = bench_sharpe if bench_sharpe is not None else 0.4
    out["benchSharpe"] = round(float(baseline), 3)
    rv = out["realized"]["252d"] or out["realized"]["63d"] or fv
    vol_ratio = fv / rv if rv else 1.0
    score = np.tanh((sharpe - baseline) / 1.5) * 0.7 + np.clip(1 - vol_ratio, -0.5, 0.5) * 0.6
    out["score"] = round(float(np.clip(score, -1, 1)), 3)
    return out
