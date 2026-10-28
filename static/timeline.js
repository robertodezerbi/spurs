'use strict';
// A single-source edit decision list: source ranges, ordered on an output timeline.
class ClipTimeline {
  constructor(video,onSelect,onChange){
    this.video=video;this.onSelect=onSelect;this.onChange=onChange;this.clips=[];this.undoStack=[];this.redoStack=[];this.selected=null;this.playhead=0;this.zoom=20;this.playing=false;this.waveform=null;
    this.viewport=document.getElementById('timelineViewport');this.track=document.getElementById('timelineTracks');
    document.getElementById('timelineZoom').oninput=e=>{this.zoom=Number(e.target.value);this.render();};
    document.getElementById('timelineFit').onclick=()=>this.fit();
    document.getElementById('timelineSplit').onclick=()=>this.split();
    document.getElementById('timelineDelete').onclick=()=>this.remove();
    document.getElementById('timelineUndo').onclick=()=>this.undo();
    document.getElementById('timelineRedo').onclick=()=>this.redo();
    document.getElementById('timelinePlay').onclick=()=>this.play();
    document.getElementById('timelineLeft').onclick=()=>this.move(-1);
    document.getElementById('timelineRight').onclick=()=>this.move(1);
    this.video.addEventListener('timeupdate',()=>this.tick());
    this.video.addEventListener('ended',()=>{if(this.playing)this.next();});
    this.track.addEventListener('pointerdown',e=>{if(e.target===this.track||e.target.closest('.ruler'))this.seek((e.clientX-this.track.getBoundingClientRect().left)/this.pixels());});
    document.addEventListener('keydown',e=>{if(document.getElementById('studio').hidden||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable)return;
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?this.redo():this.undo();}
      else if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();this.remove();}
      else if(e.key.toLowerCase()==='s'){e.preventDefault();this.split();}
      else if(e.code==='Space'){e.preventDefault();this.play();}
      else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();this.seek(this.playhead+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?1:1/30));}
    });
    new ResizeObserver(()=>this.render()).observe(this.viewport);
  }
  load(project){this.projectId=project.id;this.playing=false;this.duration=project.duration;this.clips=structuredClone(project.timeline?.clips||[]);this.waveform=project.waveform||null;this.selected=this.clips[0]?.id||null;this.undoStack=[];this.redoStack=[];this.playhead=0;if(this.clips.length){this.onSelect(this.clips[0]);this.fit();}else this.render();}
  fit(){if(this.total()>0){this.zoom=Math.max(2,Math.min(1000,(this.viewport.clientWidth-50)/this.total()));document.getElementById('timelineZoom').value=this.zoom;}this.render();}
  snapshot(){return JSON.stringify(this.clips);}
  change(fn){const prior=this.snapshot();fn();if(prior!==this.snapshot()){this.undoStack.push(prior);if(this.undoStack.length>50)this.undoStack.shift();this.redoStack=[];this.onChange();}this.render();}
  restore(stack,other){if(!stack.length)return;other.push(this.snapshot());this.clips=JSON.parse(stack.pop());if(!this.clips.some(c=>c.id===this.selected))this.selected=this.clips[0]?.id||null;this.onChange();this.render();}
  undo(){this.restore(this.undoStack,this.redoStack);}
  redo(){this.restore(this.redoStack,this.undoStack);}
  add(start,end,label='Clip'){if(!(0<=start&&start<end&&end<=this.duration))throw Error('Select valid source boundaries first');this.change(()=>{const c={id:crypto.randomUUID(),start,end,label};this.clips.push(c);this.selected=c.id;});if(this.clips.length===1)this.fit();}
  total(){return this.clips.reduce((n,c)=>n+c.end-c.start,0);}
  pixels(){return Math.min(this.zoom,200000/Math.max(1,this.total()));}
  locations(){let offset=0;return this.clips.map(c=>{const result={...c,offset};offset+=c.end-c.start;return result;});}
  choose(id){this.selected=id;const clip=this.clips.find(c=>c.id===id);if(clip)this.onSelect(clip);this.render();}
  seek(time){this.playhead=Math.max(0,Math.min(this.total(),time));const c=this.locations().find(c=>this.playhead>=c.offset&&this.playhead<c.offset+c.end-c.start)||this.locations().at(-1);if(c){this.selected=c.id;this.video.currentTime=c.start+Math.min(c.end-c.start,this.playhead-c.offset);this.onSelect(c);}this.render();}
  split(){const at=this.locations().find(c=>this.playhead>c.offset+.05&&this.playhead<c.offset+c.end-c.start-.05);if(!at)return;this.change(()=>{const i=this.clips.findIndex(c=>c.id===at.id),source=at.start+this.playhead-at.offset;const right={...this.clips[i],id:crypto.randomUUID(),start:source};this.clips[i].end=source;this.clips.splice(i+1,0,right);this.selected=right.id;});}
  remove(){this.change(()=>{this.clips=this.clips.filter(c=>c.id!==this.selected);this.selected=this.clips[0]?.id||null;this.playhead=Math.min(this.playhead,this.total());});}
  move(direction){const i=this.clips.findIndex(c=>c.id===this.selected),next=i+direction;if(i<0||next<0||next>=this.clips.length)return;this.change(()=>{[this.clips[i],this.clips[next]]=[this.clips[next],this.clips[i]];});}
  play(){if(this.playing){this.playing=false;this.video.pause();this.render();return;}if(!this.clips.length)return;window.clearSelectionPreview?.();this.playing=true;if(this.playhead>=this.total()-.04)this.playhead=0;this.seek(this.playhead);this.video.play().catch(e=>{this.playing=false;this.onChange(e.message);});}
  next(){const locations=this.locations(),i=locations.findIndex(c=>c.id===this.selected);if(i>=0&&i+1<locations.length){this.selected=locations[i+1].id;this.video.currentTime=locations[i+1].start;this.playhead=locations[i+1].offset;this.video.play().catch(()=>{this.playing=false;});}else{this.playing=false;this.video.pause();this.playhead=this.total();}this.render();}
  tick(){if(!this.playing)return;const c=this.locations().find(c=>c.id===this.selected);if(!c)return;if(this.video.currentTime>=c.end-.02){this.next();return;}this.playhead=c.offset+Math.max(0,this.video.currentTime-c.start);this.updatePlayhead();}
  updatePlayhead(){const marker=document.getElementById('timelinePlayhead');if(marker)marker.style.left=this.playhead*this.pixels()+'px';document.getElementById('timelineTime').textContent=`${this.playhead.toFixed(2)} / ${this.total().toFixed(2)} s`;}
  trim(event,id,edge){event.preventDefault();event.stopPropagation();this.playing=false;this.video.pause();const prior=this.snapshot(),x=event.clientX,clip=this.clips.find(c=>c.id===id),original={...clip},pixels=this.pixels();
    const motion=e=>{const delta=(e.clientX-x)/pixels;clip[edge]=edge==='start'?Math.max(0,Math.min(original.end-.1,original.start+delta)):Math.min(this.duration,Math.max(original.start+.1,original.end+delta));this.selected=id;this.onSelect(clip);this.render();};
    const finish=()=>{window.removeEventListener('pointermove',motion);window.removeEventListener('pointerup',finish);if(prior!==this.snapshot()){this.undoStack.push(prior);this.redoStack=[];this.onChange();}this.render();};window.addEventListener('pointermove',motion);window.addEventListener('pointerup',finish,{once:true});
  }
  render(){const pixels=this.pixels(),width=Math.max(this.viewport.clientWidth,this.total()*pixels+40);this.track.style.width=width+'px';this.track.replaceChildren();
    const ruler=document.createElement('div');ruler.className='ruler';this.track.append(ruler);const step=Math.max(1,Math.ceil(70/pixels));for(let t=0;t<=this.total();t+=step){const tick=document.createElement('span');tick.style.left=t*pixels+'px';tick.textContent=`${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;ruler.append(tick);}
    for(const c of this.locations()){const block=document.createElement('div');block.className='timelineClip'+(c.id===this.selected?' selected':'');block.style.left=c.offset*pixels+'px';block.style.width=Math.max(2,(c.end-c.start)*pixels)+'px';block.draggable=true;block.tabIndex=0;block.setAttribute('role','button');block.setAttribute('aria-label',`${c.label}: ${c.start.toFixed(2)} to ${c.end.toFixed(2)} source seconds`);block.dataset.id=c.id;
      const thumbnail=document.createElement('img');thumbnail.className='clipThumbnail';thumbnail.alt='';thumbnail.loading='lazy';thumbnail.draggable=false;thumbnail.src=`/api/projects/${this.projectId}/thumbnail?time=${c.start.toFixed(2)}`;block.append(thumbnail);const label=document.createElement('span');label.textContent=c.label;block.append(label);block.onclick=()=>this.choose(c.id);block.onkeydown=e=>{if(e.key==='Enter')this.choose(c.id);};
      for(const edge of ['start','end']){const handle=document.createElement('div');handle.className='trimHandle '+edge;handle.setAttribute('aria-label','Trim '+edge);handle.onpointerdown=e=>this.trim(e,c.id,edge);handle.draggable=false;block.append(handle);}
      block.ondragstart=e=>{e.dataTransfer.setData('text/plain',c.id);};block.ondragover=e=>e.preventDefault();block.ondrop=e=>{e.preventDefault();const id=e.dataTransfer.getData('text/plain');if(id===c.id)return;this.change(()=>{const old=this.clips.findIndex(x=>x.id===id);if(old<0)return;const [moved]=this.clips.splice(old,1);this.clips.splice(this.clips.findIndex(x=>x.id===c.id),0,moved);});};this.track.append(block);
      const audio=document.createElement('canvas');audio.className='waveClip';const canvasWidth=Math.max(1,Math.min(2048,Math.round((c.end-c.start)*pixels)));audio.width=canvasWidth;audio.height=36;audio.style.left=c.offset*pixels+'px';audio.style.width=(c.end-c.start)*pixels+'px';this.track.append(audio);const ctx=audio.getContext('2d');ctx.fillStyle='#2dd4bf';if(this.waveform){const points=this.waveform.points;for(let x=0;x<canvasWidth;x++){const source=c.start+(c.end-c.start)*x/canvasWidth;const peak=points[Math.min(points.length-1,Math.floor(source/this.duration*points.length))]||0;ctx.fillRect(x,18-peak*16,1,Math.max(1,peak*32));}}else{ctx.font='11px system-ui';ctx.fillText('Build waveform to view audio',8,22);}}
    const marker=document.createElement('div');marker.id='timelinePlayhead';marker.className='playhead';this.track.append(marker);this.updatePlayhead();document.getElementById('timelineUndo').disabled=!this.undoStack.length;document.getElementById('timelineRedo').disabled=!this.redoStack.length;document.getElementById('timelinePlay').textContent=this.playing?'Pause':'Play timeline';document.getElementById('timelineEmpty').hidden=!!this.clips.length;
  }
}
window.ClipTimeline=ClipTimeline;
