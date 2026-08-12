# Operations and usage management

## Public and private surfaces

Public production ingress should expose only:

- `GET /health/live`
- `GET /health/ready` (optionally restricted to health-check networks)
- `GET /api/models`
- the required `/v1/*` OpenAI-compatible routes

LiteLLM port `4000`, `/ui`, master-key endpoints, PostgreSQL, and Redis belong on the operator network. Local Compose binds LiteLLM to `127.0.0.1` and does not publish either database.

## User accounting model

Use a stable opaque Paply user ID as LiteLLM `user_id` and issue at least one Virtual Key per user/device boundary. Set:

- `models` to the Paply aliases the user may call;
- `max_budget` and `budget_duration` for hard spend control;
- team membership for organizational budgets;
- TPM/RPM limits where abuse control is required.

Do not share the master key or provider key with the desktop. Revoke a lost client Virtual Key without rotating provider credentials for every user.

LiteLLM's PostgreSQL spend logs are authoritative. Dashboards and exports should read through supported LiteLLM management APIs/UI rather than coupling Paply code to LiteLLM's internal Prisma table layout.

## Secrets

- `LITELLM_MASTER_KEY`: operator authentication. Rotate through a planned maintenance procedure.
- `LITELLM_SALT_KEY`: encryption root for values stored by LiteLLM. Back it up securely and keep it stable; changing it can make stored encrypted values unreadable.
- provider API keys: server-side only and independently rotatable.
- `POSTGRES_PASSWORD` and `REDIS_PASSWORD`: unique production secrets, supplied by the deployment secret manager.
- user Virtual Keys: revocable client credentials. Never include them in logs, crash reports, query strings, or analytics.

The committed `.env.example` contains placeholders only. CI and production must inject real values from their secret manager.

## Backups and recovery

Back up PostgreSQL on a defined schedule and test restore into an isolated environment. Redis persistence helps local recovery but does not replace PostgreSQL backups. A restore test should verify:

1. users, teams, Virtual Keys, and budgets are present;
2. spend aggregates reconcile with a pre-backup sample;
3. encrypted provider configuration remains readable with the backed-up salt key;
4. revoked keys remain revoked.

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
