# paply-desktop integration contract

## Authentication

The desktop main process authenticates `GET /api/models` and every `/v1/*`
request with a short-lived Paply login access token. The token is an
application session: it cannot call a model provider or the private LiteLLM
listener directly.

The current development bridge reads `PAPLYAI_GATEWAY_ACCESS_TOKEN` from the
host environment. Production must replace that resolver with the Paply account
login/refresh flow and OS-protected storage. Renderer state, app-state, model
documents, and diagnostics must never receive the token.

Remote HTTP is rejected by default. A controlled pilot may set
`PAPLYAI_ALLOW_INSECURE_GATEWAY=1`; this is a developer-only escape hatch and
must not be used for a production account session.

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

Pi's host-owned `models.json` stores only the dynamic environment reference
`$PAPLYAI_GATEWAY_ACCESS_TOKEN`; Gateway credentials are removed from
`auth.json`. Media requests resolve the same session in the main process.

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
