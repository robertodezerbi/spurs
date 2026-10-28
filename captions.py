"""Portable ASS captions: restrained fade or genuine word-timed karaoke."""
import re
import textwrap


def clean(text):
    return re.sub(r'[{}\\\r\n]', ' ', re.sub(r'<[^>]*>', '', text)).strip()


def timestamp(seconds):
    centiseconds = max(0, round(seconds*100))
    hours, centiseconds = divmod(centiseconds,360000)
    minutes, centiseconds = divmod(centiseconds,6000)
    sec, cs = divmod(centiseconds,100)
    return f'{hours}:{minutes:02}:{sec:02}.{cs:02}'


def ass_captions(transcript, start, end, *, font='Arial', size=18, color='&H00FFFFFF',
                 highlight='&H0000D7FF', animation='none', position='bottom', canvas=(1080,1920)):
    alignment={'bottom':2,'center':5,'top':8}[position]
    primary=highlight if animation=='karaoke' else color
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {canvas[0]}
PlayResY: {canvas[1]}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{size*3},{primary},{color},&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,{alignment},60,60,{round(canvas[1]*.075)},1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
    events=[]; timing='word-aligned'
    for segment in transcript:
        words=[w for w in segment.get('words',[]) if w['end']>start and w['start']<end]
        if animation=='karaoke' and not words and segment['end']>start and segment['start']<end:
            raise ValueError('Karaoke captions require word timings. Transcribe this clip first; corrected segment-only text supports plain/fade captions.')
        cues=[]
        if words:
            groups=[];group=[];characters=0
            for word in words:
                length=len(clean(word['word']))
                if length>64:raise ValueError('A timed word exceeds the caption safe width. Correct the transcript before export.')
                if group and (len(group)>=5 or characters+length+1>58):groups.append(group);group=[];characters=0
                group.append(word);characters+=length+1
            if group:groups.append(group)
            for group in groups:
                a=max(start,group[0]['start']); b=min(end,group[-1]['end'])
                if animation=='karaoke':
                    pieces=[]; cursor=a
                    for word in group:
                        wa=max(a,word['start']); wb=min(b,word['end'])
                        if wb<=wa: continue
                        gap=max(0,round((wa-cursor)*100))
                        if gap: pieces.append('{\\k'+str(gap)+'} ')
                        pieces.append('{\\kf'+str(max(1,round((wb-wa)*100)))+'}'+'\\N'.join(textwrap.wrap(clean(word['word']),32))+' ')
                        cursor=wb
                    text=''.join(pieces).strip()
                else: text='\\N'.join(textwrap.wrap(clean(' '.join(w['word'].strip() for w in group)),32))
                cues.append((a,b,text))
        else:
            timing='segment/proportional'
            a=max(start,segment['start']); b=min(end,segment['end'])
            lines=textwrap.wrap(clean(segment['text']),width=32)
            chunks=['\\N'.join(lines[i:i+2]) for i in range(0,len(lines),2)]
            for index,text in enumerate(chunks):
                cues.append((a+(b-a)*index/len(chunks),a+(b-a)*(index+1)/len(chunks),text))
        for a,b,text in cues:
            if b<=a or not text: continue
            if animation=='fade': text='{\\fad(100,100)}'+text
            events.append(f'Dialogue: 0,{timestamp(a-start)},{timestamp(b-start)},Default,,0,0,0,,{text}')
    if not events: raise ValueError('No transcript overlaps this clip')
    return header+'\n'.join(events)+'\n',len(events),timing
