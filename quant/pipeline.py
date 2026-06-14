"""Analysis pipeline shared by the web server, the research agent, and the
MCP connector. Moved out of server.py so non-web entry points (mcp_server.py)
don't need to import the FastAPI app."""
from __future__ import annotations

import time

from . import backtest, data, factors, meanrev, momentum, rating, volatility

# Rating horizons: data window + price-target horizon (trading days)
HORIZONS = {"short": ("1Y", 21), "medium": ("2Y", 63), "long": ("5Y", 126)}

_analysis_cache: dict[str, tuple[float, dict]] = {}
_ANALYSIS_TTL = 600


def get_cached(ticker: str) -> dict | None:
    """Most recent still-valid cached analysis at any horizon, else None."""
    t = ticker.upper()
    for h in HORIZONS:
        hit = _analysis_cache.get(f"{t}|{h}")
        if hit and time.time() - hit[0] < _ANALYSIS_TTL:
            return hit[1]
    return None


def run_analysis(ticker: str, force: bool = False, horizon: str = "medium") -> dict:
    t = ticker.upper()
    if horizon not in HORIZONS:
        horizon = "medium"
    rng, target_days = HORIZONS[horizon]
    key = f"{t}|{horizon}"
    hit = _analysis_cache.get(key)
    if not force and hit and time.time() - hit[0] < _ANALYSIS_TTL:
        return hit[1]

    close = data.closes(t, rng)
    q = data.quote_from_closes(t, close)

    try:
        bench = data.closes("SPY", rng) if t != "SPY" else None
    except Exception:
        bench = None
    bench_sharpe = None
    if bench is not None:
        try:
            bench_sharpe = volatility.risk_metrics(bench.pct_change().dropna())["sharpe"]
        except Exception:
            pass

    mom = momentum.analyze(close, bench_close=bench)
    mr = meanrev.analyze(close)
    vol = volatility.analyze(close, bench_sharpe=bench_sharpe)
    try:
        fac = factors.analyze(close)
    except Exception:
        fac = None

    regime = None
    ref = bench if bench is not None else (close if t == "SPY" else None)
    if ref is not None and len(ref) >= 200:
        regime = "bull" if float(ref.iloc[-1]) >= float(ref.rolling(200).mean().iloc[-1]) else "bear"

    comp = rating.composite(mom, mr, vol, fac, market_regime=regime)
    pt = rating.price_target(q["price"], mom, mr, vol, fac, close=close,
                             horizon_days=target_days)

    try:
        bt = backtest.run(data.closes(t, "5Y"))
    except Exception:
        bt = {"ok": False, "note": "backtest unavailable"}

    result = {"ticker": t, "quote": q, "horizon": horizon,
              "momentum": mom, "meanReversion": mr,
              "volatility": vol, "factors": fac, "composite": comp,
              "priceTarget": pt, "backtest": bt}
    _analysis_cache[key] = (time.time(), result)
    return result
