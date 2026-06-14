/* Fable Quant frontend */
const $ = (s) => document.querySelector(s);
const api = (p) => fetch(p).then(async (r) => {
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
});

const state = {
  watchlist: JSON.parse(localStorage.getItem("fq.watchlist") || '["SPY","AAPL","MSFT","NVDA"]'),
  selected: null,
  range: "1Y",
  chart: null,
  ratings: JSON.parse(localStorage.getItem("fq.ratings") || "{}"), // ticker -> {rating, target}
  lastAnalysis: null,
  wlView: localStorage.getItem("fq.wlview") || "list",
  wlSort: localStorage.getItem("fq.wlsort") || "custom",
  quotes: {},
  horizon: localStorage.getItem("fq.horizon") || "medium",
};
const HORIZON_LABEL = { 21: "1-mo", 63: "3-mo", 126: "6-mo" };

/* ---------- tabs ---------- */
function setTab(tab) {
  state.activeTab = tab;
  localStorage.setItem("fq.tab", tab);
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-section").forEach((s) =>
    s.classList.toggle("hidden", s.id !== "section-" + tab));
  if (tab === "longterm") window.ltInit?.();
  if (tab === "agent") window.agentInit?.();
  if (tab === "live") window.liveInit?.();
}
$("#tabs").onclick = (e) => {
  if (e.target.dataset.tab) setTab(e.target.dataset.tab);
};

/* ---------- theme ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("fq.theme", t);
  $("#themeToggle").textContent = t === "light" ? "Dark" : "Light";
  if (state.selected) drawChart(state.selected, state.range);
}
$("#themeToggle").onclick = () =>
  setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");

/* ---------- helpers ---------- */
const fmt = (x, d = 2) => x == null ? "n/a" : Number(x).toFixed(d);
const pct = (x, d = 1) => x == null ? "n/a" : (100 * x).toFixed(d) + "%";
const cls = (x) => (x >= 0 ? "pos" : "neg");
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
const rateClass = (rating) => ({
  "Strong Buy": "rate-strongbuy", "Buy": "rate-buy", "Hold": "rate-hold",
  "Sell": "rate-sell", "Strong Sell": "rate-strongsell",
}[rating] || "rate-hold");

