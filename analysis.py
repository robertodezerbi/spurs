"""Bounded audio chunks, persistent caches and transparent candidate ranking."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import time
from runtime import executable, run, hardware, regular_files

MODES = {'fast': {'model': 'tiny', 'approx_mb': 75, 'beam_size': 1},
         'balanced': {'model': 'base', 'approx_mb': 145, 'beam_size': 3},
         'quality': {'model': 'small', 'approx_mb': 485, 'beam_size': 5}}
CHUNK_SECONDS = 180
OVERLAP = 3


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda: file.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def chunk_plan(duration, chunk_seconds=CHUNK_SECONDS, overlap=OVERLAP):
    if not math.isfinite(duration) or duration <= 0 or chunk_seconds <= 2 * overlap:
        raise ValueError('Invalid chunk configuration')
    core = 0.
    while core < duration:
        stop = min(duration, core + chunk_seconds)
        yield {'core_start': core, 'core_end': stop,
               'start': max(0., core - overlap), 'end': min(duration, stop + overlap)}
        core = stop


def merge_chunk(plan, segments):
    result = []
    # Assign each word to one non-overlapping core by midpoint. Context audio is
    # transcribed in both chunks, but overlap words are emitted only by their owner.
    for segment in segments:
        words = segment.get('words') or []
        if words:
            owned = []
            for word in words:
                a, b = word['start'] + plan['start'], word['end'] + plan['start']
                if plan['core_start'] <= (a + b) / 2 < plan['core_end']:
                    owned.append({'start': max(0, a), 'end': b, 'word': word['word']})
            if owned:
                result.append({'start': owned[0]['start'], 'end': owned[-1]['end'],
                               'text': ''.join(w['word'] for w in owned).strip(), 'words': owned})
        else:
            a, b = segment['start'] + plan['start'], segment['end'] + plan['start']
            if plan['core_start'] <= (a + b) / 2 < plan['core_end']:
                result.append({'start': a, 'end': b, 'text': segment['text'], 'words': []})
    return result


def rank_candidates(transcript, preferences=None):
    candidates = []
    weights = preferences or {}
    for index, segment in enumerate(transcript):
        start = segment['start']; parts = []
        for next_index in range(index, len(transcript)):
            nxt = transcript[next_index]
            duration = nxt['end'] - start
            if duration > 75:
                break
            parts.append(nxt['text'])
            if duration < 15:
                continue
            text = ' '.join(parts)
            # These are observable language cues, not verified semantics.
            complete = bool(re.search(r'[.!?][\"\u201d\u2019]?$', text.strip()))
            if not complete:
                continue
            begins_dependent = bool(re.match(r'(?i)^(and|but|because|so|this|that|they|it)\b', text.strip()))
            features = {'boundary': float(complete and not begins_dependent),
                        'density': min(1., len(text.split()) / max(duration * 2.5, 1)),
                        'hook_cue': float('?' in parts[0] or bool(re.search(r'(?i)\b(why|how|key|important|problem)\b', parts[0]))),
                        'duration_fit': max(0., 1 - abs(duration - 40) / 40)}
            base = {'boundary': .4, 'density': .25, 'hook_cue': .15, 'duration_fit': .2}
            score = sum((base[k] + weights.get(k, 0)) * v for k, v in features.items())
            candidates.append({'id': hashlib.sha256(f'{start}:{nxt["end"]}:{text}'.encode()).hexdigest()[:16],
                               'start': start, 'end': nxt['end'], 'score': round(score, 3),
                               'text': text, 'features': features, 'ranking': 'heuristic',
                               'review_required': True})
            if duration >= 40:
                break
    candidates.sort(key=lambda item: item['score'], reverse=True)
    selected = []
    for candidate in candidates:
        if all(max(0, min(candidate['end'], prior['end']) - max(candidate['start'], prior['start'])) /
               min(candidate['end'] - candidate['start'], prior['end'] - prior['start']) < .25 for prior in selected):
            selected.append(candidate)
        if len(selected) == 8:
            break
    return selected


def model_path(root, name):
    return Path(root) / ('models--Systran--faster-whisper-' + name)


def model_inventory(root):
    result = []
    for mode, config in MODES.items():
        directory = model_path(root, config['model'])
        # Faster-whisper's local_files_only validates the actual snapshot on load.
        installed = directory.is_dir() and any(directory.glob('snapshots/*/model.bin'))
        size = sum(info.st_size for _,info in regular_files(directory)) if directory.exists() else 0
        ram = hardware(root)['ram_bytes']
        required_ram = {'tiny': 1024**3, 'base': 2*1024**3, 'small': 4*1024**3}[config['model']]
        result.append(dict(config, mode=mode, cached=installed, bytes=size,
                           compatible=ram is None or ram >= required_ram, minimum_ram_bytes=required_ram,
                           backend='faster-whisper / CPU (int8 preferred; float32 fallback)', metal=False))
    return result


def transcribe(path, duration, mode, allow_download, model_root, scratch, store, update, ensure_space, engine_factory=None):
    config = MODES[mode]
    compute_type='int8'
    if engine_factory is None:
        import ctranslate2
        supported=ctranslate2.get_supported_compute_types('cpu')
        if 'int8' not in supported:compute_type='float32'
    info = hardware(model_root)
    required_ram = {'tiny': 1024**3, 'base': 2*1024**3, 'small': 4*1024**3}[config['model']]
    if info['ram_bytes'] is not None and info['ram_bytes'] < required_ram:
        raise ValueError('Insufficient RAM for this mode. Select Fast or Balanced instead.')
    digest = fingerprint(path)
    version = importlib.metadata.version('faster-whisper') if engine_factory is None else 'test'
    identity = f'whisper-v2:{version}:{digest}:{config["model"]}:{config["beam_size"]}:{compute_type}:{CHUNK_SECONDS}'
    cached = store.cache_get(identity)
    if cached is not None:
        update(status='analyzing', progress='Reusing cached transcript')
        return cached
    inventory = next(m for m in model_inventory(model_root) if m['mode'] == mode)
    if not inventory['cached'] and not allow_download and engine_factory is None:
        raise ValueError(f"{config['model']} is not cached. Enable model-download consent or choose a cached model.")
    ensure_space((0 if inventory['cached'] else config['approx_mb'] * 1024 * 1024) + 64 * 1024 * 1024)
    update(status='loading model', progress=f'{config["model"]}: approximately {config["approx_mb"]} MB if not cached; CPU {compute_type}')
    if engine_factory is None:
        from faster_whisper import WhisperModel
        engine_factory = WhisperModel
    engine = engine_factory(config['model'], device='cpu', compute_type=compute_type,
                            download_root=str(model_root), local_files_only=not allow_download,
                            cpu_threads=max(1, min(4, (os.cpu_count() or 2) - 1)))
    transcript = []
    plan_list = list(chunk_plan(duration))
    Path(scratch).mkdir(exist_ok=True)
    measured_seconds, measured_audio = 0., 0.
    for index, plan in enumerate(plan_list):
        chunk_key = identity + f':chunk:{index}'
        chunk = store.cache_get(chunk_key)
        if chunk is None:
            ensure_space(32 * 1024 * 1024)
            wav = Path(scratch) / 'audio.wav'
            before = time.monotonic()
            try:
                run([executable('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-ss', str(plan['start']),
                     '-i', str(path), '-t', str(plan['end'] - plan['start']), '-vn', '-ac', '1',
                     '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
                segments, _ = engine.transcribe(str(wav), beam_size=config['beam_size'],
                                                word_timestamps=True, vad_filter=True)
                serial = []
                for segment in segments:
                    serial.append({'start': segment.start, 'end': segment.end, 'text': segment.text,
                                   'words': [{'start': w.start, 'end': w.end, 'word': w.word} for w in (segment.words or [])]})
                chunk = merge_chunk(plan, serial)
                store.cache_put(chunk_key, chunk)
                measured_seconds += time.monotonic() - before
                measured_audio += plan['core_end'] - plan['core_start']
                store.set_setting('benchmark:' + config['model'], {'seconds_per_audio_second': measured_seconds / measured_audio,
                                  'hardware': hardware(model_root), 'measured_audio_seconds': measured_audio})
            finally:
                wav.unlink(missing_ok=True)
        transcript.extend(chunk)
        remaining = duration - plan['core_end']
        eta = round(remaining * measured_seconds / measured_audio) if measured_audio else None
        update(status='transcribing', progress=f'Chunk {index + 1}/{len(plan_list)}', estimated_seconds_remaining=eta)
    # Ownership prevents duplicate overlap words. Clamp rare model timestamp overrun.
    transcript = [{**s, 'start': max(0, s['start']), 'end': min(duration, s['end'])} for s in transcript if s['start'] < duration and s['end'] > s['start']]
    store.cache_put(identity, transcript)
    return transcript
