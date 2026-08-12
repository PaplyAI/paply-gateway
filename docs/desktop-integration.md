# paply-desktop integration contract

## Existing contract

Paply desktop resolves the model document from either:

1. `PAPLYAI_MODELS_CONFIG_URL`, used as an exact URL; or
2. the developer-configured Gateway origin plus `/api/models`.

The host validates `schemaVersion: 1` and accepts only these chat transports:

- `openai-responses`
- `openai-completions`

Media transports currently accepted by the desktop are:

- `openai-responses`
- `openai-images`
- `openai-chat-image`
- `google-generative-ai-image`
- `dashscope-native`

The Gateway template in `config/paply-models.yaml` is intentionally missing `baseUrl` and `apiKey`. The edge injects both only after the caller's LiteLLM Virtual Key has been validated.

## Authentication gap in the current desktop

The current `fetchGatewayModelsConfig()` performs an unauthenticated GET. That makes stable per-user accounting impossible: without a durable authenticated identity, the server cannot decide which Virtual Key belongs in the response.

`PAPLY_MODELS_BOOTSTRAP_KEY` is an observable compatibility bridge, not a production identity design. It deliberately fails validation when `PAPLY_ENVIRONMENT=production`.

## Production migration

The desktop should complete this flow before the Gateway is considered production-ready:

1. Paply authentication returns a short-lived application session, not a provider key or LiteLLM master key.
2. The desktop stores that session in the operating system credential store, never in renderer state or `app-state.json`.
3. Main-process `GET /api/models` includes `Authorization: Bearer <credential>`.
4. Paply backend maps the credential to a stable internal user and obtains/rotates that user's LiteLLM Virtual Key.
5. Gateway validates the Virtual Key and returns the strict model document.
6. Desktop writes the returned Virtual Key to Pi's host-owned `auth.json`; renderer IPC never receives it.
7. Logout revokes or detaches the Key explicitly. No failed or legacy session silently falls back to a shared Key.

The MVP edge currently accepts the LiteLLM Virtual Key directly as the Bearer credential. A later Paply identity exchange can replace that step without changing the returned `schemaVersion: 1` document.

## Required request

```http
GET /api/models HTTP/1.1
Host: gateway.paply.ai
Authorization: Bearer sk-user-virtual-key
X-Request-ID: 7f57b123cb1e4b9791f13b2a4e0348b1
```

The edge validates the credential against LiteLLM's internal `GET /key/info`. This also rejects a master key because the master key is not a Virtual Key row in PostgreSQL. Invalid, expired, blocked, non-virtual, and unauthorized keys return `401`; unavailable validation returns `503`. It never returns a stale cached configuration as success.

## Response shape

```json
{
  "schemaVersion": 1,
  "chat": {
    "providers": [
      {
        "id": "paply",
        "name": "PaplyAI",
        "api": "openai-responses",
        "baseUrl": "https://gateway.paply.ai/v1",
        "apiKey": "sk-user-virtual-key",
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
    "modelId": "paply-vision",
    "apiKey": "sk-user-virtual-key"
  },
  "imageGen": {
    "provider": "paply",
    "apiType": "openai-images",
    "baseUrl": "https://gateway.paply.ai/v1",
    "modelId": "paply-image",
    "apiKey": "sk-user-virtual-key"
  }
}
```

## Compatibility tests

Whenever the desktop or Gateway document changes, copy the intended fixture into both repositories' contract tests. The Gateway must reject unknown fields in its source template, while the desktop remains the final authority on what it can materialize into Pi.
