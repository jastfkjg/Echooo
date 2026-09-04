// Pure presentation helpers shared by the workspace and its UI regression tests.
export const sessionStatus = (s, now=Date.now()/1000) => s.status==='active' && s.mode!=='private' && (s.expires_at==null || s.expires_at<=now)?'expired':s.status;

export function filterSessions(sessions, query, filter, domainName) {
  const needle=query.trim().toLocaleLowerCase();
  return sessions.filter(s=>(filter==='all'||(filter==='empty'?s.message_count===0:s.mode===filter)) &&
    [s.title,s.audience,...s.domain_ids.map(domainName)].join(' ').toLocaleLowerCase().includes(needle));
}

export function domainControl(s, {icon, esc, domainName}) {
  const names=s.domain_ids.map(domainName), privateChat=s.mode==='private';
  return `<button class="domain-control" data-action="${privateChat?'choose-domains':'context'}" aria-haspopup="dialog" aria-label="${privateChat?'Change domains':'View authorized domains'}: ${esc(names.join(', ')||'No memory')}">${icon('folder')}<strong>Domains</strong><span class="scope-separator" aria-hidden="true">·</span><span class="scope-names">${esc(names[0]||'No memory')}</span>${names.length>1?`<span class="scope-extra">+${names.length-1}</span>`:''}<svg class="scope-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg></button>`;
}

export function privateContextForm(domains, memories, initial, learning, {esc, icon}) {
  return `<p class="picker-intro">Choose the knowledge Echooo can use. Your chat stays private.</p>
    <fieldset class="domain-picker"><legend>Conversation domains</legend>
      ${domains.map(d=>`<label class="domain-option"><input type="checkbox" name="domains" value="${esc(d.id)}" ${initial.includes(d.id)?'checked':''}><i class="domain-dot ${esc(d.color)}"></i><span class="domain-option-copy"><strong>${esc(d.name)}</strong><small>${esc(d.description||'Personal knowledge and memories')}</small></span><span class="domain-memory-count">${memories.filter(m=>m.domain_id===d.id).length} memories</span></label>`).join('')}
      <label class="domain-option domainless-option"><input type="checkbox" id="without-memory" ${initial.length?'':'checked'}>${icon('chat')}<span class="domain-option-copy"><strong>Chat without memory</strong><small>No domains or personal knowledge are used.</small></span></label>
    </fieldset>
    <details class="picker-section" id="memory-access"><summary><span>Memory access</span><span id="memory-selection-count">No memories selected</span></summary><p class="dialog-help">Only checked memories can be read in this chat.</p><div id="private-fact-picker"></div></details>
    <details class="learning-section picker-section"><summary><span>Memory suggestions</span><span id="learning-summary">${learning?'On · review required':'Off'}</span></summary><label class="check"><input type="checkbox" name="allow_learning" ${learning?'checked':''}><span><strong>Suggest memories after the chat</strong><small>You review every suggestion before it is saved.</small></span></label><div class="form-field learning-destination"><label for="f-write">Send suggestions to</label><select name="write_domain_id" id="f-write"></select></div></details>
    <details class="picker-section advanced-options"><summary><span>Advanced settings</span><span>Conversation goal</span></summary><div class="form-field"><label for="f-goal">Conversation goal <small>Optional · do not include secrets</small></label><textarea id="f-goal" name="goal" rows="2" maxlength="2000" placeholder="What would you like to work on?"></textarea></div></details>
    <p class="picker-note">${icon('info')}<span>Starts a new chat with these permissions. Your current conversation stays in history.</span></p>`;
}

export function bindPrivateContext(modal, domains, memories, readIds, {esc, domainName}) {
  const $=s=>modal.querySelector(s), $$=s=>[...modal.querySelectorAll(s)];
  const selected=new Set(readIds), learning=$('input[name=allow_learning]'), writer=$('#f-write');
  let wantsLearning=learning.checked;
  function updateCount() {
    const n=$$('input[name=read_ids]:checked').length;
    $('#memory-selection-count').textContent=`${n} ${n===1?'memory':'memories'} selected`;
  }
  function updateLearning() {
    const ids=$$('input[name=domains]:checked').map(e=>e.value);
    learning.disabled=!ids.length;learning.checked=wantsLearning&&!!ids.length;
    $('#learning-summary').textContent=learning.checked?'On · review required':'Off';
    $('.learning-destination').hidden=!learning.checked;writer.disabled=!learning.checked;
  }
  function update() {
    const ids=$$('input[name=domains]:checked').map(e=>e.value), current=writer.value;
    $('#without-memory').checked=!ids.length;
    writer.innerHTML=domains.filter(d=>ids.includes(d.id)).map(d=>`<option value="${esc(d.id)}" ${d.id===current?'selected':''}>${esc(d.name)}</option>`).join('');
    const facts=memories.filter(m=>ids.includes(m.domain_id));
    $('#private-fact-picker').innerHTML=facts.length?facts.map(m=>`<label class="memory-option"><input type="checkbox" name="read_ids" value="${esc(m.id)}" ${selected.has(m.id)?'checked':''}><span><strong>${esc(m.title)}</strong><small>${esc(domainName(m.domain_id))} · ${esc(m.content.slice(0,110))}</small></span></label>`).join(''):'<p class="dialog-help picker-empty">No saved memories in this selection. You can still start a chat.</p>';
    $$('input[name=read_ids]').forEach(input=>input.onchange=()=>{if(input.checked)selected.add(input.value);else selected.delete(input.value);updateCount();});
    updateCount();updateLearning();
  }
  $$('input[name=domains]').forEach(input=>input.onchange=update);
  $('#without-memory').onchange=()=>{$$('input[name=domains]').forEach(input=>input.checked=false);update();};
  learning.onchange=()=>{wantsLearning=learning.checked;updateLearning();};
  update();
}
