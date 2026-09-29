import {LocalQuestionSpeech} from './local-question-speech.js?v=server-tts-1';
const esc = (v='') => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={proposed:'Needs approval',deferred:'Deferred',approved:'Waiting to speak',speaking:'Speaking',spoken:'Spoken',stale:'No longer current',rejected:'Dismissed',cancelled:'Cancelled',failed:'Failed'};
const active = p => ['proposed','deferred','approved','speaking','failed'].includes(p.status);
const isLocal=value=>!value.connector?.bot||['ended','fatal_error','data_deleted','not_created'].includes(value.connector.bot.state);

export function speechRequirement(meeting, localRecording, audioAvailable){
  if(isLocal(meeting)){
    if(!audioAvailable)return 'Local speech playback is unavailable in this browser.';
    if(!localRecording)return meeting.recording?'Play from the browser tab that is recording.':'Start recording in this browser to play.';
    return '';
  }
  const {bot,agent,audio_connected:audioConnected}=meeting.connector;
  if(bot.state!=='joined_recording'||bot.desired_state!=='joined'||(bot.deadline!=null&&Date.now()/1000>=bot.deadline))return 'Wait for Echooo to join and start recording before asking in the meeting.';
  if(!audioConnected||!agent)return 'Wait for Echooo to connect to meeting audio.';
  if(!agent.voice_available)return 'Voice replies need speech synthesis and live transcription.';
  if(!agent.voice_enabled)return 'Turn on Answer when called to ask in the meeting.';
  return '';
}

export function suggestionQueue(items, editingId=null){
  const priority=p=>['approved','speaking'].includes(p.status)?0:p.id===editingId?1:p.state?.task_priority==='blocking'||p.kind==='contradiction'?2:3;
  const pending=items.filter(p=>active(p)&&p.status!=='deferred').sort((a,b)=>priority(a)-priority(b)||(a.created_at||0)-(b.created_at||0));
  return {visible:pending.slice(0,3),more:pending.slice(3),saved:items.filter(p=>p.status==='deferred'),history:items.filter(p=>!active(p))};
}

export function unaskedTaskGaps(tasks=[],items=[]){
  return tasks.filter(t=>t.status==='open'&&t.evidence_current===true&&t.missing?.length&&!items.some(p=>
    (p.state?.task_ids?.includes(t.id)||t.related_proposal_ids?.includes(p.id))&&
    (p.status!=='stale'||!p.state?.task_reassess)));
}

export function suggestionQueueHTML(queue,row,tracking=''){
  return queue.visible.map(row).join('')+
    (queue.more.length?`<details data-suggestion-details="queue"><summary>More questions · ${queue.more.length}</summary>${queue.more.map(row).join('')}</details>`:'')+
    (queue.saved.length?`<details data-suggestion-details="saved"><summary>Saved for later · ${queue.saved.length}</summary>${queue.saved.map(row).join('')}</details>`:'')+
    tracking+
    (queue.history.length?`<details data-suggestion-details="history"><summary>Previous suggestions · ${queue.history.length}</summary>${queue.history.map(row).join('')}</details>`:'');
}

// Presentation only: keep every original evidence ID and never rewrite its words.
export function evidenceGroups(evidence, records=[]){
  const recordingOrder=new Map();
  for(const e of [...records,...evidence])if(!recordingOrder.has(e.recording_id))recordingOrder.set(e.recording_id,recordingOrder.size);
  const compare=(a,b)=>recordingOrder.get(a.recording_id)-recordingOrder.get(b.recording_id)||a.start_ms-b.start_ms||(a.end_ms??a.start_ms)-(b.end_ms??b.start_ms);
  const ordered=[...records].sort(compare),positions=new Map(ordered.map((r,i)=>[r.id,i])),byId=new Map(records.map(r=>[r.id,r]));
  const groups=[];
  for(const e of [...evidence].sort(compare)){
    const group=groups.at(-1),last=group?.items.at(-1),a=last&&byId.get(last.utterance_id),b=byId.get(e.utterance_id);
    const adjacent=a&&b&&positions.get(b.id)===positions.get(a.id)+1;
    const join=last&&e.recording_id&&e.recording_id===last.recording_id&&e.speaker===last.speaker
      &&e.start_ms-(last.end_ms??last.start_ms)<=6000&&e.start_ms-group.start_ms<=30000
      &&(!a||!b||adjacent);
    if(join){
      const continuous=adjacent&&a.content.trim().endsWith(last.quote.trim())&&b.content.trim().startsWith(e.quote.trim());
      const separator=continuous?(/[\u3400-\u9fff]$/.test(group.quote)&&/^[\u3400-\u9fff，。！？、；：]/.test(e.quote.trim())?'':' '):' … ';
      group.quote+=separator+e.quote.trim();group.items.push(e);group.end_ms=Math.max(group.end_ms,e.end_ms??e.start_ms);
    }else groups.push({quote:e.quote.trim(),speaker:e.speaker,start_ms:e.start_ms,end_ms:e.end_ms??e.start_ms,items:[e]});
  }
  return groups;
}
const stamp=ms=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;

