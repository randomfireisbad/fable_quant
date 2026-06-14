"""Autonomous paper day-trader.

Runs LLM-driven trading sessions against the paper portfolio — on a schedule
during US market hours when enabled, or on demand. Each session the agent
reviews its positions, scans its universe with the platform's statistical
tools, executes paper trades within risk limits, and writes a journal entry.
Recent journal entries are fed back into the next session so it can keep a
running strategy and learn from its own mistakes.

Paper only: this module has no path to a live broker. (It may still queue
live-order *proposals*, which require human approval in the Live tab.)
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from . import agent, llm, portfolio

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CFG_FILE = os.path.join(_DATA, "trader_config.json")
_JOURNAL_FILE = os.path.join(_DATA, "trader_journal.json")
_lock = threading.Lock()
_state = {"running": False, "lastError": None}

DEFAULT_CFG = {
    "enabled": False,
    "intervalMin": 30,
    "maxSteps": 12,
    "universe": ["SPY", "QQQ", "NVDA", "TSLA", "AMD", "AAPL", "META", "AMZN"],
    "lastRun": None,
}

SYSTEM = """You are the paper-trading desk inside Fable Quant — a disciplined \
intraday-swing trader practicing on a $100k paper portfolio. Quotes are ~15 \
minutes delayed, so do not pretend to scalp; trade setups that survive a \
15-minute delay.

Your process each session:
1. get_portfolio — review positions and P&L. Decide if anything should be \
closed or trimmed (thesis broken, stop level breached, target reached).
2. Scan your universe with analyze_ticker (use horizon-appropriate judgment); \
check the statistics, not vibes: TSMOM t-stats, z-scores, ADF/VR evidence, \
GARCH vol, the walk-forward backtest Sharpes.
3. Hunt beyond the universe when it looks stale: discover_tickers \
(most_actives, day_gainers, small_cap_gainers, ...) surfaces market-wide \
candidates. ALWAYS run analyze_ticker on a discovered name before trading it \
— a screener hit is a lead, not a signal. Mention promising discoveries in \
WATCHING so future sessions follow up.
4. Execute paper trades you judge appropriate.

Hard risk limits (self-enforce):
- Max 25% of equity in any single position.
- Keep at least 10% cash.
- Every entry needs an explicit exit plan (stop and target) in its rationale.
- High forecast vol (GARCH) means smaller size — scale by ~15%/vol.

You will see your recent journal entries — maintain continuity: follow up on \
your own exit plans and note what worked and what didn't.

