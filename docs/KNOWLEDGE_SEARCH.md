# Knowledge search and source-constrained answers (0.5.1)

## Why

The 0.5.0 search reduced words to five-character prefixes and chose a passage near
the first hit. Similar order IDs could collide and generic words near the start
could hide a specific answer later in a note. Previous assistant answers also
should not be treated as source material for a strict knowledge request.

## Search behavior

- Full word matches rank above a limited prefix fallback for long alphabetic words.
- Alphanumeric codes with separators (AB-17, INV/2026/17) are case-insensitive but
  otherwise exact. AB-17 does not match AB-170. A note titled with a different code
  is excluded for that query; matching a requested code inside a generic note is
  allowed. Multiple requested codes can yield sources for any of those codes.
- This is not a general identifier parser: bare short numbers, punctuation variants,
  synonyms and semantic paraphrases are not automatically resolved.
- Content is split into overlapping 600-character windows, every 400 characters.
  Windows are ranked by exact words, title, prefix fallback, phrase and exact code.
  At most one passage per record, two memories and two notes are included.
- start/end are Python Unicode offsets into the stored snapshot, end exclusive.
  UI displays a human-readable range. They do not locate the current live file.
- General chat can still receive unrelated code-free preferences as context.
  Strict search/preview uses matched records only. It does not treat arbitrary
  preferences as evidence for an unanswered question.
- No source directories are read by search. Reimport is still an explicit action.

## Knowledge-only answers

knowledge_only is opt-in and use_knowledge must be true. The backend validates the
current question and searches matched records. With none, it returns a fixed
insufficient-information reply, generated=false, with no model/status API request.
This path works even when the allowed model is not installed. The ordinary chat
UI still checks engine/model readiness; database preview does not require a model.

With sources, only system/reference context and the current user turn are sent.
No prior assistant/user turns are supplied. Ask a complete question including an
order ID where needed. The model is asked to use only the excerpts and to emit
JSON answer/sufficient/source_ids. Ollama gets a schema allowing only actual IDs.
The backend independently validates exact fields/types, known unique IDs, at least
one citation for sufficient=true, and no citations for sufficient=false. Invalid
responses raise knowledge_answer_unverified and are not inserted into the chat.
An insufficient reply discards any generated answer and uses the fixed refusal.

This checks citation integrity, not whether each factual claim follows from the
source. Contradictions, missing context, prompt injection and model mistakes remain
possible. Notes do not grant tools or permissions. Read the displayed excerpts;
no automatic actions or internet fact validation are enabled.

## API / UI

- Authenticated POST /v1/knowledge/search with {query:string}, 1..2000 characters.
  Returns {sources:[...]}. It does not modify records or start inference.
- POST /v1/ai/chat optionally accepts knowledge_only:boolean. Replies add
  answer_mode, cited_source_ids and generated; sources lists actual supplied records.
- Knowledge page: explicit Find in knowledge button, passages and snapshot ranges.
- Chat: explicit knowledge-only checkbox; disabling knowledge clears strict mode.
  Source metadata stays in displayed history but is never sent as user messages.
  Citation labels say the MODEL cited a record, not that facts were verified.
- Runtime release 0.5.1 advertises knowledge_only capability for shell compatibility.

## Validation

Regression fixtures cover AB-17 vs AB-170 vs AB-18, unknown IDs, a specific answer
far from generic text, preference-only false matches, and search after source files
are deleted. Model tests reject fabricated/duplicate/missing/non-string citations,
non-JSON replies, and invalid switches. HTTP tests check authentication, input
bounds, no generation on missing records and absence of implicit writes. UI tests
cover explicit search, double clicks, disconnect during search and strict toggles.
The installed-upgrade CI test preserves and searches fixture notes after reinstall.

A small actual local-model probe used only fictional orders. It demonstrated
schema-compatible answering for AB-17 and no generation for unknown AB-19. This
is a smoke check, not a factual reliability benchmark for the target PC's 8B model.
