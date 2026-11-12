# Malenia 0.6.0 / Sherlock local assistant

Sherlock is the assistant's display name; Malenia is the application. The ordinary
UI shows Sherlock variants; underlying model IDs and upstream notices are recorded
in THIRD_PARTY_MODELS.md. No original foundation-model training is claimed.

## Target machine and model setup

The user selected a different PC with 32 GB RAM and an NVIDIA RTX GPU. Exact GPU
model/VRAM is not yet supplied. Development machine has 15.55 GiB RAM, Intel
integrated graphics and roughly 1.4 GiB available. Do not install/load an 8B model
on the development PC. Its existing 0.4.1 installation is preserved at this stage.

On the target PC install Malenia. It automatically prepares the official portable runtime on an explicit start/install click if needed.
Start the agent, open AI models, start Sherlock, expand Install Sherlock and click
Download chosen Sherlock. Main is qwen3:8b (about 5 GB download), light qwen3:4b
(about 3 GB), extended qwen3:14b (about 9 GB). Downloads are explicit, local-runtime
only, allowlisted, proxy-free and reject redirects. They require respectively
8/5/14 GiB available system RAM before starting. Downloading does not load a model.
Only one loaded model/request is configured. Ollama handles NVIDIA offload based
on actual VRAM; GPU utilization on the target PC has not been verified.

Start reuses a healthy server or the standard LOCALAPPDATA/Programs/Ollama runtime; otherwise it installs/reuses the full pinned LOCALAPPDATA/Malenia/ollama-0.40.16 runtime. An already healthy local server is reused
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
POST /v1/ai/chat accepts model/messages and optional booleans use_knowledge/knowledge_only/use_web, returns
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
environment variables were changed. Opt-in public search snippets are available in 0.6.0 (see below).


## 0.5.1: exact identifiers, passage search and knowledge-only mode

See KNOWLEDGE_SEARCH.md. Search now prioritizes complete numeric/alphanumeric
codes and ranks overlapping 600-character passages instead of taking the first
query occurrence. Public source excerpts include start/end offsets into stored
snapshots. Search preview POST /v1/knowledge/search requires authentication,
reads only the existing database and never calls Ollama or rereads imported files.

Opt-in knowledge_only mode requires use_knowledge=true. It searches only matching
records (unrelated preferences do not count as evidence), drops previous chat
history and asks for a structured answer with known source IDs. No matching record
returns a deterministic insufficient-information response before contacting Ollama.
Malformed replies, missing citations, duplicate/unknown IDs and wrong field types
are rejected. The schema and validation establish reference integrity, not factual
entailment: a model can still draw an incorrect conclusion from a genuine excerpt.
The 0.5.1 milestone did not add internet search, embeddings or autonomous tools.


## Malenia 0.6.0: установка движка и интернет

Нажмите «Запустить Шерлока» или «Скачать выбранного Шерлока» внутри приложения.
Если работающий локальный Ollama или стандартная установка уже есть, приложение использует их.
Иначе оно автоматически скачивает официальный Ollama 0.40.16 для Windows x64 (архив 1,6 ГБ),
проверяет точный размер и SHA256 и распаковывает полный движок, включая CUDA,
в `%LOCALAPPDATA%/Malenia/ollama-0.40.16`. Права администратора и автозагрузка не нужны.
Нужно минимум 4 ГБ свободного места для движка, отдельно — место для выбранной модели.
На время установки оставьте окно открытым; при ошибке можно повторить кнопкой.
Архив не запускается при неправильной контрольной сумме. Повторная попытка начинает загрузку заново.
Старая переносная папка `ollama` не удаляется; новая установка использует полный версионный каталог.
Открытый сторонний сервер Ollama не перенастраивается и не завершается.

«Интернет-поиск» по умолчанию выключен. При включении текущий вопрос отправляется в Bing RSS.
История чата, сохранённая память, заметки и задачи в поиск не передаются.
В этом режиме модель отвечает локально только по четырём выдержкам поиска, без личной базы и истории.
Полные страницы не скачиваются; ссылки можно открыть самостоятельно.
Идентификаторы цитат проверяются, но это не доказывает правильность ответа или актуальность сайта.
Выдача может быть нерелевантной, а публичный поисковый интерфейс — временно недоступным.
При отсутствии результатов генерация не запускается, при сбое поиска показывается ошибка.
Режим «Только по знаниям» и интернет-поиск взаимоисключающие.
Не включайте секретные данные в вопрос, который отправляете во внешний поиск.
Никакого доступа к профилю браузера, cookies, паролям и истории это не предоставляет.

Зафиксированный архив: `ollama-windows-amd64.zip`, 1618244995 байт,
SHA256 `50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e`.
Источник: https://github.com/ollama/ollama/releases/tag/v0.40.16.
Наличие CUDA-библиотек не гарантирует работу конкретной видеокарты: проверка на целевом ПК ещё нужна.
