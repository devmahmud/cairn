# Getting started with the Lumen API

Lumen is a small, fictional notes-and-tasks API used as this template's
worked docs-assistant example. This guide covers everything you need to
make your first request.

## Creating an API key

Sign in to the Lumen dashboard and open **Settings > API Keys**. Click
**Create key**, give it a name, and copy the value shown -- it is only
displayed once. Store it somewhere safe; if you lose it, revoke it and
create a new one rather than trying to recover it.

## Making your first request

Every request must include your API key as a bearer token in the
`Authorization` header:

```
curl https://api.lumen.example/v1/notes \
  -H "Authorization: Bearer <your-api-key>"
```

A successful response returns a JSON array of your notes (empty on a new
account). If the header is missing or the key is invalid, you'll get a 401
response instead -- see the authentication guide for the exact error shape.

## Base URL and versioning

All requests go to `https://api.lumen.example/v1`. The `v1` segment is the
API version; Lumen will introduce `v2` alongside `v1` (not replace it) if a
breaking change is ever needed, so existing integrations keep working
without a forced migration deadline.
