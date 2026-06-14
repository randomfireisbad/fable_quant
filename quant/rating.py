"""Composite rating & price target.

Rating: weighted blend of the four model scores, each in [-1, 1].
Price target (63 trading days ≈ 3 months):
  - trend regime  → lognormal drift projection S0·exp((μ−σ²/2)τ)
  - reverting regime → exponential decay toward the 200-bar anchor at the
    fitted OU half-life
  - blended by the mean-reversion regime weight (ADF/VR evidence)
  - 80% interval from GARCH(1,1) forecast vol: ±1.2816·σ√τ in log space
"""
from __future__ import annotations

import numpy as np

# Equal weights across the four models (1/N). Deliberate: DeMiguel, Garlappi
# & Uppal (2009, RFS) show naive 1/N diversification is extremely hard to beat
# out of sample, and any unequal weighting here would be a discretionary
# choice without supporting evidence. The market regime (bull/bear vs SPY's
# 200d average) is reported as CONTEXT but no longer changes the weights —
# regime-conditional weights were themselves a discretionary tilt.
WEIGHTS = {"momentum": 0.25, "meanReversion": 0.25, "volatility": 0.25, "factors": 0.25}

BINS = [(0.45, "Strong Buy"), (0.15, "Buy"), (-0.15, "Hold"),
        (-0.45, "Sell"), (-np.inf, "Strong Sell")]

HORIZON_DAYS = 63
Z80 = 1.2816


def composite(mom: dict, mr: dict, vol: dict, fac: dict | None,
              market_regime: str | None = None) -> dict:
    scores = {
        "momentum": mom["score"],
        "meanReversion": mr["score"],
        "volatility": vol["score"],
        "factors": fac["score"] if fac else 0.0,
    }
    w = dict(WEIGHTS)
    if not fac:  # renormalize if factor regression unavailable
        total = sum(v for k, v in w.items() if k != "factors")
        w = {k: (v / total if k != "factors" else 0.0) for k, v in w.items()}
    raw = sum(scores[k] * w[k] for k in scores)

    # Agreement adjustment: when the models disagree strongly, the blended
    # signal is less trustworthy, so shrink toward Hold (0). Dispersion is the
    # std-dev of the component scores; confidence maps it to [0.45, 1].
    vals = [v for k, v in scores.items() if fac or k != "factors"]
    dispersion = float(np.std(vals))
    confidence = float(np.clip(1.0 - 0.55 * dispersion, 0.45, 1.0))
    score = raw * confidence

    rating = next(label for cut, label in BINS if score >= cut)
    return {"score": round(float(score), 3), "rawScore": round(float(raw), 3),
            "confidence": round(confidence, 3),
            "dispersion": round(dispersion, 3),
            "marketRegime": market_regime,
            "rating": rating, "components": scores, "weights": w}


def _bootstrap_band(close, mu_annual: float, horizon: int = HORIZON_DAYS,
                    n_sims: int = 2000, block: int = 5,
                    seed: int = 7) -> tuple[float, float] | None:
    """Stationary block bootstrap of log returns, recentered at the shrunk
    drift. Returns (q10-q50, q90-q50) log-space offsets — a distribution-
    shaped 80% band capturing the fat tails and skew the lognormal misses
    (cf. Politis & Romano 1994 on block bootstrap for dependent series)."""
    import numpy as np
    r = np.diff(np.log(np.asarray(close, dtype=float)))
    r = r[np.isfinite(r)]
    if len(r) < 120:
        return None
    r = r - r.mean() + mu_annual / 252.0
    rng = np.random.default_rng(seed)
    n_blocks = horizon // block + 1
    starts = rng.integers(0, len(r) - block, size=(n_sims, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_sims, -1)[:, :horizon]
    sums = r[idx].sum(axis=1)
    q10, q50, q90 = np.percentile(sums, [10, 50, 90])
    return float(q10 - q50), float(q90 - q50)


def price_target(spot: float, mom: dict, mr: dict, vol: dict,
                 fac: dict | None = None, rf: float = 0.04,
                 erp: float = 0.05, close=None,
                 horizon_days: int = HORIZON_DAYS) -> dict:
    tau = horizon_days / 252
    sigma = vol["garch"]["annVolForecast21d"] or 0.25

    # Drift: sample means over 1-2 years are dominated by noise (Merton 1980),
    # so shrink the trailing estimate heavily toward a CAPM prior
    # (rf + beta * equity risk premium). 35% sample / 65% prior.
    mu_sample = mom["annualizedDrift"]
    beta = fac["betas"]["MKT"] if fac else 1.0
    mu_prior = rf + beta * erp
    mu = 0.35 * mu_sample + 0.65 * mu_prior
    # cap at +/- 2 sigma annualized to avoid extrapolating tail runs
    mu = float(np.clip(mu, -2 * sigma, 2 * sigma))

    drift_target = spot * np.exp((mu - 0.5 * sigma ** 2) * tau)

    anchor = mr.get("anchor200", spot)
    hl = mr.get("halfLifeDays")
    if hl and hl > 0:
        decay = 0.5 ** (horizon_days / hl)
        revert_target = anchor + (spot - anchor) * decay
    else:
        revert_target = spot

    w = float(np.clip(mr.get("regimeWeight", 0.0), 0.0, 0.8))
    target = (1 - w) * drift_target + w * revert_target

    # Interval: prefer a block bootstrap of the ticker's own return
    # distribution (captures fat tails / skew); fall back to lognormal with
    # drift-estimation uncertainty added (se of an annual mean from ~2y of
    # data is roughly sigma/sqrt(2)).
    bs = _bootstrap_band(close, mu, horizon=horizon_days) if close is not None else None
    if bs is not None:
        lo_off, hi_off = bs
        low80 = float(target * np.exp(lo_off))
        high80 = float(target * np.exp(hi_off))
        interval_method = "block bootstrap (2000 sims, 5d blocks)"
    else:
        drift_se = sigma / np.sqrt(2.0)
        total_sd = float(np.sqrt(sigma ** 2 * tau + (drift_se * tau) ** 2))
        band = Z80 * total_sd
        low80 = float(target * np.exp(-band))
        high80 = float(target * np.exp(band))
        interval_method = "lognormal + drift uncertainty"
    return {
        "horizonDays": horizon_days,
        "spot": round(spot, 2),
        "target": round(float(target), 2),
        "expectedReturnPct": round(100 * (target / spot - 1), 2),
        "low80": round(low80, 2),
        "high80": round(high80, 2),
        "intervalMethod": interval_method,
        "components": {
            "driftTarget": round(float(drift_target), 2),
            "reversionTarget": round(float(revert_target), 2),
            "reversionWeight": round(w, 3),
            "driftSample": round(float(mu_sample), 4),
            "driftPrior": round(float(mu_prior), 4),
            "driftUsed": round(float(mu), 4),
            "garchVolUsed": sigma,
        },
    }
