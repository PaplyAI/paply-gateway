# Paply Token Gateway engineering contract

## Non-negotiable rules

1. Fail fast. Missing secrets, invalid model documents, and unavailable upstream services must be visible failures.
2. LiteLLM is the token accounting and budget enforcement data plane. Do not add a second token estimator or spend ledger.
3. Clients authenticate with a Paply login session. Never send a provider key, LiteLLM virtual key, internal service token, or LiteLLM master key to a client.
4. Never log prompts, responses, authorization headers, API keys, or complete request bodies.
5. Public model configuration uses the Paply desktop `schemaVersion: 2` Gateway contract and never contains credentials.
6. Preserve streaming semantics and upstream status codes on OpenAI-compatible routes.
7. Configuration changes must be reviewed with their database, key-rotation, and client-upgrade impact.
8. Protect the mainline. Broad or experimental work belongs on a dedicated branch.

## Runtime architecture

- `gateway` is the Paply-owned FastAPI edge. It serves `/api/models`, the PaplyAI `/api/skills` catalog and artifacts, liveness/readiness endpoints, and streams `/v1/*` to LiteLLM.
- The skills catalog is a desktop compatibility surface, not part of token accounting. Local artifact paths are resolved below the mounted catalog root, symlinks are rejected, and generated downloads must remain under the desktop's 50 MB artifact limit.
- `admin` is the Paply-owned Chinese management UI. Local Compose binds it to loopback port 4390; it is the only Paply service allowed to receive the LiteLLM master key.
- The native LiteLLM UI on port 4000 is shipped from the pinned Paply wrapper image in `Dockerfile.litellm`; its compiled pages receive the checked-in Chinese localization and Paply theme during image build. Never patch a running container manually.
- `litellm` is pinned to the official signed release image and owns provider routing, virtual keys, budgets, rate limits, token counts, and spend logs.
- PostgreSQL is the durable source of truth for LiteLLM users, keys, budgets, and spend.
- Redis is for LiteLLM coordination and rate limiting. It is never the durable usage source of truth.
- The LiteLLM admin port binds to loopback in local Compose. Production ingress must expose only the Paply edge unless an authenticated operator network is explicitly configured.

## Paply desktop contract

- The desktop fetches authenticated `GET /api/models` and accepts chat transports `openai-responses` and `openai-completions` only.
- The same configured Gateway origin supplies `GET /api/skills`; available local catalog entries are materialized as Gateway artifact URLs and local filesystem paths never cross the public API.
- The document contains only model metadata and the public Gateway `/v1` base URL. It never contains provider credentials, LiteLLM credentials, or a Paply session.
- The desktop authenticates `/api/models` and `/v1/*` with a short-lived Paply access token. This is an application login session, not a model API key.
- The edge validates the Paply session, strips caller-supplied internal identity headers, and derives a stable user id. Only the edge may forward that identity to the private LiteLLM listener.
- Gateway-to-LiteLLM calls use one server-only service credential. LiteLLM custom auth maps the trusted user id into its usage and budget records; users are accounting identities, not virtual keys.

## Observability and privacy

- Every edge request receives or preserves an `x-request-id` and emits one structured completion log.
- Logs may contain route, method, status, duration, and request ID only. Query strings are intentionally excluded.
- Provider failures remain observable through status codes and structured errors. The edge does not retry billable LLM requests.
- Health checks never include secret material.

## Validation

- Run `ruff check src tests` and `pytest` for application changes.
- Run `docker compose config` for Compose or environment changes.
- Validate the exact `/api/models` response against the desktop contract whenever its schema changes.
