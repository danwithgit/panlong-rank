# Panlong Rank AI 分析模块未来开发规划

更新时间：2026-07-13

## 1. 结论

当前系统可以支撑第一版 AI 分析，但只能支撑“行情技术面 + 成交活跃度 + 板块相对强弱”的分析，不能直接支撑完整的“新闻热度 + 市场情绪 + 未来一周预测”。

原因：

- 已具备：指数、板块、个股快照，日聚合、周聚合，最近 3/5 个完整板块交易日累计报表，交易日调度，任务日志，数据质量状态。
- 不足：没有新闻/公告/热榜采集，没有舆情情绪表，没有稳定真实资金流字段，没有足够完整的个股 30 日历史技术指标基础。
- 可做：先做“可解释评分 + LLM 简短报告”，让 AI 基于结构化因子总结，不让 AI 凭空预测。
- 不建议：一上来让 AI 自由判断“买入/卖出”。应输出“热度评分、趋势评分、风险评分、恐慌情绪、观察理由”，而不是投资建议。

推荐第一阶段目标：

1. 每个交易日开盘后和尾盘后，对 Top 板块生成 AI 评分。
2. 每个入选板块只分析前 10 只个股。
3. 首页展示板块 AI 评分；点击板块后，右侧个股表增加 AI 评分入口和摘要。
4. 所有 AI 报告必须显示分析时间、数据窗口、数据质量、模型版本。

## 2. 当前数据能力评估

### 2.1 已经能用的数据

当前数据库已有这些核心表：

- `index_snapshots`：上证指数实时快照。
- `sector_snapshots`：板块实时快照。
- `stock_snapshots`：个股实时快照，含板块归属。
- `daily_aggregates`：指数、板块、个股日聚合。
- `weekly_aggregates`：周聚合，含缺失交易日质量字段。
- `stock_sector_map`：个股与板块映射。
- `job_logs`：任务执行记录。

已经能稳定支持的分析：

- 板块涨跌幅排名。
- 板块成交量、成交额排名。
- 近 3/近 5 个完整板块交易日累计成交量、成交额。
- 板块内个股涨幅、成交量、成交额排名。
- 个股短期相对强弱。
- 简单趋势判断，例如连续上涨、放量、缩量、突破近期高点、跌破近期低点。

### 2.2 当前不能直接支撑的数据

当前不具备：

- 新闻标题、新闻来源、发布时间、点击/热度排名。
- 财经热榜、搜索热度、社交讨论热度。
- 新闻与板块/个股的关联关系。
- 新闻情绪、政策情绪、风险事件标签。
- 真实主力资金流、超大单/大单净流入。
- 完整 30 日个股历史日线覆盖。
- 统一的技术指标表，例如 MA、MACD、RSI、ATR、布林带。

因此，未来一周评分如果只依赖当前数据，可靠性会偏弱。当前数据更适合做“短线热度和交易强度评分”，不适合做“基本面预测”。

## 3. AI 模块总体原则

### 3.1 不让 AI 直接决定分数

建议分数由规则和因子计算得出，AI 只负责解释。

正确方式：

```text
原始数据 -> 因子计算 -> 规则评分 -> AI 生成摘要 -> 存库 -> 前端展示
```

不建议：

```text
原始数据 -> 直接丢给 AI -> AI 自己打分
```

原因是后者不可复现，模型版本变化会导致分数漂移，也不方便排查。

### 3.2 所有报告必须可追溯

每条 AI 分析记录要保存：

- 分析对象：板块或个股。
- 数据窗口：例如近 3 交易日、近 5 交易日、开盘后、尾盘后。
- 输入因子 JSON。
- 规则评分 JSON。
- AI prompt 版本。
- AI 模型名称。
- AI 输出内容。
- 生成时间。
- 数据质量状态。

### 3.3 输出必须有免责声明

页面和 API 都应避免使用“推荐买入”“必涨”等措辞。

建议统一口径：

```text
AI 分析仅基于公开行情与新闻数据生成，用于观察市场热度和风险，不构成投资建议。
```

## 4. 数据补全方案

### 4.1 新闻与热度数据

需要新增新闻采集层，不能直接混在行情 provider 里。

建议新增目录：

```text
app/services/news_provider.py
app/services/news_collector.py
app/services/news_linker.py
app/services/sentiment.py
```

第一阶段可采集：

- 财经新闻标题。
- 新闻发布时间。
- 新闻来源。
- 新闻 URL。
- 新闻热榜排名，如果来源提供。
- 新闻摘要，如果来源允许。
- 关联关键词。

候选来源按优先级：

1. 正式授权新闻/舆情源：最稳定，适合长期部署。
2. 官方/公开 RSS 或公开栏目页：稳定性中等，需遵守站点规则。
3. AKShare 或类似聚合接口：开发快，但字段和接口稳定性需要持续检查。
4. 直接爬财经网站热榜：最后选择，必须严格限频、缓存、去重。

