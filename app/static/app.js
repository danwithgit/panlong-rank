const timeframes = [
  ["realtime", "实时榜"],
  ["hour_0930_1030", "09:30-10:30"],
  ["hour_1030_1130", "10:30-11:30"],
  ["hour_1300_1400", "13:00-14:00"],
  ["hour_1400_1500", "14:00-15:00"],
  ["morning", "上午榜"],
  ["afternoon", "下午榜"],
  ["closing", "尾盘榜"],
  ["daily", "当日总榜"],
  ["last_trade_day", "最近交易日"],
];

let state = {
  timeframe: "realtime",
  boardRankings: [],
  leaderRankings: [],
  stockRankings: [],
  selectedBoardCode: null,
};

const moneyFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

function formatLarge(value) {
  if (value === null || value === undefined) return "-";
  const abs = Math.abs(value);
  if (abs >= 100000000) return `${moneyFormatter.format(value / 100000000)}亿`;
  if (abs >= 10000) return `${moneyFormatter.format(value / 10000)}万`;
  return moneyFormatter.format(value);
}

function formatPercent(value) {
  const text = `${Number(value || 0).toFixed(2)}%`;
  const cls = value >= 0 ? "up" : "down";
  return `<span class="${cls}">${text}</span>`;
}

function renderTabs() {
  const container = document.querySelector("#timeframeTabs");
  container.innerHTML = timeframes
    .map(([key, label]) => `<button class="${key === state.timeframe ? "active" : ""}" data-timeframe="${key}">${label}</button>`)
    .join("");
  container.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.timeframe = button.dataset.timeframe;
      loadDashboard();
    });
  });
}

function renderIndex(index) {
  document.querySelector("#indexPanel").innerHTML = [
    ["指数名称", `${index.name}<span class="sub">${index.code}</span>`],
    ["当前点位", Number(index.current).toFixed(2)],
    ["涨跌点数", `<span class="${index.change >= 0 ? "up" : "down"}">${Number(index.change).toFixed(2)}</span>`],
    ["涨跌幅", formatPercent(index.change_percent)],
    ["成交量", formatLarge(index.volume)],
    ["成交额", formatLarge(index.amount)],
    ["更新时间", new Date(index.updated_at).toLocaleTimeString("zh-CN", { hour12: false })],
    ["交易状态", index.trading_status.session],
  ]
    .map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function renderStatus(status) {
  document.querySelector("#tradeStatus").textContent =
    status.message || `${status.trade_date} ${status.session}`;
}

function fillSelect(selector, rankings, selectedKey) {
  const select = document.querySelector(selector);
  select.innerHTML = rankings.map((block) => `<option value="${block.key}">${block.title}</option>`).join("");
  if (selectedKey && rankings.some((block) => block.key === selectedKey)) {
    select.value = selectedKey;
  }
}

function currentBlock(rankings, selector) {
  const select = document.querySelector(selector);
  return rankings.find((block) => block.key === select.value) || rankings[0];
}

function renderBoardTable() {
  const block = currentBlock(state.boardRankings, "#boardRankingSelect");
  const body = document.querySelector("#boardRankingBody");
  body.innerHTML = (block?.items || [])
    .map(
      (item) => `
        <tr data-board-code="${item.board_code}">
          <td>${item.rank}</td>
          <td><span class="name">${item.board_name}</span><span class="sub">${item.board_code}</span></td>
          <td>${formatPercent(item.change_percent)}</td>
          <td>${formatLarge(item.volume)}</td>
          <td>${formatLarge(item.amount)}</td>
          <td>${formatLarge(item.capital_flow)}</td>
          <td><span class="name">${item.leader_stock_name || "-"}</span><span class="sub">${item.leader_stock_code || ""}</span></td>
        </tr>`
    )
    .join("");
  body.querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => loadBoardDetail(row.dataset.boardCode));
  });
}

function renderLeaderTable() {
  const block = currentBlock(state.leaderRankings, "#leaderRankingSelect");
  document.querySelector("#leaderRankingBody").innerHTML = (block?.items || [])
    .map(
      (item) => `
        <tr data-board-code="${item.board_code}">
          <td>${item.rank}</td>
          <td><span class="name">${item.board_name}</span><span class="sub">${item.board_code}</span></td>
          <td><span class="name">${item.stock_name}</span><span class="sub">${item.stock_code}</span></td>
          <td>${item.current_price ? Number(item.current_price).toFixed(2) : "-"}</td>
          <td>${formatPercent(item.change_percent)}</td>
          <td>${formatLarge(item.amount)}</td>
          <td>${formatLarge(item.capital_flow)}</td>
        </tr>`
    )
    .join("");
}

function renderStockTable() {
  const block = currentBlock(state.stockRankings, "#stockRankingSelect");
  document.querySelector("#stockRankingBody").innerHTML = (block?.items || [])
    .map(
      (item) => `
        <tr>
          <td>${item.rank}</td>
          <td><span class="name">${item.stock_name}</span><span class="sub">${item.stock_code}</span></td>
          <td>${item.current_price ? Number(item.current_price).toFixed(2) : "-"}</td>
          <td>${formatPercent(item.change_percent)}</td>
          <td>${formatLarge(item.volume)}</td>
          <td>${formatLarge(item.amount)}</td>
          <td>${formatLarge(item.capital_flow)}</td>
          <td>${item.is_leader ? '<span class="leader-tag">是</span>' : "-"}</td>
        </tr>`
    )
    .join("");
}

async function loadDashboard() {
  renderTabs();
  const response = await fetch(`/api/dashboard?timeframe=${state.timeframe}&limit=10`);
  const data = await response.json();
  state.boardRankings = data.board_rankings;
  state.leaderRankings = data.leader_rankings;
  renderIndex(data.index);
  renderStatus(data.trading_status);
  fillSelect("#boardRankingSelect", state.boardRankings);
  fillSelect("#leaderRankingSelect", state.leaderRankings);
  renderBoardTable();
  renderLeaderTable();
  const firstBoard = data.board_rankings?.[0]?.items?.[0]?.board_code;
  if (firstBoard) await loadBoardDetail(firstBoard);
}

async function loadBoardDetail(boardCode) {
  state.selectedBoardCode = boardCode;
  const response = await fetch(`/api/boards/${boardCode}?timeframe=${state.timeframe}&limit=10`);
  const data = await response.json();
  state.stockRankings = data.stock_rankings;
  document.querySelector("#detailTitle").textContent = `${data.board.name} 板块详情`;
  fillSelect("#stockRankingSelect", state.stockRankings);
  renderStockTable();
}

document.querySelector("#boardRankingSelect").addEventListener("change", renderBoardTable);
document.querySelector("#leaderRankingSelect").addEventListener("change", renderLeaderTable);
document.querySelector("#stockRankingSelect").addEventListener("change", renderStockTable);

loadDashboard();
