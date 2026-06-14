"""Research report assembly: thesis, justification, supporting models,
summary with rating and price target. Also renders a PDF via reportlab."""
from __future__ import annotations

from datetime import date

CITATIONS = {
    "momentum": "Jegadeesh & Titman (1993) JF; Moskowitz, Ooi & Pedersen (2012) JFE",
    "meanReversion": "Dickey & Fuller (1979); Lo & MacKinlay (1988) RFS; Avellaneda & Lee (2010)",
    "volatility": "Bollerslev (1986); Hansen & Lunde (2005) JAE; Moreira & Muir (2017) JF",
    "factors": "Fama & French (1993) JFE; Newey & West (1987)",
}


def _fmt_pct(x, digits=1):
    return f"{100 * x:+.{digits}f}%" if x is not None else "n/a"


def build(ticker: str, analysis: dict) -> dict:
    mom, mr, vol = analysis["momentum"], analysis["meanReversion"], analysis["volatility"]
    fac, comp, pt = analysis.get("factors"), analysis["composite"], analysis["priceTarget"]
    q = analysis["quote"]

    direction = ("bullish" if comp["score"] > 0.15 else
                 "bearish" if comp["score"] < -0.15 else "neutral")

    drivers = sorted(comp["components"].items(), key=lambda kv: -abs(kv[1]))
    lead = drivers[0][0]
    lead_names = {"momentum": "momentum/trend", "meanReversion": "mean reversion",
                  "volatility": "volatility/risk", "factors": "factor alpha"}

    thesis = (
        f"{ticker} screens {direction} on a composite of four statistical models "
        f"(score {comp['score']:+.2f} on [-1, +1]), led by the {lead_names[lead]} signal. "
        f"The {pt['horizonDays']}-trading-day model target is ${pt['target']} "
        f"({_fmt_pct(pt['expectedReturnPct'] / 100)} vs. spot ${pt['spot']}), with an 80% "
        f"interval of ${pt['low80']}–${pt['high80']} derived from the GARCH(1,1) "
        f"volatility forecast."
    )

    just_mom = (
        f"Trailing returns: 1m {_fmt_pct(mom['lookbackReturns']['1m'])}, "
        f"3m {_fmt_pct(mom['lookbackReturns']['3m'])}, "
        f"6m {_fmt_pct(mom['lookbackReturns']['6m'])}, "
        f"12m {_fmt_pct(mom['lookbackReturns']['12m'])}. "
        f"The Jegadeesh-Titman 12-1 measure is {_fmt_pct(mom['mom12_1'])}. "
        f"Time-series momentum (trailing 12m excess return) is "
        f"{_fmt_pct(mom['tsmom']['excess12m'])} with t-stat {mom['tsmom']['tStat']}"
        f"{' (significant at conventional levels)' if abs(mom['tsmom']['tStat']) > 1.96 else ' (not statistically significant)'}. "
        + (f"Price trend is in an {mom['trend']['state']} (EMA50 {mom['trend']['ema50']} vs EMA200 {mom['trend']['ema200']})."
           if mom.get("trend") else "Insufficient history for EMA trend state.")
    )

    vr = mr["varianceRatio"]
    just_mr = (
        f"ADF unit-root test on log price: stat {mr['adf']['stat']}, "
        f"p = {mr['adf']['pValue']} — "
        f"{'rejects' if mr['adf']['stationary'] else 'fails to reject'} a random walk. "
        f"Lo-MacKinlay variance ratio (q=5): VR = {vr['vr']}, robust z = {vr['z']} "
        f"(VR < 1 indicates mean reversion, VR > 1 momentum). "
        + (f"Fitted OU half-life ≈ {mr['halfLifeDays']} trading days. " if mr.get("halfLifeDays") else "No finite mean-reversion half-life detected. ")
        + f"Current 20-bar z-score is {mr['zScore20']} versus mean ${mr['mean20']}."
    )

    g = vol["garch"]
    just_vol = (
        f"Realized vol (annualized): 21d {_fmt_pct(vol['realized']['21d'], 1)}, "
        f"252d {_fmt_pct(vol['realized']['252d'], 1) if vol['realized']['252d'] else 'n/a'}. "
        + (f"{g.get('model', 'GARCH(1,1)')} forecast (21d horizon): {_fmt_pct(g['annVolForecast21d'], 1)} "
           f"(α={g['alpha']}, β={g['beta']}"
           + (f", γ={g['gamma']} [leverage]" if g.get("gamma") is not None else "")
           + f", persistence={g['persistence']}). "
           if g.get("ok") else f"GARCH fit unavailable; EWMA fallback vol {_fmt_pct(g['annVolForecast21d'], 1)}. ")
        + f"Sharpe {vol['risk']['sharpe']}, max drawdown {_fmt_pct(vol['risk']['maxDrawdown'])}, "
        f"daily 95% CVaR {_fmt_pct(vol['risk']['cvar95Daily'])}. "
        f"Volatility-managed sizing (15% target) implies a {vol['volManaged']['weight']}x weight; "
        f"note Cederburg et al. (2020) find vol-managed gains are fragile out-of-sample."
    )

    if fac:
        just_fac = (
            f"Three-factor regression (ETF proxies, Newey-West SEs, n={fac['nObs']}): "
            f"annualized alpha {_fmt_pct(fac['alphaAnnual'])} (t = {fac['alphaTStat']}), "
            f"market beta {fac['betas']['MKT']}, size {fac['betas']['SMB']}, "
            f"value {fac['betas']['HML']}; R² = {fac['r2']}. "
            f"Idiosyncratic vol {_fmt_pct(fac['idioVolAnnual'])}."
        )
    else:
        just_fac = "Factor regression unavailable for this instrument."

    bt = analysis.get("backtest") or {}
    if bt.get("ok"):
        just_bt = (
            f"Walk-forward check (5y, signals lagged 1 day, {bt['costBps']}bp costs): "
            f"TSMOM Sharpe {bt['tsmom']['sharpe']}, mean-reversion fade Sharpe "
            f"{bt['meanrev']['sharpe']}, vs buy-and-hold {bt['buyHold']['sharpe']} "
            f"over {bt['evalDays']} trading days. Historical signal performance on "
            f"this instrument is a sanity check, not a forecast."
        )
    else:
        just_bt = "Walk-forward backtest unavailable for this instrument."

    summary = (
        f"Rating: {comp['rating']} (composite {comp['score']:+.2f}, "
        f"signal agreement {comp.get('confidence', 1):.0%}). "
        f"{pt['horizonDays']}-trading-day price expectation: ${pt['target']} "
        f"[80% interval ${pt['low80']}–${pt['high80']}]. "
        f"Signals are statistical tendencies, not guarantees; the interval width "
        f"reflects forecast volatility of {_fmt_pct(pt['components']['garchVolUsed'], 1)} annualized."
    )

    return {
        "ticker": ticker,
        "date": str(date.today()),
        "quote": q,
        "thesis": thesis,
        "justification": {
            "momentum": {"text": just_mom, "citation": CITATIONS["momentum"]},
            "meanReversion": {"text": just_mr, "citation": CITATIONS["meanReversion"]},
            "volatility": {"text": just_vol, "citation": CITATIONS["volatility"]},
            "factors": {"text": just_fac, "citation": CITATIONS["factors"]},
            "backtest": {"text": just_bt,
                         "citation": "Moskowitz-Ooi-Pedersen 2012; Cederburg et al. 2020"},
        },
        "models": {
            "momentum": mom, "meanReversion": mr, "volatility": vol, "factors": fac,
        },
        "summary": summary,
        "rating": comp["rating"],
        "compositeScore": comp["score"],
        "priceTarget": pt,
        "disclaimer": ("Generated by statistical models for research/education. "
                       "Not investment advice."),
    }


