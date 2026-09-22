import {speakerName} from './meeting-transcript.js';
import {enhanceSelects} from './select.js';
const esc = (value='') => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
const labels={decision:'Decision',action_item:'Action item',unresolved_question:'Open question',contradiction:'Contradiction',risk:'Risk'};
// Group nearby source fragments for reading; keep every original quote and anchor.
export function groupEvidence(items,combineSpeakers=false) {
  const groups=[];
  for(const e of items){
    const last=groups.at(-1);
    if(last && e.recording_id && last.recording_id===e.recording_id && (combineSpeakers||last.speaker===e.speaker||speakerName(last.speaker)==='Unidentified speaker'||speakerName(e.speaker)==='Unidentified speaker') &&
      e.start_ms>=last.start_ms && e.start_ms-last.end_ms<=2000 && e.end_ms-last.start_ms<=30000){
      last.items.push(e);last.end_ms=Math.max(last.end_ms,e.end_ms);
    }else groups.push({...e,items:[e]});
  }
  return groups;
}
export function evidenceTimeRange(start,end){
  if(end<=start)return time(start);
  const precise=ms=>`${time(ms)}.${String(Math.floor(ms%1000)).padStart(3,'0')}`;
  return Math.floor(start/1000)===Math.floor(end/1000)?`${precise(start)}–${precise(end)}`:`${time(start)}–${time(end)}`;
}
const evidenceHTML=(items,fid,aliases={})=>{
  const recordings=[...new Set(items.map(e=>e.recording_id).filter(Boolean))];
  const seen=new Set();
  const unique=items.filter(e=>{const key=JSON.stringify([e.recording_id,e.utterance_id,e.quote]);if(seen.has(key))return false;seen.add(key);return true;});
  const jump=(e,ids,label='Open transcript')=>fid?`<button type="button" class="meeting-text-button" data-finding-source="${esc(fid)}" data-source-utterance="${esc(e.utterance_id)}" data-source-utterances="${esc(JSON.stringify(ids))}">${label}</button>`:'';
  return groupEvidence(unique.map(e=>({...e,speaker:aliases[e.utterance_id]||e.speaker}))).map(g=>{
    const labels=[...new Set(g.items.map(e=>speakerName(e.speaker)))];
    const displaySpeaker=labels.includes('Unidentified speaker')?'Unidentified speaker':labels.join(', ');
    const quotes=[];
    for(const e of g.items)if(quotes.at(-1)!==e.quote)quotes.push(e.quote);
    return `<blockquote><p>${quotes.map(esc).join(' ')}</p><footer><span class="evidence-anchor"><span>${recordings.length>1?`${esc(g.recording_label||`Recording · ${g.recording_id?.slice(0,4)||'notes'}`)} · `:''}${esc(displaySpeaker)} · ${g.recording_id?evidenceTimeRange(g.start_ms,g.end_ms):'Text note'}</span>${jump(g.items[0],g.items.map(e=>e.utterance_id))}</span></footer></blockquote>`;
  }).join('');
};
const answerHTML=(f,confirmed=false)=>f.details?.resolved?`<div class="finding-answer"><span>${f.status==='provisional'?'Suggested answer':'Answer'}</span><p>${esc(f.details.answer||(confirmed?'No answer saved.':'No answer summary yet. Review the source and add an answer, or keep this question open.'))}</p></div>`:'';
const metadataHTML=f=>f.kind==='action_item'?`<p class="muted">Owner: ${esc(f.details?.owner||'Unspecified')} · Deadline: ${esc(f.details?.deadline_text||f.details?.deadline||'Unspecified')}</p>`:'';

