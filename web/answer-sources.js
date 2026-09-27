const esc=(s='')=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=ms=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
export const answerLink=(mid,eid,sid)=>`#meetings/${encodeURIComponent(mid)}/answers/${encodeURIComponent(eid)}${sid?'/sources/'+encodeURIComponent(sid):''}`;

export function answerTriggers(triggers=[]){
  if(!triggers.length)return '';
  return `<section class="answer-trigger" aria-label="Question transcript"><h3>Question in transcript</h3>${triggers.map(t=>`<blockquote><p class="muted">${esc(t.speaker)}${Number.isFinite(t.start_ms)?` · ${time(t.start_ms)}`:''}${t.changed?' · Transcript changed':''}</p><p>${esc(t.content)}</p><button class="meeting-text-button" data-trigger-jump="${esc(t.utterance_id)}">${t.changed?'View current transcript':'Open transcript'}</button></blockquote>`).join('')}</section>`;
}

function nearbyTurn(citation,utterances){
  if(citation.kind!=='utterance'||!citation.recording_id||citation.changed||citation.unavailable)return null;
  const rows=utterances.filter(u=>u.recording_id===citation.recording_id)
    .sort((a,b)=>a.start_ms-b.start_ms||a.end_ms-b.end_ms);
  const anchor=rows.findIndex(u=>u.id===citation.id&&u.content===citation.content);
  if(anchor<0)return null;
  let first=anchor,last=anchor,size=rows[anchor].content.length;
  const joins=(a,b)=>a.speaker===b.speaker&&-500<=b.start_ms-a.end_ms&&b.start_ms-a.end_ms<=2000;
  while(first>0&&joins(rows[first-1],rows[first])&&rows[last].end_ms-rows[first-1].start_ms<=30000&&size+rows[first-1].content.length<=4500){
    first--;size+=rows[first].content.length;
  }
  while(last+1<rows.length&&joins(rows[last],rows[last+1])&&rows[last+1].end_ms-rows[first].start_ms<=30000&&size+rows[last+1].content.length<=4500){
    last++;size+=rows[last].content.length;
  }
  return rows.slice(first,last+1);
}

export function answerSourceGroups(citations=[],utterances=[]){
  const groups=[],byTurn=new Map();
  for(const citation of citations){
    const turn=nearbyTurn(citation,utterances);
    const key=turn?.length?`${citation.recording_id}:${turn[0].id}:${turn.at(-1).id}`:null;
    if(key&&byTurn.has(key)){
      byTurn.get(key).citations.push(citation);
    }else{
      const group={citation,citations:[citation],turn};
      groups.push(group);
      if(key)byTurn.set(key,group);
    }
  }
  return groups;
}

export function answerSources({citations=[],check},mid,eid,utterances=[]){
  if(!citations.length)return `<section class="answer-evidence" aria-label="Sources"><h3>Sources</h3><p class="muted">${esc(check?.support==='insufficient'?'No supported answer found in the available records.':check?.support==='not_applicable'?'This reply does not cite meeting evidence.':'No source citations were saved for this answer.')}</p></section>`;
  const groups=answerSourceGroups(citations,utterances);
  const source=({citation:c,citations:items,turn})=>{
    const context=turn&&turn.length>1;
    const marked=new Set(items.map(item=>item.id));
    const passage=context?turn.map(u=>marked.has(u.id)?`<mark class="answer-source-cited" title="Cited passage">${esc(u.content)}</mark>`:esc(u.content)).join(' '):esc(c.unavailable?'Source unavailable':c.changed?'Source changed':c.content);
    const start=context?turn[0].start_ms:c.start_ms,end=context?turn.at(-1).end_ms:c.end_ms;
    const meta=`${c.title||'Source'}${!c.changed&&Number.isFinite(start)?` · ${time(start)}${Number.isFinite(end)?'–'+time(end):''}`:''}`;
    const playback=c.kind==='utterance'&&c.recording_id&&!c.changed;
    return `<article class="answer-source" id="answer-source-${esc(c.id)}" data-citation-ids="${esc(JSON.stringify(items.map(item=>item.id)))}"><p class="answer-source-meta">${esc(meta)}</p>${context?'<p class="answer-source-context-label">Current transcript context · Highlighted text was cited</p>':''}<blockquote>${passage}</blockquote>${!c.unavailable?`<div class="answer-source-actions">${c.kind==='utterance'?`<button class="answer-source-action${context?'':' answer-source-action-primary'}" data-citation-jump="${esc(c.id)}">${c.changed?'View current transcript':'View transcript'}</button>${playback?`<button class="answer-source-action" data-citation-play="${esc(c.id)}" data-play-start="${start}" data-play-end="${end}">Play original</button>`:''}`:`<a class="answer-source-action answer-source-action-primary" href="#domain/${encodeURIComponent(c.domain_id)}/memories">Open knowledge domain</a>`}<a class="answer-source-action answer-source-action-link" href="${answerLink(mid,eid,c.id)}" data-copy-source>Copy source link</a></div>${playback?'<audio class="answer-source-player" controls preload="none" hidden aria-label="Source audio"></audio>':''}`:''}</article>`;
  };
  return `<section class="answer-evidence" aria-label="Sources">${check?.support==='conflicting'?'<p class="meeting-warning">Sources disagree; no confirmed resolution.</p>':''}<h3>Sources · ${groups.length}</h3>${source(groups[0])}${groups.length>1?`<details><summary>More sources · ${groups.length-1}</summary>${groups.slice(1).map(source).join('')}</details>`:''}</section>`;
}
