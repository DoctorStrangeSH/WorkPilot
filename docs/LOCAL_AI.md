# Malenia 0.4.0 local chat

The AI page connects to Ollama at fixed 127.0.0.1:11434; Python ignores proxy
settings and rejects redirects. Default first-test model: qwen2.5:0.5b. Only local
Qwen 2.5 0.5B/1.5B/3B tags are allowed; remote/cloud tags are excluded. No model
messages, prompts or responses are persisted or logged by Malenia. Ollama is a
separate trusted local runtime and may maintain its own operational logs.

The runtime is installed under LOCALAPPDATA/Malenia/ollama, models under
LOCALAPPDATA/Malenia/models. The app's Start Ollama button launches this runtime
with loopback binding, OLLAMA_NO_CLOUD=1, one parallel request/model, context 2048
and a 30-second keep-alive. Existing Ollama processes are not adopted or killed.
The app stops only an Ollama process it spawned itself.

The chat sends only user-entered messages plus the fixed Malenia system prompt.
No tabs, task queue, files, profiles or browser secrets are attached. No tool
execution is available. The model can propose plans but cannot perform them.
The short conversation lives in React memory and clears on leaving the page,
app reload or agent disconnection. A request is never retried automatically.

Requests: authenticated GET /v1/ai/status and POST /v1/ai/chat. The latter has a
32-KiB body limit, at most 12 alternating user/assistant messages, 2000 characters
per message and 8000 characters total, ending in a user turn. Inference is limited
to one request at a time, context 2048 and output 384 tokens, with a 90-second
provider timeout. Responses must be completed plain text without tool calls.
The frontend forwards at most three preceding exchanges, trimming oldest pairs
when needed. Failed sends restore the draft rather than resending it silently.

The compact first-test model has limited reasoning and Russian fluency. Evaluate
it with simple text summaries, extraction and planning; do not infer that its
accuracy represents larger models. No actual desktop/browser actions are enabled.
