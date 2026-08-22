# PaplyAI Gateway architecture

```text
Paply desktop main process
  ├─ register / login / refresh ── encrypted refresh session
  │  short-lived Paply access token
  ├─ GET /api/models ── model aliases + public /v1 URL, no credentials
  ├─ GET /api/skills ── PaplyAI catalog and bounded artifacts
  └─ /v1/responses | chat/completions | images
                         │
                         ▼
                 Paply FastAPI edge
             verify session, derive user_id
             derive private session affinity ID
             strip untrusted internal headers
                         │ internal service credential
                         ▼
                  LiteLLM data plane
           custom auth → user budget/rate policy
           routing + authoritative token/spend
                    │              │
               PostgreSQL       Redis
```

The renderer never receives provider keys, LiteLLM keys, internal service
credentials, or login tokens. A user is a stable accounting and policy
identity, not a virtual key. The main process owns the short-lived application
session and encrypts its refresh token with OS-backed storage.

LiteLLM remains the single token and spend ledger. The edge preserves streaming
and upstream status codes, does not retry billable requests, and never logs
request content or authorization values. `/v1/responses` and
`/v1/chat/completions` use exactly the same authentication and accounting path.

For `paply-chat`, `simple-shuffle` chooses a healthy deployment only at the
start of a session. Desktop sends a stable `x-paply-session-id`; the edge
validates it, namespaces it by authenticated user, and forwards only an HMACed
`x-litellm-session-id`. LiteLLM stores the 30-day affinity mapping in persistent
Redis, so native Responses reasoning and tool state stay on one actual model.
Caller-supplied LiteLLM affinity headers are discarded. Vision and image model
groups remain request-load-balanced.

The first release intentionally omits the full LiteLLM feature surface. It
needs model routing, per-user budgets/rate limits, usage reporting, the desktop
model/skill protocols, and operator diagnostics. Payments, arbitrary provider
configuration, and multi-region routing can be added later.
