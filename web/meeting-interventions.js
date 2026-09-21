import {LocalQuestionSpeech} from './local-question-speech.js?v=2';
const esc = (v='') => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={proposed:'Needs approval',deferred:'Deferred',approved:'Waiting to speak',speaking:'Speaking',spoken:'Spoken',stale:'No longer current',rejected:'Dismissed',cancelled:'Cancelled',failed:'Failed'};
const active = p => ['proposed','deferred','approved','speaking'].includes(p.status);

export function interventionHTML(p, reviews=[], ended=false){
  const reviewable=['proposed','deferred','failed','cancelled'].includes(p.status)&&!ended;
  return `<article class="intervention-row" data-intervention="${esc(p.id)}"><p class="muted">${esc(labels[p.status]||p.status)} · ${p.kind==='contradiction'?'Conflicting information':'Missing detail'}</p><p class="intervention-question">${esc(p.question)}</p><p>${esc(p.reason)}</p><details data-suggestion-details="${esc(p.id)}"><summary>Supporting conversation</summary>${p.evidence.map(e=>`<blockquote><p>${esc(e.quote)}</p><footer>${esc(e.speaker)} · ${Math.floor(e.start_ms/60000)}:${String(Math.floor(e.start_ms/1000)%60).padStart(2,'0')}</footer><button class="meeting-text-button" data-proposal-source="${esc(e.utterance_id)}">Open transcript</button></blockquote>`).join('')}</details>${reviews.length?`<details data-suggestion-details="history-${esc(p.id)}"><summary>Review history · ${reviews.length}</summary>${reviews.map(r=>`<p>${esc(r.action)} · ${esc(new Date(r.created_at*1000).toLocaleString())}</p>${r.before.question!==r.after.question?`<blockquote>${esc(r.before.question)} → ${esc(r.after.question)}</blockquote>`:''}`).join('')}</details>`:''}<div class="actions">${reviewable?`<button class="btn primary" data-proposal-action="approve">Review & ask</button>${p.status==='proposed'?'<button class="btn" data-proposal-action="defer">Later</button>':''}${['proposed','deferred'].includes(p.status)?'<button class="meeting-text-button" data-proposal-action="reject">Dismiss</button>':''}`:''}${['approved','speaking'].includes(p.status)?'<button class="btn" data-proposal-action="cancel">Cancel speech</button>':''}</div>${p.state?.delivery_error?`<p class="meeting-warning">${esc(p.state.delivery_error)}</p>`:''}</article>`;
}

export function mountInterventions(root,{api,base,refresh,openDialog,showSource,getLocalRecording=()=>null}){
  let snapshot, busy=false,disposed=false,localError='';
  root.innerHTML='<div class="meeting-section-heading"><h2>Suggested questions</h2><button class="btn" data-check-suggestions>Check again</button></div><p class="muted">Private to you. Approval allows Echooo to ask the exact question aloud.</p><p data-intervention-status role="status" aria-live="polite"></p><p data-intervention-error role="alert"></p><div data-intervention-list></div>';
  const status=root.querySelector('[data-intervention-status]'),error=root.querySelector('[data-intervention-error]'),list=root.querySelector('[data-intervention-list]');
  const localSpeech=new LocalQuestionSpeech({api,base,
    changed:()=>{if(!disposed)refresh().catch(()=>{});},error:message=>{localError=message;if(!disposed)error.textContent=message;}});
  const stopOnPageHide=()=>localSpeech.stop();
  window.addEventListener('pagehide',stopOnPageHide);
  function render(value){
    if(disposed)return;
    snapshot=value;
    localSpeech.sync(value);
    const progress=value.intervention_progress||{},items=value.interventions||[],ended=value.status==='ended';
    root.hidden=!progress.available&&!items.length;
    status.textContent=localSpeech.active?.utterance?'Playing locally · recording continues':localSpeech.active?'Checking local playback…':busy?'Checking…':progress.phase==='checking'?'Checking recent discussion…':items.some(active)?'':'No questions awaiting approval.';
    if(!busy)error.textContent=localError||progress.error||'';
    root.querySelector('[data-check-suggestions]').disabled=busy||ended||progress.phase==='checking'||!progress.available;
    const rows=items.filter(active),history=items.filter(p=>!active(p));
    const row=p=>interventionHTML(p,(value.intervention_reviews||[]).filter(r=>r.intervention_id===p.id),ended);
    const html=rows.map(row).join('')+(history.length?`<details data-suggestion-details="history"><summary>Previous suggestions · ${history.length}</summary>${history.map(row).join('')}</details>`:'');
    if(list._html!==html){
      const opened=new Set([...list.querySelectorAll('details[open]')].map(d=>d.dataset.suggestionDetails));
      list.innerHTML=html;list._html=html;
      list.querySelectorAll('details').forEach(d=>d.open=opened.has(d.dataset.suggestionDetails));
    }
    root.setAttribute('aria-busy',String(busy));
    list.querySelectorAll('[data-proposal-action]').forEach(b=>b.disabled=busy);
  }
  root.onclick=async event=>{
    const button=event.target.closest('button');if(!button||!snapshot||busy)return;
    const p=snapshot.interventions?.find(p=>p.id===button.closest('[data-intervention]')?.dataset.intervention);
    if(button.dataset.proposalSource){showSource({text:p.question,evidence_ids:[button.dataset.proposalSource]});return;}
    const action=button.dataset.proposalAction;
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
    if(action==='approve'){
      const bot=snapshot.connector?.bot;
      const local=!bot||['ended','fatal_error','data_deleted','not_created'].includes(bot.state);
      openDialog('Review spoken question',`<label for="intervention-wording">Question</label><textarea id="intervention-wording" name="question" required maxlength="1000" rows="4">${esc(p.question)}</textarea><p class="muted">${local?'Plays through this device while recording continues. Use headphones if you hear echo.':'Echooo will recheck the discussion before speaking.'}</p>`,async fd=>{try{await review(fd.get('question'),local);}catch(e){await refresh();throw e;}},local?'Approve & play locally':'Approve & ask');
      return;
    }
    busy=true;render(snapshot);error.textContent='';
    try{if(action)await review();else await api(`${base}/interventions/check`,'POST');await refresh();}
    catch(e){error.textContent=e.message;}
    finally{busy=false;const message=error.textContent;render(snapshot);error.textContent=message;}
  };
  return {render,stopLocalSpeech:()=>localSpeech.stop(),dispose(){disposed=true;window.removeEventListener('pagehide',stopOnPageHide);localSpeech.stop();}};
}
