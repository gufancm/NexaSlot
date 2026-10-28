# NexaSlot V2 — 高并发预约、自动候补与可观测性

> 状态：V2.0 功能实现与本地验收完成（2026-10-28）。
> V1 基线：Commit `e85c782`（`feat(v1): deliver NexaSlot booking platform on MySQL`）。
> V2 开发依据：`NexaSlot_V2_开发任务清单.md`。

V2 在 V1 的「资源发布 → 查空闲 → 预约 → 取消」闭环上，补齐了**并发正确性、Redis 缓存与限流、自动候补与临时占位、MySQL Outbox + Worker、确定性资源匹配、可复现压测**六条主线。所有能力均可在本地完整演示，并有自动化测试或真实运行数据佐证。

## V2 交付内容

| 主线 | 已交付 | 主要代码 |
| --- | --- | --- |
| A. 并发正确性 | 统一锁顺序、唯一约束 + CHECK、多实例并发验收 | `backend/app/services/reservations.py`、`allocation.py` |
| B. Redis 性能优化 | Cache-Aside、资源版本化失效、single-flight、Lua Token Bucket | `backend/app/cache/availability.py`、`backend/app/core/ratelimit.py`、`redis_sync.py` |
| C. 自动候补 | FIFO 队列、OFFER/HOLD、确认/拒绝/超时递补 | `backend/app/services/waitlist.py`、`allocation.py` |
| D. 可靠异步 | 事务内 Outbox、`SKIP LOCKED` 领取、租约、重试、幂等通知、独立 Worker | `backend/app/services/outbox.py`、`backend/app/worker.py` |
| E. 智能匹配 | 硬约束过滤 + 可解释软评分 + 替代推荐 | `backend/app/services/matching.py` |
| F. 测试与交付 | 74 项后端测试、Locust 场景、压测报告、多实例脚本、文档 | `backend/tests/`、`backend/locust/`、`docs/v2/` |

## 已验证证据

| 验证项 | 结果 | 证据 |
| --- | --- | --- |
| 后端全量测试 | **74 passed**（V1 61 + V2 13） | `backend/tests/`，2026-10-28 本地执行 |
| 后端静态检查 | `ruff check` 与 `ruff format --check` 通过 | 71 个 Python 文件 |
| 前端检查 | `bun run build`、`bun run lint` 通过 | `frontend/src/client` 已按最新 OpenAPI 重新生成 |
| 增量迁移 | 在已有 V1 数据库上从 `c143587f8700` 升到 `b8e52f1c4d90` | `docs/v2/migration.md` |
| 缓存对照 | 命中率 **96.94%**，P95 **22ms vs 40ms**，MySQL `Com_select` **-39.7%** | `docs/v2/performance/report.md` |
| 多实例限流 | 同一用户 11 次写入：**10 次放行 + 1 次 429** | `docs/v2/performance/multinstance-report.json` |
| 并发一致性 | 两实例并发抢同一时段：**1 笔成功 / 9 笔 409 / 0 个 5xx**，数据库仅 1 个占用槽位 | 同上 |
| 索引与执行计划 | 可用性、资源筛选、候补队列、订单列表均命中索引 | `docs/v2/performance/report.md` |

## 快速启动

前置：`uv`、`bun`、Docker Desktop。