export function trackedGapHTML(task,records=[]){
  const labels={owner:'Missing owner',timing:'Timing not agreed',scope:'Assignment unclear'};
  const evidence=evidenceGroups(task.evidence||[],records).map(g=>`<blockquote class="intervention-evidence"><p>${esc(g.quote)}</p><footer><span>${esc(g.speaker)} · ${stamp(g.start_ms)}</span><button class="meeting-text-button" data-task-source="${esc(task.id)}" data-task-sources="${esc(JSON.stringify(g.items.map(e=>e.utterance_id)))}">Open transcript</button></footer></blockquote>`).join('');
  return `<article class="intervention-row" data-tracked-task="${esc(task.id)}"><p class="intervention-question">${esc(task.task)}</p><p class="tracked-gap-fields">${(task.missing||[]).map(k=>esc(labels[k]||k)).join(' · ')}</p><details data-suggestion-details="task-${esc(task.id)}"><summary>Context</summary><p class="intervention-reason">${esc(task.reason)}</p>${evidence}</details></article>`;
}

export function trackedGapsHTML(tasks,records=[],ended=false){
  if(!tasks.length)return '';
  return `<section class="tracked-gaps"><h3>Tracked gaps</h3><p class="muted">${ended?'Unresolved details at the end of the meeting.':'Following the discussion before suggesting questions.'}</p>${tasks.slice(0,3).map(t=>trackedGapHTML(t,records)).join('')}${tasks.length>3?`<details data-suggestion-details="tracked-overflow"><summary>More tracked gaps · ${tasks.length-3}</summary>${tasks.slice(3).map(t=>trackedGapHTML(t,records)).join('')}</details>`:''}</section>`;
}

