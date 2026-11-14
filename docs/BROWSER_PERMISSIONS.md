# One-shot browser permissions: internal foundation

Status: local development only. The desktop permission panel and authenticated
list/decision routes are implemented. There is no real browser request producer,
DOM reader, screenshot executor or new extension permission in this milestone.
The capability names below reserve a protocol; they do not advertise available
browser functionality. Existing sharing still sends only explicit tab metadata.

## Binding and lifecycle

`PermissionGate` uses the existing `TaskStore` database and its generic event log.
A `BrowserAction` binds one capability (`browser.read_text` or
`browser.screenshot`) to a fresh runtime session UUID, browser tab ID, document
ID and exact JSON parameters. The SHA-256 fingerprint uses canonical JSON.
Only the fingerprint, capability, status and clock/deadline metadata are persisted; selectors,
page text, URLs and screenshots are not stored by this gate.

A request starts pending, with a default 60-second lifetime (maximum 300).
A matching explicit decision can approve or deny it. Pending/approved requests
can be revoked. Only an approved, matching, unexpired request can be consumed.
Consumed, denied, revoked and observed-expired states are terminal. Unknown IDs,
changed bindings, repeated decisions and repeated consumption return false.
Invalid actions raise ValueError; database failures propagate and must stop any
future dispatcher. There is no allow-on-error fallback.

SQLite BEGIN IMMEDIATE serializes state changes across connections/processes;
consumption and its audit event commit together. Eight concurrent consumers are
covered by a test and produce exactly one success. This guarantees at-most-once
permission use, not successful or exactly-once execution of a browser action.
A crash after consumption loses that permission. Uncertain delivery must never
be retried with it; request a new visible decision instead.

## Trusted presentation and desktop decisions

`PermissionInbox` owns a new session UUID and keeps at most 100 action snapshots
in memory. It copies input parameters and returned snapshots so later mutations
cannot change an already presented action. Creation is an internal Python entry
point for a future trusted adapter; there is no HTTP creation or consumption route.
The normal runtime currently has no producer, so its panel is empty.

Authenticated GET /v1/permissions lists the exact capability, tab, document,
parameters, fingerprint, status and remaining lifetime. Polling persists expiry.
POST /v1/permissions/{id}/decision accepts only the displayed fingerprint and
allow/deny/revoke. Changed, unknown, expired and repeated decisions return 409;
invalid bodies return 422. These routes have the same bearer/loopback protection
as other private endpoints. No CORS or browser-page decision channel is added.

The Rust command keeps the bearer token out of React. The panel shows explicit
allow/deny/revoke controls, exact parameters, statuses and a monotonic countdown;
terminal/expired requests have no decision controls. Busy/disconnected controls
are disabled and errors cause a refresh, never automatic decision retries.
Confirmation does not dispatch any browser operation. A successful server bind
revokes old open grants before serving requests. A failed bind leaves the active
runtime's grants untouched. Old session snapshots are never reloaded.

## Selected-document lifecycle adapter (internal only)

`BrowserPermissionSession` is the trusted lifecycle adapter contract. It has no
live Native Messaging connection and is not wired into the running server.
Tests instantiate it with the same inbox used by the HTTP handler. A future
transport may call connect/disconnect/select_document only with authenticated
browser-authoritative events, never page text or model-provided IDs.

- A connection gets a fresh UUID. Requests require a selected tab/document;
  creation while disconnected or with no selected document raises an error.
- Events carry strictly increasing sequence numbers. Wrong-connection, duplicate
  and older events return false without changing authority. Even a fresh event
  repeating the same document IDs invalidates old open permissions conservatively.
- Selection/navigation/closure revokes the inbox's pending and approved requests
  in one SQLite transaction. Disconnect/reconnect also rotates its session UUID.
  Returning to an old document cannot restore permission. Cancel revokes a
  specific request; denied/expired/consumed requests stay terminal.
