"""One-command verification of the full pipeline.

Run:  python selftest.py [TICKER]
Fetches live data, runs every model, sanity-checks the numbers, builds the
report and a PDF. Prints PASS/FAIL per check.
"""
from __future__ import annotations

import sys

from quant import (backtest, data, factors, meanrev, momentum, rating, report,
                   volatility)

ticker = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()
fails = 0


def check(name, cond, detail=""):
    global fails
    status = "PASS" if cond else "FAIL"
    if not cond:
        fails += 1
    print(f"[{status}] {name} {detail}")


print(f"— Fable Quant self-test on {ticker} —")

close = data.closes(ticker, "2Y")
check("data: fetched 2Y daily closes", len(close) > 250, f"({len(close)} bars)")
q = data.quote(ticker)
check("data: quote", q["price"] > 0, f"(${q['price']})")

m = momentum.analyze(close, bench_close=data.closes("SPY", "2Y"))
check("momentum: score in [-1,1]", -1 <= m["score"] <= 1, f"(score {m['score']})")
check("momentum: 12-1 computed", m["mom12_1"] is not None)

mr = meanrev.analyze(close)
check("meanrev: ADF p in [0,1]", 0 <= mr["adf"]["pValue"] <= 1, f"(p {mr['adf']['pValue']})")
check("meanrev: variance ratio computed", mr["varianceRatio"]["vr"] is not None,
      f"(VR {mr['varianceRatio']['vr']})")

v = volatility.analyze(close)
g = v["garch"]
check("vol: GARCH fit", g.get("ok", False), f"(fcst {g['annVolForecast21d']})")
if g.get("ok"):
    check("vol: GARCH stationary (alpha+beta < 1)", g["persistence"] < 1,
          f"(persistence {g['persistence']})")
check("vol: forecast in sane range (3%-150% ann.)",
      0.03 < g["annVolForecast21d"] < 1.5)

try:
    f = factors.analyze(close)
    check("factors: regression ran", f["nObs"] > 60, f"(n {f['nObs']}, R2 {f['r2']})")
    check("factors: market beta sane (-1..4)", -1 < f["betas"]["MKT"] < 4)
except Exception as e:
    f = None
    check("factors: regression ran", False, f"({e})")

bt = backtest.run(data.closes(ticker, "5Y"))
check("backtest: walk-forward ran", bt.get("ok", False),
      f"(TSMOM Sharpe {bt.get('tsmom', {}).get('sharpe')})" if bt.get("ok") else f"({bt.get('note')})")

comp = rating.composite(m, mr, v, f)
pt = rating.price_target(q["price"], m, mr, v, f, close=close)
check("target: interval method", "intervalMethod" in pt, f"({pt.get('intervalMethod')})")
check("rating: agreement in [0.45,1]", 0.45 <= comp["confidence"] <= 1,
      f"(confidence {comp['confidence']})")
check("rating: composite in [-1,1]", -1 <= comp["score"] <= 1,
      f"({comp['rating']}, {comp['score']})")
check("target: low < target < high", pt["low80"] < pt["target"] < pt["high80"],
      f"(${pt['low80']} < ${pt['target']} < ${pt['high80']})")

analysis = {"ticker": ticker, "quote": q, "momentum": m, "meanReversion": mr,
            "volatility": v, "factors": f, "composite": comp, "priceTarget": pt}
rep = report.build(ticker, analysis)
check("report: built with thesis + summary",
      len(rep["thesis"]) > 50 and len(rep["summary"]) > 50)
pdf_path = report.to_pdf(rep, f"{ticker}_selftest.pdf")
import os
check("report: PDF generated", os.path.getsize(pdf_path) > 1000, f"({pdf_path})")

p = meanrev.pairs(data.closes("KO", "2Y"), data.closes("PEP", "2Y"), "KO", "PEP")
check("pairs: Engle-Granger on KO/PEP",
      0 <= p["engleGranger"]["pValue"] <= 1, f"(p {p['engleGranger']['pValue']})")

print(f"\n{'ALL CHECKS PASSED' if fails == 0 else f'{fails} CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
