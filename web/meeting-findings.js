const esc = (value='') => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
const labels={decision:'Decision',action_item:'Action item',unresolved_question:'Unresolved question'};
const evidenceHTML=items=>items.map(e=>`<blockquote><p>${esc(e.quote)}</p><footer>${esc(e.speaker)} · ${e.recording_id?`${time(e.start_ms)}–${time(e.end_ms)}`:'Text note'}</footer></blockquote>`).join('');
const metadataHTML=f=>f.kind==='action_item'?`<p class="muted">Owner: ${esc(f.details?.owner||'Unspecified')} · Deadline: ${esc(f.details?.deadline_text||f.details?.deadline||'Unspecified')}</p>`:'';

export function decisionListHTML(findings, busy=false) {
  if (!findings.length) return '<p class="muted">Decisions, action items and unresolved questions will appear here.</p>';
  return findings.map(f => {
    const stale=!f.evidence_current, reviewable=f.status==='provisional'||(stale&&['approved','edited'].includes(f.status));
    const status=f.status==='provisional'?'Needs review':f.status==='edited'?'Edited and approved':f.status==='approved'?'Approved':'Rejected';
    return `<article class="finding-row"><div class="finding-meta"><strong>${esc(labels[f.kind]||'Decision')} · ${status}</strong>${f.superseded?'<span>Replaced by an approved revision</span>':f.replacement_pending?'<span>Update awaiting review</span>':''}${stale?'<span>Evidence changed · needs re-review</span>':''}</div><p>${esc(f.statement)}</p>${metadataHTML(f)}${f.details?.resolved?'<p>Proposed resolution: this question has been answered.</p>':''}${f.details?.supersedes?'<p class="muted">Approval replaces the earlier finding.</p>':''}<details><summary>Transcript evidence</summary>${evidenceHTML(f.evidence)}<button class="meeting-text-button" data-finding-source="${esc(f.id)}">Open transcript passages</button></details><details><summary>Review history</summary><div data-history-for="${esc(f.id)}"></div></details>${reviewable?`<div class="actions">${!stale?`<button class="btn" data-approve-finding="${esc(f.id)}" ${busy?'disabled':''}>${f.kind==='decision'?'Approve decision':'Approve'}</button>`:''}<button class="btn" data-edit-finding="${esc(f.id)}" ${busy||stale&&!f.can_refresh_evidence?'disabled':''}>${stale?'Review changes':'Edit and approve'}</button><button class="btn" data-reject-finding="${esc(f.id)}" ${busy?'disabled':''}>Reject</button></div>`:''}</article>`;
  }).join('');
}

export function approvedRecordHTML(record) {
  const groups=[['Decisions',record.decisions||[]],['Action items',record.action_items||[]],['Unresolved questions',record.unresolved_questions||[]]];
  if(!groups.some(([,items])=>items.length))return '<p class="muted">No approved findings yet.</p>';
  return `<h3>Approved meeting record</h3><p>${esc(record.title)}</p>${record.pending_reviews?`<p class="muted">${record.pending_reviews} finding(s) still need review and are not included.</p>`:''}${groups.filter(([,items])=>items.length).map(([title,items])=>`<h4>${title}</h4><ol>${items.map(f=>`<li><p>${esc(f.statement)}</p>${metadataHTML(f)}${evidenceHTML(f.evidence)}</li>`).join('')}</ol>`).join('')}`;
}

export function mountFindings(root, {api, base, refresh, showSource}) {
  let snapshot=null,busy=false,disposed=false,showRecord=false,editing=null;
  root.innerHTML=`<div class="meeting-section-heading"><h2 id="finding-title">Findings for review</h2><button class="btn" data-extract-decisions>Check for findings</button></div><p class="muted">Meeting-wide · Review the evidence before approving findings for the record.</p><p data-finding-status role="status" aria-live="polite"></p><p data-finding-error role="alert"></p><div data-finding-list></div><button class="btn" data-generate-record>Generate approved record</button><section data-approved-record hidden aria-label="Approved meeting record"></section><dialog class="finding-editor" aria-labelledby="finding-editor-title"><form><h3 id="finding-editor-title">Review finding</h3><div data-editor-fields></div><p data-editor-error role="alert"></p><div class="actions"><button type="submit" class="btn primary">Save and approve</button><button type="button" class="btn" data-cancel-edit>Cancel</button></div></form></dialog>`;
  const status=root.querySelector('[data-finding-status]'),error=root.querySelector('[data-finding-error]'),dialog=root.querySelector('dialog'),form=dialog.querySelector('form');
  function render(value){
    if(disposed)return;
    snapshot=value;
    const progress=value.finding_progress||{phase:'idle'},items=value.findings||[];
    status.textContent=busy?'Processing…':['processing','queued'].includes(progress.phase)?'Extracting findings…':progress.phase==='retrying'?'Retrying extraction…':progress.phase==='unavailable'?progress.error:progress.pending?`${progress.pending} transcript passage(s) awaiting extraction.`:'Findings are up to date with the processed transcript.';
    if(!busy)error.textContent=progress.phase==='error'?progress.error:'';
    const list=root.querySelector('[data-finding-list]'),html=decisionListHTML(items,busy);
    if(list._html!==html){list.innerHTML=html;list._html=html;}
    for(const node of list.querySelectorAll('[data-history-for]')){
      const entries=(value.finding_reviews||[]).filter(r=>r.finding_id===node.dataset.historyFor);
      node.innerHTML=entries.length?entries.map(r=>`<p>${esc(r.action.replaceAll('_',' '))} · ${esc(new Date(r.created_at*1000).toLocaleString())}</p><p>Before: ${esc(r.before.statement)}</p>${metadataHTML(r.before)}<p>After: ${esc(r.after.statement)}</p>${metadataHTML(r.after)}`).join(''):'<p class="muted">No review actions yet.</p>';
    }
    root.querySelector('[data-extract-decisions]').disabled=busy||['processing','queued','retrying','unavailable'].includes(progress.phase);
    root.querySelector('[data-generate-record]').disabled=busy||!!value.recording;
    const record=root.querySelector('[data-approved-record]');record.hidden=!showRecord;
    if(showRecord)record.innerHTML=approvedRecordHTML(value.approved_record||{});
  }
  function openEditor(f){
    editing=structuredClone(f);
    const field=(name,label,value)=>`<label>${label}<input name="${name}" maxlength="200" value="${esc(value||'')}"></label>`;
    root.querySelector('[data-editor-fields]').innerHTML=`<label>Statement<textarea name="statement" required maxlength="1000" rows="4">${esc(f.statement)}</textarea></label>${f.kind==='action_item'?field('owner','Owner',f.details?.owner)+field('deadline_text','Deadline as written',f.details?.deadline_text)+field('deadline','Normalized deadline (ISO date/time, optional)',f.details?.deadline):''}<h4>Original evidence</h4>${evidenceHTML(f.evidence)}${!f.evidence_current?`<h4>Current evidence</h4>${evidenceHTML(f.current_evidence||[])}<label class="finding-confirm"><input type="checkbox" name="confirmed" required> I reviewed the changed evidence and confirm this finding.</label>`:''}`;
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
      if(button.dataset.findingSource){showSource({text:f.statement,evidence_ids:f.evidence.map(e=>e.utterance_id)});return;}
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
