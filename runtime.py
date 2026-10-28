"""Portable dependency discovery, hardware facts and export validation."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def executable(name):
    override = os.getenv('CLIPFORGE_' + name.upper())
    candidates = [override] if override else []
    candidates += [shutil.which(name), '/opt/homebrew/bin/' + name,
                   '/usr/local/bin/' + name, '/usr/bin/' + name]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise RuntimeError(f'{name} is missing. Install FFmpeg (brew install ffmpeg on macOS), '
                       f'or set CLIPFORGE_{name.upper()} to its executable path, then run Repair ClipForge.')


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} failed ({result.returncode}): {result.stderr[-2500:]}')
    return result.stdout


def media_info(path):
    return json.loads(run([executable('ffprobe'), '-v', 'error', '-show_format',
                           '-show_streams', '-of', 'json', str(path)], timeout=60))


def validate_export(path, duration, vertical, expect_audio):
    info = media_info(path)
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    if not video or video.get('codec_name') != 'h264':
        raise RuntimeError('Export validation failed: missing H.264 video')
    actual = float(info['format'].get('duration', 0))
    if abs(actual - duration) > max(.35, duration * .02):
        raise RuntimeError(f'Export duration mismatch: expected {duration:.2f}s, got {actual:.2f}s')
    if vertical and (video['width'], video['height']) != (1080, 1920):
        raise RuntimeError('Export validation failed: expected 1080×1920')
    if expect_audio and not any(s['codec_type'] == 'audio' for s in info['streams']):
        raise RuntimeError('Export validation failed: source audio is missing')
    # Decode every packet: FFprobe metadata alone cannot establish file integrity.
    run([executable('ffmpeg'), '-v', 'error', '-xerror', '-i', str(path),
         '-f', 'null', '-'], timeout=max(120, duration * 4))
    return {'duration': actual, 'width': video['width'], 'height': video['height'],
            'integrity': 'decoded successfully', 'editorial_review': 'Manual review required'}


def hardware(path):
    ram = None
    try:
        ram = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (ValueError, OSError, AttributeError):
        if platform.system() == 'Darwin':
            ram = int(run(['sysctl', '-n', 'hw.memsize']))
    return {'os': platform.system(), 'architecture': platform.machine(),
            'apple_silicon': platform.system() == 'Darwin' and platform.machine() == 'arm64',
            'cpu_count': os.cpu_count(), 'ram_bytes': ram,
            'free_storage_bytes': shutil.disk_usage(path).free}


def diagnostics(path):
    report = {'hardware': hardware(path), 'dependencies': {}, 'ok': True}
    for name in ('ffmpeg', 'ffprobe'):
        try:
            binary = executable(name)
            report['dependencies'][name] = {'path': binary, 'version': run([binary, '-version'], timeout=10).splitlines()[0]}
        except Exception as exc:
            report['ok'] = False
            report['dependencies'][name] = {'error': str(exc)}
    if report['ok']:
        filters = run([executable('ffmpeg'), '-filters'], timeout=10)
        encoders = run([executable('ffmpeg'), '-encoders'], timeout=10)
        report['subtitles'] = ' subtitles ' in filters
        report['libx264'] = 'libx264' in encoders
        report['videotoolbox_available'] = 'h264_videotoolbox' in encoders
        report['ok'] = report['libx264']
    return report
