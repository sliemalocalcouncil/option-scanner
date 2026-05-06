/* ---------- helpers ---------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d);
const fmtInt = (v) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString();
const setStatus = (msg, cls = "") => {
  const el = $("#status");
  el.textContent = msg;
  el.className = `status ${cls}`;
};

async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) url.searchParams.set(k, v);
  });
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/* ---------- charts ---------- */
let optChart, ulChart;

function makeLineChart(canvas, label, color) {
  return new Chart(canvas, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label, data: [], borderColor: color, backgroundColor: color + "22",
          fill: true, tension: 0.2, borderWidth: 1.5, pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { labels: { color: "#8b94a5" } } },
      scales: {
        x: { ticks: { color: "#8b94a5", maxRotation: 0 }, grid: { color: "#1c2230" } },
        y: { ticks: { color: "#8b94a5" }, grid: { color: "#1c2230" } },
      },
    },
  });
}

function fillChart(chart, bars) {
  if (!bars || !bars.length) {
    chart.data.labels = []; chart.data.datasets[0].data = []; chart.update(); return;
  }
  chart.data.labels = bars.map((b) => new Date(b.t).toISOString().slice(0, 10));
  chart.data.datasets[0].data = bars.map((b) => b.c);
  chart.update();
}

/* ---------- sentiment scorecard ---------- */
function classifyClass(score) {
  if (score === null || score === undefined) return "neut";
  if (score >= 15) return "bull";
  if (score <= -15) return "bear";
  return "neut";
}

function barRow(name, score, valueText) {
  // -100 ~ +100 점수를 0~50% (음수) 또는 50~100% (양수) bar 로 변환
  let html;
  if (score === null || score === undefined || Number.isNaN(score)) {
    html = `<div class="bar-fill na" style="left:49%; width:2%"></div>`;
  } else {
    const s = Math.max(-100, Math.min(100, score));
    if (s >= 0) {
      const w = (s / 100) * 50;
      html = `<div class="bar-fill" style="left:50%; width:${w}%"></div>`;
    } else {
      const w = (-s / 100) * 50;
      const left = 50 - w;
      html = `<div class="bar-fill neg" style="left:${left}%; width:${w}%"></div>`;
    }
  }
  return `
    <div class="bar-row">
      <span class="name">${name}</span>
      <div class="bar-track">${html}</div>
      <span class="val">${valueText}</span>
    </div>`;
}

function renderSentiment(data) {
  const body = document.querySelector("#sentimentBody");
  const overall = data.overall_score;
  const cls = classifyClass(overall);

  const opt = data.option;
  const stk = data.stock;

  const optComp = opt.components || {};
  const stkComp = stk.components || {};

  const fmtSig = (v, d = 2) => v == null ? "—" : Number(v).toFixed(d);

  const optRows = [
    barRow("P/C VOL",    optComp.pc_volume?.score,
           fmtSig(optComp.pc_volume?.ratio, 2)),
    barRow("P/C OI",     optComp.pc_oi?.score,
           fmtSig(optComp.pc_oi?.ratio, 2)),
    barRow("IV SKEW",    optComp.iv_skew?.score,
           optComp.iv_skew?.skew == null
             ? "—"
             : (optComp.iv_skew.skew * 100).toFixed(2) + "%"),
    barRow("ΔW · OI",    optComp.dw_oi?.score,
           fmtSig(optComp.dw_oi?.net, 0)),
    barRow("ΔW · VOL",   optComp.dw_volume?.score,
           fmtSig(optComp.dw_volume?.net, 0)),
  ].join("");

  const stkRows = [
    barRow("MA POSITION", stkComp.ma_position?.score,
           fmtSig(stkComp.ma_position?.last, 2)),
    barRow("RSI 14",      stkComp.rsi_zone?.score,
           fmtSig(stkComp.rsi_zone?.rsi, 1)),
    barRow("MACD HIST",   stkComp.macd_hist?.score,
           fmtSig(stkComp.macd_hist?.hist, 4)),
    barRow("MOMENTUM 5D", stkComp.momentum_5d?.score,
           stkComp.momentum_5d?.ret_5d == null
             ? "—"
             : (stkComp.momentum_5d.ret_5d * 100).toFixed(2) + "%"),
  ].join("");

  body.classList.remove("sentiment-empty");
  body.innerHTML = `
    <div class="sentiment-grid">
      <div class="sentiment-hero ${cls}">
        <div class="label">${data.label}</div>
        <div class="score">${overall == null ? "—" : (overall >= 0 ? "+" : "") + overall.toFixed(0)}</div>
        <div class="meta">
          ${data.underlying} · ${data.n_contracts_used ?? 0} 계약 · 15m 지연<br/>
          option ${opt.score == null ? "—" : opt.score.toFixed(0)} ×0.6 +
          stock ${stk.score == null ? "—" : stk.score.toFixed(0)} ×0.4
        </div>
      </div>

      <div class="sentiment-bars">
        <div class="sentiment-section">
          <h3>OPTION SIGNALS <span class="agg">${opt.score == null ? "—" : opt.score.toFixed(1)}</span></h3>
          ${optRows}
        </div>
        <div class="sentiment-section">
          <h3>STOCK SIGNALS <span class="agg">${stk.score == null ? "—" : stk.score.toFixed(1)}</span></h3>
          ${stkRows}
        </div>
      </div>
    </div>
  `;
}

