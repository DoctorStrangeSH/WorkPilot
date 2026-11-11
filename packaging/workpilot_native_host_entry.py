"""PyInstaller entry point for the WorkPilot Native Messaging host."""

from workpilot.native_messaging import run_native_messaging


if __name__ == "__main__":
    raise SystemExit(run_native_messaging())
