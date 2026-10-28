"""Source-audio peak envelope using constant-size PCM buffers."""
from array import array
import subprocess
import sys
import tempfile
from runtime import executable


def envelope(path,duration,points=1024):
    peaks=[0]*points; position=0; total=max(1,int(duration*8000))
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen([executable('ffmpeg'),'-nostdin','-v','error','-i',str(path),'-vn','-ac','1',
                                  '-ar','8000','-f','s16le','pipe:1'],stdout=subprocess.PIPE,stderr=errors)
        try:
            while block:=process.stdout.read(16384):
                samples=array('h'); samples.frombytes(block)
                if sys.byteorder!='little': samples.byteswap()
                offset=0
                while offset<len(samples):
                    bucket=min(points-1,position*points//total)
                    boundary=(bucket+1)*total//points
                    count=min(len(samples)-offset,max(1,boundary-position)) if bucket<points-1 else len(samples)-offset
                    group=samples[offset:offset+count]
                    peaks[bucket]=max(peaks[bucket],abs(min(group)),abs(max(group)))
                    position+=count;offset+=count
            process.wait(timeout=30)
            if process.returncode:
                errors.seek(0);raise RuntimeError(errors.read()[-1800:].decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait()
    return {'points':[round(p/32768,4) for p in peaks],'duration':duration,'samples_decoded':position}
