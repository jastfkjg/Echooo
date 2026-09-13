const esc = (v='') => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const available = m => m.visibility === 'shareable' && !m.audiences.length && (!m.expires_at || m.expires_at > Date.now()/1000);
export const projectOptions = (domains, selected) => '<option value="">No project · this meeting only</option>' + domains.map(d=>`<option value="${esc(d.id)}" ${d.id===selected?'selected':''}>${esc(d.name)}</option>`).join('');

export async function editMeetingKnowledge({api,openDialog,meeting,onSave}) {
  const base=`/meetings/${meeting.id}`;
  const [cfg,domains]=await Promise.all([api(`${base}/knowledge`),api('/domains')]);
  let selected=new Set(cfg.memory_ids), referenceIds=new Set(cfg.reference_ids), pending=false, loadVersion=0;
  const modal=openDialog('Project & knowledge',`
    <div class="form-field"><label for="project-choice">Project</label><select id="project-choice" ${cfg.project_locked?'disabled':''}>${projectOptions(domains,cfg.project_id)}</select><p class="muted">${cfg.project_locked?'The project is fixed once recording or participation begins.':'Uses your existing knowledge domains.'}</p></div>
    <div class="form-field"><label for="project-goal">Meeting goal <span class="muted">(optional)</span></label><input id="project-goal" maxlength="2000" value="${esc(cfg.goal)}" placeholder="What should this meeting resolve?"><p class="muted">Shared with the meeting assistant.</p></div>
    <details class="project-references"><summary>Reference domains</summary><p class="muted">Optional sources to read from. Updates are saved only to the main project.</p>${domains.map(d=>`<label class="project-choice"><input type="checkbox" data-reference="${esc(d.id)}" ${referenceIds.has(d.id)?'checked':''}>${esc(d.name)}</label>`).join('')}</details>
    <fieldset class="project-knowledge-list"><legend>Knowledge to share</legend><p class="muted">Only shareable memories without audience restrictions appear here.</p><div id="project-memory-options" role="status"></div></fieldset>
    <label class="project-choice project-consent"><input id="project-share-consent" type="checkbox" ${cfg.memory_ids.length?'checked':''}>Allow selected knowledge in replies to everyone in this meeting.</label>`,async()=>{
      if(pending)throw new Error('Wait for the knowledge list to finish loading.');
      const result=await api(`${base}/knowledge`,'PUT',{project_id:modal.querySelector('#project-choice').value||null,
        goal:modal.querySelector('#project-goal').value, reference_ids:[...referenceIds],memory_ids:[...selected],
        revision:cfg.revision,share_with_meeting:modal.querySelector('#project-share-consent').checked});
      await onSave(result);
    },'Save settings');
  const list=modal.querySelector('#project-memory-options'),project=modal.querySelector('#project-choice');
  async function load(){
    const version=++loadVersion;pending=true;list.textContent='Loading knowledge…';
    const ids=project.value?[...new Set([project.value,...referenceIds])]:[];
    modal.querySelectorAll('[data-reference]').forEach(c=>{c.disabled=!project.value||c.dataset.reference===project.value;});
    try{
      const groups=await Promise.all(ids.map(async id=>({domain:domains.find(d=>d.id===id),memories:await api(`/domains/${id}/memories`)})));
      if(version!==loadVersion||!modal.open)return;
      const eligible=groups.flatMap(g=>g.memories.filter(available));
      selected=new Set([...selected].filter(id=>eligible.some(m=>m.id===id)));
      list.innerHTML=groups.map(g=>{const memories=g.memories.filter(available);return memories.length?`<div class="project-memory-group"><p class="project-group-name">${esc(g.domain.name)}</p>${memories.map(m=>`<label class="project-memory-option"><input type="checkbox" data-memory="${esc(m.id)}" ${selected.has(m.id)?'checked':''}><span><strong>${esc(m.title)}</strong><span class="muted">Version ${m.version} · ${esc(m.content.slice(0,150))}${m.content.length>150?'…':''}</span></span></label>${m.content.length>150?`<details class="project-memory-full"><summary>Read full memory</summary><p>${esc(m.content)}</p></details>`:''}`).join('')}</div>`:'';}).join('')||`<p class="muted">${ids.length?'No eligible knowledge yet. Mark a confirmed memory as shareable with no audience restriction to make it available.':'Choose a project to select knowledge.'}</p>`;
      list.querySelectorAll('[data-memory]').forEach(c=>c.onchange=()=>{c.checked?selected.add(c.dataset.memory):selected.delete(c.dataset.memory);modal.querySelector('#project-share-consent').required=selected.size>0;});
      modal.querySelector('#project-share-consent').required=selected.size>0;pending=false;
    }catch(e){if(version===loadVersion){list.textContent=e.message;pending=true;}}
  }
  project.onchange=()=>{selected.clear();if(!project.value){referenceIds.clear();modal.querySelectorAll('[data-reference]').forEach(c=>c.checked=false);}modal.querySelector('#project-share-consent').checked=false;load();};
  modal.querySelectorAll('[data-reference]').forEach(c=>c.onchange=()=>{c.checked?referenceIds.add(c.dataset.reference):referenceIds.delete(c.dataset.reference);load();});
  load();
}

export async function reviewMeetingUpdate({api,openDialog,proposal,onSave}) {
  const memories=await api(`/domains/${proposal.domain_id}/memories`);
  const targets=memories.map(m=>`<option value="${esc(m.id)}" ${m.id===proposal.target_id?'selected':''}>Replace: ${esc(m.title)} · v${m.version}</option>`).join('');
  const modal=openDialog('Review project update',`
    <p class="muted">Check the facts and attribution before saving. This does not approve actions or commitments.</p>
    <div class="form-field"><label for="update-title">Title</label><input id="update-title" name="title" required maxlength="150" value="${esc(proposal.title)}"></div>
    <div class="form-field"><label for="update-content">Memory</label><textarea id="update-content" name="content" required maxlength="12000" rows="5">${esc(proposal.content)}</textarea></div>
    <div class="form-field"><label for="update-target">Save as</label><select id="update-target"><option value="">New memory</option>${targets}</select><p id="update-previous" class="muted"></p></div>
    <label class="project-choice"><input id="update-shareable" type="checkbox">Make available for future meeting sharing</label>
    <details class="project-evidence"><summary>Supporting conversation</summary>${proposal.evidence.map(e=>`<blockquote><p>${esc(e.content)}</p><footer>${esc(e.speaker||'Unidentified speaker')} · ${Math.floor((e.start_ms||0)/60000)}:${String(Math.floor((e.start_ms||0)/1000)%60).padStart(2,'0')}</footer></blockquote>`).join('')}</details>`,async fd=>{
      const target=memories.find(m=>m.id===modal.querySelector('#update-target').value);
      await api(`/proposals/${proposal.id}/review`,'POST',{decision:'approve',title:fd.get('title'),content:fd.get('content'),
        target_id:target?.id||null,expected_version:target?.id===proposal.target_id?proposal.expected_version:target?.version||null,
        visibility:modal.querySelector('#update-shareable').checked?'shareable':'private',audiences:[]});
      await onSave();
    },'Confirm & save');
  const showPrevious=()=>{const target=memories.find(m=>m.id===modal.querySelector('#update-target').value);modal.querySelector('#update-previous').textContent=target?`Current memory: ${target.content}${target.id===proposal.target_id&&target.version!==proposal.expected_version?' — This target changed after the draft was created; saving a replacement will require a new review.':''}`:'';};
  modal.querySelector('#update-target').onchange=showPrevious;showPrevious();
}
