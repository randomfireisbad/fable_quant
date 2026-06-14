/* Long-term section: multibagger screen + LLM theses */
(() => {
  let inited = false;
  let screenRows = [];

  const money = (x) => {
    if (x == null) return "n/a";
    const a = Math.abs(x);
    if (a >= 1e12) return (x / 1e12).toFixed(1) + "T";
    if (a >= 1e9) return (x / 1e9).toFixed(1) + "B";
    if (a >= 1e6) return (x / 1e6).toFixed(1) + "M";
    return x.toFixed(0);
  };
  const bandClass = (band) => ({
    High: "rate-strongbuy", Moderate: "rate-buy", Low: "rate-sell",
  }[band] || "rate-hold");
  const convClass = (c) => ({
    High: "rate-strongbuy", Moderate: "rate-buy", Low: "rate-sell",
    Avoid: "rate-strongsell",
  }[c] || "rate-hold");

  async function refreshLlmStatus() {
    try {
      const s = await api("/api/llm/status");
      $("#llmStatus").innerHTML = s.ready
        ? `LLM: ${s.provider} (${s.model})${s.webSearch ? " · web search" : " · no web"}`
        : `<span class="neg">LLM not ready — ${s.hint || s.provider}</span>`;
    } catch { $("#llmStatus").textContent = ""; }
  }

  function renderScreen() {
    if (!screenRows.length) return;
    const rows = screenRows.map((r) => {
      if (r.error) return `<tr><td>${r.ticker}</td><td colspan="7" class="neg">${r.error}</td></tr>`;
      const mb = r.multibagger;
      return `<tr>
        <td><b>${r.ticker}</b><span class="wl-sub">${r.name || ""}</span></td>
        <td><span class="${bandClass(mb.band)}"><b>${mb.score}</b></span>/100 ${mb.band}</td>
        <td>${money(r.marketCap)}</td>
        <td>${r.revenueGrowth != null ? (100 * r.revenueGrowth).toFixed(0) + "%" : "n/a"}</td>
        <td>${r.grossMargins != null ? (100 * r.grossMargins).toFixed(0) + "%" : "n/a"}</td>
        <td>${r.priceToSales != null ? r.priceToSales.toFixed(1) : "n/a"}</td>
        <td>${r.price != null ? "$" + r.price : "n/a"}</td>
        <td><button class="btn ghost btn-sm" data-thesis="${r.ticker}">Thesis</button></td>
      </tr>`;
    }).join("");
    $("#ltScreenBody").classList.remove("muted");
    $("#ltScreenBody").innerHTML = `
      <table class="lt-table">
        <tr><th>Ticker</th><th>${"Score"}</th><th>Mkt cap</th><th>Rev growth</th>
          <th>Gross mgn</th><th>P/S</th><th>Price</th><th></th></tr>
        ${rows}
      </table>`;
  }

  async function runScreen(tickers) {
    if (!tickers.length) return;
    $("#ltScreenBody").classList.add("muted");
    $("#ltScreenBody").textContent = `Screening ${tickers.length} tickers (fundamentals are slow — ~2s each)…`;
    try {
      screenRows = await fetch("/api/longterm/screen", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickers }),
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        return r.json();
      });
      renderScreen();
    } catch (e) {
      $("#ltScreenBody").innerHTML = `<span class="neg">${e.message}</span>`;
    }
  }

  function thesisCard(t) {
    const li = (xs) => (xs || []).map((x) => `<li>${x}</li>`).join("");
    const body = t.thesis ? `
      <p>${t.thesis}</p>
      <div class="thesis-cols">
        <div><b>Catalysts</b><ul>${li(t.catalysts)}</ul></div>
        <div><b>Risks</b><ul>${li(t.risks)}</ul></div>
      </div>
      ${t.path_to_multiple ? `<p><b>Path to multiple:</b> ${t.path_to_multiple}</p>` : ""}`
      : `<pre class="thesis-raw">${t.raw || ""}</pre>`;
    return `<div class="model-card thesis-card">
      <h3>${t.ticker} — ${t.name || ""}
        <span class="${convClass(t.convictionLevel)}" style="float:right">
          ${t.convictionLevel || "?"} conviction</span></h3>
      <div class="muted" style="font-size:11px">${t.date} · screen ${t.screenScore}/100 (${t.screenBand})
        · ${t.provider}${t.webSearch ? " + web search" : " (no web)"}</div>
      ${body}
      ${t.conviction ? `<p class="muted">${t.conviction}</p>` : ""}
      <button class="btn ghost btn-sm" data-delthesis="${t.ticker}">Delete</button>
    </div>`;
  }

  async function loadResearch() {
    try {
      const d = await api("/api/longterm/research");
      const items = Object.values(d).sort((a, b) => (b.date || "").localeCompare(a.date || ""));
      if (!items.length) return;
      $("#ltResearchBody").classList.remove("muted");
      $("#ltResearchBody").innerHTML = items.map(thesisCard).join("");
    } catch {}
  }

  async function generateThesis(ticker) {
    $("#ltResearchBody").classList.remove("muted");
    $("#ltResearchBody").innerHTML =
      `<div class="muted">Researching ${ticker} — the LLM is reading market data
       ${$("#llmStatus").textContent.includes("web") ? "and searching the web" : ""}…
       (30-90s)</div>` + $("#ltResearchBody").innerHTML;
    try {
      await fetch(`/api/longterm/thesis/${ticker}`, { method: "POST" })
        .then(async (r) => {
          if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
          return r.json();
        });
      loadResearch();
    } catch (e) {
      $("#ltResearchBody").innerHTML =
        `<div class="neg">Thesis failed for ${ticker}: ${e.message}</div>`;
      setTimeout(loadResearch, 4000);
    }
  }

  $("#ltForm").onsubmit = (e) => {
    e.preventDefault();
    runScreen($("#ltTickers").value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean));
  };
  $("#ltRunScreen").onclick = () => $("#ltForm").requestSubmit();
  $("#ltUseWatchlist").onclick = () => {
    $("#ltTickers").value = state.watchlist.join(", ");
    $("#ltForm").requestSubmit();
  };
  $("#ltScreenBody").addEventListener("click", (e) => {
    const t = e.target.dataset.thesis;
    if (t) generateThesis(t);
  });
  $("#ltResearchBody").addEventListener("click", async (e) => {
    const t = e.target.dataset.delthesis;
    if (t) {
      await fetch(`/api/longterm/research/${t}`, { method: "DELETE" });
      $("#ltResearchBody").innerHTML = "";
      loadResearch();
    }
  });

  window.ltInit = () => {
    if (inited) return;
    inited = true;
    refreshLlmStatus();
    loadResearch();
  };
  // app.js runs setTab before this script loads; init now if our tab is active
  if (!$("#section-longterm").classList.contains("hidden")) window.ltInit();
})();
