# Panlong Rank 项目交接记录

更新时间：2026-07-03

## 当前目标

按照 `dev.md` 开发上证指数、板块、板块内股票、龙头股排行榜系统。正式运行模式必须采集真实行情数据并缓存展示；不能使用样例数据冒充真实数据。若上游行情不可用或快照缺失，接口应返回数据缺失/服务器繁忙状态。

## 已完成内容

- 初始化 FastAPI 项目，提供静态前端页面和 API。
- 接入 SQLAlchemy 数据模型，支持 SQLite/PostgreSQL。
- 增加 Alembic 初始迁移。
- 增加 Dockerfile 和 docker-compose，本地 Docker 可启动 app、PostgreSQL、Redis。
- 增加 APScheduler 定时采集任务。
- 增加 Redis/内存 TTL 缓存。
- 增加交易时段配置：实时、小时榜、上午榜、下午榜、尾盘榜、当日总榜、最近一个交易日榜。
- 增加数据库快照表：指数、板块、个股、个股板块映射、龙头股配置、榜单、任务日志。
- 增加榜单计算：板块成交额、成交量、资金量、涨幅；板块内个股榜；龙头股榜。
- 增加采集任务日志接口和手动采集接口。
- 增加上游采集限频：默认最小采集间隔 60 秒，避免用户请求直接打到第三方接口。
- 正式模式下禁止样例数据兜底：`DATA_PROVIDER=auto` 或 `akshare` 采集失败时不写入假数据。
- 样例数据仅保留给开发和测试：必须显式设置 `DATA_PROVIDER=sample`。

## 关键文件

- `dev.md`：原始开发需求。
- `README.md`：启动、配置、API、当前边界说明。
- `docker-compose.yml`：本地 Docker 部署配置，默认 `DATA_PROVIDER=auto`。
- `app/services/provider.py`：数据源适配层，当前正式数据源为 AKShare。
- `app/services/collector.py`：采集、限频、任务日志。
- `app/services/ranking_service.py`：从数据库快照计算 API 榜单。
- `app/services/snapshot_store.py`：快照写入与查询。
- `app/main.py`：FastAPI 路由。
- `app/static/`：静态前端页面。
- `tests/`：当前核心单元测试。

## 本地 Docker 验证结果

已执行过：

```bash
docker compose down -v
docker compose up --build -d
docker compose ps
```

服务可以启动。由于当前环境访问 AKShare/Eastmoney 上游失败，Fresh DB 下真实快照表为空，API 正确返回 503：

```text
GET /api/index/shanghai -> 503
{"detail":"行情数据缺失，采集服务繁忙或上游数据源不可用"}
```

当时数据库计数：

```text
index_snapshots  0
sector_snapshots 0
stock_snapshots  0
rankings         0
job_logs         1
```

`job_logs` 中记录的失败原因包括 AKShare 上游连接失败：

```text
AKShare unavailable after retries: RemoteDisconnected('Remote end closed connection without response')
```

## AKShare/Eastmoney 访问诊断

已查 AKShare 官方文档，以下接口不需要 token 或认证：

- `stock_zh_index_spot_em`：沪深京指数实时行情，来源东方财富。
- `stock_zh_a_spot_em`：沪深京 A 股实时行情，来源东方财富。
- `stock_board_industry_name_em`：行业板块行情，来源东方财富。

本机和 Docker 容器中，AKShare 对 `*.push2.eastmoney.com` 的访问失败，出现过：

- DNS 解析失败，例如 `Failed to resolve '48.push2.eastmoney.com'`。
- 远端断开连接，例如 `RemoteDisconnected('Remote end closed connection without response')`。

使用公共 DoH 查询时，`48.push2.eastmoney.com` 可以解析，说明域名本身不是 NXDOMAIN：

```text
48.push2.eastmoney.com CNAME push2ipv6.trafficmanager.cn
push2ipv6.trafficmanager.cn A 14.103.191.91
```

美国 VPS 验证结果：

- `getent hosts 48.push2.eastmoney.com` 可解析到 IPv6。
- `https://48.push2.eastmoney.com/...` 强制 IPv4 时出现 302，跟随跳转后空响应。
- `https://push2.eastmoney.com/...` 在 VPS 上返回 502。

结论：这不是 AKShare 需要 token 的问题，也不是简单的“域名不存在”。更可能是 Eastmoney push2 动态节点对不同网络出口、IPv4/IPv6、CDN 节点或请求路径不稳定，AKShare 当前接口在该运行环境下无法稳定拿到真实数据。

## 当前设计原则

- 正式展示只允许真实行情快照。
- 没有真实快照时返回 503，不展示样例点位。
- 用户访问 API 不触发第三方实时采集，避免被访问量放大。
- 采集由启动任务、调度任务、或后台管理手动触发。
- 上游失败要记录 `job_logs`，便于排查。
- 可配置 `DATA_PROVIDER=sample` 做开发测试，但不得用于正式部署。

## 下一步建议

1. 继续验证 AKShare 在目标部署机器上的可用性：

   ```bash
   python3 - <<'PY'
   import akshare as ak
   for name in ["stock_zh_index_spot_em", "stock_zh_a_spot_em", "stock_board_industry_name_em"]:
       try:
           df = getattr(ak, name)()
           print(name, "OK", df.shape, list(df.columns)[:8])
       except Exception as exc:
           print(name, "FAIL", repr(exc))
   PY
   ```

2. 若 AKShare 在目标机器仍不可用，优先实现一个真实 Eastmoney Provider，不再完全依赖 AKShare 随机编号子域名。

   已知需要重新验证的接口方向：

   - 指数：`/api/qt/stock/get?secid=1.000001`
   - A 股列表：`/api/qt/clist/get`
   - 行业板块列表：`/api/qt/clist/get`
   - 板块成分股：可参考 AKShare 源码中行业板块成分接口的参数。

3. 增加“数据源健康检查”页面或接口，明确展示最近采集成功时间、失败原因、当前数据源。
4. 若未来公开或商业化部署，应接入正式授权行情源，而不是依赖 AKShare/Eastmoney 免费接口。

## Git 状态

本地仓库已初始化，远程仓库：

```text
git@github.com:danwithgit/panlong-rank.git
```

之前推送失败过一次，原因是本机默认 SSH key 识别为其他 GitHub 账户。下次推送应显式使用目标账户对应的 RSA key：

```bash
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_rsa -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" git push -u origin main
```

不要把任何服务器密码、VPS 密码、GitHub token 写进仓库。
