"""Paper-trading portfolio: positions, trade log, mark-to-market P&L.
Persists to data/portfolio.json. Starts with $100,000 paper cash."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from . import data

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_FILE = os.path.join(_DATA, "portfolio.json")
_lock = threading.Lock()

START_CASH = 100_000.0


def _load() -> dict:
    try:
        with open(_FILE) as f:
            return json.load(f)
    except Exception:
        return {"cash": START_CASH, "positions": {}, "trades": []}


def _save(p: dict):
    os.makedirs(_DATA, exist_ok=True)
    with open(_FILE, "w") as f:
        json.dump(p, f, indent=1)


def trade(ticker: str, side: str, qty: float, rationale: str = "",
          source: str = "manual", signal: dict | None = None) -> dict:
    """Execute a paper trade at the live quote price."""
    t, side = ticker.upper(), side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    qty = float(qty)
    if qty <= 0:
        raise ValueError("qty must be positive")
    price = data.quote(t)["price"]

    with _lock:
        p = _load()
        pos = p["positions"].get(t, {"qty": 0.0, "avgCost": 0.0})
        cost = qty * price
        if side == "buy":
            if cost > p["cash"]:
                raise ValueError(f"Insufficient paper cash (${p['cash']:.2f} < ${cost:.2f})")
            new_qty = pos["qty"] + qty
            pos["avgCost"] = (pos["avgCost"] * pos["qty"] + cost) / new_qty
            pos["qty"] = new_qty
            p["cash"] -= cost
        else:
            if qty > pos["qty"]:
                raise ValueError(f"Cannot sell {qty}; only hold {pos['qty']}")
            pos["qty"] -= qty
            p["cash"] += cost
        if pos["qty"] > 1e-9:
            p["positions"][t] = pos
        else:
            p["positions"].pop(t, None)
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "ticker": t,
               "side": side, "qty": qty, "price": price,
               "rationale": rationale, "source": source}
        if signal:
            rec["signal"] = signal  # model state at trade time, for attribution
        p["trades"].append(rec)
        _save(p)
    return rec


def snapshot() -> dict:
    p = _load()
    positions, total_value = [], 0.0
    for t, pos in p["positions"].items():
        try:
            px = data.quote(t)["price"]
        except Exception:
            px = pos["avgCost"]
        mv = pos["qty"] * px
        total_value += mv
        positions.append({
            "ticker": t, "qty": pos["qty"], "avgCost": round(pos["avgCost"], 2),
            "price": px, "marketValue": round(mv, 2),
            "unrealizedPnl": round(mv - pos["qty"] * pos["avgCost"], 2),
            "unrealizedPct": round(100 * (px / pos["avgCost"] - 1), 2) if pos["avgCost"] else 0,
        })
    equity = p["cash"] + total_value
    return {
        "cash": round(p["cash"], 2),
        "positionsValue": round(total_value, 2),
        "equity": round(equity, 2),
        "totalReturnPct": round(100 * (equity / START_CASH - 1), 2),
        "positions": sorted(positions, key=lambda x: -x["marketValue"]),
        "trades": p["trades"][-50:][::-1],
    }


def reset():
    _save({"cash": START_CASH, "positions": {}, "trades": []})
