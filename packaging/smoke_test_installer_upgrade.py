"""CI-only install/reinstall test with a real installed frozen agent."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler
from uuid import uuid4


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def main():
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Windows':
        raise RuntimeError('Run only in an isolated Windows GitHub Actions runner')
    root = Path(__file__).resolve().parents[1]
    installers = list((root / 'desktop/src-tauri/target/release/bundle/nsis').glob('*.exe'))
    if len(installers) != 1:
        raise RuntimeError('Expected exactly one built installer')
    resources = root / 'desktop/src-tauri/resources'
    expected = {p.relative_to(resources): digest(p) for p in resources.rglob('*') if p.is_file()}
    if not expected:
        raise RuntimeError('No bundled resources to verify')
    release = json.loads((root / 'desktop/package.json').read_text())['version']
    with tempfile.TemporaryDirectory(prefix='malenia-upgrade-') as directory:
        base = Path(directory)
        target = base / 'installation'
        data = base / 'data'
        data.mkdir()
        sentinel = data / 'preserve.txt'
        sentinel.write_text('keep fixture data')
        env = os.environ.copy()
        env['LOCALAPPDATA'] = str(data)
        env['XDG_DATA_HOME'] = str(data)
        env['MALENIA_API_TOKEN'] = secrets.token_urlsafe(32)
        command = [str(installers[0]), '/S', '/UPDATE', '/NS', f'/D={target}']

        def install():
            return subprocess.run(command, env=env, timeout=120).returncode

        def verify_resources():
            for relative, checksum in expected.items():
                installed = target / 'resources' / relative
                if not installed.is_file() or digest(installed) != checksum:
                    raise AssertionError(f'Installed resource mismatch: {relative}')
            if sentinel.read_text() != 'keep fixture data':
                raise AssertionError('Fixture data was modified')

        assert install() == 0, 'Initial installation failed'
        verify_resources()
        opener = build_opener(ProxyHandler({}))
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]

        def api(path, body=None):
            request = Request(f'http://127.0.0.1:{port}{path}',
                              headers={'Authorization': 'Bearer ' + env['MALENIA_API_TOKEN'],
                                       'Content-Type': 'application/json'},
                              data=None if body is None else json.dumps(body).encode())
            with opener.open(request, timeout=10) as response:
                return json.load(response)

        executable = target / 'resources/malenia-agent/malenia-agent.exe'
        def start():
            process = subprocess.Popen([str(executable), '--port', str(port)], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('Installed agent exited')
                try:
                    runtime = api('/v1/runtime')
                    assert runtime['release'] == release
                    assert 'task_idempotency' in runtime['capabilities']
                    return process
                except (URLError, OSError):
                    time.sleep(0.1)
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError('Installed agent did not become ready')

        def stop(process):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)

        process = start()
        body = {'title': 'Preserve reviewed task', 'description': 'Fixture only', 'request_id': str(uuid4())}
        try:
            first = api('/v1/tasks', body)['task']
            memory = {'request_id': str(uuid4()), 'title': 'Confirmed fixture', 'content': 'Never invent order IDs', 'kind': 'memory'}
            api('/v1/knowledge', memory)
            assert len(api('/v1/knowledge')['records']) == 1
            assert api('/v1/tasks', body)['task']['id'] == first['id']
            assert isinstance(api('/v1/ai/status')['available'], bool)
            assert install() != 0, 'Locked resource upgrade incorrectly succeeded'
            assert process.poll() is None, 'Installer stopped the existing agent'
            verify_resources()
            assert api('/v1/runtime')['release'] == release
        finally:
            stop(process)
        # Reproduce a stale installed executable, then repair by reinstalling.
        executable.write_bytes(b'stale fixture executable')
        assert install() == 0, 'Reinstallation failed'
        verify_resources()
        process = start()
        try:
            assert api('/v1/tasks', body)['task']['id'] == first['id']
            assert len(api('/v1/tasks')['tasks']) == 1
            assert api('/v1/knowledge')['records'][0]['id'] == memory['request_id']
        finally:
            stop(process)
    print('PASS: installed resource hashes, locked-agent refusal, reinstall, preserved tasks/knowledge and idempotency')


if __name__ == '__main__':
    main()
