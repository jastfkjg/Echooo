import {speakerName} from './meeting-transcript.js';
const esc = (value='') => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
const labels={decision:'Decision',action_item:'Action item',unresolved_question:'Open question'};
// Group nearby source fragments for reading; keep every original quote and anchor.
export function groupEvidence(items) {
  const groups=[];
  for(const e of items){
    const last=groups.at(-1);
    if(last && e.recording_id && last.recording_id===e.recording_id && last.speaker===e.speaker &&
      e.start_ms>=last.start_ms && e.start_ms-last.end_ms<=2000 && e.end_ms-last.start_ms<=30000){
      last.items.push(e);last.end_ms=Math.max(last.end_ms,e.end_ms);
    }else groups.push({...e,items:[e]});
  }
  return groups;
}
const evidenceHTML=(items,fid)=>groupEvidence(items).map(g=>`<blockquote><p>${g.items.map(e=>`<span>${esc(e.quote)}</span>`).join('<span class="evidence-break" aria-label="Next transcript segment"> / </span>')}</p><footer><span>${esc(speakerName(g.speaker))} · ${g.recording_id?`${time(g.start_ms)}–${time(g.end_ms)}`:'Text note'}</span>${g.items.length>1?`<span>${g.items.length} transcript segments</span>`:''}${fid?g.items.map((e,i)=>`<button type="button" class="meeting-text-button" data-finding-source="${esc(fid)}" data-source-utterance="${esc(e.utterance_id)}">${g.items.length>1?`Segment ${i+1} · ${time(e.start_ms)}`:'Open transcript'}</button>`).join(''):''}</footer></blockquote>`).join('');
const metadataHTML=f=>f.kind==='action_item'?`<p class="muted">Owner: ${esc(f.details?.owner||'Unspecified')} · Deadline: ${esc(f.details?.deadline_text||f.details?.deadline||'Unspecified')}</p>`:'';

export function findingSpeakers(f){
  const groups=[];
  for(const e of f.evidence||[]){
    const name=f.details?.speaker_names?.[e.utterance_id]||speakerName(e.speaker);
    const group=groups.find(g=>g.original===speakerName(e.speaker)&&g.recording===e.recording_id&&g.name===name);
    if(group)group.ids.push(e.utterance_id);
    else groups.push({name,original:speakerName(e.speaker),recording:e.recording_id,ids:[e.utterance_id]});
  }
  return groups;
}
export function findingContentHTML(f, className='finding-statement'){
  const speakers=findingSpeakers(f);
  let statement=f.statement;
  // Separate only an exact, evidenced name at the beginning; never infer identity.
  const prefix=speakers.flatMap(s=>[s.original,s.name]).sort((a,b)=>b.length-a.length).find(name=>
    statement.startsWith(name+' ')||statement.startsWith(name+':'));
  if(prefix)statement=statement.slice(prefix.length).replace(/^:\s*|^\s+/, '');
  return `${speakers.length?`<p class="finding-speakers" aria-label="Speakers">${[...new Set(speakers.map(s=>s.name))].map(name=>`<span>${esc(name)}</span>`).join('')}</p>`:''}<p class="${className}">${esc(statement||f.statement)}</p>`;
}

export function findingHistoryHTML(entries, fid) {
  if(!entries.length)return '';
  const actions={approve:'Approved',edit:'Edited & approved',reject:'Rejected',extraction_revision:'Updated from transcript'};
  const changes=r=>{
    const fields=[['speakers','Speaker',v=>v],['kind','Type',v=>labels[v]||v],['statement','Summary',v=>v],['owner','Owner',v=>v],['deadline_text','Deadline',v=>v]];
    return fields.flatMap(([key,label,format])=>{
      const before=key==='speakers'?findingSpeakers(r.before).map(s=>s.name).join(', '):key==='owner'||key==='deadline_text'?r.before.details?.[key]:r.before[key];
      const after=key==='speakers'?findingSpeakers(r.after).map(s=>s.name).join(', '):key==='owner'||key==='deadline_text'?r.after.details?.[key]:r.after[key];
      return (before??null)===(after??null)?[]:[`<div class="finding-change"><dt>${label}</dt><dd><span class="finding-change-before">${esc(format(before)||'Not set')}</span><span>${esc(format(after)||'Not set')}</span></dd></div>`];
    }).join('');
  };
  return `<details class="finding-details finding-history" data-finding-details="history-${esc(fid)}"><summary>History <span class="finding-detail-count">${entries.length}</span></summary><ol class="finding-timeline">${[...entries].reverse().map(r=>`<li><div class="finding-history-heading"><strong>${esc(actions[r.action]||r.action.replaceAll('_',' '))}</strong><time datetime="${esc(new Date(r.created_at*1000).toISOString())}">${esc(new Date(r.created_at*1000).toLocaleString())}</time></div>${changes(r)?`<dl>${changes(r)}</dl>`:''}</li>`).join('')}</ol></details>`;
}

export const needsReview=f=>!f.superseded&&(f.status==='provisional'||(!f.evidence_current&&['approved','edited'].includes(f.status)));

