const esc = (value='') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = ms => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;

export function decisionListHTML(findings, busy=false) {
  if (!findings.length) return '<p class="muted">Decisions will appear here when explicitly agreed in the conversation.</p>';
  return findings.map(f => `<article class="finding-row"><div class="finding-meta"><strong>${esc(f.status === 'provisional' ? 'Needs review' : f.status === 'edited' ? 'Edited and approved' : f.status === 'approved' ? 'Approved' : 'Rejected')}</strong>${!f.evidence_current?'<span>Evidence changed · needs re-review</span>':''}</div><p>${esc(f.statement)}</p><details><summary>Transcript evidence</summary>${f.evidence.map(e=>`<blockquote><p>${esc(e.quote)}</p><footer>${esc(e.speaker)} · ${e.recording_id?`${time(e.start_ms)}–${time(e.end_ms)}`:'Text note'}</footer></blockquote>`).join('')}<button class="meeting-text-button" data-finding-source="${esc(f.id)}">Open transcript passages</button></details>${f.status==='provisional'?`<button class="btn" data-approve-finding="${esc(f.id)}" ${busy||!f.evidence_current?'disabled':''}>Approve decision</button>`:''}</article>`).join('');
}

export function approvedRecordHTML(record) {
  return record.decisions.length ? `<h3>${esc(record.title)}</h3><ol>${record.decisions.map(f=>`<li><p>${esc(f.statement)}</p>${f.evidence.map(e=>`<p class="muted">${esc(e.speaker)} · ${e.recording_id?time(e.start_ms):'Text note'} — “${esc(e.quote)}”</p>`).join('')}</li>`).join('')}</ol>` : '<p class="muted">No approved decisions yet.</p>';
}

export function mountFindings(root, {api, base, refresh, showSource}) {
  let snapshot = null, busy = false, disposed = false, showRecord = false;
  root.innerHTML = `<div class="meeting-section-heading"><h2 id="finding-title">Decisions for review</h2><button class="btn" data-extract-decisions>Check for decisions</button></div><p class="muted">Meeting-wide · Evidence-backed decisions need your approval before entering the record.</p><p data-finding-status role="status" aria-live="polite"></p><p data-finding-error role="alert"></p><div data-finding-list></div><button class="btn" data-generate-record>Generate approved record</button><section data-approved-record hidden aria-label="Approved meeting record"></section>`;
  const status=root.querySelector('[data-finding-status]'), error=root.querySelector('[data-finding-error]');
  function render(value) {
    if (disposed) return;
    snapshot=value;
    const progress=value.finding_progress||{phase:'idle'}, items=value.findings||[];
    status.textContent=busy?'Saving…':progress.phase==='processing'?'Extracting decisions…':progress.phase==='unavailable'?progress.error:'Only explicitly agreed decisions are extracted in this version.';
    if(!busy)error.textContent=progress.phase==='error'?progress.error:'';
    const list=root.querySelector('[data-finding-list]'), html=decisionListHTML(items,busy);
    if(list._html!==html){list.innerHTML=html;list._html=html;}
    root.querySelector('[data-extract-decisions]').disabled=busy||['processing','unavailable'].includes(progress.phase);
    root.querySelector('[data-generate-record]').disabled=busy;
    const record=root.querySelector('[data-approved-record]');
    record.hidden=!showRecord;
    if(showRecord)record.innerHTML=approvedRecordHTML(value.approved_record||{decisions:[]});
  }
  root.onclick=async event=>{
    const button=event.target.closest('button');
    if(!button||!snapshot||busy)return;
    if(button.dataset.findingSource){
      const f=snapshot.findings.find(f=>f.id===button.dataset.findingSource);
      if(f)showSource({text:f.statement,evidence_ids:f.evidence.map(e=>e.utterance_id)});
      return;
    }
    const fid=button.dataset.approveFinding;
    if(!fid&&!button.hasAttribute('data-extract-decisions')&&!button.hasAttribute('data-generate-record'))return;
    busy=true;error.textContent='';render(snapshot);
    try {
      if(fid){
        const f=snapshot.findings.find(f=>f.id===fid);
        await api(`${base}/findings/${fid}/review`,'POST',{action:'approve',revision:f.revision});
      }else if(button.hasAttribute('data-extract-decisions')){
        await api(`${base}/findings/extract`,'POST');
      }else{
        await api(`${base}/approved-record`,'POST');
        showRecord=true;
      }
      await refresh();
      if(!disposed){busy=false;render(snapshot);status.textContent=fid?'Decision approved.':showRecord?'Approved record updated.':'Decision check requested.';}
    }catch(e){if(!disposed){busy=false;render(snapshot);error.textContent=e.message||'Could not complete this action. Please retry.';}}
  };
  return {render, dispose(){disposed=true;root.onclick=null;}};
}
