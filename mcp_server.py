"""Fable Quant MCP connector — exposes the platform to Claude Desktop.

Add to Claude Desktop (Settings → Developer → Edit Config), adjusting paths:

{
  "mcpServers": {
    "fable-quant": {
      "command": "python3",
      "args": ["/path/to/Fable Quant/mcp_server.py"]
    }
  }
}

Use the same Python that has this project's requirements installed (give the
absolute path to your venv's python if needed). Claude Desktop then gets the
platform's research tools. Deliberately NOT exposed: order approval and
broker mode — those decisions stay with the human in the Live tab.

Run `pip install mcp` if the SDK is missing.
"""
from __future__ import annotations

import json
import os
import sys

# Ensure the project root is importable regardless of Claude Desktop's cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # pip install mcp

from quant import data, fundamentals, meanrev, orders, portfolio
from quant.agent import _condense_analysis
from quant.pipeline import run_analysis

mcp = FastMCP(
    "fable-quant",
    instructions=(
        "Quantitative research platform. Statistical methods are literature-"
        "grounded (Jegadeesh-Titman & Moskowitz-Ooi-Pedersen momentum; ADF/"
        "variance-ratio/OU mean reversion; GJR-GARCH volatility; Fama-French-"
        "style factor regression; walk-forward backtests). Ratings blend the "
        "four models with equal weights and shrink toward Hold on "
        "disagreement. paper_trade affects only the $100k paper portfolio. "
        "propose_live_order only queues a proposal for HUMAN approval in the "
        "platform's Live tab — nothing here can execute a real order."),
)

_J = lambda o: json.dumps(o, default=str)


@mcp.tool()
def get_quote(ticker: str) -> str:
    """Latest price and daily change for a ticker (Yahoo Finance, ~15min delayed)."""
    return _J(data.quote(ticker))


@mcp.tool()
def analyze(ticker: str, horizon: str = "medium") -> str:
    """Full statistical analysis of a ticker: momentum, mean reversion, GARCH
    volatility, factor regression, composite rating, price target with 80%
    interval, and a 5y walk-forward backtest. horizon: short (21d target, 1Y
    window), medium (63d, 2Y), or long (126d, 5Y)."""
    return _J(_condense_analysis(run_analysis(ticker, horizon=horizon)))


@mcp.tool()
def multibagger_screen(tickers: list[str]) -> str:
    """Fundamentals screen scoring 3-10x potential 0-100 (small base, revenue
    growth, margins, balance sheet, valuation room, insiders, 52w momentum).
    Max 10 tickers; each fetch takes ~2s."""
    return _J(fundamentals.screen(tickers[:10]))


@mcp.tool()
def pairs_test(ticker_a: str, ticker_b: str) -> str:
    """Engle-Granger cointegration test for a pairs trade: t-stat, p-value,
    hedge ratio, spread z-score and half-life."""
    return _J(meanrev.pairs(data.closes(ticker_a, "2Y"),
                            data.closes(ticker_b, "2Y"), ticker_a, ticker_b))


@mcp.tool()
def search_tickers(query: str) -> str:
    """Find ticker symbols by company name or keyword."""
    return _J(data.search(query))


@mcp.tool()
def discover_tickers(screen: str = "most_actives", count: int = 25) -> str:
    """Discover tickers market-wide via Yahoo screeners. Screens:
    most_actives, day_gainers, day_losers, small_cap_gainers,
    growth_technology_stocks, undervalued_growth_stocks,
    aggressive_small_caps, most_shorted_stocks. Verify candidates with
    analyze() before acting on them."""
    return _J(data.discover(screen, count))


@mcp.tool()
def get_paper_portfolio() -> str:
    """Paper portfolio state: cash, positions, mark-to-market P&L, recent trades."""
    return _J(portfolio.snapshot())


@mcp.tool()
def paper_trade(ticker: str, side: str, qty: float, rationale: str) -> str:
    """Execute a PAPER trade (simulated money only) at the live price."""
    from quant import performance
    return _J({"executed": portfolio.trade(ticker, side, qty, rationale,
                                           source="claude-mcp",
                                           signal=performance.signal_snapshot(ticker)),
               "note": "paper trade only"})


@mcp.tool()
def performance_review() -> str:
    """Trade-outcome attribution: closed round trips bucketed by the model
    rating/score/source at entry, with win rates, average returns, and
    sample-size warnings. The evidence base for model improvements — heed the
    warnings before concluding anything from small samples."""
    from quant import performance
    return _J(performance.review())


@mcp.tool()
def log_improvement(observation: str, change: str = "", evidence: str = "") -> str:
    """Record an entry in the model improvement log (observation, the change
    made or proposed, and the evidence). Used to keep an audit trail of every
    model adjustment."""
    from quant import performance
    return _J(performance.log_add(observation, change, "claude-mcp", evidence))


@mcp.tool()
def propose_live_order(ticker: str, side: str, qty: float, rationale: str) -> str:
    """Queue an order PROPOSAL for human review in the platform's Live tab.
    This never executes anything — the owner approves or rejects each
    proposal. Include the statistical evidence in the rationale."""
    return _J({"proposed": orders.propose(ticker, side, qty, rationale,
                                          source="claude-mcp"),
               "note": "queued for human approval — NOT executed"})


@mcp.tool()
def pending_orders() -> str:
    """List order proposals awaiting human approval, plus recent decisions."""
    return _J(orders.list_orders()[:25])


if __name__ == "__main__":
    mcp.run()
