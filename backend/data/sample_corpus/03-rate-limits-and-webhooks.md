# Rate limits and webhooks

## Rate limits

The default rate limit is 120 requests per minute per API key. If you go
over it, Lumen responds with `HTTP 429` and a `Retry-After` header telling
you how many seconds to wait before your next request. Retrying
immediately without waiting just extends the cooldown. Verified production
workloads can request a higher limit from support.

## Webhooks

Configure a webhook endpoint under **Settings > Webhooks** to get notified
of events in near real time instead of polling. Supported event types are
`note.created`, `note.updated`, and `task.completed`. Each delivery is a
POST request with a JSON body describing the event and the resource it
affects.

## Retry behavior

If your endpoint doesn't return a `2xx` status, Lumen retries the delivery
up to five times with exponential backoff (roughly 1, 2, 4, 8, then 16
minutes between attempts). After the fifth failed attempt, the webhook is
marked as failing in the dashboard and no further retries happen until you
manually re-enable it.
