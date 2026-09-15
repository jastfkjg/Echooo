const esc = (value='') => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
const labels={decision:'Decision',action_item:'Action item',unresolved_question:'Open question'};
const evidenceHTML=(items,fid)=>items.map(e=>`<blockquote><p>${esc(e.quote)}</p><footer><span>${esc(e.speaker)} · ${e.recording_id?`${time(e.start_ms)}–${time(e.end_ms)}`:'Text note'}</span>${fid?`<button class="meeting-text-button" data-finding-source="${esc(fid)}" data-source-utterance="${esc(e.utterance_id)}">Open transcript</button>`:''}</footer></blockquote>`).join('');
const metadataHTML=f=>f.kind==='action_item'?`<p class="muted">Owner: ${esc(f.details?.owner||'Unspecified')} · Deadline: ${esc(f.details?.deadline_text||f.details?.deadline||'Unspecified')}</p>`:'';

const needsReview=f=>!f.superseded&&(f.status==='provisional'||(!f.evidence_current&&['approved','edited'].includes(f.status)));

export function decisionListHTML(findings, busy=false) {
  if (!findings.length) return '<p class="muted">No findings yet. Only clear decisions, commitments and open follow-ups are included.</p>';
  const row=f=>{
    const stale=!f.evidence_current, reviewable=needsReview(f);
    const status=f.superseded?'Superseded':f.status==='rejected'?'Rejected':reviewable?(stale?'Outdated · needs update':'Needs review'):'Approved';
    const disabled=busy||stale&&!f.can_refresh_evidence;
    return `<article class="finding-row" data-review-state="${reviewable?'pending':f.status}"><div class="finding-main"><div class="finding-meta"><span>${esc(labels[f.kind]||'Decision')}</span><span class="finding-status">${status}</span>${f.replacement_pending?'<span>Update pending</span>':''}</div><p class="finding-statement">${esc(f.statement)}</p>${metadataHTML(f)}${f.details?.resolved?'<p class="muted">Answered · approval removes this open question from the record.</p>':''}</div>${reviewable?`<div class="actions finding-actions"><button class="btn primary" ${stale?'data-edit-finding':'data-approve-finding'}="${esc(f.id)}" ${disabled?'disabled':''}>${stale?'Review &amp; approve':'Approve'}</button>${!stale?`<button class="meeting-text-button" data-edit-finding="${esc(f.id)}" ${busy?'disabled':''}>Edit</button>`:''}<button class="meeting-text-button" data-reject-finding="${esc(f.id)}" ${busy?'disabled':''}>Reject</button></div>`:''}<details class="finding-details" data-finding-details="${esc(f.id)}"><summary>${stale?'Original evidence':'Evidence'}${f.evidence.length>1?` · ${f.evidence.length} sources`: ''}</summary>${stale&&!f.can_refresh_evidence?'<p class="muted">Source deleted. This finding can only be rejected.</p>':''}${f.details?.supersedes?'<p class="muted">Approval replaces the earlier finding.</p>':''}${evidenceHTML(f.evidence,f.id)}<div data-history-for="${esc(f.id)}"></div></details></article>`;
  };
  const pending=findings.filter(needsReview),reviewed=findings.filter(f=>!needsReview(f));
  return pending.map(row).join('')+(reviewed.length?`<details class="finding-reviewed" data-finding-details="reviewed"><summary>Reviewed · ${reviewed.length}</summary>${reviewed.map(row).join('')}</details>`:'');
}

export function approvedRecordHTML(record) {
  const groups=[['Decisions',record.decisions||[]],['Action items',record.action_items||[]],['Unresolved questions',record.unresolved_questions||[]]];
  if(!groups.some(([,items])=>items.length))return '<p class="muted">No approved findings yet.</p>';
  return `<h3>Approved meeting record</h3><p>${esc(record.title)}</p>${record.pending_reviews?`<p class="muted">${record.pending_reviews} finding(s) still need review and are not included.</p>`:''}${groups.filter(([,items])=>items.length).map(([title,items])=>`<h4>${title}</h4><ol>${items.map(f=>`<li><p>${esc(f.statement)}</p>${metadataHTML(f)}${evidenceHTML(f.evidence)}</li>`).join('')}</ol>`).join('')}`;
}

export function findingEditorHTML(f){
  const field=(name,label,value)=>`<label>${label}<input name="${name}" maxlength="200" value="${esc(value||'')}"></label>`;
  return `${!f.evidence_current?`<h4>Current transcript</h4>${evidenceHTML(f.current_evidence||[],f.id)}`:''}<label>${f.evidence_current?'Statement':'Update statement to match the current transcript'}<textarea name="statement" required maxlength="1000" rows="3">${esc(f.statement)}</textarea></label>${f.kind==='action_item'?field('owner','Owner',f.details?.owner)+field('deadline_text','Deadline as written',f.details?.deadline_text)+field('deadline','Normalized deadline (ISO date/time, optional)',f.details?.deadline):''}${f.evidence_current?`<h4>Supporting evidence</h4>${evidenceHTML(f.evidence,f.id)}`:`<details><summary>Previous evidence</summary>${evidenceHTML(f.evidence)}</details>`}`;
}

