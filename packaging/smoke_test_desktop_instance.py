"""Windows CI-only smoke test: launching Malenia twice activates one desktop instance."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def visible_window(process_id: int) -> bool:
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    found = False

    @callback_type
    def visit(window, _):
        nonlocal found
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(window):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(window, title, 256)
            if 'Malenia' in title.value:
                found = True
        return True

    user32.EnumWindows(visit, 0)
    return found


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    if sys.platform != 'win32' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Desktop instance smoke test runs only on an isolated Windows CI runner')
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise RuntimeError('Malenia desktop executable is missing')
    with tempfile.TemporaryDirectory(prefix='malenia-desktop-smoke-') as temporary:
        environment = os.environ.copy()
        environment['LOCALAPPDATA'] = temporary
        environment['APPDATA'] = temporary
        environment['WEBVIEW2_USER_DATA_FOLDER'] = str(Path(temporary) / 'webview-test')
        first = subprocess.Popen([str(executable)], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        second = None
        try:
            for _ in range(150):
                if first.poll() is not None:
                    raise RuntimeError('Malenia desktop exited before opening its window')
                if visible_window(first.pid):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('Malenia window did not appear')
            second = subprocess.Popen([str(executable)], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if second.wait(timeout=15) != 0:
                raise RuntimeError('Second desktop launch did not exit successfully')
            if first.poll() is not None or not visible_window(first.pid):
                raise RuntimeError('Original Malenia window was not retained')
        finally:
            if second is not None:
                stop_owned(second)
            stop_owned(first)
    print('PASS: second Malenia desktop launch exits and retains the original visible window.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
