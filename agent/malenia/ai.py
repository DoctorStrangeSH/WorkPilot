"""Bounded local-only Ollama chat. No tools, persistence or automatic context."""
from __future__ import annotations
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

BASE_URL = "http://127.0.0.1:11434"
ALLOWED_MODELS = {"qwen2.5:0.5b", "qwen2.5:1.5b", "qwen2.5:3b"}
SYSTEM = "Ты Маления, локальный помощник. Отвечай по-русски, кратко и по делу. У тебя нет инструментов, доступа к браузеру или файлам. Не утверждай, что выполнила действия. Если не знаешь ответ, скажи об этом."

class AIError(Exception):
    def __init__(self, code, status=503):
        self.code, self.status = code, status
        super().__init__(code)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AIError("ollama_redirect_rejected")

class OllamaClient:
    def __init__(self):
        self._opener = build_opener(ProxyHandler({}), NoRedirect())
        self._generation = threading.Lock()

    def _request(self, path, body=None, timeout=3):
        request = Request(BASE_URL + path,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise AIError("ollama_response_too_large")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise AIError("ollama_invalid_response")
            return value
        except AIError:
            raise
        except (HTTPError, URLError, OSError, ValueError):
            raise AIError("ollama_unavailable") from None

    def status(self):
        try:
            data = self._request("/api/tags")
            models = data.get("models")
            if not isinstance(models, list):
                raise AIError("ollama_invalid_response")
            names = sorted({item["name"] for item in models if isinstance(item, dict)
                and isinstance(item.get("name"), str) and item["name"] in ALLOWED_MODELS
                and not item.get("remote_host") and not item.get("remote_model")})
            return {"available": True, "models": names, "provider": "ollama", "local_only": True}
        except AIError as error:
            return {"available": False, "models": [], "error": error.code,
                    "provider": "ollama", "local_only": True}

    def chat(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"model", "messages"}:
            raise AIError("invalid_chat_request", 422)
        model, messages = payload["model"], payload["messages"]
        if not isinstance(model, str) or model not in ALLOWED_MODELS:
            raise AIError("local_model_not_allowed", 422)
        if not isinstance(messages, list) or not 1 <= len(messages) <= 12:
            raise AIError("invalid_chat_messages", 422)
        total = 0
        for index, message in enumerate(messages):
            expected_role = "user" if index % 2 == 0 else "assistant"
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message.get("role") != expected_role
                    or not isinstance(message.get("content"), str)
                    or not message["content"].strip() or len(message["content"]) > 2000):
                raise AIError("invalid_chat_messages", 422)
            total += len(message["content"])
        if messages[-1]["role"] != "user" or total > 8000:
            raise AIError("chat_context_too_large", 422)
        if not self._generation.acquire(blocking=False):
            raise AIError("model_busy", 429)
        try:
            status = self.status()
            if not status["available"]:
                raise AIError("ollama_unavailable")
            if model not in status["models"]:
                raise AIError("local_model_not_installed", 409)
            result = self._request("/api/chat", {"model": model,
                "messages": [{"role": "system", "content": SYSTEM}] + messages,
                "stream": False, "keep_alive": "30s",
                "options": {"num_ctx": 2048, "num_predict": 384, "num_thread": 2,
                            "temperature": 0.3}}, timeout=90)
            message = result.get("message")
            if (result.get("done") is not True or not isinstance(message, dict)
                    or not isinstance(message.get("content"), str)
                    or not message["content"].strip() or len(message["content"]) > 2000
                    or message.get("tool_calls")):
                raise AIError("ollama_invalid_response")
            return {"model": model, "message": {"role": "assistant", "content": message["content"]},
                    "local_only": True, "tools_enabled": False}
        finally:
            self._generation.release()
