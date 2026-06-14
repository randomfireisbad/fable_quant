# Fable Quant

A local quantitative research platform: live market data, academically grounded
statistical models, ratings, price targets, and printable research reports.

## Run

```bash
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://127.0.0.1:8000

## Sections

The platform has three tabs. **Swing** is the statistical trading dashboard
described below. **Long-Term** screens for 3-10x candidates using fundamentals
(small base, revenue growth, margins, balance sheet, valuation room, insider
ownership) and then has an LLM research current trends and catalysts to write a
structured thesis per candidate (thesis, catalysts, risks, path to multiple,
conviction). **Agent** is a research agent that pursues a goal you give it by
calling the platform's tools — quotes, full statistical analysis, fundamentals
screen, pairs tests, web research — and writes a research memo; it can log
trades to a paper portfolio ($100k starting cash, live mark-to-market P&L) but
never places real orders.

## LLM configuration

Set environment variables before launching:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Use Claude (recommended — enables live web search for research) |
| `FQ_ANTHROPIC_MODEL` | Claude model, default `claude-sonnet-4-6` |
| `FQ_LLM_PROVIDER` | Force `anthropic` or `ollama` (default: anthropic if key set) |
| `FQ_OLLAMA_URL` / `FQ_OLLAMA_MODEL` | Local model via Ollama, default `qwen2.5:14b` (no web search; theses are flagged accordingly) |

The broker layer (`quant/broker.py`) defaults to the paper broker everywhere.
A Robinhood adapter skeleton shows where live execution could plug in; it is
disabled unless you deliberately enable it and accept the risks — review that
file before considering it.

## Claude Desktop connector (MCP)

`mcp_server.py` exposes the platform to Claude Desktop as an MCP connector:
analyze, multibagger screen, pairs tests, quotes, ticker search, the paper
portfolio (including paper trades), and `propose_live_order`, which queues
proposals into the Live tab for human approval. Order approval and broker
mode are deliberately not exposed over MCP. The Agent tab shows the exact
config JSON (with correct absolute paths) to paste into Claude Desktop →
Settings → Developer → Edit Config; requires `pip install mcp`.

## Live tab: order approval queue

The **Live** tab is the human-in-the-loop gate for agentic trading. The
research agent (via its `propose_live_order` tool), Claude in Cowork (by
appending to `data/order_queue.json`), or you (via the form) can *propose*
orders with a rationale. Nothing executes until you press Approve. Approved
orders route through the broker layer — the paper portfolio by default; only
if `FQ_BROKER=robinhood` and `FQ_ENABLE_LIVE_TRADING=1` are set do they reach
a real brokerage, and the approve dialog warns you loudly when the broker is
live. Claude never approves or executes orders itself.

## Swing features

The dashboard is a set of modular panels. The watchlist shows each ticker with a
sparkline, live price, and (once analyzed) a rating + target badge. The chart
panel covers six horizons from 15-minute bars (1W) to weekly bars (10Y). The
analysis panel runs the full model suite on the selected ticker; the rating
panel shows the composite rating, 3-month price target, and 80% interval. The
pairs panel runs Engle-Granger cointegration tests on any two tickers. Reports
open as a print-optimized page (Print / Save PDF) and are also downloadable as
a generated PDF (`/api/report/{ticker}/pdf`).

Light/dark mode toggles in the top bar; theme, watchlist, and cached ratings
persist in the browser.

## Methods (and the literature behind them)

| Model | Method | Key references |
|---|---|---|
| Momentum | 12-1 cross-sectional momentum; time-series momentum with t-stat signal; EMA50/200 trend | Jegadeesh & Titman (1993, JF); Moskowitz, Ooi & Pedersen (2012, JFE) |
| Mean reversion | ADF unit-root test; Lo-MacKinlay heteroskedasticity-robust variance ratio; OU half-life via AR(1); 20-bar z-score | Dickey & Fuller (1979); Lo & MacKinlay (1988, RFS); Avellaneda & Lee (2010) |
| Pairs | Engle-Granger cointegration, OLS hedge ratio, spread z-score & half-life | Engle & Granger (1987); Gatev, Goetzmann & Rouwenhorst (2006, RFS) |
| Volatility | GARCH(1,1) MLE forecast (EWMA fallback); Sharpe/Sortino; max drawdown; VaR/CVaR; vol-managed sizing | Bollerslev (1986); Hansen & Lunde (2005, JAE); Moreira & Muir (2017, JF); caveat: Cederburg et al. (2020) |
| Factors | Three-factor regression on ETF proxies (SPY, IWM−SPY, VTV−VUG) with Newey-West errors | Fama & French (1993, JFE); Newey & West (1987) |

## Rating & price target

Each model emits a score in [−1, +1]. The composite is a weighted blend
(momentum 0.35, factor alpha 0.25, mean reversion 0.20, volatility 0.20) mapped
to Strong Buy / Buy / Hold / Sell / Strong Sell. The 63-trading-day price target
blends a lognormal drift projection with an OU reversion target (weighted by
stationarity evidence), with an 80% interval from the GARCH volatility forecast.

Data comes from Yahoo Finance via `yfinance` (free, no API key, ~15 min delayed).
For research and education only — not investment advice.
