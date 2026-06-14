"""Performance attribution + model-improvement loop.

Every trade can carry a snapshot of the model state at entry. This module
matches buys to sells (FIFO) into round trips, then attributes outcomes by
the rating/score/source at entry — the evidence base for improving the
models. It also maintains an improvement log: every model change must cite
the evidence behind it (see MODEL_ASSUMPTIONS.md policy).

Statistical honesty: with n < 30 round trips, win rates are noise. review()
computes and reports this rather than hiding it.
"""
from __future__ import annotations

import json
import math
import os
import threading
from collections import defaultdict, deque
from datetime import datetime

from . import pipeline, portfolio

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_LOG_FILE = os.path.join(_DATA, "improvement_log.json")
_lock = threading.Lock()


def signal_snapshot(ticker: str, allow_run: bool = False) -> dict | None:
    """Condensed model state for attaching to a trade record."""
    a = pipeline.get_cached(ticker)
    if a is None and allow_run:
        try:
            a = pipeline.run_analysis(ticker)
        except Exception:
            return None
    if a is None:
        return None
    return {
        "rating": a["composite"]["rating"],
        "score": a["composite"]["score"],
        "components": a["composite"]["components"],
        "confidence": a["composite"].get("confidence"),
        "regime": a["composite"].get("marketRegime"),
        "horizon": a.get("horizon"),
        "target": a["priceTarget"]["target"],
        "garchVol": a["volatility"]["garch"].get("annVolForecast21d"),
    }


def _round_trips(trades: list[dict]) -> list[dict]:
    """FIFO-match buys to sells per ticker into closed round trips."""
    lots: dict[str, deque] = defaultdict(deque)
    rts: list[dict] = []
    for t in sorted(trades, key=lambda x: x.get("ts", "")):
        tk, qty = t["ticker"], float(t["qty"])
        if t["side"] == "buy":
            lots[tk].append({"qty": qty, "price": t["price"], "ts": t.get("ts"),
                             "signal": t.get("signal"), "source": t.get("source")})
        else:
            remaining = qty
            while remaining > 1e-9 and lots[tk]:
                lot = lots[tk][0]
                used = min(lot["qty"], remaining)
                rts.append({
                    "ticker": tk, "qty": used,
                    "entryPrice": lot["price"], "exitPrice": t["price"],
                    "retPct": round(100 * (t["price"] / lot["price"] - 1), 3),
                    "entryTs": lot["ts"], "exitTs": t.get("ts"),
                    "entrySignal": lot["signal"], "source": lot["source"],
                })
                lot["qty"] -= used
                remaining -= used
                if lot["qty"] <= 1e-9:
                    lots[tk].popleft()
    return rts


def _bucket_stats(rts: list[dict]) -> dict:
    if not rts:
        return {"n": 0}
    rets = [r["retPct"] for r in rts]
    wins = sum(1 for r in rets if r > 0)
    n = len(rets)
    # 95% binomial CI half-width for the win rate (normal approx)
    ci = round(1.96 * math.sqrt(0.25 / n) * 100, 1) if n else None
    return {"n": n, "winRatePct": round(100 * wins / n, 1),
            "winRateCi95": f"±{ci}", "avgRetPct": round(sum(rets) / n, 3),
            "medianRetPct": round(sorted(rets)[n // 2], 3),
            "totalWeightedRetPct": round(sum(r["retPct"] * r["qty"] * r["entryPrice"]
                                             for r in rts) /
                                         max(sum(r["qty"] * r["entryPrice"] for r in rts), 1e-9), 3)}


def review() -> dict:
    trades = portfolio._load()["trades"]
    rts = _round_trips(trades)

    by_rating: dict[str, list] = defaultdict(list)
    by_source: dict[str, list] = defaultdict(list)
    by_score_sign: dict[str, list] = defaultdict(list)
    for r in rts:
        sig = r.get("entrySignal") or {}
        by_rating[sig.get("rating") or "no snapshot"].append(r)
        by_source[r.get("source") or "unknown"].append(r)
        if sig.get("score") is not None:
            by_score_sign["score>0" if sig["score"] > 0 else "score<=0"].append(r)

    n = len(rts)
    warnings = []
    if n == 0:
        warnings.append("No closed round trips yet — no outcome evidence exists. "
                        "Do not change model parameters.")
    elif n < 30:
        warnings.append(f"Only {n} closed round trips. Win rates at this sample size "
                        f"are statistically meaningless (95% CI ≈ ±{round(196 * math.sqrt(0.25 / max(n,1)), 0):.0f}pp). "
                        "Treat every pattern below as anecdote, not evidence. "
                        "Parameter changes require n ≥ 30, ideally ≥ 100.")
    snapshotless = sum(1 for r in rts if not r.get("entrySignal"))
    if snapshotless:
        warnings.append(f"{snapshotless}/{n} round trips lack an entry signal snapshot "
                        "(trades made before snapshotting existed, or analysis cache was cold).")

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "closedRoundTrips": n,
        "overall": _bucket_stats(rts),
        "byEntryRating": {k: _bucket_stats(v) for k, v in sorted(by_rating.items())},
        "byScoreSign": {k: _bucket_stats(v) for k, v in sorted(by_score_sign.items())},
        "bySource": {k: _bucket_stats(v) for k, v in sorted(by_source.items())},
        "recentRoundTrips": rts[-15:][::-1],
        "warnings": warnings,
    }


# ------------------------------------------------------------ improvement log
def log_list() -> list[dict]:
    try:
        with open(_LOG_FILE) as f:
            out = json.load(f)
            return out if isinstance(out, list) else []
    except Exception:
        return []


def log_add(observation: str, change: str = "", author: str = "user",
            evidence: str = "") -> dict:
    entry = {"ts": datetime.now().isoformat(timespec="seconds"),
             "author": author, "observation": observation,
             "change": change, "evidence": evidence}
    with _lock:
        log = log_list()
        log.append(entry)
        os.makedirs(_DATA, exist_ok=True)
        with open(_LOG_FILE, "w") as f:
            json.dump(log[-300:], f, indent=1)
    return entry
