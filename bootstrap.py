"""Repeatable first-run Python setup. Never installs OS software or removes a venv."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def expected_packages(path):
    return dict(line.strip().split('==', 1) for line in path.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith('#'))


def verify_python():
    if not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError('ClipForge requires Python 3.10–3.12. Install python@3.12 using your existing Homebrew or python.org.')


def environment_ready(python, requirements=ROOT / 'requirements.txt'):
    code = ('import importlib.metadata as m, json; '
            'expected=json.loads(' + repr(json.dumps(expected_packages(requirements))) + '); '
            'assert all(m.version(k)==v for k,v in expected.items()); '
            'import fastapi, uvicorn, multipart, cv2, numpy')
    return subprocess.run([str(python), '-c', code], capture_output=True).returncode == 0


def prepare(root=ROOT):
    verify_python()
    from runtime import diagnostics
    report = diagnostics(root)
    if not report['ok']:
        raise RuntimeError('FFmpeg/FFprobe check failed:\n' + json.dumps(report, indent=2))
    venv = root / '.venv'; python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        if venv.exists():
            raise RuntimeError('An incomplete .venv already exists. Run Repair ClipForge; no files were removed. Rename it as a backup before retrying.')
        subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
    # Never silently replace an incompatible/user-maintained Python environment.
    subprocess.run([str(python), '-c', 'import sys; assert (3,10)<=sys.version_info[:2]<(3,13), "Incompatible .venv Python; preserve it and recreate with Python 3.10–3.12"'], check=True)
    if not environment_ready(python, root / 'requirements.txt'):
        print('Installing pinned core packages into .venv. No AI model will be downloaded.', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    if not environment_ready(python, root / 'requirements.txt'):
        raise RuntimeError('Installed packages did not pass import/version checks. Run Repair ClipForge.')
    stamp = hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest()
    (venv / 'clipforge-requirements').write_text(stamp + '\n')
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true')
    args = parser.parse_args()
    # Prevent concurrent installers mutating the same .venv; lock file is retained.
    with (ROOT / '.bootstrap.lock').open('a') as lock:
        if os.name == 'posix':
            import fcntl
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('Another ClipForge installation is running. Wait for it to finish.')
        python = prepare()
    if args.launch:
        os.execv(str(python), [str(python), str(ROOT / 'launcher.py')])


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print(f'First-run setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
