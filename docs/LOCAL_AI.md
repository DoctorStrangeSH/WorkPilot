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


## Verified Intel Graphics experiment on the user's PC

Intel integrated graphics uses shared system RAM, not an additional VRAM pool.
Ollama v0.40.16 detects the Vulkan device but skips an integrated GPU unless
OLLAMA_IGPU_ENABLE=1 is also set. A temporary isolated server with both
OLLAMA_VULKAN=1 and OLLAMA_IGPU_ENABLE=1 did offload about 456 MB. On one short
48-token Qwen 0.5B test, CPU generated 50.17 tokens/s versus 45.93 on the iGPU;
this is a limited machine/model-specific comparison, not a general GPU benchmark.
The regular chat stays on CPU. No graphics driver/global environment was changed.
GPU probe processes were stopped; the original local CPU server remains running.

## First test in the installed application

Open Malenia 0.4.0, start its agent on the main page, then open the AI models page.
The installed qwen2.5:0.5b should be selected. Use Check connection if needed and
send a short question. Ollama must be running; the Start Ollama button can launch
the portable runtime installed in LOCALAPPDATA/Malenia/ollama on this machine.
The compact model answered arithmetic correctly but invented order details in a
planning probe. Treat it as an experimental baseline, never as verified business
facts. Tasks and browser actions are still not executed by the model.


### Reviewed task creation (0.4.1 source)

An assistant reply can be copied into an editable task review. Saving requires
an explicit click and only queues the reviewed text; the model cannot execute
it. Check invented details before confirming. The description limit is 2000
characters; longer replies must be shortened. An uncertain save can be retried
with the same submission key and unchanged content without creating a duplicate.
After the first attempt, check the Tasks page before cancelling the review or
creating a new submission. Chat history and unsaved review state remain temporary.

The desktop checks the agent release and protocol when starting it. If versions
do not match, close Malenia and rerun the verified installer. Setup refuses to
replace an agent/browser-host executable still in use. Close Malenia and the
browser bridge before retrying. User tasks and model files are preserved.
