const esc = (value='') => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json = value => `<pre class="debug-json">${esc(JSON.stringify(value,null,2))}</pre>`;
const duration = ms => Number.isFinite(ms) ? ` · ${ms} ms` : '';
const section = (title,value) => `<details class="debug-step"><summary>${esc(title)}</summary>${json(value)}</details>`;
const text = value => `<pre class="debug-text">${esc(value ?? 'Not recorded')}</pre>`;
const fold = (title,body) => `<details class="debug-fold"><summary>${esc(title)}</summary>${body}</details>`;
const pair = (input,output) => `<div class="debug-io"><section aria-label="Input"><h3>Input</h3>${input}</section><section aria-label="Output"><h3>Output</h3>${output}</section></div>`;
const step = (title,body,raw) => `<details class="debug-step debug-trace-step" open><summary>${esc(title)}</summary>${body}${fold('Raw JSON',json(raw))}</details>`;
function contextView(context){
  if(!context || typeof context!=='object')return text(context);
  const {question,discussion,knowledge,retrieval,recent_questions,...other}=context;
  return (question?`<h4>Question</h4>${text(question)}`:'')+
    fold(`Recent discussion · ${discussion?.length??0} passages`,passagesView(discussion))+
    (retrieval?fold(`Retrieved evidence · ${retrieval.passages?.length??0} passages`,passagesView(retrieval.passages)):'')+
    (knowledge?.length?fold(`Project knowledge · ${knowledge.length}`,passagesView(knowledge)):'')+
    (recent_questions?.length?fold('Previous exchanges',json(recent_questions)):'')+
    fold('Context metadata',json(other));
}
function passagesView(passages){
  return passages?.length?passages.map((p,i)=>{
    if(Array.isArray(p.turns))return `<section class="debug-passage"><h4>Evidence block ${i+1}</h4>${passagesView(p.turns)}${fold('Recording',text(p.recording_id||'Meeting notes'))}</section>`;
    return `<article class="debug-passage"><h4>Passage ${i+1}${p.speaker?' · '+esc(p.speaker):''}</h4>${text(p.content)}${fold('Source details',json(Object.fromEntries(Object.entries(p).filter(([k])=>k!=='content'))))}</article>`;
  }).join(''):'<p class="muted">No passages.</p>';
}
function llmView(call,i){
  const messages=call.request?.messages;
  const input=messages?.length?messages.map(m=>{
    if(m.role==='system')return fold('System prompt',text(m.content));
    if(m.role==='user'){
      try{return contextView(JSON.parse(m.content));}catch{return fold('User message',text(m.content));}
    }
    return fold(m.role,text(m.content));
  }).join(''):fold('System prompt',text(call.system))+contextView(call.context);
  let result=call.result;
  if(!result&&call.response?.content){try{result=JSON.parse(call.response.content);}catch{}}
  const output=result?`<p class="debug-result">${esc(result.action||'Result')}${result.support?' · '+esc(result.support):''}</p>`+
    (result.reply?text(result.reply):'')+(result.queries?`<h4>Search queries</h4>${text(result.queries.join('\n'))}`:'')+
    (result.citations?fold(`Citations · ${result.citations.length}`,json(result.citations)):'')+
    fold('Parsed result',json(result)):text(call.response?.content||call.error_type||'No response recorded');
  const settings=call.request?Object.fromEntries(Object.entries(call.request).filter(([k])=>k!=='messages')):null;
  return step(`LLM ${i+1} · ${call.status}${duration(call.elapsed_ms)}`,
    pair(input+(settings?fold('Model settings',json(settings)):''),output+
      (call.response?fold('Raw model response',text(call.response.content)):'')+
      (call.error_type?`<p role="status">${esc(call.error_type)}</p>`:'')),call);
}
export function renderAnswerTrace(result){
  const trace=result.trace;
  return (trace?(trace.calls||[]).map((call,i)=>llmView(call,i)+
    (i===0&&trace.search?step(`Search / retrieval${duration(trace.search.elapsed_ms??result.check?.search_ms)}`,
      pair(`<h4>Queries</h4>${text(trace.search.queries?.join('\n'))}`+fold('Search metadata',json({trigger:trace.search.trigger,started_at:trace.search.started_at})),
        `<p>${trace.search.result?.passages?.length??0} passages returned</p>`+
        fold('Retrieved passages',passagesView(trace.search.result?.passages))+
        (trace.calls[1]?.context?.retrieval?fold('Evidence sent to LLM 2',json(evidenceDiff(trace))):'')),trace.search):'')
    ).join('')+(trace.failure?section('Failure',trace.failure):''):'')+
    step('Final answer and validation',pair(text(result.event?.request),text(result.event?.response||'No answer')+fold('Validation',json(result.check))),{event:result.event,check:result.check});
}
export function evidenceDiff(trace){
  const retrieved=trace?.search?.result?.passages||[];
  const sent=trace?.calls?.at(-1)?.context?.retrieval?.passages||[];
  return retrieved.map(p=>({id:p.id,offset:p.offset,recording_id:p.recording_id,score:p.score,selection:p.selection,
    sent:sent.some(s=>Array.isArray(s.turns)
      ?s.recording_id===p.recording_id&&s.turns.some(t=>t.source_ids?.includes(p.id)&&t.content.includes(p.content))
      :s.id===p.id&&s.offset===p.offset&&s.content===p.content),content:p.content}));
}
export async function showMeetingDebug({api,shell,isCurrent},id){
  const base=`/meetings/${encodeURIComponent(id)}`;
  let data=await api(`${base}/debug`);if(!isCurrent())return;
  shell(`<div class="heading"><div><a href="#meetings/${esc(id)}">← Back to meeting</a><h1>Meeting debug</h1><p>${esc(data.title)}</p></div><button class="btn" id="debug-refresh">Refresh</button></div>
    <p class="muted">Answer traces are saved. Live diagnostics retain up to 500 recent events per meeting in this server process and reset on restart.</p>
    <label for="debug-recording">Recording</label><select id="debug-recording"><option value="">All recordings</option>${data.recordings.map((r,i)=>`<option value="${esc(r.id)}">Recording ${i+1}</option>`).join('')}</select>
    <label for="debug-answer">Question</label><select id="debug-answer"></select>
    <p id="debug-status" role="status"></p><div id="debug-detail"></div>
    <h2>Live pipeline</h2><p class="muted">Includes nearby activity; these events are not all caused by the selected question.</p><div id="debug-runtime"></div>`,'Meetings');
  const $=s=>document.querySelector(s);
  let revision=0;
  const runtime=()=>{
    const rid=$('#debug-recording').value;
    const events=data.runtime.filter(e=>!rid||e.recording_id===rid);
    $('#debug-runtime').innerHTML=events.length?events.slice().reverse().map(e=>section(`${new Date(e.at*1000).toLocaleTimeString()} · ${e.stage}${e.data.decision?' · '+e.data.decision:''}`,e)).join(''):'<p>No live diagnostics retained.</p>';
  };
  async function detail(){
    const seq=++revision,eid=$('#debug-answer').value;
    $('#debug-detail').innerHTML='';$('#debug-status').textContent='';runtime();if(!eid)return;
    $('#debug-status').textContent='Loading trace…';
    try{
      const result=await api(`${base}/debug/${encodeURIComponent(eid)}`);
      if(!isCurrent()||seq!==revision)return;
      const trace=result.trace;
      $('#debug-status').textContent=trace?'':'No saved trace for this answer.';
      $('#debug-detail').innerHTML=`<h2>Answer trace</h2><a href="/api${base}/debug/${encodeURIComponent(eid)}" download="answer-${esc(eid)}.json">Export this answer</a>`+
        renderAnswerTrace(result);
    }catch(e){if(isCurrent()&&seq===revision)$('#debug-status').textContent=e.message;}
  }
  function choices(){
    const selected=$('#debug-answer').value;
    const rid=$('#debug-recording').value;
    const events=data.events.filter(e=>!rid||e.connection_id===`browser-recording:${rid}`||data.runtime.some(r=>r.recording_id===rid&&(r.event_id===e.id||r.data.answer_id===e.id)));
    $('#debug-answer').innerHTML='<option value="">Select a question</option>'+events.map(e=>`<option value="${esc(e.id)}">${esc(new Date(e.created_at*1000).toLocaleTimeString()+' · '+e.request.slice(0,140))}</option>`).join('');
    if(events.some(e=>e.id===selected))$('#debug-answer').value=selected;
    detail();
  }
  $('#debug-recording').onchange=choices;$('#debug-answer').onchange=detail;
  $('#debug-refresh').onclick=async()=>{
    $('#debug-refresh').disabled=true;
    try{const result=await api(`${base}/debug`);if(!isCurrent())return;data=result;choices();$('#debug-status').textContent='Updated.';}
    catch(e){if(isCurrent())$('#debug-status').textContent=e.message;}
    finally{if(isCurrent())$('#debug-refresh').disabled=false;}
  };
  choices();
}