新闻采集原则：

- 只采标题、来源、发布时间、URL、热榜排名，不抓全文，除非有授权。
- 同一 URL 或相同标题要去重。
- 设置最小采集间隔，例如 10-30 分钟。
- 每个来源单独失败，不影响其他来源。
- 失败只记录日志，不阻塞行情采集。

### 4.2 板块/个股关联

新闻要能映射到板块和个股。

第一版规则：

- 标题中出现股票名称或股票代码，关联到个股。
- 标题中出现板块关键词，关联到板块。
- 个股所属板块来自 `stock_sector_map`，个股新闻可向上归因到板块。

需要新增配置表或文件：

```text
sector_keywords
stock_aliases
news_stopwords
```

例如：

```text
半导体 -> 电子器件、芯片、晶圆、光刻机、封测
新能源 -> 光伏、储能、锂电、风电
医药 -> 生物制药、创新药、医疗器械
```

### 4.3 技术指标数据

当前 `daily_aggregates` 有日线基础字段，但个股历史覆盖不完整。要做技术分析，至少需要：

- 每只入选股票最近 30 个交易日的 open/high/low/close/volume/turnover。
- 每个板块最近 30 个完整交易日数据。
- 数据质量必须区分 `live`、`backfilled`、`partial`、`missing`。

建议新增技术指标表：

```text
technical_indicators
```

字段建议：

```text
id
trade_date
target_type        # sector / stock / index
target_code
sector_code        # stock 时可填
ma5
ma10
ma20
volume_ma5
volume_ratio       # 当前成交量 / 5 日均量
turnover_ratio
rsi6
rsi14
macd_dif
macd_dea
macd_hist
atr14
recent_high_20
recent_low_20
support_price
resistance_price
trend_label        # uptrend / downtrend / range / breakout / breakdown
data_quality
created_at
updated_at
```

第一版可以先不做复杂指标，只做：

- MA5、MA10、MA20。
- 近 20 日最高价、最低价。
- 5 日成交量均值。
- 当前量比。
- 简单压力位：近 20 日高点。
- 简单支撑位：近 20 日低点。
- 趋势标签：多头、空头、震荡、突破、跌破。

## 5. 评分体系建议

### 5.1 板块评分

板块未来一周评分可以先定义为“未来一周关注热度评分”，不是涨跌预测。

总分 0-100。

建议拆分：

```text
sector_score =
  market_activity_score * 0.30
  + relative_strength_score * 0.25
  + breadth_score * 0.15
  + news_heat_score * 0.20
  + risk_adjustment_score * 0.10
```

字段含义：

- `market_activity_score`：成交量、成交额、近 3/5 交易日放量情况。
- `relative_strength_score`：板块涨幅相对上证指数、相对全市场板块排名。
- `breadth_score`：板块内上涨个股占比、前 10 个股强度。
- `news_heat_score`：新闻数量、热榜排名、正负面情绪。
- `risk_adjustment_score`：高位放量下跌、连续冲高回落、负面新闻、市场恐慌时降分。

没有新闻数据时：

- `news_heat_score` 标记为 `unavailable`。
- 总分可按已有因子重归一，但页面必须显示“新闻热度未接入”。

### 5.2 个股评分

每个板块只对前 10 只股票评分，避免成本爆炸。

入选规则：

- 当前选中板块内，按涨幅、成交额、成交量综合排序取前 10。
- 或直接取当前板块个股榜前 10。

总分 0-100。

建议拆分：

```text
stock_score =
  trend_score * 0.30
  + volume_score * 0.20
  + relative_strength_score * 0.20
  + sector_alignment_score * 0.15
  + risk_score * 0.15
```

字段含义：

- `trend_score`：MA5/MA10/MA20 排列、突破/跌破状态。
- `volume_score`：量比、成交额排名、是否放量。
- `relative_strength_score`：个股涨幅相对板块、相对上证指数。
- `sector_alignment_score`：是否与板块走势同向，是否板块龙头。
- `risk_score`：高位回落、放量下跌、连续大涨、波动过高。

AI 个股报告建议输出：

```text
评分：78
趋势：偏强
压力位：xx.xx
支撑位：xx.xx
量能：近 5 日放量
风险：短线涨幅较快，回撤风险上升
摘要：该股与板块走势一致，成交活跃度靠前，但需观察能否有效突破压力位。
```

### 5.3 恐慌情绪指标

建议新增一个市场级情绪分数 `fear_score`，0-100，越高表示越恐慌。

第一版可以不依赖新闻，先用行情计算：