```bash
# 1. MySQL 8.4 + Redis 7.4（宿主端口 3307 / 6380）
docker compose up -d db redis

# 2. 后端
cp .env.example .env
cd backend
uv sync
uv run alembic upgrade head
uv run python app/initial_data.py
uv run fastapi dev --port 8001

# 3. Worker（候补 OFFER 过期、Outbox 通知；V2 必须单独启动）
cd backend
uv run python -m app.worker

# 4. 前端
cd frontend
bun install
bun run dev
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8001/docs |
| 健康检查 | http://localhost:8001/api/v1/utils/health-check/ |
| 运营指标 | http://localhost:8001/api/v1/operations/metrics（需登录） |

默认管理员：`admin@example.com` / `changethis`。演示数据：`uv run python scripts/seed_demo.py`。

> Worker 不启动时，预约/取消仍可正常工作，但 OFFER 不会自动过期，Outbox 通知不会投递。生产环境用 `docker compose up -d backend worker` 或独立进程运行。

## 多实例运行

两个 API 实例共用同一 MySQL 与 Redis；缓存、限流、候补与 Outbox 均按共享存储设计：

```powershell
cd backend
$env:CACHE_ENABLED='false'; fastapi run --port 8002
$env:CACHE_ENABLED='true';  fastapi run --port 8003
```

验收脚本会检查限流是否被实例数放大，以及并发抢同一时段是否只产生一笔订单：

```powershell
cd backend
pwsh scripts/bench_availability.ps1 -Users 10 -DurationSeconds 20
uv run python scripts/verify_multinstance.py
```

## 配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CACHE_ENABLED` | `true` | 可用性与资源详情 Cache-Aside 总开关 |
| `CACHE_AVAILABILITY_TTL_SECONDS` | `60` | 可用性缓存 TTL |
| `CACHE_RESOURCE_TTL_SECONDS` | `300` | 资源详情缓存 TTL |
| `RATE_LIMIT_ENABLED` | `true` | 分布式限流总开关 |
| `RATE_LIMIT_BOOKING_CAPACITY` | `10` | 预约写接口令牌桶容量 |
| `RATE_LIMIT_BOOKING_REFILL_PER_MINUTE` | `10` | 预约写接口每分钟补充令牌 |
| `RATE_LIMIT_WAITLIST_CAPACITY` | `10` | 候补写接口令牌桶容量 |
| `RATE_LIMIT_FAIL_CLOSED_ON_WRITE` | `false` | Redis 故障时写接口是否 503（默认降级放行） |
| `WAITLIST_OFFER_TTL_MINUTES` | `10` | OFFER 确认期限 |
| `OUTBOX_BATCH_SIZE` | `20` | Worker 单次领取事件数 |
| `OUTBOX_LEASE_SECONDS` | `60` | 事件租约，防止多 Worker 重复处理 |
| `OUTBOX_MAX_ATTEMPTS` | `5` | 最大重试次数，超过转 `FAILED` |
| `WORKER_POLL_SECONDS` | `2.0` | Worker 轮询间隔 |
| `MATCH_WEIGHT_CAPACITY` | `0.5` | 匹配评分：容量契合权重 |
| `MATCH_WEIGHT_SITE` | `0.3` | 匹配评分：场地偏好权重 |
| `MATCH_WEIGHT_WINDOW` | `0.2` | 匹配评分：时段契合权重 |

完整示例见 `.env.example`。

## V2 新增 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/waitlist` | 加入候补（需 `Idempotency-Key`，429 限流） |
| `GET` | `/api/v1/waitlist/me` | 我的候补（分页、按状态过滤、队列位置） |
| `DELETE` | `/api/v1/waitlist/{entry_id}` | 退出候补 |
| `GET` | `/api/v1/waitlist/offers/{hold_id}` | 查看 OFFER 与到期时间 |
| `POST` | `/api/v1/waitlist/offers/{hold_id}/confirm` | 确认 OFFER，原子转预约 |
| `POST` | `/api/v1/waitlist/offers/{hold_id}/decline` | 拒绝 OFFER，原子递补下一位 |
| `GET` | `/api/v1/admin/waitlist` | 组织级候补队列（RBAC 隔离） |
| `POST` | `/api/v1/scheduling/match` | 资源匹配（硬约束 + 可解释评分） |
| `GET` | `/api/v1/resources/{id}/alternatives` | 同时段替代资源与同资源替代时段 |
| `GET` | `/api/v1/notifications` | 我的通知（含未读数） |
| `POST` | `/api/v1/notifications/{id}/read` | 标记单条已读（幂等） |
| `POST` | `/api/v1/notifications/read-all` | 全部标记已读 |
| `GET` | `/api/v1/operations/metrics` | Outbox/HOLD/候补/缓存/通知指标 |
| `GET` | `/api/v1/operations/outbox/failed` | 失败事件排查 |
| `POST` | `/api/v1/operations/outbox/{id}/retry` | 手动重试失败事件 |

原有 `POST /api/v1/reservations`、`POST /api/v1/reservations/{id}/cancel` 保持兼容，并已接入 HOLD 互斥、候补递补与资源版本化缓存失效。

## 文档索引

- `architecture.md`：组件、事务边界、锁顺序、候补状态机、缓存/限流/Outbox/匹配设计。
- `migration.md`：V1 → V2 增量迁移、约束决策、升级/回滚步骤。
- `testing.md`：测试矩阵、运行命令、多实例验收与 Locust 场景。
- `performance/report.md`：真实性能数据、执行计划、多实例结果与复现方法。

## 范围边界

- 候补 FIFO 只承诺**同一资源 + 完全相同的起止时间**；不承诺跨时段、跨资源全局排队公平。
- Outbox 是**至少一次**语义，消费者通过 `(event_id, user_id)` 唯一键实现幂等；不承诺外部通知恰好一次。
- Redis 只做缓存、限流与共享锁，**不是订单权威**；Redis 故障不会导致数据库双重占用。
- 通知中心采用前端轮询（15–20 秒）刷新，未实现 SSE 推送；轮询失败会退回正常查询。
- LangGraph、LLM 自然语言预约、AI 运营问答、支付与动态定价属于 V3，不在本版本范围。

