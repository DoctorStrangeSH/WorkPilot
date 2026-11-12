# Malenia Agent API — MVP

This API is an internal local bridge for the future desktop shell. It is not intended to be exposed to a LAN or the public internet.

## Start

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
malenia-agent
```

The server binds to 127.0.0.1 only. At startup it prints a random, per-run bearer token. Keep that token private. It is not persisted and changes after restart.

## Authentication

All endpoints except GET /health require:

```http
Authorization: Bearer <token>
```

The server accepts loopback Host values only, does not enable CORS, and limits JSON request bodies.

## Endpoints

- GET /health — basic process health.
- GET /v1/resources — memory snapshot, CPU logical processor count, operating mode and recommended parallelism.
- GET /v1/tasks?limit=50 — newest local tasks.
- GET /v1/events?limit=50 — newest audit events.
- GET /v1/browser/tabs?limit=20 — latest active tabs explicitly shared by the user through the Browser Bridge.
- POST /v1/tasks — add a task to the local queue. JSON: {"title":"...","description":"..."}.
- POST /v1/tasks/{uuid}/cancel — cancel a pending task.

The current MVP persists and lists tasks but does not execute them. Browser Bridge supports only explicit active-tab sharing in its preview; automatic tab discovery, DOM access, screenshots, desktop control, AI planning and image search are not implemented.


## One-shot permission decisions (development preview)

- GET /v1/permissions: session-scoped request snapshots and execution_enabled=false.
- POST /v1/permissions/{uuid}/decision: JSON {"binding":"<displayed SHA-256>",
  "decision":"allow|deny|revoke"}. No other fields are accepted. Requires bearer
  authentication and a loopback Host, like the other private routes.
- Success: 200, updated=true, execution_enabled=false. Unavailable/changed/replayed
  requests: 409. Invalid bodies: 422. The server never creates or consumes a
  permission through HTTP. Decisions do not execute browser actions.

There is currently no live request producer. Only a future trusted internal
adapter may create requests after obtaining browser-authoritative target identity.
See BROWSER_PERMISSIONS.md for lifecycle and integration requirements.
