"""Optional two-pass EBU R128 normalization, conservative denoising and edge fades."""
import json
import math
import re
import subprocess
from runtime import executable


def audio_filters(source,start,end,normalize=False,denoise=False,fade=False):
    filters=['highpass=f=70','afftdn=nf=-25'] if denoise else []
    report={'normalization':'off','denoise':denoise,'edge_fades':fade}
    if normalize:
        command=[executable('ffmpeg'),'-nostdin','-hide_banner','-ss',str(start),'-i',str(source),'-t',str(end-start),
                 '-vn','-af',','.join(filters+['loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json']),'-f','null','-']
        result=subprocess.run(command,capture_output=True,text=True,timeout=max(120,(end-start)*2))
        if result.returncode: raise RuntimeError('Loudness analysis failed: '+result.stderr[-1800:])
        matches=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',result.stderr)
        if not matches: raise ValueError('FFmpeg did not return loudness measurements')
        stats=json.loads(matches[-1])
        if all(math.isfinite(float(stats[k])) for k in ('input_i','input_tp','input_lra','input_thresh','target_offset')):
            filters.append('loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:'+
                ':'.join(f'{field}={float(stats[key])}' for field,key in [('measured_I','input_i'),('measured_TP','input_tp'),
                    ('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')]))
            report.update(normalization='two-pass measured',measurements=stats)
        else:
            report.update(normalization='skipped: silence/undefined measurements')
    if fade:
        duration=end-start; length=min(.02,duration/4)
        filters.extend([f'afade=t=in:st=0:d={length}',f'afade=t=out:st={max(0,duration-length)}:d={length}'])
    return filters,report
