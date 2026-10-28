import subprocess
from pathlib import Path
from fastapi.testclient import TestClient
from app import app

def test_upload_and_render(tmp_path):
    sample=tmp_path/'sample.mp4'
    subprocess.run(['ffmpeg','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=10','-f','lavfi','-i','anullsrc','-t','2','-c:v','libx264','-c:a','aac',str(sample)],capture_output=True,check=True)
    with TestClient(app) as client:
        with sample.open('rb') as f:
            r=client.post('/api/upload',files={'file':('sample.mp4',f,'video/mp4')})
        assert r.status_code==200,r.text
        pid=r.json()['id']
        r=client.post(f'/api/projects/{pid}/render',json={'start':0,'end':1,'vertical':True,'captions':False})
        assert r.status_code==200,r.text
        import time
        for _ in range(100):
            j=client.get('/api/jobs/'+r.json()['job_id']).json()
            if j['status'] in ('done','error'):break
            time.sleep(.2)
        assert j['status']=='done',j
        assert client.get(j['url']).status_code==200
