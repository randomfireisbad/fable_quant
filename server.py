"""Fable Quant — quantitative research platform server.

Run:  pip install -r requirements.txt
      uvicorn server:app --reload
Open: http://127.0.0.1:8000
"""
from __future__ import annotations

import io
import json
import time
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from quant import (agent, backtest, broker, data, factors, fundamentals, llm,
                   longterm, meanrev, momentum, orders, performance, portfolio,
                   rating, report, trader, volatility)

trader.start_scheduler()

app = FastAPI(title="Fable Quant")

_analysis_cache: dict[str, tuple[float, dict]] = {}
_ANALYSIS_TTL = 600


def _err(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/search")
def api_search(q: str):
    try:
        return data.search(q)
    except Exception:
        return []  # autocomplete failures should be silent


@app.get("/api/discover")
def api_discover(screen: str = "most_actives", count: int = 25):
    try:
        return data.discover(screen, count)
    except Exception as e:
        _err(e)


@app.get("/api/quote/{ticker}")
def api_quote(ticker: str):
    try:
        return data.quote(ticker)
    except Exception as e:
        _err(e)


@app.get("/api/history/{ticker}")
def api_history(ticker: str, range: str = "1Y"):
    try:
        return data.history_payload(ticker, range)
    except Exception as e:
        _err(e)


from quant.pipeline import run_analysis  # shared with agent + MCP connector


@app.get("/api/analyze/{ticker}")
def api_analyze(ticker: str, force: bool = False, horizon: str = "medium"):
    try:
        return run_analysis(ticker, force, horizon)
    except Exception as e:
        traceback.print_exc()
        _err(e)


@app.get("/api/pairs")
def api_pairs(a: str, b: str):
    try:
        return meanrev.pairs(data.closes(a, "2Y"), data.closes(b, "2Y"), a, b)
    except Exception as e:
        _err(e)


@app.get("/api/report/{ticker}")
def api_report(ticker: str, horizon: str = "medium"):
    try:
        return report.build(ticker.upper(), run_analysis(ticker, horizon=horizon))
    except Exception as e:
        traceback.print_exc()
        _err(e)


@app.get("/api/report/{ticker}/pdf")
def api_report_pdf(ticker: str, horizon: str = "medium"):
    try:
        rep = report.build(ticker.upper(), run_analysis(ticker, horizon=horizon))
        import tempfile, os
        path = os.path.join(tempfile.gettempdir(), f"{ticker.upper()}_report.pdf")
        report.to_pdf(rep, path)
        return FileResponse(path, media_type="application/pdf",
                            filename=f"{ticker.upper()}_quant_report.pdf")
    except Exception as e:
        traceback.print_exc()
        _err(e)


# ---------------------------------------------------------------- long-term
class ScreenReq(BaseModel):
    tickers: list[str]


class TradeReq(BaseModel):
    ticker: str
    side: str
    qty: float
    rationale: str = ""


class AgentReq(BaseModel):
    goal: str
    maxSteps: int = 10


class LLMConfigReq(BaseModel):
    provider: str | None = None
    anthropicKey: str | None = None
    anthropicModel: str | None = None
    ollamaUrl: str | None = None
    ollamaModel: str | None = None


@app.get("/api/llm/status")
def api_llm_status():
    return llm.status()


@app.get("/api/llm/config")
def api_llm_config():
    return llm.get_config_masked()


@app.post("/api/llm/config")
def api_llm_config_set(req: LLMConfigReq):
    return llm.set_config(req.model_dump())


@app.get("/api/fundamentals/{ticker}")
def api_fundamentals(ticker: str):
    try:
        f = fundamentals.fetch(ticker)
        return {**f, "multibagger": fundamentals.multibagger_score(f)}
    except Exception as e:
        _err(e)


@app.post("/api/longterm/screen")
def api_lt_screen(req: ScreenReq):
    if not req.tickers or len(req.tickers) > 30:
        raise HTTPException(400, "Provide 1-30 tickers")
    return fundamentals.screen(req.tickers)


@app.post("/api/longterm/thesis/{ticker}")
def api_lt_thesis(ticker: str):
    try:
        return longterm.generate_thesis(ticker)
    except Exception as e:
        traceback.print_exc()
        _err(e)


@app.get("/api/longterm/research")
def api_lt_research():
    return longterm.saved_research()


@app.delete("/api/longterm/research/{ticker}")
def api_lt_research_delete(ticker: str):
    longterm.delete_research(ticker)
    return {"ok": True}


# ---------------------------------------------------------------- portfolio
@app.get("/api/portfolio")
def api_portfolio():
    return portfolio.snapshot()


@app.post("/api/portfolio/trade")
def api_portfolio_trade(req: TradeReq):
    try:
        return portfolio.trade(req.ticker, req.side, req.qty, req.rationale,
                               signal=performance.signal_snapshot(req.ticker))
    except Exception as e:
        _err(e)


@app.post("/api/portfolio/reset")
def api_portfolio_reset():
    portfolio.reset()
    return {"ok": True}


# ---------------------------------------------------------- order proposals
class ProposeReq(BaseModel):
    ticker: str
    side: str
    qty: float
    rationale: str = ""
    source: str = "manual"


class BrokerModeReq(BaseModel):
    mode: str


@app.get("/api/broker/status")
def api_broker_status():
    return broker.status()


@app.post("/api/broker/mode")
def api_broker_mode(req: BrokerModeReq):
    try:
        return broker.set_mode(req.mode)
    except Exception as e:
        _err(e)


@app.get("/api/orders")
def api_orders(status: str | None = None):
    return orders.list_orders(status)


@app.post("/api/orders/propose")
def api_orders_propose(req: ProposeReq):
    try:
        return orders.propose(req.ticker, req.side, req.qty, req.rationale, req.source)
    except Exception as e:
        _err(e)


@app.post("/api/orders/{order_id}/approve")
def api_orders_approve(order_id: str):
    try:
        return orders.approve(order_id)
    except Exception as e:
        _err(e)


@app.post("/api/orders/{order_id}/reject")
def api_orders_reject(order_id: str):
    try:
        return orders.reject(order_id)
    except Exception as e:
        _err(e)


# ----------------------------------------------- performance & model review
class ImprovementReq(BaseModel):
    observation: str
    change: str = ""
    evidence: str = ""
    author: str = "user"


@app.get("/api/performance/review")
def api_performance_review():
    try:
        return performance.review()
    except Exception as e:
        traceback.print_exc()
        _err(e)


@app.get("/api/performance/log")
def api_performance_log():
    return performance.log_list()[::-1]


@app.post("/api/performance/log")
def api_performance_log_add(req: ImprovementReq):
    try:
        return performance.log_add(req.observation, req.change, req.author,
                                   req.evidence)
    except Exception as e:
        _err(e)


# --------------------------------------------------------- paper day-trader
class TraderConfigReq(BaseModel):
    enabled: bool | None = None
    intervalMin: int | None = None
    universe: list[str] | None = None


@app.get("/api/trader/status")
def api_trader_status():
    return trader.status()


@app.post("/api/trader/config")
def api_trader_config(req: TraderConfigReq):
    try:
        return trader.set_config(req.model_dump())
    except Exception as e:
        _err(e)


@app.post("/api/trader/run")
def api_trader_run():
    try:
        started = trader.run_session("manual")
        return {"started": started,
                "note": None if started else "a session is already running"}
    except Exception as e:
        _err(e)


@app.get("/api/trader/journal")
def api_trader_journal():
    return trader.load_journal()[::-1][:30]


# --------------------------------------------------- Claude Desktop connector
@app.get("/api/connector/config")
def api_connector_config():
    import os
    import sys
    root = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(root, "mcp_server.py")
    snippet = {
        "mcpServers": {
            "fable-quant": {
                "command": sys.executable,
                "args": [script],
            }
        }
    }
    try:
        import mcp  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    return {"snippet": json.dumps(snippet, indent=2), "scriptPath": script,
            "python": sys.executable, "mcpSdkInstalled": sdk}


# -------------------------------------------------------------------- agent
@app.post("/api/agent/run")
def api_agent_run(req: AgentReq):
    if not req.goal.strip():
        raise HTTPException(400, "Goal is required")
    st = llm.status()
    if not st.get("ready"):
        raise HTTPException(400, f"LLM not ready ({st['provider']}): {st.get('hint', '')}")
    return {"runId": agent.start_run(req.goal, min(max(req.maxSteps, 1), 20))}


@app.get("/api/agent/run/{run_id}")
def api_agent_get(run_id: str):
    r = agent.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@app.get("/api/agent/runs")
def api_agent_list():
    return agent.list_runs()


app.mount("/", StaticFiles(directory="static", html=True), name="static")
