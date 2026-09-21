import {mountFindings} from './meeting-findings.js?v=12';
import {mountInterventions} from './meeting-interventions.js?v=3';
import {editMeetingKnowledge, reviewMeetingUpdate, newProjectMeeting} from './meeting-project.js?v=project-simple-3';
import {TranscriptUpdates} from './meeting-live.js?v=live-transcript-1';
import {MeetingAudio} from './meeting-audio.js?v=tab-audio-4';
import {groupTranscript, recordingContent, speakerName, transcriptMatches, searchParts, playingUtterance, minutesContent, transcriptRecords} from './meeting-transcript.js?v=meeting-transcript-7';
const esc = (v='') => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const meetingTime = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
let current;
export function leaveMeeting(){current?.dispose();current=null;}

export async function showMeetings({api,shell,openDialog,field,navigate,toast,isCurrent=()=>true},id){
  if(!id){
    const [meetings,projects]=await Promise.all([api('/meetings'),api('/domains')]);if(!isCurrent())return;
    shell(`<div class="heading"><div><h1>Meetings</h1></div><button class="btn primary" id="new-meeting">New meeting</button></div>${meetings.length?meetings.map(m=>`<article class="session-row meeting-library-row"><a class="meeting-library-link" href="#meetings/${esc(m.id)}"><h3>${esc(m.title)}</h3><p class="muted">${m.project_name?esc(m.project_name)+' · ':''}${esc(m.status)} · ${new Date(m.created_at*1000).toLocaleString()}</p></a><details class="meeting-menu"><summary aria-label="Manage ${esc(m.title)}">…</summary><div class="meeting-menu-items"><button data-rename-meeting="${m.id}">Rename</button><a href="/api/meetings/${m.id}/export" download>Export meeting</a><button class="danger" data-delete-meeting="${m.id}">Delete meeting…</button></div></details></article>`).join(''):'<div class="empty"><h2>Your meetings will appear here</h2><p>Create a meeting to start recording.</p></div>'}`,'Meetings');
    document.querySelector('#new-meeting').onclick=()=>newProjectMeeting({api,openDialog,field,projects,onCreate:m=>navigate(`meetings/${m.id}`)});
    document.querySelectorAll('[data-rename-meeting]').forEach(b=>b.onclick=()=>{const m=meetings.find(m=>m.id===b.dataset.renameMeeting);b.closest('details').open=false;openDialog('Rename meeting',field('title','Meeting title',m.title,'text','required maxlength="120"'),async fd=>{await api(`/meetings/${m.id}`,'PATCH',{title:fd.get('title')});navigate('meetings');});});
    document.querySelectorAll('[data-delete-meeting]').forEach(b=>b.onclick=()=>{const m=meetings.find(m=>m.id===b.dataset.deleteMeeting);b.closest('details').open=false;openDialog('Delete meeting',`<p>Delete <strong>${esc(m.title)}</strong> and all its recordings, transcripts and notes? This cannot be undone.</p>`,async()=>{await api(`/meetings/${m.id}`,'DELETE');navigate('meetings');},'Delete meeting');});
    bindMenus(document.querySelector('.workspace'));return;
  }
  let meeting=await api(`/meetings/${id}`);if(!isCurrent())return;
  let disposed=false,socket,audioInput,context,capture,starting=false,stopping=false,recordingRate=16000,pendingBuffers=[],captureFlushed=null;
  let selectedRecording=meeting.recordings.at(-1)?.id||'notes',captureRecording=null,selectedPassage=null,selectedView='full';
  let analysisTask=null,analysisMessage='',analysisError=false,analysisRecording=null;
  let searchOpen=false,searchQuery='',searchIndex=-1,searchIds=[],playingId=null,followedId=null,searchTimer;
  let playbackRecords=[],activePanel='transcript',unread=0,partialSpeaker='Listening',refreshing=false;
  let minuteSources=[];
  const liveUpdates=new TranscriptUpdates();
  let liveDraft=null,feedConnected=false,refreshAgain=false;
  let eventFeed;
  const panelScroll={transcript:0,review:0,summary:0};
  let sourceReturn=null;
  let botBusy=false,projectUpdatesBusy=false,projectUpdateError='';
  const botActive=()=>!!meeting.connector?.bot&&!['ended','fatal_error','data_deleted','not_created'].includes(meeting.connector.bot.state);
  const base=`/meetings/${id}`,$=s=>document.querySelector(s);
  const recordingLabel=rid=>rid==='notes'?'Meeting notes':`Recording ${meeting.recordings.findIndex(r=>r.id===rid)+1}`;
  const scope=rid=>`?recording_id=${encodeURIComponent(rid)}`;
  const textOf=u=>u.content.replace(/\s+/g,' ').trim();
  shell(`<div class="heading meeting-heading"><div><a class="meeting-back" href="#meetings">← All meetings</a><h1>${esc(meeting.title)}</h1><p id="meeting-context"></p><button class="meeting-text-button" id="meeting-project">Project & knowledge</button><p id="meeting-knowledge-hint" class="muted" role="status" hidden></p></div><div class="actions"><button class="btn" id="meeting-end">End meeting</button></div></div>
    <div class="meeting-controls" aria-label="Choose how to record"><section class="meeting-bot" aria-labelledby="meeting-online-title"><div class="meeting-method-copy"><h2 id="meeting-online-title">Online meeting</h2></div><div class="meeting-method-actions"><button class="btn" id="bot-join">Invite Echooo</button><button class="btn" id="bot-leave" hidden>Leave meeting</button></div><p id="bot-status" role="status" aria-live="polite" hidden></p><p id="bot-error" class="meeting-warning" role="alert"></p><div id="bot-agent-controls" class="meeting-agent-controls" hidden><label><input type="checkbox" id="bot-chat-enabled"> Chat replies</label><label><input type="checkbox" id="bot-voice-enabled"> Answer when called</label><button class="btn" id="bot-stop">Stop speaking</button></div></section>
    <section class="meeting-capture" aria-labelledby="meeting-device-title"><div class="meeting-method-copy"><h2 id="meeting-device-title">Record audio</h2></div><div class="meeting-session-bar"><div class="meeting-audio-source"><label class="sr-only" id="meeting-audio-label" for="meeting-audio-source">Audio source</label><select id="meeting-audio-source" aria-labelledby="meeting-audio-label" aria-describedby="meeting-audio-help-copy"><option value="tab">Tab + microphone</option><option value="microphone">Microphone only</option></select></div><button class="btn primary" id="meeting-record">Start recording</button></div><details class="meeting-recording-help"><summary>Recording help</summary><p id="meeting-audio-help-copy" class="muted">Choose a Chrome tab and enable “Share tab audio”. Your microphone records your voice. Windows and full screens are not supported.</p></details><p id="capture-warning" class="meeting-warning" role="status"></p></section></div>
    <div class="meeting-processing"><div class="meeting-health"><p id="capture-status" role="status" class="sr-only"></p><p id="transcription-status" role="status"></p></div><button class="meeting-text-button" id="meeting-repair">Check saved audio</button></div>
    <div class="meeting-reader-toolbar"><div class="meeting-navigation"><div role="tablist" aria-label="Meeting content"><button id="tab-transcript" role="tab" aria-selected="true" aria-controls="panel-transcript" data-panel="transcript">Transcript</button><button id="tab-review" role="tab" aria-selected="false" aria-controls="panel-review" tabindex="-1" data-panel="review">Review<span id="review-count" class="review-count" hidden></span></button><button id="tab-summary" role="tab" aria-selected="false" aria-controls="panel-summary" tabindex="-1" data-panel="summary">Summary</button></div><div class="meeting-recording-tools"><span id="single-recording"></span><label class="meeting-recording-select" for="recording-picker"><span class="sr-only">Selected recording</span><select id="recording-picker"></select></label><button class="meeting-search-toggle" id="meeting-search-toggle" aria-label="Search transcript" title="Search transcript" aria-expanded="false" aria-controls="meeting-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg></button><details class="meeting-menu" id="recording-menu"><summary aria-label="More meeting options">…</summary><div class="meeting-menu-items"><button id="meeting-activity" aria-haspopup="dialog" aria-controls="meeting-activity-dialog">Messages & activity</button><button id="meeting-text">Add text note</button><div id="recording-options"></div></div></details></div></div>
      <div class="meeting-search" id="meeting-search" hidden><label class="sr-only" for="transcript-search">Search transcript</label><div class="meeting-search-controls"><input type="search" id="transcript-search" maxlength="200" placeholder="Search this conversation" autocomplete="off" aria-describedby="transcript-search-status"><button class="btn subtle" id="search-prev" aria-label="Previous matching passage" disabled>↑</button><button class="btn subtle" id="search-next" aria-label="Next matching passage" disabled>↓</button><button class="btn subtle" id="search-clear" disabled>Clear</button><button class="btn subtle" id="search-close" aria-label="Close search" title="Close search">×</button></div><p id="transcript-search-status" role="status" aria-live="polite"></p></div>
      <div class="meeting-live-controls"><span id="meeting-read-status" role="status"></span><button class="btn" id="meeting-latest" hidden>Back to live ↓</button><label class="meeting-follow"><input type="checkbox" id="meeting-follow" checked> Follow live</label></div>
    </div>
    <section id="panel-transcript" role="tabpanel" aria-labelledby="tab-transcript" class="meeting-transcript-section">
      <button id="return-to-review" class="meeting-text-button" hidden>← Back to review</button><h2 id="transcript-heading" class="sr-only" tabindex="-1">Conversation</h2>
      <div class="meeting-feed" aria-label="Conversation transcript"><div id="meeting-transcript"></div><article id="meeting-draft" class="meeting-paragraph meeting-draft" hidden><div class="paragraph-meta"><span id="draft-speaker">Listening</span><span class="paragraph-time">Transcribing…</span></div><p id="meeting-partial" class="meeting-prose"></p></article><div id="meeting-live-anchor"></div></div>

    </section>
    <section id="panel-review" role="tabpanel" aria-labelledby="tab-review" hidden><section id="meeting-findings" class="meeting-findings" aria-labelledby="finding-title"></section></section>
    <section id="panel-summary" role="tabpanel" aria-labelledby="tab-summary" hidden><div class="meeting-minutes-reader"><div class="meeting-section-heading"><h2>Overview</h2><div class="actions"><button class="btn" id="meeting-analyze">Generate summary</button><details class="meeting-menu" id="summary-menu" hidden><summary aria-label="Summary options">…</summary><div class="meeting-menu-items"><button id="meeting-regenerate">Regenerate summary</button></div></details></div></div><p class="meeting-summary-coverage" id="meeting-summary-coverage"></p><p id="meeting-summary-status" class="meeting-summary-status" role="status"></p><div id="meeting-minutes"></div><section id="meeting-approved-record" class="meeting-findings meeting-approved-record" aria-label="Confirmed results"></section><div id="meeting-discussion"></div><section id="meeting-project-updates" class="meeting-project-updates" hidden><div class="meeting-section-heading"><h2>Project updates</h2><button class="btn" id="prepare-project-updates">Prepare updates</button></div><p class="muted">Review before saving to the project.</p><p id="project-updates-status" role="status"></p><div id="project-update-list"></div></section></div></section>
    <dialog id="meeting-activity-dialog" class="meeting-activity-dialog" aria-labelledby="meeting-activity-title"><div class="dialog-head"><div><h2 id="meeting-activity-title">Messages & activity</h2></div><button class="btn" id="close-meeting-activity" autofocus aria-label="Close messages and activity">Close</button></div><div class="meeting-activity-body"><details class="inline-help"><summary>Meeting help</summary><p id="bot-help" class="muted"></p></details><details id="meeting-audio-help" class="meeting-audio-help"><summary>Recording tips</summary><p class="muted">For online meetings or videos, open the meeting or video in a Chrome tab before starting. Your microphone records your voice.</p></details><p class="meeting-activity-privacy">Private replies stay here and out of meeting notes.</p><section id="bot-agent-history" class="meeting-agent-history"><h3>Recent exchanges</h3><ol id="bot-agent-events"></ol></section><p id="meeting-activity-empty" class="meeting-placeholder">No messages yet.</p></div></dialog>
    <dialog id="meeting-source-dialog" class="meeting-source-dialog" aria-labelledby="meeting-source-title"><div class="dialog-head"><h2 id="meeting-source-title">Supporting conversation</h2><button class="btn" id="close-meeting-source" aria-label="Close source">Close</button></div><p id="meeting-source-point"></p><div id="meeting-source-passages"></div></dialog>
    <section class="meeting-player-wrap" aria-label="Recording player"><div class="meeting-player-title"><strong id="meeting-player-label"></strong><span id="meeting-playback" class="muted"></span></div><audio id="meeting-player" controls preload="none" aria-label="Selected recording audio"></audio><div class="meeting-player-tools"><button class="btn" id="play-back" aria-label="Back 10 seconds">−10s</button><button class="btn" id="play-forward" aria-label="Forward 10 seconds">+10s</button><label class="meeting-speed" for="play-speed">Speed<select id="play-speed"><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label><label class="meeting-follow"><input type="checkbox" id="follow-playback"> Follow playback</label></div></section>`,'Meetings');
  $('.meeting-reader-toolbar').insertAdjacentHTML('beforebegin','<section id="meeting-interventions" class="meeting-interventions" aria-label="Private suggested questions" hidden></section>');
  const interventionsPanel=mountInterventions($('#meeting-interventions'),{api,base,refresh,openDialog,showSource,
    getLocalRecording:()=>!disposed&&!stopping&&socket?.readyState===WebSocket.OPEN?captureRecording:null,
    });
  const findingsPanel=mountFindings($('#meeting-findings'),{api,base,refresh,showSource,recordRoot:$('#meeting-approved-record'),getRecordScope:()=>selectedRecording,
    onNextRecording(id){selectRecording(id);setPanel('review');},
    onPending(count){$('#review-count').textContent=` · ${count}`;$('#review-count').hidden=!count;$('#tab-review').setAttribute('aria-label',count?`Review, ${count} awaiting review`:'Review');},
    onRecord(finding){
      if(!finding){
        setPanel('summary');
        const section=$('#meeting-approved-record');
        section.tabIndex=-1;section.scrollIntoView({block:'start'});section.focus({preventScroll:true});
        return;
      }
      const recording=finding.evidence.some(e=>(e.recording_id||'notes')===selectedRecording)?selectedRecording:(finding.evidence[0]?.recording_id||'notes');
      if(recording!==selectedRecording)selectRecording(recording);
      setPanel('summary');
      const target=[...$('#meeting-approved-record').querySelectorAll('[data-confirmed-finding]')].find(node=>node.dataset.confirmedFinding===finding.id);
      if(target)for(let parent=target.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
      if(target){target.scrollIntoView({block:'center'});target.focus({preventScroll:true});}
    }});
  const dock=$('.meeting-player-wrap'),workspace=$('.workspace');
  // Outside the animated workspace, so fixed controls remain viewport-relative.
  $('.main').append(dock);workspace.classList.add('meeting-workspace');
  document.documentElement.classList.add('meeting-open');
  const status=message=>{if(!disposed)$('#capture-status').textContent=message;};
  const warning=message=>{if(!disposed){$('#capture-warning').textContent=message;}};
  const highlighted=text=>searchParts(text,searchQuery).map(p=>p.match?`<mark>${esc(p.text)}</mark>`:esc(p.text)).join('');
  const colorFor=speaker=>{const letter=/^Speaker ([A-Z])$/.exec(speaker);return letter?(letter[1].charCodeAt(0)-65)%6:[...speaker].reduce((hash,c)=>(hash*31+c.codePointAt(0))>>>0,0)%6;};
  const phraseHTML=(u,view)=>`<span role="button" tabindex="0" class="meeting-phrase" id="${view}-${u.id}" data-select="${u.id}" data-view="${view}" aria-label="${esc(`${meetingTime(u.start_ms)}: ${textOf(u)}`)}">${view==='full'?highlighted(textOf(u)):esc(textOf(u))}</span>`;
  const actionsHTML=u=>u?.assistant?`<span>Spoken reply${u.timing_estimated?' · Time estimated':''}. Original reply text; outbound speech may not be in the recording.</span><button class="meeting-text-button" data-clear>Close</button>`:u?`<span>${meetingTime(u.start_ms)}</span>${u.recording_id?`<button class="meeting-text-button" data-play="${u.id}">Play original</button>`:''}<button class="meeting-text-button" data-edit="${u.id}">Edit text / speaker</button><button class="meeting-text-button" data-clear>Close</button>`:'';
  function groupHTML(g,view){const selected=selectedView===view?g.records.find(u=>u.id===selectedPassage):null;return `<article class="meeting-paragraph" data-group="${g.records[0].id}" data-speaker-color="${colorFor(g.speaker)}"><div class="paragraph-meta"><span class="paragraph-speaker">${esc(g.speaker)}</span><span class="paragraph-time">${g.records[0].assistant?'Spoken reply · ':''}${g.records[0].timing_estimated?'~':''}${g.recordingId?meetingTime(g.records[0].start_ms):'Note'}</span></div><p class="meeting-prose">${g.records.map(u=>phraseHTML(u,view)).join(' ')}</p><div class="meeting-passage-actions" ${selected?'':'hidden'}>${actionsHTML(selected)}</div></article>`;}
  function setHTML(node,html){if(node._html!==html){node.innerHTML=html;node._html=html;}}
  function renderTranscript(records){
    const root=$('#meeting-transcript'),groups=groupTranscript(records),wanted=new Set(groups.map(g=>g.records[0].id));
    root.querySelector('.meeting-placeholder')?.remove();
    for(const child of [...root.children])if(!wanted.has(child.dataset.group))child.remove();
    groups.forEach((g,index)=>{
      let node=[...root.children].find(n=>n.dataset.group===g.records[0].id);
      if(!node){const template=document.createElement('template');template.innerHTML=groupHTML(g,'full');node=template.content.firstElementChild;}
      if(root.children[index]!==node)root.insertBefore(node,root.children[index]||null);
      const name=node.querySelector('.paragraph-speaker');if(name.textContent!==g.speaker)name.textContent=g.speaker;
      node.dataset.speakerColor=colorFor(g.speaker);
      const body=node.querySelector('.meeting-prose'),ids=new Set(g.records.map(u=>u.id));
      for(const phrase of [...body.querySelectorAll('[data-select]')])if(!ids.has(phrase.dataset.select)){if(phrase.nextSibling?.nodeType===3)phrase.nextSibling.remove();phrase.remove();}
      for(const [index,u] of g.records.entries()){
        let phrase=document.getElementById(`full-${u.id}`);
        if(!phrase||!body.contains(phrase)){const template=document.createElement('template');template.innerHTML=phraseHTML(u,'full');phrase=template.content.firstElementChild;if(body.childNodes.length)body.append(' ');body.append(phrase);}
        const at=body.querySelectorAll('[data-select]')[index];if(at!==phrase){body.insertBefore(phrase,at);body.insertBefore(document.createTextNode(' '),at);}
        const html=highlighted(textOf(u));if(phrase.innerHTML!==html)phrase.innerHTML=html;
        phrase.classList.toggle('selected',u.id===selectedPassage&&selectedView==='full');
        phrase.classList.toggle('search-current',u.id===searchIds[searchIndex]);
        phrase.setAttribute('aria-pressed',String(u.id===selectedPassage&&selectedView==='full'));
        phrase.setAttribute('aria-label',`${meetingTime(u.start_ms)}: ${textOf(u)}`);
      }
      const selected=selectedView==='full'?g.records.find(u=>u.id===selectedPassage):null,actions=node.querySelector('.meeting-passage-actions');
      setHTML(actions,actionsHTML(selected));actions.hidden=!selected;
    });
    if(!groups.length)root.innerHTML=`<p class="meeting-placeholder">${botActive()?'Waiting for speech from the online meeting…':meeting.recordings.length?'No speech has been transcribed in this recording.':'Choose a recording method above to get started.'}</p>`;
  }
  function updateHealth(){
    const rec=meeting.recordings.find(r=>r.id===selectedRecording),state=rec?.transcription||{phase:'unverified'};
    const messages={connecting:'Connecting transcription…',live:'Live transcription',reconnecting:'Transcription reconnecting · audio is saving',verifying:'Checking saved audio · refining transcript',complete:'Saved audio checked',error:'Audio saved · transcript check failed',interrupted:'Audio saved · transcript needs checking',unverified:'Transcript has not been checked against saved audio'};
    $('#transcription-status').textContent=selectedRecording==='notes'?'Text notes':(state.phase==='error'&&state.message?state.message:messages[state.phase])||messages.unverified;
    $('#transcription-status').dataset.phase=state.phase;
    $('#meeting-repair').hidden=selectedRecording==='notes'||!!socket||!!meeting.recording||(state.phase==='complete'&&state.summary_phase!=='error')||state.phase==='verifying'||!meeting.transcription_available;
    $('.meeting-processing').hidden=state.phase==='complete'&&state.summary_phase!=='error'||selectedRecording==='notes'||!rec;
    $('#meeting-repair').textContent=state.summary_phase==='error'?'Retry summary':state.phase==='error'?'Retry transcript check':'Check saved audio';
    $('#meeting-summary-coverage').textContent=state.summary_error||(selectedRecording==='notes'||state.phase==='complete'?'':'Transcript verification in progress.');
    $('#meeting-summary-coverage').hidden=!$('#meeting-summary-coverage').textContent;
  }
  function setPanel(panel){
    if(panel!==activePanel){panelScroll[activePanel]=window.scrollY;activePanel=panel;}else return;
    for(const button of document.querySelectorAll('[data-panel]')){const active=button.dataset.panel===panel;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;}
    for(const name of ['transcript','review','summary'])$(`#panel-${name}`).hidden=panel!==name;
    $('.meeting-recording-tools').hidden=false;
    $('.meeting-search').hidden=panel!=='transcript'||!searchOpen;
    $('#meeting-search-toggle').hidden=panel!=='transcript';
    $('#meeting-search-toggle').setAttribute('aria-expanded',String(panel==='transcript'&&searchOpen));
    $('.meeting-live-controls').hidden=panel!=='transcript'||!socket&&!meeting.recording;
    updateDockSpace();
    window.scrollTo({top:panelScroll[panel],behavior:'instant'});
  }
  function liveChanged(){
    if(selectedRecording!==captureRecording)return;
    if($('#meeting-follow').checked&&activePanel==='transcript'){
      if(!$('#meeting-activity-dialog').open&&!$('#meeting-source-dialog').open&&!$('#modal')?.open){$('#meeting-live-anchor').scrollIntoView({block:'end',behavior:'instant'});unread=0;}
    }else unread++;
    $('#meeting-latest').hidden=$('#meeting-follow').checked;
    $('#meeting-latest').textContent=unread?`${unread} new updates · Back to live ↓`:'Back to live ↓';
    $('#meeting-read-status').textContent=$('#meeting-follow').checked?'Following live':'Reading earlier conversation';
  }
  function showPartial(text,speaker){
    document.querySelectorAll('.meeting-inline-draft').forEach(node=>node.remove());
    partialSpeaker=speakerName(speaker||'Listening');
    const draft=$('#meeting-draft'),last=$('#meeting-transcript').lastElementChild;
    if(text&&last?.querySelector('.paragraph-speaker')?.textContent===partialSpeaker){
      let inline=last.querySelector('.meeting-inline-draft');if(!inline){inline=document.createElement('span');inline.className='meeting-inline-draft';last.querySelector('.meeting-prose').append(' ',inline);}inline.textContent=text;
      draft.hidden=true;
    }else{
      document.querySelector('.meeting-inline-draft')?.remove();
      draft.hidden=!text;$('#meeting-partial').textContent=text;$('#draft-speaker').textContent=partialSpeaker;
      draft.dataset.speakerColor=colorFor(partialSpeaker);
    }
    if(!text)document.querySelector('.meeting-inline-draft')?.remove();
  }
  function draw(){
    interventionsPanel.render(meeting);
    drawProject();
    if(disposed)return;
    drawBot();
    if(selectedRecording!=='notes'&&!meeting.recordings.some(r=>r.id===selectedRecording))selectedRecording=meeting.recordings.at(-1)?.id||'notes';
    findingsPanel.render(meeting);
    const {records}=recordingContent(meeting,selectedRecording);
    const {minutes,current:minutesCurrent}=minutesContent(meeting,selectedRecording);
    playbackRecords=records;
    const options=meeting.recordings.map((r,i)=>`<option value="${r.id}">Recording ${i+1} · ${meetingTime(r.samples/r.sample_rate*1000)}</option>`).join('')+(transcriptRecords(meeting).some(u=>!u.recording_id)||!meeting.recordings.length?'<option value="notes">Text notes</option>':'');
    setHTML($('#recording-picker'),options);$('#recording-picker').value=selectedRecording;$('#recording-picker').dispatchEvent(new Event('input'));
    updateHealth();$('.meeting-live-controls').hidden=activePanel!=='transcript'||!socket&&!meeting.recording;
    const completed=meeting.status==='ended',verified=meeting.recordings.find(r=>r.id===selectedRecording)?.transcription;
    $('#meeting-end').hidden=completed;$('#meeting-record').hidden=completed||botActive();
    $('.meeting-capture').hidden=completed||botActive();
    $('.meeting-bot').hidden=completed&&!botActive();
    $('.meeting-controls').hidden=completed&&!botActive();
    $('#meeting-context').textContent=completed?`Ended${verified?.phase==='complete'?' · Saved audio checked':''}`:meeting.recording?'Recording':'Active';
    const summaryBusy=!!analysisTask&&analysisRecording===selectedRecording||verified?.summary_phase==='building';
    const summaryFailed=analysisError&&analysisRecording===selectedRecording||verified?.summary_phase==='error'||!!verified?.summary_error;
    $('#meeting-summary-status').textContent=analysisRecording===selectedRecording?analysisMessage:'';$('#meeting-summary-status').dataset.error=String(analysisError&&analysisRecording===selectedRecording);
    const summaryAction=$('#meeting-analyze');
    summaryAction.textContent=summaryBusy?'Generating…':summaryFailed?'Retry':!minutes?'Generate summary':'Update summary';
    summaryAction.hidden=!!minutes&&minutesCurrent&&!summaryBusy&&!summaryFailed;
    summaryAction.disabled=!!analysisTask||summaryBusy||!records.length;
    $('#summary-menu').hidden=!minutes||!minutesCurrent||summaryBusy||summaryFailed;
    $('#meeting-regenerate').disabled=!!analysisTask||summaryBusy||!records.length;
    if(minutes&&!minutesCurrent&&!summaryBusy&&!$('#meeting-summary-coverage').textContent){$('#meeting-summary-coverage').textContent='Transcript changed · update summary.';$('#meeting-summary-coverage').hidden=false;}
    minuteSources=[];
    const pointHTML=item=>{const index=minuteSources.push(item)-1;return `<li><button class="minute-point" data-minute-source="${index}" aria-haspopup="dialog">${esc(item.text)}${item.kind==='action'?`<span class="minute-action-meta">${esc([item.status==='requested'?'Requested':'Committed',speakerName(item.owner||'').replace('Unidentified speaker',''),item.deadline].filter(Boolean).join(' · '))}</span>`:''}</button></li>`;};
    setHTML($('#meeting-minutes'),minutes?`<p class="minutes-overview">${esc(minutes.content.overview)}</p>`:`<p class="meeting-placeholder">${records.length?'No summary yet.':'Summary will appear after the conversation starts.'}</p>`);
    setHTML($('#meeting-discussion'),minutes&&(minutes.content.topics.length||minutes.content.outcomes.length)?`<section class="minutes-discussion"><h2>Discussion</h2>${minutes.content.topics.map(t=>`<section class="minutes-topic"><h3>${esc(t.title)}</h3><ul>${t.points.map(pointHTML).join('')}</ul></section>`).join('')}${minutes.content.outcomes.length?`<details class="minutes-highlights"><summary>Highlights</summary><ul>${minutes.content.outcomes.map(pointHTML).join('')}</ul></details>`:''}</section>`:'');
    updateSearchState(records);
    renderTranscript(records);
    if(liveDraft?.recording_id===selectedRecording)showPartial(liveDraft.text,liveDraft.speaker);else showPartial('');
    const picker=$('#recording-picker'),multiple=picker.options.length>1,rec=meeting.recordings.find(r=>r.id===selectedRecording);
    $('.meeting-recording-select').hidden=!multiple;$('#single-recording').hidden=multiple;
    $('#single-recording').textContent=rec?`${recordingLabel(rec.id)} · ${meetingTime(rec.samples/rec.sample_rate*1000)}`:'Text notes';
    $('#recording-menu').hidden=!rec&&completed;
    setHTML($('#recording-options'),rec?`<a href="/api${base}/recordings/${rec.id}/audio" download>Download audio</a><button class="danger" data-delete-recording="${rec.id}" ${socket||meeting.recording||analysisTask?'disabled':''}>Delete recording…</button>`:'');
    const remoteLive=botActive()&&meeting.recording&&selectedRecording===meeting.recordings.at(-1)?.id;
    $('#meeting-player-label').textContent=recordingLabel(selectedRecording);$('.meeting-player-wrap').hidden=selectedRecording==='notes'||!!socket||remoteLive;
    $('#meeting-player').hidden=!!socket&&selectedRecording===captureRecording||remoteLive;
    const playable=selectedRecording!=='notes'&&!(socket&&selectedRecording===captureRecording)&&!remoteLive;
    $('#play-back').disabled=$('#play-forward').disabled=$('#play-speed').disabled=$('#follow-playback').disabled=!playable;
    $('#meeting-record').disabled=meeting.status==='ended'||!!meeting.recording&&!socket||starting||stopping||botActive()||botBusy;
    $('#meeting-audio-source').disabled=starting||!!socket||!!meeting.recording||completed||botActive()||botBusy;
    $('.meeting-audio-source').hidden=completed||botActive();$('#meeting-audio-help').hidden=completed||botActive();$('.meeting-recording-help').hidden=completed||botActive();
    $('#meeting-end').disabled=meeting.status==='ended'||starting||!!socket||meeting.recording||!!analysisTask||botActive()||botBusy;$('#meeting-text').disabled=meeting.status==='ended';
    bindContent();
    syncPlayback(false);updateDockSpace();
  }
  function drawProject(){
    const k=meeting.knowledge||{},button=$('#meeting-project');
    button.textContent=k.project_name?`${k.project_name} · ${k.shared_count} ${k.shared_count===1?'memory':'memories'}`:'Choose project';
    const hint=$('#meeting-knowledge-hint');
    hint.textContent=k.project_id&&!k.shared_count?'No shareable project knowledge yet.':'';
    hint.hidden=!hint.textContent;
    $('#meeting-project-updates').hidden=!k.project_id;
    $('#prepare-project-updates').disabled=meeting.status!=='ended'||projectUpdatesBusy;
    $('#prepare-project-updates').textContent=projectUpdatesBusy?'Preparing…':'Prepare updates';
    const drafts=k.proposals||[];
    $('#project-updates-status').textContent=projectUpdateError||(meeting.status!=='ended'?'End the meeting to prepare project updates.':drafts.length?'':'No project updates prepared yet.');
    setHTML($('#project-update-list'),drafts.map(p=>`<article class="project-update"><p class="muted">${esc({pending:'Needs review',approved:'Saved',rejected:'Dismissed'}[p.status]||p.status)}${p.stale?' · Source changed':''}${p.target_title?' · Revises '+esc(p.target_title):''}</p><h3>${esc(p.title)}</h3><p>${esc(p.content)}</p>${p.status==='pending'?`<div class="actions"><button class="btn" data-review-update="${p.id}" ${p.stale?'disabled':''}>Review</button><button class="meeting-text-button" data-dismiss-update="${p.id}">Dismiss</button></div>`:''}</article>`).join(''));
    $('#project-update-list').querySelectorAll('[data-review-update]').forEach(b=>b.onclick=()=>reviewMeetingUpdate({api,openDialog,proposal:drafts.find(p=>p.id===b.dataset.reviewUpdate),onSave:refresh}).catch(e=>toast(e.message)));
    $('#project-update-list').querySelectorAll('[data-dismiss-update]').forEach(b=>b.onclick=async()=>{const p=drafts.find(p=>p.id===b.dataset.dismissUpdate);b.disabled=true;try{await api(`/proposals/${p.id}/review`,'POST',{decision:'reject',title:p.title,content:p.content});await refresh();}catch(e){toast(e.message);b.disabled=false;}});
  }

  function drawBot(){
    const connector=meeting.connector||{},bot=connector.bot,agent=connector.agent,active=botActive();
    const labels={creating:'Requesting entry…',unknown:'Confirming participant status…',ready:'Preparing to join…',joining:'Joining…',waiting_room:'Waiting for the host to admit Echooo AI',joined_not_recording:'In the meeting · waiting for audio',joined_recording:'In the meeting',joined_recording_paused:'In the meeting · recording paused',joined_recording_permission_denied:'In the meeting · recording permission needed',leaving:'Leaving…',post_processing:'Finishing…',ended:'Left the meeting',fatal_error:'Participant disconnected',not_created:'Could not join',data_deleted:'Participant session ended'};
    $('#bot-status').textContent=botBusy?'Sending request…':bot?.desired_state==='left'&&active?'Leaving · waiting for confirmation…':bot?`${bot.bot_name} · ${labels[bot.state]||'Updating status…'}${connector.audio_connected?' · audio connected':''}${agent?' · '+({listening:agent.deciding_turn?'Considering your follow-up…':agent.conversation_active?'Ready for your follow-up':'Listening',thinking:'Thinking…',speaking:'Speaking…',paused:'Pausing to listen…',waiting:'Waiting'}[agent.phase]||agent.phase):''}`:'Join Zoom, Google Meet or Microsoft Teams as a separate participant.';
    $('#bot-status').hidden=!active&&!botBusy;
    $('#bot-help').textContent=!connector.configured?'The self-hosted meeting connector needs to be configured before joining.':active?`${bot?.platform==='zoom'?'Send Echooo a private message, address Echooo in meeting chat,':'Address Echooo in public meeting chat'} or say “Echooo, …”. ${agent?.conversation_active?`You can follow up without saying Echooo${agent.follow_up_seconds?` · ${agent.follow_up_seconds}s remaining`:""}.`:"After a spoken reply, follow up within 15 seconds without repeating Echooo. It uses conversation context to decide when to answer."} Say “stop” to stop or “that’s all” to end the conversation.`:'Echooo joins as an AI participant, records audio and answers when addressed. Tell participants before inviting it; the host may need to admit it.';
    const audioStale=active&&bot?.state==='joined_recording'&&(!connector.last_audio_at||Date.now()/1000-connector.last_audio_at>15);
    $('#bot-error').textContent=bot?.error||agent?.error||(agent&&!agent.voice_available?'Voice replies need server speech synthesis and live transcription. Meeting chat can still be used.':'')||(audioStale?'Waiting for meeting audio. If this persists, check recording permissions in the meeting.':'');
    $('#bot-error').hidden=!$('#bot-error').textContent;
    $('#bot-join').hidden=active||meeting.status==='ended';
    $('#bot-join').disabled=botBusy||!connector.configured||!!socket||!!meeting.recording||starting||stopping;
    $('#bot-leave').hidden=!active;$('#bot-leave').disabled=botBusy||bot?.desired_state==='left';
    $('#bot-agent-controls').hidden=!active||!agent;
    if(agent){
      $('#bot-chat-enabled').checked=agent.chat_enabled;$('#bot-voice-enabled').checked=agent.voice_enabled;
      $('#bot-chat-enabled').disabled=botBusy;$('#bot-voice-enabled').disabled=botBusy||!agent.voice_available;
      $('#bot-stop').disabled=botBusy||!agent.voice_enabled;
    }
    const events=agent?.events||[];
    $('#bot-agent-history').hidden=!events.length;
    $('#meeting-activity-empty').hidden=!!events.length;
    setHTML($('#bot-agent-events'),events.map(e=>`<li><p class="muted">${esc({private:'Private reply to sender',public:'Meeting chat',voice:'Spoken reply'}[e.audience])} · ${esc({submitted:'Submitted to meeting chat',spoken:'Speech played',thinking:'Thinking…',speaking:'Speaking…',queued:'Queued',interrupted:'Interrupted',uncertain:'Delivery unconfirmed',error:'Failed',skipped:'Skipped'}[e.status]||e.status)}</p><p>${esc(e.request)}</p>${e.response?`<p class="meeting-agent-answer">${esc(e.response)}</p>`:''}${e.citations?.length?`<details class="project-answer-sources"><summary>Sources · ${e.citations.length}</summary>${e.citations.map(c=>`<blockquote><strong>${esc(c.title)}${c.version?' · v'+c.version:''}</strong><p>${esc(c.changed?'Source changed since this answer.':c.content)}</p>${c.kind==='utterance'?`<button class="meeting-text-button" data-answer-passage="${c.id}">View passage</button>`:`<a href="#domain/${encodeURIComponent(c.domain_id)}/memories">Open knowledge domain</a>`}</blockquote>`).join('')}</details>`:''}${e.error?`<p class="meeting-warning">${esc(e.error)}</p>`:''}</li>`).join(''));
    if(bot&&!socket)status(active?(bot.desired_state==='left'?'Saving meeting audio…':connector.audio_connected?'Recording from Echooo AI':'Waiting for Echooo AI audio'):meeting.recordings.length?'Audio saved':'Ready to record');
  }
  function bindContent(){
    bindMenus(workspace);
    document.querySelectorAll('[data-answer-passage]').forEach(b=>b.onclick=()=>{const u=meeting.utterances.find(u=>u.id===b.dataset.answerPassage);if(u)showSource({text:'Answer source',evidence_ids:[u.id]});});
    document.querySelectorAll('[data-minute-source]').forEach(b=>b.onclick=()=>showSource(minuteSources[Number(b.dataset.minuteSource)]));
    document.querySelectorAll('[data-select]').forEach(b=>{
      b.onclick=()=>{if(!window.getSelection()?.isCollapsed)return;selectedPassage=b.dataset.select;selectedView=b.dataset.view;stopFollowing();draw();document.getElementById(`${selectedView}-${selectedPassage}`)?.focus({preventScroll:true});};
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
    document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{
      const u=meeting.utterances.find(u=>u.id===b.dataset.edit);
      openDialog('Correct transcript',field('speaker','Speaker',speakerName(u.speaker),'text','required maxlength="80"')+`<div class="form-field"><label for="meeting-correction">Original words</label><textarea id="meeting-correction" name="content" required maxlength="6000">${esc(u.content)}</textarea></div>`,async fd=>{const since=liveUpdates.version;const next=await api(`${base}/utterances/${u.id}`,'PATCH',{speaker:fd.get('speaker')===speakerName(u.speaker)?u.speaker:fd.get('speaker'),content:fd.get('content')});if(disposed)return;merge(next,since);draw();toast('Transcript corrected. Update notes to include the correction.');});
    });
  }
  function showSource(item){
    sourceReturn=activePanel==='review'?{scroll:window.scrollY,focus:document.activeElement}:null;
    const dialog=$('#meeting-source-dialog');$('#meeting-source-point').textContent=item.text;
    const passages=meeting.utterances.filter(u=>item.evidence_ids.includes(u.id)).sort((a,b)=>a.start_ms-b.start_ms);
    $('#meeting-source-passages').innerHTML=passages.map(u=>`<article class="minute-source-passage"><p class="muted">${esc(item.speaker_names?.[u.id]||speakerName(u.speaker))}${u.recording_id?` · ${meetingTime(u.start_ms)}`:''}</p><p>${esc(u.content)}</p><button class="meeting-text-button" data-source-jump="${u.id}">Go to transcript${u.recording_id?` · ${meetingTime(u.start_ms)}`:''}</button></article>`).join('')||'<p class="muted">This transcript evidence is no longer available.</p>';
    dialog.querySelectorAll('[data-source-jump]').forEach(b=>b.onclick=()=>{const u=meeting.utterances.find(u=>u.id===b.dataset.sourceJump);dialog.close();const reviewScroll=sourceReturn?.scroll;if(selectedRecording!==(u.recording_id||'notes'))selectRecording(u.recording_id||'notes');selectedPassage=u.id;selectedView='full';stopFollowing();setPanel('transcript');if(reviewScroll!==undefined){panelScroll.review=reviewScroll;$('#return-to-review').hidden=false;}draw();if(u.recording_id)loadSelectedAudio(u.start_ms);const phrase=openPassage(u.id);phrase?.scrollIntoView({block:'center'});phrase?.focus({preventScroll:true});});
    dialog.showModal();
  }
  $('#return-to-review').onclick=()=>{setPanel('review');if(sourceReturn){window.scrollTo({top:sourceReturn.scroll,behavior:'instant'});if(sourceReturn.focus?.isConnected)sourceReturn.focus.focus({preventScroll:true});}sourceReturn=null;$('#return-to-review').hidden=true;};
  $('#close-meeting-source').onclick=()=>$('#meeting-source-dialog').close();
  function loadSelectedAudio(ms=0,autoplay=false){
    const player=$('#meeting-player');player.pause();player.onloadedmetadata=null;playingId=null;followedId=null;
    player.playbackRate=Number($('#play-speed').value);syncPlayback(false);
    if(selectedRecording==='notes'){player.removeAttribute('src');player.load();return;}
    if(socket&&selectedRecording===captureRecording||botActive()&&meeting.recording&&selectedRecording===meeting.recordings.at(-1)?.id){player.removeAttribute('src');player.load();$('#meeting-playback').textContent='Original audio will be ready after recording stops.';return;}
    const url=`/api${base}/recordings/${selectedRecording}/audio`,seek=()=>{player.playbackRate=Number($('#play-speed').value);player.currentTime=Math.min(ms/1000,Number.isFinite(player.duration)?player.duration:ms/1000);syncPlayback();if(autoplay)player.play().catch(e=>{if(e.name!=='AbortError'&&!disposed)toast(e.message);});};
    if(player.getAttribute('src')!==url){player.onloadedmetadata=seek;player.src=url;player.load();}else if(Number.isFinite(player.duration))seek();else{player.onloadedmetadata=seek;player.load();}
    $('#meeting-playback').textContent='Original audio';
  }
  function selectRecording(rid){stopFollowing();selectedRecording=rid;selectedPassage=null;searchQuery='';searchIndex=-1;searchIds=[];$('#transcript-search').value='';analysisMessage='';analysisError=false;showPartial('');draw();loadSelectedAudio();panelScroll.transcript=panelScroll.summary=panelScroll.review=0;$('.meeting-reader-toolbar').scrollIntoView({block:'start',behavior:'instant'});}
  function playPassage(uid){const u=meeting.utterances.find(u=>u.id===uid);if(!u?.recording_id)return;if(selectedRecording!==u.recording_id){selectedRecording=u.recording_id;draw();}loadSelectedAudio(u.start_ms,true);}

  function stopFollowing(){$('#meeting-follow').checked=false;$('#follow-playback').checked=false;$('#meeting-latest').hidden=!socket&&!meeting.recording;$('#meeting-read-status').textContent='Auto-follow paused';}
  function updateSearchState(records){
    const previous=searchIds[searchIndex];searchIds=transcriptMatches(records,searchQuery);searchIndex=previous?searchIds.indexOf(previous):-1;
    $('#transcript-search-status').textContent=!searchQuery?'':!searchIds.length?'No matches in this recording.':`${searchIndex<0?'':`${searchIndex+1} of `}${searchIds.length} matching passages · Enter for next`;
    $('#search-prev').disabled=$('#search-next').disabled=!searchIds.length;$('#search-clear').disabled=!searchQuery;
  }
  function openPassage(uid){
    const phrase=document.getElementById(`full-${uid}`);if(!phrase)return null;
    setPanel('transcript');return phrase;
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
    if(allowScroll&&playingId&&activePanel==='transcript'&&!document.querySelector('dialog[open]')&&$('#follow-playback').checked&&followedId!==playingId){
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
    // Size only fixed controls; the document owns transcript and summary scrolling.
    const main=$('.main').getBoundingClientRect();
    dock.style.left=`${Math.max(0,main.left)}px`;dock.style.right=`${Math.max(0,innerWidth-main.right)}px`;
    document.documentElement.style.setProperty('--meeting-nav-height',`${Math.ceil($('.meeting-reader-toolbar').getBoundingClientRect().height)}px`);
  }
  const onFocus=e=>{
    if(!e.target.closest('#panel-transcript,#panel-review,#panel-summary')||!e.target.matches('button,input,summary,[tabindex],a'))return;
    const rect=e.target.getBoundingClientRect(),bottom=dock.hidden?innerHeight:dock.getBoundingClientRect().top;
    if(rect.bottom>bottom||rect.top<$('.meeting-reader-toolbar').getBoundingClientRect().bottom)e.target.scrollIntoView({block:'center'});
  };
  const resizeObserver=new ResizeObserver(updateDockSpace);resizeObserver.observe(dock);resizeObserver.observe($('.meeting-reader-toolbar'));window.addEventListener('resize',updateDockSpace);
  workspace.addEventListener('focusin',onFocus);
  document.querySelectorAll('[data-panel]').forEach(b=>{
    b.onmousedown=e=>{if(e.button===0){e.preventDefault();b.focus({preventScroll:true});}};
    b.onclick=()=>setPanel(b.dataset.panel);
    b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const panels=['transcript','review','summary'],index=panels.indexOf(b.dataset.panel);const panel=e.key==='Home'?panels[0]:e.key==='End'?panels.at(-1):panels[(index+(e.key==='ArrowRight'?1:2))%3];setPanel(panel);$(`#tab-${panel}`).focus({preventScroll:true});}};
  });
  // User scroll intent pauses following; programmatic source/search jumps do not.
  const onReadIntent=e=>{
    if(e.target.closest?.('dialog,select,[role="listbox"],.sidebar'))return;
    if(e.type==='keydown'&&(!['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key)||e.target.closest?.('input,textarea,button,[role="button"],[role="tab"],[role="combobox"],summary')))return;
    if(e.type==='wheel'&&!e.deltaY)return;
    if($('#meeting-follow').checked||$('#follow-playback').checked)stopFollowing();
  };
  window.addEventListener('wheel',onReadIntent,{passive:true});window.addEventListener('touchmove',onReadIntent,{passive:true});window.addEventListener('keydown',onReadIntent);
  const activity=$('#meeting-activity-dialog');
  $('#meeting-activity').onclick=()=>{$('#recording-menu').open=false;activity.showModal();};
  $('#close-meeting-activity').onclick=()=>activity.close();
  activity.addEventListener('close',()=>$('#recording-menu > summary')?.focus({preventScroll:true}));
  activity.addEventListener('click',e=>{if(e.target===activity){const r=activity.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)activity.close();}});
  $('#meeting-latest').onclick=()=>{setPanel('transcript');$('#meeting-follow').checked=true;$('#follow-playback').checked=false;liveChanged();};
  $('#recording-picker').onchange=e=>selectRecording(e.target.value);
  $('#meeting-repair').onclick=async()=>{try{$('#meeting-repair').disabled=true;meeting=await api(`${base}/recordings/${selectedRecording}/transcribe`,'POST');draw();}catch(e){toast(e.message);}finally{if(!disposed)$('#meeting-repair').disabled=false;}};
  function toggleSearch(open){
    searchOpen=open;
    $('.meeting-search').hidden=!open||activePanel!=='transcript';
    $('#meeting-search-toggle').setAttribute('aria-expanded',String(open&&activePanel==='transcript'));
    if(open)$('#transcript-search').focus({preventScroll:true});
    else {$('#transcript-search').value='';applySearch();$('#meeting-search-toggle').focus({preventScroll:true});}
    updateDockSpace();
  }
  $('#meeting-search-toggle').onclick=()=>toggleSearch(!searchOpen);
  $('#search-close').onclick=()=>toggleSearch(false);
  $('#transcript-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(applySearch,120);};
  $('#transcript-search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(searchQuery!==e.target.value.trim())applySearch();navigateMatch(e.shiftKey?-1:1);}else if(e.key==='Escape'){e.preventDefault();toggleSearch(false);}};
  $('#search-prev').onclick=()=>navigateMatch(-1);$('#search-next').onclick=()=>navigateMatch(1);
  $('#search-clear').onclick=()=>{$('#transcript-search').value='';applySearch();$('#transcript-search').focus();};
  $('#play-back').onclick=()=>seekBy(-10);$('#play-forward').onclick=()=>seekBy(10);
  $('#play-speed').onchange=()=>{$('#meeting-player').playbackRate=Number($('#play-speed').value);};
  $('#meeting-player').ontimeupdate=()=>syncPlayback();$('#meeting-player').onplay=()=>syncPlayback();$('#meeting-player').onseeked=()=>syncPlayback();$('#meeting-player').onended=()=>syncPlayback(false);
  $('#meeting-player').onerror=()=>{if($('#meeting-player').getAttribute('src'))$('#meeting-playback').textContent='Audio unavailable. Try reselecting the recording.';};
  $('#follow-playback').onchange=()=>{if($('#follow-playback').checked){$('#meeting-follow').checked=false;followedId=null;syncPlayback();}};
  $('#meeting-follow').onchange=()=>{if($('#meeting-follow').checked)$('#follow-playback').checked=false;liveChanged();};
  function merge(next,since=liveUpdates.version){
    const previous=meeting.recordings.at(-1)?.id||'notes',latest=next.recordings.at(-1)?.id;
    if(botActive()&&latest&&latest!==previous&&selectedRecording===previous&&$('#meeting-follow').checked)selectedRecording=latest;
    const known=new Set(next.utterances.map(u=>u.id));const extra=socket?meeting.utterances.filter(u=>!known.has(u.id)&&u.recording_id===captureRecording):[];
    meeting={...next,utterances:liveUpdates.merge([...next.utterances,...extra],since)};
    if(botActive())captureRecording=latest;
  }
  async function refresh(){
    if(refreshing){refreshAgain=true;return;}
    refreshing=true;const since=liveUpdates.version;
    try{
      const next=await api(base);
      if(!disposed){
        const count=transcriptRecords(meeting).length,previous=selectedRecording;
        const remoteStopped=!!meeting.connector?.bot&&meeting.recording&&!next.recording;
        merge(next,since);draw();
        if(previous!==selectedRecording||remoteStopped)loadSelectedAudio();
        if(transcriptRecords(meeting).length>count)liveChanged();
      }
    }finally{
      refreshing=false;
      if(refreshAgain&&!disposed){refreshAgain=false;refresh().catch(()=>{});}
    }
  }
  function receiveLive(p){
    if(disposed)return;
    if(p.type==='findings'||p.type==='interventions'){refresh().catch(()=>{});return;}
    if(p.type==='resync'){liveDraft=null;showPartial('');refresh().catch(()=>{});return;}
    if(p.type==='partial'){
      liveDraft=p.text?p:null;
      if(!meeting.recordings.some(r=>r.id===p.recording_id))refresh().catch(()=>{});
      if(selectedRecording===p.recording_id){showPartial(p.text,p.speaker);if(p.text)liveChanged();}
    }
    if(p.type==='utterance'){
      const u=p.utterance,index=meeting.utterances.findIndex(old=>old.id===u.id);
      const previous=index<0?null:meeting.utterances[index];
      liveUpdates.receive(u);
      if(index<0)meeting.utterances.push(u);else meeting.utterances[index]=u;
      if(!meeting.recordings.some(r=>r.id===u.recording_id))refresh().catch(()=>{});
      if(selectedRecording===u.recording_id){
        playbackRecords=recordingContent(meeting,selectedRecording).records;
        updateSearchState(playbackRecords);renderTranscript(playbackRecords);bindContent();
        if(liveDraft?.recording_id===selectedRecording)showPartial(liveDraft.text,liveDraft.speaker);
        if(!previous)liveChanged();
      }
    }
  }
  if(typeof EventSource!=='undefined'){
    eventFeed=new EventSource(`/api${base}/events`);
    eventFeed.onopen=()=>{feedConnected=true;};
    eventFeed.onerror=()=>{feedConnected=false;};
    eventFeed.onmessage=event=>{try{receiveLive(JSON.parse(event.data));}catch(error){console.warn('Live transcript update failed',error);}};
  }
  function requestAnalysis(force=false,rid=selectedRecording){
    if(disposed)return Promise.resolve();if(analysisTask)return analysisTask;
    analysisRecording=rid;analysisMessage='';analysisError=false;
    analysisTask=Promise.resolve().then(()=>runAnalysis(force,rid)).finally(()=>{analysisTask=null;if(!disposed)draw();});draw();return analysisTask;
  }
  async function runAnalysis(force,rid){
    if(!recordingContent(meeting,rid).records.length)return;
    let remaining=Infinity;analysisError=false;
    try{
      while(!disposed&&remaining){
        const since=liveUpdates.version;const next=await api(`${base}/minutes${scope(rid)}${force?'&force=true':''}`,'POST');if(disposed)return;force=false;merge(next,since);draw();
        const nextRemaining=next.summary_remaining;
        if(nextRemaining>=remaining)throw new Error('No summary returned. Please retry.');remaining=nextRemaining;
      }
      analysisMessage='';
    }catch(e){analysisMessage=e.message;analysisError=true;}
    finally{if(!disposed)draw();}
  }
  async function updateRecording(rid){if(rid)await requestAnalysis(false,rid);}
  function release(){interventionsPanel.stopLocalSpeech();capture?.disconnect();audioInput?.close();context?.close().catch(()=>{});capture=audioInput=context=null;}
  function flush(){if(!pendingBuffers.length||socket?.readyState!==WebSocket.OPEN)return;const pcm=new Uint8Array(pendingBuffers.reduce((n,b)=>n+b.byteLength,0));let offset=0;for(const b of pendingBuffers){pcm.set(new Uint8Array(b),offset);offset+=b.byteLength;}pendingBuffers=[];socket.send(pcm);}
  async function stop(){interventionsPanel.stopLocalSpeech();if(!socket||stopping)return;stopping=true;status('Saving final speech…');if(capture){await new Promise(resolve=>{const timeout=setTimeout(()=>{captureFlushed=null;resolve();},500);captureFlushed=()=>{clearTimeout(timeout);captureFlushed=null;resolve();};capture.port.postMessage({type:'flush'});});}release();flush();if(socket.readyState===WebSocket.OPEN)socket.send('stop');else socket.close();status('Saving final speech…');draw();}
  async function start(){
    if(starting||disposed)return;
    starting=true;stopping=false;pendingBuffers=[];warning('');$('#meeting-player').pause();draw();
    const includeTab=$('#meeting-audio-source').value==='tab';
    status(includeTab?'Choose a tab and share its audio…':'Connecting microphone…');
    try{
      audioInput=new MeetingAudio({onEnded:()=>{warning('An audio source stopped. Recording ended automatically.');if(socket)stop();}});
      await audioInput.open(includeTab);if(disposed){release();return;}
      status('Connecting recording…');
      socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/meetings/${id}`);
      socket.onmessage=async event=>{
        const p=JSON.parse(event.data);if(disposed)return;if(p.type==='warning')warning(p.message);
        if(p.type==='transcription'){const rec=meeting.recordings.find(r=>r.id===p.recording_id);if(rec)rec.transcription=p.state;updateHealth();findingsPanel.render(meeting);}
        if(p.type==='ready'){
          if(stopping)return;
          recordingRate=p.recording.sample_rate;captureRecording=p.recording.id;selectedRecording=captureRecording;meeting.recordings.push(p.recording);meeting.recording=true;setPanel('transcript');$('#meeting-follow').checked=true;warning('');draw();loadSelectedAudio();
          try{
            context=new AudioContext();await context.audioWorklet.addModule('/static/capture-worklet.js?v=meeting-minutes-6');if(disposed||stopping||!socket){release();return;}
            capture=new AudioWorkletNode(context,'pcm16-capture',{processorOptions:{targetSampleRate:recordingRate,chunkSamples:recordingRate/10}});
            capture.port.onmessage=({data})=>{if(data?.type==='flushed'){captureFlushed?.();return;}if(!socket||!(data instanceof ArrayBuffer))return;pendingBuffers.push(data);flush();if(socket.bufferedAmount>recordingRate*20){warning('Connection too slow. Pausing; acknowledged audio is saved.');stop();}};
            audioInput.connect(context,capture);capture.connect(context.destination);await context.resume();if(disposed||stopping)return;status(includeTab?'Recording · tab + microphone':'Recording · microphone');$('#meeting-record').textContent='Stop recording';draw();
          }catch(e){warning(e.message);stop();}
        }
        if(p.type==='saved'){const rec=meeting.recordings.find(r=>r.id===captureRecording);if(rec)rec.samples=p.samples;status(`Recording · ${includeTab?'tab + microphone':'microphone'} · ${meetingTime(p.samples/recordingRate*1000)} saved`);}
        if(p.type==='partial'&&!feedConnected)receiveLive({...p,recording_id:captureRecording});
        if(p.type==='utterance'&&!feedConnected){receiveLive({type:'partial',text:'',recording_id:captureRecording});receiveLive(p);}
      };
      socket.onclose=()=>{const rid=captureRecording;liveDraft=null;release();socket=null;stopping=false;meeting.recording=false;captureRecording=null;if(!disposed){showPartial('');$('#meeting-latest').hidden=true;$('#meeting-read-status').textContent='';status('Audio saved');$('#meeting-record').textContent='New recording';refresh().then(()=>{if(!disposed){loadSelectedAudio();if(!meeting.transcription_available)return updateRecording(rid);}}).catch(e=>toast(e.message));}};
      socket.onerror=()=>warning('Connection failed. Check your connection and retry.');
    }catch(e){release();warning(e.message);status('Recording not started');}
    finally{starting=false;if(!disposed)draw();}
  }
  $('#meeting-audio-source').onchange=()=>{$('#meeting-audio-help-copy').textContent=$('#meeting-audio-source').value==='tab'?'Choose a Chrome tab and enable “Share tab audio”. Your microphone records your voice. Windows and full screens are not supported.':'Records your microphone only. Audio playing on your computer is not shared.';};
  $('#meeting-record').onclick=()=>socket?stop():start();$('#meeting-analyze').onclick=()=>requestAnalysis(true);$('#meeting-regenerate').onclick=()=>{$('#summary-menu').open=false;requestAnalysis(true);};
  $('#meeting-text').onclick=()=>{$('#recording-menu').open=false;openDialog('Add text note',field('speaker','Speaker','Unidentified speaker','text','required maxlength="80"')+'<div class="form-field"><label for="meeting-text-input">Spoken words</label><textarea id="meeting-text-input" name="content" required maxlength="6000"></textarea></div>',async fd=>{await api(`${base}/utterances`,'POST',{speaker:fd.get('speaker'),content:fd.get('content')});selectedRecording='notes';await refresh();if(!disposed)loadSelectedAudio();},'Add note');};
  $('#meeting-project').onclick=()=>editMeetingKnowledge({api,openDialog,meeting,onSave:async k=>{meeting.knowledge=k;await refresh();}}).catch(e=>toast(e.message));
  $('#prepare-project-updates').onclick=async()=>{projectUpdatesBusy=true;projectUpdateError='';drawProject();try{const drafts=await api(`${base}/memory-proposals`,'POST');await refresh();if(!drafts.length){projectUpdateError='No supported project changes were found.';}}catch(e){projectUpdateError=e.message;}finally{projectUpdatesBusy=false;drawProject();}};
  $('#bot-join').onclick=()=>openDialog('Invite Echooo AI',`${field('meeting_url','Meeting link','','url','required maxlength="2048" placeholder="https://meet.google.com/…"')}${field('bot_name','Participant name','Echooo AI','text','required maxlength="60"')}<p>Echooo joins as an AI participant and records the meeting. Let participants know; the host may need to admit it.</p>`,async fd=>{
    botBusy=true;draw();
    try{meeting.connector=await api(`${base}/bot`,'POST',{meeting_url:fd.get('meeting_url'),bot_name:fd.get('bot_name')});await refresh();}
    finally{botBusy=false;draw();}
  },'Join meeting');
  $('#bot-leave').onclick=async()=>{
    botBusy=true;draw();
    try{meeting.connector=await api(`${base}/bot/leave`,'POST');await refresh();}
    catch(e){toast(e.message);}finally{botBusy=false;draw();}
  };
  const agentControl=async(path,method,body)=>{
    botBusy=true;draw();
    try{meeting.connector=await api(`${base}/bot/${path}`,method,body);}
    catch(e){toast(e.message);}finally{botBusy=false;draw();}
  };
  $('#bot-stop').onclick=()=>agentControl('stop','POST');
  const updateAgent=()=>agentControl('agent','PATCH',{chat_enabled:$('#bot-chat-enabled').checked,voice_enabled:$('#bot-voice-enabled').checked});
  $('#bot-chat-enabled').onchange=updateAgent;$('#bot-voice-enabled').onchange=updateAgent;
  $('#meeting-end').onclick=async()=>{try{await requestAnalysis();meeting=await api(`${base}/end`,'POST');status('Meeting ended');draw();}catch(e){toast(e.message);}};
  const timer=setInterval(()=>{if(socket&&!stopping&&!analysisTask&&captureRecording)updateRecording(captureRecording);},60000);
  const remoteTimer=setInterval(()=>{if(!disposed&&(!socket||meeting.recordings.some(r=>r.transcription?.phase==='verifying')))refresh().catch(()=>{});},3000);
  const unload=e=>{if(socket){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',unload);
  current={dispose(){disposed=true;interventionsPanel.dispose();findingsPanel.dispose();eventFeed?.close();clearInterval(timer);clearInterval(remoteTimer);clearTimeout(searchTimer);resizeObserver.disconnect();window.removeEventListener('resize',updateDockSpace);window.removeEventListener('wheel',onReadIntent);window.removeEventListener('touchmove',onReadIntent);window.removeEventListener('keydown',onReadIntent);activity.close();workspace.removeEventListener('focusin',onFocus);window.removeEventListener('beforeunload',unload);release();flush();$('#meeting-player')?.pause();$('#meeting-source-dialog')?.close();dock.remove();document.documentElement.classList.remove('meeting-open');document.documentElement.style.removeProperty('--meeting-dock-height');document.documentElement.style.removeProperty('--meeting-nav-height');if(socket?.readyState===WebSocket.OPEN)socket.send('stop');else socket?.close();}};
  status(meeting.status==='ended'?'Meeting ended':meeting.recording?'Recording on another page':meeting.recordings.length?'Audio saved':'Ready to record');draw();loadSelectedAudio();
}

function bindMenus(root){
  root.querySelectorAll('.meeting-menu').forEach(menu=>{
    menu.ontoggle=()=>{if(menu.open)root.querySelectorAll('.meeting-menu[open]').forEach(other=>{if(other!==menu)other.open=false;});};
    menu.onkeydown=e=>{if(e.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();e.stopPropagation();}};
    menu.onfocusout=()=>queueMicrotask(()=>{if(!menu.contains(document.activeElement))menu.open=false;});
  });
  root.onclick=e=>root.querySelectorAll('.meeting-menu[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;});
}
