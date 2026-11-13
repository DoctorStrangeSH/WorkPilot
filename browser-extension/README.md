

## Open-tab discovery foundation (experimental, not yet wired)

`browser-extension/tab_discovery.js` contains a deterministic, side-effect-free
candidate matcher for the next milestone. It accepts the browser's current tab
metadata, three **explicit user-confirmed HTTPS origin/path mappings**, and the
set of granted exact-origin host-permission patterns. It returns zero/one/many
candidate states per role; duplicate matches are marked `ambiguous` and are
never auto-selected. Query strings and fragments are stripped from displayed
candidate URLs. Unknown origins, lookalike hostnames, non-HTTPS URLs, embedded
credentials, and tabs outside the configured path prefix are ignored.

This helper does **not** query the browser, persist mappings, request permissions,
bind a live document identity, read page content, or trigger an audit. It is a
tested foundation only; the popup and desktop workflow still use the existing
configured-URL audit path until the full tab/document lifecycle is integrated.
Run `node --test tests/tab_discovery.test.cjs` to validate the matching rules.


## Open-tab discovery foundation (experimental, not yet wired)

`browser-extension/tab_discovery.js` contains a deterministic, side-effect-free
candidate matcher for the next milestone. It accepts the browser's current tab
metadata, three **explicit user-confirmed HTTPS origin/path mappings**, and the
set of granted exact-origin host-permission patterns. It returns zero/one/many
candidate states per role; duplicate matches are marked `ambiguous` and are
never auto-selected. Query strings and fragments are stripped from displayed
candidate URLs. Unknown origins, lookalike hostnames, non-HTTPS URLs, embedded
credentials, and tabs outside the configured path prefix are ignored.

This helper does **not** query the browser, persist mappings, request permissions,
bind a live document identity, read page content, or trigger an audit. It is a
tested foundation only; the popup and desktop workflow still use the existing
configured-URL audit path until the full tab/document lifecycle is integrated.
Run `node --test tests/tab_discovery.test.cjs` to validate the matching rules.