export function findingSpeakers(f){
  const groups=[];
  for(const e of f.evidence||[]){
    const name=f.details?.speaker_names?.[e.utterance_id]||speakerName(e.speaker);
    const group=groups.find(g=>g.original===speakerName(e.speaker)&&g.name===name);
    if(group)group.ids.push(e.utterance_id);
    else groups.push({identity:e.speaker,name,original:speakerName(e.speaker),recording:e.recording_id,ids:[e.utterance_id]});
  }
  return groups;
}
export function findingAttribution(f){
  const speakers=findingSpeakers(f);
  const prefix=speakers.flatMap(s=>[s.original,s.name]).sort((a,b)=>b.length-a.length).find(name=>
    f.statement.startsWith(name+' ')||f.statement.startsWith(name+':'));
  const explicitNames=[...new Set(Object.values(f.details?.speaker_names||{}))];
  if(!prefix&&explicitNames.length===1&&speakers.every(s=>s.name===explicitNames[0]))return {name:explicitNames[0],statement:f.statement};
  const matches=prefix?speakers.filter(s=>s.original===prefix||s.name===prefix):[];
  const names=[...new Set(matches.map(s=>s.name))];
  // Evidence contributors are not necessarily the person making this finding.
  return names.length===1?{name:names[0],statement:f.statement.slice(prefix.length).replace(/^:\s*|^\s+/, '')||f.statement}:
    {name:null,statement:f.statement};
}
export function findingContentHTML(f, className='finding-statement'){
  const {name,statement}=findingAttribution(f);
  return name?`<div class="finding-attributed"><p class="finding-speakers" aria-label="Attributed speaker"><span>${esc(name)}</span></p><p class="${className}">${esc(statement)}</p></div>`:`<p class="${className}">${esc(statement)}</p>`;
}

export function findingHistoryHTML(entries, fid) {
  if(!entries.length)return '';
  const actions={approve:'Approved',edit:'Edited & approved',reject:'Rejected',keep_open:'Kept open',extraction_revision:'Updated from transcript'};
  const speakerSet=f=>[...new Set(findingSpeakers(f).map(s=>s.name))].sort().join(', ');
  const changes=r=>{
    const fields=[['speakers','Source speakers',v=>v],['kind','Type',v=>labels[v]||v],['statement','Summary',v=>v],['owner','Owner',v=>v],['deadline_text','Deadline',v=>v],['answer','Answer',v=>v],['resolved','Resolution',v=>v?'Resolved':'Open']];
    const value=(f,key)=>key==='speakers'?speakerSet(f):key==='resolved'?!!f.details?.resolved:
      key==='deadline_text'?(f.details?.deadline_text||f.details?.deadline):key==='owner'||key==='answer'?f.details?.[key]:f[key];
    return fields.flatMap(([key,label,format])=>{
      if(key==='speakers'&&(r.action!=='edit'||JSON.stringify(r.before.details?.speaker_names||{})===JSON.stringify(r.after.details?.speaker_names||{})))return [];
      const before=value(r.before,key),after=value(r.after,key);
      return (before??null)===(after??null)?[]:[`<div class="finding-change"><dt>${label}</dt><dd><span class="finding-change-before">${esc(format(before)||'Not set')}</span><span>${esc(format(after)||'Not set')}</span></dd></div>`];
    }).join('');
  };
  const visible=entries.filter(r=>['approve','edit','reject','keep_open'].includes(r.action)).map(r=>({r,change:changes(r)}));
  if(!visible.length)return '';
  return `<details class="finding-details finding-history" data-finding-details="history-${esc(fid)}"><summary>History <span class="finding-detail-count">${visible.length}</span></summary><ol class="finding-timeline">${visible.reverse().map(({r,change})=>`<li><div class="finding-history-heading"><strong>${esc(actions[r.action]||r.action.replaceAll('_',' '))}</strong><time datetime="${esc(new Date(r.created_at*1000).toISOString())}">${esc(new Date(r.created_at*1000).toLocaleString())}</time></div>${change?`<dl>${change}</dl>`:''}</li>`).join('')}</ol></details>`;
}

export const needsReview=f=>!f.superseded&&(f.status==='provisional'||(!f.evidence_current&&['approved','edited'].includes(f.status)));

