/* Agent section: research agent runs + paper portfolio */
(() => {
  let inited = false;
  let pollTimer = null;

  async function refreshLlmStatus() {
    try {
      const s = await api("/api/llm/status");
      $("#agentLlmStatus").innerHTML = s.ready
        ? `LLM: ${s.provider} (${s.model})`
        : `<span class="neg">LLM not ready — ${s.hint || s.provider}</span>`;
      $("#agentRunBtn").disabled = !s.ready;
    } catch { $("#agentLlmStatus").textContent = ""; }
  }

  function renderTranscript(run) {
    const steps = (run.transcript || []).map((s) => {
      if (s.type === "thought") {
        return `<div class="step step-thought"><span class="step-tag">thinking</span>
          <div>${(s.text || "").replace(/\n/g, "<br>")}</div></div>`;
      }
      const input = s.input ? Object.entries(s.input)
        .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
        .join(", ") : "";
      return `<div class="step step-tool"><span class="step-tag tool">${s.name}</span>
        <span class="muted">(${input})</span>
        <details><summary>output</summary><pre>${(s.output || "").slice(0, 1500)}</pre></details>
      </div>`;
    }).join("");
    const status = run.status === "running"
      ? `<div class="muted">⏳ running… (${(run.transcript || []).length} steps so far)</div>`
      : run.status === "error"
        ? `<div class="neg">Run failed: ${run.error}</div>` : "";
    $("#agentTranscript").classList.remove("muted");
    $("#agentTranscript").innerHTML =
      `<div class="muted" style="margin-bottom:6px"><b>Goal:</b> ${run.goal}</div>` + steps + status;
    $("#agentTranscript").scrollTop = $("#agentTranscript").scrollHeight;

    const memo = $("#agentMemo");
    if (run.status === "done" && run.memo) {
      memo.classList.remove("hidden");
      memo.innerHTML = `<h3>Research memo</h3><div>${run.memo
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>")}</div>`;
    } else if (run.status === "running") {
      memo.classList.add("hidden");
    }
  }

  async function poll(runId) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const run = await api(`/api/agent/run/${runId}`);
        renderTranscript(run);
        if (run.status !== "running") {
          clearInterval(pollTimer);
          loadPortfolio(); // agent may have paper-traded
        }
      } catch { clearInterval(pollTimer); }
    }, 2000);
  }

  $("#agentForm").onsubmit = async (e) => {
    e.preventDefault();
    const goal = $("#agentGoal").value.trim();
    if (!goal) return;
    $("#agentTranscript").innerHTML = `<span class="muted">Starting run…</span>`;
    $("#agentMemo").classList.add("hidden");
    try {
      const { runId } = await fetch("/api/agent/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, maxSteps: Number($("#agentSteps").value) || 10 }),
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        return r.json();
      });
      poll(runId);
    } catch (err) {
      $("#agentTranscript").innerHTML = `<span class="neg">${err.message}</span>`;
    }
  };

  /* ---------- paper portfolio ---------- */
  async function loadPortfolio() {
    try {
      const p = await api("/api/portfolio");
      const rows = p.positions.map((x) => `<tr>
        <td><b>${x.ticker}</b></td><td>${x.qty}</td><td>$${x.avgCost}</td>
        <td>$${x.price}</td><td>$${x.marketValue}</td>
        <td class="${x.unrealizedPnl >= 0 ? "pos" : "neg"}">
          ${x.unrealizedPnl >= 0 ? "+" : ""}$${x.unrealizedPnl} (${x.unrealizedPct}%)</td>
      </tr>`).join("");
      const trades = p.trades.slice(0, 12).map((t) => `
        <div class="trade-row">
          <span class="${t.side === "buy" ? "pos" : "neg"}">${t.side.toUpperCase()}</span>
          ${t.qty} ${t.ticker} @ $${t.price}
          <span class="muted">${t.ts.replace("T", " ")} · ${t.source}</span>
          ${t.rationale ? `<div class="muted trade-rationale">${t.rationale}</div>` : ""}
        </div>`).join("");
      $("#portfolioBody").classList.remove("muted");
      $("#portfolioBody").innerHTML = `
        <div class="kv"><span>Equity</span><span><b>$${p.equity.toLocaleString()}</b>
          <span class="${p.totalReturnPct >= 0 ? "pos" : "neg"}">(${p.totalReturnPct >= 0 ? "+" : ""}${p.totalReturnPct}%)</span></span></div>
        <div class="kv"><span>Cash</span><span>$${p.cash.toLocaleString()}</span></div>
        <div class="kv"><span>Positions value</span><span>$${p.positionsValue.toLocaleString()}</span></div>
        ${rows ? `<table class="lt-table" style="margin-top:8px">
          <tr><th>Ticker</th><th>Qty</th><th>Avg</th><th>Price</th><th>Value</th><th>P&L</th></tr>${rows}</table>`
          : `<div class="muted" style="margin-top:8px">No open positions.</div>`}
        ${trades ? `<h3 class="trades-h">Recent trades</h3>${trades}` : ""}`;
    } catch (e) {
      $("#portfolioBody").innerHTML = `<span class="neg">${e.message}</span>`;
    }
  }

  $("#pfRefresh").onclick = loadPortfolio;
  $("#pfReset").onclick = async () => {
    if (!confirm("Reset paper portfolio to $100,000 cash?")) return;
    await fetch("/api/portfolio/reset", { method: "POST" });
    loadPortfolio();
  };
  $("#pfTradeForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await fetch("/api/portfolio/trade", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: $("#pfTicker").value.trim().toUpperCase(),
          side: $("#pfSide").value,
          qty: Number($("#pfQty").value),
          rationale: "manual trade",
        }),
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      });
      $("#pfQty").value = "";
      loadPortfolio();
    } catch (err) { alert(err.message); }
  };

  /* ---------- paper day-trader desk ---------- */
  let traderPoll = null;

  async function loadTrader() {
    try {
      const s = await api("/api/trader/status");
      $("#traderToggle").textContent = s.enabled ? "Disable" : "Enable";
      $("#traderInterval").value = String(s.intervalMin);
      if (document.activeElement !== $("#traderUniverse"))
        $("#traderUniverse").value = (s.universe || []).join(", ");
      const bits = [];
      bits.push(s.running ? `<span class="pos"><b>session running…</b></span>`
                          : s.enabled ? "scheduled" : "off");
      bits.push(s.marketOpen ? "market open" : "market closed");
      if (s.equity != null) bits.push(`equity $${s.equity.toLocaleString()} (${s.totalReturnPct >= 0 ? "+" : ""}${s.totalReturnPct}%)`);
      if (s.lastRun) bits.push("last " + s.lastRun.replace("T", " "));
      if (!s.llmReady) bits.push(`<span class="neg">LLM not ready</span>`);
      if (s.lastError) bits.push(`<span class="neg">${s.lastError}</span>`);
      $("#traderStatus").innerHTML = bits.join(" · ");
      $("#traderRunNow").disabled = s.running || !s.llmReady;
      return s;
    } catch { return null; }
  }

  async function loadJournal() {
    try {
      const j = await api("/api/trader/journal");
      if (!j.length) return;
      $("#traderJournal").innerHTML = j.map((e) => {
        const trades = (e.trades || []).map((t) =>
          `<div class="trade-row"><span class="${t.side === "buy" ? "pos" : "neg"}">${t.side.toUpperCase()}</span>
           ${t.qty} ${t.ticker} @ $${t.price}</div>`).join("");
        const memo = (e.memo || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/\n/g, "<br>");
        return `<div class="step">
          <span class="step-tag ${e.error ? "" : "tool"}">${e.error ? "failed" : "session"}</span>
          <span class="muted" style="font-size:11px">${(e.ts || "").replace("T", " ")} · ${e.trigger}
            ${e.equity != null ? `· equity $${e.equity.toLocaleString()} (${e.returnPct >= 0 ? "+" : ""}${e.returnPct}%)` : ""}
            ${e.trades?.length ? `· ${e.trades.length} trade(s)` : "· no trades"}</span>
          ${trades}
          <details><summary>journal entry</summary><div style="font-size:12px">${memo}</div></details>
        </div>`;
      }).join("");
    } catch {}
  }

  function pollTrader() {
    clearInterval(traderPoll);
    traderPoll = setInterval(async () => {
      if ($("#section-agent").classList.contains("hidden")) { clearInterval(traderPoll); return; }
      const s = await loadTrader();
      if (s && !s.running) {
        clearInterval(traderPoll);
        loadJournal();
        loadPortfolio();
      }
    }, 4000);
  }

  $("#traderRunNow").onclick = async () => {
    try {
      const r = await fetch("/api/trader/run", { method: "POST" }).then(async (x) => {
        if (!x.ok) throw new Error((await x.json()).detail || x.statusText);
        return x.json();
      });
      if (!r.started) alert(r.note);
      loadTrader();
      pollTrader();
    } catch (e) { alert(e.message); }
  };

  $("#traderToggle").onclick = async () => {
    const s = await api("/api/trader/status");
    if (!s.enabled && !confirm(
      "Enable scheduled sessions? The agent will trade the PAPER portfolio " +
      "autonomously during market hours, every " + s.intervalMin + " minutes. " +
      "Each session uses LLM tokens.")) return;
    await fetch("/api/trader/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !s.enabled }),
    });
    loadTrader();
  };

  $("#traderSave").onclick = async () => {
    await fetch("/api/trader/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        intervalMin: Number($("#traderInterval").value),
        universe: $("#traderUniverse").value.split(","),
      }),
    });
    loadTrader();
  };

  /* ---------- Claude Desktop connector ---------- */
  async function loadConnector() {
    try {
      const c = await api("/api/connector/config");
      $("#connectorConfig").textContent = c.snippet;
      $("#connectorStatus").innerHTML = c.mcpSdkInstalled
        ? `MCP SDK installed · server script: ${c.scriptPath}`
        : `<span class="neg">MCP SDK missing — run: pip install mcp</span> · server script: ${c.scriptPath}`;
      $("#connectorCopy").onclick = async () => {
        await navigator.clipboard.writeText(c.snippet);
        $("#connectorCopy").textContent = "Copied!";
        setTimeout(() => { $("#connectorCopy").textContent = "Copy config"; }, 1500);
      };
    } catch (e) {
      $("#connectorConfig").textContent = "Could not load config: " + e.message;
    }
  }

  window.agentInit = () => {
    if (inited) {
      loadPortfolio(); loadTrader(); loadJournal();
      window.loadPerformance("#perfAgent", "#perfLogAgent");
      return;
    }
    inited = true;
    refreshLlmStatus();
    loadPortfolio();
    loadConnector();
    loadTrader();
    loadJournal();
    window.loadPerformance("#perfAgent", "#perfLogAgent");
    $("#perfRefreshAgent").onclick = () =>
      window.loadPerformance("#perfAgent", "#perfLogAgent");
    attachAutocomplete($("#pfTicker"));
  };
  // app.js runs setTab before this script loads; init now if our tab is active
  if (!$("#section-agent").classList.contains("hidden")) window.agentInit();
})();