export function decisionListHTML(findings, busy=false, reviews=[]) {
  if (!findings.length) return '';
  const row=f=>{
    const stale=!f.evidence_current, reviewable=needsReview(f);
    const status=f.superseded?'Superseded':f.status==='rejected'?'Rejected':reviewable?(stale?'Needs update':'Needs review'):f.status==='edited'?'Edited & approved':'Approved';
    const disabled=busy||stale&&!f.can_refresh_evidence;
    return `<article class="finding-row" data-review-state="${reviewable?'pending':f.status}"><div class="finding-main"><div class="finding-meta"><span>${esc(labels[f.kind]||'Decision')}</span><span class="finding-status">${esc(status)}</span>${f.replacement_pending?'<span>Update pending</span>':''}</div>${findingContentHTML(f)}${metadataHTML(f)}${f.details?.resolved?'<p class="muted">Answered · approval removes this open question from the record.</p>':''}</div>${reviewable?`<div class="actions finding-actions"><button class="btn primary" ${stale?'data-edit-finding':'data-approve-finding'}="${esc(f.id)}" ${disabled?'disabled':''}>${stale?'Review &amp; approve':'Approve'}</button>${!stale?`<button class="meeting-text-button" data-edit-finding="${esc(f.id)}" ${busy?'disabled':''}>Edit</button>`:''}<button class="meeting-text-button" data-reject-finding="${esc(f.id)}" ${busy?'disabled':''}>Reject</button></div>`:''}<div class="finding-disclosures"><details class="finding-details" data-finding-details="${esc(f.id)}"><summary>Source</summary>${stale?'<p class="muted">Previous transcript</p>':''}${stale&&!f.can_refresh_evidence?'<p class="muted">Source deleted. This finding can only be rejected.</p>':''}${f.details?.supersedes?'<p class="muted">Approval replaces the earlier finding.</p>':''}${evidenceHTML(f.evidence,f.id)}</details>${findingHistoryHTML(reviews.filter(r=>r.finding_id===f.id),f.id)}</div></article>`;
  };
  const pending=findings.filter(needsReview),reviewed=findings.filter(f=>!needsReview(f));
  return pending.map(row).join('')+(reviewed.length?`<details class="finding-reviewed" data-finding-details="reviewed"><summary>Reviewed · ${reviewed.length}</summary>${reviewed.map(row).join('')}</details>`:'');
}

export function approvedRecordHTML(record, recordingId) {
  const groups=[['Decisions',record.decisions||[]],['Action items',record.action_items||[]],['Open questions',record.unresolved_questions||[]]].map(([label,items])=>[label,recordingId===undefined?items:items.filter(f=>f.evidence.some(e=>(e.recording_id||'notes')===recordingId))]);
  if(!groups.some(([,items])=>items.length))return recordingId===undefined?'<p class="muted">No approved findings yet. Approve items in Review.</p>':'';
  return `<h2>Confirmed results</h2>${groups.filter(([,items])=>items.length).map(([title,items])=>`<section class="record-group"><h3>${title}</h3><ol>${items.map(f=>`<li data-confirmed-finding="${esc(f.id)}" tabindex="-1">${findingContentHTML(f,'record-statement')}${metadataHTML(f)}<details class="finding-details" data-record-evidence="${esc(f.id)}"><summary>Source</summary>${f.status==='edited'?'<p class="record-edit-label">Edited &amp; approved</p>':''}${evidenceHTML(f.evidence,f.id)}</details></li>`).join('')}</ol></section>`).join('')}`;
}

export function findingEditorHTML(f){
  const field=(name,label,value)=>`<label>${label}<input name="${name}" maxlength="200" value="${esc(value||'')}"></label>`;
  return `<label>Type<select name="kind">${Object.entries(labels).map(([kind,label])=>`<option value="${kind}" ${f.kind===kind?'selected':''}>${label}</option>`).join('')}</select></label><div class="finding-speaker-fields">${findingSpeakers(f).map((speaker,i)=>`<label>${i?'Speaker '+(i+1):'Speaker name'}<input name="speaker_${i}" maxlength="80" required value="${esc(speaker.name)}"></label>`).join('')}<p class="muted">Applies to this finding. Source names stay unchanged.</p></div>${!f.evidence_current?`<h4>Current transcript</h4>${evidenceHTML(f.current_evidence||[],f.id)}`:''}<label>${f.evidence_current?'Finding summary':'Update summary to match the current transcript'}<textarea name="statement" required maxlength="1000" rows="3">${esc(f.statement)}</textarea></label><div class="finding-action-fields" data-action-fields ${f.kind==='action_item'?'':'hidden'}>${field('owner','Owner (optional)',f.details?.owner)+field('deadline_text','Deadline (optional)',f.details?.deadline_text||f.details?.deadline)}</div>${f.evidence_current?`<h4>Source</h4>${evidenceHTML(f.evidence,f.id)}`:`<details><summary>Previous transcript</summary>${evidenceHTML(f.evidence)}</details>`}`;
}

