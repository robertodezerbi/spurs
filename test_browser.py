"""Real Chromium UI → timeline editing → captioned export smoke test.
Use CLIPFORGE_CHROMIUM to select an existing browser; no browser download occurs.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import httpx
import pytest
from playwright.sync_api import sync_playwright, expect
from test_app import sample
import app as module


def test_browser_timeline_to_export(sample,tmp_path):
    browser_path=os.getenv('CLIPFORGE_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome') or (str(Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')) if Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file() else None)
    if not browser_path:pytest.skip('Install an authorized Chromium browser or set CLIPFORGE_CHROMIUM to run the UI gate')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    environment=dict(os.environ,CLIPFORGE_NO_BROWSER='1',CLIPFORGE_PORT=str(port),CLIPFORGE_DATA_DIR=str(tmp_path/'browser-data'))
    errors=[]
    with (tmp_path/'browser-server.log').open('w+') as log:
        server=subprocess.Popen([sys.executable,'launcher.py'],cwd=module.ROOT,env=environment,stdout=log,stderr=log)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=5) as client:
                for _ in range(150):
                    try:
                        if client.get('/api/health').status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.1)
                else:pytest.fail('Browser test server failed to start')
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=browser_path,headless=True,args=['--no-sandbox'])
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{port}')
                    page.locator('#upload').set_input_files(str(sample))
                    expect(page.locator('#title')).to_have_text('sample.mp4',timeout=15000)
                    for _ in range(100):
                        if page.locator('#video').evaluate('(el) => el.readyState')>=1:break
                        time.sleep(.1)
                    else:pytest.fail('Source video metadata did not load')
                    page.locator('#start').fill('0.2');page.locator('#end').fill('2.8')
                    page.locator('#addTimeline').click()
                    expect(page.locator('.timelineClip')).to_have_count(1)
                    page.evaluate('clipTimeline.seek(.9)')
                    page.locator('#timelineSplit').click()
                    expect(page.locator('.timelineClip')).to_have_count(2)
                    page.locator('#timelineUndo').click();expect(page.locator('.timelineClip')).to_have_count(1)
                    page.locator('#timelineRedo').click();expect(page.locator('.timelineClip')).to_have_count(2)
                    # Real pointer drag on a source trim handle.
                    handle=page.locator('.timelineClip').nth(1).locator('.trimHandle.end').bounding_box()
                    page.mouse.move(handle['x']+handle['width']/2,handle['y']+15);page.mouse.down()
                    page.mouse.move(handle['x']-8,handle['y']+15,steps=5);page.mouse.up()
                    assert page.evaluate('clipTimeline.clips[1].end')<2.8
                    first_before=page.evaluate('clipTimeline.clips[0].id')
                    page.locator('#timelineLeft').click()
                    assert page.evaluate('clipTimeline.clips[0].id')!=first_before
                    page.locator('#timelineSave').click()
                    expect(page.locator('#timelineSaved')).to_have_text('Saved locally')
                    project=client.get('/api/projects').json()[0];pid=project['id']
                    assert len(project['timeline']['clips'])==2
                    page.locator('#waveform').click()
                    expect(page.locator('#status')).to_have_text('Source waveform generated and cached.',timeout=20000)
                    page.get_by_text('Transcript corrections',exact=True).click()
                    page.locator('#transcriptEditor').fill(json.dumps([{'start':0,'end':3,'text':'Browser caption check.'}]))
                    page.locator('#saveTranscript').click()
                    expect(page.locator('#status')).to_have_text('Transcript corrections saved. Re-run semantic review to refresh suggestions.')
                    page.locator('summary').filter(has_text='Captions').click()
                    page.locator('#captions').check();page.locator('#captionAnimation').select_option('fade')
                    page.locator('#timelineExport').click()
                    expect(page.locator('#status')).to_contain_text('Timeline export passed technical validation',timeout=60000)
                    expect(page.locator('#exports a')).to_have_count(1)
                    url=page.locator('#exports a').get_attribute('href')
                    assert client.get(url).status_code==200
                    # Reopen the project to verify the saved edit decision list and export history.
                    page.locator('#projects button').first.click()
                    expect(page.locator('.timelineClip')).to_have_count(2)
                    expect(page.locator('#exports a')).to_have_count(1)
                    artifact=module.ROOT/'artifacts';artifact.mkdir(exist_ok=True)
                    page.screenshot(path=str(artifact/'studio.png'),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2')
                    page.screenshot(path=str(artifact/'studio-mobile.png'),full_page=True)
                    assert not errors,errors
                    browser.close()
        finally:
            server.terminate();server.wait(timeout=15)
