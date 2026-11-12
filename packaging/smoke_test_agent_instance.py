"""Verify the frozen agent rejects duplicate startup without replacing its owner."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise RuntimeError('Bundled Malenia agent is missing')
    with tempfile.TemporaryDirectory(prefix='malenia-agent-smoke-') as temporary:
        environment = os.environ.copy()
        environment['LOCALAPPDATA'] = temporary
        environment['XDG_DATA_HOME'] = temporary
        environment['MALENIA_API_TOKEN'] = 'isolated-smoke-test-only'
        # Verify an unrelated listener is never terminated or replaced.
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1', 0))
            unrelated.listen()
            result = subprocess.run([str(executable), '--port', str(unrelated.getsockname()[1])],
                                    env=environment, capture_output=True, timeout=20)
            if result.returncode != 2 or b'Local API:' in result.stdout:
                raise RuntimeError('Agent did not reject an unrelated occupied port before readiness')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        command = [str(executable), '--port', str(port)]
        first = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            ready = False
            for _ in range(100):
                if first.poll() is not None:
                    raise RuntimeError('First frozen Malenia agent exited during startup')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health', timeout=0.5) as response:
                        ready = json.load(response).get('service') == 'malenia-agent'
                    if ready:
                        break
                except (URLError, OSError, ValueError):
                    pass
                time.sleep(0.1)
            if not ready:
                raise RuntimeError('Frozen Malenia agent did not become healthy')
            second = subprocess.run(command, env=environment, capture_output=True, timeout=20)
            if second.returncode != 2 or first.poll() is not None:
                raise RuntimeError('Duplicate agent startup did not preserve the original process')
            if b'Local API:' in second.stdout or b'isolated-smoke-test-only' in second.stdout + second.stderr:
                raise RuntimeError('Rejected agent announced readiness or exposed its test token')
            with urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                if json.load(response).get('service') != 'malenia-agent':
                    raise RuntimeError('Original agent was replaced')
        finally:
            if first.poll() is None:
                first.terminate()
            try:
                first.wait(timeout=10)
            except subprocess.TimeoutExpired:
                first.kill()
                first.wait(timeout=5)
    print('PASS: frozen Malenia agent rejects duplicate/foreign listeners; original remains healthy.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
