# Paply Token Gateway

Paply 论文 Agent 的模型网关工程。它以 [LiteLLM Proxy](https://github.com/BerriAI/litellm) 为数据面，负责真实 token 计量、用户/团队预算、限流和 Spend Logs；Paply 自有边缘服务负责登录会话认证、desktop 模型配置协议和 OpenAI 兼容流式入口。

当前基线固定在 LiteLLM 官方签名发布镜像 `ghcr.io/berriai/litellm:v1.96.0`。工程没有 fork 或复制 LiteLLM 源码，后续可独立升级上游版本。

## 架构

```text
Paply Desktop
  ├─ GET /api/models ───────────────┐
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
- Gateway 不记录 prompt、response、Authorization 或请求体。
- `/v1/*` 不自动重试，避免一次客户端请求产生重复计费。

## 本地启动

要求 Docker Compose v2、Python 3.12（仅本地脚本/测试需要）。

本地默认假设 `paply-litellm` 与 `paplyai-skills-catalog` 两个仓库同级放置；若目录不同，通过 `PAPLY_SKILLS_CATALOG_HOST_PATH` 指向技能目录仓库。

```bash
cp .env.example .env
# 编辑 .env，替换所有 change-me，并填写真实 provider key
docker compose up -d --build
curl http://127.0.0.1:4387/health/ready
```

Paply 中文管理台仅绑定本机：<http://127.0.0.1:4390>。登录账号由 `.env` 的 `PAPLY_ADMIN_USERNAME` / `PAPLY_ADMIN_PASSWORD` 配置。已汉化的 LiteLLM 原生高级运维后台位于 <http://127.0.0.1:4000/ui>，由单独的 `LITELLM_UI_USERNAME` / `LITELLM_UI_PASSWORD` 登录。对外客户端入口是 <http://127.0.0.1:4387>。

## 创建测试用户与登录会话

```bash
LITELLM_MASTER_KEY='你的管理密钥' \
  python scripts/create_test_user.py user_01 \
  --alias paply-user-01 \
  --max-budget 20 \
  --budget-duration 30d \
  --tpm-limit 100000 \
  --rpm-limit 60

docker exec "$(docker compose ps -q gateway)" \
  python scripts/create_access_token.py user_01 --hours 24
```

第一个脚本只创建 LiteLLM 计量用户，并明确设置 `auto_create_key=false`；第二个脚本在 Gateway 容器内签发开发测试用的短期 Paply 会话。二者都不创建或下发模型 API Key。正式环境应由 Paply 账号服务签发和刷新会话。

可在 LiteLLM 管理界面查看：

- 每个 User/Team 的 prompt、completion 和总 token；
- 按模型、时间、用户聚合的 spend；
- 预算消耗、软/硬限制和重置周期；
- 失败请求、延迟和 provider 路由状态。

## 与 paply-desktop 对接

Gateway 模型协议为 `schemaVersion: 2`。`/api/models` 与 `/v1/*` 都使用同一个 Paply 登录会话；模型文档中没有 `apiKey`。当前开发桥从主进程环境读取短期会话：

```bash
PAPLYAI_GATEWAY_ACCESS_TOKEN='<上一步签发的短期会话>' npm start
```

然后在 desktop 的“开发者选项 → API Gateway 地址”填写 `http://127.0.0.1:4387`，并启用本地 HTTP 调试开关。生产必须使用 HTTPS，并由账号登录流程把可刷新会话保存在主进程安全存储中。

整体职责与请求链路见 [docs/gateway-architecture.md](docs/gateway-architecture.md)，详细客户端迁移契约见 [docs/desktop-integration.md](docs/desktop-integration.md)，部署和密钥运维见 [docs/operations.md](docs/operations.md)。

## 开发验证

```bash
python -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/ruff check src tests scripts
.venv/bin/pytest
cp .env.example .env
docker compose config --quiet
```

## 配置入口

- `config/litellm.yaml`：公开模型别名到上游 provider 模型的路由。
- `config/paply-models.yaml`：下发给 desktop 的模型能力元数据，不含任何密钥。
- `PAPLY_CHAT_*` / `PAPLY_VISION_*` / `PAPLY_IMAGE_*`：三类能力可分别配置兼容上游的模型、Base URL 与 API Key，公开别名保持稳定。
- `PAPLY_SKILLS_CATALOG_HOST_PATH`：只读挂载 PaplyAI 官方技能目录，由 Gateway 输出远程可下载的目录协议。
- `.env`：provider、数据库、Redis 和管理密钥；永不提交。
- `compose.yaml`：本地单节点拓扑。生产应使用托管 PostgreSQL/Redis、TLS ingress 和独立备份策略。

LiteLLM 官方资料：[Docker 快速开始](https://docs.litellm.ai/docs/proxy/docker_quick_start)、[Custom Auth](https://docs.litellm.ai/docs/proxy/custom_auth)、[成本追踪](https://docs.litellm.ai/docs/proxy/cost_tracking)。
