import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
import app as module
from runtime import executable, media_info
from store import Store
from analysis import chunk_plan, merge_chunk, rank_candidates, transcribe


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / 'data'; data.mkdir()
    models = data / '_models'; models.mkdir()
    monkeypatch.setattr(module, 'DATA', data)
    monkeypatch.setattr(module, 'MODELS', models)
    monkeypatch.setattr(module, 'DB', Store(data / 'db.sqlite3'))
    with TestClient(module.app) as client:
        yield client


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / 'sample.mp4'
    subprocess.run([executable('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=12',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '3',
                    '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', str(path)], capture_output=True, check=True)
    return path


def upload(client, sample):
    with sample.open('rb') as file:
        response = client.post('/api/upload', files={'file': ('sample.mp4', file, 'video/mp4')})
    assert response.status_code == 200, response.text
    return response.json()['id']


def wait_job(client, jid):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = client.get('/api/jobs/' + jid).json()
        if value['status'] in ('done', 'error', 'paused', 'interrupted'):
            return value
        time.sleep(.05)
    pytest.fail('Background job did not complete in 45 seconds')


@pytest.mark.parametrize('captions,framing', [(False, 'fit'), (True, 'center')])
def test_upload_and_render(client, sample, tmp_path, captions, framing):
    assert client.get('/').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/health').json()['application'] == 'clipforge'
    pid = upload(client, sample)
    if captions:
        response = client.put(f'/api/projects/{pid}/transcript', json={'segments': [
            {'start': .1, 'end': 2.5, 'text': 'A readable caption with meaningful words.'}]})
        assert response.status_code == 200
    response = client.post(f'/api/projects/{pid}/render', json={'start': .2, 'end': 2.2,
                          'captions': captions, 'framing': framing})
    assert response.status_code == 200, response.text
    result = wait_job(client, response.json()['job_id'])
    assert result['status'] == 'done', result
    assert result['quality_checks']['caption_cues'] > 0 if captions else result['quality_checks']['caption_cues'] == 0
    response = client.get(result['url'])
    assert response.status_code == 200
    output = tmp_path / 'download.mp4'; output.write_bytes(response.content)
    info = media_info(output)
    assert abs(float(info['format']['duration']) - 2) < .3
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert (video['width'], video['height']) == (1080, 1920)
    assert any(s['codec_type'] == 'audio' for s in info['streams'])
    # Done state is persisted, not dependent on an in-memory job dictionary.
    assert Store(module.DB.path).job(response.request.url.path.split('/')[-1])['status'] == 'done'
    assert client.get('/api/storage').json()['bytes']['exports'] > 0


def test_failures_preserve_projects(client, sample):
    pid = upload(client, sample)
    response = client.post(f'/api/projects/{pid}/render', json={'start': 2, 'end': 1})
    assert response.status_code == 400
    assert client.post(f'/api/projects/{pid}/render', json={'start': 0, 'end': 2, 'captions': True}).status_code == 200
    job = module.DB.active(pid, 'render')
    if job: assert wait_job(client, job)['status'] == 'error'
    assert client.get('/api/projects/' + pid).status_code == 200
    assert client.get('/api/projects/' + pid + '/source').status_code == 200
    assert client.get('/api/jobs/missing').status_code == 404
    assert client.get('/api/download/' + pid + '/bad').status_code == 400
    assert client.post('/api/upload', files={'file': ('bad.txt', b'bad')}).status_code == 400
    assert client.post('/api/upload', files={'file': ('bad.mp4', b'not video')}).status_code == 400
    assert len(client.get('/api/projects').json()) == 1


def test_transcript_presets_feedback(client, sample):
    pid = upload(client, sample)
    assert client.put(f'/api/projects/{pid}/transcript', json={'segments': [{'start': 0, 'end': 5, 'text': 'Bad'}]}).status_code == 400
    assert client.put(f'/api/projects/{pid}/edits', json={'start': 0, 'end': 2, 'framing': 'fit'}).status_code == 200
    assert client.get(f'/api/projects/{pid}').json()['edits']['end'] == 2
    assert client.put('/api/presets/Custom', json={'start': 0, 'end': 1, 'caption_font_size': 24}).status_code == 200
    assert client.get('/api/presets').json()['Custom']['caption_font_size'] == 24
    assert 'Football Podcast Professional' in client.get('/api/presets').json()
    assert client.put('/api/storage/settings', json={'reserve_bytes': 1}).status_code == 422


def test_low_disk_does_not_delete_original(client, sample, monkeypatch):
    pid = upload(client, sample)
    def no_space(required=0): raise OSError('Low storage test')
    monkeypatch.setattr(module, 'ensure_space', no_space)
    response = client.post(f'/api/projects/{pid}/render', json={'start': 0, 'end': 1})
    result = wait_job(client, response.json()['job_id'])
    assert result['status'] == 'paused'
    assert client.get(f'/api/projects/{pid}/source').status_code == 200
    assert not list((module.DATA / pid).glob('*.mp4'))[1:]


def test_local_access_policy(client):
    assert client.get('/api/projects', headers={'Host': 'attacker.example'}).status_code == 403
    assert client.post('/api/upload', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/health', headers={'Origin': 'http://testserver'}).status_code == 200


def test_dependency_discovery(tmp_path, monkeypatch):
    from runtime import executable
    path = tmp_path / 'ffmpeg'; path.write_text('#!/bin/sh\nexit 0\n'); path.chmod(0o755)
    monkeypatch.setenv('CLIPFORGE_FFMPEG', str(path))
    assert executable('ffmpeg') == str(path)


def test_interrupted_jobs(tmp_path):
    store = Store(tmp_path / 'jobs.db')
    store.create_job('job', 'project', 'analysis', {'status': 'transcribing'})
    store.interrupt_jobs()
    assert store.job('job')['status'] == 'interrupted'
    store.cache_put('completed chunk', [1])
    assert Store(store.path).cache_get('completed chunk') == [1]


def test_overlap_word_ownership():
    plans = list(chunk_plan(20, chunk_seconds=10, overlap=2))
    first = merge_chunk(plans[0], [{'start': 9, 'end': 11, 'text': ' boundary', 'words': [{'start': 9, 'end': 11, 'word': ' boundary'}]}])
    second = merge_chunk(plans[1], [{'start': 1, 'end': 3, 'text': ' boundary', 'words': [{'start': 1, 'end': 3, 'word': ' boundary'}]}])
    assert first == []
    assert len(second) == 1
    assert second[0]['start'] == 9
    assert list(chunk_plan(12 * 3600))[-1]['core_end'] == 12 * 3600


def test_cached_transcription_and_resume(sample, tmp_path):
    store = Store(tmp_path / 'cache.db'); calls = []
    class Engine:
        def __init__(self, *args, **kwargs): calls.append('load')
        def transcribe(self, path, **kwargs):
            calls.append('transcribe')
            assert Path(path).exists()
            word = SimpleNamespace(start=0., end=1., word=' Hello.')
            return iter([SimpleNamespace(start=0., end=1., text='Hello.', words=[word])]), None
    scratch = tmp_path / 'scratch'; models = tmp_path / 'models'; models.mkdir()
    args = (sample, 3, 'fast', False, models, scratch, store, lambda **kw: None, lambda n: None)
    result = transcribe(*args, engine_factory=Engine)
    assert result[0]['text'] == 'Hello.'
    assert not (scratch / 'audio.wav').exists()
    assert transcribe(*args, engine_factory=Engine) == result
    assert calls == ['load', 'transcribe']
    # Remove only whole-transcript cache; a retry must reuse completed chunk output.
    with store.connect() as db: db.execute("DELETE FROM cache WHERE key NOT LIKE '%:chunk:%'")
    assert transcribe(*args, engine_factory=Engine) == result
    assert calls == ['load', 'transcribe', 'load']
    assert store.setting('benchmark:tiny')['measured_audio_seconds'] == 3


def test_rank_and_feedback(tmp_path):
    transcript = [{'start': i*8, 'end': (i+1)*8, 'text': ('Why is this important?' if i % 3 == 0 else 'A complete explanation with supporting evidence.')} for i in range(20)]
    candidates = rank_candidates(transcript)
    assert candidates
    for a, b in zip(candidates, candidates[1:]):
        overlap = max(0, min(a['end'], b['end']) - max(a['start'], b['start']))
        assert overlap / min(a['end']-a['start'], b['end']-b['start']) < .25
    store = Store(tmp_path / 'feedback.db')
    store.feedback('p', candidates[0]['id'], 1, candidates[0]['features'])
    assert any(v != 0 for v in store.preferences().values())
    reranked = rank_candidates(transcript, store.preferences())
    assert any(c['score'] != next(old['score'] for old in candidates if old['id'] == c['id']) for c in reranked if c['id'] in {v['id'] for v in candidates})
