"""Experimental audio-gated mouth-motion tracking with conservative framing.

Haar faces + temporal matching are local and lightweight. This is not a learned
speaker diarization model. Uncertain multi-face scenes fall back to full-image fit.
"""
import math
from pathlib import Path
import subprocess
import tempfile
import numpy as np

from runtime import executable, media_info

FPS = 4
FRAME_W, FRAME_H = 640, 360


class FaceDetector:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.classifier = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if self.classifier.empty(): raise RuntimeError('OpenCV bundled face detector is unavailable')

    def detect(self, frame):
        return [tuple(int(v) for v in box) for box in self.classifier.detectMultiScale(
            frame, scaleFactor=1.1, minNeighbors=5, minSize=(28, 28))]


def overlap(a, b):
    x = max(0, min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]))
    y = max(0, min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
    area = x*y
    return area / max(1, a[2]*a[3]+b[2]*b[3]-area)


class SpeakerTracker:
    def __init__(self):
        self.tracks = {}; self.next_id = 0; self.speaker = None; self.challenger = None; self.streak = 0

    def observe(self, gray, boxes, audio_rms):
        import cv2
        current = {}; used = set()
        for box in boxes:
            matches = [(overlap(box, prior['box']), ident) for ident,prior in self.tracks.items() if ident not in used]
            score, ident = max(matches, default=(0, -1))
            if score < .2: ident = self.next_id; self.next_id += 1
            used.add(ident); x,y,w,h = box
            face = gray[y:y+h, x:x+w]
            if face.size == 0: continue
            face = cv2.resize(face, (48, 48))
            prior = self.tracks.get(ident); motion = 0.
            if prior is not None:
                delta = np.abs(face.astype(np.float32)-prior['face'].astype(np.float32)) / 255
                motion = max(0., float(delta[28:44,10:38].mean()) - .7*float(delta[4:22,8:40].mean()))
            smoothed = .6*(prior['motion'] if prior else 0) + .4*motion
            current[ident] = {'box': box, 'face': face, 'motion': smoothed}
        ranked = sorted(current, key=lambda ident: current[ident]['motion'], reverse=True)
        possible = ranked[0] if ranked and audio_rms > .008 and current[ranked[0]]['motion'] > .018 else None
        if len(ranked) > 1 and possible is not None:
            if current[ranked[0]]['motion'] < current[ranked[1]]['motion'] * 1.4: possible = None
        if possible == self.challenger: self.streak += 1
        else: self.challenger = possible; self.streak = 1
        if self.streak >= 3: self.speaker = possible
        if self.speaker not in current: self.speaker = None
        self.tracks = current
        return [{'id': ident, 'box': list(track['box']), 'mouth_motion': round(track['motion'],4),
                 'active_speaker_candidate': ident == self.speaker} for ident,track in current.items()]


def read_exact(pipe, count):
    data = bytearray()
    while len(data) < count:
        block = pipe.read(count-len(data))
        if not block: break
        data.extend(block)
    return bytes(data)


def analyze_video(path, start, end, update=lambda **kw: None, detector=None):
    if end <= start: raise ValueError('Invalid vision interval')
    detector = detector or FaceDetector()
    streams = media_info(path)['streams']
    video = next(s for s in streams if s['codec_type']=='video')
    width, height = video['width'], video['height']
    rotation = next((abs(int(s.get('rotation',0))) for s in video.get('side_data_list',[]) if 'rotation' in s), 0)
    if rotation % 180 == 90: width,height = height,width
    scale = min(FRAME_W/width,FRAME_H/height); content_w=width*scale; pad_x=(FRAME_W-content_w)/2
    command = [executable('ffmpeg'), '-nostdin', '-v', 'error', '-ss', str(start), '-i', str(path), '-t', str(end-start)]
    vf = f'fps={FPS},scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=decrease,pad={FRAME_W}:{FRAME_H}:(ow-iw)/2:(oh-ih)/2,format=gray'
    processes = []; points=[]; tracker=SpeakerTracker(); count=0; unsafe=0; detected=0; active=0
    with tempfile.TemporaryFile() as errors:
        try:
            frames = subprocess.Popen(command + ['-an','-threads','1','-filter_threads','1','-vf',vf,'-f','rawvideo','pipe:1'], stdout=subprocess.PIPE, stderr=errors)
            processes.append(frames)
            audio = None
            if any(s['codec_type']=='audio' for s in streams):
                audio = subprocess.Popen(command + ['-vn','-ac','1','-ar','8000','-f','s16le','pipe:1'], stdout=subprocess.PIPE, stderr=errors)
                processes.append(audio)
            center=.5
            while True:
                raw=read_exact(frames.stdout,FRAME_W*FRAME_H)
                if not raw: break
                if len(raw)!=FRAME_W*FRAME_H: raise RuntimeError('Incomplete vision frame')
                rms=0.
                if audio:
                    pcm=read_exact(audio.stdout,8000//FPS*2)
                    if pcm:
                        samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
                        rms=float(np.sqrt(np.mean(samples*samples)))
                frame=np.frombuffer(raw,dtype=np.uint8).reshape(FRAME_H,FRAME_W)
                faces=tracker.observe(frame, detector.detect(frame), rms)
                detected += bool(faces)
                speaker=next((face for face in faces if face['active_speaker_candidate']),None)
                active += speaker is not None
                chosen=speaker or (faces[0] if len(faces)==1 else None)
                # Never choose a face arbitrarily in an ambiguous multi-person scene.
                if chosen:
                    x,y,w,h=chosen['box']; target=max(0.,min(1.,(x+w/2-pad_x)/content_w))
                    if count==0: center=target
                    else: center += max(-.025,min(.025,(target-center)*.25))
                    crop_fraction=(height*9/16)/width
                    left=(x-pad_x)/content_w; right=(x+w-pad_x)/content_w
                    if left<center-crop_fraction/2+.015 or right>center+crop_fraction/2-.015: unsafe+=1
                else: unsafe += 1
                points.append({'time':round(count/FPS,3),'center':round(center,5),'faces':faces,
                               'speaker_track': speaker['id'] if speaker else None})
                count+=1
                if count % 40 == 0: update(status='tracking faces',progress=f'{count/FPS:.0f}/{end-start:.0f}s')
            # FFmpeg can emit a fraction more audio than sampled frames. Close and stop
            # our audio decoder rather than waiting on a full stdout pipe.
            for process in processes:
                if process.stdout: process.stdout.close()
            frames.wait(timeout=30)
            if frames.returncode:
                errors.seek(0); raise RuntimeError(errors.read()[-2500:].decode(errors='replace'))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
    # Uncertain intervals cause a whole-clip fit fallback; private faces are never
    # assumed detected reliably just because a Haar cascade returned something.
    safe_crop = width > height*9/16 and count>0 and detected/count>=.8 and unsafe/count<=.1
    return {'version':'mouth-motion-v1','source_width':width,'source_height':height,'sample_fps':FPS,
            'frames_sampled':count,'frames_with_faces':detected,'active_candidate_frames':active,
            'framing':'track' if safe_crop else 'fit','points':points,
            'limitations':'Experimental mouth-motion/audio-activity association, not verified diarization. Review all crops; ambiguous scenes use full-image fit.'}


def tracking_filter(report, directory, output_width, output_height):
    if report['framing']!='track': return None
    width,height=report['source_width'],report['source_height']
    crop_width=int(height*9/16)//2*2
    commands=[]
    previous=max(0,min(width-crop_width,report['points'][0]['center']*width-crop_width/2))
    # Send crop expressions, interpolating between smoothed samples at frame rate.
    for point in report['points'][1:]:
        x=max(0,min(width-crop_width,point['center']*width-crop_width/2))
        t=max(0,point['time']-1/FPS)
        expression=f'{previous:.3f}+({x-previous:.3f})*clip((t-{t:.3f})*{FPS},0,1)'
        commands.append(f"{t:.3f} crop x '{expression}';")
        previous=x
    (Path(directory)/'tracking.cmd').write_text('\n'.join(commands))
    return f"sendcmd=f=tracking.cmd,crop={crop_width}:{height}:x=(iw-ow)/2:y=0,scale={output_width}:{output_height},setsar=1"
