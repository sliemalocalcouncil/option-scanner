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

    const [chain, ulBars] = await Promise.all([
      api("/api/chain", params),
      api("/api/stock_bars", { ticker: ul, days: 120 }),
    ]);

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
