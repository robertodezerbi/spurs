"""Reproducible low-complexity long-media test; no speech accuracy claim."""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime import executable


def main():
    duration=31*60;started=time.monotonic();report={'source_duration_seconds':duration,'fixture':'160×90, 2 fps, static color + sine audio',
        'transcription':'controlled engine; real bounded FFmpeg extraction, not real Whisper inference'}
    with tempfile.TemporaryDirectory(prefix='clipforge-long-') as temp:
        root=Path(temp);os.environ['CLIPFORGE_DATA_DIR']=str(root/'data')
        from fastapi.testclient import TestClient
        import app
        from analysis import transcribe
        source=root/'long.mp4'
        subprocess.run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x90:r=2',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t',str(duration),'-c:v','libx264','-threads','1',
            '-c:a','aac','-b:a','32k',str(source)],capture_output=True,check=True)
        report['source_bytes']=source.stat().st_size;report['generation_seconds']=round(time.monotonic()-started,2)
        tracemalloc.start()
        with TestClient(app.app) as client:
            before=time.monotonic()
            with source.open('rb') as file:response=client.post('/api/upload',files={'file':('long.mp4',file,'video/mp4')})
            assert response.status_code==200,response.text
            pid=response.json()['id'];assert abs(response.json()['duration']-duration)<1
            report['upload_seconds']=round(time.monotonic()-before,2)
            calls=[]
            class Engine:
                def __init__(self,*args,**kwargs):pass
                def transcribe(self,path,**kwargs):
                    calls.append(Path(path).stat().st_size)
                    word=SimpleNamespace(start=4.,end=5.,word=' bounded chunk.')
                    return iter([SimpleNamespace(start=4.,end=5.,text='bounded chunk.',words=[word])]),None
            scratch=root/'scratch';scratch.mkdir();before=time.monotonic()
            source_path=app.folder(pid)/response.json()['source']
            args=(source_path,duration,'fast',False,app.MODELS,scratch,app.DB,lambda **kw:None,app.ensure_space)
            transcript=transcribe(*args,engine_factory=Engine)
            assert len(calls)==11 and len(transcript)==11
            assert max(calls)<=186*16000*2+1024
            assert all(a['end']<=b['start'] for a,b in zip(transcript,transcript[1:]))
            assert transcribe(*args,engine_factory=Engine)==transcript and len(calls)==11
            report.update(chunks_extracted=len(calls),largest_chunk_bytes=max(calls),chunk_and_cache_seconds=round(time.monotonic()-before,2))
            before=time.monotonic()
            result=client.post(f'/api/projects/{pid}/render',json={'start':duration-5,'end':duration,'vertical':True})
            assert result.status_code==200,result.text
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                job=client.get('/api/jobs/'+result.json()['job_id']).json()
                if job['status'] in ('done','error','paused'):break
                time.sleep(.1)
            assert job['status']=='done',job
            assert client.get(job['url']).status_code==200
            report['end_of_source_export_seconds']=round(time.monotonic()-before,2)
            report['output_checks']=job['quality_checks']
            report['python_traced_peak_bytes']=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
        unit=1 if sys.platform=='darwin' else 1024
        report['process_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*unit
        report['largest_child_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss*unit
        report['memory_note']='Separate peak RSS values, not summed concurrent memory; traced memory excludes native allocations.'
    report['total_seconds']=round(time.monotonic()-started,2);report['status']='passed'
    artifact=Path(__file__).resolve().parents[1]/'artifacts';artifact.mkdir(exist_ok=True)
    (artifact/'long-video.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
