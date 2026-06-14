"""Factor regression.

Methods grounded in:
- Sharpe (1964) CAPM; Fama & French (1993) three-factor model. Since the Ken
  French data library lags by weeks, we use liquid ETF spread proxies:
    MKT  = SPY excess return
    SMB~ = IWM - SPY   (size spread)
    HML~ = VTV - VUG   (value-minus-growth spread)
- Newey & West (1987) HAC standard errors (5 lags).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from . import data

ANN = 252


def analyze(close: pd.Series, rf_annual: float = 0.04) -> dict:
    rf_d = rf_annual / ANN
    r = close.dropna().pct_change().dropna().rename("asset")

    spy = data.closes("SPY", "2Y").pct_change().rename("spy")
    iwm = data.closes("IWM", "2Y").pct_change().rename("iwm")
    vtv = data.closes("VTV", "2Y").pct_change().rename("vtv")
    vug = data.closes("VUG", "2Y").pct_change().rename("vug")

    df = pd.concat([r, spy, iwm, vtv, vug], axis=1).dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if len(df) < 60:
        raise ValueError("Not enough overlapping data for factor regression")

    y = df["asset"] - rf_d
    X = pd.DataFrame({
        "MKT": df["spy"] - rf_d,
        "SMB": df["iwm"] - df["spy"],
        "HML": df["vtv"] - df["vug"],
    }, index=df.index)
    X = sm.add_constant(X)

    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

    alpha_ann = float(model.params["const"] * ANN)
    out = {
        "alphaAnnual": round(alpha_ann, 4),
        "alphaTStat": round(float(model.tvalues["const"]), 3),
        "betas": {k: round(float(model.params[k]), 3) for k in ("MKT", "SMB", "HML")},
        "tStats": {k: round(float(model.tvalues[k]), 3) for k in ("MKT", "SMB", "HML")},
        "r2": round(float(model.rsquared), 3),
        "nObs": int(model.nobs),
        "idioVolAnnual": round(float(np.std(model.resid, ddof=1) * np.sqrt(ANN)), 4),
    }

    # Factor score in [-1,1]: alpha credibility scaled by its t-stat.
    t = out["alphaTStat"]
    out["score"] = round(float(np.tanh(t / 2.0)), 3)
    return out
