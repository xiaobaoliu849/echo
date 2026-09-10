"""Extract the NSIS application payload and smoke-test the files it installs.

Avoids replacing the user's installed copy or changing uninstall registry keys.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('installer', type=Path)
    args = parser.parse_args()
    installer = args.installer.resolve()
    seven_zip = ROOT / 'electron/node_modules/electron-winstaller/vendor/7z-x64.exe'
    with tempfile.TemporaryDirectory(prefix='Echo installed 中文 ') as temporary:
        folder = Path(temporary)
        for command in (
            [str(seven_zip), 'x', str(installer), f'-o{folder / "nsis"}', '-y'],
            [str(seven_zip), 'x', str(folder / 'nsis/$PLUGINSDIR/app-64.7z'), f'-o{folder / "app"}', '-y'],
        ):
            subprocess.run(command, check=True, capture_output=True, timeout=120)
        installed = folder / 'app'
        # Verify the installer contains precisely the code/resources already tested.
        for relative in ('resources/app.asar', 'resources/frontend/dist/index.html',
                         'resources/backend-dist/voicespirit-backend.exe'):
            expected = ROOT / 'electron/dist/win-unpacked' / relative
            assert hashlib.sha256((installed / relative).read_bytes()).digest() == hashlib.sha256(expected.read_bytes()).digest(), relative
        subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_desktop.py'),
                        '--resources', str(installed / 'resources'),
                        '--electron', str(installed / 'Echo.exe')], check=True, timeout=120)
    print(f'PASS: installer payload verified: {installer.name}')


if __name__ == '__main__':
    main()
