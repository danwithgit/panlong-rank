# Panlong Rank

上证指数、板块、板块内股票和龙头股排行榜 MVP。

当前版本提供：

- 上证指数摘要
- 板块成交额、成交量、资金量、涨幅和尾盘榜
- 板块详情内股票排行榜
- 龙头股成交量、成交额、资金量、涨幅和尾盘榜
- 实时榜、小时榜、上午榜、下午榜、尾盘榜、当日总榜、最近一个交易日榜
- 交易日/非交易日状态提示
- SQLite/PostgreSQL 快照存储
- 数据库快照差值计算区间榜单
- APScheduler 交易时间定时采集
- 内存 TTL 缓存，配置 Redis 后自动使用 Redis
- 采集任务日志
- 手动龙头股配置表和自动龙头股识别
- AKShare 可选数据源；Eastmoney 实时接口失败时自动降级到 AKShare Sina 真实数据源
- 正式模式下采集失败不回退样例数据

## 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后打开：

```text
http://127.0.0.1:8000
```

也可以使用：

```bash
bash start.sh
```

Docker 方式：

```bash
docker compose up --build
```

默认 compose 会启动 PostgreSQL、Redis 和应用。`DATA_PROVIDER` 默认设为 `auto`，使用 AKShare 采集真实数据；采集失败时不写入样例数据，API 返回 503。

数据库迁移可选执行：

```bash
python3 -m alembic upgrade head
```

本地开发默认启动时会自动建表；生产环境建议显式执行 Alembic 迁移。

## 配置

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `Panlong Rank` | 服务名称 |
| `DATA_PROVIDER` | `auto` | `auto`、`akshare`、`sample`；Docker 默认不要用 `sample` |
| `DATABASE_URL` | `sqlite:///./panlong_rank.sqlite3` | SQLAlchemy 数据库连接，生产可设 PostgreSQL |
| `REDIS_URL` | 空 | 设置后使用 Redis 缓存，否则使用进程内 TTL 缓存 |
| `TUSHARE_TOKEN` | 空 | 设置后可用 Tushare 交易日历 |
| `RANK_LIMIT` | `10` | 默认排行条数 |
| `CACHE_TTL_SECONDS` | `30` | API 排行缓存 TTL |
| `SCHEDULER_ENABLED` | `true` | 是否启动 APScheduler |
| `COLLECT_ON_STARTUP` | `true` | 启动时没有快照则采集一次 |
| `COLLECT_INTERVAL_SECONDS` | `120` | 交易时间采集间隔 |
| `MIN_COLLECT_INTERVAL_SECONDS` | `60` | 最小采集间隔，防止重复请求上游 |

`DATA_PROVIDER=auto` 时会尝试 AKShare。当前 provider 优先使用 AKShare Eastmoney 实时接口；若 `push2.eastmoney.com` 编号节点不可用，会自动降级到 AKShare Sina 真实行情接口：

- 上证指数：`stock_zh_index_spot_em` -> `stock_zh_index_spot_sina`
- 板块排行：`stock_board_industry_name_em` -> `stock_sector_spot`
- 板块成分股：`stock_board_industry_cons_em` -> `stock_sector_detail`

若全部真实数据源都不可用，采集任务失败并记录 `job_logs`，API 在没有可用快照时返回 `503`。`sample` 只用于开发和测试，不用于正式展示。

## API

- `GET /api/health`
- `POST /api/admin/collect`
- `GET /api/admin/job-logs`
- `GET /api/index/shanghai`
- `GET /api/periods`
- `GET /api/rank/sectors?period=tail&type=turnover`
- `GET /api/rank/stocks?sector_code=BK0475&period=tail&type=turnover`
- `GET /api/rank/leaders?period=tail&type=fund`
- `GET /api/index`
- `GET /api/dashboard?timeframe=realtime&limit=10`
- `GET /api/rankings?timeframe=closing&limit=10`
- `GET /api/boards/{board_code}?timeframe=realtime&limit=10`
- `GET /api/leaders?timeframe=morning&limit=10`

支持的 `timeframe`：

- `realtime`
- `hour_0930_1030`
- `hour_1030_1130`
- `hour_1300_1400`
- `hour_1400_1500`
- `morning`
- `afternoon`
- `closing`
- `daily`
- `last_trade_day`

## 说明

AKShare 多数实时接口返回累计快照。小时榜、上午榜、下午榜和尾盘榜的正式计算方式应基于区间开始/结束快照差值：

```text
区间成交量 = 区间结束累计成交量 - 区间开始累计成交量
区间成交额 = 区间结束累计成交额 - 区间开始累计成交额
区间涨跌幅 = (区间结束价格 - 区间开始价格) / 区间开始价格 * 100%
```

当前 API 排行榜从数据库快照计算。若指定区间没有足够的开始/结束快照，服务会使用最新快照兜底，保证页面可用；调度任务积累到区间快照后，会自动按真实差值计算。

## 数据库表

启动时会自动创建：

- `trading_calendar`
- `index_snapshots`
- `stock_snapshots`
- `sector_snapshots`
- `stock_sector_map`
- `sector_leader_config`
- `rankings`
- `job_logs`

## 前端

当前前端是静态 HTML/CSS/JS，无需单独构建。页面包含：

- 上证指数指标栏
- 时间维度 Tab
- 板块成交额 Top 10 ECharts 图
- 板块成交额、成交量、资金量、涨幅榜单卡片
- 龙头股成交额、成交量、资金量、涨幅榜单卡片
- 点击板块后的板块内个股榜单

ECharts 从 CDN 加载；如果外网不可用，页面会降级显示表格榜单。

## 当前边界

- AKShare 字段会变化，provider 层做了兼容和失败回退，但生产需要持续校验。
- 当前默认 `DATA_PROVIDER=auto`：AKShare 全量接口失败时不回退样例数据，页面/API 会显示行情数据缺失或服务繁忙。
- 当数据源降级到 Sina 时，资金量字段暂以成交额作为可比排序指标，不能视为东方财富主力净流入数据。
- Tushare token 为空时只能按工作日粗略判断交易日，不能识别全部法定节假日。
- Redis 是可选项；本地默认使用内存缓存，重启后缓存丢失但数据库快照保留。
