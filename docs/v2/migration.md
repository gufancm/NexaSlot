# V1 → V2 数据库迁移

## 1. 迁移链

```text
c143587f8700 (V1 基线)
  -> a7c41d9e2b10  v2 waitlist, holds, notifications, outbox
  -> b8e52f1c4d90  waitlist FIFO timestamp precision
```

两条迁移均为**增量迁移**，不重建 V1 表，不修改历史预约数据。已在本地已有 V1 数据的 MySQL 8.4.13 实例上实际执行 `upgrade head` 成功。

## 2. `a7c41d9e2b10` 做了什么

| 变更 | 说明 |
| --- | --- |
| 新建 `booking_holds` | OFFER 临时占位；索引 `(status, expires_at)`、`(resource_id, start_at)` |
| 新建 `waitlist_entries` | 候补队列；索引 `(resource_id, start_at, end_at, status, created_at, id)`、`(user_id, created_at)` |
| 新建 `notifications` | 站内通知；唯一 `(event_id, user_id)`，索引 `(user_id, created_at)` |
| 新建 `outbox_events` | 事务事件；索引 `(status, available_at)` |
| `resource_slots.current_hold_id` | 指向当前 HOLD，外键 `RESTRICT` |
| `CHECK ck_slot_single_owner` | 预约指针与 HOLD 指针不能同时非空 |
| `uq_waitlist_active` | 同一用户对同一资源+完全相同窗口只能有一条活跃候补 |

### 三个关键兼容决策

1. **`current_reservation_id` 外键从 `SET NULL` 改为 `RESTRICT`**
   MySQL 不允许 CHECK 约束引用带 `SET NULL` 外键的列。V2 业务从不物理删除预约，因此改为 `RESTRICT` 语义正确；降级时会恢复 V1 的 `SET NULL`。

2. **活跃候补唯一索引使用生成列 `active_flag`**
   `active_flag = CASE WHEN status IN ('WAITING','OFFERED') THEN 1 ELSE NULL END`，终态行为 `NULL` 被唯一索引忽略。这样既阻止重复排队，又保留历史记录。

3. **时间戳精度使用 `DATETIME(6)`**
   MySQL `DATETIME` 默认只到秒。候补 FIFO 排序键是 `(created_at, id)`；同一秒内加入的候补若只有秒级时间，会退化成 UUID 随机顺序，破坏公平性。`b8e52f1c4d90` 将 `waitlist_entries.created_at/updated_at` 与 `booking_holds.created_at/updated_at/expires_at` 改为微秒精度。

## 3. 升级已有 V1 数据库

```bash
cd backend
uv run alembic current       # 应为 c143587f8700
uv run alembic upgrade head  # 升到 b8e52f1c4d90
uv run alembic current       # 确认 b8e52f1c4d90 (head)
```

升级后建议执行以下校验：

```sql
-- 新表存在
SHOW TABLES LIKE 'booking_holds';
SHOW TABLES LIKE 'waitlist_entries';
SHOW TABLES LIKE 'notifications';
SHOW TABLES LIKE 'outbox_events';

-- 互斥约束存在
SHOW CREATE TABLE resource_slots;  -- 应包含 ck_slot_single_owner

-- 历史预约未被改写
SELECT COUNT(*) FROM reservations WHERE status = 'CONFIRMED';
SELECT COUNT(*) FROM resource_slots WHERE current_reservation_id IS NOT NULL;
```

本地实测：升级前 `a7c41d9e2b10` 应用成功，随后 `b8e52f1c4d90` 应用成功；历史订单与时间片指针保持不变。

## 4. 全新数据库

```bash
cd backend
uv run alembic upgrade head
uv run python app/initial_data.py
uv run python scripts/seed_demo.py
```

全新库会按迁移链一次建到 `b8e52f1c4d90`，无需先建 V1 再升级。

## 5. 降级

```bash
cd backend
uv run alembic downgrade a7c41d9e2b10   # 回到秒级时间戳
uv run alembic downgrade c143587f8700   # 回退 V2 全部表与列
```

降级注意事项：

- `b8e52f1c4d90` 降级会把时间戳截断到秒，可能丢失微秒精度；仅在确认不再需要 FIFO 稳定性时执行。
- `a7c41d9e2b10` 降级会删除 V2 新表；已有候补、HOLD、通知和 Outbox 数据会丢失。生产环境应先备份。
- 降级会恢复 `current_reservation_id` 的 V1 `SET NULL` 外键，并删除 `ck_slot_single_owner`。

## 6. 上线顺序

1. 备份数据库。
2. 执行 `alembic upgrade head`。
3. 部署新 API（可滚动；新旧实例共享同一库）。
4. 启动 Worker（`python -m app.worker` 或 Compose `worker` 服务）。
5. 验证健康检查、预约创建/取消、候补加入、通知读取。

> 迁移只增加表/列和约束，不要求停写；但 `CHECK` 与唯一索引创建期间会对 `resource_slots`/`waitlist_entries` 加锁，建议在低峰执行。

