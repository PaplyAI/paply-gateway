# Operations and usage management

## Public and private surfaces

Public production ingress should expose only:

- `GET /health/live`
- `GET /health/ready` (optionally restricted to health-check networks)
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/models`
- `GET /api/skills`
- `GET /api/skills/{skill-id}/artifact`
- the required `/v1/*` OpenAI-compatible routes

LiteLLM port `4000`, `/ui`, master-key endpoints, PostgreSQL, and Redis belong on the operator network. Local Compose binds LiteLLM to `127.0.0.1` by default and does not publish either database. A temporary IP-and-port operator setup may set `PAPLY_LITELLM_UI_BIND_ADDRESS=0.0.0.0` and `PAPLY_LITELLM_UI_PUBLIC_URL=http://<server-ip>:4000`; do not expose PostgreSQL or Redis. Move this endpoint behind HTTPS before any non-temporary deployment.

## User accounting model

Use a stable opaque Paply account ID as LiteLLM `user_id`; do not issue a LiteLLM key to the client. Set on the user record:

- `models` to the Paply aliases the user may call;
- `max_budget` and `budget_duration` for hard spend control;
- team membership for organizational budgets;
- TPM/RPM limits where abuse control is required.

The desktop main process holds only a short-lived Paply access session and an
OS-encrypted refresh token. The internal pilot stores accounts and hashed
refresh sessions in the `gateway_accounts` SQLite volume. Back up that volume
with PostgreSQL; move identity to Paply's shared account service before public
launch. Revoking a login session does not rotate any LiteLLM or provider
credential.

LiteLLM's PostgreSQL spend logs are authoritative. Dashboards and exports should read through supported LiteLLM management APIs/UI rather than coupling Paply code to LiteLLM's internal Prisma table layout.

The Paply management dashboard reads the latest 30-day prompt, completion, and total token aggregates from LiteLLM's usage API. It must not calculate tokens from request text. The edge strips caller-supplied internal identity headers and derives the LiteLLM user from the verified session.

## Provider routing on a mainland China host

Chat, vision, and image generation deployments are maintained in LiteLLM's PostgreSQL-backed native control plane. The desktop continues to use the stable `paply-chat`, `paply-vision`, and `paply-image` aliases. Add multiple deployments with the same alias for load balancing. The checked-in Router strategy is `simple-shuffle`: without capacity metadata it distributes requests randomly; numeric `weight`, RPM, or TPM values configured per deployment in LiteLLM refine the split. Before enabling a deployment, verify from the target host that the upstream is reachable and that its selected LiteLLM provider adapter supports the corresponding Responses, Chat Completions, or Images route.

Provider credentials stay only in the `litellm` container. Do not put a domestic provider key into `config/paply-models.yaml`, a desktop setting, or the public Gateway response.

Legacy deployments marked `Defined in config` must be migrated before removing
the static `model_list`. Run `scripts/migrate_static_models.py` without
`--apply`, review the plan, take a PostgreSQL backup, run it again with
`--apply`, and verify that `/model/info` reports `model_info.db_model=true` for
all three Paply aliases. Only then deploy the empty `model_list`. Never delete
or rotate `LITELLM_SALT_KEY` during this migration because LiteLLM uses it to
encrypt provider credentials in PostgreSQL.

## Secrets

- `LITELLM_MASTER_KEY`: operator authentication. Rotate through a planned maintenance procedure.
- `LITELLM_SALT_KEY`: encryption root for values stored by LiteLLM. Back it up securely and keep it stable; changing it can make stored encrypted values unreadable.
- `PAPLY_AUTH_JWT_SECRET`: signs development Paply access tokens; production should use the account service's managed signing keys.
- `gateway_accounts` volume: contains password hashes and hashed refresh sessions; protect and back it up as identity data.
- `PAPLY_LITELLM_SERVICE_TOKEN`: authenticates only the edge-to-LiteLLM hop and never leaves the server network.
- provider API keys: server-side only and independently rotatable.
- `POSTGRES_PASSWORD` and `REDIS_PASSWORD`: unique production secrets, supplied by the deployment secret manager.
- Paply access tokens: short-lived client sessions. Never include them in logs, crash reports, query strings, model documents, or analytics.

The committed `.env.example` contains placeholders only. CI and production must inject real values from their secret manager.

## Backups and recovery

Back up PostgreSQL on a defined schedule and test restore into an isolated environment. Redis persistence helps local recovery but does not replace PostgreSQL backups. A restore test should verify:

1. users, teams, budgets, and operator credentials are present;
2. spend aggregates reconcile with a pre-backup sample;
3. encrypted provider configuration remains readable with the backed-up salt key;
4. blocked users and revoked operator credentials remain blocked/revoked.

## Upgrades

LiteLLM is pinned to `v1.96.0`, whose release publishes a signed GHCR image. For an upgrade:

1. review release notes and database migrations;
2. verify the image signature using LiteLLM's published cosign key;
3. back up PostgreSQL;
4. test `/v1/responses`, `/v1/chat/completions`, image generation, streaming usage, key budgets, and `/api/models` in staging;
5. deploy one controlled environment and observe request/error/spend reconciliation before broad rollout.

Never switch production to a floating `main` or `latest` image.

## Incident signals

- `/health/live` failing means the Paply edge process is unavailable.
- `/health/ready` failing means the account store or LiteLLM is unavailable, or one of the public model aliases delivered to desktop is missing from LiteLLM.
- `/api/models` `401` means missing, expired, or invalid user identity.
- `/api/models` `503` means validation could not be completed; clients must not reuse the response as if refresh succeeded.
- `/v1/*` `502` means the edge could not establish a LiteLLM request.
- Provider errors preserve their LiteLLM status and should be correlated using `x-request-id`.

Logs intentionally exclude query strings, prompts, responses, tool payloads, and credentials.
