# PaplyAI Gateway Admin UI

PaplyAI Gateway 的 React 19 + TypeScript + Vite 管理前端。界面结构与基础组件派生自 Octopus；固定上游提交、修改范围和许可证见 [UPSTREAM.md](UPSTREAM.md) 与 [LICENSE](LICENSE)。

本地开发：

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Vite 默认监听 `http://localhost:5173`，并将 `/api` 代理到 `http://127.0.0.1:4390`。可通过 `VITE_PROXY_TARGET` 指向其他 PaplyAI Gateway 管理服务。

生产构建：

```bash
pnpm run lint
pnpm run build
```

构建产物输出到 `../web/static/admin-app`，由 FastAPI 管理服务通过 `/static/admin-app/` 提供。该输出目录不提交 Git，Dockerfile 会在 Node 构建阶段生成并复制到最终 Python 镜像。

浏览器只保存 HttpOnly 管理会话 Cookie。CSRF token 仅保存在内存中；Provider API Key 只允许写入，不允许从 API 或页面读取。
