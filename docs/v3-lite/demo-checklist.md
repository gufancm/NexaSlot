# V3 Lite 演示清单

## 准备

1. `docker compose up -d db redis`
2. 后端：`cd backend; uv run fastapi dev --port 8001`
3. Worker：`cd backend; uv run python -m app.worker`
4. 前端：`cd frontend; bun run dev`
5. 登录 `admin@example.com` / `changethis`，选择有资源的组织。
6. 确认 `.env`：`AI_ENABLED=true`、`LLM_PROVIDER=mock`；修改后重启 API。

## 演示 1：完整成功预约

- 资源中心 → 智能预约 → 输入“后天下午，8个人，带投影仪，开两个小时”。
- 展示解析结果：日期、13:00–18:00 搜索窗口、120 分钟、8 人、投影仪。
- 展示真实候选资源、地点、设备、空闲时段与推荐理由。
- 点击推荐卡片 → 确认预约 → 展示真实订单号。
- 打开“我的预约”确认订单存在。

证据：`screenshots/smart-booking.png`、`screenshots/smart-booking-confirmed.png`。

## 演示 2：缺少条件

- 输入“帮我找会议室” → 提示补充日期、人数、时长。
- 在修正表单中补充后重新推荐。

## 演示 3：无结果

- 输入“后天下午，99个人，带投影仪，开两个小时” → `no_results`。
- 关闭弹窗，使用原资源中心手动预约。

## 演示 4：AI 不可用

- 设置 `AI_ENABLED=false` 并重启 API，或网络拦截 `/api/v1/ai/recommend`。
- 智能预约返回 `unavailable`，手动预约仍正常。

## 演示 5：并发冲突

- 先获取推荐，再由另一个会话占用同一时段。
- 点击确认预约 → 409 → 提示“该时段已被其他人占用”，不展示成功。

## 自动化命令

```powershell
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .

cd ../frontend
bun run lint
bun run build
$env:PLAYWRIGHT_CHANNEL='chrome'
bunx playwright test tests/v3-ai-booking.spec.ts --reporter=line
```

