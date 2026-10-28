# NexaSlot — Docker Compose 部署

使用 Docker Compose 将项目部署到自有服务器。部署配置包含 Traefik，用于 HTTPS 与流量路由。

## 准备

- 一台可用的 Linux 服务器。
- DNS 已指向服务器的应用域名与 Adminer 子域名，例如 `nexaslot.example.com` 与 `adminer.nexaslot.example.com`。
- 服务器已安装 Docker Engine（非 Docker Desktop）。

## 复制代码

```bash
rsync -av --exclude=".git/" --filter=":- .gitignore" ./ root@your-server.example.com:/root/code/app/
```

## 配置环境变量

```bash
export DOMAIN=nexaslot.example.com
export PROJECT_NAME="NexaSlot"
export FIRST_SUPERUSER=admin@example.com
```

可选配置：

- `SMTP_HOST`、`SMTP_USER`、`EMAILS_FROM_EMAIL`：邮件发送。
- `SENTRY_DSN`：Sentry 监控。
- `BOOKING_*`：预约规则，详见 README。

## 密钥

```bash
export MYSQL_ROOT_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MYSQL_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export FIRST_SUPERUSER_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

如使用带认证的邮件服务，再设置 `SMTP_PASSWORD`。

## 部署

```bash
cd /root/code/app/
docker compose -f compose.yml -f compose.deploy.yml build
docker compose -f compose.yml -f compose.deploy.yml run --rm backend bash scripts/prestart.sh
docker compose -f compose.yml -f compose.deploy.yml up -d
```

`compose.deploy.yml` 在共享的 `compose.yml` 之上追加 HTTPS 与证书配置；显式列出两个文件可排除本地的 `compose.override.yml`。

后端镜像会构建前端，因此服务器无需安装 Bun。MySQL 与 Redis 数据分别保存在 `app-db-data`、`app-redis-data` 卷中。

## GitHub Actions 部署

仓库包含 `.github/workflows/deploy-docker-compose.yml`，可在 GitHub Actions 中手动触发部署。

仅在你信任仓库贡献者与工作流代码时使用自托管 Runner。

### 仓库变量与密钥

Variables：`DOMAIN`、`PROJECT_NAME`、`FIRST_SUPERUSER`；可选 `SMTP_HOST`、`SMTP_USER`、`EMAILS_FROM_EMAIL`、`SENTRY_DSN`。

Secrets：`MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`、`SECRET_KEY`、`FIRST_SUPERUSER_PASSWORD`；可选 `SMTP_PASSWORD`。

### 安装自托管 Runner

```bash
sudo adduser github
sudo usermod -aG docker github
sudo su - github
```

在仓库 **Settings → Actions → Runners** 中选择 **New self-hosted runner**，按提示安装到 `/home/github/actions-runner`，然后：

```bash
exit
cd /home/github/actions-runner
sudo ./svc.sh install github
sudo ./svc.sh start
sudo ./svc.sh status
```

### 执行部署

在仓库 **Actions** 中选择 **Deploy with Docker Compose**，点击 **Run workflow**。

## 访问地址

- 应用（前端与 API）：`https://nexaslot.example.com`
- API 文档：`https://nexaslot.example.com/docs`
- Adminer：`https://adminer.nexaslot.example.com`
