# Panlong Rank

上证指数、板块、板块内股票和龙头股排行榜 MVP。

当前版本提供：

- 上证指数摘要
- 板块成交额、成交量、资金量、涨幅和尾盘榜
- 板块详情内股票排行榜
- 龙头股成交量、成交额、资金量、涨幅和尾盘榜
- 实时榜、小时榜、上午榜、下午榜、尾盘榜、当日总榜、最近一个交易日榜
- 交易日/非交易日状态提示
- AKShare 可选数据源，依赖不可用时自动回退到样例数据

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

## 配置

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `Panlong Rank` | 服务名称 |
| `DATA_PROVIDER` | `auto` | `auto`、`akshare`、`sample` |
| `TUSHARE_TOKEN` | 空 | 设置后可用 Tushare 交易日历 |
| `RANK_LIMIT` | `10` | 默认排行条数 |

`DATA_PROVIDER=auto` 时会优先尝试 AKShare，失败后使用样例数据，保证页面和 API 可运行。

## API

- `GET /api/health`
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

当前代码已经提供差值计算函数和统一排行结构。后续接 PostgreSQL/Redis/APScheduler 时，只需要把快照落库并将指定区间的开始、结束快照传入计算层。
