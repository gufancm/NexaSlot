# NexaSlot — 开发指南

## 本地开发

本地开发使用 Docker Compose 运行 MySQL 与 Redis，FastAPI 与 Vite 直接跑在宿主机上。

```bash
docker compose up -d db redis
```

后端（`backend/` 目录）：

```bash
uv sync
uv run bash scripts/prestart.sh   # alembic upgrade head + 初始化超级管理员
uv run fastapi dev --port 8001
```

前端（项目根目录或 `frontend/`）：

```bash
bun install
bun run dev
```

入口：

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5173 |
| 后端 API | http://localhost:8001 |
| Swagger | http://localhost:8001/docs |
| Adminer | http://localhost:8080 |
| Mailpit | http://localhost:8025 |

`frontend/.env` 中的 `VITE_API_URL` 指向 `http://localhost:8001`。

### 数据库与迁移

- 数据库为 MySQL 8.4，容器内端口 `3306`，宿主映射 `3307`；字符集 `utf8mb4`，服务端时区 `+00:00`。
- 所有表结构通过 Alembic 管理：

  ```bash
  cd backend
  uv run alembic upgrade head
  uv run alembic revision -m "describe change"
  ```

- 删除本地数据并重建（**仅限开发环境**）：

  ```bash
  docker compose down -v
  docker compose up -d db redis
  cd backend && uv run alembic upgrade head
  ```

### 演示数据

```bash
cd backend
uv run python scripts/seed_demo.py
```

脚本幂等：重复执行不会重复创建组织与资源。

## 前端由 FastAPI 托管

```bash
cd frontend
bun run build
```

构建产物输出到 `backend/app/frontend`，由 FastAPI 在 <http://localhost:8001> 提供。

## Docker Compose 全栈

```bash
docker compose run --rm backend bash scripts/prestart.sh
docker compose watch
```

- 应用：<http://localhost:8000>
- Adminer：<http://localhost:8080>
- Traefik 面板：<http://localhost:8090>

启动 Compose 后端前请先停掉本机 8000 端口的 FastAPI 进程。

## 环境变量

- 根目录 `.env`：后端与 Compose 共用，包含 `DATABASE_URL`、`REDIS_URL`、预约规则等；不入库，从 `.env.example` 复制。
- `frontend/.env`：前端 API 地址与 Mailpit 地址。
- 生产部署请替换所有 `changethis` 占位值，并参考 `deployment-docker-compose.md`。

## 代码规范

项目使用 [prek](https://prek.j178.dev/)（pre-commit 的现代替代品）：

```bash
uv run prek install -f     # 安装 Git hook
uv run prek run --all-files
```

后端同时使用 Ruff 与 mypy（`backend/pyproject.toml`），前端使用 Biome。
