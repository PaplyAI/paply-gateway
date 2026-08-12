# Paply Token Gateway engineering contract

## Non-negotiable rules

1. Fail fast. Missing secrets, invalid model documents, and unavailable upstream services must be visible failures.
2. LiteLLM is the token accounting and budget enforcement data plane. Do not add a second token estimator or spend ledger.
3. Every production user or tenant uses a LiteLLM virtual key. Never send the LiteLLM master key to a client.
4. Never log prompts, responses, authorization headers, API keys, or complete request bodies.
5. Public model configuration must stay compatible with the Paply desktop `schemaVersion: 1` Gateway contract.
6. Preserve streaming semantics and upstream status codes on OpenAI-compatible routes.
7. Configuration changes must be reviewed with their database, key-rotation, and client-upgrade impact.
8. Protect the mainline. Broad or experimental work belongs on a dedicated branch.

## Runtime architecture

- `gateway` is the Paply-owned FastAPI edge. It serves `/api/models`, liveness/readiness endpoints, and streams `/v1/*` to LiteLLM.
- `admin` is the Paply-owned Chinese management UI. Local Compose binds it to loopback port 4390; it is the only Paply service allowed to receive the LiteLLM master key.
- The native LiteLLM UI on port 4000 is shipped from the pinned Paply wrapper image in `Dockerfile.litellm`; its compiled pages receive the checked-in Chinese localization and Paply theme during image build. Never patch a running container manually.
- `litellm` is pinned to the official signed release image and owns provider routing, virtual keys, budgets, rate limits, token counts, and spend logs.
- PostgreSQL is the durable source of truth for LiteLLM users, keys, budgets, and spend.
- Redis is for LiteLLM coordination and rate limiting. It is never the durable usage source of truth.
- The LiteLLM admin port binds to loopback in local Compose. Production ingress must expose only the Paply edge unless an authenticated operator network is explicitly configured.

## Paply desktop contract

- The desktop fetches `GET /api/models` and accepts chat transports `openai-responses` and `openai-completions` only.
- The document contains the caller's virtual key and the public Gateway `/v1` base URL; it must never contain provider credentials or the LiteLLM master key.
- Production `/api/models` requires a Bearer virtual key and validates it through LiteLLM `/key/info` before returning configuration. This must reject the LiteLLM master key.
- `PAPLY_MODELS_BOOTSTRAP_KEY` is an explicit compatibility bridge for the current desktop build, which does not yet attach authorization to the model-config fetch. It is for local development or a tightly controlled pilot only, because all clients using it share one usage identity.
- The production desktop integration must authenticate the model-config request with the signed-in user's virtual key (or exchange a Paply session for one) before per-user accounting is considered complete.

## Observability and privacy

- Every edge request receives or preserves an `x-request-id` and emits one structured completion log.
- Logs may contain route, method, status, duration, and request ID only. Query strings are intentionally excluded.
- Provider failures remain observable through status codes and structured errors. The edge does not retry billable LLM requests.
- Health checks never include secret material.

## Validation

- Run `ruff check src tests` and `pytest` for application changes.
- Run `docker compose config` for Compose or environment changes.
- Validate the exact `/api/models` response against the desktop contract whenever its schema changes.