export function decisionListHTML(findings, busy=false, reviews=[]) {
  if (!findings.length) return '';
  const row=f=>{
    const stale=!f.evidence_current, reviewable=needsReview(f),resolved=f.kind==='unresolved_question'&&f.details?.resolved;
    const status=f.superseded?'Superseded':f.status==='rejected'?'Rejected':reviewable?(stale?'Source changed':''):resolved?'Resolved':f.status==='edited'?'Edited & approved':'Approved';
    const disabled=busy||stale&&!f.can_refresh_evidence;
    return `<article class="finding-row" data-review-state="${reviewable?'pending':f.status}"><div class="finding-main"><div class="finding-meta"><span>${esc(resolved&&reviewable?'Answer found':labels[f.kind]||'Decision')}</span>${status?`<span class="finding-status">${esc(status)}</span>`:''}${f.replacement_pending?'<span>Update pending</span>':''}</div>${findingContentHTML(f)}${answerHTML(f)}${metadataHTML(f)}</div>${reviewable?`<div class="actions finding-actions"><button class="btn primary" ${stale||(resolved&&!f.details.answer)?'data-edit-finding':'data-approve-finding'}="${esc(f.id)}" ${disabled?'disabled':''}>${stale?'Review changes':resolved?(f.details.answer?'Confirm answer':'Review answer'):'Approve'}</button>${!stale&&(!resolved||f.details.answer)?`<button class="meeting-text-button" data-edit-finding="${esc(f.id)}" ${busy?'disabled':''}>Edit</button>`:''}<button class="meeting-text-button" ${resolved&&(!stale||f.can_refresh_evidence)?'data-keep-open-finding':'data-reject-finding'}="${esc(f.id)}" ${busy?'disabled':''}>${resolved&&(!stale||f.can_refresh_evidence)?'Keep open':'Reject'}</button></div>`:''}<div class="finding-disclosures"><details class="finding-details" data-finding-details="${esc(f.id)}"><summary>Source</summary>${resolved&&reviewable?'<p class="muted">Confirming saves this question and answer under Answered questions in Summary.</p>':''}${stale?'<p class="muted">Previous transcript</p>':''}${stale&&!f.can_refresh_evidence?'<p class="muted">Source deleted. This finding can only be rejected.</p>':''}${f.details?.supersedes?'<p class="muted">Approval replaces the earlier finding.</p>':''}${evidenceHTML(f.evidence,f.id,f.details?.speaker_names)}</details>${findingHistoryHTML(reviews.filter(r=>r.finding_id===f.id),f.id)}</div></article>`;
  };
  const pending=findings.filter(needsReview),reviewed=findings.filter(f=>!needsReview(f));
  return pending.map(row).join('')+(reviewed.length?`<details class="finding-reviewed" data-finding-details="reviewed"><summary>Reviewed · ${reviewed.length}</summary>${reviewed.map(row).join('')}</details>`:'');
}

export const findingsForRecording=(items,recordingId)=>recordingId===undefined?items:items.filter(f=>f.evidence.some(e=>(e.recording_id||'notes')===recordingId));

export function nextReviewRecording(items,recordingId){
  const pending=items.filter(needsReview);
  const next=pending.flatMap(f=>f.evidence.map(e=>e.recording_id||'notes')).find(id=>id!==recordingId);
  return next?{id:next,count:findingsForRecording(pending,next).length}:null;
}

export function approvedRecordHTML(record, recordingId) {
  const groups=[['Decisions',record.decisions||[]],['Action items',record.action_items||[]],['Open questions',record.unresolved_questions||[]],['Contradictions',record.contradictions||[]],['Risks',record.risks||[]],['Answered questions',record.answered_questions||[]]].map(([label,items])=>[label,findingsForRecording(items,recordingId)]);
  if(!groups.some(([,items])=>items.length))return recordingId===undefined?'<p class="muted">No approved findings yet. Approve items in Review.</p>':'';
  return `<h2>Confirmed results</h2>${groups.filter(([,items])=>items.length).map(([title,items])=>`<section class="record-group">${title==='Answered questions'?`<details class="answered-questions" data-record-evidence="answered-questions"><summary>Answered questions · ${items.length}</summary>`:`<h3>${title}</h3>`}<ol>${items.map(f=>`<li data-confirmed-finding="${esc(f.id)}" tabindex="-1">${findingContentHTML(f,'record-statement')}${answerHTML(f,true)}${metadataHTML(f)}<details class="finding-details" data-record-evidence="${esc(f.id)}"><summary>Source</summary>${f.status==='edited'?'<p class="record-edit-label">Edited &amp; approved</p>':''}${evidenceHTML(f.evidence,f.id,f.details?.speaker_names)}</details></li>`).join('')}</ol>${title==='Answered questions'?'</details>':''}</section>`).join('')}`;
}

