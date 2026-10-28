# V2 性能与多实例验收报告

> 数据采集时间：2026-10-28 11:45（Asia/Shanghai）
> 结论只适用于下列环境与负载，不代表生产容量承诺。所有数字均来自本机真实运行，原始 CSV/JSON 一并保留。

## 1. 环境

| 项目 | 配置 |
| --- | --- |
| CPU | 12th Gen Intel Core i7-12700H，14 核 / 20 线程 |
| 内存 | 15.7 GB |
| 操作系统 | Windows 10 专业版 |
| Python | 3.14 |
| MySQL | 8.4.13（Docker，宿主端口 3307，容器内 3306） |
| Redis | 7.4.12（Docker，宿主端口 6380，容器内 6379） |
| API | `fastapi run` 生产模式，每个实例单 worker |
| 压测工具 | Locust 2.47.0 |
| 数据规模 | 1 个压测组织、1 个场地、20 个资源；可用性查询日期 2026-10-29 |

对照实例：

- `http://127.0.0.1:8002`：`CACHE_ENABLED=false`
- `http://127.0.0.1:8003`：`CACHE_ENABLED=true`
- 两者共享同一 MySQL 与 Redis；Redis 仅用于缓存与限流。

## 2. 负载与方法

- 场景：`BENCH_SCENARIO=availability`，随机请求 20 个资源中某一个的 `/resources/{id}/availability?date=2026-10-29`。
- 用户模型：10 个并发 Locust 用户，升压 5 用户/秒，持续 20 秒，请求间等待 0.1–0.4 秒（闭环负载）。
- 预热：每个实例先用 5 用户跑 5 秒，使 MySQL InnoDB buffer pool 处于热状态。
- 缓存冷启动：预热后清空 `nexaslot:availability:*`，但保留 MySQL 预热效果；因此命中率不是“缓存已热”的乐观值。
- 所有请求均登录为同一演示用户；登录请求单独统计，不计入可用性延迟。
- `409`/`429` 与 `5xx` 分开统计；本场景为只读，实际失败数为 0。

## 3. 对照结果

| 指标 | 无缓存（8002） | 有缓存（8003） | 变化 |
| --- | ---: | ---: | ---: |
| 可用性请求数（Locust CSV） | 678 | 698 | +2.9% |
| 失败数 | 0 | 0 | — |
| 吞吐（req/s） | 35.41 | 36.53 | +3.2% |
| 平均延迟 | 20 ms | 13 ms | **-35.0%** |
| P50 | 16 ms | 12 ms | **-25.0%** |
| P95 | 40 ms | 22 ms | **-45.0%** |
| P99 | 74 ms | 44 ms | **-40.5%** |
| 最大延迟 | 160 ms | 92 ms | -42.5% |
| MySQL `Com_select` 增量（20 秒） | 4,876 | 2,939 | **-39.7%** |
| 每请求平均 SELECT 数 | 7.19 | 4.21 | -2.98 |
| 缓存命中 / 未命中 | — | 697 / 22 | — |
| 缓存命中率 | — | **96.94%** | — |

说明：

- 吞吐只提升 3.2%，因为这是 10 用户的闭环负载，客户端思考时间主导上限；本实验的目标是对比同一负载下的延迟与回源量，不是压出系统最大 RPS。
- 缓存命中 697 次、未命中 22 次；22 次接近 20 个资源键的冷启动回源，另有少量并发回填。
- 缓存后仍有约 4.21 次 SELECT/请求，主要来自 JWT 用户查询、组织成员校验、资源/场地访问校验；本次只缓存了可用性构建，未缓存鉴权链。因此不能把 39.7% 的回源下降解释为“所有数据库查询减少 40%”。
- Locust CSV 的请求数与 Redis 命中数相差 <1%，是进程退出时少量在途请求未落入 CSV 的快照误差；延迟统计使用 CSV，缓存命中统计使用 Redis 服务端计数。