export function mountFindings(root, {api, base, refresh, showSource}) {
  let snapshot=null,busy=false,disposed=false,showRecord=false,editing=null;
  root.innerHTML=`<div class="meeting-section-heading"><h2 id="finding-title">Findings for review</h2><button class="btn" data-extract-decisions>Check for findings</button></div><p class="muted" data-finding-count></p><p data-finding-status role="status" aria-live="polite"></p><p data-finding-error role="alert"></p><div data-finding-list></div><button class="btn" data-generate-record>Generate approved record</button><section data-approved-record hidden aria-label="Approved meeting record"></section><dialog class="finding-editor" aria-labelledby="finding-editor-title"><form><h3 id="finding-editor-title">Review finding</h3><div data-editor-fields></div><p data-editor-error role="alert"></p><div class="actions"><button type="submit" class="btn primary">Save and approve</button><button type="button" class="btn" data-cancel-edit>Cancel</button></div></form></dialog>`;
  const status=root.querySelector('[data-finding-status]'),error=root.querySelector('[data-finding-error]'),dialog=root.querySelector('dialog'),form=dialog.querySelector('form');
  function render(value){
    if(disposed)return;
    snapshot=value;
    const progress=value.finding_progress||{phase:'idle'},items=value.findings||[];
    status.textContent=busy?'Processing…':['processing','queued'].includes(progress.phase)?'Extracting findings…':progress.phase==='retrying'?'Retrying extraction…':progress.phase==='unavailable'?progress.error:progress.pending?`${progress.pending} transcript passage(s) awaiting extraction.`:'';
    if(!busy)error.textContent=progress.phase==='error'?progress.error:'';
    const list=root.querySelector('[data-finding-list]'),html=decisionListHTML(items,busy);
    if(list._html!==html){
      const opened=new Set([...list.querySelectorAll('details[open]')].map(n=>n.dataset.findingDetails));
      list.innerHTML=html;list._html=html;
      for(const node of list.querySelectorAll('[data-finding-details]'))node.open=opened.has(node.dataset.findingDetails);
    }
    root.querySelector('[data-finding-count]').textContent=`${items.filter(needsReview).length} awaiting review`;
    for(const node of list.querySelectorAll('[data-history-for]')){
      const entries=(value.finding_reviews||[]).filter(r=>r.finding_id===node.dataset.historyFor);
      node.innerHTML=entries.length?'<details><summary>History · '+entries.length+'</summary>'+entries.map(r=>`<p>${esc(r.action.replaceAll('_',' '))} · ${esc(new Date(r.created_at*1000).toLocaleString())}</p><p>Before: ${esc(r.before.statement)}</p>${metadataHTML(r.before)}<p>After: ${esc(r.after.statement)}</p>${metadataHTML(r.after)}`).join('')+'</details>':'';
    }
    root.querySelector('[data-extract-decisions]').disabled=busy||['processing','queued','retrying','unavailable'].includes(progress.phase);
    root.querySelector('[data-generate-record]').disabled=busy||!!value.recording;
    const record=root.querySelector('[data-approved-record]');record.hidden=!showRecord;
    if(showRecord)record.innerHTML=approvedRecordHTML(value.approved_record||{});
  }
  function openEditor(f){
    editing=structuredClone(f);
    root.querySelector('[data-editor-fields]').innerHTML=findingEditorHTML(f);
    root.querySelector('[data-editor-error]').textContent='';dialog.showModal();form.elements.statement.focus();
  }
  async function submitReview(f,body){
    busy=true;render(snapshot);
    try{
      await api(`${base}/findings/${f.id}/review`,'POST',body);
      dialog.close();await refresh();
      if(!disposed){busy=false;render(snapshot);status.textContent=body.action==='reject'?'Finding rejected.':'Finding approved.';}
    }catch(e){if(!disposed){busy=false;render(snapshot);(dialog.open?root.querySelector('[data-editor-error]'):error).textContent=e.message||'Could not save this review.';}}
  }
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!editing)return;
    const data=new FormData(form),body={action:'edit',revision:editing.revision,statement:data.get('statement'),evidence_token:editing.evidence_token};
    if(editing.kind==='action_item')for(const key of ['owner','deadline','deadline_text'])body[key]=data.get(key)||null;
    form.querySelector('[type="submit"]').disabled=true;
    await submitReview(editing,body);
    form.querySelector('[type="submit"]').disabled=false;
  };
  dialog.onclose=()=>{editing=null;};
  root.onclick=async event=>{
    const button=event.target.closest('button');if(!button||!snapshot||busy)return;
    if(button.hasAttribute('data-cancel-edit')){dialog.close();return;}
    const fid=button.dataset.findingSource||button.dataset.approveFinding||button.dataset.editFinding||button.dataset.rejectFinding;
    if(fid){
      const f=snapshot.findings.find(f=>f.id===fid);if(!f)return;
      if(button.dataset.findingSource){if(dialog.open)dialog.close();showSource({text:'',evidence_ids:button.dataset.sourceUtterance?[button.dataset.sourceUtterance]:f.evidence.map(e=>e.utterance_id)});return;}
      if(button.dataset.editFinding){openEditor(f);return;}
      await submitReview(f,{action:button.dataset.rejectFinding?'reject':'approve',revision:f.revision});return;
    }
    if(!button.hasAttribute('data-extract-decisions')&&!button.hasAttribute('data-generate-record'))return;
    busy=true;error.textContent='';render(snapshot);
    try{
      if(button.hasAttribute('data-extract-decisions'))await api(`${base}/findings/extract`,'POST');
      else{await api(`${base}/approved-record`,'POST');showRecord=true;}
      await refresh();if(!disposed){busy=false;render(snapshot);}
    }catch(e){if(!disposed){busy=false;render(snapshot);error.textContent=e.message||'Could not complete this action.';}}
  };
  return {render,dispose(){disposed=true;dialog.close();root.onclick=null;form.onsubmit=null;}};
}
