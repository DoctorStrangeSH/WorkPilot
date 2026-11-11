"""Command-line entry point for the WorkPilot local agent."""

from __future__ import annotations

import argparse
import secrets

from .config import database_path
from .resources import ResourceManager
from .server import serve
from .store import TaskStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local WorkPilot agent.")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback address only.")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("For safety, WorkPilot only listens on localhost.")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535.")

    store = TaskStore(database_path())
    snapshot = ResourceManager().snapshot()
    token = secrets.token_urlsafe(32)

    print("WorkPilot Agent 0.1.0")
    print(f"Local API: http://{args.host}:{args.port}")
    print(f"Resource mode: {snapshot.mode}")
    print(f"Available memory: {snapshot.available_memory_bytes} bytes")
    print("Temporary API token (keep private; valid for this run only):")
    print(token)
    print("Press Ctrl+C to stop. No browser or desktop actions are enabled in this MVP.")

    serve(args.host, args.port, store, token)
    return 0
