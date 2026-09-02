import { Voice } from './voice.js';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  wave:'M3 10v4m5-9v14m5-16v18m5-15v12m4-8v4',
  grid:'M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z',
  chat:'M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0Z',
  check:'m5 12 4 4L19 6',plus:'M12 5v14M5 12h14',
  lock:'M6 10h12v11H6zm3 0V6a3 3 0 0 1 6 0v4',
  file:'M14 2H5v20h14V7Zm0 0v5h5M8 12h8M8 16h6',
  edit:'m4 16-1 5 5-1L20 7l-4-4ZM14 5l5 5',
  trash:'M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7',
  close:'m6 6 12 12M6 18 18 6',arrow:'M5 12h14m-6-6 6 6-6 6',
  shield:'m12 2 8 3v6c0 5-8 11-8 11S4 16 4 11V5Zm-4 9 3 3 5-6',
  settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-6v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
  mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0Zm-4 7a7 7 0 0 0 14 0M12 19v3m-4 0h8',
  review:'M9 5H5v17h14V5h-4M9 2h6v5H9Zm-1 13 3 3 5-6',
  menu:'M4 6h16M4 12h16M4 18h16',history:'M3 12a9 9 0 1 0 3-7L3 8m0-5v5h5m4-2v6l4 3',
  upload:'M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6',
  logout:'M9 4H3v16h6m4-4 4-4-4-4m-5 4h13',info:'M12 11v6m0-10v.1M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
  link:'m9 15 6-6M8 16l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0 12a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-1 1',
  folder:'M3 5h6l2 3h10v13H3Z',stop:'M6 6h12v12H6Z',download:'M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
const brand = `<a class="brand" href="/" aria-label="Echooo workspace">${icon('wave')}<span>echooo<span class="muted">.</span></span></a>`;
const dt = t => new Date(t * 1000).toLocaleString('en-US', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const countLabel = (n, singular, plural=singular+'s') => `${n.toLocaleString('en-US')} ${n===1?singular:plural}`;
const roleName = {assistant:'Echooo',guest:'Guest',owner:'You',owner_approved:'Owner approved',private_note:'Private note'};
const statusName = s => ({active:'Active',ended:'Ended',revoked:'Revoked',expired:'Expired'}[s.status] || s.status) + (s.status==='active' && s.expires_at < Date.now()/1000 ? ' · Expired' : '');
const state = {user:null,config:{},domains:[],sessions:[],proposals:[],memories:[],sources:[],route:[],session:null,guest:false,filter:'',socket:null,voice:null};
let toastTimer, poll, navigation = 0;

async function api(path, method='GET', data) {
  const options = {method, credentials:'same-origin', headers:{}};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(data); }
  const response = await fetch('/api'+path, options);
  const result = await response.json();
  if (!response.ok) {
    const detail = typeof result.detail==='string' ? result.detail : (result.detail||[]).map(x=>`${x.loc?.slice(1).join('.')}: ${x.msg}`).join('\n');
    throw new Error(detail || 'The operation could not be completed. Please try again.');
  }
  return result;
}
function toast(message) {
  const el=$('#toast'); el.textContent=message; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove('show'),5000);
}
function field(name,label,value='',type='text',extra='') {
  return `<div class="form-field"><label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}></div>`;
}
function area(name,label,value='',extra='') {
  return `<div class="form-field"><label for="f-${name}">${label}</label><textarea id="f-${name}" name="${name}" ${extra}>${esc(value)}</textarea></div>`;
}
function openDialog(title,body,submit,label='Save') {
  const modal=$('#modal');
  modal.innerHTML=`<form id="dialog-form"><div class="dialog-head"><h2 id="dialog-title">${esc(title)}</h2><button class="icon-btn" type="button" data-close aria-label="Close">${icon('close')}</button></div><div class="dialog-body"><div class="form-error" role="alert"></div>${body}</div><div class="dialog-footer"><button type="button" class="btn subtle" data-close>Cancel</button><button type="submit" class="btn primary">${esc(label)}</button></div></form>`;
  $$('[data-close]',modal).forEach(b=>b.onclick=()=>modal.close());
  $('#dialog-form').onsubmit=async e=>{
    e.preventDefault(); const button=$('button[type=submit]',modal), error=$('.form-error',modal);
    button.disabled=true; error.textContent='';
    try { await submit(new FormData(e.target), e.target); modal.close(); }
    catch(err){ error.textContent=err.message; error.scrollIntoView({block:'nearest'}); }
    finally {button.disabled=false;}
  };
  modal.showModal();
  $('input:not([type=checkbox]),textarea,select',modal)?.focus();
  return modal;
}
function empty(title,description,button='',symbol='folder') {
  return `<div class="empty">${icon(symbol).replace('<svg ','<svg class="empty-art" ')}<h2>${esc(title)}</h2><p>${esc(description)}</p>${button}</div>`;
}
async function refreshBase() {
  [state.domains,state.sessions,state.proposals]=await Promise.all([api('/domains'),api('/sessions'),api('/proposals')]);
}
const domainName=id=>state.domains.find(d=>d.id===id)?.name || 'Removed domain';
function navigate(hash) { if(location.hash==='#'+hash) renderRoute(); else location.hash=hash; }
function shell(body,crumb='My domains') {
  const pending=state.proposals.filter(p=>p.status==='pending').length;
  $('#app').innerHTML=`<div class="shell"><aside class="sidebar">${brand}<button class="btn primary" data-action="quick-chat">${icon('chat')}Talk with Echooo</button><a class="navlink ${!state.route[0]?'active':''}" href="#">${icon('grid')}<span>My domains</span></a><a class="navlink ${state.route[0]==='sessions'?'active':''}" href="#sessions">${icon('chat')}<span>Conversations</span><span class="count">${state.sessions.length||''}</span></a><a class="navlink ${state.route[0]==='review'?'active':''}" href="#review">${icon('review')}<span>Review</span>${pending?`<span class="count">${pending}</span>`:''}</a><div class="label">Domains · ${state.domains.length}</div><nav class="domain-nav" aria-label="Domains">${state.domains.map(d=>`<a class="navlink ${state.route[1]===d.id?'active':''}" href="#domain/${d.id}/memories"><i class="domain-dot ${esc(d.color)}"></i><span class="name">${esc(d.name)}</span><span class="count">${d.memory_count}</span></a>`).join('')}</nav><button class="navlink" data-action="new-domain">${icon('plus')}<span>Add domain</span></button><div class="side-bottom"><a class="navlink ${state.route[0]==='settings'?'active':''}" href="#settings">${icon('settings')}<span>Workspace settings</span></a><div class="profile"><span class="avatar">${esc(state.user.name.slice(0,1).toUpperCase())}</span><div><strong>${esc(state.user.name)}</strong><small>Private workspace</small></div></div></div></aside><main class="main" id="main"><header class="topbar"><div class="path"><button class="icon-btn mobile-menu" data-action="menu" aria-label="Open navigation">${icon('menu')}</button><span>Personal workspace</span><span>/</span><strong>${esc(crumb)}</strong></div><span class="status">Domain isolation enabled</span></header><div class="workspace">${body}</div></main></div>`;
  bindActions();
}
const demoBanner=()=>state.config.demo?`<div class="banner">${icon('info')}<span>Local demo: replies use authorized memories. Connect a live model for natural conversations with the same data and permission controls.</span></div>`:'';

