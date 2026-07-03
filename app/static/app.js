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
  chart: null,
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
  document.querySelector("#tradeStatus").textContent = status.message || `${status.trade_date} ${status.session}`;
}

function renderMeta(data) {
  const updatedAt = data.index?.updated_at ? new Date(data.index.updated_at).toLocaleString("zh-CN", { hour12: false }) : "-";
  document.querySelector("#dataMeta").textContent = `${data.timeframe_label} / 更新 ${updatedAt}`;
}

function renderRankingCards(selector, rankings, kind) {
  const container = document.querySelector(selector);
  container.innerHTML = rankings.map((block) => rankingCard(block, kind)).join("");
  container.querySelectorAll("tr[data-board-code]").forEach((row) => {
    row.addEventListener("click", () => loadBoardDetail(row.dataset.boardCode));
  });
}

function rankingCard(block, kind) {
  const rows = (block.items || []).map((item) => rankingRow(item, kind)).join("");
  return `
    <article class="rank-card">
      <h3>${block.title}</h3>
      <div class="mini-table">
        <table>
          <thead>${tableHead(kind)}</thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </article>
  `;
}

function tableHead(kind) {
  if (kind === "sector") {
    return `<tr><th>排名</th><th>板块</th><th>涨跌幅</th><th>成交额</th><th>资金量</th><th>龙头股</th></tr>`;
  }
  return `<tr><th>排名</th><th>股票</th><th>板块</th><th>价格</th><th>涨跌幅</th><th>成交额</th><th>资金量</th></tr>`;
}

function rankingRow(item, kind) {
  if (kind === "sector") {
    return `
      <tr data-board-code="${item.board_code}">
        <td>${item.rank}</td>
        <td><span class="name">${item.board_name}</span><span class="sub">${item.board_code}</span></td>
        <td>${formatPercent(item.change_percent)}</td>
        <td>${formatLarge(item.amount)}</td>
        <td>${formatLarge(item.capital_flow)}</td>
        <td><span class="name">${item.leader_stock_name || "-"}</span><span class="sub">${item.leader_stock_code || ""}</span></td>
      </tr>`;
  }
  return `
    <tr data-board-code="${item.board_code}">
      <td>${item.rank}</td>
      <td><span class="name">${item.stock_name}</span><span class="sub">${item.stock_code}${item.is_leader ? " / 龙头" : ""}</span></td>
      <td><span class="name">${item.board_name}</span><span class="sub">${item.board_code}</span></td>
      <td>${item.current_price ? Number(item.current_price).toFixed(2) : "-"}</td>
      <td>${formatPercent(item.change_percent)}</td>
      <td>${formatLarge(item.amount)}</td>
      <td>${formatLarge(item.capital_flow)}</td>
    </tr>`;
}

function renderTurnoverChart() {
  const block = state.boardRankings.find((item) => item.key === "sector_turnover") || state.boardRankings[0];
  const el = document.querySelector("#turnoverChart");
  if (!block || !window.echarts) {
    el.textContent = "图表资源未加载，排行榜数据仍可查看。";
    return;
  }
  if (!state.chart) {
    state.chart = echarts.init(el);
    window.addEventListener("resize", () => state.chart.resize());
  }
  const items = [...block.items].reverse();
  state.chart.setOption({
    animation: false,
    grid: { left: 96, right: 28, top: 18, bottom: 24 },
    xAxis: { type: "value", axisLabel: { formatter: (value) => formatLarge(value) } },
    yAxis: { type: "category", data: items.map((item) => item.board_name) },
    tooltip: { trigger: "axis", valueFormatter: (value) => formatLarge(value) },
    series: [{ type: "bar", data: items.map((item) => item.amount), itemStyle: { color: "#1167b1" } }],
  });
}

async function loadDashboard() {
  renderTabs();
  const response = await fetch(`/api/dashboard?timeframe=${state.timeframe}&limit=10`);
  if (!response.ok) throw new Error(`dashboard request failed: ${response.status}`);
  const data = await response.json();
  state.boardRankings = data.board_rankings;
  state.leaderRankings = data.leader_rankings;
  renderIndex(data.index);
  renderStatus(data.trading_status);
  renderMeta(data);
  renderRankingCards("#boardRankings", state.boardRankings, "sector");
  renderRankingCards("#leaderRankings", state.leaderRankings, "stock");
  renderTurnoverChart();
  const firstBoard = data.board_rankings?.[0]?.items?.[0]?.board_code;
  if (firstBoard) await loadBoardDetail(firstBoard);
}

async function loadBoardDetail(boardCode) {
  state.selectedBoardCode = boardCode;
  const response = await fetch(`/api/boards/${boardCode}?timeframe=${state.timeframe}&limit=10`);
  if (!response.ok) return;
  const data = await response.json();
  state.stockRankings = data.stock_rankings;
  document.querySelector("#detailTitle").textContent = `${data.board.name} 板块详情`;
  document.querySelector("#detailMeta").textContent = `${formatPercent(data.board.change_percent).replace(/<[^>]*>/g, "")} / ${formatLarge(data.board.amount)}`;
  renderRankingCards("#stockRankings", state.stockRankings, "stock");
}

loadDashboard().catch((error) => {
  document.querySelector("#tradeStatus").textContent = error.message;
});
