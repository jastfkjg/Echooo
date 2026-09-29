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
  return renderAnswerTiming(trace?.timing)+(trace?(trace.calls||[]).map((call,i)=>llmView(call,i)+
    (i===0&&trace.search?step(`Search / retrieval${duration(trace.search.elapsed_ms??result.check?.search_ms)}`,
      pair(`<h4>Queries</h4>${text(trace.search.queries?.join('\n'))}`+fold('Search metadata',json({trigger:trace.search.trigger,started_at:trace.search.started_at})),
        `<p>${trace.search.result?.passages?.length??0} passages returned</p>`+
        fold('Retrieved passages',passagesView(trace.search.result?.passages))+
        (trace.calls[1]?.context?.retrieval?fold('Evidence sent to LLM 2',json(evidenceDiff(trace))):'')),trace.search):'')
    ).join('')+(trace.failure?section('Failure',trace.failure):''):'')+
    step('Final answer and validation',pair(text(result.event?.request),text(result.event?.response||'No answer')+fold('Validation',json(result.check))),{event:result.event,check:result.check});
}
export function renderAnswerTiming(timing){
  if(!timing)return '<p class="muted">Detailed timing was not recorded for this answer.</p>';
  const s=timing.stages||{},delta=(a,b)=>Number.isFinite(s[a])&&Number.isFinite(s[b])?s[b]-s[a]:null;
  const rows=[
    ['Question-end audio frame received → STT final',timing.input?.stt_finalization_ms],
    ['STT input frame duration',timing.input?.stt_frame_ms],
    ['STT audio backlog estimate',timing.input?.stt_audio_lag_ms],
    ['Follow-up classification LLM',timing.input?.turn_classification_ms],
    [timing.input?.follow_up_combined?'Final transcript → queued (includes LLM 1)':'Final transcript → queued (includes follow-up classification)',delta('stt_final_received','queued')],
    ['Queue',delta('queued','answer_started')],
    ['Context preparation',timing.input?.follow_up_combined?delta('follow_up_context_started','follow_up_context_finished'):delta('answer_started','generation_started')],
    [timing.input?.follow_up_combined?'LLM 1 (includes follow-up decision)':'LLM 1',delta('llm_1_started','llm_1_finished')],
    ['Retrieval',delta('retrieval_started','retrieval_finished')],
    ['LLM 2',delta('llm_2_started','llm_2_finished')],
    ['Answer validation',delta('generation_finished','answer_validated')],
    ['Waiting for the floor',delta('floor_wait_started','floor_wait_finished')],
    ['TTS first chunk',delta('tts_requested','tts_first_chunk')],
    ['TTS stream duration (includes backpressure)',delta('tts_requested','tts_finished')],
    ['First chunk → playback authorization',delta('tts_first_chunk','playback_authorized')],
    ['Playback authorization → first output report received',delta('playback_authorized','first_audio_report_received')],
    ['Browser offer → first output frame',timing.client?.offer_to_first_audio_ms],
    ['Question end → browser first output frame',timing.client?.question_to_first_audio_ms],
    ['Browser output latency estimate',timing.client?.output_latency_ms],
    ['Remote start → first output frame',timing.remote?.start_to_first_audio_ms],
  ];
  return `<section class="debug-step"><h2>Answer timing</h2><p>Server durations use one monotonic clock. Browser durations use the capture and playback audio clock. Output frames exclude physical speaker and meeting-network delay. STT finalization starts when the server receives the frame containing the last word; it excludes capture uplink and has frame-level precision. STT backlog is an estimate, not isolated service latency. Missing stages were not recorded or did not run; overlapping stages must not be added.</p><table><thead><tr><th scope="col">Stage</th><th scope="col">Time</th></tr></thead><tbody>${rows.map(([label,value])=>`<tr><th scope="row">${esc(label)}</th><td>${Number.isFinite(value)?`${value.toFixed(0)} ms`:'—'}</td></tr>`).join('')}</tbody></table>${fold('Timing data',json(timing))}</section>`;
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