export function mountFindings(root, {api, base, refresh, showSource, recordRoot=null, onRecord=()=>{}, onPending=()=>{}, getRecordScope=()=>undefined}) {
  let snapshot=null,busy=false,disposed=false,editing=null,noticeTimer=null,noticeFinding=null;
  root.innerHTML=`<div class="meeting-section-heading"><h2 id="finding-title">Findings for review</h2><details class="meeting-menu"><summary aria-label="Review options">…</summary><div class="meeting-menu-items"><button data-extract-decisions>Check for findings</button></div></details></div><p class="muted" data-finding-count></p><p data-finding-status role="status" aria-live="polite"></p><p data-finding-error role="alert"></p><div class="finding-notice" data-finding-notice hidden><span role="status" data-notice-text></span><button class="meeting-text-button" data-view-summary hidden>View in Summary</button></div><div data-finding-list></div><section data-approved-record hidden aria-label="Approved meeting record"></section><dialog class="finding-editor" aria-labelledby="finding-editor-title"><form><h3 id="finding-editor-title">Review finding</h3><div data-editor-fields></div><p data-editor-error role="alert"></p><div class="actions"><button type="submit" class="btn primary">Save and approve</button><button type="button" class="btn" data-cancel-edit>Cancel</button></div></form></dialog>`;
  const record=recordRoot||root.querySelector('[data-approved-record]');
  if(recordRoot)root.querySelector('[data-approved-record]').remove();
  const status=root.querySelector('[data-finding-status]'),error=root.querySelector('[data-finding-error]'),dialog=root.querySelector('dialog'),form=dialog.querySelector('form');
  function render(value){
    if(disposed)return;
    snapshot=value;
    const progress=value.finding_progress||{phase:'idle'},items=value.findings||[];
    status.textContent=busy?'Processing…':['processing','queued'].includes(progress.phase)?'Extracting findings…':progress.phase==='retrying'?'Retrying extraction…':progress.phase==='unavailable'?progress.error:progress.pending?`${progress.pending} transcript passage(s) awaiting extraction.`:'';
    if(!busy)error.textContent=progress.phase==='error'?progress.error:'';
    const list=root.querySelector('[data-finding-list]'),html=decisionListHTML(items,busy,value.finding_reviews||[]);
    if(list._html!==html){
      const opened=new Set([...list.querySelectorAll('details[open]')].map(n=>n.dataset.findingDetails));
      list.innerHTML=html;list._html=html;
      for(const node of list.querySelectorAll('[data-finding-details]'))node.open=opened.has(node.dataset.findingDetails);
    }
    onPending(items.filter(needsReview).length);
    const pending=items.filter(needsReview).length;
    root.querySelector('[data-finding-count]').textContent=pending?`${pending} awaiting review`:['processing','queued','retrying','error','unavailable'].includes(progress.phase)||progress.pending?'':'All caught up';
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
    form.elements.kind.onchange=()=>{root.querySelector('[data-action-fields]').hidden=form.elements.kind.value!=='action_item';};
    root.querySelector('[data-editor-error]').textContent='';dialog.showModal();form.elements.statement.focus();
  }
  async function submitReview(f,body){
    clearTimeout(noticeTimer);root.querySelector('[data-finding-notice]').hidden=true;
    busy=true;render(snapshot);
    try{
      await api(`${base}/findings/${f.id}/review`,'POST',body);
      dialog.close();await refresh();
      if(!disposed){
        busy=false;render(snapshot);
        noticeFinding=Object.values(snapshot.approved_record||{}).filter(Array.isArray).flat().find(item=>item.id===f.id);
        const notice=root.querySelector('[data-finding-notice]');
        root.querySelector('[data-notice-text]').textContent=body.action==='reject'?'Rejected':'Approved';
        root.querySelector('[data-view-summary]').hidden=body.action==='reject'||!noticeFinding;
        notice.hidden=false;
        noticeTimer=setTimeout(()=>{if(!notice.contains(document.activeElement))notice.hidden=true;},12000);
      }
    }catch(e){if(!disposed){busy=false;render(snapshot);(dialog.open?root.querySelector('[data-editor-error]'):error).textContent=e.message||'Could not save this review.';}}
  }
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!editing)return;
    const data=new FormData(form),body={action:'edit',revision:editing.revision,kind:data.get('kind'),statement:data.get('statement'),evidence_token:editing.evidence_token};
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
    if(button.hasAttribute('data-view-summary')){if(noticeFinding)onRecord(noticeFinding);return;}
    if(button.hasAttribute('data-cancel-edit')){dialog.close();return;}
    const fid=button.dataset.findingSource||button.dataset.approveFinding||button.dataset.editFinding||button.dataset.rejectFinding;
    if(fid){
      const f=snapshot.findings.find(f=>f.id===fid);if(!f)return;
      if(button.dataset.findingSource){if(dialog.open)dialog.close();showSource({text:f.statement,evidence_ids:button.dataset.sourceUtterance?[button.dataset.sourceUtterance]:f.evidence.map(e=>e.utterance_id)});return;}
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
