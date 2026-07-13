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

const metricLabels = {
  change: "涨幅",
  turnover: "成交额",
  volume: "成交量",
  fund: "资金量",
};

const metricBlockKeys = {
  change: "sector_change",
  turnover: "sector_turnover",
  volume: "sector_volume",
  fund: "sector_fund",
};

const stockBlockKeys = {
  change: "stock_change",
  turnover: "stock_turnover",
  volume: "stock_volume",
  fund: "stock_fund",
};

let state = {
  timeframe: "realtime",
  liveMetric: "change",
  stockMetric: "change",
  selectedBoardCode: null,
  selectedBoardName: "",
  boardBlocks: [],
  stockBlocks: [],
  dailyOptions: [],
  weeklyOptions: [],
  dailyDate: null,
  weeklyRange: null,
  reportPeriod: "3d",
  dataSource: "unknown",
  fundAvailable: false,
  refreshTimer: null,
  loading: false,
  lastTradingStatus: null,
  requestSeq: 0,
};

const moneyFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const ACTIVE_REFRESH_MS = 60 * 1000;
const BREAK_REFRESH_MS = 5 * 60 * 1000;

function formatLarge(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const number = Number(value);
  const abs = Math.abs(number);
  if (abs >= 100000000) return `${moneyFormatter.format(number / 100000000)}亿`;
  if (abs >= 10000) return `${moneyFormatter.format(number / 10000)}万`;
  return moneyFormatter.format(number);
}

function formatFund(value) {
  if (!state.fundAvailable) return "-";
  return formatLarge(value);
}

function formatPrice(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(2);
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const number = Number(value);
  const cls = number >= 0 ? "up" : "down";
  return `<span class="${cls}">${number.toFixed(2)}%</span>`;
}

function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

function renderTabs() {
  const container = document.querySelector("#timeframeTabs");
  container.innerHTML = timeframes
    .map(([key, label]) => `<button class="${key === state.timeframe ? "active" : ""}" data-timeframe="${key}">${label}</button>`)
    .join("");
  container.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.timeframe = button.dataset.timeframe;
      refreshDashboard({ force: true });
    });
  });
}