def to_pdf(report: dict, path: str) -> str:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable)

    blue, slate = HexColor("#1d4ed8"), HexColor("#334155")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=blue, fontSize=20)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=blue, spaceBefore=14)
    body = ParagraphStyle("body", parent=styles["BodyText"], textColor=slate, leading=15)
    cite = ParagraphStyle("cite", parent=body, fontSize=8, textColor=HexColor("#64748b"))

    pt = report["priceTarget"]
    doc = SimpleDocTemplate(path, pagesize=letter, topMargin=0.8 * inch,
                            bottomMargin=0.8 * inch)
    el = [
        Paragraph(f"{report['ticker']} — Quantitative Research Report", h1),
        Paragraph(f"{report['date']} · Spot ${pt['spot']} · "
                  f"Rating: <b>{report['rating']}</b> · "
                  f"{pt['horizonDays']}d target ${pt['target']} (80%: ${pt['low80']}–${pt['high80']})", body),
        HRFlowable(width="100%", color=blue), Spacer(1, 10),
        Paragraph("Thesis", h2), Paragraph(report["thesis"], body),
        Paragraph("Justification & Supporting Models", h2),
    ]
    titles = {"momentum": "Momentum & Trend", "meanReversion": "Mean Reversion",
              "volatility": "Volatility & Risk", "factors": "Factor Regression",
              "backtest": "Walk-Forward Backtest"}
    for key, block in report["justification"].items():
        el += [Paragraph(f"<b>{titles[key]}</b>", body),
               Paragraph(block["text"], body),
               Paragraph(f"References: {block['citation']}", cite), Spacer(1, 6)]

    rows = [["Component", "Score [-1, +1]"]]
    for k, v in report["models"].items():
        if v and "score" in v:
            rows.append([titles[k], f"{v['score']:+.2f}"])
    rows.append(["Composite", f"{report['compositeScore']:+.2f}"])
    tbl = Table(rows, colWidths=[3 * inch, 1.5 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), blue),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#dbeafe")),
    ]))
    el += [Paragraph("Model Scores", h2), tbl,
           Paragraph("Summary", h2), Paragraph(report["summary"], body),
           Spacer(1, 12), Paragraph(report["disclaimer"], cite)]
    doc.build(el)
    return path
