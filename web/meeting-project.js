const esc = (v='') => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const available = m => m.visibility === 'shareable' && !m.audiences.length && (!m.expires_at || m.expires_at > Date.now()/1000);
export const projectOptions = (domains, selected) => '<option value="">No project</option>' + domains.map(d=>`<option value="${esc(d.id)}" ${d.id===selected?'selected':''}>${esc(d.name)}</option>`).join('');

export function newProjectMeeting({api,openDialog,field,projects,onCreate}) {
  const modal=openDialog('New meeting',field('title','Meeting title','','text','required maxlength="120"')+`
    <div class="form-field"><label for="new-project">Project <span class="muted">(optional)</span></label><select id="new-project" name="project_id">${projectOptions(projects,null)}</select><p id="new-project-sharing" class="muted" hidden>Uses all shareable project knowledge.</p></div>`,async fd=>{
      onCreate(await api('/meetings','POST',{title:fd.get('title'),project_id:fd.get('project_id')||null}));
    },'Create meeting');
  modal.querySelector('#new-project').onchange=e=>{modal.querySelector('#new-project-sharing').hidden=!e.target.value;};
  return modal;
}

export async function editMeetingKnowledge({api,openDialog,meeting,onSave}) {
  const base=`/meetings/${meeting.id}`;
  const [cfg,domains]=await Promise.all([api(`${base}/knowledge`),api('/domains')]);
  let referenceIds=new Set(cfg.reference_ids),loadVersion=0;
  const modal=openDialog('Project settings',`
    <div class="form-field"><label for="project-choice">Project</label><select id="project-choice" ${cfg.project_locked?'disabled title="Fixed after the meeting starts"':''}>${projectOptions(domains,cfg.project_id)}</select></div>
    <div class="form-field"><label for="project-goal">Meeting goal <span class="muted">(optional)</span></label><input id="project-goal" maxlength="2000" value="${esc(cfg.goal)}" placeholder="What should this meeting resolve?"></div>
    <p class="muted" id="project-access-note">Uses all shareable project knowledge, kept up to date.</p>
    <details class="project-knowledge-preview"><summary id="project-knowledge-count">Knowledge</summary><div id="project-memory-options"></div></details>
    <details class="project-references"><summary>More options</summary><p class="project-group-name">Reference projects</p>${domains.map(d=>`<label class="project-choice"><input type="checkbox" data-reference="${esc(d.id)}" ${referenceIds.has(d.id)?'checked':''}>${esc(d.name)}</label>`).join('')}<p class="muted">Updates save to the main project. Private, restricted and unreviewed knowledge stays excluded.</p>${cfg.project_locked?'<p class="muted">The main project is fixed after the meeting starts.</p>':''}</details>`,async()=>{
      await onSave(await api(`${base}/knowledge`,'PUT',{project_id:modal.querySelector('#project-choice').value||null,
        goal:modal.querySelector('#project-goal').value,reference_ids:[...referenceIds],revision:cfg.revision}));
    },'Save');
  const list=modal.querySelector('#project-memory-options'),project=modal.querySelector('#project-choice'),count=modal.querySelector('#project-knowledge-count');
  async function load(){
    const version=++loadVersion;count.textContent='Knowledge · Loading…';
    const ids=project.value?[...new Set([project.value,...referenceIds])]:[];
    modal.querySelector('#project-access-note').textContent=project.value?'Uses all shareable project knowledge, kept up to date.':'Uses this meeting’s discussion only.';
    modal.querySelectorAll('[data-reference]').forEach(c=>{c.disabled=!project.value||c.dataset.reference===project.value;});
    try{
      const groups=await Promise.all(ids.map(async id=>({domain:domains.find(d=>d.id===id),memories:(await api(`/domains/${id}/memories`)).filter(available)})));
      if(version!==loadVersion||!modal.open)return;
      const n=groups.reduce((sum,g)=>sum+g.memories.length,0);
      count.textContent=`Knowledge · ${n} ${n===1?'memory':'memories'}`;
      list.innerHTML=groups.filter(g=>g.memories.length).map(g=>`<div class="project-memory-group"><a href="#domain/${encodeURIComponent(g.domain.id)}/memories" data-open-project>${esc(g.domain.name)}</a>${g.memories.map(m=>`<div class="project-memory-preview"><strong>${esc(m.title)}</strong><p class="muted">${esc(m.content.slice(0,150))}${m.content.length>150?'…':''}</p></div>`).join('')}</div>`).join('')||'<p class="muted">No shareable memories yet.</p>';
      list.querySelectorAll('[data-open-project]').forEach(a=>a.onclick=()=>modal.close());
    }catch(e){if(version===loadVersion){count.textContent='Knowledge unavailable';list.textContent=e.message;}}
  }
  project.onchange=()=>{if(!project.value){referenceIds.clear();modal.querySelectorAll('[data-reference]').forEach(c=>c.checked=false);}load();};
  modal.querySelectorAll('[data-reference]').forEach(c=>c.onchange=()=>{c.checked?referenceIds.add(c.dataset.reference):referenceIds.delete(c.dataset.reference);load();});
  load();
}

export async function reviewMeetingUpdate({api,openDialog,proposal,onSave}) {
  const memories=await api(`/domains/${proposal.domain_id}/memories`);
  const targets=memories.map(m=>`<option value="${esc(m.id)}" ${m.id===proposal.target_id?'selected':''}>Replace: ${esc(m.title)} · v${m.version}</option>`).join('');
  const modal=openDialog('Review project update',`
    <div class="form-field"><label for="update-title">Title</label><input id="update-title" name="title" required maxlength="150" value="${esc(proposal.title)}"></div>
    <div class="form-field"><label for="update-content">Memory</label><textarea id="update-content" name="content" required maxlength="12000" rows="5">${esc(proposal.content)}</textarea></div>
    <div class="form-field"><label for="update-target">Save as</label><select id="update-target"><option value="">New memory</option>${targets}</select><p id="update-previous" class="muted"></p></div>
    <label class="project-choice"><input id="update-shareable" type="checkbox">Shareable in project meetings</label>
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