原始数据：

- `benchmark-summary.json`
- `availability-no-cache_stats.csv`
- `availability-cache_stats.csv`
- 对应的 `_stats_history.csv`、`_failures.csv`、`_exceptions.csv`

## 4. SQL 执行计划

在压测数据上执行 `EXPLAIN ANALYZE`（UUID 在 MySQL 中以 32 位十六进制存储）：

| 查询 | 访问路径 | 实际行数 | 实际耗时 |
| --- | --- | ---: | ---: |
| 某资源某日时间片 | `uq_slot_resource_start` 索引范围扫描 | 24 | 0.099 ms |
| 场地内启用资源 + 容量过滤 | `ix_resources_site_status` 索引查找，容量条件过滤 | 20 | 0.065 ms |
| 候补队列取队首 | `ix_waitlist_queue` 索引范围扫描 | 0 | 0.009 ms |
| 用户订单倒序分页 | `ix_reservations_user_created` 反向索引查找 | 6 | 0.036 ms |

结论：四条核心读路径均命中预期索引，没有全表扫描。当前数据量很小，绝对耗时不具代表性；该证据用于确认索引设计与查询形态匹配。

## 5. 多实例限流与并发一致性

脚本：`backend/scripts/verify_multinstance.py`；原始结果：`multinstance-report.json`。

### 5.1 限流不被实例数放大

同一用户交替请求 8002/8003，共 11 次预约写请求：

```text
201, 409, 409, 409, 409, 409, 409, 409, 409, 409, 429
```

- 放行 10 次，429 一次；`Retry-After: 6`。
- 说明两个实例共享同一 Redis Token Bucket，配额没有随实例数翻倍。
- 其中 9 次 409 是同一时段已被第一笔订单占用，属于预期业务冲突，不是系统故障。

### 5.2 并发抢同一时段

两实例各处理 5 个并发请求，共 10 个不同 `Idempotency-Key` 抢同一资源同一时段：

```text
1 × 201, 9 × 409, 0 × 429, 0 × 5xx
```

数据库核对：

| 不变量 | 结果 |
| --- | --- |
| 该时段 `CONFIRMED` 订单数 | 1 |
| 成功响应 ID 与数据库订单一致 | 是 |
| 该时段被占用时间片数 | 1 |
| 该时段带 HOLD 的时间片数 | 0 |
| 同一时间片同时有预约与 HOLD | 否 |

两笔测试预约随后均成功取消（HTTP 200），未留下测试占用。

## 6. 复现

```powershell
# 1. 准备数据
cd backend
uv run python scripts/seed_benchmark.py

# 2. 启动两个生产模式实例（另开两个终端）
$env:CACHE_ENABLED='false'; fastapi run --port 8002
$env:CACHE_ENABLED='true';  fastapi run --port 8003

# 3. 采集对照数据（预热 + 冷缓存 + Com_select + 命中率）
pwsh scripts/bench_availability.ps1 -Users 10 -DurationSeconds 20

# 4. 多实例限流与并发一致性
uv run python scripts/verify_multinstance.py
```

注意：

- 必须用 `fastapi run`，不要用 `fastapi dev`；文件监听重载会污染延迟数据。
- 两个实例必须共用同一 MySQL/Redis，否则限流和缓存对照不成立。
- 压测密码从 `BENCH_PASSWORD` 读取，不写入 seed 文件。

## 7. 适用边界

- 本报告只证明**同一台开发机、单 API worker、20 个资源、10 个闭环用户**下的可用性读优化与多实例正确性。
- 未测生产级网络、TLS、反向代理、连接池上限、Worker 并发与更大数据量；不应把 35 req/s 当作系统容量上限。
- 未声称“P95 降低 45%”适用于所有接口；该数字仅适用于本可用性查询场景。
- 未测量锁等待与死锁次数；并发正确性通过结果状态与数据库不变量验证，而非性能指标。

