# V3 Lite 评测

## 冻结评测集

`backend/tests/fixtures/ai_booking_cases.json` 包含 40 条固定中文样例，参考时间为 `2026-10-28T09:00:00+08:00`，覆盖：

- 完整需求、显式时间范围、相对日期、星期表达、月日表达。
- 缺日期、缺人数、缺时长、开始时间单独出现。
- 过去日期、超出预约窗口、反向时间范围、非法时长。
- 设备表达及别名/错别字：投影、投屏、投景仪、白班、视频会议、隔音、白噪音。
- 楼层偏好：二楼、2楼、二层。
- 非预约意图与提示注入：天气、取消、密码、伪造 `resource_id`。

## 运行

```powershell
cd backend
uv run python scripts/evaluate_ai_parser.py --output ../docs/v3-lite/evaluation.json
```

真实模型（会产生费用，需自行配置 Key）：

```powershell
uv run python scripts/evaluate_ai_parser.py --provider openai
```

## 当前结果

```json
{
  "provider": "mock",
  "cases": 40,
  "intent_accuracy": 1.0,
  "field_accuracy": 1.0,
  "pydantic_valid_rate": 1.0,
  "avg_latency_ms": 0.121,
  "p95_latency_ms": 0.347,
  "field_checks": 272,
  "failures": []
}
```

完整输出见 [evaluation.json](evaluation.json)。

> **重要说明：** 以上是 Mock 解析器的确定性契约基线，只证明测试集、解析规则和 Pydantic 契约一致，**不代表真实 LLM 的准确率**。真实模型需在配置 Key 后单独运行并记录自己的结果。

## 评测口径

- `intent_accuracy`：`is_booking_request` 与期望一致的比例。
- `field_accuracy`：所有样例中所有期望字段逐一比对后的正确率（共 272 个字段检查）。
- `pydantic_valid_rate`：解析结果序列化后仍能通过 `BookingExtraction` 校验的比例。
- `avg_latency_ms` / `p95_latency_ms`：本地解析耗时，不含真实网络调用。

业务规则、时间边界、权限与冲突另由 `tests/test_ai_validation.py` 与 `tests/api/routes/test_ai.py` 验证，不用“返回了 JSON”代替“提取正确”。

