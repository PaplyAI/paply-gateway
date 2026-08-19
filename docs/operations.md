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

LiteLLM port `4000`, `/ui`, master-key endpoints, PostgreSQL, and Redis belong on the operator network. Local Compose binds LiteLLM to `127.0.0.1` and does not publish either database.

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

Chat, vision, and image generation have separate `PAPLY_*_UPSTREAM_MODEL`, `PAPLY_*_API_BASE`, and `PAPLY_*_API_KEY` settings. They may point at different OpenAI-compatible upstreams while the desktop continues to use the stable `paply-chat`, `paply-vision`, and `paply-image` aliases. Before deployment, verify from the target host that each upstream is reachable and that its selected LiteLLM provider adapter supports the corresponding Responses, Chat Completions, or Images route.

Provider credentials stay only in the `litellm` container. Do not put a domestic provider key into `config/paply-models.yaml`, a desktop setting, or the public Gateway response.

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
- `/health/ready` failing means LiteLLM is unavailable or unhealthy.
- `/api/models` `401` means missing, expired, or invalid user identity.
- `/api/models` `503` means validation could not be completed; clients must not reuse the response as if refresh succeeded.
- `/v1/*` `502` means the edge could not establish a LiteLLM request.
- Provider errors preserve their LiteLLM status and should be correlated using `x-request-id`.

Logs intentionally exclude query strings, prompts, responses, tool payloads, and credentials.
