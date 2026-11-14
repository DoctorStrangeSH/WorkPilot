# Signed browser lifecycle events (protocol prototype)

Status: internal Python implementation and tests only. BrowserEventChannel is
not wired to Native Messaging, the local HTTP API or a running browser extension.
It does not open a socket, collect page information or execute browser actions.
The existing extension permissions and native host behavior are unchanged.

## Trust and key provisioning

A future authenticated transport must provision a fresh random 32-byte key for
one connection, keep it out of page/model content and logs, and identify the
registered extension using transport-owned origin metadata. Key provisioning,
peer authentication, connection timeout/liveness and actual transport delivery
are not implemented in this prototype. HMAC possession by itself does not prove
browser identity or that submitted tab/document IDs are truthful.

The channel constructor validates extension-ID syntax and key length before
starting a fresh BrowserPermissionSession connection. The connection UUID is
provided by the local session, not chosen by an incoming event. Origin is an
argument supplied by the trusted transport; it is never accepted from JSON.
Expected origin is exactly chrome-extension://<registered-extension-id>/.
Reuse of a channel key across connections is forbidden by the transport contract.

## Event envelope

The body is between 2 and 8192 bytes, strictly UTF-8 JSON with one object and no
duplicate keys or NaN/Infinity. The detached signature is 64 lowercase hex
characters: HMAC-SHA256(channel_key, exact_body_bytes). No JSON canonicalization
is needed for event authentication; changing any byte requires a new signature.
The signature is compared in constant time after bounded input/origin checks.

Selected-document event, with exactly these fields:

```json
{"version":1,"type":"selected_document","connection_id":"<current UUID>","sequence":0,"tab_id":7,"document_id":"<browser document identity>"}
```

No selected document is represented by both tab_id and document_id set to null.
A disconnect event has only version, type, connection_id and sequence.
Version must be integer 1, sequence and non-null tab_id must be integers in
0..2^53-1 (booleans are rejected), and document identity must be nonempty and at
most 256 characters. No URLs, page text, decisions, action creation or execution
messages are supported by this channel.

Sequence starts at zero and must advance by exactly one on this channel. A
replayed/older event or a valid but different connection UUID is ignored. A
signed sequence gap, malformed schema or invalid current event closes the
channel and invalidates document authority. Reconnect must use a new channel;
a closed channel cannot resume. Rejected unauthenticated/oversized inputs do not
alter authority, preventing an unauthenticated sender from revoking grants.
A storage error closes the channel and propagates; there is no retry/fallback.
Concurrent delivery is serialized. Closing a stale channel cannot disconnect a
newer BrowserPermissionSession connection.

## Remaining integration work

Implement trusted key provisioning and origin acquisition, bounded framing,
connection liveness/timeouts, and transport ownership before exposing this
prototype to external input. Closing an actual transport must close this channel.
Browser-side document validation, command fingerprint verification and replay
protection are still required before DOM/screenshot execution. No such executor
is implemented or claimed by these tests.

Verification: tests/test_browser_channel.py covers signatures, exact origin,
replay, duplicate/concurrent events, gaps, malformed JSON/schema, input limits,
old connections, storage failure and closed-channel behavior, using fixture keys
and identifiers only. Tests do not access a browser or installed registration.
