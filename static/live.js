/* Live tab: order approval queue (human-in-the-loop gate) */
(() => {
  let inited = false;
  let pollTimer = null;

  const post = (url, body) => fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (r) => {
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    return r.json();
  });

  async function loadBrokerStatus() {
    try {
      const s = await api("/api/broker/status");
      $("#brokerStatus").innerHTML = s.mode === "live"
        ? `<span class="neg"><b>LIVE</b> — approved orders hit Robinhood</span>`
        : `<span class="pos">Paper mode</span>`;
      $("#modeToggle").textContent = s.mode === "live" ? "Switch to paper" : "Switch to live";
      return s;
    } catch { $("#brokerStatus").textContent = ""; return null; }
  }

  $("#modeToggle").onclick = async () => {
    const s = await api("/api/broker/status");
    if (!s) return;
    if (s.mode === "paper") {
      if (!s.liveReady) {
        alert("Live broker isn't configured on the backend yet:\n• " +
              (s.readyHint || "unknown") +
              "\n\nStaying in paper mode. Credentials are never entered in this UI.");
        return;
      }
      const typed = prompt(
        "You are switching to LIVE trading.\n\nEvery order you approve will be " +
        "placed on Robinhood with REAL money. Models here are research tools — " +
        "losses are entirely possible.\n\nType LIVE to confirm:");
      if (typed !== "LIVE") return;
      await post("/api/broker/mode", { mode: "live" });
    } else {
      await post("/api/broker/mode", { mode: "paper" });
    }
    loadBrokerStatus();
  };

  function orderRow(o, withActions) {
    const sideCls = o.side === "buy" ? "pos" : "neg";
    const badge = { executed: "rate-buy", rejected: "rate-sell",
                    failed: "rate-strongsell", pending: "rate-hold" }[o.status] || "rate-hold";
    const result = o.status === "executed" && o.result
      ? `<div class="muted trade-rationale">→ ${o.result.broker} broker${o.result.detail?.price ? ` @ $${o.result.detail.price}` : ""}</div>`
      : o.status === "failed" && o.result
        ? `<div class="neg trade-rationale">→ ${o.result.error}</div>` : "";
    return `<div class="oq-row">
      <div>
        <span class="${sideCls}"><b>${o.side.toUpperCase()}</b></span>
        <b>${o.qty} ${o.ticker}</b>
        ${o.priceAtProposal ? `<span class="muted">~$${o.priceAtProposal}</span>` : ""}
        <span class="wl-badge ${badge}">${o.status}</span>
        <span class="muted" style="font-size:11px">${(o.ts || "").replace("T", " ")} · ${o.source}</span>
        <div class="muted trade-rationale">${o.rationale || ""}</div>
        ${result}
      </div>
      ${withActions ? `<div class="oq-actions">
        <button class="btn btn-sm" data-approve="${o.id}">Approve</button>
        <button class="btn ghost btn-sm" data-reject="${o.id}">Reject</button>
      </div>` : ""}
    </div>`;
  }

  async function loadOrders() {
    try {
      const all = await api("/api/orders");
      const pending = all.filter((o) => o.status === "pending");
      const done = all.filter((o) => o.status !== "pending").slice(0, 25);

      const qb = $("#orderQueueBody");
      qb.classList.remove("muted");
      qb.innerHTML = pending.length
        ? pending.map((o) => orderRow(o, true)).join("")
        : `<div class="muted">No pending proposals. The research agent (Agent tab),
           Claude, or the form above can add them.</div>`;

      const hb = $("#orderHistoryBody");
      if (done.length) {
        hb.classList.remove("muted");
        hb.innerHTML = done.map((o) => orderRow(o, false)).join("");
      }
    } catch (e) {
      $("#orderQueueBody").innerHTML = `<span class="neg">${e.message}</span>`;
    }
  }

  $("#orderQueueBody").addEventListener("click", async (e) => {
    const ap = e.target.dataset.approve, rj = e.target.dataset.reject;
    try {
      if (ap) {
        const s = await api("/api/broker/status");
        const msg = s.mode === "live"
          ? "Approve this order? Broker is LIVE — this places a REAL order on Robinhood."
          : "Approve this order? It will execute in the paper portfolio.";
        if (!confirm(msg)) return;
        await post(`/api/orders/${ap}/approve`);
      } else if (rj) {
        await post(`/api/orders/${rj}/reject`);
      } else return;
      loadOrders();
    } catch (err) { alert(err.message); }
  });

  $("#oqProposeForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await post("/api/orders/propose", {
        ticker: $("#oqTicker").value.trim().toUpperCase(),
        side: $("#oqSide").value,
        qty: Number($("#oqQty").value),
        rationale: $("#oqRationale").value.trim() || "manual proposal",
        source: "manual",
      });
      $("#oqQty").value = ""; $("#oqRationale").value = "";
      loadOrders();
    } catch (err) { alert(err.message); }
  };

  $("#oqRefresh").onclick = loadOrders;

  window.liveInit = () => {
    if (!inited) {
      inited = true;
      loadBrokerStatus();
      $("#perfRefreshLive").onclick = () =>
        window.loadPerformance("#perfLive", "#perfLogLive");
      attachAutocomplete($("#oqTicker"));
    }
    loadOrders();
    window.loadPerformance("#perfLive", "#perfLogLive");
    clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (!$("#section-live").classList.contains("hidden")) loadOrders();
      else clearInterval(pollTimer);
    }, 5000);
  };
  if (!$("#section-live").classList.contains("hidden")) window.liveInit();
})();
