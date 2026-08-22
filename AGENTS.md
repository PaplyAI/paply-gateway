# PaplyAI Gateway engineering contract

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

- `gateway` is the Paply-owned FastAPI edge. It owns the internal-pilot account registration/login/refresh/logout API, persists password hashes and hashed refresh sessions in its SQLite volume, serves `/api/models`, the PaplyAI `/api/skills` catalog and artifacts, liveness/readiness endpoints, and streams `/v1/*` to LiteLLM. Image generation/edit calls still pass through LiteLLM for accounting; the edge may buffer their small JSON responses only to materialize provider result URLs as OpenAI-compatible `b64_json` for Desktop.
- The skills catalog is sourced from the sibling `PaplyAI/paplyai-skills`
  repository and is not part of token accounting. Every current ID must use
  `paplyai-*`; `replaces` is the only protocol field for retired managed IDs.
  Catalog and artifact endpoints require the same Paply login session as model
  configuration. Local artifact paths are resolved below the mounted catalog
  root, symlinks are rejected, and generated downloads must remain under the
  desktop's 50 MB artifact limit. The Gateway strictly validates and publicly
  forwards skill kind, category, display order, localized `zh`/`en` display
  copy, Desktop built-in capability requirements, and acyclic canonical skill
  composition. It never invents or
  hard-codes product skill grouping independently of the skills repository.
  `image-engine` is the single catalog capability ID for Desktop image
  recognition and generation, while `/api/models` still delivers separate
  `vision` and `imageGen` providers.
  Skills absorbed into the product are removed from `skills` and exposed only
  through top-level `retiredSkillIds`, allowing Desktop to archive existing
  managed installations without inventing retirement state locally.
- `admin` is the Paply-owned Chinese management UI. Local Compose binds it to loopback port 4390; it is the only Paply service allowed to receive the LiteLLM master key. Overview, users, models, and system status are separate routes. It is the daily control surface for LiteLLM deployments and user budgets; provider secrets are write-only and must never be rendered or stored in the browser session.
- The admin SPA lives in `admin-ui/` and is derived from Octopus at the exact commit recorded in `admin-ui/UPSTREAM.md`. That frontend subtree remains AGPL-3.0-only; Paply branding, session authentication, JSON control-plane APIs, and write-only provider-secret handling are Paply-owned adaptations. Build it into `web/static/admin-app`; never serve the Octopus API-key authentication or product branding.
- The native LiteLLM UI on port 4000 is shipped from the pinned Paply wrapper image in `Dockerfile.litellm`; its compiled pages receive the checked-in Chinese localization and Paply theme during image build. Never patch a running container manually.
- The pinned wrapper also loads `config/litellm_dashscope_image_edit.py`: v1.96.0 already supports DashScope Qwen-Image generation but not edits, so the compatibility module adds the missing JSON edit transform and corrects the provider's `n` parameter mapping. Keep it isolated, covered by container smoke tests, and remove it when a reviewed LiteLLM upgrade provides equivalent behavior.
- The pinned wrapper applies `scripts/patch_litellm_session_affinity.py` to LiteLLM v1.96.0 at image build. Upstream session affinity silently returns to the healthy deployment pool when the pinned deployment is unavailable; Paply must instead return no eligible deployment so a stateful Responses turn fails visibly rather than crossing providers. The patch asserts the exact upstream source shape and must fail the image build after an incompatible LiteLLM upgrade.
- `litellm` is pinned to the official signed release image and owns provider routing, virtual keys, budgets, rate limits, token counts, and spend logs.
- Upstream deployments are owned by LiteLLM's PostgreSQL-backed control plane and are managed through the Paply admin's validated LiteLLM API calls. The native LiteLLM UI remains an advanced diagnostic escape hatch. `config/litellm.yaml` must not contain production provider deployments or credentials. Multiple deployments sharing a `paply-*` model name form that alias's load-balancing pool. New `paply-chat` sessions load-balance, but every turn in one session is pinned to the same deployment through LiteLLM session affinity; never fail over a stateful Responses turn to another provider.
- PostgreSQL is the durable source of truth for LiteLLM users, keys, budgets, and spend.
- Redis is for LiteLLM coordination, rate limiting, and the append-only 30-day `paply-chat` affinity map. It is never the durable usage source of truth.
- The LiteLLM admin port binds to loopback in local Compose. Production ingress must expose only the Paply edge unless an authenticated operator network is explicitly configured.

## Paply desktop contract

- The desktop fetches authenticated `GET /api/models` and accepts chat transports `openai-responses` and `openai-completions` only.
- The same configured Gateway origin supplies authenticated `GET /api/skills`
  and artifact downloads; available local catalog entries are materialized as
  same-origin Gateway artifact URLs and local filesystem paths never cross the
  public API.
- The document contains only model metadata and the public Gateway `/v1` base URL. It never contains provider credentials, LiteLLM credentials, or a Paply session.
- The desktop authenticates `/api/models` and `/v1/*` with a short-lived Paply access token. This is an application login session, not a model API key.
- Registration provisions one stable LiteLLM user with `auto_create_key=false`; it never creates a client virtual key. The desktop encrypts the refresh token in the OS keychain-backed Electron safe storage and keeps the access token in the main process only.
- The edge validates the Paply session, strips caller-supplied internal identity and LiteLLM affinity headers, and derives a stable user id. It also HMACs the validated Paply session ID together with that user ID before forwarding `x-litellm-session-id`. Only the edge may forward either trusted value to the private LiteLLM listener.
- Gateway-to-LiteLLM calls use one server-only service credential. LiteLLM custom auth maps the trusted user id into its usage and budget records; users are accounting identities, not virtual keys.

## Observability and privacy

- Every edge request receives or preserves an `x-request-id` and emits one structured completion log.
- Logs may contain route, method, status, duration, and request ID only. Query strings are intentionally excluded.
- Provider failures remain observable through status codes and structured errors. The edge does not retry billable LLM requests.
- Health checks never include secret material.
- Gateway readiness authenticates to LiteLLM with the internal service credential and must fail when any public model alias from `paply-models.yaml` is absent; process liveness alone is not readiness.

## Validation

- Run `ruff check src tests` and `pytest` for application changes.
- Run `docker compose config` for Compose or environment changes.
- Validate the exact `/api/models` response against the desktop contract whenever its schema changes.