export function interventionHTML(p, reviews=[], ended=false, {local=false, speechBlocked=false, editing=null,records=[]}={}){
  const reviewable=['proposed','deferred','failed','cancelled'].includes(p.status)&&!ended;
  const edit=reviewable&&editing?.id===p.id;
  const evidence=evidenceGroups(p.evidence,records).map(g=>`<blockquote class="intervention-evidence"><p>${esc(g.quote)}</p><footer><span>${esc(g.speaker)} · ${stamp(g.start_ms)}${Math.floor(g.end_ms/1000)>Math.floor(g.start_ms/1000)?'–'+stamp(g.end_ms):''}</span><button class="meeting-text-button" data-proposal-source="${esc(g.items[0].utterance_id)}" data-proposal-sources="${esc(JSON.stringify(g.items.map(e=>e.utterance_id)))}">Open transcript</button></footer></blockquote>`).join('');
  const responses=(p.responses||[]).map(r=>`<blockquote class="intervention-evidence"><p>${esc(r.content)}</p><footer><span>${esc(r.speaker)} · ${stamp(r.start_ms)}${r.changed?' · Transcript changed':''}</span><button class="meeting-text-button" data-proposal-source="${esc(r.utterance_id)}" data-proposal-sources="${esc(JSON.stringify([r.utterance_id]))}">${r.changed?'View current transcript':'Open transcript'}</button></footer></blockquote>`).join('');
  const actionItems=(p.action_items||[]).map(f=>`<p class="intervention-linked-action">${esc(f.statement)} <span class="muted">· ${esc(f.status==='provisional'?'Awaiting review':f.status==='approved'||f.status==='edited'?'Confirmed':f.status)}</span> <button class="meeting-text-button" data-proposal-finding="${esc(f.id)}">View action</button></p>`).join('');
  const followup=responses||actionItems?`<details data-suggestion-details="answers-${esc(p.id)}"><summary>Participant replies${p.responses?.length?` · ${p.responses.length}`:''}</summary>${responses}${actionItems}</details>`:'';
  const question=edit?`<label for="question-${esc(p.id)}">Question</label><textarea id="question-${esc(p.id)}" data-question-draft required maxlength="1000" rows="3">${esc(editing.text)}</textarea>`:`<p class="intervention-question">${esc(p.question)}</p>`;
  const actions=reviewable?`<button class="btn primary" data-proposal-action="approve"${speechBlocked?' disabled aria-describedby="suggestion-speech-requirement"':''}>${local?'Play locally':'Ask in meeting'}</button><button class="btn" data-proposal-action="${edit?'cancel-edit':'edit'}">${edit?'Cancel edit':'Edit'}</button>${['proposed','deferred'].includes(p.status)?'<button class="btn" data-proposal-action="reject">Dismiss</button>':''}${p.status==='proposed'?`<details class="intervention-more" data-suggestion-details="more-${esc(p.id)}"><summary class="btn">More</summary><button class="btn" data-proposal-action="defer">Save for later</button></details>`:''}`:'';
  return `<article class="intervention-row" data-intervention="${esc(p.id)}"><div class="intervention-meta"><span class="intervention-kind">${p.kind==='contradiction'?'Conflicting information':'Missing detail'}</span>${p.status==='proposed'?'':`<span class="muted">${esc(labels[p.status]||p.status)}</span>`}</div>${question}<p class="intervention-reason">${esc(p.reason)}</p>${followup}<details data-suggestion-details="${esc(p.id)}"><summary>Supporting conversation</summary>${evidence}${reviews.length?`<details data-suggestion-details="history-${esc(p.id)}"><summary>Review history · ${reviews.length}</summary>${reviews.map(r=>`<p>${esc(r.action)} · ${esc(new Date(r.created_at*1000).toLocaleString())}</p>${r.before.question!==r.after.question?`<blockquote>${esc(r.before.question)} → ${esc(r.after.question)}</blockquote>`:''}`).join('')}</details>`:''}</details><div class="actions">${actions}${['approved','speaking'].includes(p.status)?'<button class="btn" data-proposal-action="cancel">Stop</button>':''}</div>${p.state?.delivery_error?`<p class="meeting-warning">${esc(p.state.delivery_error)}</p>`:''}</article>`;
}

