# paply-desktop integration contract

## Authentication

The desktop main process authenticates `GET /api/models` and every `/v1/*`
request with a short-lived Paply login access token. The token is an
application session: it cannot call a model provider or the private LiteLLM
listener directly.

The main process owns registration, login, refresh rotation, and logout. It
encrypts the refresh token with Electron `safeStorage`, keeps the access token
in memory, and exposes only account status through validated IPC. Renderer
state, app-state, model documents, and diagnostics never receive either token.

The product Gateway origin is built into the desktop. Product users do not
enter a Gateway URL, token, or SK. Engineering builds may override the origin
with `PAPLYAI_GATEWAY_BASE_URL` and may inject a short-lived access token with
`PAPLYAI_GATEWAY_ACCESS_TOKEN` for isolated protocol tests.

Remote HTTP is rejected except for the exact built-in internal-pilot origin. A
different controlled pilot origin may set `PAPLYAI_ALLOW_INSECURE_GATEWAY=1`;
this is an engineering-only escape hatch and must not be used after launch.

## Model document v2

The host accepts chat transports `openai-responses` and
`openai-completions`. The public document contains no `apiKey` or other
credential:

```json
{
  "schemaVersion": 2,
  "chat": {
    "providers": [
      {
        "id": "paply",
        "name": "PaplyAI",
        "api": "openai-responses",
        "baseUrl": "https://gateway.paply.ai/v1",
        "models": [
          {
            "id": "paply-chat",
            "name": "Paply Chat",
            "input": ["text", "image"],
            "reasoning": true,
            "contextWindow": 128000,
            "maxOutputTokens": 32768
          }
        ]
      }
    ]
  },
  "vision": {
    "provider": "paply",
    "apiType": "openai-responses",
    "baseUrl": "https://gateway.paply.ai/v1",
    "modelId": "paply-vision"
  },
  "imageGen": {
    "provider": "paply",
    "apiType": "openai-images",
    "baseUrl": "https://gateway.paply.ai/v1",
    "modelId": "paply-image"
  }
}
```

Pi's host-owned chat provider configuration stores no API key. Before each
chat or utility-model operation, the main process injects the short-lived
session into Pi's in-memory runtime. Media requests resolve the same session
directly. No concrete session enters `models.json`, `auth.json`, or the global
process environment.

## Account provisioning

`POST /api/auth/register` creates the Paply account and provisions the same
opaque user ID in LiteLLM with `auto_create_key=false`. Login and refresh return
the normal Paply application session. No endpoint in this flow creates or
returns a LiteLLM virtual key.

## Server identity mapping

The edge validates the signed session and derives `user_id` from its `sub`
claim. It removes any caller-supplied `x-paply-user-id`, replaces the public
Bearer token with one server-only service credential, and forwards the trusted
identity to the private LiteLLM listener. LiteLLM custom auth maps that identity
to the existing accounting user and applies its model, budget, TPM, and RPM
rules. There is no per-user LiteLLM key.

Both repositories keep the same v2 fixture in contract tests. Unknown or
expired sessions fail with `401`; the client must not silently fall back to a
shared identity.
