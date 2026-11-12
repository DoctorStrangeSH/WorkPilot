# Malenia 0.5.0 / Sherlock local assistant

Sherlock is the assistant's display name; Malenia is the application. The ordinary
UI shows Sherlock variants; underlying model IDs and upstream notices are recorded
in THIRD_PARTY_MODELS.md. No original foundation-model training is claimed.

## Target machine and model setup

The user selected a different PC with 32 GB RAM and an NVIDIA RTX GPU. Exact GPU
model/VRAM is not yet supplied. Development machine has 15.55 GiB RAM, Intel
integrated graphics and roughly 1.4 GiB available. Do not install/load an 8B model
on the development PC. Its existing 0.4.1 installation is preserved at this stage.

On the target PC install the full official Ollama Windows runtime, then Malenia.
Start the agent, open AI models, start Sherlock, expand Install Sherlock and click
Download chosen Sherlock. Main is qwen3:8b (about 5 GB download), light qwen3:4b
(about 3 GB), extended qwen3:14b (about 9 GB). Downloads are explicit, local-runtime
only, allowlisted, proxy-free and reject redirects. They require respectively
8/5/14 GiB available system RAM before starting. Downloading does not load a model.
Only one loaded model/request is configured. Ollama handles NVIDIA offload based
on actual VRAM; GPU utilization on the target PC has not been verified.

Start searches portable LOCALAPPDATA/Malenia/ollama first, then the standard
LOCALAPPDATA/Programs/Ollama runtime. An already healthy local server is reused
without adopting or killing it. App-owned runtime is loopback only with cloud
models disabled, one parallel request/model, context 2048 default, keep-alive 30s.
Explicit inference sets context 4096 for Sherlock or retrieved knowledge. A full
NVIDIA-capable runtime is needed on the second PC; the old portable CPU extraction
from the development machine is not a GPU installation kit.

## Explicit memory and Markdown knowledge

- Authenticated /v1/knowledge endpoints list, save, delete and import knowledge.
  SQLite stores confirmed memory and imported note snapshots next to existing
  task data. Chats/model replies are never automatically saved as knowledge.
- Remember under a USER message opens editable review. Only Confirm and remember
  writes data. Review freezes after an uncertain attempt and retries the same UUID
  and text; changed content for the same UUID is rejected. Records are visible
  and deletable in Memory and knowledge. No hidden conversational history store.
- Up to 12 memory entries and 200 total records. Memory content <=2000 characters;
  note <=6000; title <=120. The UI permits adding manual reference notes as well.
- Explicit folder import reads UTF-8 .md snapshots only, <=100 notes, <=24 KiB each,
  <=1000 directory entries, depth <=6. Hidden/dot files/directories, symlinks and
  Windows reparse points are skipped; linked ancestors are rejected. Root/home
  folders are rejected. Attachments, embedded links and other files are not read.
  No network links are followed. Import validates all notes before one transaction.
- Reimport replaces that folder's snapshot and removes disappeared notes from the
  database; source files remain untouched. No watcher or automatic synchronization.
- Retrieval is a small lexical search using word prefixes, not semantic embeddings.
  It includes at most two memory records and two matching notes, excerpts <=600
  characters each. Relevant memories rank first, ties favor recent records. Not
  every saved rule is necessarily included; sources/excerpts are visible per reply.
  The chat checkbox disables all knowledge retrieval for that request.
- Notes are quoted reference DATA, never permission to run tools or alter storage.
  Retrieval is not a guarantee of grounded answers; inspect original notes and
  model answers. No browser/desktop tools or autonomous task execution are enabled.

## API and inference

Ollama destination fixed 127.0.0.1:11434; proxies ignored, redirects rejected.
Allowed legacy local tags plus Qwen3 0.6b/4b/8b/14b; cloud metadata excluded.
POST /v1/ai/chat accepts model/messages and optional boolean use_knowledge, returns
actual retrieved source metadata. <=12 alternating messages, <=2000 characters
per message, <=8000 total; backend trims oldest pairs if reference+history exceeds
6500 characters. Deterministic temperature 0, output <=384 tokens, 90s timeout,
Qwen3 thinking disabled, no tool calls. Frontend sends at most three earlier pairs
and strips source metadata from conversation messages before submitting again.
No silent retries or full chat persistence. Task creation remains reviewed queueing.

## Verification and limitations

Small-machine smoke comparison (three short Russian prompts) confirmed neither
0.5B nor 0.6B is a satisfactory factual baseline: the 0.6B answer to Japan capital
was wrong. Arithmetic/extraction were better but did not obey exact-output format.
The UTF-8-correct evaluation artifact is local; an initial shell-encoding-corrupted
probe was discarded and is not evidence. No 8B/14B quality/latency/memory benchmark
has run on the second PC. Keep these claims separate from passing software tests.

Intel integrated graphics on the development PC shares RAM. Earlier tiny-model
probe: CPU 50.17 vs iGPU 45.93 tokens/s on a short test, so CPU stayed default.
This says nothing about the second PC's NVIDIA performance. No drivers/global
environment variables were changed. Internet factual search is not implemented.
