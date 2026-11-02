# NexaSlot — Nginx + Certbot 生产部署

生产环境使用 Docker Compose 运行 MySQL、Redis、FastAPI、Worker、Nginx 与 Certbot。Nginx 是唯一公网入口，FastAPI 只监听容器内网 `8000`，MySQL 与 Redis 不对公网映射端口。

```text
Internet
   |
   v
Nginx :80 / :443  --- Certbot Webroot
   |
   v
FastAPI :8000  ---> MySQL
   |                 Redis
   +--> Worker  -----> MySQL / Redis
```

## 1. 前置条件

- Linux 服务器已安装 Docker Engine 与 Compose 插件，当前用户可执行 `docker compose`。
- 防火墙放行 `80/tcp` 与 `443/tcp`。
- 应用域名 A/AAAA 记录已经指向服务器，例如 `gcm.cc.cd`。
- 服务器可访问 Let's Encrypt；域名解析在申请证书前必须生效。

## 2. 获取代码

```bash
git clone https://github.com/gufancm/NexaSlot.git
cd NexaSlot
cp .env.example .env
chmod 600 .env
```

`.env`、数据库卷、Redis 卷和证书卷都不应提交到 Git。

## 3. 配置环境变量

在 `.env` 中至少替换以下占位值，并追加生产入口配置：

```dotenv
PROJECT_NAME=NexaSlot
SECRET_KEY=<随机长字符串>
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=<强密码>
MYSQL_ROOT_PASSWORD=<强密码>
MYSQL_USER=nexaslot
MYSQL_PASSWORD=<强密码>

# 生产 Compose / Nginx / Certbot
DOMAIN=gcm.cc.cd
CERTBOT_EMAIL=admin@example.com
WEB_CONCURRENCY=4
```

可用以下命令生成随机密钥：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

可选配置：

- `SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD`、`EMAILS_FROM_EMAIL`：邮件发送。
- `SENTRY_DSN`：Sentry 监控。
- `AI_ENABLED=true`、`LLM_PROVIDER=openai`、`LLM_API_KEY=...`：启用 OpenAI-compatible 自然语言预约；密钥只放在服务器环境变量中。
- `BOOKING_*`、`CACHE_*`、`RATE_LIMIT_*`、`OUTBOX_*`：预约规则、缓存、限流与异步事件参数。

## 4. 首次部署

首次部署时还没有 Let's Encrypt 证书。Nginx 启动脚本会自动生成 30 天临时自签名证书，使容器可以正常启动；Certbot 随后通过 HTTP-01 Webroot 申请正式证书。

```bash
export DOMAIN=gcm.cc.cd

docker compose -f compose.yml -f compose.deploy.yml build
docker compose -f compose.yml -f compose.deploy.yml run --rm backend bash scripts/prestart.sh
docker compose -f compose.yml -f compose.deploy.yml up -d
```

确认 Nginx 已启动并可通过 HTTP 提供 ACME 校验：

```bash
docker compose -f compose.yml -f compose.deploy.yml ps
docker compose -f compose.yml -f compose.deploy.yml exec nginx nginx -t
curl -I "http://$DOMAIN/.well-known/acme-challenge/"
```

申请证书：

```bash
docker compose -f compose.yml -f compose.deploy.yml run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$CERTBOT_EMAIL" \
  --agree-tos --no-eff-email

docker compose -f compose.yml -f compose.deploy.yml exec nginx nginx -s reload
```

如果 DNS 还未生效，Certbot 会失败。修正 DNS 后重新执行 `certonly` 即可，不要删除业务数据卷。

## 5. 验证

```bash
curl -I "http://$DOMAIN"                  # 应 301 到 HTTPS
curl -fsS "https://$DOMAIN/healthz"        # FastAPI + MySQL 健康检查
curl -fsS "https://$DOMAIN/api/v1/utils/health-check/"
docker compose -f compose.yml -f compose.deploy.yml logs --tail=100 nginx
docker compose -f compose.yml -f compose.deploy.yml logs --tail=100 certbot
```

浏览器打开 `https://$DOMAIN`，验证：

| 验收项 | 预期结果 |
| --- | --- |
| HTTP 访问 | 自动跳转 HTTPS |
| HTTPS 证书 | 域名证书有效，无浏览器警告 |
| React 页面 | 首页与登录页正常加载 |
| 页面刷新 | 前端路由不回退 404 |
| JWT 登录 | 登录、注册、成员邀请正常 |
| 预约 | 创建、取消、候补、AI 推荐正常 |
| Worker | HOLD 到期可释放，Outbox 通知可投递 |
| MySQL | 公网无法直接访问 |
| Redis | 公网无法直接访问 |
| 文件上传 | 不超过 Nginx `client_max_body_size=20m` |

## 6. 证书续期

- `certbot` 容器每 12 小时执行一次 `certbot renew --webroot`。
- `nginx` 容器默认每小时重新检查证书并 `nginx -s reload`，可通过 `CERT_RELOAD_SECONDS` 调整。
- 证书和 ACME 文件分别保存在 `certbot-conf`、`certbot-www` 卷中。
- 手动检查：

```bash
docker compose -f compose.yml -f compose.deploy.yml run --rm --entrypoint certbot certbot certificates
```

## 7. 更新版本

```bash
git pull --ff-only
docker compose -f compose.yml -f compose.deploy.yml build
docker compose -f compose.yml -f compose.deploy.yml run --rm backend bash scripts/prestart.sh
docker compose -f compose.yml -f compose.deploy.yml up -d --remove-orphans
```

`prestart.sh` 会执行 `alembic upgrade head` 并幂等初始化超级管理员。升级前建议备份 MySQL 卷或使用 `mysqldump`。

## 8. 运维与安全边界

- 只有 Nginx 映射宿主机 `80/443`；`backend` 仅 `expose: 8000`，`db`、`redis`、`adminer` 不映射公网端口。
- FastAPI 只信任固定 Nginx 内网地址 `172.31.250.10` 的转发头，启动参数为 `--proxy-headers --forwarded-allow-ips 172.31.250.10`。
- Nginx 设置 HSTS、`X-Content-Type-Options`、`X-Frame-Options`、Referrer Policy 与 20MB 请求体上限。
- 如确需使用 Adminer，请通过 SSH 隧道访问，不要在 Compose 中恢复公网端口。
- 备份卷：`app-db-data`、`app-redis-data`、`certbot-conf`。
- 常用排查命令：

```bash
docker compose -f compose.yml -f compose.deploy.yml ps
docker compose -f compose.yml -f compose.deploy.yml logs -f backend worker nginx
docker compose -f compose.yml -f compose.deploy.yml exec backend python -m app.worker
```

## 9. 本地与生产的区别

本地默认使用 `compose.yml + compose.override.yml`：MySQL/Redis 映射 `3307/6380`，后端映射 `8001`，并启动 Mailpit，方便开发调试。

生产必须显式使用 `compose.yml + compose.deploy.yml`，不要叠加 `compose.override.yml`：

```bash
docker compose -f compose.yml -f compose.deploy.yml up -d
```
