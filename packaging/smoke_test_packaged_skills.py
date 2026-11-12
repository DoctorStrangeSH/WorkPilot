"""End-to-end smoke test for the frozen Windows agent's skills API.

Uses only disposable LOCALAPPDATA, a random bearer token and loopback port.
Never touches the user's Malenia database or requires an installed Qwen model.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler


def check(exe: Path) -> None:
    if not exe.is_file():
        raise RuntimeError("missing_frozen_agent")
    with tempfile.TemporaryDirectory(prefix="malenia-skills-smoke-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        token = "smoke-" + uuid.uuid4().hex
        env = dict(os.environ, LOCALAPPDATA=directory, MALENIA_API_TOKEN=token)
        opener = build_opener(ProxyHandler({}))
        base = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [str(exe), "--port", str(port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            def request(method: str, path: str, data=None):
                payload = json.dumps(data).encode("utf-8") if data is not None else None
                headers = {"Authorization": f"Bearer {token}",
                           "Content-Type": "application/json"}
                req = Request(base + path, data=payload, headers=headers, method=method)
                with opener.open(req, timeout=2) as response:
                    return response.status, json.load(response)

            deadline = time.monotonic() + 25
            while True:
                if process.poll() is not None:
                    raise RuntimeError("frozen_agent_exited_before_ready")
                try:
                    status, catalogue = request("GET", "/v1/skills")
                    break
                except (URLError, TimeoutError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("frozen_agent_not_ready") from None
                    time.sleep(0.25)
            if status != 200 or catalogue.get("executable") is not False:
                raise RuntimeError("skills_catalogue_missing")
            ids = {s["id"] for s in catalogue.get("skills", [])}
            if not {"planning", "research", "data-analysis", "order-review"} <= ids:
                raise RuntimeError("builtin_skills_missing")

            skill_id = str(uuid.uuid4())
            draft = {"request_id": skill_id, "title": "Проверка документов",
                     "description": "Проверка текстов", "instructions": "Проверь структуру.",
                     "terms": "документ текст"}
            status, result = request("POST", "/v1/skills/draft", draft)
            if status != 200 or result["skill"]["status"] != "draft":
                raise RuntimeError("draft_skill_failed")
            status, result = request("POST", "/v1/skills/approve", {"id": skill_id})
            if status != 200 or result["skill"]["status"] != "approved":
                raise RuntimeError("skill_approval_failed")
            status, result = request("GET", "/v1/skills")
            if status != 200 or not any(s["id"] == skill_id for s in result["skills"]):
                raise RuntimeError("skill_persistence_failed")
            if not (Path(directory) / "Malenia" / "malenia.sqlite3").is_file():
                raise RuntimeError("isolated_database_missing")

            try:
                request("GET", "/v1/skills")
            except HTTPError:
                raise RuntimeError("local_skill_api_unexpected_failure") from None
            print("Frozen Malenia skill catalogue, draft, approval and isolated SQLite: OK")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_test_packaged_skills.py PATH_TO_AGENT_EXE")
    check(Path(sys.argv[1]).resolve())
