"""Smoke-test the frozen Native Messaging host using the real stdio frame protocol."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def frame(payload: dict) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def read_frame(stream: bytes, offset: int = 0) -> tuple[dict, int]:
    if len(stream) - offset < 4:
        raise RuntimeError("Native host returned an incomplete frame header")
    (length,) = struct.unpack_from("<I", stream, offset)
    start = offset + 4
    end = start + length
    if end > len(stream):
        raise RuntimeError("Native host returned an incomplete frame body")
    return json.loads(stream[start:end].decode("utf-8")), end


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_test_native_host.py PATH_TO_NATIVE_HOST_EXE")

    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"Native host executable not found: {executable}")

    extension_id = "a" * 32
    origin = f"chrome-extension://{extension_id}/"
    with tempfile.TemporaryDirectory() as temporary:
        local_app_data = Path(temporary)
        app_dir = local_app_data / "WorkPilot"
        app_dir.mkdir()
        (app_dir / "browser_bridge.json").write_text(
            json.dumps({"extension_id": extension_id}), encoding="utf-8"
        )

        requests = b"".join(
            [
                frame({"type": "hello", "request_id": "hello"}),
                frame(
                    {
                        "type": "share_active_tab",
                        "request_id": "share",
                        "tab": {
                            "title": "Smoke test",
                            "url": "https://example.com/orders/1?token=must-not-persist#private",
                        },
                    }
                ),
            ]
        )
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(local_app_data)
        result = subprocess.run(
            [str(executable), origin],
            input=requests,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Native host exited {result.returncode}: "
                f"{result.stderr.decode('utf-8', errors='replace')}"
            )

        hello, offset = read_frame(result.stdout)
        shared, offset = read_frame(result.stdout, offset)
        if offset != len(result.stdout):
            raise RuntimeError("Native host wrote unexpected bytes to stdout")
        if not hello.get("ok") or hello.get("request_id") != "hello":
            raise RuntimeError(f"Unexpected hello response: {hello}")
        if not shared.get("ok") or shared.get("request_id") != "share":
            raise RuntimeError(f"Unexpected share response: {shared}")
        if shared["tab"]["url"] != "https://example.com/orders/1":
            raise RuntimeError("Native host did not remove query/fragment data")

        database = app_dir / "workpilot.sqlite3"
        if not database.is_file():
            raise RuntimeError("Native host did not persist the explicitly shared tab")
        print("Native Messaging host framing, origin check, tab validation and SQLite write passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