function renderUOA(data) {
  const tbody = document.querySelector("#uoaTable tbody");
  tbody.innerHTML = "";
  if (!data.results || !data.results.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="11" style="text-align:left; color: var(--fg-dim);">
      현재 기준치를 만족하는 UOA 후보가 없습니다.</td>`;
    tbody.appendChild(tr);
    return;
  }
  data.results.slice(0, 30).forEach((r) => {
    const tr = document.createElement("tr");
    const score = r.uoa_score || 0;
    const barW = Math.max(0, Math.min(100, score)) * 0.7;
    tr.innerHTML = `
      <td class="tk">${r.ticker}</td>
      <td class="${r.contract_type}">${(r.contract_type || "").toUpperCase()}</td>
      <td>${fmt(r.strike, 2)}</td>
      <td>${r.expiration_date || "—"}</td>
      <td>${r.dte ?? "—"}</td>
      <td>${fmtInt(r.volume)}</td>
      <td>${fmtInt(r.open_interest)}</td>
      <td>${fmt(r.vol_oi_ratio, 2)}</td>
      <td>${fmt(r.z_score, 1)}</td>
      <td>${r.oi_jump?.pct == null ? "—" : r.oi_jump.pct.toFixed(0) + "%"}</td>
      <td class="score-cell">
        <span class="score-bar" style="width:${barW}px"></span>${fmt(score, 0)}
      </td>
    `;
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => selectOption(r.ticker));
    tbody.appendChild(tr);
  });
}

/* ---------- chain table ---------- */
function renderChain(data) {
  const ul = data.underlying_price;
  $("#ulPrice").textContent = ul ? `${data.underlying} @ ${fmt(ul, 2)}` : data.underlying;

  const tbody = $("#chainTable tbody");
  tbody.innerHTML = "";
  data.results.forEach((r) => {
    const tr = document.createElement("tr");
    tr.dataset.ticker = r.ticker;
    tr.innerHTML = `
      <td class="tk">${r.ticker}</td>
      <td class="${r.contract_type}">${(r.contract_type || "").toUpperCase()}</td>
      <td>${fmt(r.strike, 2)}</td>
      <td>${r.expiration_date || "—"}</td>
      <td>${r.dte ?? "—"}</td>
      <td>${fmt(r.iv, 3)}</td>
      <td>${fmt(r.delta, 3)}</td>
      <td>${fmt(r.gamma, 4)}</td>
      <td>${fmt(r.theta, 3)}</td>
      <td>${fmt(r.vega, 3)}</td>
      <td>${fmtInt(r.open_interest)}</td>
      <td>${fmtInt(r.volume)}</td>
      <td>${fmt(r.day_close, 2)}</td>
      <td>${fmt(r.rank_volume, 0)}</td>
      <td>${fmt(r.rank_oi, 0)}</td>
      <td>${fmt(r.rank_iv, 0)}</td>
      <td><span class="score-pill">${fmt(r.score, 0)}</span></td>
    `;
    tr.addEventListener("click", () => selectOption(r.ticker, tr));
    tbody.appendChild(tr);
  });
}

/* ---------- recommended cards ---------- */
function renderCards(data) {
  const cards = $("#cards");
  cards.innerHTML = "";
  data.results.slice(0, 8).forEach((r) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="row">
        <span class="badge-c ${r.contract_type}">${(r.contract_type || "").toUpperCase()}</span>
        <span class="meta">${r.expiration_date || "—"} · DTE ${r.dte ?? "—"}</span>
      </div>
      <div class="tk" style="margin-top:8px">${r.ticker}</div>
      <div class="meta" style="margin-top:4px">strike ${fmt(r.strike, 2)} · last ${fmt(r.day_close, 2)}</div>
      <div class="row" style="margin-top:8px">
        <span class="num">IV ${fmt(r.iv, 3)}</span>
        <span class="num">Δ ${fmt(r.delta, 2)}</span>
        <span class="num">OI ${fmtInt(r.open_interest)}</span>
      </div>
      <div class="row" style="margin-top:6px">
        <span class="meta">SCORE</span>
        <span class="score-pill">${fmt(r.score, 0)}</span>
      </div>
    `;
    card.addEventListener("click", () => selectOption(r.ticker));
    cards.appendChild(card);
  });
}