function renderIndex(index) {
  document.querySelector("#indexPanel").innerHTML = [
    ["指数名称", `${escapeText(index.name)}<span class="sub">${escapeText(index.code)}</span>`],
    ["当前点位", formatPrice(index.current)],
    ["涨跌点数", `<span class="${index.change >= 0 ? "up" : "down"}">${formatPrice(index.change)}</span>`],
    ["涨跌幅", formatPercent(index.change_percent)],
    ["成交量", formatLarge(index.volume)],
    ["成交额", formatLarge(index.amount)],
    ["更新时间", index.updated_at ? new Date(index.updated_at).toLocaleTimeString("zh-CN", { hour12: false }) : "-"],
    ["交易状态", escapeText(index.trading_status.session)],
  ]
    .map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function renderStatus(status) {
  document.querySelector("#tradeStatus").textContent = status.message || `${status.trade_date} ${status.session}`;
}

function renderMeta(data) {
  const updatedAt = data.index?.updated_at ? new Date(data.index.updated_at).toLocaleString("zh-CN", { hour12: false }) : "-";
  const source = data.index?.data_source || data.data_source || "unknown";
  document.querySelector("#dataMeta").textContent = `${data.timeframe_label} / 更新 ${updatedAt} / ${source} / ${refreshLabel(data.trading_status)}`;
}

function selectedBoardItems() {
  const block = state.boardBlocks.find((item) => item.key === metricBlockKeys[state.liveMetric]) || state.boardBlocks[0];
  return block?.items || [];
}

function selectedStockItems() {
  const block = state.stockBlocks.find((item) => item.key === stockBlockKeys[state.stockMetric]) || state.stockBlocks[0];
  return block?.items || [];
}

function ensureSelectedBoard() {
  const rows = selectedBoardItems();
  if (!rows.length) {
    state.selectedBoardCode = null;
    state.selectedBoardName = "";
    return null;
  }
  const current = rows.find((item) => item.board_code === state.selectedBoardCode);
  if (current) {
    state.selectedBoardName = current.board_name || state.selectedBoardName;
    return current;
  }
  const fallback = rows[0];
  state.selectedBoardCode = fallback.board_code;
  state.selectedBoardName = fallback.board_name;
  return fallback;
}

function renderBoards() {
  const rows = selectedBoardItems();
  const sourceNote = state.liveMetric === "fund" && !state.fundAvailable ? " / 当前数据源无资金流字段" : "";
  document.querySelector("#boardMeta").textContent = `按${metricLabels[state.liveMetric]}降序 / ${rows.length} 个板块${sourceNote}`;
  document.querySelector("#boardRows").innerHTML = rows.length
    ? rows.map(boardRow).join("")
    : `<tr><td colspan="7" class="empty">当前没有可展示的板块数据</td></tr>`;
  document.querySelectorAll("#boardRows tr[data-board-code]").forEach((row) => {
    row.addEventListener("click", () => {
      loadBoardDetail(row.dataset.boardCode, row.dataset.boardName).catch(renderError);
    });
  });
}

function boardRow(item) {
  const active = item.board_code === state.selectedBoardCode ? "active-row" : "";
  return `
    <tr class="${active}" data-board-code="${escapeText(item.board_code)}" data-board-name="${escapeText(item.board_name)}">
      <td>${item.rank}</td>
      <td><span class="name">${escapeText(item.board_name)}</span><span class="sub">${escapeText(item.board_code)}</span></td>
      <td>${formatPercent(item.change_percent)}</td>
      <td>${formatLarge(item.volume)}</td>
      <td>${formatLarge(item.amount)}</td>
      <td>${formatFund(item.capital_flow)}</td>
      <td><span class="name">${escapeText(item.leader_stock_name || "-")}</span><span class="sub">${escapeText(item.leader_stock_code || "")}</span></td>
    </tr>`;
}

function renderStocks() {
  const rows = selectedStockItems();
  const title = state.selectedBoardName ? `${state.selectedBoardName} 个股` : "板块个股";
  document.querySelector("#stockTitle").textContent = title;
  const sourceNote = state.stockMetric === "fund" && !state.fundAvailable ? " / 当前数据源无资金流字段" : "";
  document.querySelector("#stockMeta").textContent = rows.length
    ? `按${metricLabels[state.stockMetric]}降序 / ${rows.length} 只个股${sourceNote}`
    : "当前板块没有可展示的个股数据";
  document.querySelector("#stockRows").innerHTML = rows.length
    ? rows.map(stockRow).join("")
    : `<tr><td colspan="7" class="empty">点击左侧板块查看个股</td></tr>`;
}

function stockRow(item) {
  return `
    <tr>
      <td>${item.rank}</td>
      <td><span class="name">${escapeText(item.stock_name)}</span><span class="sub">${escapeText(item.stock_code)}${item.is_leader ? " / 龙头" : ""}</span></td>
      <td>${formatPrice(item.current_price)}</td>
      <td>${formatPercent(item.change_percent)}</td>
      <td>${formatLarge(item.volume)}</td>
      <td>${formatLarge(item.amount)}</td>
      <td>${formatFund(item.capital_flow)}</td>
    </tr>`;
}

function renderDailyOptions() {
  const select = document.querySelector("#dailyDateSelect");
  select.innerHTML = state.dailyOptions.length
    ? state.dailyOptions.map((item) => `<option value="${escapeText(item.trade_date)}">${escapeText(item.trade_date)}</option>`).join("")
    : `<option value="">暂无日期</option>`;
  const values = new Set(state.dailyOptions.map((item) => item.trade_date));
  if (state.dailyOptions.length && !values.has(state.dailyDate)) state.dailyDate = state.dailyOptions[0].trade_date;
  if (!state.dailyOptions.length) state.dailyDate = null;
  select.value = state.dailyDate || "";
}

function renderWeeklyOptions() {
  const select = document.querySelector("#weeklyDateSelect");
  select.innerHTML = state.weeklyOptions.length
    ? state.weeklyOptions
        .map((item) => `<option value="${escapeText(item.week_start)}|${escapeText(item.week_end)}">${escapeText(item.label)}</option>`)
        .join("")
    : `<option value="">暂无周区间</option>`;
  const values = new Set(state.weeklyOptions.map((item) => `${item.week_start}|${item.week_end}`));
  const current = state.weeklyRange ? `${state.weeklyRange.weekStart}|${state.weeklyRange.weekEnd}` : "";
  if (state.weeklyOptions.length && !values.has(current)) {
    state.weeklyRange = { weekStart: state.weeklyOptions[0].week_start, weekEnd: state.weeklyOptions[0].week_end };
  }
  if (!state.weeklyOptions.length) state.weeklyRange = null;
  select.value = state.weeklyRange ? `${state.weeklyRange.weekStart}|${state.weeklyRange.weekEnd}` : "";
}

function renderHistoryRows(selector, items) {
  document.querySelector(selector).innerHTML = items.length
    ? items.map(historyRow).join("")
    : `<tr><td colspan="5" class="empty">暂无历史聚合数据</td></tr>`;
}

function renderSummaryReport(data) {
  const items = data.items || [];
  renderSummaryPeriodTabs();
  const usedDays = data.expected_days ? `${data.days}/${data.expected_days}` : `${data.days}`;
  const meta = data.days
    ? `${data.period_label || "报表"} / ${data.date_start || "-"} ~ ${data.date_end || "-"} / 完整交易日 ${usedDays} / ${qualityLabel(data.data_quality)} / ${data.metric_note || ""}`
    : data.metric_note || "暂无报表数据";
  document.querySelector("#summaryReportMeta").textContent = meta;
  document.querySelector("#summaryReportRows").innerHTML = items.length
    ? items.map(summaryReportCard).join("")
    : `<div class="report-empty">暂无交易强度报表</div>`;
}

function summaryReportCard(card) {
  const item = card.item || {};
  const metricValue = item[card.metric] ?? item.amount;
  const missingDays = Number(item.missing_trading_days || 0);
  const quality = item.data_quality || "missing";
  const qualityText = missingDays > 0 ? `${qualityLabel(quality)} / 缺 ${missingDays} 天` : qualityLabel(quality);
  return `
    <article class="report-card">
      <div class="report-title">
        <span>${escapeText(card.title)}</span>
        <small>${escapeText(card.period_label || "-")}</small>
      </div>
      <strong class="report-value">${formatLarge(metricValue)}</strong>
      <div class="report-target">
        <span class="name">${escapeText(item.target_name || "-")}</span>
        <span class="sub">${escapeText(item.target_code || "")}</span>
      </div>
      <div class="report-foot">
        <span>${escapeText(card.metric_label || metricLabels[card.metric] || card.metric)}</span>
        <span class="quality ${escapeText(quality)}">${escapeText(qualityText)}</span>
      </div>
    </article>`;
}

function renderSummaryPeriodTabs() {
  document.querySelectorAll("#summaryPeriodTabs button[data-report-period]").forEach((button) => {
    button.classList.toggle("active", button.dataset.reportPeriod === state.reportPeriod);
  });
}

function historyRow(item) {
  return `
    <tr>
      <td>${item.rank}</td>
      <td><span class="name">${escapeText(item.target_name)}</span><span class="sub">${escapeText(item.target_code)}</span></td>
      <td>${formatPercent(item.change_percent)}</td>
      <td>${formatLarge(item.turnover)}</td>
      <td><span class="quality ${escapeText(item.data_quality)}">${qualityLabel(item.data_quality)}</span></td>
    </tr>`;
}

function renderCompare(data) {
  const rows = data.items || [];
  document.querySelector("#compareTitle").textContent = state.selectedBoardName ? `${state.selectedBoardName} 3 日成交对比` : "3 日成交对比";
  document.querySelector("#compareMeta").textContent = rows.length
    ? `${data.trade_date || "-"} 起最近 ${rows.length} 个交易日`
    : "没有足够的历史聚合数据";
  document.querySelector("#compareRows").innerHTML = rows.length
    ? rows.map(compareRow).join("")
    : `<tr><td colspan="9" class="empty">暂无对比数据</td></tr>`;
}

function compareRow(item) {
  return `
    <tr>
      <td>${escapeText(item.trade_date)}</td>
      <td><span class="name">${escapeText(item.target_name)}</span><span class="sub">${escapeText(item.target_code)}</span></td>
      <td>${formatPercent(item.change_percent)}</td>
      <td>${formatLarge(item.volume)}</td>
      <td>${formatPercent(item.volume_change_percent)}</td>
      <td>${formatLarge(item.turnover)}</td>
      <td>${formatPercent(item.turnover_change_percent)}</td>
      <td>${formatLarge(item.fund_amount)}</td>
      <td>${formatPercent(item.fund_change_percent)}</td>
    </tr>`;
}

function qualityLabel(value) {
  return {
    live: "实时",
    backfilled: "回填",
    partial: "部分",
    missing: "缺失",
  }[value] || value || "-";
}

function updateFundAvailability(data) {
  const blocks = [...(data.board_rankings || []), ...(data.leader_rankings || [])];
  const fundBlocks = blocks.filter((block) => block.metric === "capital_flow");
  state.fundAvailable = fundBlocks.some((block) => block.metric_available !== false);
}

function refreshLabel(status) {
  if (!status?.is_trade_day) return "非交易日，回到页面时刷新";
  if (["morning_trading", "afternoon_trading", "closing_trading"].includes(status.session)) return "交易中自动刷新";
  if (status.session === "lunch_break") return "午休低频刷新";
  return "已收盘，回到页面时刷新";
}

function refreshDelay(status) {
  if (!status?.is_trade_day) return null;
  if (["morning_trading", "afternoon_trading", "closing_trading"].includes(status.session)) return ACTIVE_REFRESH_MS;
  if (status.session === "lunch_break") return BREAK_REFRESH_MS;
  return null;
}

function scheduleNextRefresh(status) {
  if (state.refreshTimer) {
    window.clearTimeout(state.refreshTimer);
    state.refreshTimer = null;
  }
  const delay = refreshDelay(status);
  if (!delay || document.hidden) return;
  state.refreshTimer = window.setTimeout(() => refreshDashboard(), delay);
}

function renderLoadingState(label = "加载中") {
  document.querySelector("#dataMeta").textContent = label;
  document.querySelector("#boardRows").innerHTML = `<tr><td colspan="7" class="empty">${label}</td></tr>`;
  document.querySelector("#stockRows").innerHTML = `<tr><td colspan="7" class="empty">${label}</td></tr>`;
  document.querySelector("#summaryReportRows").innerHTML = `<div class="report-empty">${label}</div>`;
}

function renderError(error) {
  document.querySelector("#tradeStatus").textContent = `行情服务器繁忙：${error.message}`;
  document.querySelector("#dataMeta").textContent = `数据不可用：${error.message}`;
  document.querySelector("#boardRows").innerHTML = `<tr><td colspan="7" class="empty">数据缺失或上游服务繁忙</td></tr>`;
  document.querySelector("#stockRows").innerHTML = `<tr><td colspan="7" class="empty">数据缺失或上游服务繁忙</td></tr>`;
  document.querySelector("#summaryReportRows").innerHTML = `<div class="report-empty">报表数据暂不可用</div>`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${detail.slice(0, 120)}`);
  }
  return response.json();
}

async function refreshDashboard(options = {}) {
  if (state.loading && !options.force) return;
  const seq = ++state.requestSeq;
  state.loading = true;
  renderTabs();
  renderLoadingState(`${timeframeLabel(state.timeframe)} 加载中`);
  try {
    const data = await fetchJson(`/api/dashboard?timeframe=${encodeURIComponent(state.timeframe)}&limit=50`);
    if (seq !== state.requestSeq) return;
    state.boardBlocks = data.board_rankings || [];
    state.lastTradingStatus = data.trading_status;
    state.dataSource = data.data_source || "unknown";
    updateFundAvailability(data);
    renderIndex(data.index);
    renderStatus(data.trading_status);
    renderMeta(data);
    ensureSelectedBoard();
    renderBoards();
    if (state.selectedBoardCode) {
      await loadBoardDetail(state.selectedBoardCode, state.selectedBoardName, seq);
    } else {
      renderStocks();
    }
    await refreshHistory(seq);
  } catch (error) {
    if (seq === state.requestSeq) renderError(error);
  } finally {
    if (seq !== state.requestSeq) return;
    state.loading = false;
    scheduleNextRefresh(state.lastTradingStatus);
  }
}

async function loadBoardDetail(boardCode, boardName = "", seq = state.requestSeq) {
  state.selectedBoardCode = boardCode;
  state.selectedBoardName = boardName || state.selectedBoardName;
  renderBoards();
  const data = await fetchJson(`/api/boards/${encodeURIComponent(boardCode)}?timeframe=${encodeURIComponent(state.timeframe)}&limit=50`);
  if (seq !== state.requestSeq) return;
  state.stockBlocks = data.stock_rankings || [];
  state.selectedBoardName = data.board?.name || state.selectedBoardName;
  renderStocks();
  await refreshCompare(seq);
}

async function refreshHistory(seq = state.requestSeq) {
  const [summary, days, weeks] = await Promise.all([
    fetchJson(`/api/report/summary?target_type=sector&period=${encodeURIComponent(state.reportPeriod)}`),
    fetchJson("/api/history/days?limit=7"),
    fetchJson("/api/history/weeks?limit=4"),
  ]);
  if (seq !== state.requestSeq) return;
  renderSummaryReport(summary);
  state.dailyOptions = days.items || [];
  state.weeklyOptions = weeks.items || [];
  renderDailyOptions();
  renderWeeklyOptions();
  await Promise.all([refreshDailyRank(seq), refreshWeeklyRank(seq), refreshCompare(seq)]);
}

async function refreshSummaryReport(seq = state.requestSeq) {
  renderSummaryPeriodTabs();
  const data = await fetchJson(`/api/report/summary?target_type=sector&period=${encodeURIComponent(state.reportPeriod)}`);
  if (seq !== state.requestSeq) return;
  renderSummaryReport(data);
}

async function refreshDailyRank(seq = state.requestSeq) {
  const dateQuery = state.dailyDate ? `&trade_date=${encodeURIComponent(state.dailyDate)}` : "";
  const data = await fetchJson(`/api/history/daily-rank?target_type=sector&metric=change&limit=20${dateQuery}`);
  if (seq !== state.requestSeq) return;
  document.querySelector("#dailyMeta").textContent = `${data.trade_date || "-"} / 按涨幅降序 / ${qualityLabel(data.data_quality)}`;
  renderHistoryRows("#dailyRows", data.items || []);
}

async function refreshWeeklyRank(seq = state.requestSeq) {
  const rangeQuery = state.weeklyRange
    ? `&week_start=${encodeURIComponent(state.weeklyRange.weekStart)}&week_end=${encodeURIComponent(state.weeklyRange.weekEnd)}`
    : "";
  const data = await fetchJson(`/api/history/weekly-rank?target_type=sector&metric=change&limit=20${rangeQuery}`);
  if (seq !== state.requestSeq) return;
  document.querySelector("#weeklyMeta").textContent = `${data.label || "-"} / 按涨幅降序 / ${qualityLabel(data.data_quality)}`;
  renderHistoryRows("#weeklyRows", data.items || []);
}

async function refreshCompare(seq = state.requestSeq) {
  if (!state.selectedBoardCode) {
    renderCompare({ items: [] });
    return;
  }
  const dateQuery = state.dailyDate ? `&trade_date=${encodeURIComponent(state.dailyDate)}` : "";
  const data = await fetchJson(`/api/history/compare?target_type=sector&target_code=${encodeURIComponent(state.selectedBoardCode)}&days=3${dateQuery}`);
  if (seq !== state.requestSeq) return;
  renderCompare(data);
}

function timeframeLabel(timeframe) {
  return timeframes.find(([key]) => key === timeframe)?.[1] || timeframe;
}

document.querySelector("#liveMetricSelect").addEventListener("change", (event) => {
  state.liveMetric = event.target.value;
  const selected = ensureSelectedBoard();
  if (selected) {
    loadBoardDetail(selected.board_code, selected.board_name).catch(renderError);
  } else {
    renderBoards();
  }
});

document.querySelector("#stockMetricSelect").addEventListener("change", (event) => {
  state.stockMetric = event.target.value;
  renderStocks();
});

document.querySelector("#dailyDateSelect").addEventListener("change", async (event) => {
  state.dailyDate = event.target.value || null;
  const seq = state.requestSeq;
  await Promise.all([refreshDailyRank(seq), refreshCompare(seq)]);
});

document.querySelector("#weeklyDateSelect").addEventListener("change", async (event) => {
  const [weekStart, weekEnd] = event.target.value.split("|");
  state.weeklyRange = weekStart && weekEnd ? { weekStart, weekEnd } : null;
  await refreshWeeklyRank(state.requestSeq);
});

document.querySelectorAll("#summaryPeriodTabs button[data-report-period]").forEach((button) => {
  button.addEventListener("click", async () => {
    state.reportPeriod = button.dataset.reportPeriod || "3d";
    await refreshSummaryReport(state.requestSeq).catch(renderError);
  });
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (state.refreshTimer) {
      window.clearTimeout(state.refreshTimer);
      state.refreshTimer = null;
    }
    return;
  }
  refreshDashboard({ force: true });
});

window.addEventListener("focus", () => refreshDashboard({ force: true }));

renderSummaryPeriodTabs();
refreshDashboard({ force: true });
