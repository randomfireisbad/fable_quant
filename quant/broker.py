"""Broker abstraction.

PaperBroker is the default. The mode (paper | live) is switchable from the
Live tab and persists to data/broker_config.json. Live mode additionally
requires, on the backend:
  1. pip install robin_stocks
  2. RH_USERNAME / RH_PASSWORD env vars (MFA may require a TOTP secret) —
     credentials are NEVER accepted through the web UI.
Review every order path yourself before going live. Automated brokerage
trading carries real financial risk and may be constrained by your broker's
terms of service.
"""
from __future__ import annotations

import importlib.util
import json
import os
import threading

from . import portfolio

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CFG = os.path.join(_DATA, "broker_config.json")
_lock = threading.Lock()


def get_mode() -> str:
    try:
        with open(_CFG) as f:
            mode = json.load(f).get("mode", "paper")
            return mode if mode in ("paper", "live") else "paper"
    except Exception:
        return "paper"


def set_mode(mode: str) -> dict:
    if mode not in ("paper", "live"):
        raise ValueError("mode must be 'paper' or 'live'")
    with _lock:
        os.makedirs(_DATA, exist_ok=True)
        with open(_CFG, "w") as f:
            json.dump({"mode": mode}, f)
    return status()


def _creds_present() -> bool:
    return bool(os.environ.get("RH_USERNAME") and os.environ.get("RH_PASSWORD"))


def _lib_present() -> bool:
    return importlib.util.find_spec("robin_stocks") is not None


def status() -> dict:
    mode = get_mode()
    ready = _creds_present() and _lib_present()
    hint = None
    if not ready:
        missing = []
        if not _lib_present():
            missing.append("pip install robin_stocks")
        if not _creds_present():
            missing.append("set RH_USERNAME / RH_PASSWORD env vars on the server")
        hint = "; ".join(missing)
    return {
        "mode": mode,
        "broker": "robinhood" if mode == "live" else "paper",
        "liveReady": ready,
        "liveEnabled": mode == "live",
        "readyHint": hint,
        "note": ("LIVE — approved orders go to Robinhood" if mode == "live"
                 else "Paper mode — approved orders execute in the paper portfolio only"),
    }


class Broker:
    name = "base"

    def place_order(self, ticker: str, side: str, qty: float,
                    rationale: str = "", source: str = "manual",
                    signal: dict | None = None) -> dict:
        raise NotImplementedError

    def snapshot(self) -> dict:
        raise NotImplementedError


class PaperBroker(Broker):
    name = "paper"

    def place_order(self, ticker, side, qty, rationale="", source="manual",
                    signal=None):
        return portfolio.trade(ticker, side, qty, rationale, source, signal=signal)

    def snapshot(self):
        return portfolio.snapshot()


class RobinhoodBroker(Broker):
    """Live adapter. Mirrors orders to the paper portfolio for tracking.
    Credentials come from server env vars only — never from the web UI."""
    name = "robinhood"

    def __init__(self):
        if not _lib_present():
            raise RuntimeError("robin_stocks not installed — run: pip install robin_stocks")
        if not _creds_present():
            raise RuntimeError("RH_USERNAME / RH_PASSWORD env vars not set on the server")
        import robin_stocks.robinhood as rh
        self._rh = rh
        rh.login(os.environ["RH_USERNAME"], os.environ["RH_PASSWORD"])

    def place_order(self, ticker, side, qty, rationale="", source="manual",
                    signal=None):
        fn = (self._rh.orders.order_buy_market if side == "buy"
              else self._rh.orders.order_sell_market)
        result = fn(ticker.upper(), qty)
        portfolio.trade(ticker, side, qty, rationale,
                        source=f"{source}(live-mirror)", signal=signal)
        return {"live": True, "broker": "robinhood", "result": result}

    def snapshot(self):
        return {"holdings": self._rh.account.build_holdings(),
                "profile": self._rh.profiles.load_account_profile()}


def status() -> dict:
    wants_live = os.environ.get("FQ_BROKER") == "robinhood"
    enabled = os.environ.get("FQ_ENABLE_LIVE_TRADING") == "1"
    return {
        "broker": "robinhood" if (wants_live and enabled) else "paper",
        "liveConfigured": wants_live,
        "liveEnabled": wants_live and enabled,
        "note": ("LIVE — approved orders go to Robinhood" if (wants_live and enabled)
                 else "Paper mode — approved orders execute in the paper portfolio only"),
    }


def get_broker() -> Broker:
    """Paper broker unless the owner has switched the Live tab to live mode.
    RobinhoodBroker raises (and the order is marked failed) if the backend
    isn't actually configured for live trading."""
    return RobinhoodBroker() if get_mode() == "live" else PaperBroker()