- 上证指数跌幅。
- 下跌板块占比。
- 下跌个股占比。
- 跌幅超过 5% 个股数量。
- 放量下跌板块数量。
- 指数接近近期低点程度。

接入新闻后再加入：

- 负面新闻数量。
- 风险关键词数量，例如“监管、退市、暴雷、亏损、减持、处罚、制裁”。
- 热榜负面事件权重。

页面显示：

```text
市场恐慌情绪：低 / 中 / 高
恐慌分：32
主要原因：下跌个股占比升高，但指数仍在 20 日区间中位。
```

## 6. AI 任务调度

用户设想“开盘、尾盘做分析”是合理的。

建议任务：

```text
09:45 开盘分析
14:50 尾盘分析
15:10 收盘复盘
```

第一版先做：

- `09:45`：开盘后热度分析。
- `14:50`：尾盘分析。

调度约束：

- 只在交易日执行。
- 非交易日跳过。
- 每次只分析 Top N 板块，默认 10。
- 每个板块只分析前 10 个股。
- 分析前必须检查行情快照新鲜度。
- 如果行情数据质量不是 `live`，跳过 AI 分析或标记为 `partial`。
- AI 失败不能影响行情采集。

新增配置建议：

```text
AI_ANALYSIS_ENABLED=false
AI_PROVIDER=openai
AI_MODEL=
AI_SECTOR_LIMIT=10
AI_STOCK_LIMIT_PER_SECTOR=10
AI_RUN_OPEN_TIME=09:45
AI_RUN_TAIL_TIME=14:50
AI_CACHE_TTL_HOURS=8
AI_MAX_DAILY_CALLS=300
NEWS_COLLECT_ENABLED=false
NEWS_COLLECT_INTERVAL_SECONDS=900
```

## 7. 数据库设计建议

### 7.1 新闻表

```text
news_items
id
source
source_rank
title
summary
url
published_at
collected_at
raw_hash
sentiment_score
sentiment_label
importance_score
data_quality
```

### 7.2 新闻关联表

```text
news_links
id
news_id
target_type       # sector / stock / index / market
target_code
target_name
match_type        # exact_stock / keyword / manual / ai
confidence
```

### 7.3 技术指标表

见第 4.3 节。

### 7.4 AI 分析表

```text
ai_analysis_reports
id
analysis_date
analysis_time
analysis_session   # open / tail / close / manual
target_type        # market / sector / stock
target_code
target_name
sector_code
sector_name
score
score_breakdown_json
fear_score
trend_label
support_level
resistance_level
next_target_level
risk_level
summary
pros_json
cons_json
input_features_json
news_refs_json
model_name
prompt_version
data_quality
generated_at
expires_at
```

### 7.5 AI 任务日志

```text
ai_analysis_jobs
id
job_name
analysis_session
status
started_at
finished_at
target_count
token_usage_json
error_message
```

## 8. API 设计建议

### 8.1 板块 AI 榜

```text
GET /api/ai/sectors?session=tail&limit=10
```

返回：

```json
{
  "analysis_date": "2026-07-13",
  "analysis_session": "tail",
  "generated_at": "...",
  "items": [
    {
      "sector_code": "new_dzqj",
      "sector_name": "电子器件",
      "score": 82,
      "heat_score": 88,
      "trend_score": 74,
      "risk_level": "medium",
      "fear_score": 31,
      "summary": "成交活跃度维持高位，板块相对强势，但短线波动较大。"
    }
  ]
}
```

### 8.2 个股 AI 分析

```text
GET /api/ai/stocks?sector_code=new_dzqj&session=tail&limit=10
```

### 8.3 单个对象分析详情

```text
GET /api/ai/report?target_type=stock&target_code=600000&session=tail
```

### 8.4 手动触发分析

```text
POST /api/admin/ai/analyze?session=tail
```

必须要求 admin token。

## 9. 前端布局建议

当前首页已经有：

- 指数指标。
- 交易强度报表。
- 板块实时榜。
- 右侧板块个股列表。
- 历史榜和成交对比。

建议不要把 AI 信息全塞进现有表格，否则会很乱。

### 9.1 首页板块区

左侧板块榜增加列：

```text
AI分
风险
分析时间
```

点击板块后，右侧改为上下结构：

```text
右侧顶部：板块 AI 摘要
右侧下方：板块个股列表
```

板块 AI 摘要展示：

- 综合分。
- 热度分。
- 趋势。
- 恐慌情绪。
- 简短摘要。
- 利好因素 2-3 条。
- 风险因素 2-3 条。
- 分析时间。

### 9.2 个股列表

个股表增加：

```text
AI分
趋势
风险
```

点击个股后，不建议跳页，建议右侧或抽屉展示：