export function mountInterventions(root,{api,base,refresh,showSource,openFinding=()=>{},getLocalRecording=()=>null,onLocalSpeech=async()=>{}}){
  let snapshot, busy=false,disposed=false,localError='',editing=null,expanded=false;
  root.innerHTML='<div class="meeting-section-heading"><h2><button class="meeting-suggestions-toggle" data-toggle-suggestions aria-expanded="false" aria-controls="meeting-suggestions-content"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>Suggested questions <span data-suggestion-count>0</span><span data-tracked-gap-count hidden></span></button></h2><button class="meeting-icon-button" data-check-suggestions aria-label="Check for suggested questions" title="Check for suggested questions"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 0 1 15.36-6.36L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.36 6.36L3 16M8 16H3v5"/></svg></button></div><p data-intervention-status role="status" aria-live="polite" hidden></p><p data-intervention-error role="alert"></p><p id="suggestion-speech-requirement" data-speech-requirement hidden></p><div id="meeting-suggestions-content" data-intervention-list hidden></div>';
  const status=root.querySelector('[data-intervention-status]'),error=root.querySelector('[data-intervention-error]'),requirement=root.querySelector('[data-speech-requirement]'),list=root.querySelector('[data-intervention-list]');
  const localSpeech=new LocalQuestionSpeech({api,base,
    changed:()=>{if(!disposed)refresh().catch(()=>{});},error:message=>{localError=message;if(!disposed)error.textContent=message;}});
  const speechRequest=localSpeech.request.bind(localSpeech);
  localSpeech.request=async(receipt,action)=>{
    const active=action==='start'||action==='heartbeat';
    try{
      if(active)await onLocalSpeech(true);
      let renew;
      if(action==='start')renew=setInterval(()=>{if(localSpeech.active?.id===receipt.id)onLocalSpeech(true).catch(()=>localSpeech.stop());else clearInterval(renew);},2000);
      let result;
      try{result=await speechRequest(receipt,action);}finally{clearInterval(renew);}
      if(active&&localSpeech.active?.id===receipt.id)await onLocalSpeech(true);
      if(!active)await onLocalSpeech(false).catch(()=>{});
      return result;
    }catch(error){await onLocalSpeech(false).catch(()=>{});throw error;}
  };
  const stopOnPageHide=()=>localSpeech.stop();
  window.addEventListener('pagehide',stopOnPageHide);
  function render(value){
    if(disposed)return;
    snapshot=value;
    localSpeech.sync(value);
    const progress=value.intervention_progress||{},items=value.interventions||[],ended=value.status==='ended';
    const tracked=unaskedTaskGaps(value.tracked_tasks||[],items);
    root.hidden=!progress.available&&!items.length&&!tracked.length;
    status.textContent=localSpeech.active?.audio?'Playing locally · recording continues':localSpeech.active?'Checking local playback…':busy?'Checking…':progress.phase==='checking'?'Checking recent discussion…':progress.phase==='waiting'?'Waiting for a complete, stable sentence…':progress.phase==='scheduled'?'Waiting for the next discussion check…':items.some(active)||tracked.length?'':progress.last_check?.outcome==='no_issue'?'Checked · no new questions.':progress.last_check?.outcome==='expired'?'Check took too long. Try again.':'No questions awaiting approval.';
    if(!busy)error.textContent=localError||progress.error||'';
    root.querySelector('[data-check-suggestions]').disabled=busy||ended||progress.phase==='checking'||!progress.available;
    if(editing&&!items.some(p=>p.id===editing.id&&p.revision===editing.revision&&['proposed','deferred','failed','cancelled'].includes(p.status))){editing=null;error.textContent='This suggestion changed. Review the latest question.';}
    const queue=suggestionQueue(items,editing?.id);
    const reason=speechRequirement(value,getLocalRecording(),localSpeech.available);
    requirement.textContent=reason;
    requirement.hidden=!expanded||!reason||ended||!items.some(p=>['proposed','deferred','failed','cancelled'].includes(p.status));
    root.querySelector('[data-toggle-suggestions]').setAttribute('aria-expanded',String(expanded));
    root.querySelector('[data-suggestion-count]').textContent=String(queue.visible.length+queue.more.length+queue.saved.length);
    const trackedCount=root.querySelector('[data-tracked-gap-count]');
    trackedCount.hidden=!tracked.length;
    trackedCount.textContent=tracked.length?`· Tracked gaps ${tracked.length}`:'';
    list.hidden=!expanded;
    status.hidden=!expanded&&!busy&&!localSpeech.active&&!['checking','waiting','scheduled'].includes(progress.phase)&&progress.last_check?.outcome!=='expired';
    const row=p=>interventionHTML(p,(value.intervention_reviews||[]).filter(r=>r.intervention_id===p.id),ended,{local:isLocal(value),speechBlocked:!!reason,editing,records:value.utterances||[]});
    const html=suggestionQueueHTML(queue,row,trackedGapsHTML(tracked,value.utterances||[],ended));
    if(list._html!==html){
      const opened=new Set([...list.querySelectorAll('details[open]')].map(d=>d.dataset.suggestionDetails));
      const focused=list.querySelector('[data-question-draft]'),restore=focused&&focused===document.activeElement,selection=restore?[focused.selectionStart,focused.selectionEnd]:null;
      list.innerHTML=html;list._html=html;
      list.querySelectorAll('details').forEach(d=>d.open=opened.has(d.dataset.suggestionDetails));
      const replacement=list.querySelector('[data-question-draft]');
      if(restore&&replacement){replacement.focus();replacement.setSelectionRange(...selection);}
    }
    root.setAttribute('aria-busy',String(busy));
    list.querySelectorAll('[data-proposal-action]').forEach(b=>b.disabled=(busy&&b.dataset.proposalAction!=='cancel')||(b.dataset.proposalAction==='approve'&&!!reason));
    const draft=list.querySelector('[data-question-draft]');if(draft)draft.disabled=busy;
  }
  root.oninput=event=>{if(event.target.matches('[data-question-draft]')&&editing)editing.text=event.target.value;};
  root.onclick=async event=>{
    const button=event.target.closest('button');if(!button||button.disabled||!snapshot)return;
    if(button.hasAttribute('data-toggle-suggestions')){expanded=!expanded;render(snapshot);return;}
    const p=snapshot.interventions?.find(p=>p.id===button.closest('[data-intervention]')?.dataset.intervention);
    if(busy){
      if(button.dataset.proposalAction==='cancel'&&p){
        try{
          if(localSpeech.active?.id===p.id)localSpeech.stop();
          else await api(`${base}/interventions/${p.id}/review`,'POST',{action:'cancel',revision:p.revision});
          await refresh();
        }catch(e){error.textContent=e.message;}
      }
      return;
    }
    if(button.dataset.taskSource){
      const task=snapshot.tracked_tasks?.find(t=>t.id===button.dataset.taskSource);
      if(task)showSource({text:task.task,evidence_ids:JSON.parse(button.dataset.taskSources)});
      return;
    }
    if(button.dataset.proposalSource){
      const reply=p.responses?.find(r=>r.utterance_id===button.dataset.proposalSource);
      showSource({text:reply?.content||p.question,evidence_ids:JSON.parse(button.dataset.proposalSources)});
      return;
    }
    if(button.dataset.proposalFinding){openFinding(button.dataset.proposalFinding);return;}
    const action=button.dataset.proposalAction;
    if(action==='edit'||action==='cancel-edit'){
      editing=action==='edit'?{id:p.id,revision:p.revision,text:p.question}:null;
      render(snapshot);
      if(editing)list.querySelector('[data-question-draft]')?.focus();
      return;
    }
    const review=async(question,local=false)=>{
      if(disposed)throw new Error('This meeting page has closed.');
      localError='';
      const recordingId=local?getLocalRecording():null;
      if(local&&(!recordingId||!localSpeech.available))throw new Error('Start recording in this browser and allow speech playback first.');
      if(local&&localSpeech.active)throw new Error('Finish or cancel the current local question first.');
      if(action==='cancel'&&localSpeech.active?.id===p.id){localSpeech.stop();await refresh();return;}
      const result=await api(`${base}/interventions/${p.id}/review`,'POST',{action,revision:p.revision,...(question===undefined?{}:{question}),...(local?{delivery:'browser',recording_id:recordingId}:{})});
      if(result.browser_speech){
        if(disposed||!getLocalRecording()){localSpeech.request(result.browser_speech,'cancelled').catch(()=>{});return;}
        await localSpeech.play(result.browser_speech);
      }
      await refresh();
    };
    const question=editing&&editing.id===p?.id?editing.text.trim():p?.question;
    if(action==='approve'&&!question){error.textContent='Enter a question.';list.querySelector('[data-question-draft]')?.focus();return;}
    const local=isLocal(snapshot);
    busy=true;render(snapshot);error.textContent='';
    try{if(action)await review(action==='approve'?question:undefined,action==='approve'&&local);else await api(`${base}/interventions/check`,'POST');if(action)editing=null;await refresh();}
    catch(e){localError=e.message;error.textContent=localError;}
    finally{busy=false;const message=error.textContent;render(snapshot);error.textContent=message;}
  };
  return {render,stopLocalSpeech:()=>localSpeech.stop(),dispose(){disposed=true;window.removeEventListener('pagehide',stopOnPageHide);localSpeech.stop();}};
}
