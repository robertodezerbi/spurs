"""Real Whisper verification gate. Does not claim success when weights are blocked."""
import argparse
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import shutil
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analysis import transcribe,model_inventory
from runtime import media_info
from store import Store


def word_error_rate(reference,hypothesis):
    a=re.findall(r'\w+',reference.lower());b=re.findall(r'\w+',hypothesis.lower())
    if not a:raise ValueError('Reference text is empty')
    previous=list(range(len(b)+1))
    for index,word in enumerate(a,1):
        current=[index]
        for j,other in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(word!=other)))
        previous=current
    return previous[-1]/len(a)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--reference',required=True,type=Path)
    parser.add_argument('--allow-download',action='store_true',help='Allow approximately 75 MB tiny weights, plus cached metadata')
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    args=parser.parse_args();root=args.data_dir;root.mkdir(parents=True,exist_ok=True)
    models=root/'_models';models.mkdir(exist_ok=True)
    if not model_inventory(models)[0]['cached'] and args.allow_download:
        # A supported, non-destructive host probe makes policy errors explicit.
        try:
            with urllib.request.urlopen(urllib.request.Request('https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/config.json',method='HEAD'),timeout=20):pass
        except Exception as exc:
            print(json.dumps({'status':'blocked','operation':'authorized Hugging Face model access','error':str(exc),
                'action':'Activate the saved model-host rules in cloud environment settings. No alternate route, token or disabled TLS is used.'},indent=2));return 2
    duration=float(media_info(args.source)['format']['duration'])
    def ensure_space(needed):
        if shutil.disk_usage(root).free < needed+256*1024*1024:raise OSError('Insufficient free space for verification')
    with tempfile.TemporaryDirectory(prefix='verification-',dir=root) as temporary:
        scratch=Path(temporary)
        transcript=transcribe(args.source,duration,'fast',args.allow_download,models,scratch,Store(root/'verification.sqlite3'),
            lambda **kw:print(json.dumps(kw),flush=True),ensure_space)
        text=' '.join(s['text'] for s in transcript);wer=word_error_rate(args.reference.read_text(),text)
        result={'status':'passed' if text and wer<=.3 else 'failed','transcript':text,'word_error_rate':wer,
                'reference_words':len(re.findall(r'\w+',args.reference.read_text())),'model':'tiny','audio_seconds':duration}
        print(json.dumps(result,indent=2));return 0 if result['status']=='passed' else 1



if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:print(json.dumps({'status':'failed','error':str(exc)}));sys.exit(1)