// Keep the existing attribution identity in storage while editing only the content.
export function editedFindingStatement(f, content){
  const attribution=findingAttribution(f);
  return attribution.name ? f.statement.slice(0,f.statement.length-attribution.statement.length)+content : content;
}

export function findingEditorHTML(f){
  const field=(name,label,value)=>`<label>${label}<input name="${name}" maxlength="200" value="${esc(value||'')}"></label>`;
  return `<div class="finding-type-field"><label for="finding-kind">Type</label><select id="finding-kind" name="kind">${Object.entries(labels).map(([kind,label])=>`<option value="${kind}" ${f.kind===kind?'selected':''}>${label}</option>`).join('')}</select></div><fieldset class="finding-speaker-fields"><legend>Rename speakers</legend><div class="finding-speaker-grid">${findingSpeakers(f).map((speaker,i)=>`<label>${esc(speaker.original)}${findingSpeakers(f).filter(s=>s.original===speaker.original).length>1?` · Source ${i+1} · ${time(f.evidence.find(e=>e.utterance_id===speaker.ids[0])?.start_ms||0)}`:''}<input aria-label="Name for ${esc(speaker.original)}${findingSpeakers(f).filter(s=>s.original===speaker.original).length>1?` source ${i+1}`:''}" name="speaker_${i}" maxlength="80" required value="${esc(speaker.name)}"></label>`).join('')}</div><p class="muted">One name per label, across this finding’s sources.</p></fieldset>${!f.evidence_current?`<h4>Current transcript</h4>${evidenceHTML(f.current_evidence||[],f.id,f.details?.speaker_names)}`:''}<label>${f.evidence_current?'Finding summary':'Update summary to match the current transcript'}<textarea name="statement" required maxlength="1000" rows="3">${esc(findingAttribution(f).statement)}</textarea></label>${f.details?.resolved?`<label data-answer-field>Answer<textarea name="answer" maxlength="2000" rows="3" required>${esc(f.details.answer||'')}</textarea></label>`:''}<div class="finding-action-fields" data-action-fields ${f.kind==='action_item'?'':'hidden'}>${field('owner','Owner (optional)',f.details?.owner)+field('deadline_text','Deadline (optional)',f.details?.deadline_text||f.details?.deadline)}</div>${f.evidence_current?`<h4>Source</h4>${evidenceHTML(f.evidence,f.id,f.details?.speaker_names)}`:`<details><summary>Previous transcript</summary>${evidenceHTML(f.evidence)}</details>`}`;
}

