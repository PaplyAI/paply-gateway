# Paply Gateway

Paply 论文 Agent 的模型网关工程。它以 [LiteLLM Proxy](https://github.com/BerriAI/litellm) 为数据面，负责真实 token 计量、用户/团队预算、限流和 Spend Logs；Paply 自有边缘服务负责登录会话认证、desktop 模型配置协议和 OpenAI 兼容流式入口。

当前基线固定在 LiteLLM 官方签名发布镜像 `ghcr.io/berriai/litellm:v1.96.0`。工程没有 fork 或复制 LiteLLM 源码，后续可独立升级上游版本。

## 架构

```text
Paply Desktop
  ├─ 注册 / 登录 / 刷新会话 ─────────┐
  ├─ GET /api/models ───────────────┤
  ├─ GET /api/skills + artifacts ───┤
  └─ /v1/responses | chat | images ─┤
                                     ▼
                              Paply FastAPI Edge
                                     │ streaming, no retry
                                     ▼
                                LiteLLM Proxy
                                  │        │
                         usage / budgets   rate limits
                                  ▼        ▼
                              PostgreSQL  Redis
```

关键原则：

- token 与费用以 LiteLLM 记录的 provider usage 为准，不在 Paply 层重复估算。
- 用户是计量身份，不是一把客户端模型 Key；预算、模型白名单和速率限制绑定稳定 `user_id`。
- 客户端只持有短期 Paply 登录会话。provider key、LiteLLM key 和内部服务凭证只存在于服务端。
- 用户注册时自动创建稳定的 LiteLLM 计量用户，并强制 `auto_create_key=false`；账号、密码和模型密钥不会写进客户端配置。
- Gateway 不记录 prompt、response、Authorization 或请求体。
- `/v1/*` 不自动重试，避免一次客户端请求产生重复计费。

## 本地启动

要求 Docker Compose v2、Python 3.12（仅本地脚本/测试需要）。Docker 镜像会在独立 Node 构建阶段编译管理前端，不要求宿主机安装 Node。

本地默认假设 `paply-gateway` 与 `paplyai-skills-catalog` 两个仓库同级放置；若目录不同，通过 `PAPLY_SKILLS_CATALOG_HOST_PATH` 指向技能目录仓库。

```bash
cp .env.example .env
# 编辑 .env，替换所有 change-me；启动后在 Paply Gateway 管理台添加模型节点
docker compose up -d --build
curl http://127.0.0.1:4387/health/ready
```

Paply 中文管理台默认仅绑定本机：<http://127.0.0.1:4390>。登录账号由 `.env` 的 `PAPLY_ADMIN_USERNAME` / `PAPLY_ADMIN_PASSWORD` 配置。管理台包含独立的用量概览、用户与预算、模型配置和系统状态页面；模型页面可以新增、编辑、启停、测试和删除 LiteLLM deployment，同一公开模型名下的多个节点组成负载均衡池。API Key 只在创建或轮换时提交，不会回显到页面。

LiteLLM 原生高级运维后台默认位于 <http://127.0.0.1:4000/ui>，由单独的 `LITELLM_UI_USERNAME` / `LITELLM_UI_PASSWORD` 登录，仅作为高级诊断入口。临时通过 IP 和端口开放该入口时，将 `PAPLY_LITELLM_UI_BIND_ADDRESS=0.0.0.0` 和 `PAPLY_LITELLM_UI_PUBLIC_URL=http://<server-ip>:4000` 一并设置；Paply 管理台的系统状态页会显示跳转入口。对外客户端入口是 <http://127.0.0.1:4387>。

## 内部账号注册与登录

```bash
curl -X POST http://127.0.0.1:4387/api/auth/register \
  -H 'content-type: application/json' \
  -d '{"displayName":"测试同事","email":"tester@example.com","password":"至少八位密码"}'
```

Desktop 已内置相同流程：用户只看到注册和登录页，成功后自动获取模型配置并进入产品。Gateway 签发短期访问会话和可轮换刷新会话；注册同时建立 LiteLLM 计量用户，但不创建或下发模型 API Key。当前 SQLite 账号库用于内部体验，正式上线前应迁移到 Paply 统一账号服务。

可在 LiteLLM 管理界面查看：

- 每个 User/Team 的 prompt、completion 和总 token；
- 按模型、时间、用户聚合的 spend；
- 预算消耗、软/硬限制和重置周期；
- 失败请求、延迟和 provider 路由状态。

## 与 paply-desktop 对接

Gateway 模型协议为 `schemaVersion: 2`。`/api/models` 与 `/v1/*` 都使用同一个 Paply 登录会话；模型文档中没有 `apiKey`。Desktop 内置内部 Gateway 地址，产品用户无需填写地址、Token 或 SK。主进程用 Electron `safeStorage` 加密保存刷新会话，短期访问会话仅保留在主进程内存中。工程测试可用 `PAPLYAI_GATEWAY_BASE_URL` 覆盖地址；正式上线前必须切换 HTTPS 域名。

整体职责与请求链路见 [docs/gateway-architecture.md](docs/gateway-architecture.md)，详细客户端迁移契约见 [docs/desktop-integration.md](docs/desktop-integration.md)，部署和密钥运维见 [docs/operations.md](docs/operations.md)。

## 开发验证

```bash
cd admin-ui
pnpm install --frozen-lockfile
pnpm run lint
pnpm run build
cd ..
python -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/ruff check src tests scripts
.venv/bin/python -m pytest
cp .env.example .env
docker compose config --quiet
```

管理前端位于 `admin-ui/`，生产构建输出到 `web/static/admin-app/`（该目录不提交 Git）。其 Octopus 上游提交、修改范围与 AGPL-3.0 源码许可见 `admin-ui/UPSTREAM.md` 和 `admin-ui/LICENSE`。

## 配置入口

- `config/litellm.yaml`：LiteLLM 的认证、数据库、Redis 和 Router 基础配置；上游 deployment 不写入该文件。
- `config/paply-models.yaml`：下发给 desktop 的模型能力元数据，不含任何密钥。
- Paply Gateway 管理台：日常维护上游模型、Base URL、API Key、权重、启停与 RPM/TPM；所有变更通过 LiteLLM 管理 API 写入 PostgreSQL，同一 `paply-*` 公开别名下的多个 deployment 由 LiteLLM Router 负载均衡。
- LiteLLM 原生控制台：仅用于 Paply 管理台尚未覆盖的高级诊断和底层能力。
- `PAPLY_SKILLS_CATALOG_HOST_PATH`：只读挂载 PaplyAI 官方技能目录，由 Gateway 输出远程可下载的目录协议。
- `.env`：数据库、Redis、服务认证和管理密钥；永不提交 provider key。
- `compose.yaml`：本地单节点拓扑。生产应使用托管 PostgreSQL/Redis、TLS ingress 和独立备份策略。

LiteLLM 官方资料：[Docker 快速开始](https://docs.litellm.ai/docs/proxy/docker_quick_start)、[Custom Auth](https://docs.litellm.ai/docs/proxy/custom_auth)、[成本追踪](https://docs.litellm.ai/docs/proxy/cost_tracking)。

已有环境从静态 deployment 迁移时，先保留旧 `.env` 中的 `PAPLY_CHAT_*`、
`PAPLY_VISION_*`、`PAPLY_IMAGE_*` 和 provider key，运行只读预检：

```bash
set -a
. ./.env
set +a
python3 scripts/migrate_static_models.py
python3 scripts/migrate_static_models.py --apply
```

脚本确认数据库 deployment 后，才可部署空 `model_list` 的新配置并重建 LiteLLM。
迁移后的 provider key 可从 `.env` 删除；`LITELLM_SALT_KEY` 必须保持不变。
