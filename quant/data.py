"""Market data layer: yfinance fetch with simple TTL caching.

Supports multiple horizons:
  intraday  : 15m bars, 5 days     (short-term)
  swing     : 1h bars, 60 days     (short/medium)
  daily     : 1d bars, 2 years     (medium)
  weekly    : 1wk bars, 10 years   (long-term)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

RANGES = {
    "1W":  dict(period="5d",  interval="15m"),
    "1M":  dict(period="1mo", interval="1h"),
    "6M":  dict(period="6mo", interval="1d"),
    "1Y":  dict(period="1y",  interval="1d"),
    "2Y":  dict(period="2y",  interval="1d"),
    "5Y":  dict(period="5y",  interval="1d"),
    "10Y": dict(period="10y", interval="1wk"),
}

_TTL = {"15m": 120, "1h": 300, "1d": 600, "1wk": 3600}


@dataclass
class _Cache:
    store: dict = field(default_factory=dict)

    def get(self, key, ttl):
        hit = self.store.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        return None

    def put(self, key, value):
        self.store[key] = (time.time(), value)


_cache = _Cache()


def fetch_history(ticker: str, range_key: str = "2Y") -> pd.DataFrame:
    """Return OHLCV DataFrame indexed by timestamp."""
    spec = RANGES.get(range_key, RANGES["2Y"])
    key = (ticker.upper(), range_key)
    cached = _cache.get(key, _TTL.get(spec["interval"], 600))
    if cached is not None:
        return cached
    df = yf.Ticker(ticker).history(period=spec["period"], interval=spec["interval"],
                                   auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"No data returned for {ticker!r} ({range_key})")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    _cache.put(key, df)
    return df


def closes(ticker: str, range_key: str = "2Y") -> pd.Series:
    return fetch_history(ticker, range_key)["Close"]


def search(q: str) -> list[dict]:
    """Ticker autocomplete via Yahoo Finance's search endpoint."""
    q = q.strip()
    if not q:
        return []
    key = ("__search__", q.lower())
    cached = _cache.get(key, 3600)
    if cached is not None:
        return cached
    import requests
    r = requests.get(
        "https://query2.finance.yahoo.com/v1/finance/search",
        params={"q": q, "quotesCount": 8, "newsCount": 0},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=5,
    )
    r.raise_for_status()
    out = []
    for x in r.json().get("quotes", []):
        if x.get("symbol") and x.get("quoteType") in ("EQUITY", "ETF", "INDEX", "MUTUALFUND", None):
            out.append({
                "symbol": x["symbol"],
                "name": x.get("shortname") or x.get("longname") or "",
                "exch": x.get("exchDisp") or "",
            })
    _cache.put(key, out)
    return out


DISCOVERY_SCREENS = (
    "most_actives", "day_gainers", "day_losers", "small_cap_gainers",
    "growth_technology_stocks", "undervalued_growth_stocks",
    "aggressive_small_caps", "most_shorted_stocks",
)


def discover(screen: str = "most_actives", count: int = 25) -> list[dict]:
    """Market-wide ticker discovery via Yahoo's predefined screeners."""
    if screen not in DISCOVERY_SCREENS:
        raise ValueError(f"screen must be one of {DISCOVERY_SCREENS}")
    count = max(5, min(50, int(count)))
    key = ("__discover__", screen, count)
    cached = _cache.get(key, 300)
    if cached is not None:
        return cached

    quotes = None
    try:  # yfinance >= 0.2.54 ships a screener API (handles auth crumbs)
        if hasattr(yf, "screen"):
            quotes = (yf.screen(screen, count=count) or {}).get("quotes")
    except Exception:
        quotes = None
    if quotes is None:  # direct fallback
        import requests
        r = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved",
            params={"scrIds": screen, "count": count},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        quotes = r.json()["finance"]["result"][0]["quotes"]

    out = []
    for x in quotes or []:
        if not x.get("symbol"):
            continue
        out.append({
            "symbol": x["symbol"],
            "name": x.get("shortName") or x.get("longName") or "",
            "price": x.get("regularMarketPrice"),
            "changePct": x.get("regularMarketChangePercent"),
            "volume": x.get("regularMarketVolume"),
            "marketCap": x.get("marketCap"),
        })
    _cache.put(key, out)
    return out


def quote_from_closes(ticker: str, close: pd.Series) -> dict:
    """Build a quote payload from an already-fetched close series, avoiding a
    redundant network round trip when the caller already holds the data."""
    s = close.dropna()
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    return {
        "ticker": ticker.upper(),
        "price": round(last, 2),
        "change": round(last - prev, 2),
        "changePct": round(100 * (last / prev - 1), 2),
        "asOf": str(s.index[-1]),
    }


def quote(ticker: str) -> dict:
    return quote_from_closes(ticker, fetch_history(ticker, "6M")["Close"])


def history_payload(ticker: str, range_key: str) -> dict:
    df = fetch_history(ticker, range_key)
    return {
        "ticker": ticker.upper(),
        "range": range_key,
        "t": [str(i) for i in df.index],
        "o": [round(float(x), 4) for x in df["Open"]],
        "h": [round(float(x), 4) for x in df["High"]],
        "l": [round(float(x), 4) for x in df["Low"]],
        "c": [round(float(x), 4) for x in df["Close"]],
        "v": [int(x) for x in df["Volume"].fillna(0)],
    }