async function renderRoute() {
  const run=++navigation;
  disconnect();
  state.route=location.hash.slice(1).split('/').filter(Boolean); state.filter=''; state.session=null;
  try {
    await refreshBase(); if(run!==navigation)return;
    const [page,id,tab]=state.route;
    if(page==='domain') {
      const d=state.domains.find(d=>d.id===id); if(!d){navigate('');return;}
      [state.memories,state.sources]=await Promise.all([api(`/domains/${id}/memories`),api(`/domains/${id}/sources`)]);
      if(run!==navigation)return;
      renderDomain(d,tab||'memories');
    } else if(page==='sessions' && id) {
      state.session=await api(`/sessions/${id}`); if(run!==navigation)return;
      renderSession();
    } else if(page==='sessions') renderSessions();
    else if(page==='review') renderReview();
    else if(page==='settings') renderSettings();
    else renderHome();
  } catch(err){shell(empty('Unable to open this page',err.message,`<button class="btn" data-action="refresh">Reload</button>`),'Unable to load');}
}
function renderHome() {
  shell(`<div class="heading"><div><p class="eyebrow">Your knowledge, your boundaries</p><h1>My domains</h1><p>Organize memories around your life and work. Choose what your assistant can use for each delegation.</p></div><div class="actions"><button class="btn primary" data-action="quick-chat">${icon('chat')}Talk with Echooo</button><button class="btn" data-action="new-domain">${icon('plus')}Add domain</button></div></div>${demoBanner()}${state.domains.length?`<div class="grid-summary"><div><small>Domains</small><strong>${state.domains.length}</strong></div><div><small>Confirmed memories</small><strong>${state.domains.reduce((n,d)=>n+d.memory_count,0)}</strong></div><div><small>Awaiting review</small><strong>${state.proposals.filter(p=>p.status==='pending').length}</strong></div></div><div class="list-head"><h3>Domains</h3><small>Memories are not automatically shared across domains</small></div>${state.domains.map(d=>`<a class="session-row" href="#domain/${d.id}/memories"><div><h3><i class="domain-dot ${esc(d.color)}"></i> ${esc(d.name)}</h3><p class="muted">${esc(d.description||'No description yet')}</p><div class="meta"><span>${countLabel(d.memory_count,'memory','memories')}</span><span>${d.pending_count} pending review</span></div></div>${icon('arrow')}</a>`).join('')}`:empty('Your domains will appear here','You can start chatting now. Add a domain whenever you want the assistant to use personal memories.',`<button class="btn primary" data-action="new-domain">${icon('plus')}Create your first domain</button>`)} `);
}
function renderDomain(d,tab) {
  const body=`<div class="heading"><div><p class="eyebrow">Knowledge space</p><h1>${esc(d.name)}</h1><p>${esc(d.description||'Organize sources, confirm memories, and choose permissions for each conversation.')}</p></div><div class="actions"><button class="btn" data-action="new-private">${icon('chat')}Private chat</button><button class="btn primary" data-action="new-delegate">${icon('arrow')}Delegate</button><button class="icon-btn" data-action="edit-domain" aria-label="Manage domain">${icon('settings')}</button></div></div><nav class="tabs" aria-label="Domain content"><a class="${tab==='memories'?'active':''}" href="#domain/${d.id}/memories">Confirmed memories <small>${state.memories.length}</small></a><a class="${tab==='sources'?'active':''}" href="#domain/${d.id}/sources">Sources <small>${state.sources.length}</small></a></nav>${tab==='sources'?`<div class="list-head"><small>Sources are private. Extracted memories must be reviewed before use.</small><div class="actions"><button class="btn" data-action="upload">${icon('upload')}Upload file</button><button class="btn primary" data-action="new-source">${icon('plus')}Paste text</button></div></div><div id="source-list">${sourceList()}</div>`:`<div class="list-head"><input class="search" id="memory-search" aria-label="Search domain memories" placeholder="Search memories in this domain…"><button class="btn primary" data-action="new-memory">${icon('plus')}Add memory</button></div><div id="memory-list">${memoryList()}</div>`}`;
  shell(body,d.name);
  if($('#memory-search')) $('#memory-search').oninput=e=>{state.filter=e.target.value;$('#memory-list').innerHTML=memoryList();bindActions($('#memory-list'));};
}
function memoryList() {
  const filtered=state.memories.filter(m=>(m.title+m.content).toLowerCase().includes(state.filter.toLowerCase()));
  if(!filtered.length)return empty(state.memories.length?'No matching memories':'No memories yet',state.memories.length?'Try a different search term.':'Add confirmed information or extract it from sources. New memories are private by default.','', 'file');
  return filtered.map(m=>`<article class="memory-row"><span class="row-symbol">${icon(m.visibility==='private'?'lock':'file')}</span><div><h3>${esc(m.title)}</h3><div class="excerpt">${esc(m.content)}</div><div class="meta"><span class="tag ${m.visibility==='shareable'?'green':''}">${icon(m.visibility==='private'?'lock':'shield')}${m.visibility==='private'?'Private':'Shareable'}</span>${m.audiences.length?`<span>Audience: ${esc(m.audiences.join(', '))}</span>`:''}<span>v${m.version}</span><span>${dt(m.updated_at)}</span>${m.expires_at?`<span class="${m.expires_at<Date.now()/1000?'tag warn':''}">${m.expires_at<Date.now()/1000?'Expired':'Expires at '+dt(m.expires_at)}</span>`:''}</div></div><div class="row-actions"><button class="icon-btn" data-action="edit-memory" data-id="${m.id}" aria-label="Edit ${esc(m.title)}">${icon('edit')}</button><button class="icon-btn" data-action="versions" data-id="${m.id}" aria-label="View versions and provenance">${icon('history')}</button></div></article>`).join('');
}
function sourceList() {
  if(!state.sources.length)return empty('Add sources to this domain','Upload text, Markdown, PDF, DOCX, CSV, or JSON. Guests cannot access raw sources.','', 'upload');
  return state.sources.map(s=>`<article class="memory-row"><span class="row-symbol">${icon('file')}</span><div><h3>${esc(s.title)}</h3><p class="excerpt">${esc(s.content.slice(0,180))}${s.content.length>180?'…':''}</p><div class="meta"><span class="tag">Sources · Private</span><span>${s.content.length.toLocaleString('en-US')} characters</span><span>${dt(s.created_at)}</span></div></div><div class="row-actions"><button class="btn" data-action="extract" data-id="${s.id}">Extract memories</button><button class="icon-btn" data-action="delete-source" data-id="${s.id}" aria-label="Delete source">${icon('trash')}</button></div></article>`).join('');
}
function renderSessions() {
  shell(`<div class="heading"><div><p class="eyebrow">Delegated conversations</p><h1>Conversations</h1><p>Each conversation has its own permissions. Review the transcript and proposed memories afterward.</p></div><div class="actions"><button class="btn primary" data-action="quick-chat">${icon('chat')}Talk with Echooo</button><button class="btn" data-action="new-delegate">${icon('plus')}Delegate</button></div></div>${demoBanner()}${state.sessions.length?state.sessions.map(s=>`<a class="session-row" href="#sessions/${s.id}"><div><h3>${esc(s.title)}</h3><div class="meta"><span>${s.mode==='private'?'Private conversation':esc(s.audience)}</span><span>${esc(s.domain_ids.map(domainName).join(' / ')||'General chat')}</span><span>${dt(s.created_at)}</span></div></div><span class="tag ${s.status==='active'?'green':''}">${esc(statusName(s))}</span></a>`).join(''):empty('No conversations yet','Start a private chat immediately, or create a separately authorized delegation.','', 'chat')}`,'Conversations');
}
function renderReview() {
  const pending=state.proposals.filter(p=>p.status==='pending');
  shell(`<div class="heading"><div><p class="eyebrow">Memory review</p><h1>Review <span class="muted">${pending.length}</span></h1><p>Check the evidence, refine the wording, and decide what to remember. New memories are private by default.</p></div></div>${pending.length?pending.map(p=>`<article class="review-row"><div class="review-header"><div><span class="tag">${esc(domainName(p.domain_id))}</span><h3>${esc(p.title)}</h3></div><div class="actions"><button class="btn subtle" data-action="reject-proposal" data-id="${p.id}">Dismiss</button><button class="btn primary" data-action="review-proposal" data-id="${p.id}">Review and save ${icon('arrow')}</button></div></div><p>${esc(p.content)}</p><details><summary>View evidence · ${countLabel(p.evidence.length,'item')}</summary>${p.evidence.map(e=>`<div class="evidence"><strong>${esc(e.speaker||'Imported source')}</strong>: ${esc(e.content)}</div>`).join('')}</details><small>${p.session_id?'From a conversation':'Extracted from a source'} · ${dt(p.created_at)} · Not yet used in replies</small></article>`).join(''):empty('No updates to review','Import sources or finish a conversation to see proposed memories here.','', 'check')}<p class="muted"><small>${countLabel(state.proposals.length-pending.length,'update')} processed. Another person&#39;s opinion does not become your decision.</small></p>`,'Review');
}
function renderSettings() {
  shell(`<div class="heading"><div><p class="eyebrow">Workspace</p><h1>Workspace settings</h1><p>View service status and manage your data and sign-in.</p></div></div>${demoBanner()}<section class="settings-section"><div><h3>Model connections</h3><p>STT: ${esc(state.config.providers?.stt)} · LLM: ${esc(state.config.providers?.llm)} · TTS: ${esc(state.config.providers?.tts)}</p><p>Services are configured on the server. API keys stay server-side.</p></div><span class="tag">${state.config.demo?'Local demo':'Configured services'}</span></section><section class="settings-section"><div><h3>Persistent storage</h3><p>${state.config.database==='sqlite'?'Local SQLite':'PostgreSQL · Row-level security'} · Confirmed memories retain versions and provenance.</p></div></section><section class="settings-section"><div><h3>Export my data</h3><p>Includes domains, sources, memories, conversations, and review records. Store the export privately.</p></div><a class="btn" href="/api/export" download>${icon('download')}Export JSON</a></section><section class="settings-section"><div><h3>Signed in as: ${esc(state.user.name)}</h3><p>Signing out invalidates your current credential.</p></div><button class="btn" data-action="logout">${icon('logout')}Sign out</button></section>`,'Workspace settings');
}
function messageHTML(m) {
  return `<article class="message ${esc(m.role)}" data-message="${m.id}"><div class="speaker"><strong>${esc(roleName[m.role]||m.role)}</strong><time>${dt(m.created_at)}</time>${m.role==='private_note'?'<span>Only you</span>':''}</div><div class="text">${esc(m.content)}</div>${m.citations?.length?`<div class="citations">Based on ${countLabel(m.citations.length,'authorized memory','authorized memories')}</div>`:''}</article>`;
}
function conversation(s, canSpeak) {
  return `<section class="conversation" aria-label="Conversation"><div class="conversation-top"><span>${canSpeak?'Talk with Echooo':'Live transcript · Private supervision'}</span><span class="status" id="room-state">${esc(statusName(s))}</span></div><div class="transcript" id="transcript" role="log" aria-label="Transcript" aria-live="polite">${s.messages.length?s.messages.map(messageHTML).join(''):empty('Ready to talk',canSpeak?'Type a message or turn on your microphone.':'Create an invitation and share it with your guest. Their conversation will appear here.','', 'wave')}</div><div class="composer">${s.status==='active'?`<form id="message-form"><textarea id="message-input" aria-label="${canSpeak?'Message':'Private note'}" placeholder="${canSpeak?'Type your message…':'Write a private note. It will not be sent to the guest…'}" maxlength="6000" required></textarea><button class="btn primary" type="submit">${canSpeak?'Send':'Save note'} ${icon('arrow')}</button></form><div class="foot"><span id="partial" class="muted"><small>${canSpeak?(state.guest?'Personal facts come from this authorization. New decisions require owner approval.':s.domain_ids.length?`Using ${esc(s.domain_ids.map(domainName).join(', '))} · ${s.allow_learning?'Memory updates proposed after chat':'Automatic memory updates off'}`:'General chat · No personal memories loaded · Automatic memory updates off'):'Notes are excluded from public replies and memory extraction.'}</small></span>${canSpeak?`<div class="actions"><label><input type="checkbox" id="speak-toggle">Read replies aloud</label><button class="icon-btn" data-action="mic" aria-label="Turn on microphone">${icon('mic')}</button><button class="icon-btn" data-action="interrupt" aria-label="Interrupt reply">${icon('stop')}</button></div>`:''}</div>`:`<p class="muted"><small>This conversation has ended. Start a new authorization to continue.</small></p>`}</div></section>`;
}
function inspector(s) {
  if(s.mode==='private')return `<h3>${icon('shield')} Chat context</h3><dl><dt>Active domains</dt><dd>${esc(s.domain_ids.map(domainName).join(', ')||'None · General chat')}</dd><dt>Personal memories</dt><dd>${s.read_ids.length?countLabel(s.read_ids.length,'selected memory','selected memories'):s.domain_ids.length?'No confirmed memories selected yet':'Not accessed'}</dd><dt>Automatic proposals</dt><dd>${s.allow_learning?esc(domainName(s.write_domain_id))+' · Review before saving':'Off'}</dd><dt>Expires at</dt><dd>${dt(s.expires_at)}</dd></dl><hr><p class="dialog-help">${s.domain_ids.length?'Only selected memories are available here.':'Ask general questions or share something in this conversation. Personal memories are not loaded.'}</p><p class="dialog-help">Use Save memory to choose what to keep and where it belongs.</p>`;
  const pending=s.actions.filter(a=>a.status==='pending');
  return `<h3>${icon('shield')} Authorization</h3><dl><dt>Audience</dt><dd>${esc(s.audience||'Private')}</dd><dt>Readable domains</dt><dd>${esc(s.domain_ids.map(domainName).join(', '))}</dd><dt>Authorized memories</dt><dd>${s.read_ids.length} readable · ${s.disclose_ids.length} disclosable</dd><dt>Save memories to</dt><dd>${s.allow_learning?esc(domainName(s.write_domain_id))+' · Save after review':'Do not extract memories'}</dd><dt>Action permissions</dt><dd>${s.action_policy==='ask'?'New commitments require owner approval':'Information only'}</dd><dt>Expires at</dt><dd>${dt(s.expires_at)}</dd></dl>${s.goal?`<hr><h3>Conversation goal</h3><p class="muted pre">${esc(s.goal)}</p>`:''}<hr><h3>Needs your approval ${pending.length?`· ${pending.length}`:''}</h3>${pending.length?pending.map(a=>`<div class="approval"><small>Guest request</small><p>${esc(a.request)}</p><button class="btn primary" data-action="decide" data-id="${a.id}" ${s.status!=='active'?'disabled':''}>Review request</button></div>`).join(''):'<small>No requests need your decision right now.</small>'}`;
}
function renderSession() {
  const s=state.session,active=s.status==='active' && s.expires_at>Date.now()/1000;
  if(!active && s.status==='active')s.status='expired';
  shell(`<div class="heading"><div><p class="eyebrow">${s.mode==='private'?'Private conversation':'Scoped delegation'}</p><h1 id="session-title">${esc(s.title)}</h1><p>${s.mode==='private'?(s.domain_ids.length?`A private chat using memories from ${esc(s.domain_ids.map(domainName).join(', '))}.`:'General chat. No personal memories are loaded or updated automatically.'):'Your assistant identifies itself as AI. Follow the conversation, review requests, and revoke access at any time.'}</p></div><div class="actions">${s.mode==='private'?`<button class="btn" data-action="choose-domains">${icon('folder')}Choose domains</button><button class="btn" data-action="save-chat-memory">${icon('file')}Save memory</button><button class="btn" data-action="new-delegate">${icon('arrow')}Delegate</button>`:''}${active?`${s.mode==='delegate'?'<button class="btn" data-action="invite">'+icon('link')+'Create invitation</button>':''}<button class="btn" data-action="end-session">End and review</button><button class="icon-btn" data-action="revoke-session" aria-label="Revoke access now">${icon('shield')}</button>`:''}</div></div>${demoBanner()}<div class="room-layout">${conversation(s,s.mode==='private')}<aside class="inspector" id="inspector">${inspector(s)}</aside></div>${!active?summaryHTML(s):''}`,'Conversations');
  bindConversation(s.mode==='private');
  if(active&&s.mode==='private')$('#message-input')?.focus();
  if(active){ connect(s.id,false); poll=setInterval(refreshSession,3500); }
}
function summaryHTML(s) {
  return `<section class="review-row"><div class="review-header"><div><h2>Conversation review</h2><p>${countLabel(s.summary.checked_replies||0,'checked reply','checked replies')} · ${countLabel(s.proposals.length,'memory proposal')}</p></div><div class="actions">${s.status==='ended'&&s.allow_learning?'<button class="btn" data-action="retry-learning">Extract memories</button>':''}<a class="btn primary" href="#review">Review updates ${icon('arrow')}</a></div></div><details><summary>Participant statements and approved decisions</summary>${(s.summary.statements||[]).map(x=>`<div class="evidence"><strong>${esc(roleName[x.speaker]||x.speaker)}</strong>: ${esc(x.text)}</div>`).join('')||'<p class="muted">No statements recorded.</p>'}</details><details><summary>Checks and authorization log · ${s.audit.length}</summary><ul class="detail-list">${s.audit.map(a=>`<li>${dt(a.created_at)} · ${esc(a.kind)} ${a.detail.kind_result?'· '+esc(a.detail.kind_result):''}</li>`).join('')}</ul></details></section>`;
}
async function refreshSession() {
  if(!state.session||state.guest)return;
  try{
    const sid=state.session.id;
    const s=await api(`/sessions/${sid}`);if(state.session?.id!==sid)return;state.session=s;
    if(s.status!=='active'||s.expires_at<Date.now()/1000){disconnect();renderSession();return;}
    if($('#session-title'))$('#session-title').textContent=s.title;
    if($('#inspector')){$('#inspector').innerHTML=inspector(s);bindActions($('#inspector'));}
    s.messages.forEach(appendMessage);
  }catch(err){disconnect();toast(err.message);}
}
function appendMessage(m) {
  if(state.session&&!state.session.messages.some(x=>x.id===m.id))state.session.messages.push(m);
  const box=$('#transcript');if(!box||$(`[data-message="${m.id}"]`,box))return;
  $('.empty',box)?.remove();box.insertAdjacentHTML('beforeend',messageHTML(m));box.scrollTop=box.scrollHeight;
}
function bindConversation(canSpeak) {
  const form=$('#message-form');if(!form)return;
  form.onsubmit=async e=>{
    e.preventDefault();const input=$('#message-input'),value=input.value.trim();if(!value)return;
    const button=$('button[type=submit]',form);button.disabled=true;
    try{
      if(!canSpeak){const m=await api(`/sessions/${state.session.id}/notes`,'POST',{content:value});appendMessage(m);}
      else if(state.socket?.readyState===WebSocket.OPEN)state.socket.send(JSON.stringify({type:'input.text',content:value}));
      else{
        const result=await api(`${state.guest?'/guest':''}/sessions/${state.session.id}/messages`,'POST',{content:value});
        appendMessage(result.user);appendMessage(result.assistant);state.voice?.speak(result.assistant.content);
      }
      input.value='';
    }catch(err){toast(err.message);}finally{button.disabled=false;input.focus();}
  };
  $('#message-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit();}};
  if($('#speak-toggle'))$('#speak-toggle').onchange=e=>{state.voice.enabled=e.target.checked;if(!e.target.checked)state.voice.stopPlayback();};
}
function connect(sid,guest) {
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/sessions/${sid}?role=${guest?'guest':'owner'}`);
  ws.binaryType='arraybuffer';state.socket=ws;const voice=new Voice(ws,toast);state.voice=voice;
  ws.onmessage=async e=>{
    if(state.socket!==ws)return;
    if(e.data instanceof ArrayBuffer){await state.voice?.pcm(e.data);return;}
    const m=JSON.parse(e.data);
    if(m.type==='message')appendMessage(m.message);
    if(m.type==='speech.checked')state.voice?.speak(m.content);
    if(m.type==='playback.stop')state.voice?.stopPlayback();
    if(m.type==='audio.start')await state.voice?.preparePlayback(m.sample_rate);
    if(m.type==='audio.ready')await voice.capture(m.sample_rate);
    if(m.type==='audio.error'){voice.stopMic();toast(m.message);$('[data-action=mic]')?.classList.remove('recording');}
    if(m.type==='transcript.partial'&&$('#partial'))$('#partial').textContent=m.content;
    if(m.type==='session.state'&&$('#room-state'))$('#room-state').textContent=({thinking:'Checking reply',listening:'Listening',speaking:'Replying'}[m.state]||m.state)+(m.reply_ms?` · ${(m.reply_ms/1000).toFixed(1)}s`:'');
    if(m.type==='session.ready'&&$('#room-state'))$('#room-state').textContent='Connected';
    if(m.type==='error'){toast(m.message);$('[data-action=mic]')?.classList.remove('recording');}
    if(m.type==='session.closed'){state.voice?.close();toast(m.message);if($('#room-state'))$('#room-state').textContent='Authorization ended';if(state.guest){state.session.status='ended';renderGuest();}else refreshSession();}
  };
  ws.onclose=()=>{voice.close();if(state.socket===ws&&$('#room-state'))$('#room-state').textContent='Disconnected';};
  ws.onerror=()=>toast('The live connection is unavailable. You can still send text messages.');
}
function disconnect() {clearInterval(poll);poll=null;state.voice?.close();state.voice=null;if(state.socket){state.socket.onmessage=null;state.socket.onerror=null;state.socket.onclose=null;state.socket.close();state.socket=null;}}

function domainDialog(edit=false) {
  const d=edit?state.domains.find(x=>x.id===state.route[1]):null;
  const modal=openDialog(edit?'Manage domain':'Add domain',field('name','Domain name',d?.name||'','text','required maxlength="60" placeholder="Choose a name, such as Product research or Music…"')+area('description','Description',d?.description||'','maxlength="1000" placeholder="What information belongs in this domain?"')+`<div class="form-field"><label for="f-color">Label color</label><select name="color" id="f-color">${[['sage','Sage'],['blue','Blue'],['amber','Amber'],['violet','Violet'],['rose','Rose'],['slate','Slate']].map(([v,n])=>`<option value="${v}" ${d?.color===v?'selected':''}>${n}</option>`).join('')}</select></div>${edit?'<p class="dialog-help">Editing this domain revokes active conversations using it so outdated authorizations cannot continue.</p><button type="button" class="btn danger" id="delete-domain">Delete this domain</button>':''}`,async fd=>{
    const result=await api(edit?`/domains/${d.id}`:'/domains',edit?'PUT':'POST',Object.fromEntries(fd));
    toast(edit?'Domain updated. Related conversation access has been revoked.':'Domain created.');navigate(`domain/${result.id}/memories`);
  },edit?'Save changes':'Create domain');
  if(edit)$('#delete-domain',modal).onclick=()=>{
    modal.close();openDialog('Delete domain',`<p class="dialog-help">Delete sources, memories, versions, and related conversations for “${esc(d.name)}” and stop active conversations. Derived memories may also be removed from other domains. This cannot be undone.</p>`+field('confirm','Type the domain name to confirm','','text','required'),async fd=>{
      if(fd.get('confirm')!==d.name)throw new Error('The name does not match.');
      await api(`/domains/${d.id}`,'DELETE');toast('Domain and related data deleted.');navigate('');
    },'Confirm deletion');
  };
}
function memoryFields(m={}) {
  const exp=m.expires_at?new Date(m.expires_at*1000-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16):'';
  return field('title','Memory title',m.title||'','text','required maxlength="150"')+area('content','Confirmed information',m.content||'','required maxlength="12000"')+`<div class="two-col"><div class="form-field"><label for="f-visibility">Disclosure</label><select name="visibility" id="f-visibility"><option value="private" ${m.visibility!=='shareable'?'selected':''}>Private</option><option value="shareable" ${m.visibility==='shareable'?'selected':''}>May be disclosed in authorized conversations</option></select></div>${field('expires_at','Expires at (optional)',exp,'datetime-local')}</div>`+field('audiences','Allowed audiences (optional)',(m.audiences||[]).join(', '),'text','placeholder="Comma-separated, e.g. Client, Team. Leave blank to decide per conversation."')+'<p class="dialog-help">Marking a memory as shareable does not disclose it automatically. You must still select it for each delegation.</p>';
}
function memoryData(fd) {
  return {title:fd.get('title'),content:fd.get('content'),visibility:fd.get('visibility'),
    audiences:fd.get('audiences').split(/[,，]/).map(x=>x.trim()).filter(Boolean),
    expires_at:fd.get('expires_at')?new Date(fd.get('expires_at')).getTime()/1000:null};
}
function memoryDialog(mid) {
  const m=state.memories.find(x=>x.id===mid);
  const modal=openDialog(m?'Edit memory':'Add memory',memoryFields(m)+(m?'<p class="dialog-help">Editing this memory revokes conversations authorized to use it.</p><button type="button" class="btn danger" id="delete-memory">Delete memory</button>':''),async fd=>{
    const data=memoryData(fd);if(m)data.expected_version=m.version;
    await api(m?`/memories/${m.id}`:`/domains/${state.route[1]}/memories`,m?'PUT':'POST',data);
    toast(m?'Memory updated.':'Memory saved.');await renderRoute();
  });
  if(m)$('#delete-memory',modal).onclick=()=>{modal.close();openDialog('Delete memory','<p class="dialog-help">This also deletes its versions and conversations that used it, and stops related active conversations.</p>',async()=>{await api(`/memories/${m.id}`,'DELETE');toast('Memory deleted.');await renderRoute();},'Delete memory');};
}
async function versionsDialog(mid) {
  const m=state.memories.find(x=>x.id===mid),versions=await api(`/memories/${mid}/versions`);
  const modal=openDialog('Versions and provenance',`<p class="dialog-help">${esc(m.title)} · Current v${m.version}</p>${versions.reverse().map(v=>`<article class="review-row"><strong>v${v.version}</strong> <small>${dt(v.created_at)}</small><p>${esc(v.snapshot.content)}</p><small>Source: ${esc(v.snapshot.provenance?.kind==='owner'?'Confirmed by owner':'Reviewed by owner')}</small>${(v.snapshot.provenance?.evidence||[]).map(e=>`<div class="evidence">${esc(e.speaker||'Sources')}: ${esc(e.content)}</div>`).join('')}${v.version!==m.version?`<button type="button" class="btn" data-restore="${v.version}">Restore this version</button>`:''}</article>`).join('')}`,async()=>{},'Done');
  $$('[data-restore]',modal).forEach(b=>b.onclick=()=>{const v=versions.find(v=>v.version===Number(b.dataset.restore));modal.close();openDialog('Restore memory content',memoryFields(v.snapshot),async fd=>{await api(`/memories/${mid}`,'PUT',{...memoryData(fd),expected_version:m.version});toast('Saved as a new version.');await renderRoute();},'Confirm restore');});
}
function sourceDialog() {
  openDialog('Add source',field('title','Source title','','text','required maxlength="150"')+area('content','Source content','','required maxlength="100000"')+'<p class="dialog-help">Sources stay in this domain. Extract memories after saving; they cannot inform public replies until reviewed.</p>',async fd=>{
    await api(`/domains/${state.route[1]}/sources`,'POST',Object.fromEntries(fd));toast('Source saved. You can now extract memories.');await renderRoute();
  },'Save source');
}
function uploadDialog() {
  openDialog('Upload source',field('file','Choose a file','','file','required accept=".txt,.md,.csv,.json,.pdf,.docx"')+'<p class="dialog-help">Up to 5 MB. PDFs must contain extractable text. Sources stay private in this domain.</p>',async(fd)=>{
    await api(`/domains/${state.route[1]}/upload`,'POST',fd);toast('Source uploaded.');await renderRoute();
  },'Upload');
}
let startingChat=false;
async function quickChat() {
  if(startingChat)return;
  startingChat=true;
  try {
    const result=await api('/sessions/quick-chat','POST');
    navigate(`sessions/${result.id}`);
  } finally {startingChat=false;}
}
function saveChatMemoryDialog() {
  const session=state.session,messages=session.messages.filter(m=>m.role==='owner');
  if(!messages.length){toast('Send a message first, then choose what to save.');return;}
  const domains=state.domains.filter(d=>!session.domain_ids.length||session.domain_ids.includes(d.id));
  const selected=messages[messages.length-1];let createdDomainId=null;
  const destination=domains.length?`<div class="form-field"><label for="f-destination">Destination domain</label><select id="f-destination" name="domain_id">${domains.map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div>`:field('domain_name','Create a destination domain','','text','required maxlength="60"');
  const modal=openDialog('Save a memory for review',destination+`<div class="form-field"><label for="f-evidence">Your source message</label><select id="f-evidence" name="message_id">${messages.map(m=>`<option value="${m.id}" ${m.id===selected.id?'selected':''}>${esc(m.content.slice(0,80))}</option>`).join('')}</select></div>`+field('title','Memory title',selected.content.slice(0,60),'text','required maxlength="150"')+area('content','Information to remember',selected.content,'required maxlength="12000"')+'<p class="dialog-help">This creates a proposal in the chosen domain. It is not available as a memory until you review it. The active chat does not gain access to that domain.</p>',async fd=>{
    let did=fd.get('domain_id')||createdDomainId;
    if(!did){const created=await api('/domains','POST',{name:fd.get('domain_name')});did=created.id;createdDomainId=did;state.domains.push({...created,memory_count:0,pending_count:0});}
    await api(`/sessions/${session.id}/memory-proposals`,'POST',{domain_id:did,message_id:fd.get('message_id'),title:fd.get('title'),content:fd.get('content')});
    toast('Memory proposed. Review it before it becomes available to the assistant.');
  },'Send for review');
  $('#f-evidence',modal).onchange=e=>{const m=messages.find(m=>m.id===e.target.value);$('#f-title',modal).value=m.content.slice(0,60);$('#f-content',modal).value=m.content;};
}
async function sessionDialog(mode, changingContext=false) {
  if(!state.domains.length){toast(mode==='private'?'You can chat without domains. Add one when you want to use personal memories.':'Create a domain to authorize a delegation.');domainDialog();return;}
  const initial=state.route[0]==='domain'?[state.route[1]]:changingContext?(state.session?.domain_ids||[]):mode==='private'?state.domains.filter(d=>d.name==='default').map(d=>d.id):[];
  const all=(await Promise.all(state.domains.map(d=>api(`/domains/${d.id}/memories`)))).flat();
  const body=(mode==='delegate'?field('title','Conversation title','','text','required maxlength="120" placeholder="Discuss project progress with a client"'):'<p class="dialog-help">Quick chats use default. Choose domains for a different context, or deselect all to chat without memory. A new chat starts without previous conversation text.</p>')+
    (mode==='delegate'?field('audience','Audience','','text','required maxlength="80" placeholder="For example, Client or Team. Must match memory audience restrictions."'):'')+
    `<fieldset><legend>Active domains</legend>${state.domains.map(d=>`<label class="check"><input type="checkbox" name="domains" value="${d.id}" ${initial.includes(d.id)?'checked':''}><span>${esc(d.name)}</span></label>`).join('')}</fieldset>`+
    `<fieldset><legend>${mode==='private'?'Memories available to read':'Read and disclosure permissions'}</legend><p class="dialog-help">${mode==='private'?'Used only in this private conversation.':'The public reply model only receives memories marked Disclose. Private memories and audience mismatches cannot be disclosed.'}</p><div class="fact-picker" id="fact-picker"></div></fieldset>`+
    `<div class="two-col"><div class="form-field"><label for="f-write">Save proposed memories to</label><select id="f-write" name="write_domain_id"></select></div><div class="form-field"><label for="f-duration">Authorization duration</label><select name="duration_minutes" id="f-duration"><option value="30">30 minutes</option><option value="60" selected>1 hour</option><option value="180">3 hours</option><option value="1440">24 hours</option></select></div></div>`+
    area('goal','Conversation goal (do not include secrets)','','maxlength="2000" placeholder="What would you like your assistant to accomplish?"')+
    `<label class="check"><input type="checkbox" name="allow_learning" ${mode==='delegate'||(changingContext&&state.session?.allow_learning)||initial.some(id=>state.domains.find(d=>d.id===id)?.name==='default')?'checked':''}><span>Propose memories when the conversation ends<small>Proposals go to the selected domain for review. Confirmed memories are not changed automatically.</small></span></label>`+
    (mode==='delegate'?`<div class="form-field"><label for="f-action">Action permissions</label><select name="action_policy" id="f-action"><option value="ask">Ask me before making new commitments</option><option value="none">Share information only; do not make decisions</option></select></div>`:'')+
    `<p class="dialog-help">${mode==='private'?'Changing domains starts a new chat. Your previous conversation stays in history.':'Delegation permissions are fixed. A new authorization never includes your private chat history.'}</p>`;
  const modal=openDialog(mode==='private'?'Start a private conversation':'Create a delegation',body,async fd=>{
    const domains=fd.getAll('domains');if(mode==='delegate'&&!domains.length)throw new Error('Select at least one domain for delegation.');
    const selected=fd.getAll('read_ids');const disclose=fd.getAll('disclose_ids');
    const result=await api('/sessions','POST',{title:fd.get('title')||'New conversation',mode,audience:fd.get('audience')||'',goal:fd.get('goal'),
      domain_ids:domains,read_ids:[...new Set([...selected,...disclose])],disclose_ids:disclose,write_domain_id:fd.has('allow_learning')?fd.get('write_domain_id'):null,
      allow_learning:fd.has('allow_learning'),action_policy:fd.get('action_policy')||'none',duration_minutes:Number(fd.get('duration_minutes'))});
    toast('Conversation created.');navigate(`sessions/${result.id}`);
  },mode==='private'?'Start conversation':'Create conversation');
  function updatePicker(){
    const ids=$$('input[name=domains]:checked',modal).map(e=>e.value),aud=$('#f-audience',modal)?.value.trim()||'';
    const facts=all.filter(m=>ids.includes(m.domain_id)&&(!m.expires_at||m.expires_at>Date.now()/1000));
    $('#fact-picker').innerHTML=`<div class="fact-choice picker-header"><span>Memory</span><span>Read</span>${mode==='delegate'?'<span>Disclose</span>':''}</div>`+facts.map(m=>{
      const allowed=m.visibility==='shareable'&&(!m.audiences.length||m.audiences.includes(aud));
      return `<div class="fact-choice"><div><p>${esc(m.title)}</p><small>${esc(domainName(m.domain_id))} · ${m.visibility==='private'?'Private':m.audiences.length?esc(m.audiences.join(', ')):'Shareable'}</small></div><label class="check"><input aria-label="Read ${esc(m.title)}" type="checkbox" name="read_ids" value="${m.id}" checked></label>${mode==='delegate'?`<label class="check"><input aria-label="Disclose ${esc(m.title)}" type="checkbox" name="disclose_ids" value="${m.id}" ${allowed?'':'disabled'}></label>`:''}</div>`;
    }).join('')+(facts.length?'':'<p class="dialog-help">No valid memories in this selection. You can still create a conversation to gather information.</p>');
    const learning=$('input[name=allow_learning]',modal);learning.disabled=!ids.length;if(!ids.length)learning.checked=false;
    const current=$('#f-write').value;$('#f-write').innerHTML=state.domains.filter(d=>ids.includes(d.id)).map(d=>`<option value="${d.id}" ${d.id===current?'selected':''}>${esc(d.name)}</option>`).join('')||'<option value="">No domain selected</option>';
    $('#f-write').disabled=!ids.length;
  }
  $$('input[name=domains]',modal).forEach(e=>e.onchange=updatePicker);
  if($('#f-audience'))$('#f-audience').oninput=updatePicker;
  updatePicker();
}
async function proposalDialog(pid) {
  const p=state.proposals.find(x=>x.id===pid);
  const memories=await api(`/domains/${p.domain_id}/memories`);
  openDialog('Review memory update',`<p class="dialog-help">Save to domain: ${esc(domainName(p.domain_id))}. Check the speaker and facts, and edit as needed. Updates stay in this domain.</p>`+memoryFields({...p,visibility:'private',audiences:[]})+`<div class="form-field"><label for="f-target">Save as</label><select name="target_id" id="f-target"><option value="">Add a new memory</option>${memories.map(m=>`<option value="${m.id}">Replace: ${esc(m.title)} · v${m.version}</option>`).join('')}</select></div><details><summary>Evidence</summary>${p.evidence.map(e=>`<div class="evidence">${esc(e.speaker||'Imported source')}: ${esc(e.content)}</div>`).join('')}</details>`,async fd=>{
    const target=memories.find(m=>m.id===fd.get('target_id'));
    await api(`/proposals/${pid}/review`,'POST',{...memoryData(fd),decision:'approve',target_id:target?.id||null,expected_version:target?.version||null});
    toast('Update confirmed and saved.');await renderRoute();
  },'Confirm and save');
}
async function inviteDialog() {
  const sid=state.session.id;
  openDialog('Create invitation','<p class="dialog-help">This invitation is valid for one conversation and can be redeemed once. A new invitation revokes previous guest credentials. Share it only with the intended participant.</p>',async()=>{
    const data=await api(`/sessions/${sid}/invite`,'POST');
    const link=`${location.origin}/invite#${data.token}`;
    // Opening a follow-up dialog after the current form closes keeps native focus management intact.
    setTimeout(()=>{
      const m=openDialog('Invitation created',field('link','Share this link with your guest',link,'text','readonly')+`<p class="dialog-help">Expires at ${dt(data.expires_at)}. The guest can only talk to the authorized assistant and cannot access your private workspace.</p>`,async()=>{},'Done');
      const input=$('#f-link',m);input.onclick=()=>input.select();input.select();
      const copy=document.createElement('button');copy.type='button';copy.className='btn';copy.textContent='Copy invitation link';
      copy.onclick=async()=>{try{await navigator.clipboard.writeText(link);toast('Invitation copied.');}catch{input.select();toast('Copy the selected link.');}};
      $('.dialog-body',m).append(copy);
    },0);
  },'Create one-time invitation');
}
function decisionDialog(aid) {
  const a=state.session.actions.find(a=>a.id===aid);
  openDialog('Review request',`<p class="dialog-help">Guest request: ${esc(a.request)}</p><div class="form-field"><label for="f-decision">Your decision</label><select id="f-decision" name="decision"><option value="approve">Approve the wording below</option><option value="reject">Reject this request</option></select></div>`+area('response','Exact wording to send to the guest','','maxlength="2000" placeholder="Required for approval. You may add an explanation when rejecting."')+'<p class="dialog-help">You are approving a message to the guest. This does not execute actions in external calendar, payment, or email systems.</p>',async fd=>{
    await api(`/actions/${aid}/decision`,'POST',Object.fromEntries(fd));toast('Your decision was sent to the conversation.');await refreshSession();
  },'Confirm and send');
}
function bindActions(root=document) {
  $$('[data-action]',root).forEach(b=>b.onclick=async()=>{
    const action=b.dataset.action,id=b.dataset.id;
    try{
      if(action==='menu'){const open=$('.shell').classList.toggle('menu-open');b.setAttribute('aria-expanded',String(open));}
      if(action==='new-domain')domainDialog();
      if(action==='edit-domain')domainDialog(true);
      if(action==='new-memory')memoryDialog();
      if(action==='edit-memory')memoryDialog(id);
      if(action==='versions')await versionsDialog(id);
      if(action==='new-source')sourceDialog();
      if(action==='upload')uploadDialog();
      if(action==='quick-chat'){b.disabled=true;await quickChat();}
      if(action==='new-private')await sessionDialog('private');
      if(action==='choose-domains')await sessionDialog('private',true);
      if(action==='save-chat-memory')saveChatMemoryDialog();
      if(action==='new-delegate')await sessionDialog('delegate');
      if(action==='extract'){
        b.disabled=true;b.textContent='Extracting…';const p=await api(`/sources/${id}/extract`,'POST');toast(`Ready for review: ${countLabel(p.length,'memory proposal')}.`);await renderRoute();
      }
      if(action==='delete-source')openDialog('Delete source','<p class="dialog-help">Also deletes memories derived from this source, proposals, and related conversations. This cannot be undone.</p>',async()=>{await api(`/sources/${id}`,'DELETE');toast('Source deleted.');await renderRoute();},'Confirm deletion');
      if(action==='review-proposal')await proposalDialog(id);
      if(action==='reject-proposal'){const p=state.proposals.find(p=>p.id===id);await api(`/proposals/${id}/review`,'POST',{title:p.title,content:p.content,decision:'reject'});toast('Update dismissed.');await renderRoute();}
      if(action==='invite')await inviteDialog();
      if(action==='decide')decisionDialog(id);
      if(action==='end-session'){
        b.disabled=true;b.textContent='Preparing review…';const result=await api(`/sessions/${state.session.id}/end`,'POST');toast(result.warning||'Conversation ended. Proposed updates are ready for review.');await renderRoute();
      }
      if(action==='revoke-session'){await api(`/sessions/${state.session.id}/revoke`,'POST');toast('Access revoked immediately. Memories will not be extracted automatically.');await renderRoute();}
      if(action==='retry-learning'){b.disabled=true;const p=await api(`/sessions/${state.session.id}/learn`,'POST');toast(`Ready for review: ${countLabel(p.length,'update')}.`);await renderRoute();}
      if(action==='refresh')await renderRoute();
      if(action==='logout'){await api('/auth/logout','POST');disconnect();location.href='/';}
      if(action==='mic'){
        if(!state.voice||state.socket?.readyState!==WebSocket.OPEN)throw new Error('Connect to a conversation first.');
        if((state.guest?state.session.stt:state.config.providers?.stt)==='mock')throw new Error('The local demo uses text input. Configure AssemblyAI to enable speech recognition.');
        const enabled=await state.voice.toggleMic();b.classList.toggle('recording',enabled);b.setAttribute('aria-label',enabled?'Turn off microphone':'Turn on microphone');
      }
      if(action==='interrupt'){state.voice?.stopPlayback();if(state.socket?.readyState===WebSocket.OPEN)state.socket.send(JSON.stringify({type:'interrupt'}));}
    }catch(err){toast(err.message);b.disabled=false;if(action==='extract')b.textContent='Extract memories';}
  });
}
function authPage(needsSetup) {
  $('#app').innerHTML=`<main class="auth-page" id="main">${brand}<p class="eyebrow">Personal agent workspace</p><h1>${needsSetup?'Create your private workspace':'Welcome back'}</h1><p>${needsSetup?'Set up your sign-in to start managing domains and memories.':'Sign in to manage memories, conversations, and pending updates.'}</p><form id="auth-form"><div class="form-error" role="alert"></div>${field('name','Username','','text','required minlength="2" maxlength="60" autocomplete="username"')}${field('password','Password','','password',`required maxlength="200" autocomplete="${needsSetup?'new-password':'current-password'}"`)}<button class="btn primary" type="submit">${needsSetup?'Create workspace':'Sign in'} ${icon('arrow')}</button></form><p class="footnote">${needsSetup?'Initial setup creates one owner account for this deployment.':'Sign in to access your data. Invitation links grant access to one conversation only.'}</p></main>`;
  $('#auth-form').onsubmit=async e=>{e.preventDefault();const b=$('button',e.target);b.disabled=true;try{const d=await api(needsSetup?'/auth/setup':'/auth/login','POST',Object.fromEntries(new FormData(e.target)));state.user=d.user;await startOwner();}catch(err){$('.form-error',e.target).textContent=err.message;}finally{b.disabled=false;}};
}
function renderGuest() {
  const s=state.session;
  $('#app').innerHTML=`<main class="guest-shell" id="main"><header class="guest-header">${brand}<span class="tag green">Guest conversation</span></header><div class="heading"><div><p class="eyebrow">An authorized conversation</p><h1>${esc(s.title)}</h1><p>You are speaking with an authorized AI assistant. New commitments require owner approval.</p></div></div>${s.demo?'<div class="banner">'+icon('info')+'Local demo: replies are generated from authorized memories.</div>':''}<div class="room-layout">${conversation(s,true)}</div><p class="muted"><small>The owner can view the transcript. This conversation is open only while authorization is valid.</small></p></main>`;
  bindActions();bindConversation(true);
}
async function startGuest(sid) {
  state.guest=true;
  try{state.session=await api(`/guest/sessions/${sid}`);renderGuest();connect(sid,true);}catch(err){$('#app').innerHTML=`<main class="auth-page" id="main">${brand}<h1>Invitation expired or conversation ended</h1><p>${esc(err.message)}</p><p>Ask the owner for a new authorization.</p></main>`;}
}
async function startOwner() {
  state.config=await api('/config');await renderRoute();window.addEventListener('hashchange',renderRoute);
}
async function boot() {
  if(location.pathname==='/invite'){
    const token=location.hash.slice(1);history.replaceState(null,'','/invite');
    $('#app').innerHTML=`<main class="auth-page" id="main">${brand}<p class="eyebrow">Invitation</p><h1>Join an authorized conversation</h1><p>You will talk with the Echooo AI assistant. The owner can view this conversation, and it may produce memory proposals for their review.</p><button class="btn primary" id="join">Join conversation ${icon('arrow')}</button><p class="form-error" role="alert"></p></main>`;
    $('#join').onclick=async()=>{const b=$('#join');b.disabled=true;try{const r=await api('/guest/join','POST',{token});history.replaceState(null,'',`/room/${r.session_id}`);await startGuest(r.session_id);}catch(err){$('.form-error').textContent=err.message;b.disabled=false;}};return;
  }
  if(location.pathname.startsWith('/room/')){await startGuest(location.pathname.split('/')[2]);return;}
  try{const auth=await api('/auth');if(!auth.user)authPage(auth.needs_setup);else{state.user=auth.user;await startOwner();}}catch(err){$('#app').innerHTML=empty('Unable to connect to the workspace',err.message);}
}
document.addEventListener('click',e=>{const shell=$('.shell.menu-open');if(shell&&!e.target.closest('.sidebar,[data-action=menu]')){shell.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('.shell')?.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');}});
window.addEventListener('pagehide',disconnect);
boot();