```text
个股 AI 分析抽屉
- 综合分
- 趋势标签
- 支撑位
- 压力位
- 下一个目标位
- 量能评价
- 简短报告
- 风险提示
- 输入数据质量
```

### 9.3 页面优先级

第一版 UI 推荐：

1. 板块表格左侧仍是主导航。
2. 右侧顶部显示选中板块 AI 摘要。
3. 右侧下方显示个股列表。
4. 点击个股后打开详情抽屉。

这样不破坏当前用户习惯，也方便后续扩展。

## 10. 开发阶段规划

### 阶段 1：规则评分，不接 AI

目标：先把评分体系跑通。

任务：

- 新增技术指标计算。
- 新增板块评分服务。
- 新增个股评分服务。
- 新增 `ai_analysis_reports` 表，但 summary 先用模板生成。
- 新增 `/api/ai/sectors` 和 `/api/ai/stocks`。
- 前端显示 AI 分数和模板摘要。

验收：

- 不调用大模型也能稳定生成分数。
- 分数可复现。
- 数据质量不足时明确显示 `partial` 或 `missing`。

### 阶段 2：接入新闻采集

目标：补市场热度和新闻情绪。

任务：

- 新增新闻 provider。
- 新增新闻表和关联表。
- 新增关键词关联规则。
- 新增新闻热度因子。
- 新增新闻情绪初版，可先用词典规则，不急着用 AI。

验收：

- 每条新闻可追溯来源。
- 每个板块能看到相关新闻数量和最近新闻。
- 新闻采集失败不影响行情系统。

### 阶段 3：接入 LLM 生成报告

目标：让 AI 解释分数，不直接决定分数。

任务：

- 新增 AI prompt 模板。
- 新增 AI client。
- 新增 token 和调用次数限制。
- 新增 AI 任务日志。
- 对 Top 板块和板块前 10 个股生成报告。

验收：

- 每次报告可追溯输入因子。
- 同一输入不会频繁重复调用 AI。
- AI 输出失败时页面仍显示规则分数。

### 阶段 4：优化前端交互

目标：让人看得懂。

任务：

- 板块右侧增加 AI 摘要。
- 个股增加 AI 分析抽屉。
- 增加恐慌情绪组件。
- 增加分析时间和数据质量提示。

验收：

- 用户能一眼看出当前热度最高板块。
- 用户能看到 AI 为什么给这个分。
- 用户能看到数据不足时的提示。

## 11. 可靠性与安全边界

必须遵守：

- AI 分析只读数据库，不直接触发第三方行情采集。
- 新闻采集限频，不能因为用户刷新页面而请求上游。
- AI 调用限频，不能因为用户点击而重复生成。
- 所有 AI 报告落库后展示，页面只读缓存结果。
- 上游新闻失败、AI 失败、行情失败必须分开记录。
- AI 输出不允许包含“保证上涨”“建议买入”等绝对化表述。

## 12. 当前不足清单

按优先级：

1. 个股 30 日历史覆盖不足，技术指标可靠性不够。
2. 新闻与热榜数据完全缺失。
3. 真实资金流字段不可用，目前不能做主力资金评分。
4. 板块历史回填多为 `partial`，不能直接参与长期趋势判断。
5. 没有 AI 分析表、prompt 版本、输入特征记录。
6. 没有前端 AI 展示区。

## 13. 推荐下一步

建议下一轮开发不要直接接大模型，先做阶段 1：

1. 增加技术指标计算表。
2. 增加规则评分服务。
3. 增加 AI 分析报告表，但先用模板摘要。
4. 首页展示板块评分。
5. 板块右侧展示前 10 个股评分。

这样做的好处：

- 不依赖新闻源也能先跑通完整链路。
- 分数可复现，方便调试。
- 后面接新闻和大模型时，只是新增因子和摘要能力，不会推翻架构。

## 14. 后续给 Codex 的实现提示

如果后续用 Codex 继续开发，优先读取：

```text
PROJECT_STATUS.md
dev.md
AI_DEVELOPMENT_PLAN.md
app/db/tables.py
app/services/aggregates.py
app/services/history_rankings.py
app/services/scheduler.py
app/static/index.html
app/static/app.js
app/static/style.css
```

第一阶段推荐提交拆分：

1. 数据库迁移：新增 `technical_indicators`、`ai_analysis_reports`、`ai_analysis_jobs`。
2. 服务层：新增 `technical_indicators.py`、`analysis_scoring.py`。
3. 调度层：新增开盘/尾盘评分任务。
4. API：新增 `/api/ai/sectors`、`/api/ai/stocks`。
5. 前端：板块 AI 摘要、个股 AI 分数和详情抽屉。
6. 测试：覆盖数据不足、评分排序、缓存复用、AI 失败降级。

不要在第一阶段直接做新闻爬虫和大模型调用，先把可复现的评分基础打稳。
