/* Shared model-improvement loop renderer (used by Agent and Live tabs) */
(() => {
  function bucketTable(title, buckets) {
    const rows = Object.entries(buckets || {})
      .filter(([, s]) => s.n > 0)
      .map(([k, s]) => `<tr><td>${k}</td><td>${s.n}</td>
        <td>${s.winRatePct}% <span class="muted">${s.winRateCi95 || ""}</span></td>
        <td class="${s.avgRetPct >= 0 ? "pos" : "neg"}">${s.avgRetPct}%</td></tr>`)
      .join("");
    if (!rows) return "";
    return `<h3 class="trades-h">${title}</h3>
      <table class="lt-table"><tr><th>Bucket</th><th>n</th><th>Win rate</th><th>Avg ret</th></tr>${rows}</table>`;
  }

  window.loadPerformance = async function (reviewSel, logSel) {
    const el = document.querySelector(reviewSel);
    if (!el) return;
    try {
      const r = await api("/api/performance/review");
      const warn = (r.warnings || []).map((w) =>
        `<div class="perf-warning">⚠ ${w}</div>`).join("");
      const recent = (r.recentRoundTrips || []).slice(0, 8).map((t) => `
        <div class="trade-row">
          <b>${t.ticker}</b> ${t.qty} @ $${t.entryPrice} → $${t.exitPrice}
          <span class="${t.retPct >= 0 ? "pos" : "neg"}">${t.retPct >= 0 ? "+" : ""}${t.retPct}%</span>
          <span class="muted">${t.entrySignal ? `entry rating ${t.entrySignal.rating} (${t.entrySignal.score})` : "no snapshot"} · ${t.source || ""}</span>
        </div>`).join("");
      el.classList.remove("muted");
      el.innerHTML = `
        ${warn}
        <div class="kv"><span>Closed round trips</span><span><b>${r.closedRoundTrips}</b></span></div>
        ${r.overall && r.overall.n ? `
          <div class="kv"><span>Overall win rate</span><span>${r.overall.winRatePct}% <span class="muted">${r.overall.winRateCi95}</span></span></div>
          <div class="kv"><span>Avg / median return</span><span>${r.overall.avgRetPct}% / ${r.overall.medianRetPct}%</span></div>` : ""}
        ${bucketTable("By rating at entry", r.byEntryRating)}
        ${bucketTable("By composite score sign", r.byScoreSign)}
        ${bucketTable("By trade source", r.bySource)}
        ${recent ? `<h3 class="trades-h">Recent round trips</h3>${recent}` : ""}`;
    } catch (e) {
      el.innerHTML = `<span class="neg">${e.message}</span>`;
    }

    if (!logSel) return;
    const lel = document.querySelector(logSel);
    if (!lel) return;
    try {
      const log = await api("/api/performance/log");
      if (!log.length) {
        lel.innerHTML = `<span class="muted">No improvement entries yet. Changes to
          the models get recorded here with their evidence.</span>`;
        return;
      }
      lel.classList.remove("muted");
      lel.innerHTML = log.slice(0, 20).map((e) => `
        <div class="step">
          <span class="step-tag">${e.author}</span>
          <span class="muted" style="font-size:11px">${(e.ts || "").replace("T", " ")}</span>
          <div style="font-size:12px"><b>Observation:</b> ${e.observation}
            ${e.change ? `<br><b>Change:</b> ${e.change}` : ""}
            ${e.evidence ? `<br><b>Evidence:</b> ${e.evidence}` : ""}</div>
        </div>`).join("");
    } catch {}
  };
})();