- Local state is cleared before invalidation. If the database operation fails,
  preparation stays disabled; batch updates and audit rows roll back together.
- Internal prepare consumes the stored action only when the current session,
  selected tab and document match. It returns a bound connection/sequence/action
  envelope; it performs no network send, browser operation or automatic retry.
- Local locking orders navigation against preparation, but cannot prevent a
  navigation after preparation and before delivery. The receiving browser must
  validate the connection, sequence, selected tab/document and action fingerprint
  immediately before executing; reject tampered bodies and duplicate request IDs.
  Tests model this requirement with a FakeBrowserReceiver. They do not implement
  or verify a real browser-side executor, transport or its trust boundary.

The ordinary app still has no request producer: its permission panel stays empty.
Never expose connect/select/request/prepare through unauthenticated page channels
or add a public request-creation/consumption endpoint for convenience.

## Requirements before wiring a real browser adapter

- Keep approval inside trusted desktop controls. Page content, task descriptions
  and model output cannot approve requests or supply authoritative resource IDs.
- Generate a new runtime session UUID on every runtime start/reconnect. Never
  reuse a previous session ID or reload old requests into a new session.
- Obtain tab/document identity from the browser, bind it before presenting the
  request, and show the exact capability, target and parameters to the user.
  A caller holding a request ID alone cannot grant a different action.
- Immediately before dispatch, revalidate the current selected tab and document
  and atomically consume the matching permission. The browser-side executor
  must enforce document identity too, closing the navigation race between the
  local check and actual execution. This gate alone cannot observe navigation.
- Invalidate pending/approved requests on navigation, disconnect and cancellation.
  Revocation wins only if committed before consumption; it cannot undo an action
  already dispatched. Cancellation after consumption needs executor cooperation.
- Lifetimes are checked against both wall-clock and monotonic deadlines.
  Either deadline expiring or either clock falling below its creation value
  permanently expires the grant. Monotonic time prevents wall-clock rollback
  from extending a lifetime. Session rotation is still required after restart;
  persisted monotonic values alone do not establish browser-session identity.
- Permission metadata is now bounded globally to 100 open and 100 terminal rows.
  Maintenance expires elapsed grants before admission/observation/transitions;
  terminal rows are pruned by creation time with rowid as the tie-breaker. A
  pruned ID is permanently unknown and cannot be consumed or restored. Cleanup
  never deletes task/shared-tab records or append-only audit events. The audit
  log has separate, unchanged retention; this is not a total database-size limit.
  Fingerprints avoid storing action parameters but are not encryption.

## Verification

Run `python -m unittest discover -s tests -v` with `PYTHONPATH=agent`.
The permission tests cover pending/unknown IDs, allow/deny, revocation, exact
expiry boundary, terminal persistence after reopening, all binding fields,
competing decisions, concurrent consumers, clock rollback/reset, input limits
and generic auditing.
HTTP tests additionally cover authentication, foreign Host rejection, exact
binding decisions, expiry polling, replay rejection and absent create/consume
routes. Inbox tests cover defensive copies, session boundaries, startup/busy-port
behavior and the 100-request memory limit. Node tests render the actual React
component for pending/approved/terminal/empty/disconnected states and hostile
text; these are rendering tests, not native-window interaction tests.
Lifecycle tests cover navigation, tab return, reused document IDs, reconnects,
out-of-order events, cancellation, no selection, uncertainty after consumption,
concurrent navigation/preparation, invalidation failures and transactional rollback.
An HTTP integration test covers internal request creation, explicit API approval
and one-shot local preparation. Receiver identity/replay checks use a test double.
No real browser or installed registration is used by these tests.


## Lifecycle message validation prototype

BrowserEventChannel adds bounded HMAC/origin/schema/sequence validation in front
of BrowserPermissionSession. It is not connected to the running app or native
host. See BROWSER_CHANNEL.md for the exact protocol and missing key-provisioning,
transport/liveness and browser-side execution requirements.
