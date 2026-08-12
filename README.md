# Paply Token Gateway

Paply 论文 Agent 的模型网关工程。它以 [LiteLLM Proxy](https://github.com/BerriAI/litellm) 为数据面，负责真实 token 计量、Virtual Key、用户/团队预算、限流和 Spend Logs；Paply 自有的轻量边缘服务负责 desktop 模型配置协议和 OpenAI 兼容流式入口。

当前基线固定在 LiteLLM 官方签名发布镜像 `ghcr.io/berriai/litellm:v1.96.0`。工程没有 fork 或复制 LiteLLM 源码，后续可独立升级上游版本。

## 架构

```text
Paply Desktop
  ├─ GET /api/models ───────────────┐
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
- 每个用户使用独立 Virtual Key，预算、模型白名单和速率限制都绑定该 Key/User。
- provider key 和 LiteLLM master key 只存在于服务端。
- Gateway 不记录 prompt、response、Authorization 或请求体。
- `/v1/*` 不自动重试，避免一次客户端请求产生重复计费。

## 本地启动

要求 Docker Compose v2、Python 3.12（仅本地脚本/测试需要）。

```bash
cp .env.example .env
# 编辑 .env，替换所有 change-me，并填写真实 provider key
docker compose up -d --build
curl http://127.0.0.1:4387/health/ready
```

LiteLLM 管理端仅绑定本机：<http://127.0.0.1:4000/ui>。使用 `.env` 中的 `LITELLM_MASTER_KEY` 登录。对外客户端入口是 <http://127.0.0.1:4387>。

## 创建用户 Virtual Key

```bash
LITELLM_MASTER_KEY='你的管理密钥' \
  python scripts/create_user_key.py user_01 \
  --alias paply-user-01 \
  --max-budget 20 \
  --budget-duration 30d
```

脚本只输出一次创建结果，不写入仓库或 `.env`。`user_id` 应使用 Paply 内部稳定 ID，不要使用邮箱或其他个人信息。

可在 LiteLLM 管理界面查看：

- 每个 Key/User/Team 的 prompt、completion 和总 token；
- 按模型、时间、用户聚合的 spend；
- 预算消耗、软/硬限制和重置周期；
- 失败请求、延迟和 provider 路由状态。

## 与 paply-desktop 对接

当前 desktop 已能从 `Gateway 地址 + /api/models` 拉取模型文档，但尚未给该请求附带用户身份。因此有两种模式：

1. 正式模式：`GET /api/models` 携带 `Authorization: Bearer <user virtual key>`。Gateway 会先向 LiteLLM 验证 Key，再把同一 Key 和公共 `/v1` 地址写入模型文档。这是逐用户计量的目标模式。
2. 兼容模式：在非生产环境设置 `PAPLY_MODELS_BOOTSTRAP_KEY`。当前 desktop 可匿名拉取配置，但所有客户端共用一个用量身份，只适合本地或受控 pilot。`PAPLY_ENVIRONMENT=production` 会拒绝这种配置并启动失败。

本地兼容调试：

```bash
# 先通过上面的脚本创建一个 pilot Virtual Key
# 将它写入本地 .env 的 PAPLY_MODELS_BOOTSTRAP_KEY（.env 已被 gitignore）
docker compose up -d --build gateway
```

然后在 desktop 的“开发者选项 → API Gateway 地址”填写 `http://127.0.0.1:4387`，并启用 desktop 的本地 HTTP 调试开关。生产必须使用 HTTPS。

详细客户端迁移契约见 [docs/desktop-integration.md](docs/desktop-integration.md)，部署和密钥运维见 [docs/operations.md](docs/operations.md)。

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
- `.env`：provider、数据库、Redis 和管理密钥；永不提交。
- `compose.yaml`：本地单节点拓扑。生产应使用托管 PostgreSQL/Redis、TLS ingress 和独立备份策略。

LiteLLM 官方资料：[Docker 快速开始](https://docs.litellm.ai/docs/proxy/docker_quick_start)、[Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys)、[成本追踪](https://docs.litellm.ai/docs/proxy/cost_tracking)。

