"""Run the real frozen backend / Electron with a fresh profile and minimal PATH.

Usage: python scripts/smoke_desktop.py [--resources PATH] [--electron PATH]
Requires the packaging environment (httpx and websockets). No paid API calls.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def clean_env(profile: Path, resources: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
        ('ECHO_', 'VOICESPIRIT_', 'PYTHON', 'VITE_', 'ELECTRON_', 'CONDA')
    ) and k.upper() != 'PATH'}
    env.update({
        'ECHO_DATA_DIR': str(profile), 'VOICESPIRIT_DATA_DIR': str(profile),
        'ECHO_DESKTOP_USER_DATA_DIR': str(profile), 'PYTHONUTF8': '1',
        'VOICESPIRIT_FRONTEND_DIST': str(resources / 'frontend' / 'dist'),
        'PATH': os.pathsep.join([str(resources / 'media-tools'),
                                 str(Path(os.environ['SystemRoot']) / 'System32'),
                                 os.environ['SystemRoot']]),
    })
    return env


def assert_free(port: int) -> None:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


def wait_http(client: httpx.Client, url: str, process: subprocess.Popen, timeout: int = 60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Process exited early: {process.returncode}; see smoke log')
        try:
            response = client.get(url)
            if response.is_success:
                return response
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f'Not ready: {url}')


def check_http(client: httpx.Client, instance: str | None = None) -> None:
    runtime = client.get('http://127.0.0.1:8000/').json()
    assert runtime['name'] == 'Echo API', runtime
    if instance:
        assert runtime['desktop_instance_id'] == instance
    assert not runtime['auth_enabled'], 'Fresh profile unexpectedly contains auth configuration'
    assert client.get('http://127.0.0.1:8000/health').json()['status'] == 'healthy'
    page = client.get('http://127.0.0.1:8000/app/')
    page.raise_for_status()
    assert '<div id="root">' in page.text
    assets = re.findall(r'(?:src|href)="(\./assets/[^\"]+)"', page.text)
    assert assets, 'No production assets referenced'
    for asset in assets:
        client.get('http://127.0.0.1:8000/app/' + asset.removeprefix('./')).raise_for_status()
    client.get('http://127.0.0.1:8000/api/settings/').raise_for_status()
    # Exercise the bundled WebSocket protocol, without contacting a provider.
    with connect('ws://127.0.0.1:8000/api/transcription/realtime', open_timeout=5) as ws:
        # Connect/disconnect without configuration or audio: no paid upstream.
        pass


def check_media(resources: Path, env: dict[str, str], cwd: Path) -> None:
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        result = subprocess.run([str(resources / 'media-tools' / name), '-version'],
                                env=env, cwd=cwd, capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr.decode(errors='replace')
    sample = cwd / 'smoke.wav'
    subprocess.run([str(resources / 'media-tools' / 'ffmpeg.exe'), '-v', 'error',
                    '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono', '-t', '0.1', str(sample)],
                   env=env, check=True, capture_output=True, timeout=15)
    probe = subprocess.run([str(resources / 'media-tools' / 'ffprobe.exe'), '-v', 'error',
                            '-show_entries', 'format=duration', '-of', 'json', str(sample)],
                           env=env, check=True, capture_output=True, timeout=15)
    assert float(json.loads(probe.stdout)['format']['duration']) > 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--resources', type=Path,
                        default=ROOT / 'electron/dist/win-unpacked/resources')
    parser.add_argument('--electron', type=Path)
    args = parser.parse_args()
    resources = args.resources.resolve()
    def resource_snapshot():
        return {str(p.relative_to(resources)): (p.stat().st_size, p.stat().st_mtime_ns) if p.is_file() else 'directory'
                for p in resources.rglob('*')}

    resources_before = resource_snapshot()
    assert_free(8000)
    output = ROOT / 'output'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='Echo smoke 中文 ') as temporary:
        profile = Path(temporary)
        env = clean_env(profile, resources)
        # An installed build must ignore a developer's global NODE_ENV.
        env['NODE_ENV'] = 'development'
        check_media(resources, env, profile)
        instance = uuid.uuid4().hex
        env['ECHO_DESKTOP_INSTANCE_ID'] = instance
        command = [str(resources / 'backend-dist/voicespirit-backend.exe')]
        debug_port = None
        if args.electron:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                debug_port = sock.getsockname()[1]
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                main_port = sock.getsockname()[1]
            command = [str(args.electron.resolve()), '--smoke-test', f'--remote-debugging-port={debug_port}',
                       f'--inspect=127.0.0.1:{main_port}']
        log_path = output / ('electron-smoke.log' if args.electron else 'backend-smoke.log')
        with log_path.open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, env=env, cwd=profile, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                with httpx.Client(timeout=2, trust_env=False) as client:
                    wait_http(client, 'http://127.0.0.1:8000/', process)
                    check_http(client, None if args.electron else instance)
                    if debug_port:
                        tabs_url = f'http://127.0.0.1:{debug_port}/json'
                        wait_http(client, tabs_url, process)
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            pages = [t for t in client.get(tabs_url).json()
                                     if t.get('type') == 'page' and '/app/' in t.get('url', '')]
                            if pages:
                                break
                            time.sleep(0.2)
                        assert pages, 'Electron did not navigate to the HTTP app'
                        with connect(pages[0]['webSocketDebuggerUrl']) as ws:
                            sequence = 0

                            def cdp(method, params=None):
                                nonlocal sequence
                                sequence += 1
                                ws.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
                                while True:
                                    message = json.loads(ws.recv(timeout=15))
                                    if message.get('id') == sequence:
                                        assert 'error' not in message, message
                                        return message.get('result', {})

                            expression = '''(async () => {
                              // CDP may list the destination URL before the
                              // initial about:blank execution context is gone.
                              if (location.origin !== 'http://127.0.0.1:8000' ||
                                  !window.electronAPI || !document.getElementById('root')) {
                                return {pending: true};
                              }
                              const health = await (await fetch('/health')).json();
                              const version = await window.electronAPI.getAppVersion();
                              const root = document.getElementById('root');
                              return {health: health.status, version, electron: window.isElectron,
                                chatLoaded: !!root.querySelector('textarea'),
                                buttons: root.querySelectorAll('button').length,
                                text: root.innerText.slice(0, 1000)};
                            })()'''
                            for attempt in range(60):
                                evaluated = cdp('Runtime.evaluate', {'expression': expression,
                                    'awaitPromise': True, 'returnByValue': True})
                                assert 'exceptionDetails' not in evaluated, evaluated
                                result = evaluated['result'].get('value', {})
                                if result.get('chatLoaded'):
                                    break
                                time.sleep(0.25)
                            assert result.get('electron') and result.get('health') == 'healthy', result
                            assert result.get('chatLoaded'), result
                            screenshot = cdp('Page.captureScreenshot', {'format': 'png'})
                            (output / 'electron-smoke.png').write_bytes(base64.b64decode(screenshot['data']))
                            print(json.dumps(result, ensure_ascii=True))
                        # app.quit() takes the normal Electron quit path; a
                        # force-kill would conceal broken backend cleanup.
                        targets = client.get(f'http://127.0.0.1:{main_port}/json').json()
                        with connect(targets[0]['webSocketDebuggerUrl']) as ws:
                            ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                'params': {'expression': "process.mainModule.require('electron').app.quit()"}}))
                            # Wait for evaluation, then disconnect so the Node
                            # inspector does not hold the quitting process open.
                            try:
                                reply = json.loads(ws.recv(timeout=5))
                                assert 'exceptionDetails' not in reply.get('result', {}), reply
                            except EOFError:
                                pass
                        process.wait(timeout=15)
                        assert process.returncode == 0, process.returncode
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            try:
                                assert_free(8000)
                                break
                            except OSError:
                                time.sleep(0.2)
                        assert_free(8000)
            finally:
                if process.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=10)
                    process.wait(timeout=10)
                startup_log = profile / 'logs/desktop-startup.log'
                if startup_log.exists():
                    shutil.copy2(startup_log, output / 'desktop-startup-smoke.log')
        assert resource_snapshot() == resources_before, 'Application wrote into installation resources'
        print(f'PASS: {"Electron UI + IPC + shutdown" if args.electron else "frozen backend"}, HTTP assets and bundled audio tools. Log: {log_path}')


if __name__ == '__main__':
    main()
