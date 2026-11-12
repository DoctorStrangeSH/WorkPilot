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


## Local chat and explicit public search (0.6.0)

POST `/v1/ai/chat` requires the private loopback bearer. Fields: `model`, `messages`,
optional booleans `use_knowledge` (default true), `knowledge_only` (false), `use_web` (false).
`use_web` and `knowledge_only` cannot both be true. Public search sends only the last
user message to the fixed Bing RSS endpoint, never chat history or the knowledge store.
Only bounded snippets and source links are returned, not full pages. Search mode uses
only the current question and search snippets for local inference. Known citation IDs
are validated, not factual correctness. Reply `answer_mode` is `general`, `knowledge_only`
or `web`; `local_only` is false after external search, although inference remains local.
No results returns `generated=false`; network/parse failures return `web_*` errors.
GET `/v1/runtime` release is `0.6.0` and includes `public_search` capability.
