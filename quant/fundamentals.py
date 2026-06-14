"""Fundamentals fetch + multibagger screen.

Criteria inspired by the multibagger literature (Lynch's ten-baggers; Mayer's
'100 Baggers' — small base, high reinvested growth, margin power, low dilution)
plus the momentum evidence that 52-week strength persists.
Score is 0-100 with a per-criterion breakdown.
"""
from __future__ import annotations

import time

import yfinance as yf

from . import data

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 3600


def fetch(ticker: str) -> dict:
    t = ticker.upper()
    hit = _cache.get(t)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    info = yf.Ticker(t).info or {}

    def g(key):
        v = info.get(key)
        return v if isinstance(v, (int, float)) else None

    out = {
        "ticker": t,
        "name": info.get("shortName") or info.get("longName") or t,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "marketCap": g("marketCap"),
        "revenueGrowth": g("revenueGrowth"),          # yoy, fraction
        "earningsGrowth": g("earningsGrowth"),
        "grossMargins": g("grossMargins"),
        "operatingMargins": g("operatingMargins"),
        "freeCashflow": g("freeCashflow"),
        "totalCash": g("totalCash"),
        "totalDebt": g("totalDebt"),
        "priceToSales": g("priceToSalesTrailing12Months"),
        "forwardPE": g("forwardPE"),
        "heldPercentInsiders": g("heldPercentInsiders"),
        "sharesOutstanding": g("sharesOutstanding"),
        "fiftyTwoWeekChange": g("52WeekChange"),
    }
    _cache[t] = (time.time(), out)
    return out


def _pts(value, bands):
    """bands: list of (threshold, points) descending; value >= threshold wins."""
    if value is None:
        return 0, "n/a"
    for th, p in bands:
        if value >= th:
            return p, None
    return 0, None


def multibagger_score(f: dict) -> dict:
    br = {}

    mc = f["marketCap"]
    if mc is None:
        br["smallBase"] = {"pts": 0, "max": 20, "note": "market cap unknown"}
    elif mc < 2e9:
        br["smallBase"] = {"pts": 20, "max": 20, "note": "micro/small cap (<$2B)"}
    elif mc < 1e10:
        br["smallBase"] = {"pts": 12, "max": 20, "note": "mid cap (<$10B)"}
    elif mc < 5e10:
        br["smallBase"] = {"pts": 5, "max": 20, "note": "large cap (<$50B)"}
    else:
        br["smallBase"] = {"pts": 0, "max": 20, "note": "mega cap — base too large"}

    p, _ = _pts(f["revenueGrowth"], [(0.30, 20), (0.15, 12), (0.05, 5)])
    br["revenueGrowth"] = {"pts": p, "max": 20,
                           "note": f"yoy revenue growth {f['revenueGrowth']:.0%}" if f["revenueGrowth"] is not None else "n/a"}

    p, _ = _pts(f["grossMargins"], [(0.60, 10), (0.40, 6), (0.25, 3)])
    br["grossMargin"] = {"pts": p, "max": 10,
                         "note": f"gross margin {f['grossMargins']:.0%}" if f["grossMargins"] is not None else "n/a"}

    fcf = f["freeCashflow"]
    br["freeCashflow"] = {"pts": 10 if (fcf or 0) > 0 else 0, "max": 10,
                          "note": "FCF positive" if (fcf or 0) > 0 else "FCF negative/unknown"}

    cash, debt = f["totalCash"], f["totalDebt"]
    ok = cash is not None and debt is not None and cash > debt
    br["balanceSheet"] = {"pts": 10 if ok else 0, "max": 10,
                          "note": "net cash" if ok else "net debt or unknown"}

    ps = f["priceToSales"]
    if ps is None:
        br["valuationRoom"] = {"pts": 0, "max": 10, "note": "P/S unknown"}
    elif ps < 3:
        br["valuationRoom"] = {"pts": 10, "max": 10, "note": f"P/S {ps:.1f} — cheap vs growth"}
    elif ps < 8:
        br["valuationRoom"] = {"pts": 5, "max": 10, "note": f"P/S {ps:.1f}"}
    else:
        br["valuationRoom"] = {"pts": 0, "max": 10, "note": f"P/S {ps:.1f} — rich"}

    ins = f["heldPercentInsiders"]
    br["insiderOwnership"] = {"pts": 10 if (ins or 0) > 0.05 else 0, "max": 10,
                              "note": f"insiders hold {ins:.0%}" if ins is not None else "n/a"}

    wk = f["fiftyTwoWeekChange"]
    br["momentum52w"] = {"pts": 10 if (wk or 0) > 0 else 0, "max": 10,
                         "note": f"52w change {wk:+.0%}" if wk is not None else "n/a"}

    score = sum(v["pts"] for v in br.values())
    band = ("High" if score >= 65 else "Moderate" if score >= 40 else "Low")
    return {"score": score, "max": 100, "band": band, "breakdown": br}


def screen(tickers: list[str]) -> list[dict]:
    rows = []
    for t in tickers:
        try:
            f = fetch(t)
            s = multibagger_score(f)
            try:
                f["price"] = data.quote(t)["price"]
            except Exception:
                f["price"] = None
            rows.append({**f, "multibagger": s})
        except Exception as e:
            rows.append({"ticker": t.upper(), "error": str(e)})
    rows.sort(key=lambda r: -(r.get("multibagger", {}).get("score", -1)))
    return rows
