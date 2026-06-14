"""Long-term (3-10x) research: fundamentals screen + LLM-driven thesis.

The screen narrows candidates quantitatively; the LLM then researches current
trends, catalysts, and risks (live web search when the provider supports it)
and writes a structured thesis. Theses persist to data/longterm_research.json.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date

from . import fundamentals, llm

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_FILE = os.path.join(_DATA, "longterm_research.json")
_lock = threading.Lock()

THESIS_PROMPT = """Analyze {ticker} ({name}, sector: {sector}, industry: {industry}) \
as a potential 3-10x long-term investment over a 3-7 year horizon.

Quantitative snapshot (from the platform's screen):
{snapshot}
Multibagger screen score: {score}/100 ({band})
Breakdown: {breakdown}

Research current market trends, recent news, and any events or catalysts that \
could materially drive (or impair) this company's valuation. Then respond in \
EXACTLY this format:

THESIS: <2-4 sentence core thesis>
CATALYSTS:
- <catalyst 1>
- <catalyst 2>
- <catalyst 3>
RISKS:
- <risk 1>
- <risk 2>
- <risk 3>
PATH_TO_MULTIPLE: <how revenue/margin/multiple expansion could compound to 3-10x; \
show rough math>
CONVICTION: <High|Moderate|Low|Avoid> — <one sentence why>
"""


def _load() -> dict:
    try:
        with open(_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    os.makedirs(_DATA, exist_ok=True)
    with _lock:
        with open(_FILE, "w") as f:
            json.dump(d, f, indent=1)


def saved_research() -> dict:
    return _load()


def delete_research(ticker: str):
    d = _load()
    if ticker.upper() in d:
        del d[ticker.upper()]
        _save(d)


def _parse(text: str) -> dict:
    """Best-effort parse of the structured response; falls back to raw text."""
    out = {"raw": text}
    cur = None
    sections = {"THESIS": "", "CATALYSTS": [], "RISKS": [],
                "PATH_TO_MULTIPLE": "", "CONVICTION": ""}
    for line in text.splitlines():
        s = line.strip()
        up = s.upper()
        matched = False
        for key in sections:
            if up.startswith(key + ":") or up == key + ":":
                cur = key
                rest = s[len(key) + 1:].strip()
                if isinstance(sections[key], str):
                    sections[key] = rest
                matched = True
                break
        if matched or not cur or not s:
            continue
        if isinstance(sections[cur], list):
            sections[cur].append(s.lstrip("-• ").strip())
        else:
            sections[cur] += (" " if sections[cur] else "") + s
    if sections["THESIS"]:
        out.update({k.lower(): v for k, v in sections.items()})
        conv = sections["CONVICTION"].split("—")[0].split("-")[0].strip().title()
        out["convictionLevel"] = conv if conv in ("High", "Moderate", "Low", "Avoid") else "Moderate"
    return out


def generate_thesis(ticker: str) -> dict:
    t = ticker.upper()
    f = fundamentals.fetch(t)
    s = fundamentals.multibagger_score(f)
    snapshot = "\n".join(f"  {k}: {v}" for k, v in f.items()
                         if k not in ("ticker",) and v is not None)
    breakdown = "; ".join(f"{k}: {v['pts']}/{v['max']} ({v['note']})"
                          for k, v in s["breakdown"].items())
    prompt = THESIS_PROMPT.format(ticker=t, name=f["name"], sector=f["sector"],
                                  industry=f["industry"], snapshot=snapshot,
                                  score=s["score"], band=s["band"],
                                  breakdown=breakdown)
    p = llm.provider()
    text = p.research(prompt)
    rec = {
        "ticker": t, "name": f["name"], "date": str(date.today()),
        "provider": p.name, "webSearch": p.supports_web,
        "screenScore": s["score"], "screenBand": s["band"],
        **_parse(text),
    }
    d = _load()
    d[t] = rec
    _save(d)
    return rec
