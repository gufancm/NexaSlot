# NexaSlot — 智能资源预约与调度平台

NexaSlot 是一个面向**资源预约与调度**的全栈平台。当前为第一版基础骨架：包含账号体系、权限管理与基础数据管理能力，后续将逐步扩展预约、排期、资源调度等核心业务。

## 技术栈

| 层级 | 选型 |
| --- | --- |
| 后端 | Python 3.14、FastAPI、SQLModel、PostgreSQL、Alembic |
| 前端 | React 19、TypeScript、Vite、Tailwind CSS、shadcn/ui |
| 数据请求 | TanStack Query + 自动生成的 OpenAPI 客户端 |
| 鉴权 | JWT（OAuth2 密码模式） |
| 测试 | Pytest（后端）、Playwright（前端端到端） |
| 本地依赖 | Docker Compose（PostgreSQL + Mailpit） |

## 目录结构

```text
backend/              后端应用、Alembic 迁移与测试
frontend/             前端应用（构建产物输出到 backend/app/frontend）
packages/react-email/ 邮件模板源码
compose.yml           本地与部署的容器编排
```

## 本地运行

前置：已安装 `uv`、`bun` 与 Docker。

1. 启动依赖服务（PostgreSQL 映射到宿主机 5433，Mailpit 为 1025/8025）：

   ```bash
   docker compose up -d db mailpit
   ```

2. 准备配置并启动后端（首次需同步依赖并初始化数据库）：

   ```bash
   cp .env.example .env
   cd backend
   uv sync
   uv run alembic upgrade head
   uv run python app/initial_data.py
   uv run fastapi dev --port 8001
   ```

3. 启动前端（另开一个终端）：

   ```bash
   bun install
   bun run dev
   ```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8001/docs |
| 邮件测试（Mailpit） | http://localhost:8025 |

默认管理员账号见 `.env`：`admin@example.com` / `changethis`（首次部署请务必修改）。

## 配置说明

本地配置位于 `.env`（后端）与 `frontend/.env`（前端）。`.env` 不入库，首次运行请从示例复制：`cp .env.example .env`。生产部署前请务必替换 `SECRET_KEY`、`POSTGRES_PASSWORD`、`FIRST_SUPERUSER_PASSWORD` 等 `changethis` 占位值。

## 仓库

<https://github.com/gufancm/NexaSlot>
