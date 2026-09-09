import {groupTranscript, recordingContent, speakerName, transcriptMatches, searchParts, playingUtterance, findingGroups, findingTypes} from './meeting-transcript.js?v=meeting-listen-4';
const esc = (v='') => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const meetingTime = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
let current;
export function leaveMeeting(){current?.dispose();current=null;}

export async function showMeetings({api,shell,openDialog,field,navigate,toast,isCurrent=()=>true},id){
  if(!id){
    const meetings=await api('/meetings');if(!isCurrent())return;
    shell(`<div class="heading"><div><p class="eyebrow">Your meeting library</p><h1>Meetings</h1><p>Record, read the essentials, and return to the original conversation.</p></div><button class="btn primary" id="new-meeting">New meeting</button></div>${meetings.length?meetings.map(m=>`<a class="session-row" href="#meetings/${esc(m.id)}"><div><h3>${esc(m.title)}</h3><p class="muted">${esc(m.status)} · ${new Date(m.created_at*1000).toLocaleString()}</p></div><span>Open →</span></a>`).join(''):'<div class="empty"><h2>Your meetings will appear here</h2><p>Create a meeting to start recording.</p></div>'}`,'Meetings');
    document.querySelector('#new-meeting').onclick=()=>openDialog('New meeting',field('title','Meeting title','','text','required maxlength="120"'),async fd=>{const m=await api('/meetings','POST',{title:fd.get('title')});navigate(`meetings/${m.id}`);},'Create meeting');return;
  }
  let meeting=await api(`/meetings/${id}`);if(!isCurrent())return;
  let disposed=false,socket,stream,context,capture,source,stopping=false,recordingRate=16000,pendingBuffers=[];
  let selectedRecording=meeting.recordings.at(-1)?.id||'notes',captureRecording=null,selectedPassage=null,selectedView='full';
  let analysisTask=null,analysisMessage='',analysisError=false;
  let searchQuery='',searchIndex=-1,searchIds=[],playingId=null,followedId=null,searchTimer,scrollFrame;
  let playbackRecords=[];
  const expansion=new Map(),base=`/meetings/${id}`,$=s=>document.querySelector(s);
  const recordingLabel=rid=>rid==='notes'?'Meeting notes':`Recording ${meeting.recordings.findIndex(r=>r.id===rid)+1}`;
  const scope=rid=>`?recording_id=${encodeURIComponent(rid)}`;
  const textOf=u=>u.content.replace(/\s+/g,' ').trim();
  shell(`<div class="heading meeting-heading"><div><h1>${esc(meeting.title)}</h1><p id="meeting-context"></p></div><div class="actions"><a class="btn subtle" href="#meetings">All meetings</a><button class="btn" id="meeting-end">End meeting</button></div></div>
    <nav class="meeting-navigation" aria-label="Recording sections"><button data-jump="overview-heading" aria-current="location">Overview</button><button data-jump="chapter-heading">Chapters</button><button data-jump="transcript-heading">Transcript</button><span id="selected-recording-label"></span></nav>
    <div class="meeting-layout"><section class="meeting-reader" aria-label="Selected recording content">
      <section class="meeting-overview" aria-labelledby="overview-heading"><div class="meeting-section-heading"><h2 id="overview-heading" tabindex="-1">Recording summary</h2><button class="btn primary" id="meeting-analyze">Summarize recording</button></div><div id="meeting-overview"></div><p id="meeting-summary-status" class="meeting-summary-status" role="status"></p></section>
      <section class="meeting-chapter-section" aria-labelledby="chapter-heading"><div class="meeting-section-heading"><h2 id="chapter-heading" tabindex="-1">Live summaries</h2><button class="btn subtle" id="meeting-chapters-update">Update highlights</button></div><div id="meeting-chapters"></div></section>
      <section class="meeting-transcript-section" aria-labelledby="transcript-heading"><div class="meeting-section-heading"><h2 id="transcript-heading" tabindex="-1">Full transcript</h2><label class="meeting-follow"><input type="checkbox" id="meeting-follow"> Follow live text</label></div>
        <div class="meeting-search"><label for="transcript-search">Search transcript</label><div class="meeting-search-controls"><input type="search" id="transcript-search" maxlength="200" placeholder="Find words in this recording" autocomplete="off" aria-describedby="transcript-search-status"><button class="btn subtle" id="search-prev" aria-label="Previous matching passage" disabled>↑</button><button class="btn subtle" id="search-next" aria-label="Next matching passage" disabled>↓</button><button class="btn subtle" id="search-clear" disabled>Clear</button></div><p id="transcript-search-status" role="status" aria-live="polite"></p></div>
        <div class="meeting-transcript-tools"><button class="meeting-text-button" id="expand-paragraphs">Expand paragraphs</button><button class="meeting-text-button" id="collapse-paragraphs">Collapse paragraphs</button><button class="meeting-text-button" id="meeting-text">Add text note</button></div><div id="meeting-transcript"></div><p id="meeting-partial"></p></section>
    </section><aside class="meeting-sidebar" aria-label="Recordings and follow-up"><section class="meeting-recording-panel"><div class="meeting-section-heading"><h2>Recordings</h2><span id="recording-count"></span></div><div id="meeting-recordings"></div><button class="btn primary" id="meeting-record">Start recording</button><p id="capture-status" role="status"></p><p id="capture-warning" class="muted">Microphone audio is saved. Inform participants before recording.</p></section><section class="meeting-evidence-panel" aria-label="Key points and follow-up"><h2>Key points & follow-up</h2><div id="meeting-insights"></div><details class="meeting-definitions"><summary>What belongs here?</summary><p>Only categories supported by this recording appear. A KT meeting can contain knowledge points only.</p><dl>${findingTypes.map(t=>`<dt>${t.label}</dt><dd>${t.description}</dd>`).join('')}<dt>Sources / evidence</dt><dd>Transcript passages and audio timestamps supporting a point. They do not prove a statement is true or that everyone agreed.</dd></dl><p>All points are AI suggestions. No tasks are sent or executed automatically.</p></details></section><button class="meeting-text-button danger" id="meeting-delete">Delete meeting…</button></aside></div>
    <section class="meeting-player-wrap" aria-label="Recording player"><div class="meeting-player-title"><strong id="meeting-player-label"></strong><span id="meeting-playback" class="muted"></span></div><audio id="meeting-player" controls preload="none" aria-label="Selected recording audio"></audio><div class="meeting-player-tools"><button class="btn" id="play-back" aria-label="Back 10 seconds">−10s</button><button class="btn" id="play-forward" aria-label="Forward 10 seconds">+10s</button><label class="meeting-speed" for="play-speed">Speed<select id="play-speed"><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label><label class="meeting-follow"><input type="checkbox" id="follow-playback"> Follow playback</label></div></section>`,'Meetings');
  const dock=$('.meeting-player-wrap'),workspace=$('.workspace');
  // Outside the animated workspace, so fixed controls remain viewport-relative.
  $('.main').append(dock);workspace.classList.add('meeting-workspace');
  document.documentElement.classList.add('meeting-open');
  const status=message=>{if(!disposed)$('#capture-status').textContent=message;};
  const warning=message=>{if(!disposed)$('#capture-warning').textContent=message;};
  const highlighted=text=>searchParts(text,searchQuery).map(p=>p.match?`<mark>${esc(p.text)}</mark>`:esc(p.text)).join('');
  function rememberExpansion(){document.querySelectorAll('[data-expand]').forEach(d=>expansion.set(d.dataset.expand,d.open));}
  function transcriptHTML(records,view){return groupTranscript(records).map(g=>{
    const first=g.records[0],last=g.records.at(-1),key=`${view}-${first.id}`,open=expansion.get(key)??true;
    const selected=selectedView===view?g.records.find(u=>u.id===selectedPassage):null;
    const time=g.recordingId?`${meetingTime(first.start_ms)}–${meetingTime(last.end_ms)}`:'Text note';
    return `<details class="meeting-paragraph" data-expand="${key}" ${open?'open':''}><summary><span class="paragraph-speaker">${esc(g.speaker)}</span><span class="paragraph-time">${time}</span><span class="paragraph-preview">${esc(g.records.map(textOf).join(' '))}</span></summary><div class="paragraph-body"><p class="meeting-prose">${g.records.map(u=>`<span role="button" tabindex="0" class="meeting-phrase ${selected?.id===u.id?'selected':''} ${searchIds[searchIndex]===u.id?'search-current':''}" id="${view}-${u.id}" data-select="${u.id}" data-view="${view}" aria-pressed="${selected?.id===u.id}" aria-label="${esc(`${meetingTime(u.start_ms)}: ${textOf(u)}`)}">${view==='full'?highlighted(textOf(u)):esc(textOf(u))}</span>`).join(' ')}</p>${selected?`<div class="meeting-passage-actions"><span>${meetingTime(selected.start_ms)}</span>${selected.recording_id?`<button class="meeting-text-button" data-play="${selected.id}">Play original</button>`:'<span>No audio</span>'}<button class="meeting-text-button" data-edit="${selected.id}">Correct text / speaker</button><button class="meeting-text-button" data-clear>Close</button></div>`:''}<details class="meeting-sentence-details" data-expand="sentences-${key}" ${expansion.get(`sentences-${key}`)?'open':''}><summary>Sentence timestamps & corrections</summary>${g.records.map(u=>`<div class="meeting-sentence-row"><button class="meeting-text-button" data-play="${u.id}" ${u.recording_id?'':'disabled'} aria-label="Play at ${meetingTime(u.start_ms)}">${meetingTime(u.start_ms)}</button><p>${esc(textOf(u))}</p><button class="meeting-text-button" data-edit="${u.id}">Correct</button></div>`).join('')}</details></div></details>`;
  }).join('');}
  function draw(){
    if(disposed)return;rememberExpansion();
    if(selectedRecording!=='notes'&&!meeting.recordings.some(r=>r.id===selectedRecording))selectedRecording=meeting.recordings.at(-1)?.id||'notes';
    const {records,sections,overview,overviewCurrent}=recordingContent(meeting,selectedRecording);
    playbackRecords=records;
    $('#selected-recording-label').textContent=recordingLabel(selectedRecording);
    $('#meeting-context').textContent=`${meeting.status==='ended'?'Ended':meeting.recording?'Recording':'Active'} · ${recordingLabel(selectedRecording)}`;
    $('#meeting-overview').innerHTML=overview?`<p class="overview-state">${overviewCurrent?'Draft overview':overview.status==='building'?'Overview in progress':'New or corrected text · update the overview'}</p><div class="overview-text">${esc(overview.summary)}</div>`:`<p class="meeting-placeholder">${records.length?'Summarize this recording to see the main topics, decisions and open questions here.':'The overview will appear here after speech is transcribed.'}</p>`;
    $('#meeting-summary-status').textContent=analysisMessage;$('#meeting-summary-status').dataset.error=String(analysisError);
    $('#meeting-analyze').disabled=!!analysisTask||!records.length;$('#meeting-chapters-update').disabled=!!analysisTask||!records.length;
    $('#meeting-chapters').innerHTML=sections.length?sections.map((s,i)=>{
      const passages=records.filter(u=>s.evidence_ids.includes(u.id)),key=`chapter-${s.id}`,first=passages[0],last=passages.at(-1);
      return `<article class="meeting-chapter"><div class="chapter-meta"><span>${first?.recording_id?`${meetingTime(first.start_ms)}–${meetingTime(last.end_ms)}`:`Highlight ${i+1}`}</span><span>${esc({pending:'AI draft',confirmed:'Checked by you',rejected:'Findings excluded'}[s.status]||s.status)}</span></div><p class="chapter-summary">${esc(s.summary)}</p><details data-expand="${key}" ${expansion.get(key)?'open':''}><summary>Source transcript · ${passages.length} passages</summary>${transcriptHTML(passages,key)}</details>${s.status==='pending'?`<details class="chapter-review" data-expand="review-${s.id}" ${expansion.get(`review-${s.id}`)?'open':''}><summary>Review AI output (optional)</summary><p>Marking accurate checks the AI summary and extracted points, not participant agreement. Excluding hides its extracted points; the summary and original remain available.</p><div class="actions"><button class="meeting-text-button" data-review="${s.id}" data-status="confirmed">Mark accurate</button><button class="meeting-text-button" data-review="${s.id}" data-status="rejected">Exclude findings</button></div></details>`:''}</article>`;
    }).join(''):'<p class="meeting-placeholder">Short summaries appear about every minute during recording. You can also update highlights from saved text.</p>';
    updateSearchState(records);
    $('#meeting-transcript').innerHTML=transcriptHTML(records,'full')||'<p class="meeting-placeholder">Recognized speech will appear here.</p>';
    $('#recording-count').textContent=String(meeting.recordings.length);
    $('#meeting-recordings').innerHTML=meeting.recordings.map((r,i)=>`<div class="recording-row ${selectedRecording===r.id?'active':''}"><button class="recording-select" data-recording="${r.id}" aria-pressed="${selectedRecording===r.id}"><strong>Recording ${i+1}</strong><span>${meetingTime(r.samples/r.sample_rate*1000)}${r.id===captureRecording?' · Recording':''}</span></button><a class="recording-download" href="/api${base}/recordings/${r.id}/audio" download aria-label="Download recording ${i+1}">↓</a><button class="recording-delete" data-delete-recording="${r.id}" aria-label="Delete recording ${i+1}" ${socket||meeting.recording||analysisTask?'disabled':''}>×</button></div>`).join('')+(meeting.utterances.some(u=>!u.recording_id)||!meeting.recordings.length?`<button class="recording-select notes-select" data-recording="notes" aria-pressed="${selectedRecording==='notes'}">Meeting notes <span>No audio</span></button>`:'');
    $('#meeting-player-label').textContent=recordingLabel(selectedRecording);$('.meeting-player-wrap').hidden=selectedRecording==='notes';
    $('#meeting-player').hidden=!!socket&&selectedRecording===captureRecording;
    const playable=selectedRecording!=='notes'&&!(socket&&selectedRecording===captureRecording);
    $('#play-back').disabled=$('#play-forward').disabled=$('#play-speed').disabled=$('#follow-playback').disabled=!playable;
    $('#meeting-record').disabled=meeting.status==='ended'||!!meeting.recording&&!socket||stopping;
    $('#meeting-end').disabled=meeting.status==='ended'||!!socket||meeting.recording||!!analysisTask;$('#meeting-text').disabled=meeting.status==='ended';
    $('#meeting-insights').innerHTML=findingGroups(sections).map(group=>`<section class="meeting-finding-group"><h3>${group.label}</h3>${group.items.map(item=>`<article class="meeting-finding"><p>${esc(item.text)}</p>${group.key==='action'?`<p class="muted">${esc(item.owner||'Owner unspecified')} · ${esc(item.deadline||'Date unspecified')}</p>`:''}<div class="evidence-links">${item.evidence_ids.map(uid=>`<button class="meeting-text-button" data-evidence="${uid}">Source ${records.find(u=>u.id===uid)?.recording_id?meetingTime(records.find(u=>u.id===uid).start_ms):'note'}</button>`).join('')}</div></article>`).join('')}</section>`).join('')||`<p class="meeting-placeholder">${sections.length?'No additional points extracted. The summaries and source transcript remain available.':'Relevant knowledge and follow-up will appear after highlights are generated.'}</p>`;
    bindContent();
    syncPlayback(false);updateDockSpace();
  }
  function bindContent(){
    document.querySelectorAll('[data-expand]').forEach(d=>d.ontoggle=()=>{expansion.set(d.dataset.expand,d.open);});
    document.querySelectorAll('[data-select]').forEach(b=>{
      b.onclick=()=>{selectedPassage=b.dataset.select;selectedView=b.dataset.view;stopFollowing();draw();document.getElementById(`${selectedView}-${selectedPassage}`)?.focus({preventScroll:true});};
      b.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();b.click();}};
    });
    document.querySelectorAll('[data-clear]').forEach(b=>b.onclick=()=>{selectedPassage=null;draw();});
    document.querySelectorAll('[data-play]').forEach(b=>b.onclick=()=>playPassage(b.dataset.play));
    document.querySelectorAll('[data-recording]').forEach(b=>b.onclick=()=>selectRecording(b.dataset.recording));
    document.querySelectorAll('[data-delete-recording]').forEach(b=>b.onclick=()=>openDialog(`Delete ${recordingLabel(b.dataset.deleteRecording)}`, '<p>This removes this recording, its transcript and summaries. Other recordings remain available.</p>',async()=>{
      const rid=b.dataset.deleteRecording,next=await api(`${base}/recordings/${rid}`,'DELETE');if(disposed)return;
      if(selectedRecording===rid){$('#meeting-player').pause();$('#meeting-player').removeAttribute('src');$('#meeting-player').load();}
      meeting=next;draw();loadSelectedAudio();toast('Recording and its associated content deleted.');
    },'Delete recording'));
    document.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>{
      selectedPassage=b.dataset.evidence;selectedView='full';stopFollowing();
      openPassage(selectedPassage);draw();
      document.getElementById(`full-${selectedPassage}`)?.scrollIntoView({block:'center'});playPassage(selectedPassage);
    });
    document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{
      const u=meeting.utterances.find(u=>u.id===b.dataset.edit);
      openDialog('Correct transcript',field('speaker','Speaker',speakerName(u.speaker),'text','required maxlength="80"')+`<div class="form-field"><label for="meeting-correction">Original words</label><textarea id="meeting-correction" name="content" required maxlength="6000">${esc(u.content)}</textarea></div>`,async fd=>{meeting=await api(`${base}/utterances/${u.id}`,'PATCH',{speaker:fd.get('speaker'),content:fd.get('content')});draw();toast('Transcript corrected. Update the overview and highlights to include the correction.');});
    });
    document.querySelectorAll('[data-review]').forEach(b=>b.onclick=async()=>{try{const s=meeting.sections.find(s=>s.id===b.dataset.review);meeting=await api(`${base}/sections/${s.id}/review`,'POST',{status:b.dataset.status,revision:s.revision});draw();}catch(e){toast(e.message);}});
  }
  function loadSelectedAudio(ms=0,autoplay=false){
    const player=$('#meeting-player');player.pause();player.onloadedmetadata=null;playingId=null;followedId=null;
    player.playbackRate=Number($('#play-speed').value);syncPlayback(false);
    if(selectedRecording==='notes'){player.removeAttribute('src');player.load();return;}
    if(socket&&selectedRecording===captureRecording){player.removeAttribute('src');player.load();$('#meeting-playback').textContent='Original audio will be ready to play after pausing.';return;}
    const url=`/api${base}/recordings/${selectedRecording}/audio`,seek=()=>{player.playbackRate=Number($('#play-speed').value);player.currentTime=Math.min(ms/1000,Number.isFinite(player.duration)?player.duration:ms/1000);syncPlayback();if(autoplay)player.play().catch(e=>{if(e.name!=='AbortError'&&!disposed)toast(e.message);});};
    if(player.getAttribute('src')!==url){player.onloadedmetadata=seek;player.src=url;player.load();}else if(Number.isFinite(player.duration))seek();else{player.onloadedmetadata=seek;player.load();}
    $('#meeting-playback').textContent='Original audio';
  }
  function selectRecording(rid){stopFollowing();selectedRecording=rid;selectedPassage=null;searchQuery='';searchIndex=-1;searchIds=[];$('#transcript-search').value='';analysisMessage='';analysisError=false;$('#meeting-partial').textContent='';draw();loadSelectedAudio();}
  function playPassage(uid){const u=meeting.utterances.find(u=>u.id===uid);if(!u?.recording_id)return;if(selectedRecording!==u.recording_id){selectedRecording=u.recording_id;draw();}loadSelectedAudio(u.start_ms,true);}

  function stopFollowing(){$('#meeting-follow').checked=false;$('#follow-playback').checked=false;}
  function updateSearchState(records){
    const previous=searchIds[searchIndex];searchIds=transcriptMatches(records,searchQuery);searchIndex=previous?searchIds.indexOf(previous):-1;
    $('#transcript-search-status').textContent=!searchQuery?'':!searchIds.length?'No matches in this recording.':`${searchIndex<0?'':`${searchIndex+1} of `}${searchIds.length} matching passages · Enter for next`;
    $('#search-prev').disabled=$('#search-next').disabled=!searchIds.length;$('#search-clear').disabled=!searchQuery;
  }
  function openPassage(uid){
    const phrase=document.getElementById(`full-${uid}`);if(!phrase)return null;
    const paragraph=phrase.closest('.meeting-paragraph');paragraph.open=true;expansion.set(paragraph.dataset.expand,true);return phrase;
  }
  function navigateMatch(direction){
    if(!searchIds.length)return;stopFollowing();
    searchIndex=(searchIndex+(direction<0&&searchIndex<0?0:direction)+searchIds.length)%searchIds.length;
    const uid=searchIds[searchIndex];
    document.querySelectorAll('.search-current').forEach(el=>el.classList.remove('search-current'));
    const phrase=openPassage(uid);phrase?.classList.add('search-current');phrase?.scrollIntoView({block:'center'});
    $('#transcript-search-status').textContent=`${searchIndex+1} of ${searchIds.length} matching passages`;
  }
  function applySearch(){
    clearTimeout(searchTimer);stopFollowing();searchQuery=$('#transcript-search').value.trim();searchIndex=-1;
    draw();searchIds.forEach(openPassage);
  }
  function syncPlayback(allowScroll=true){
    if(disposed)return;
    const player=$('#meeting-player'),matchesSource=player.getAttribute('src')===`/api${base}/recordings/${selectedRecording}/audio`;
    playingId=matchesSource&&(!player.paused||player.currentTime>0)&&!player.ended?playingUtterance(playbackRecords,player.currentTime*1000):null;
    document.querySelectorAll('.meeting-phrase.playing').forEach(el=>{el.classList.remove('playing');el.removeAttribute('aria-current');});
    if(playingId)document.querySelectorAll(`[data-select="${playingId}"]`).forEach(el=>{el.classList.add('playing');el.setAttribute('aria-current','true');});
    if(allowScroll&&playingId&&$('#follow-playback').checked&&followedId!==playingId){
      followedId=playingId;openPassage(playingId)?.scrollIntoView({block:'center'});
    }
  }
  function seekBy(seconds){
    const player=$('#meeting-player');if(!Number.isFinite(player.duration))return;
    player.currentTime=Math.max(0,Math.min(player.duration,player.currentTime+seconds));syncPlayback();
  }
  function updateDockSpace(){
    const height=dock.hidden?0:Math.ceil(dock.getBoundingClientRect().height);
    document.documentElement.style.setProperty('--meeting-dock-height',`${height}px`);
    document.documentElement.style.setProperty('--meeting-nav-height',`${Math.ceil($('.meeting-navigation').getBoundingClientRect().height)}px`);
  }
  function updateNavigation(){
    scrollFrame=null;if(disposed)return;
    const links=[...document.querySelectorAll('[data-jump]')],threshold=$('.meeting-navigation').getBoundingClientRect().bottom+36;
    const active=links.filter(b=>document.getElementById(b.dataset.jump).getBoundingClientRect().top<=threshold).at(-1)||links[0];
    links.forEach(b=>b===active?b.setAttribute('aria-current','location'):b.removeAttribute('aria-current'));
  }
  const onScroll=()=>{if(!scrollFrame)scrollFrame=requestAnimationFrame(updateNavigation);};
  const onFocus=e=>{
    if(!workspace.contains(e.target)||!e.target.matches('button,input,summary,[tabindex],a'))return;
    const rect=e.target.getBoundingClientRect(),bottom=dock.hidden?innerHeight:dock.getBoundingClientRect().top;
    if(rect.bottom>bottom||rect.top<$('.meeting-navigation').getBoundingClientRect().bottom)e.target.scrollIntoView({block:'center'});
  };
  const resizeObserver=new ResizeObserver(updateDockSpace);resizeObserver.observe(dock);resizeObserver.observe($('.meeting-navigation'));
  window.addEventListener('scroll',onScroll,{passive:true});workspace.addEventListener('focusin',onFocus);
  document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>{stopFollowing();const target=document.getElementById(b.dataset.jump);target.focus({preventScroll:true});target.scrollIntoView({block:'start'});});
  $('#transcript-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(applySearch,120);};
  $('#transcript-search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(searchQuery!==e.target.value.trim())applySearch();navigateMatch(e.shiftKey?-1:1);}else if(e.key==='Escape'){e.target.value='';applySearch();}};
  $('#search-prev').onclick=()=>navigateMatch(-1);$('#search-next').onclick=()=>navigateMatch(1);
  $('#search-clear').onclick=()=>{$('#transcript-search').value='';applySearch();$('#transcript-search').focus();};
  $('#play-back').onclick=()=>seekBy(-10);$('#play-forward').onclick=()=>seekBy(10);
  $('#play-speed').onchange=()=>{$('#meeting-player').playbackRate=Number($('#play-speed').value);};
  $('#meeting-player').ontimeupdate=()=>syncPlayback();$('#meeting-player').onplay=()=>syncPlayback();$('#meeting-player').onseeked=()=>syncPlayback();$('#meeting-player').onended=()=>syncPlayback(false);
  $('#meeting-player').onerror=()=>{if($('#meeting-player').getAttribute('src'))$('#meeting-playback').textContent='Audio unavailable. Try reselecting the recording.';};
  $('#follow-playback').onchange=()=>{if($('#follow-playback').checked){$('#meeting-follow').checked=false;followedId=null;syncPlayback();}};
  $('#meeting-follow').onchange=()=>{if($('#meeting-follow').checked){$('#follow-playback').checked=false;$('#meeting-partial').scrollIntoView({block:'center'});}};
  function merge(next){const known=new Set(next.utterances.map(u=>u.id));const extra=meeting.utterances.filter(u=>!known.has(u.id)&&u.recording_id===captureRecording);meeting={...next,utterances:[...next.utterances,...extra]};}
  async function refresh(){const next=await api(base);if(!disposed){merge(next);draw();}}
  function requestAnalysis(kind='overview',rid=selectedRecording){
    if(disposed)return Promise.resolve();if(analysisTask)return analysisTask.then(()=>requestAnalysis(kind,rid));
    analysisTask=Promise.resolve().then(()=>runAnalysis(kind,rid)).finally(()=>{analysisTask=null;if(!disposed)draw();});draw();return analysisTask;
  }
  async function runAnalysis(kind,rid){
    const target=new Set(recordingContent(meeting,rid).records.map(u=>u.id));if(!target.size)return;
    const endpoint=kind==='overview'?'summarize':'chapters';let remaining=target.size;const started=Date.now();analysisError=false;
    const progress=()=>{if(disposed)return;analysisMessage=`${recordingLabel(rid)} · ${kind==='overview'?'Updating overall summary':'Organizing live summaries'} · ${Math.floor((Date.now()-started)/1000)}s`;$('#meeting-summary-status').textContent=analysisMessage;};
    progress();const timer=setInterval(progress,1000);
    try{
      while(!disposed&&remaining){
        const next=await api(`${base}/${endpoint}${scope(rid)}`,'POST');if(disposed)return;merge(next);draw();
        const data=recordingContent(meeting,rid),ids=new Set(kind==='overview'?(data.overview?.evidence_ids||[]):data.sections.flatMap(s=>s.evidence_ids));
        const nextRemaining=[...target].filter(uid=>!ids.has(uid)).length;
        if(nextRemaining>=remaining)throw new Error('No new summary returned. Please retry.');remaining=nextRemaining;
      }
      analysisMessage=`${recordingLabel(rid)} · ${kind==='overview'?'Overall summary updated':'Live summaries updated'}`;
    }catch(e){analysisMessage=e.message;analysisError=true;}
    finally{clearInterval(timer);if(!disposed)draw();}
  }
  async function updateRecording(rid){if(!rid)return;await requestAnalysis('chapters',rid);if(!disposed&&!analysisError)await requestAnalysis('overview',rid);}
  function release(){capture?.disconnect();source?.disconnect();stream?.getTracks().forEach(t=>t.stop());context?.close().catch(()=>{});capture=source=stream=context=null;}
  function flush(){if(!pendingBuffers.length||socket?.readyState!==WebSocket.OPEN)return;const pcm=new Uint8Array(pendingBuffers.reduce((n,b)=>n+b.byteLength,0));let offset=0;for(const b of pendingBuffers){pcm.set(new Uint8Array(b),offset);offset+=b.byteLength;}pendingBuffers=[];socket.send(pcm);}
  async function stop(){if(!socket||stopping)return;stopping=true;release();flush();if(socket.readyState===WebSocket.OPEN)socket.send('stop');else socket.close();status('Saving final speech…');draw();}
  async function start(){
    $('#meeting-record').disabled=true;stopping=false;pendingBuffers=[];status('Connecting microphone…');
    try{
      stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});if(disposed){release();return;}
      socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/meetings/${id}`);
      socket.onmessage=async event=>{
        const p=JSON.parse(event.data);if(disposed)return;if(p.type==='warning')warning(p.message);
        if(p.type==='ready'){
          recordingRate=p.recording.sample_rate;captureRecording=p.recording.id;selectedRecording=captureRecording;meeting.recordings.push(p.recording);meeting.recording=true;draw();loadSelectedAudio();
          try{
            context=new AudioContext();await context.audioWorklet.addModule('/static/capture-worklet.js');if(disposed||stopping||!socket){release();return;}
            source=context.createMediaStreamSource(stream);capture=new AudioWorkletNode(context,'pcm16-capture',{processorOptions:{targetSampleRate:recordingRate,chunkSamples:recordingRate/10}});
            capture.port.onmessage=({data})=>{if(!socket||stopping)return;pendingBuffers.push(data);if(pendingBuffers.length>=10)flush();if(socket.bufferedAmount>recordingRate*20){warning('Connection too slow. Pausing; acknowledged audio is saved.');stop();}};
            source.connect(capture);capture.connect(context.destination);await context.resume();status('Recording');$('#meeting-record').textContent='Pause recording';draw();
          }catch(e){warning(e.message);stop();}
        }
        if(p.type==='saved'){const rec=meeting.recordings.find(r=>r.id===captureRecording);if(rec)rec.samples=p.samples;status(`Recording · ${meetingTime(p.samples/recordingRate*1000)} saved`);}
        if(p.type==='partial'&&selectedRecording===captureRecording)$('#meeting-partial').textContent=p.text;
        if(p.type==='utterance'){meeting.utterances.push(p.utterance);if(selectedRecording===captureRecording){$('#meeting-partial').textContent='';draw();if($('#meeting-follow').checked)$('#meeting-partial').scrollIntoView({block:'nearest'});}}
      };
      socket.onclose=()=>{const rid=captureRecording;release();socket=null;stopping=false;meeting.recording=false;captureRecording=null;if(!disposed){status('Paused · audio saved');$('#meeting-record').textContent='New recording';refresh().then(()=>{if(!disposed){loadSelectedAudio();return updateRecording(rid);}}).catch(e=>toast(e.message));}};
      socket.onerror=()=>warning('Connection failed. Check your connection and retry.');
    }catch(e){release();warning(e.message);draw();}
  }
  $('#meeting-record').onclick=()=>socket?stop():start();$('#meeting-analyze').onclick=()=>requestAnalysis('overview');$('#meeting-chapters-update').onclick=()=>requestAnalysis('chapters');
  $('#expand-paragraphs').onclick=()=>document.querySelectorAll('#meeting-transcript .meeting-paragraph').forEach(d=>{d.open=true;expansion.set(d.dataset.expand,true);});
  $('#collapse-paragraphs').onclick=()=>{stopFollowing();document.querySelectorAll('#meeting-transcript .meeting-paragraph').forEach(d=>{d.open=false;expansion.set(d.dataset.expand,false);});};
  $('#meeting-text').onclick=()=>openDialog('Add text note',field('speaker','Speaker','Unidentified speaker','text','required maxlength="80"')+'<div class="form-field"><label for="meeting-text-input">Spoken words</label><textarea id="meeting-text-input" name="content" required maxlength="6000"></textarea></div>',async fd=>{await api(`${base}/utterances`,'POST',{speaker:fd.get('speaker'),content:fd.get('content')});selectedRecording='notes';await refresh();if(!disposed)loadSelectedAudio();},'Add note');
  $('#meeting-end').onclick=async()=>{try{await requestAnalysis('overview');meeting=await api(`${base}/end`,'POST');status('Meeting ended');draw();}catch(e){toast(e.message);}};
  $('#meeting-delete').onclick=()=>openDialog('Delete meeting','<p>This removes all recordings, transcripts and summaries in this meeting.</p>',async()=>{await api(base,'DELETE');navigate('meetings');},'Delete meeting');
  const timer=setInterval(()=>{if(socket&&!stopping&&!analysisTask&&captureRecording)updateRecording(captureRecording);},60000);
  const remoteTimer=setInterval(()=>{if(meeting.recording&&!socket&&!disposed&&!analysisTask)refresh().catch(e=>toast(e.message));},3000);
  const unload=e=>{if(socket){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',unload);
  current={dispose(){disposed=true;clearInterval(timer);clearInterval(remoteTimer);clearTimeout(searchTimer);cancelAnimationFrame(scrollFrame);resizeObserver.disconnect();window.removeEventListener('scroll',onScroll);workspace.removeEventListener('focusin',onFocus);window.removeEventListener('beforeunload',unload);release();flush();$('#meeting-player')?.pause();dock.remove();document.documentElement.classList.remove('meeting-open');document.documentElement.style.removeProperty('--meeting-dock-height');document.documentElement.style.removeProperty('--meeting-nav-height');if(socket?.readyState===WebSocket.OPEN)socket.send('stop');else socket?.close();}};
  status(meeting.status==='ended'?'Meeting ended':'Ready to record');draw();loadSelectedAudio();
}
