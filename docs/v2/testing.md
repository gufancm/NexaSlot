# V2 测试与验收

## 1. 后端测试

```bash
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

最近一次结果（2026-10-28）：

```text
74 passed, 90 warnings in 20.96s
All checks passed!
71 files already formatted
```

### 测试分布

| 文件 | 数量 | 覆盖重点 |
| --- | ---: | --- |
| `tests/api/routes/test_users.py` | 27 | 用户、权限、资料、密码（V1） |
| `tests/crud/test_user.py` | 10 | 用户 CRUD（V1） |
| `tests/api/routes/test_login.py` | 9 | 登录、Token、重置密码（V1） |
| `tests/api/routes/test_reservations.py` | 6 | 预约冲突、幂等、取消释放、跨租户（V1） |
| `tests/api/routes/test_organizations.py` | 5 | 组织、成员、RBAC（V1） |
| `tests/api/routes/test_scheduling.py` | 5 | 硬约束、稳定排序、冲突过滤、替代推荐、缓存失效 |
| `tests/api/routes/test_waitlist.py` | 5 | FIFO、确认、重复确认、拒绝递补、过期递补、跨租户、通知已读、Outbox 去重 |
| `tests/api/routes/test_sites_resources.py` | 3 | 场地、资源、开放规则（V1） |
| `tests/test_v2_infrastructure.py` | 3 | Token Bucket、Redis 降级、Outbox 幂等 |
| `tests/api/routes/test_private.py` | 1 | 开发态私有路由（V1） |

> 测试连接 `.env` 中的 MySQL。`conftest.py` 会创建超级管理员与测试用户；请勿把测试指向生产库。

## 2. 前端检查

```bash
cd frontend
bun run generate-client   # 后端 schema 变更后必须执行
bun run lint
bun run build
```

`bun run lint` 使用 Biome（`--write --unsafe`），会就地修复格式与可自动修复的问题。

## 3. 多实例验收

前置：两个 API 实例共享同一 MySQL/Redis，并已生成 `docs/v2/performance/seed.json`。

```powershell
cd backend
$env:CACHE_ENABLED='false'; fastapi run --port 8002
$env:CACHE_ENABLED='true';  fastapi run --port 8003

# 另开终端
uv run python scripts/verify_multinstance.py
```

最近一次结果：

| 检查 | 结果 |
| --- | --- |
| 同一用户 11 次预约写请求（交替 8002/8003） | 状态序列 `201, 9×409, 429`；10 次放行、1 次 429；`Retry-After: 6` |
| 两实例并发抢同一时段（10 并发） | `1×201, 9×409, 0×429, 0×5xx` |
| 数据库不变量 | 确认订单 1 笔；占用槽位 1 个；HOLD 槽位 0 个；单占用指针成立 |
| 清理 | 两笔测试预约取消均返回 200 |

完整机器可读结果：`docs/v2/performance/multinstance-report.json`。

脚本只清除 `reservation-create` 限流桶，并在结束时取消自己创建的预约，便于重复执行。

## 4. Locust 压测场景

```bash
cd backend
uv run python scripts/seed_benchmark.py

# 只读可用性（性能对照使用）
BENCH_SCENARIO=availability uv run locust -f locust/locustfile.py \
  --headless -u 10 -r 5 -t 20s --host http://127.0.0.1:8003 \
  --csv ../docs/v2/performance/availability-cache

# 热点争抢
BENCH_SCENARIO=hotspot uv run locust -f locust/locustfile.py \
  --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8003

# 分散预约
BENCH_SCENARIO=distributed uv run locust -f locust/locustfile.py \
  --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8003

# 查询 + 预约 + 匹配混合
BENCH_SCENARIO=mixed uv run locust -f locust/locustfile.py \
  --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8003
```

- `409`（业务冲突）与 `429`（限流）被视为预期结果，不计入故障；`5xx` 计为失败。
- 对照实验请使用相同 `-u/-r/-t`、生产模式 `fastapi run`、预热后再测。
- 压测夹具密码不写入 `seed.json`；通过 `BENCH_PASSWORD` 环境变量提供（默认 `changethis`）。

## 5. 前端 E2E（已编写，未执行）

新增 `tests/v2-smoke.spec.ts`：登录后依次访问 `/waitlist`、`/notifications`、`/match` 并断言页面标题。V2 页面已通过 TypeScript 构建与 Biome 检查；本次验收尝试运行 Playwright，但本机缺少 Chromium，且从 `storage.googleapis.com` 下载浏览器在 30 秒后超时（重试 5 次均失败），因此 **3 个冒烟用例未执行，不计为通过**。

网络可用时执行：

```bash
cd frontend
bunx playwright install chromium
bunx playwright test tests/v2-smoke.spec.ts
```

该限制只影响浏览器 E2E；后端 74 项测试、前端构建/检查与多实例脚本均已实际执行。

## 6. 手工验收清单

- [ ] 资源详情选择一个已占用时段，出现「加入候补」。
- [ ] 两个用户依次加入同一时段，`/waitlist` 显示队列位置。
- [ ] 取消占用预约后，第一位候补变为 `OFFERED` 并显示倒计时。
- [ ] 确认 OFFER 后生成真实预约；重复点击不会生成第二笔。
- [ ] 拒绝或等待超时后，资源递补给下一位。
- [ ] `/notifications` 出现通知，未读角标随已读减少。
- [ ] `/match` 输入人数/设备/时间，返回真实可用资源及推荐理由。
- [ ] 连续快速预约触发 429，并展示 `Retry-After` 提示。
- [ ] Worker 停止再启动后，过期 HOLD 被补处理，通知恢复投递。

