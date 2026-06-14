"""Research agent: an LLM loop with access to the platform's quant tools.

The agent can screen fundamentals, run the full statistical analysis, test
pairs, do web research (provider permitting), inspect the paper portfolio, and
log paper trades. It never touches a live broker. Runs execute in background
threads; poll /api/agent/run/{id} for transcript + memo.
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime

from . import data, fundamentals, llm, meanrev, portfolio

SYSTEM = """You are the research agent inside Fable Quant, a quantitative \
trading research platform. Use the tools to gather evidence before concluding. \
Statistical outputs come from peer-reviewed methods (momentum: Jegadeesh-Titman, \
Moskowitz-Ooi-Pedersen; mean reversion: ADF, variance ratio, OU half-life; \
volatility: GARCH(1,1); factors: Fama-French-style regression).

Rules:
- Ground every claim in tool output or cited web research.
- Distinguish statistical significance from noise; report t-stats/p-values.
- You can place paper trades directly, and may PROPOSE live orders via \
propose_live_order — but you can never execute live orders; a human reviews \
every proposal. Size positions sensibly vs available cash and explain each.
- Finish with a structured research memo: GOAL, FINDINGS, ACTIONS TAKEN (if \
any), CANDIDATES (ticker / direction / rationale / key stats), RISKS, NEXT STEPS.
"""

_J = lambda o: json.dumps(o, default=str)


def _condense_analysis(a: dict) -> dict:
    return {
        "ticker": a["ticker"], "price": a["quote"]["price"],
        "rating": a["composite"]["rating"], "compositeScore": a["composite"]["score"],
        "componentScores": a["composite"]["components"],
        "priceTarget3mo": a["priceTarget"],
        "momentum": {"mom12_1": a["momentum"]["mom12_1"],
                     "tsmomT": a["momentum"]["tsmom"]["tStat"],
                     "trend": a["momentum"].get("trend")},
        "meanReversion": {"adfP": a["meanReversion"]["adf"]["pValue"],
                          "vr": a["meanReversion"]["varianceRatio"]["vr"],
                          "halfLife": a["meanReversion"]["halfLifeDays"],
                          "z20": a["meanReversion"]["zScore20"]},
        "volatility": {"garchFcst": a["volatility"]["garch"]["annVolForecast21d"],
                       "sharpe": a["volatility"]["risk"]["sharpe"],
                       "maxDD": a["volatility"]["risk"]["maxDrawdown"]},
        "factors": ({"alphaAnn": a["factors"]["alphaAnnual"],
                     "alphaT": a["factors"]["alphaTStat"],
                     "betaMkt": a["factors"]["betas"]["MKT"]}
                    if a.get("factors") else None),
        "walkForwardBacktest5y": (a.get("backtest")
                                  if (a.get("backtest") or {}).get("ok") else None),
        "signalAgreement": a["composite"].get("confidence"),
    }


def _tools_spec() -> list[dict]:
    S = lambda props, req: {"type": "object", "properties": props, "required": req}
    str_p = {"type": "string"}
    return [
        {"name": "get_quote", "description": "Latest price and daily change for a ticker.",
         "input_schema": S({"ticker": str_p}, ["ticker"])},
        {"name": "analyze_ticker",
         "description": "Run the full statistical suite (momentum, mean reversion, GARCH vol, factor regression) on a ticker. Returns scores, rating, and 3-month price target.",
         "input_schema": S({"ticker": str_p}, ["ticker"])},
        {"name": "screen_fundamentals",
         "description": "Fundamentals + multibagger screen (0-100) for up to 10 tickers.",
         "input_schema": S({"tickers": {"type": "array", "items": str_p}}, ["tickers"])},
        {"name": "pairs_test",
         "description": "Engle-Granger cointegration test and spread z-score for two tickers.",
         "input_schema": S({"a": str_p, "b": str_p}, ["a", "b"])},
        {"name": "search_tickers", "description": "Find ticker symbols by company name or keyword.",
         "input_schema": S({"query": str_p}, ["query"])},
        {"name": "discover_tickers",
         "description": "Discover tickers market-wide via screeners — use this to find candidates beyond your given universe/watchlist. Screens: most_actives, day_gainers, day_losers, small_cap_gainers, growth_technology_stocks, undervalued_growth_stocks, aggressive_small_caps, most_shorted_stocks. Verify any candidate with analyze_ticker before trading it.",
         "input_schema": S({"screen": {"type": "string",
                                       "enum": ["most_actives", "day_gainers", "day_losers",
                                                "small_cap_gainers", "growth_technology_stocks",
                                                "undervalued_growth_stocks", "aggressive_small_caps",
                                                "most_shorted_stocks"]},
                            "count": {"type": "number"}}, ["screen"])},
        {"name": "web_research",
         "description": "Live web research on market trends, news, or events (if the LLM provider supports it).",
         "input_schema": S({"query": str_p}, ["query"])},
        {"name": "get_portfolio", "description": "Current paper portfolio: cash, positions, P&L.",
         "input_schema": S({}, [])},
        {"name": "paper_trade",
         "description": "Log a PAPER trade (no real money) at the live price. Include a rationale.",
         "input_schema": S({"ticker": str_p,
                            "side": {"type": "string", "enum": ["buy", "sell"]},
                            "qty": {"type": "number"},
                            "rationale": str_p}, ["ticker", "side", "qty", "rationale"])},
        {"name": "performance_review",
         "description": "Trade-outcome attribution: closed round trips bucketed by the model rating/score/source at entry, with win rates and sample-size warnings. Consult before sizing decisions; respect the warnings — small samples are noise.",
         "input_schema": S({}, [])},
        {"name": "propose_live_order",
         "description": "Propose an order for HUMAN review in the Live tab. You can never execute orders; a human approves or rejects every proposal. Include thorough rationale with the statistics that support it.",
         "input_schema": S({"ticker": str_p,
                            "side": {"type": "string", "enum": ["buy", "sell"]},
                            "qty": {"type": "number"},
                            "rationale": str_p}, ["ticker", "side", "qty", "rationale"])},
    ]


def _execute(name: str, args: dict) -> str:
    from .pipeline import run_analysis
    try:
        if name == "get_quote":
            return _J(data.quote(args["ticker"]))
        if name == "analyze_ticker":
            return _J(_condense_analysis(run_analysis(args["ticker"])))
        if name == "screen_fundamentals":
            return _J(fundamentals.screen(args["tickers"][:10]))
        if name == "pairs_test":
            return _J(meanrev.pairs(data.closes(args["a"], "2Y"),
                                    data.closes(args["b"], "2Y"),
                                    args["a"], args["b"]))
        if name == "search_tickers":
            return _J(data.search(args["query"]))
        if name == "discover_tickers":
            return _J(data.discover(args.get("screen", "most_actives"),
                                    int(args.get("count", 25))))
        if name == "web_research":
            p = llm.provider()
            if not p.supports_web:
                return ("Web research unavailable on this provider (local model). "
                        "Proceed with platform data and flag the gap.")
            return p.research(args["query"], max_tokens=2000)
        if name == "get_portfolio":
            return _J(portfolio.snapshot())
        if name == "performance_review":
            from . import performance
            return _J(performance.review())
        if name == "paper_trade":
            from . import performance
            rec = portfolio.trade(args["ticker"], args["side"], args["qty"],
                                  args.get("rationale", ""), source="agent",
                                  signal=performance.signal_snapshot(args["ticker"]))
            return _J({"executed": rec, "note": "paper trade only"})
        if name == "propose_live_order":
            from . import orders
            rec = orders.propose(args["ticker"], args["side"], args["qty"],
                                 args.get("rationale", ""), source="agent")
            return _J({"proposed": rec,
                       "note": "queued for human approval in the Live tab — NOT executed"})
        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool error ({name}): {e}"


# ----------------------------------------------------------- run management
_runs: dict[str, dict] = {}


def start_run(goal: str, max_steps: int = 10) -> str:
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {"id": run_id, "goal": goal, "status": "running",
                     "started": datetime.now().isoformat(timespec="seconds"),
                     "provider": llm.provider().name,
                     "transcript": [], "memo": None, "error": None}
    threading.Thread(target=_run, args=(run_id, goal, max_steps), daemon=True).start()
    return run_id


def _run(run_id: str, goal: str, max_steps: int):
    rec = _runs[run_id]
    try:
        p = llm.provider()

        def execute(name, args):
            out = _execute(name, args)
            return out

        # live transcript: wrap execute to append as we go
        def tracked_execute(name, args):
            out = execute(name, args)
            rec["transcript"].append({"type": "tool", "name": name,
                                      "input": args, "output": out[:2000]})
            return out

        memo, transcript = p.tool_loop(SYSTEM, goal, _tools_spec(),
                                       tracked_execute, max_steps=max_steps)
        # provider also returns its own transcript (incl. thoughts); prefer it
        rec["transcript"] = transcript
        rec["memo"] = memo
        rec["status"] = "done"
    except Exception as e:
        traceback.print_exc()
        rec["status"] = "error"
        rec["error"] = str(e)


def get_run(run_id: str) -> dict | None:
    return _runs.get(run_id)


def list_runs() -> list[dict]:
    return [{"id": r["id"], "goal": r["goal"], "status": r["status"],
             "started": r["started"]} for r in _runs.values()]