/* ---------- autocomplete ---------- */
function attachAutocomplete(input, onPick) {
  const wrap = document.createElement("span");
  wrap.className = "ac-wrap";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const list = document.createElement("ul");
  list.className = "ac-list hidden";
  wrap.appendChild(list);

  let items = [], active = -1, timer = null, seq = 0;

  const close = () => { list.classList.add("hidden"); items = []; active = -1; };
  const render = () => {
    list.innerHTML = items.map((it, i) => `
      <li class="${i === active ? "active" : ""}" data-i="${i}">
        <span class="ac-sym">${it.symbol}</span>
        <span class="ac-name">${it.name}${it.exch ? " · " + it.exch : ""}</span>
      </li>`).join("");
    list.classList.toggle("hidden", items.length === 0);
  };
  const pick = (i) => {
    if (i < 0 || i >= items.length) return;
    input.value = items[i].symbol;
    close();
    onPick?.(items[i].symbol);
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 1) return close();
    timer = setTimeout(async () => {
      const mySeq = ++seq;
      try {
        const res = await api(`/api/search?q=${encodeURIComponent(q)}`);
        if (mySeq !== seq) return; // stale response
        items = res; active = -1; render();
      } catch { close(); }
    }, 220);
  });
  input.addEventListener("keydown", (e) => {
    if (list.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, items.length - 1); render(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") close();
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); pick(Number(li.dataset.i)); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
}

/* ---------- stat explanations ---------- */
const T = {
  ret: "Total price return over the trailing window.\nIn plain terms: how much the price went up or down over that period.",
  mom121: "Jegadeesh-Titman momentum: trailing 12-month return excluding the most recent month (which tends to reverse). Positive values historically predicted continued outperformance.\nIn plain terms: stocks that did well over the past year often keep doing well for a while. This measures that, skipping the last month because very recent moves often snap back.",
  rel121: "12-1 momentum minus SPY's over the same window — momentum relative to the market, closer to the original cross-sectional construction. Used to offset the buy bias absolute momentum has in rising markets.\nIn plain terms: did this stock actually beat the market over the past year, or was it just carried along by it?",
  agreement: "Confidence multiplier from component dispersion: when the four models disagree strongly, the composite is shrunk toward Hold.\nIn plain terms: if the models are split, the rating hedges toward the middle instead of pretending to be sure.",
  backtest: "Walk-forward check: each signal is traded on this ticker's past 5 years using only information available at the time, lagged one day, minus 5bp costs per turnover. Compare each strategy's Sharpe to buy-and-hold.\nIn plain terms: 'would this signal actually have made money on this stock?' Past results don't guarantee future ones — but a signal that never worked here deserves extra skepticism.",
  tsmom: "Time-series momentum t-statistic (Moskowitz-Ooi-Pedersen): how statistically distinguishable from zero the asset's own 12-month excess return is. |t| > 1.96 is significant at the 5% level.\nIn plain terms: a confidence check on the past year's trend. Above about 2 (or below −2) means the trend is probably real, not just noise.",
  trend: "Trend state from the 50-day vs 200-day exponential moving average crossover. EMA50 above EMA200 = uptrend.\nIn plain terms: compares the recent average price to the long-run average. Recent above long-run = the stock is generally climbing.",
  adf: "Augmented Dickey-Fuller test for a unit root in log price. p < 0.05 rejects a random walk, i.e. statistically significant evidence the price mean-reverts.\nIn plain terms: tests whether the price tends to bounce back toward a typical level. A value below 0.05 = strong evidence it does.",
  vr: "Lo-MacKinlay variance ratio (q=5). VR < 1 suggests mean reversion, VR > 1 momentum, VR ≈ 1 a random walk.\nIn plain terms: below 1 = price tends to bounce back after moves; above 1 = moves tend to keep going; near 1 = basically a coin flip.",
  halflife: "Ornstein-Uhlenbeck half-life: estimated trading days for a deviation from the mean to decay by half.\nIn plain terms: if the price gets stretched away from normal, this is roughly how many days until half of that stretch unwinds.",
  zscore: "Standard deviations of current price from its 20-bar mean (Bollinger-style).\nIn plain terms: how unusually high or low the price is versus the last month. Beyond ±2 is rare — the price is stretched.",
  realvol: "Realized volatility: annualized standard deviation of daily returns over the window.\nIn plain terms: how bumpy the ride has actually been. 15% is calm; 50%+ is a rollercoaster.",
  garch: "GARCH(1,1) forecast of annualized volatility over the next 21 trading days (Hansen & Lunde 2005 found this very hard to beat).\nIn plain terms: a forecast of how bumpy the next month will be, based on the pattern that turbulent days cluster together.",
  persistence: "α + β from the GARCH fit: how long volatility shocks persist. Near 1 = shocks decay slowly.\nIn plain terms: close to 1 means that once the stock gets turbulent, it stays turbulent for a long time.",
  sharpe: "Sharpe: annualized excess return per unit of volatility. Sortino: same but penalizes only downside moves. > 1 is strong.\nIn plain terms: reward earned per unit of risk taken. Higher is better — above 1 means returns have been worth the bumps.",
  mdd: "Maximum drawdown: worst peak-to-trough loss over the sample.\nIn plain terms: the most money you'd have lost buying at the worst peak and selling at the worst bottom.",
  volmgd: "Volatility-managed position size (Moreira-Muir): 15% target vol ÷ forecast vol, capped at 2x.\nIn plain terms: a suggested position size. Below 1x = the stock is choppy right now, so hold less of it; above 1x = calm enough to hold more.",
  alpha: "Annualized return unexplained by market, size, and value factor exposure; |t| > 2 ≈ statistically significant.\nIn plain terms: the extra return the stock earned beyond what just riding the market would explain. The t number says whether it's real or luck.",
  beta: "Sensitivity to the market (SPY). 1 = moves with the market, > 1 amplified, < 0 inverse.\nIn plain terms: if the market rises 1%, this stock tends to rise by this many percent. 1.5 = exaggerated market moves; 0.5 = muted ones.",
  smbhml: "Exposure to size (small-minus-big, IWM−SPY) and value (value-minus-growth, VTV−VUG) factor proxies.\nIn plain terms: whether the stock behaves more like small companies vs giants (first number), and like cheap 'value' stocks vs expensive growth stocks (second).",
  r2: "Share of daily return variance explained by the factor regression (0–1).\nIn plain terms: how much of the stock's movement is just the overall market moving it. Near 1 = mostly follows the market; near 0 = marches to its own beat.",
  idio: "Idiosyncratic volatility: annualized vol of residual returns after removing factor effects.\nIn plain terms: the part of the bumpiness that's unique to this company, not the market.",
  score: "Model output normalized to [−1, +1]; positive = bullish contribution to the composite rating.\nIn plain terms: this model's vote, from −1 (very bearish) to +1 (very bullish).",
  target: "Model price expectation at the selected horizon (1M = 21, 3M = 63, 6M = 126 trading days): shrunk-drift projection blended with the mean-reversion target, weighted by stationarity evidence. Shorter horizons use shorter data windows.\nIn plain terms: the models' best guess of the price at the horizon you picked above.",
  interval: "80% interval, preferably from a block bootstrap of the ticker's own return history (captures fat tails and skew that a normal-distribution assumption misses); falls back to lognormal with drift uncertainty.\nIn plain terms: the models think there's an 80% chance the price lands in this range — built by replaying thousands of shuffled chunks of the stock's actual past moves.",
  regime: "Market state: SPY above its 200-day average = bull, below = bear. Shown as context (momentum historically earns less after down markets — Cooper-Gutierrez-Hameed 2004) but it does NOT change the model weights, to avoid discretionary tilts.\nIn plain terms: a weather report for the overall market — informational only.",
  composite: "Equal-weighted (1/N) blend of the four model scores — DeMiguel-Garlappi-Uppal (2009) show naive equal weighting is very hard to beat out of sample — then shrunk toward Hold when the models disagree.\nIn plain terms: all four models get one vote each; a split vote moves the rating toward the middle.",
  eg: "Engle-Granger two-step cointegration test. p < 0.05 = stable long-run relationship between the two prices.\nIn plain terms: tests whether two stocks are tied together long-term, like two boats anchored to the same dock. Below 0.05 = yes.",
  hedge: "OLS slope of log(A) on log(B): dollars of B to short per dollar of A for a market-neutral spread.\nIn plain terms: the recipe for a balanced bet — how much of the second stock offsets one unit of the first.",
  spreadz: "Standard deviations of the current spread from its historical mean. Classic rule (Gatev et al.): open at |z| > 1–2, close at z = 0.\nIn plain terms: how far apart the pair has drifted compared to usual. Big gaps tend to close, which is what the trade bets on.",
};
const tip = (label, key) => key ? `<span class="tip" data-tip="${T[key]}">${label}</span>` : label;

/* ---------- watchlist ---------- */
function saveWatchlist() {
  localStorage.setItem("fq.watchlist", JSON.stringify(state.watchlist));
}
function displayOrder() {
  const arr = [...state.watchlist];
  const sc = (t) => state.ratings[t]?.score ?? -Infinity;
  const ch = (t) => state.quotes[t]?.changePct ?? -Infinity;
  if (state.wlSort === "score") arr.sort((a, b) => sc(b) - sc(a));
  else if (state.wlSort === "scoreAsc") arr.sort((a, b) => sc(a) - sc(b));
  else if (state.wlSort === "change") arr.sort((a, b) => ch(b) - ch(a));
  else if (state.wlSort === "alpha") arr.sort();
  return arr;
}
let dragTicker = null;
async function renderWatchlist() {
  const ul = $("#watchlist");
  ul.innerHTML = "";
  const grid = state.wlView === "grid";
  ul.classList.toggle("grid-view", grid);
  const tgl = $("#wlViewToggle");
  if (tgl) tgl.textContent = grid ? "List" : "Grid";
  for (const t of displayOrder()) {
    const li = document.createElement("li");
    li.dataset.ticker = t;
    li.draggable = true;
    if (t === state.selected) li.classList.add("selected");
    const known = state.ratings[t];
    const badge = known
      ? `<span class="wl-badge ${rateClass(known.rating)}">${known.rank ? "#" + known.rank + " · " : ""}${known.rating} · $${known.target}</span>`
      : "";
    li.innerHTML = grid ? `
      <span class="wl-name">${t}</span>
      ${badge || '<span class="wl-badge">unrated</span>'}
      <span class="wl-price" id="price-${t}">—</span>
      <span class="wl-chg" id="chg-${t}"></span>
      <button class="wl-remove" data-remove="${t}" title="Remove">×</button>` : `
      <div><span class="wl-name">${t}</span>
        ${badge}
        <span class="wl-sub" id="sub-${t}">loading…</span></div>
      <canvas class="wl-spark" id="spark-${t}" width="92" height="34"></canvas>
      <div class="wl-right">
        <div class="wl-price" id="price-${t}">—</div>
        <div class="wl-chg" id="chg-${t}"></div>
        <button class="wl-remove" data-remove="${t}" title="Remove">×</button>
      </div>`;
    li.onclick = (e) => {
      if (e.target.dataset.remove) {
        state.watchlist = state.watchlist.filter((x) => x !== e.target.dataset.remove);
        saveWatchlist(); renderWatchlist(); return;
      }
      select(t);
    };
    ul.appendChild(li);
    loadQuote(t);
  }
}
async function loadQuote(t) {
  try {
    const grid = state.wlView === "grid";
    const q = await api(`/api/quote/${t}`);
    state.quotes[t] = q;
    const p = $(`#price-${t}`); if (p) p.textContent = fmt(q.price);
    const c = $(`#chg-${t}`);
    if (c) {
      c.textContent = `${q.change >= 0 ? "+" : ""}${fmt(q.change)} (${fmt(q.changePct)}%)`;
      c.className = "wl-chg " + cls(q.change);
    }
    const sub = $(`#sub-${t}`);
    if (sub) sub.textContent = "as of " + q.asOf.slice(0, 10);
    if (!grid) {
      const h = await getHistory(t, "6M");
      sparkline($(`#spark-${t}`), h.c);
    }
  } catch (e) {
    const el = $(`#sub-${t}`) || $(`#chg-${t}`);
    if (el) el.textContent = "error: " + e.message;
  }
}
function sparkline(canvas, series) {
  if (!canvas || !series?.length) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...series), max = Math.max(...series);
  ctx.beginPath();
  series.forEach((v, i) => {
    const x = (i / (series.length - 1)) * w;
    const y = h - ((v - min) / (max - min || 1)) * (h - 4) - 2;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = series.at(-1) >= series[0] ? cssVar("--pos") : cssVar("--neg");
  ctx.lineWidth = 1.4;
  ctx.stroke();
}
async function addTicker(t) {
  t = (t || "").trim().toUpperCase();
  if (!t) return false;
  if (state.watchlist.includes(t)) { select(t); return true; }
  try {
    await api(`/api/quote/${t}`); // validate
    state.watchlist.push(t); saveWatchlist();
    renderWatchlist(); select(t);
    return true;
  } catch (err) {
    alert(`Could not load "${t}": ${err.message}`);
    return false;
  }
}
$("#addForm").onsubmit = async (e) => {
  e.preventDefault();
  if (await addTicker($("#tickerInput").value)) $("#tickerInput").value = "";
};
/* ---------- watchlist: drag reorder + sort + analyze all ---------- */
const wlUl = $("#watchlist");
wlUl.addEventListener("dragstart", (e) => {
  const li = e.target.closest("li[data-ticker]");
  if (!li) return;
  dragTicker = li.dataset.ticker;
  li.classList.add("dragging");
});
wlUl.addEventListener("dragend", (e) => {
  e.target.closest("li")?.classList.remove("dragging");
  wlUl.querySelectorAll(".drag-over").forEach((x) => x.classList.remove("drag-over"));
});
wlUl.addEventListener("dragover", (e) => {
  e.preventDefault();
  const li = e.target.closest("li[data-ticker]");
  wlUl.querySelectorAll(".drag-over").forEach((x) => x.classList.remove("drag-over"));
  if (li && li.dataset.ticker !== dragTicker) li.classList.add("drag-over");
});
wlUl.addEventListener("drop", (e) => {
  e.preventDefault();
  const li = e.target.closest("li[data-ticker]");
  if (!li || !dragTicker || li.dataset.ticker === dragTicker) return;
  // Take the currently displayed order, move dragged ticker before the drop
  // target, and make that the new custom order.
  const order = displayOrder().filter((t) => t !== dragTicker);
  order.splice(order.indexOf(li.dataset.ticker), 0, dragTicker);
  state.watchlist = order;
  state.wlSort = "custom";
  $("#wlSort").value = "custom";
  localStorage.setItem("fq.wlsort", "custom");
  dragTicker = null;
  saveWatchlist();
  renderWatchlist();
});
$("#wlSort").onchange = () => {
  state.wlSort = $("#wlSort").value;
  localStorage.setItem("fq.wlsort", state.wlSort);
  renderWatchlist();
};
$("#wlAnalyzeAll").onclick = async () => {
  const btn = $("#wlAnalyzeAll");
  btn.disabled = true;
  const list = [...state.watchlist];
  let failed = [];
  for (let i = 0; i < list.length; i++) {
    const t = list[i];
    $("#wlProgress").textContent = `Analyzing ${t} (${i + 1}/${list.length})…`;
    try {
      const a = await api(`/api/analyze/${t}?horizon=${state.horizon}`);
      state.ratings[t] = {
        rating: a.composite.rating, target: a.priceTarget.target,
        score: a.composite.score, date: new Date().toISOString().slice(0, 10),
      };
      if (t === state.selected) {
        state.lastAnalysis = a;
        renderAnalysis(a);
        renderRatingPanel(t);
        $("#viewReport").disabled = false;
        const pdf = $("#pdfLink");
        pdf.classList.remove("disabled");
        pdf.href = `/api/report/${t}/pdf`;
      }
    } catch (err) { failed.push(t); }
  }
  // Cross-sectional rank: percentile position of each composite score.
  // Relative ranking across the candidate set is how cross-sectional
  // strategies are actually constructed (Jegadeesh-Titman deciles).
  const ranked = list.filter((t) => state.ratings[t])
    .sort((a, b) => state.ratings[b].score - state.ratings[a].score);
  ranked.forEach((t, i) => { state.ratings[t].rank = i + 1; });
  localStorage.setItem("fq.ratings", JSON.stringify(state.ratings));
  $("#wlProgress").textContent =
    `Done — ranked ${ranked.length}/${list.length}` +
    (failed.length ? ` (failed: ${failed.join(", ")})` : "");
  renderWatchlist();
  btn.disabled = false;
  setTimeout(() => { $("#wlProgress").textContent = ""; }, 8000);
};

$("#wlAddBtn").onclick = () => {
  const f = $("#wlAddForm");
  f.classList.toggle("hidden");
  if (!f.classList.contains("hidden")) $("#wlAddInput").focus();
};
$("#wlAddForm").onsubmit = async (e) => {
  e.preventDefault();
  if (await addTicker($("#wlAddInput").value)) {
    $("#wlAddInput").value = "";
    $("#wlAddForm").classList.add("hidden");
  }
};
$("#ratingAddForm").onsubmit = async (e) => {
  e.preventDefault();
  if (await addTicker($("#ratingAddInput").value)) $("#ratingAddInput").value = "";
};

/* ---------- chart ---------- */
const histCache = {}; // `${ticker}|${range}` -> {ts, data}
const HIST_TTL = 5 * 60 * 1000;

async function getHistory(t, range) {
  const key = `${t}|${range}`;
  const hit = histCache[key];
  if (hit && Date.now() - hit.ts < HIST_TTL) return hit.data;
  const data = await api(`/api/history/${t}?range=${range}`);
  histCache[key] = { ts: Date.now(), data };
  return data;
}

async function prefetchHistories() {
  // Warm the cache so watchlist clicks render instantly.
  for (const t of state.watchlist) {
    const key = `${t}|${state.range}`;
    if (histCache[key] && Date.now() - histCache[key].ts < HIST_TTL) continue;
    try { await getHistory(t, state.range); } catch {}
  }
}

async function drawChart(t, range) {
  // Render whatever is cached immediately, then refresh if stale.
  const key = `${t}|${range}`;
  const cached = histCache[key];
  if (cached) renderChart(t, range, cached.data);
  if (!cached || Date.now() - cached.ts >= HIST_TTL) {
    try {
      const h = await getHistory(t, range);
      if (state.selected === t && state.range === range) renderChart(t, range, h);
    } catch (e) {
      if (!cached) $("#chartTitle").textContent = `${t} — ${e.message}`;
    }
  }
}

function renderChart(t, range, h) {
  $("#chartTitle").textContent = `${t} — ${range}`;
  const labels = h.t.map((s) => s.slice(0, range === "1W" || range === "1M" ? 16 : 10));
  if (state.chart) state.chart.destroy();
  const up = h.c.at(-1) >= h.c[0];
  const lineColor = cssVar(up ? "--pos" : "--neg");
  state.chart = new Chart($("#priceChart"), {
    type: "line",
    data: { labels, datasets: [{
      data: h.c, borderColor: lineColor, borderWidth: 1.6,
      pointRadius: 0, fill: false, tension: 0,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { intersect: false, mode: "index" } },
      scales: {
        x: { ticks: { color: cssVar("--muted"), maxTicksLimit: 8 }, grid: { display: false } },
        y: { ticks: { color: cssVar("--muted") }, grid: { color: cssVar("--border") } },
      },
    },
  });
}
$("#rangeGroup").onclick = (e) => {
  if (!e.target.dataset.range) return;
  state.range = e.target.dataset.range;
  document.querySelectorAll("#rangeGroup button").forEach((b) =>
    b.classList.toggle("active", b === e.target));
  if (state.selected) drawChart(state.selected, state.range);
  prefetchHistories();
};

function select(t) {
  state.selected = t;
  document.querySelectorAll("#watchlist li").forEach((li) =>
    li.classList.toggle("selected", li.dataset.ticker === t));
  drawChart(t, state.range);
  $("#viewReport").disabled = !state.lastAnalysis || state.lastAnalysis.ticker !== t;
  renderRatingPanel(t);
}

/* ---------- analysis ---------- */
async function runAnalysisFor(force = false) {
  if (!state.selected) return alert("Select a ticker first.");
  const t = state.selected;
  $("#analysisBody").innerHTML = `<span class="muted">Running models on ${t}…</span>`;
  try {
    const a = await api(`/api/analyze/${t}?horizon=${state.horizon}${force ? "&force=true" : ""}`);
    state.lastAnalysis = a;
    state.ratings[t] = {
      rating: a.composite.rating,
      target: a.priceTarget.target,
      score: a.composite.score,
      date: new Date().toISOString().slice(0, 10),
      rank: state.ratings[t]?.rank, // keep cross-sectional rank from Analyze all
    };
    localStorage.setItem("fq.ratings", JSON.stringify(state.ratings));
    renderAnalysis(a);
    renderRatingPanel(t);
    renderWatchlist();
    $("#viewReport").disabled = false;
    const pdf = $("#pdfLink");
    pdf.classList.remove("disabled");
    pdf.href = `/api/report/${t}/pdf?horizon=${state.horizon}`;
  } catch (e) {
    $("#analysisBody").innerHTML = `<span class="neg">Analysis failed: ${e.message}</span>`;
  }
}
$("#runAnalysis").onclick = () => runAnalysisFor(false);
$("#ratingAnalyze").onclick = () => runAnalysisFor(false);
$("#horizonGroup").onclick = (e) => {
  const h = e.target.dataset.h;
  if (!h) return;
  state.horizon = h;
  localStorage.setItem("fq.horizon", h);
  document.querySelectorAll("#horizonGroup button").forEach((b) =>
    b.classList.toggle("active", b === e.target));
  if (state.selected) runAnalysisFor(false); // re-rate at the new horizon
};

function kv(label, value, tipKey) {
  return `<div class="kv"><span>${tip(label, tipKey)}</span><span>${value}</span></div>`;
}
function renderAnalysis(a) {
  const m = a.momentum, mr = a.meanReversion, v = a.volatility, f = a.factors;
  const g = v.garch;
  $("#analysisBody").innerHTML = `<div class="analysis-grid">
    <div class="model-card"><h3>Momentum & Trend</h3>
      ${kv("1m / 3m", `${pct(m.lookbackReturns["1m"])} / ${pct(m.lookbackReturns["3m"])}`, "ret")}
      ${kv("6m / 12m", `${pct(m.lookbackReturns["6m"])} / ${pct(m.lookbackReturns["12m"])}`, "ret")}
      ${kv("12-1 momentum", pct(m.mom12_1), "mom121")}
      ${kv("12-1 vs SPY", pct(m.rel12_1), "rel121")}
      ${kv("TSMOM t-stat", fmt(m.tsmom.tStat), "tsmom")}
      ${m.trend ? kv("Trend (EMA50/200)", m.trend.state, "trend") : ""}
      ${kv("Score", `<b>${fmt(m.score)}</b>`, "score")}
      <div class="cite">Jegadeesh-Titman 1993; Moskowitz-Ooi-Pedersen 2012</div></div>
    <div class="model-card"><h3>Mean Reversion</h3>
      ${kv("ADF p-value", fmt(mr.adf.pValue, 4), "adf")}
      ${kv("Variance ratio (q=5)", `${fmt(mr.varianceRatio.vr)} (z ${fmt(mr.varianceRatio.z)})`, "vr")}
      ${kv("OU half-life", mr.halfLifeDays ? mr.halfLifeDays + "d" : "n/a", "halflife")}
      ${kv("20-bar z-score", fmt(mr.zScore20), "zscore")}
      ${kv("Score", `<b>${fmt(mr.score)}</b>`, "score")}
      <div class="cite">Dickey-Fuller; Lo-MacKinlay 1988; Avellaneda-Lee 2010</div></div>
    <div class="model-card"><h3>Volatility & Risk</h3>
      ${kv("Realized 21d / 252d", `${pct(v.realized["21d"])} / ${pct(v.realized["252d"])}`, "realvol")}
      ${kv((g.model || "GARCH") + " fcst", pct(g.annVolForecast21d), "garch")}
      ${g.ok ? kv("Persistence α+β", fmt(g.persistence, 3), "persistence") : ""}
      ${kv("Sharpe / Sortino", `${fmt(v.risk.sharpe)} / ${fmt(v.risk.sortino)}`, "sharpe")}
      ${kv("Max drawdown", pct(v.risk.maxDrawdown), "mdd")}
      ${kv("Vol-managed weight", fmt(v.volManaged.weight) + "x", "volmgd")}
      ${kv("Score", `<b>${fmt(v.score)}</b>`, "score")}
      <div class="cite">Bollerslev 1986; Hansen-Lunde 2005; Moreira-Muir 2017</div></div>
    <div class="model-card"><h3>Factor Regression</h3>
      ${f ? `
        ${kv("Alpha (ann.)", `${pct(f.alphaAnnual)} (t ${fmt(f.alphaTStat)})`, "alpha")}
        ${kv("Beta MKT", fmt(f.betas.MKT), "beta")}
        ${kv("Beta SMB / HML", `${fmt(f.betas.SMB)} / ${fmt(f.betas.HML)}`, "smbhml")}
        ${kv("R²", fmt(f.r2), "r2")}
        ${kv("Idio vol (ann.)", pct(f.idioVolAnnual), "idio")}
        ${kv("Score", `<b>${fmt(f.score)}</b>`, "score")}` : `<div class="muted">Unavailable</div>`}
      <div class="cite">Fama-French 1993; Newey-West HAC errors</div></div>
    ${a.backtest && a.backtest.ok ? `<div class="model-card"><h3>${tip("Walk-Forward Check (5y)", "backtest")}</h3>
      ${kv("TSMOM Sharpe", fmt(a.backtest.tsmom.sharpe), "backtest")}
      ${a.backtest.tsmomVolScaled ? kv("TSMOM vol-scaled Sharpe", fmt(a.backtest.tsmomVolScaled.sharpe), "volmgd") : ""}
      ${kv("MR-fade Sharpe", fmt(a.backtest.meanrev.sharpe), "backtest")}
      ${kv("Buy & hold Sharpe", fmt(a.backtest.buyHold.sharpe), "sharpe")}
      ${kv("TSMOM ann. return", pct(a.backtest.tsmom.annReturn))}
      ${kv("TSMOM max DD", pct(a.backtest.tsmom.maxDD), "mdd")}
      ${kv("Eval window", a.backtest.evalDays + "d, cost " + a.backtest.costBps + "bp")}
      <div class="cite">Signals lagged 1 day; Cederburg et al. 2020 caveat applies</div></div>` : ""}
  </div>`;
}

function renderRatingPanel(t) {
  const body = $("#ratingBody");
  const a = state.lastAnalysis;
  if (a && a.ticker === t) {
    const c = a.composite, p = a.priceTarget;
    const x = ((c.score + 1) / 2) * 100;
    body.classList.remove("muted");
    body.innerHTML = `
      <div class="big-rating ${rateClass(c.rating)}">${c.rating}</div>
      <div class="muted">${tip("composite score", "composite")} ${fmt(c.score)}</div>
      <div class="score-bar"><i style="left:${x}%"></i></div>
      <div class="rating-row"><span>Spot</span><span>$${fmt(p.spot)}</span></div>
      <div class="rating-row"><span>${tip((HORIZON_LABEL[p.horizonDays] || p.horizonDays + "d") + " target", "target")}</span><span><b>$${fmt(p.target)}</b>
        (<span class="${cls(p.expectedReturnPct)}">${fmt(p.expectedReturnPct)}%</span>)</span></div>
      <div class="rating-row"><span>${tip("80% interval", "interval")}</span><span>$${fmt(p.low80)} – $${fmt(p.high80)}</span></div>
      <div class="rating-row"><span>${tip("Signal agreement", "agreement")}</span><span>${c.confidence != null ? Math.round(c.confidence * 100) + "%" : "n/a"}</span></div>
      ${c.marketRegime ? `<div class="rating-row"><span>${tip("Market regime", "regime")}</span><span>${c.marketRegime}</span></div>` : ""}
      <div class="rating-row"><span>${tip("Momentum", "score")}</span><span>${fmt(c.components.momentum)}</span></div>
      <div class="rating-row"><span>${tip("Mean reversion", "score")}</span><span>${fmt(c.components.meanReversion)}</span></div>
      <div class="rating-row"><span>${tip("Volatility", "score")}</span><span>${fmt(c.components.volatility)}</span></div>
      <div class="rating-row"><span>${tip("Factor alpha", "score")}</span><span>${fmt(c.components.factors)}</span></div>
      <button class="btn ghost analyze-again" id="analyzeAgain">Analyze again</button>`;
  } else if (state.ratings[t]) {
    const r = state.ratings[t];
    body.classList.remove("muted");
    body.innerHTML = `
      <div class="big-rating ${rateClass(r.rating)}">${r.rating}</div>
      <div class="muted">cached ${r.date} · score ${fmt(r.score)} · target $${r.target}</div>
      <button class="btn ghost analyze-again" id="analyzeAgain">Analyze again</button>`;
  } else {
    body.classList.add("muted");
    body.textContent = "Run an analysis to see the rating.";
  }
  const again = $("#analyzeAgain");
  if (again) again.onclick = () => {
    again.textContent = "Re-running…";
    runAnalysisFor(true);
  };
}

/* ---------- pairs ---------- */
$("#pairsForm").onsubmit = async (e) => {
  e.preventDefault();
  const a = $("#pairA").value.trim(), b = $("#pairB").value.trim();
  if (!a || !b) return;
  $("#pairsBody").innerHTML = `<span class="muted">Testing ${a}/${b}…</span>`;
  try {
    const p = await api(`/api/pairs?a=${a}&b=${b}`);
    $("#pairsBody").innerHTML = `<div class="model-card"><h3>${p.pair}</h3>
      ${kv("Engle-Granger t / p", `${fmt(p.engleGranger.tStat)} / ${fmt(p.engleGranger.pValue, 4)}`, "eg")}
      ${kv("Cointegrated (5%)", p.engleGranger.cointegrated ? "yes" : "no", "eg")}
      ${kv("Hedge ratio", fmt(p.hedgeRatio, 3), "hedge")}
      ${kv("Spread z-score", fmt(p.spreadZ), "spreadz")}
      ${kv("Spread half-life", p.spreadHalfLifeDays ? p.spreadHalfLifeDays + "d" : "n/a", "halflife")}
      ${kv("Signal", p.signal)}
      <div class="cite">Engle-Granger 1987; Gatev-Goetzmann-Rouwenhorst 2006</div></div>`;
  } catch (err) {
    $("#pairsBody").innerHTML = `<span class="neg">${err.message}</span>`;
  }
};

/* ---------- report ---------- */
$("#viewReport").onclick = async () => {
  if (!state.selected) return;
  const t = state.selected;
  $("#reportContent").innerHTML = `<p class="muted">Building report…</p>`;
  $("#reportView").classList.remove("hidden");
  document.querySelectorAll(".tab-section").forEach((s) => s.classList.add("hidden"));
  document.querySelector("header.topbar").classList.add("hidden");
  try {
    const r = await api(`/api/report/${t}?horizon=${state.horizon}`);
    renderReport(r);
  } catch (e) {
    $("#reportContent").innerHTML = `<p class="neg">${e.message}</p>`;
  }
};
$("#closeReport").onclick = () => {
  $("#reportView").classList.add("hidden");
  document.querySelector("header.topbar").classList.remove("hidden");
  setTab(state.activeTab || "swing");
};
$("#printReport").onclick = () => window.print();

function renderReport(r) {
  const p = r.priceTarget;
  const titles = { momentum: "Momentum & Trend", meanReversion: "Mean Reversion",
                   volatility: "Volatility & Risk", factors: "Factor Regression",
                   backtest: "Walk-Forward Backtest" };
  const scoreRows = Object.entries(r.models)
    .filter(([, v]) => v && v.score != null)
    .map(([k, v]) => `<tr><td>${titles[k]}</td><td>${fmt(v.score)}</td></tr>`).join("");
  const just = Object.entries(r.justification).map(([k, b]) => `
    <h2>${titles[k]}</h2><p>${b.text}</p>
    <p class="disclaimer">References: ${b.citation}</p>`).join("");
  $("#reportContent").innerHTML = `
    <h1>${r.ticker} — Quantitative Research Report</h1>
    <p class="meta">${r.date} · Spot $${p.spot} · Rating <b>${r.rating}</b> ·
      3-mo target $${p.target} (80% interval $${p.low80}–$${p.high80})</p>
    <h2>Thesis</h2><p>${r.thesis}</p>
    ${just}
    <h2>Model Scores</h2>
    <table><tr><th>Component</th><th>Score [-1, +1]</th></tr>
      ${scoreRows}
      <tr><td><b>Composite</b></td><td><b>${fmt(r.compositeScore)}</b></td></tr></table>
    <h2>Summary</h2><p>${r.summary}</p>
    <p class="disclaimer">${r.disclaimer}</p>`;
}

/* ---------- init ---------- */
setTheme(localStorage.getItem("fq.theme") || "light");
$("#wlSort").value = state.wlSort;
$("#wlViewToggle").onclick = () => {
  state.wlView = state.wlView === "grid" ? "list" : "grid";
  localStorage.setItem("fq.wlview", state.wlView);
  renderWatchlist();
};
attachAutocomplete($("#tickerInput"), () => $("#addForm").requestSubmit());
attachAutocomplete($("#wlAddInput"), () => $("#wlAddForm").requestSubmit());
attachAutocomplete($("#ratingAddInput"), () => $("#ratingAddForm").requestSubmit());
attachAutocomplete($("#pairA"));
attachAutocomplete($("#pairB"));

/* ---------- LLM settings modal ---------- */
$("#llmBtn").onclick = async () => {
  $("#llmModal").classList.remove("hidden");
  try {
    const [cfg, st] = await Promise.all([api("/api/llm/config"), api("/api/llm/status")]);
    $("#llmProvider").value = cfg.provider || "";
    $("#llmKey").placeholder = cfg.anthropicKey || (cfg.envKeyPresent ? "(using env key)" : "sk-ant-…");
    $("#llmModel").placeholder = cfg.anthropicModel || "claude-sonnet-4-6";
    $("#llmOllamaUrl").placeholder = cfg.ollamaUrl || "http://localhost:11434";
    $("#llmOllamaModel").placeholder = cfg.ollamaModel || "qwen2.5:14b";
    $("#llmModalStatus").innerHTML = st.ready
      ? `Status: <span class="pos">ready</span> — ${st.provider} (${st.model})`
      : `Status: <span class="neg">not ready</span> — ${st.hint || st.provider}`;
  } catch {}
};
$("#llmClose").onclick = () => $("#llmModal").classList.add("hidden");
$("#llmModal").onclick = (e) => {
  if (e.target.id === "llmModal") $("#llmModal").classList.add("hidden");
};
$("#llmSave").onclick = async () => {
  $("#llmModalStatus").textContent = "Saving…";
  try {
    const st = await fetch("/api/llm/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: $("#llmProvider").value,
        anthropicKey: $("#llmKey").value || null,
        anthropicModel: $("#llmModel").value || null,
        ollamaUrl: $("#llmOllamaUrl").value || null,
        ollamaModel: $("#llmOllamaModel").value || null,
      }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    });
    $("#llmKey").value = "";
    $("#llmModalStatus").innerHTML = st.ready
      ? `Status: <span class="pos">ready</span> — ${st.provider} (${st.model})`
      : `Status: <span class="neg">not ready</span> — ${st.hint || st.provider}`;
  } catch (e) {
    $("#llmModalStatus").innerHTML = `<span class="neg">${e.message}</span>`;
  }
};
renderWatchlist();
if (state.watchlist.length) select(state.watchlist[0]);
setTab(localStorage.getItem("fq.tab") || "swing");
prefetchHistories();
