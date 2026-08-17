# Authentication and error handling

## Authentication

Lumen uses bearer-token authentication. API keys never expire on their own,
but you can revoke or rotate one at any time from **Settings > API Keys**.
There is no separate OAuth flow for server-to-server integrations -- the API
key is the only credential you need.

## Rotating keys

When you rotate a key, the old value keeps working for 24 hours so
in-flight deployments don't break mid-rollout. After that window, requests
using the old key start failing with a 401. There's no way to extend the
grace period, so coordinate a rotation with your deploy rather than doing
it mid-incident.

## Error responses

Every error is a JSON object shaped like:

```json
{
  "error": {
    "code": "invalid_api_key",
    "message": "The provided API key is invalid or has been revoked."
  }
}
```

Common `error.code` values: `invalid_api_key` (401), `rate_limited` (429),
`not_found` (404), and `validation_error` (422, when a request body fails
schema validation -- the message names the offending field).
