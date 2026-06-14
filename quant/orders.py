"""Order proposal queue — the human-in-the-loop gate for live trading.

Anything (the research agent, Claude in Cowork via the queue file, or a
human) may PROPOSE an order. Nothing executes until a human approves it in
the Live tab. On approval the order is routed to the configured broker —
the paper broker by default; Robinhood only if the owner has deliberately
enabled live trading (see quant/broker.py).

Queue persists to data/order_queue.json so external tools (e.g. Claude in
Cowork, which can write files in this project) can append proposals with
status "pending".
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime

from . import broker as broker_mod
from . import data

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_FILE = os.path.join(_DATA, "order_queue.json")
_lock = threading.Lock()

VALID_STATUS = ("pending", "executed", "rejected", "failed")


def _load() -> list[dict]:
    try:
        with open(_FILE) as f:
            out = json.load(f)
            return out if isinstance(out, list) else []
    except Exception:
        return []


def _save(orders: list[dict]):
    os.makedirs(_DATA, exist_ok=True)
    with open(_FILE, "w") as f:
        json.dump(orders, f, indent=1)


def propose(ticker: str, side: str, qty: float, rationale: str,
            source: str = "manual") -> dict:
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    qty = float(qty)
    if qty <= 0:
        raise ValueError("qty must be positive")
    try:
        px = data.quote(ticker)["price"]
    except Exception:
        px = None
    rec = {
        "id": uuid.uuid4().hex[:10],
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ticker": ticker.upper(), "side": side, "qty": qty,
        "priceAtProposal": px,
        "rationale": rationale or "(none given)",
        "source": source,
        "status": "pending",
        "result": None,
    }
    with _lock:
        orders = _load()
        orders.append(rec)
        _save(orders)
    return rec


def list_orders(status: str | None = None) -> list[dict]:
    orders = _load()
    # tolerate hand-written entries: fill defaults
    for o in orders:
        o.setdefault("id", uuid.uuid4().hex[:10])
        o.setdefault("status", "pending")
        o.setdefault("source", "external")
        o.setdefault("ts", "")
    if status:
        orders = [o for o in orders if o.get("status") == status]
    return sorted(orders, key=lambda o: o.get("ts", ""), reverse=True)


def _update(order_id: str, **fields) -> dict:
    with _lock:
        orders = _load()
        for o in orders:
            if o.get("id") == order_id:
                o.update(fields)
                _save(orders)
                return o
    raise ValueError(f"order {order_id!r} not found")


def approve(order_id: str) -> dict:
    """Human approval: route to the configured broker (paper by default)."""
    target = next((o for o in list_orders() if o.get("id") == order_id), None)
    if target is None:
        raise ValueError(f"order {order_id!r} not found")
    if target.get("status") != "pending":
        raise ValueError(f"order is {target.get('status')}, not pending")
    try:
        from . import performance
        b = broker_mod.get_broker()
        result = b.place_order(target["ticker"], target["side"], target["qty"],
                               rationale=target.get("rationale", ""),
                               source=f"approved:{target.get('source', '?')}",
                               signal=performance.signal_snapshot(target["ticker"],
                                                                  allow_run=True))
        return _update(order_id, status="executed",
                       result={"broker": b.name, "detail": result},
                       executedTs=datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        return _update(order_id, status="failed", result={"error": str(e)})


def reject(order_id: str) -> dict:
    return _update(order_id, status="rejected")
