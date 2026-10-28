"""Read-only diagnostics plus a disposable real render; no destructive repair."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

from runtime import diagnostics, executable, run, validate_export


def report(directory, port=8000):
    result = diagnostics(directory)
    result['python'] = {'version': sys.version, 'executable': sys.executable,
                        'isolated': sys.prefix != sys.base_prefix,
                        'supported': (3, 10) <= sys.version_info[:2] < (3, 13)}
    check = subprocess.run([sys.executable, '-m', 'pip', 'check'], capture_output=True, text=True)
    result['packages'] = {'ok': check.returncode == 0, 'details': check.stdout + check.stderr}
    from bootstrap import expected_packages
    mismatches=[]
    for package,wanted in expected_packages(Path(__file__).resolve().parent/'requirements.txt').items():
        try: actual=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:actual='not installed'
        if actual!=wanted:mismatches.append({'package':package,'expected':wanted,'actual':actual})
    result['packages']['version_mismatches']=mismatches
    if mismatches:result['packages']['ok']=False
    try:
        import cv2,numpy
        from vision import FaceDetector
        FaceDetector()
        result['vision']={'opencv':cv2.__version__,'numpy':numpy.__version__,'bundled_detector':'loaded'}
    except Exception as exc:
        result['vision']={'error':str(exc)};result['ok']=False
    for package in ('fastapi', 'uvicorn', 'python-multipart', 'faster-whisper'):
        try: result.setdefault('versions', {})[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: result.setdefault('versions', {})[package] = 'not installed'
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port)); result['port'] = {'number': port, 'available': True}
        except OSError:
            result['port'] = {'number': port, 'available': False, 'action': 'Close the server or select CLIPFORGE_PORT'}
    try:
        with tempfile.TemporaryDirectory(prefix='clipforge-diagnostic-', dir=directory) as temp:
            path = Path(temp) / 'test.mp4'
            run([executable('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=180x320:r=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264', '-threads', '2',
                 '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)], timeout=60)
            result['render_test'] = validate_export(path, 1, False, True)
            result['storage_writable'] = True
    except Exception as exc:
        result['render_test'] = {'error': str(exc)}; result['ok'] = False
    result['ok'] = bool(result['ok'] and result['python']['supported'] and result['packages']['ok'])
    result['notes'] = 'No original media, model, project or environment was changed. Port use may be an already-running ClipForge.'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write a new diagnostic report; existing files are never overwritten')
    args = parser.parse_args()
    root = Path(os.getenv('CLIPFORGE_DATA_DIR', str(Path(__file__).resolve().parent / 'data'))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    result = report(root, int(os.getenv('CLIPFORGE_PORT', '8000')))
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        with args.output.open('x') as file: file.write(text + '\n')
    sys.exit(0 if result['ok'] else 1)
