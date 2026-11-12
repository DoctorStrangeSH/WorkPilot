# Third-party models and Sherlock branding

Sherlock is the assistant name in Malenia. It is not a claim that the underlying
foundation model was trained by this project. The ordinary UI uses Sherlock names.

- Main: qwen3:8b; extended: qwen3:14b; light: qwen3:4b; experimental: qwen3:0.6b.
- Qwen3 is developed by the Qwen team / Alibaba. Upstream code/models and license:
  https://github.com/QwenLM/Qwen3 and https://huggingface.co/Qwen/Qwen3-8B
  (Apache-2.0; consult upstream model card/license for the exact downloaded version).
- Legacy qwen2.5 test tags remain supported. Their individual model cards and
  license terms apply; do not assume all sizes share the same license.
- Runtime: Ollama, https://github.com/ollama/ollama (MIT project; its bundled
  dependencies have their own licenses). Install the full official Windows runtime
  on NVIDIA PCs so CUDA libraries are present, not just the earlier CPU-only kit.

Malenia downloads model weights only after an explicit install click. No weights
are embedded in the installer or claimed as original Malenia training. Ollama
verifies downloaded blobs. Keep upstream notices and licenses when redistributing
runtime/model bundles. Model availability/licensing may change; check upstream.

No model benchmark for 8B/14B on the second PC has been run in this session.
Branding and a larger parameter count do not establish factual reliability.
