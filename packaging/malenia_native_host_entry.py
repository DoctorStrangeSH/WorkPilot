"""PyInstaller entry point for the Malenia Native Messaging host."""

from malenia.native_messaging import run_native_messaging


if __name__ == "__main__":
    raise SystemExit(run_native_messaging())