export function mountFindings(root, {api, base, refresh, showSource, recordRoot=null, onRecord=()=>{}, onPending=()=>{}, getRecordScope=()=>undefined, onNextRecording=()=>{}}) {
  let snapshot=null,busy=false,disposed=false,editing=null,noticeTimer=null,noticeFinding=null,lastScope=undefined,processing=false;
  root.innerHTML=`<div class="meeting-section-heading"><h2 id="finding-title">Findings for review</h2><button type="button" class="btn finding-results-link" data-view-results hidden>View results</button><details class="meeting-menu"><summary aria-label="Review options">…</summary><div class="meeting-menu-items"><button data-extract-decisions>Check for findings</button></div></details></div><p class="muted" data-finding-count></p><p data-finding-status role="status" aria-live="polite"></p><p data-finding-error role="alert"></p><div class="finding-notice" data-finding-notice hidden><span role="status" data-notice-text></span><button class="meeting-text-button" data-view-summary hidden>View in Summary</button></div><section class="finding-complete" data-review-complete hidden aria-labelledby="review-complete-title"><h3 id="review-complete-title" role="status">Review complete</h3><p class="muted" data-no-results hidden>No results confirmed</p><button type="button" class="btn primary" data-view-results hidden>View confirmed results <span aria-hidden="true">→</span></button></section><button type="button" class="btn finding-next-recording" data-next-recording hidden></button><div data-finding-list></div><section data-approved-record hidden aria-label="Approved meeting record"></section><dialog class="finding-editor" aria-labelledby="finding-editor-title"><form><h3 id="finding-editor-title">Review finding</h3><div data-editor-fields></div><p class="muted finding-resolution-help" data-resolution-help hidden>Confirming saves this question and answer under Answered questions in Summary.</p><p data-editor-error role="alert"></p><div class="actions finding-editor-actions"><button type="button" class="btn" data-cancel-edit>Cancel</button><button type="button" class="btn" data-editor-keep-open hidden>Keep open</button><button type="submit" class="btn primary">Save and approve</button></div></form></dialog>`;
  const record=recordRoot||root.querySelector('[data-approved-record]');
  if(recordRoot)root.querySelector('[data-approved-record]').remove();
  const status=root.querySelector('[data-finding-status]'),error=root.querySelector('[data-finding-error]'),dialog=root.querySelector('dialog'),form=dialog.querySelector('form');
  function render(value){
    if(disposed)return;
    const recordingNames=new Map((value.recordings||snapshot?.recordings||[]).map((r,i)=>[r.id,`Recording ${i+1}`]));
    const labelFinding=f=>({...f,evidence:f.evidence.map(e=>({...e,recording_label:recordingNames.get(e.recording_id)}))});
    value={...value,findings:(value.findings||[]).map(labelFinding),approved_record:Object.fromEntries(Object.entries(value.approved_record||{}).map(([key,entries])=>[key,Array.isArray(entries)?entries.map(labelFinding):entries]))};
    snapshot=value;
    const scope=getRecordScope(),allItems=value.findings||[],items=findingsForRecording(allItems,scope);
    const pending=items.filter(needsReview).length;
    onPending(pending);
    root.querySelector('[data-finding-count]').textContent=pending?`${pending} awaiting review`:'';
    if(scope!==lastScope){root.querySelector('[data-finding-notice]').hidden=true;noticeFinding=null;lastScope=scope;}
    const globalProgress=value.finding_progress||{phase:'idle'};
    const scopedPending=scope!==undefined&&globalProgress.pending_by_recording?globalProgress.pending_by_recording[scope]||0:globalProgress.pending;
    const progress={...globalProgress,pending:scopedPending};
    if(globalProgress.pending_by_recording&&scope!==undefined&&!scopedPending)Object.assign(progress,{phase:'idle',error:''});
    processing=['processing','queued','retrying'].includes(globalProgress.phase)||
      (globalProgress.updating_recordings||[]).some(id=>scope===undefined||id===scope||items.some(f=>f.evidence.some(e=>e.recording_id===id)))||
      (value.recordings||[]).some(r=>(scope===undefined||r.id===scope||items.some(f=>f.evidence.some(e=>e.recording_id===r.id)))&&['connecting','live','reconnecting','verifying'].includes(r.transcription?.phase));
    root.querySelector('[data-finding-list]').hidden=processing;
    root.setAttribute('aria-busy',String(processing));
    if(dialog.open){
      const current=editing&&items.find(f=>f.id===editing.id);
      const changed=editing&&(!current||current.revision!==editing.revision||current.evidence_token!==editing.evidence_token);
      for(const control of form.querySelectorAll('input,textarea,select,button'))if(!control.hasAttribute('data-cancel-edit'))control.disabled=processing||changed;
      root.querySelector('[data-editor-error]').textContent=processing?'Processing transcript and findings. Editing is paused.':changed?'This finding has changed. Close and reopen it to review the latest version.':'';
    }
    if(processing){
      status.textContent='Processing transcript and findings… Review will be available when processing finishes.';
      error.textContent='';
      for(const selector of ['[data-review-complete]','[data-next-recording]','[data-finding-notice]'])root.querySelector(selector).hidden=true;
      for(const button of root.querySelectorAll('[data-view-results],[data-extract-decisions]'))button.disabled=true;
      return;
    }
    status.textContent=busy?'Processing…':['processing','queued'].includes(progress.phase)?'Extracting findings…':progress.phase==='retrying'?'Retrying extraction…':progress.phase==='unavailable'?progress.error:progress.pending?`${progress.pending} transcript passage(s) awaiting extraction.`:'';
    if(!busy)error.textContent=progress.phase==='error'?progress.error:'';
    const list=root.querySelector('[data-finding-list]'),html=decisionListHTML(items,busy,value.finding_reviews||[]);
    if(list._html!==html){
      const opened=new Set([...list.querySelectorAll('details[open]')].map(n=>n.dataset.findingDetails));
      list.innerHTML=html;list._html=html;
      for(const node of list.querySelectorAll('[data-finding-details]'))node.open=opened.has(node.dataset.findingDetails);
    }
    const resultCount=Object.values(value.approved_record||{}).reduce((count,v)=>count+(Array.isArray(v)?findingsForRecording(v,scope).length:0),0);
    const complete=items.length>0&&!pending&&!busy&&!progress.pending&&
      !['processing','queued','retrying','error','unavailable'].includes(progress.phase);
    for(const button of root.querySelectorAll('[data-view-results]')){
      button.hidden=!resultCount;
      button.disabled=busy;
    }
    root.querySelector('.finding-results-link').innerHTML=`View results (${resultCount}) <span aria-hidden="true">→</span>`;
    root.querySelector('[data-review-complete]').hidden=!complete;
    root.querySelector('[data-no-results]').hidden=!!resultCount;
    const next=scope===undefined?null:nextReviewRecording(allItems,scope);
    const nextButton=root.querySelector('[data-next-recording]');
    nextButton.hidden=pending>0||busy||!next;
    nextButton.textContent=next?`Review next recording (${next.count}) →`:'';
    nextButton.dataset.nextId=next?.id||'';
    root.querySelector('[data-extract-decisions]').textContent=progress.phase==='error'?'Retry Extraction':'Check for findings';
    root.querySelector('[data-extract-decisions]').disabled=busy||['processing','queued','retrying','unavailable'].includes(progress.phase);
    {
      const html=approvedRecordHTML(value.approved_record||{},getRecordScope());
      record.hidden=!html;
      if(record._html!==html){
        const opened=new Set([...record.querySelectorAll('details[open]')].map(n=>n.dataset.recordEvidence));
        record.innerHTML=html;record._html=html;
        for(const node of record.querySelectorAll('[data-record-evidence]'))node.open=opened.has(node.dataset.recordEvidence);
      }
    }
  }
  function openEditor(f){
    editing=structuredClone(f);
    root.querySelector('[data-editor-fields]').innerHTML=findingEditorHTML(f);
    const syncKind=()=>{
      root.querySelector('[data-action-fields]').hidden=form.elements.kind.value!=='action_item';
      const resolving=f.details?.resolved&&form.elements.kind.value==='unresolved_question';
      form.querySelector('[type="submit"]').textContent=resolving?'Confirm answer':'Save and approve';
      root.querySelector('[data-resolution-help]').hidden=!resolving;
      form.querySelector('[data-editor-keep-open]').hidden=!resolving;
      const answerField=form.querySelector('[data-answer-field]');
      if(answerField){answerField.hidden=!resolving;form.elements.answer.required=resolving;}
    };
    enhanceSelects(root.querySelector('[data-editor-fields]'));
    form.elements.kind.onchange=syncKind;syncKind();
    root.querySelector('[data-editor-error]').textContent='';dialog.showModal();form.elements.statement.focus();
  }
  async function submitReview(f,body){
    clearTimeout(noticeTimer);root.querySelector('[data-finding-notice]').hidden=true;
    busy=true;render(snapshot);
    try{
      const reviewed=await api(`${base}/findings/${f.id}/review`,'POST',body);
      render(reviewed);
      dialog.close();await refresh();
      if(!disposed){
        busy=false;render(snapshot);
        noticeFinding=Object.values(snapshot.approved_record||{}).filter(Array.isArray).flat().find(item=>item.id===f.id);
        const notice=root.querySelector('[data-finding-notice]');
        root.querySelector('[data-notice-text]').textContent=body.action==='keep_open'?'Question kept open':body.action==='reject'?'Rejected':f.details?.resolved&&(body.kind||f.kind)==='unresolved_question'?'Answer confirmed':'Approved';
        root.querySelector('[data-view-summary]').hidden=body.action==='reject'||!noticeFinding;
        notice.hidden=false;
        noticeTimer=setTimeout(()=>{if(!notice.contains(document.activeElement))notice.hidden=true;},12000);
      }
    }catch(e){if(!disposed){busy=false;render(snapshot);(dialog.open?root.querySelector('[data-editor-error]'):error).textContent=e.message||'Could not save this review.';}}
  }
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||processing||!editing)return;
    const data=new FormData(form),body={action:'edit',revision:editing.revision,kind:data.get('kind'),statement:editedFindingStatement(editing,data.get('statement')),evidence_token:editing.evidence_token};
    if(editing.details?.resolved&&body.kind==='unresolved_question')body.answer=data.get('answer')?.trim()||null;
    body.speaker_names=Object.fromEntries(findingSpeakers(editing).flatMap((speaker,i)=>speaker.ids.map(id=>[id,data.get(`speaker_${i}`)?.trim()||''])));
    if(body.kind==='action_item'){
      body.owner=data.get('owner')?.trim()||null;
      body.deadline_text=data.get('deadline_text')?.trim()||null;
      // Preserve existing date precision only while the displayed deadline is unchanged.
      body.deadline=body.deadline_text===(editing.details?.deadline_text||editing.details?.deadline||null)?editing.details?.deadline||null:null;
    }
    form.querySelector('[type="submit"]').disabled=true;
    await submitReview(editing,body);
    form.querySelector('[type="submit"]').disabled=false;
  };
  dialog.onclose=()=>{editing=null;};
  const handleClick=async event=>{
    const button=event.target.closest('button');if(!button||!snapshot||busy)return;
    if(processing&&!button.hasAttribute('data-cancel-edit'))return;
    if(button.hasAttribute('data-next-recording')){onNextRecording(button.dataset.nextId);return;}
    if(button.hasAttribute('data-view-results')){onRecord();return;}
    if(button.hasAttribute('data-view-summary')){if(noticeFinding)onRecord(noticeFinding);return;}
    if(button.hasAttribute('data-editor-keep-open')){if(editing)await submitReview(editing,{action:'keep_open',revision:editing.revision,evidence_token:editing.evidence_token});return;}
    if(button.hasAttribute('data-cancel-edit')){dialog.close();return;}
    const fid=button.dataset.findingSource||button.dataset.approveFinding||button.dataset.editFinding||button.dataset.rejectFinding||button.dataset.keepOpenFinding;
    if(fid){
      const f=snapshot.findings.find(f=>f.id===fid);if(!f)return;
      if(button.dataset.findingSource){if(dialog.open)dialog.close();showSource({text:f.statement,speaker_names:f.details?.speaker_names,evidence_ids:button.dataset.sourceUtterances?JSON.parse(button.dataset.sourceUtterances):button.dataset.sourceUtterance?[button.dataset.sourceUtterance]:f.evidence.map(e=>e.utterance_id)});return;}
      if(button.dataset.keepOpenFinding){
        if(!f.evidence_current){openEditor(f);return;}
        await submitReview(f,{action:'keep_open',revision:f.revision});return;
      }
      if(button.dataset.editFinding){openEditor(f);return;}
      await submitReview(f,{action:button.dataset.rejectFinding?'reject':'approve',revision:f.revision});return;
    }
    if(!button.hasAttribute('data-extract-decisions'))return;
    button.closest('details').open=false;
    busy=true;error.textContent='';render(snapshot);
    try{
      await api(`${base}/findings/extract`,'POST');
      await refresh();if(!disposed){busy=false;render(snapshot);}
    }catch(e){if(!disposed){busy=false;render(snapshot);error.textContent=e.message||'Could not complete this action.';}}
  };
  root.onclick=handleClick;if(recordRoot)recordRoot.onclick=handleClick;
  return {render,dispose(){disposed=true;clearTimeout(noticeTimer);dialog.close();root.onclick=null;if(recordRoot)recordRoot.onclick=null;form.onsubmit=null;}};
}
