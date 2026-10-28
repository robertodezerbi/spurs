"""Loopback-only launcher. Browser opens only after our server answers health checks."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    from runtime import diagnostics
    report = diagnostics(root)
    if not report['ok']:
        raise RuntimeError(json.dumps(report, indent=2))
    port = int(os.getenv('CLIPFORGE_PORT', '8000'))
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is already in use. Close the other server or set CLIPFORGE_PORT.') from exc
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)], cwd=root)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f'http://127.0.0.1:{port}'
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError(f'ClipForge exited during startup ({process.returncode}). See the error above.')
            try:
                with opener.open(url + '/api/health', timeout=1) as response:
                    if json.load(response).get('application') == 'clipforge':
                        break
            except (OSError, ValueError):
                time.sleep(.2)
        else:
            raise RuntimeError('ClipForge did not become ready within 30 seconds.')
        print(f'ClipForge is ready at {url}. Press Control+C to stop.', flush=True)
        if os.getenv('CLIPFORGE_NO_BROWSER') != '1':
            webbrowser.open(url)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Cannot start ClipForge: {exc}', file=sys.stderr)
        sys.exit(1)
