# Paply Gateway architecture

```text
Paply desktop main process
  │  Paply login access token
  ├─ GET /api/models ── model aliases + public /v1 URL, no credentials
  ├─ GET /api/skills ── PaplyAI catalog and bounded artifacts
  └─ /v1/responses | chat/completions | images
                         │
                         ▼
                 Paply FastAPI edge
             verify session, derive user_id
             strip untrusted identity headers
                         │ internal service credential
                         ▼
                  LiteLLM data plane
           custom auth → user budget/rate policy
           routing + authoritative token/spend
                    │              │
               PostgreSQL       Redis
```

The desktop never receives provider keys, LiteLLM keys, or the internal
service credential. A user is a stable accounting and policy identity, not a
virtual key. The only client credential is a normal short-lived Paply login
session.

LiteLLM remains the single token and spend ledger. The edge preserves streaming
and upstream status codes, does not retry billable requests, and never logs
request content or authorization values. `/v1/responses` and
`/v1/chat/completions` use exactly the same authentication and accounting path.

The first release intentionally omits the full LiteLLM feature surface. It
needs model routing, per-user budgets/rate limits, usage reporting, the desktop
model/skill protocols, and operator diagnostics. Payments, arbitrary provider
configuration, and multi-region routing can be added later.