End with a journal entry in EXACTLY this format:
MARKET_VIEW: <1-2 sentences>
ACTIONS: <trades made this session and why, or "none">
WATCHING: <setups you're stalking for next session>
LESSONS: <what your past trades are teaching you>
"""


def _load_cfg() -> dict:
    try:
        with open(_CFG_FILE) as f:
            cfg = {**DEFAULT_CFG, **json.load(f)}
    except Exception:
        cfg = dict(DEFAULT_CFG)
    return cfg


def _save_cfg(cfg: dict):
    os.makedirs(_DATA, exist_ok=True)
    with open(_CFG_FILE, "w") as f:
        json.dump(cfg, f, indent=1)


def set_config(updates: dict) -> dict:
    with _lock:
        cfg = _load_cfg()
        if "enabled" in updates and updates["enabled"] is not None:
            cfg["enabled"] = bool(updates["enabled"])
        if "intervalMin" in updates and updates["intervalMin"]:
            cfg["intervalMin"] = max(5, min(240, int(updates["intervalMin"])))
        if "universe" in updates and updates["universe"]:
            cfg["universe"] = [t.strip().upper() for t in updates["universe"]
                               if t and t.strip()][:20]
        _save_cfg(cfg)
    return status()


def load_journal() -> list[dict]:
    try:
        with open(_JOURNAL_FILE) as f:
            out = json.load(f)
            return out if isinstance(out, list) else []
    except Exception:
        return []


def _append_journal(entry: dict):
    with _lock:
        j = load_journal()
        j.append(entry)
        os.makedirs(_DATA, exist_ok=True)
        with open(_JOURNAL_FILE, "w") as f:
            json.dump(j[-200:], f, indent=1)


def market_open() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def status() -> dict:
    cfg = _load_cfg()
    try:
        snap = portfolio.snapshot()
        equity = {"equity": snap["equity"], "totalReturnPct": snap["totalReturnPct"]}
    except Exception:
        equity = {}
    return {**cfg, "running": _state["running"], "marketOpen": market_open(),
            "lastError": _state["lastError"], "llmReady": llm.status().get("ready", False),
            **equity}


def _execute(name: str, args: dict) -> str:
    """Same toolset as the research agent, but paper trades are tagged."""
    if name == "paper_trade":
        try:
            from . import performance
            rec = portfolio.trade(args["ticker"], args["side"], args["qty"],
                                  args.get("rationale", ""), source="day-trader",
                                  signal=performance.signal_snapshot(args["ticker"]))
            return json.dumps({"executed": rec, "note": "paper trade only"}, default=str)
        except Exception as e:
            return f"Tool error (paper_trade): {e}"
    return agent._execute(name, args)


def run_session(trigger: str = "manual") -> bool:
    """Start a session in a background thread. Returns False if one is running."""
    if _state["running"]:
        return False
    if not llm.status().get("ready"):
        raise RuntimeError("LLM not ready — configure it via the LLM settings (top bar)")
    threading.Thread(target=_session, args=(trigger,), daemon=True).start()
    return True


def _session(trigger: str):
    _state["running"] = True
    _state["lastError"] = None
    started = datetime.now().isoformat(timespec="seconds")
    try:
        cfg = _load_cfg()
        snap = portfolio.snapshot()
        n_trades_before = len(snap["trades"])
        recent = load_journal()[-3:]
        recent_txt = "\n\n".join(
            f"[{e['ts']}] equity ${e.get('equity')}\n{e.get('memo', '')[:1200]}"
            for e in recent) or "(no prior sessions — this is your first)"

        goal = (
            f"Trading session start ({trigger}). "
            f"Market is {'OPEN' if market_open() else 'CLOSED — review/plan only, place entries cautiously'}.\n\n"
            f"Universe: {', '.join(cfg['universe'])}\n\n"
            f"Portfolio now: {json.dumps({k: snap[k] for k in ('cash', 'equity', 'totalReturnPct', 'positions')}, default=str)}\n\n"
            f"Your recent journal:\n{recent_txt}\n\n"
            f"Run your session now."
        )

        p = llm.provider()
        memo, transcript = p.tool_loop(SYSTEM, goal, agent._tools_spec(),
                                       _execute, max_steps=cfg.get("maxSteps", 12))

        after = portfolio.snapshot()
        new_trades = after["trades"][:max(0, len(after["trades"]) - n_trades_before)]
        _append_journal({
            "ts": started, "trigger": trigger,
            "provider": p.name,
            "steps": len(transcript),
            "trades": new_trades,
            "equity": after["equity"], "returnPct": after["totalReturnPct"],
            "memo": memo or "(no memo)",
        })
        with _lock:
            cfg = _load_cfg()
            cfg["lastRun"] = started
            _save_cfg(cfg)
    except Exception as e:
        traceback.print_exc()
        _state["lastError"] = str(e)
        _append_journal({"ts": started, "trigger": trigger, "error": str(e),
                         "memo": f"Session failed: {e}"})
    finally:
        _state["running"] = False


def start_scheduler():
    """Daemon loop: run a session every intervalMin during market hours."""
    def _loop():
        while True:
            time.sleep(60)
            try:
                cfg = _load_cfg()
                if not cfg["enabled"] or _state["running"] or not market_open():
                    continue
                if not llm.status().get("ready"):
                    continue
                last = cfg.get("lastRun")
                due = True
                if last:
                    elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
                    due = elapsed >= cfg["intervalMin"] * 60
                if due:
                    _session("scheduled")
            except Exception:
                traceback.print_exc()
    threading.Thread(target=_loop, daemon=True, name="fq-trader-scheduler").start()