function renderSignals(signals) {
  const ul = $("#signals");
  ul.innerHTML = "";
  if (!signals || !signals.length) {
    ul.innerHTML = `<li class="meta">조건을 만족하는 신호가 아직 없습니다.</li>`;
    return;
  }
  signals.slice(0, 30).forEach((s) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="kind">${s.kind}</span>
      <span class="tk">${s.ticker}</span>
      <span class="meta">${s.note || ""}</span>
      <span class="when">score ${fmt(s.score, 0)}</span>
    `;
    li.addEventListener("click", () => selectOption(s.ticker));
    ul.appendChild(li);
  });
}

/* ---------- selection ---------- */
async function selectOption(ticker, row = null) {
  $$("#chainTable tbody tr").forEach((tr) => tr.classList.remove("selected"));
  if (row) row.classList.add("selected");
  $("#optTickerLabel").textContent = ticker;
  setStatus("옵션 차트 로딩…");
  try {
    const data = await api("/api/bars", { ticker, timespan: "day", days: 120 });
    fillChart(optChart, data.bars);
    setStatus("준비됨", "live");
  } catch (e) {
    setStatus(`옵션 차트 오류: ${e.message}`, "err");
  }
}

/* ---------- main scan ---------- */
async function scan(form) {
  const ul = form.ul.value.trim().toUpperCase();
  if (!ul) return;
  setStatus(`${ul} 스캔 중…`);
  try {
    const params = Object.fromEntries(
      new FormData(form).entries()
    );
    params.ul = ul;

    const [chain, ulBars, sentiment, uoa] = await Promise.all([
      api("/api/chain", params),
      api("/api/stock_bars", { ticker: ul, days: 120 }),
      api("/api/sentiment", { ul, max_strike_distance_pct: 15, days: 120 }),
      api("/api/uoa", { ul, min_vol_oi: 1.0, min_volume: 50 }),
    ]);

    renderSentiment(sentiment);
    renderUOA(uoa);
    renderChain(chain);
    renderCards(chain);
    renderSignals(chain.signals);

    $("#ulLabel").textContent = `${ul} · ${fmt(chain.underlying_price, 2)}`;
    fillChart(ulChart, ulBars.bars);

    // 첫 행 자동 선택해서 옵션 차트도 띄움
    if (chain.results[0]) await selectOption(chain.results[0].ticker);

    setStatus(`완료 · ${chain.count} 종목 (15m 지연)`, "live");
  } catch (e) {
    setStatus(`오류: ${e.message}`, "err");
    console.error(e);
  }
}

/* ---------- bootstrap ---------- */
window.addEventListener("DOMContentLoaded", () => {
  optChart = makeLineChart($("#optChart"), "옵션 종가", "#c9ff3b");
  ulChart = makeLineChart($("#ulChart"), "기초 종가", "#4cc2ff");

  $("#searchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    scan(e.target);
  });
});
