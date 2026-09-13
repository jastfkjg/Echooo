import { Voice } from './voice.js';
import {showMeetings, leaveMeeting} from './meetings.js?v=project-simple-3';
import { voiceControls, sessionHeader, updateVoiceUI } from './chat-ui.js';
import {sessionStatus, filterSessions, privateContextForm, bindPrivateContext} from './session-ui.js?v=project-simple-3';
import {enhanceSelects} from './select.js';
import {bindVoiceOptions} from './voice-options.js';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5',
  moon:'M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z',
  volume:'M11 5 6 9H3v6h3l5 4Zm4 3a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14',
  panel:'M3 4h18v16H3Zm12 0v16',more:'M5 11a1 1 0 1 0 0 2 1 1 0 1 0 0-2M12 11a1 1 0 1 0 0 2 1 1 0 1 0 0-2M19 11a1 1 0 1 0 0 2 1 1 0 1 0 0-2',
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
function themePicker() {
  const theme=document.documentElement.dataset.theme||'light';
  return `<div class="theme-switch" role="group" aria-label="Appearance">${[['light','Light','sun'],['dark','Dark','moon']].map(([value,label,symbol])=>`<button type="button" class="theme-choice" data-theme-choice="${value}" aria-label="${label} mode" aria-pressed="${theme===value}" title="${label} mode">${icon(symbol)}<span>${label}</span></button>`).join('')}</div>`;
}
const brand = `<a class="brand" href="/" aria-label="Echooo workspace">${icon('wave')}<span>echooo<span class="muted">.</span></span></a>`;
const dt = t => new Date(t * 1000).toLocaleString('en-US', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const countLabel = (n, singular, plural=singular+'s') => `${n.toLocaleString('en-US')} ${n===1?singular:plural}`;
const roleName = {assistant:'Echooo',guest:'Guest',owner:'You',owner_approved:'Owner approved',private_note:'Private note'};
const statusName = s => ({active:'Active',ended:'Ended',revoked:'Revoked',expired:'Expired'}[sessionStatus(s)] || s.status);
const state = {user:null,config:{},domains:[],sessions:[],proposals:[],memories:[],sources:[],route:[],session:null,guest:false,filter:'',socket:null,voice:null};
let toastTimer, poll, navigation = 0;
state.voicePrefs = {muted:false, dictation:false};

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
function openDialog(title,body,submit,label='Save',options={}) {
  const modal=$('#modal');
  modal.className=options.className||'';
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
  $(options.focusSelector||'input:not([type=checkbox]),textarea,select',modal)?.focus();
  enhanceSelects(modal);
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
function shell(body,crumb='My domains',chatHeader='') {
  const pending=state.proposals.filter(p=>p.status==='pending').length;
  $('#app').innerHTML=`<div class="shell ${chatHeader?'chat-shell':''}"><aside class="sidebar">${brand}<button class="btn primary" data-action="quick-chat">${icon('chat')}Talk with Echooo</button><a class="navlink ${!state.route[0]?'active':''}" href="#">${icon('grid')}<span>My domains</span></a><a class="navlink ${state.route[0]==='sessions'?'active':''}" href="#sessions">${icon('chat')}<span>Conversations</span><span class="count">${state.sessions.length||''}</span></a><a class="navlink ${state.route[0]==='review'?'active':''}" href="#review">${icon('review')}<span>Review</span>${pending?`<span class="count">${pending}</span>`:''}</a><div class="label">Domains · ${state.domains.length}</div><nav class="domain-nav" aria-label="Domains">${state.domains.map(d=>`<a class="navlink ${state.route[1]===d.id?'active':''}" href="#domain/${d.id}/memories"><i class="domain-dot ${esc(d.color)}"></i><span class="name">${esc(d.name)}</span><span class="count">${d.memory_count}</span></a>`).join('')}</nav><button class="navlink" data-action="new-domain">${icon('plus')}<span>Add domain</span></button><div class="side-bottom">${themePicker()}<a class="navlink ${state.route[0]==='settings'?'active':''}" href="#settings">${icon('settings')}<span>Workspace settings</span></a><div class="profile"><span class="avatar">${esc(state.user.name.slice(0,1).toUpperCase())}</span><div><strong>${esc(state.user.name)}</strong><small>Private workspace</small></div></div></div></aside><main class="main" id="main"><header class="topbar">${chatHeader||`<div class="path"><button class="icon-btn mobile-menu" data-action="menu" aria-label="Open navigation">${icon('menu')}</button><span>Personal workspace</span><span>/</span><strong>${esc(crumb)}</strong></div><span class="status">Private workspace</span>`}</header><div class="workspace">${body}</div></main></div>`;
  $('.sidebar a[href="#sessions"]')?.insertAdjacentHTML('afterend', `<a class="navlink ${state.route[0]==='meetings'?'active':''}" href="#meetings">${icon('mic')}<span>Meetings</span></a>`);
  if(state.route[0]==='meetings') $('.topbar .status').textContent='Private meeting workspace';
  bindActions();
}
const demoBanner=()=>state.config.demo?`<div class="banner">${icon('info')}<span>Demo mode · Connect a live model for natural replies.</span></div>`:'';

async function renderRoute() {
  const run=++navigation;
  leaveMeeting();
  disconnect();
  state.route=location.hash.slice(1).split('/').filter(Boolean); state.filter=''; state.session=null;
  try {
    await refreshBase(); if(run!==navigation)return;
    const [page,id,tab]=state.route;
    if(page==='meetings') {
      await showMeetings({api,shell,openDialog,field,navigate,toast,isCurrent:()=>run===navigation},id);
    } else if(page==='domain') {
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
  const pending=state.proposals.filter(p=>p.status==='pending').length;
  shell(`<div class="heading"><div><h1>My domains</h1></div><div class="actions"><button class="btn primary" data-action="new-domain">${icon('plus')}Add domain</button></div></div>${demoBanner()}${pending?`<a class="review-prompt" href="#review">${countLabel(pending,'update')} ready to review ${icon('arrow')}</a>`:''}${state.domains.length?state.domains.map(d=>`<a class="session-row" href="#domain/${d.id}/memories"><div><h3><i class="domain-dot ${esc(d.color)}"></i> ${esc(d.name)}</h3>${d.description?`<p class="muted">${esc(d.description)}</p>`:''}<div class="meta"><span>${countLabel(d.memory_count,'memory','memories')}</span>${d.pending_count?`<span>${d.pending_count} pending</span>`:''}</div></div>${icon('arrow')}</a>`).join(''):empty('Add your first domain','Keep related knowledge together.',`<button class="btn primary" data-action="new-domain">${icon('plus')}Add domain</button>`)} `);
}
function renderDomain(d,tab) {
  const body=`<div class="heading"><div><h1>${esc(d.name)}</h1>${d.description?`<p>${esc(d.description)}</p>`:''}</div><div class="actions"><button class="btn" data-action="new-private">${icon('chat')}Private chat</button><button class="btn primary" data-action="new-delegate">${icon('arrow')}Delegate</button><button class="icon-btn" data-action="edit-domain" aria-label="Manage domain">${icon('settings')}</button></div></div><nav class="tabs" aria-label="Domain content"><a class="${tab==='memories'?'active':''}" href="#domain/${d.id}/memories">Confirmed memories <small>${state.memories.length}</small></a><a class="${tab==='sources'?'active':''}" href="#domain/${d.id}/sources">Sources <small>${state.sources.length}</small></a></nav>${tab==='sources'?`<div class="list-head"><small>Private sources · Review extracted memories before use.</small><div class="actions"><button class="btn" data-action="upload">${icon('upload')}Upload file</button><button class="btn primary" data-action="new-source">${icon('plus')}Paste text</button></div></div><div id="source-list">${sourceList()}</div>`:`<div class="list-head"><input class="search" id="memory-search" aria-label="Search domain memories" placeholder="Search memories…"><button class="btn primary" data-action="new-memory">${icon('plus')}Add memory</button></div><div id="memory-list">${memoryList()}</div>`}`;
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
  shell(`<div class="heading"><div><h1>Conversations</h1></div><div class="actions"><button class="btn primary" data-action="quick-chat">${icon('chat')}Talk with Echooo</button><button class="btn" data-action="new-delegate">${icon('plus')}Delegate</button></div></div>${demoBanner()}<div class="conversation-filters"><div class="form-field"><label for="conversation-search">Search conversations</label><input type="search" id="conversation-search" placeholder="Search by title, domain, or audience…"></div><div class="form-field"><label for="conversation-filter">Show</label><select id="conversation-filter"><option value="all">All conversations</option><option value="private">Private chats</option><option value="delegate">Delegations</option><option value="empty">Empty conversations</option></select></div></div><p class="conversation-count" id="conversation-count" role="status"></p><div id="conversation-list"></div>`,'Conversations');
  $('#conversation-search').oninput=renderConversationList;
  $('#conversation-filter').onchange=renderConversationList;
  renderConversationList();
}
function renderConversationList() {
  const records=filterSessions(state.sessions,$('#conversation-search').value,$('#conversation-filter').value,domainName);
  $('#conversation-count').textContent=`${records.length} of ${countLabel(state.sessions.length,'conversation')}`;
  $('#conversation-list').innerHTML=records.length?records.map(s=>`<article class="conversation-list-row"><a class="conversation-link" href="#sessions/${esc(s.id)}"><span class="conversation-symbol">${icon(s.mode==='private'?'chat':'shield')}</span><div><h3>${esc(s.title)}</h3><div class="meta"><span>${s.mode==='private'?'Private chat':esc(s.audience)}</span><span>${esc(s.domain_ids.map(domainName).join(' / ')||'No memory')}</span><span>${s.message_count==null?'':s.message_count===0?'Empty':countLabel(s.message_count,'message')}</span><time>${dt(s.created_at)}</time></div></div></a><span class="tag ${sessionStatus(s)==='active'?'green':''}">${esc(statusName(s))}</span><details class="toolbar-menu conversation-row-menu" name="conversation-actions"><summary class="icon-btn" aria-label="Manage conversation: ${esc(s.title)}" title="Manage conversation">${icon('more')}</summary><div class="toolbar-popover action-menu"><h2>Conversation actions</h2><button data-action="rename-session" data-id="${esc(s.id)}">${icon('edit')}Rename</button><button class="danger" data-action="delete-session" data-id="${esc(s.id)}">${icon('trash')}Delete conversation…</button></div></details></article>`).join(''):empty(state.sessions.length?'No matching conversations':'No conversations yet',state.sessions.length?'Try a different search or filter.':'Start a chat or delegation.','','chat');
  bindActions($('#conversation-list'));
}
function renameSessionDialog(id=state.session?.id) {
  const s=state.session?.id===id?state.session:state.sessions.find(s=>s.id===id);if(!s)return;
  openDialog('Rename conversation',field('title','Conversation title',s.title,'text','required maxlength="120"'),async fd=>{
    const renamed=await api(`/sessions/${id}`,'PATCH',{title:fd.get('title')});
    state.sessions=state.sessions.map(s=>s.id===id?{...s,title:renamed.title}:s);
    if(state.session?.id===id){state.session.title=renamed.title;$('#session-title').textContent=renamed.title;$('#session-title').title=renamed.title;}
    if($('#conversation-list'))renderConversationList();toast('Conversation renamed.');
  },'Save title');
}
function deleteSessionDialog(id=state.session?.id) {
  const s=state.session?.id===id?state.session:state.sessions.find(s=>s.id===id);if(!s)return;
  const modal=openDialog('Delete conversation?',`<p class="delete-conversation-title">${esc(s.title)}</p><p class="dialog-help">This permanently deletes the transcript, memory proposals, and review records for this conversation. Active voice and guest access will stop.</p><p class="dialog-help">Confirmed memories and their saved evidence stay in your domains. Other conversations are not affected. This cannot be undone.</p>`,async()=>{
    await api(`/sessions/${id}`,'DELETE');
    state.sessions=state.sessions.filter(s=>s.id!==id);
    if(state.session?.id===id){disconnect();navigate('sessions');}else await renderRoute();
    toast('Conversation deleted. Confirmed memories were kept.');
  },'Delete conversation',{focusSelector:'button[data-close]'});
  $('button[type=submit]',modal).className='btn danger';
}
function renderReview() {
  const pending=state.proposals.filter(p=>p.status==='pending');
  shell(`<div class="heading"><div><h1>Review <span class="muted">${pending.length}</span></h1><p>Confirm what to remember.</p></div></div>${pending.length?pending.map(p=>`<article class="review-row"><div class="review-header"><div><span class="tag">${esc(domainName(p.domain_id))}</span><h3>${esc(p.title)}</h3></div><div class="actions"><button class="btn subtle" data-action="reject-proposal" data-id="${p.id}">Dismiss</button><button class="btn primary" data-action="review-proposal" data-id="${p.id}">Review ${icon('arrow')}</button></div></div><p>${esc(p.content)}</p><details><summary>View evidence · ${countLabel(p.evidence.length,'item')}</summary>${p.evidence.map(e=>`<div class="evidence"><strong>${esc(e.speaker||'Imported source')}</strong>: ${esc(e.content)}</div>`).join('')}</details><small>${p.session_id?'From a conversation':'Extracted from a source'} · ${dt(p.created_at)} · Not yet used in replies</small></article>`).join(''):empty('No updates to review','Proposed memories will appear here.','', 'check')}<p class="muted"><small>${countLabel(state.proposals.length-pending.length,'update')} processed</small></p>`,'Review');
}
function renderSettings() {
  shell(`<div class="heading"><div><h1>Settings</h1></div></div>${demoBanner()}<section class="settings-section appearance-setting"><h3>Appearance</h3>${themePicker()}</section><section class="settings-section"><div><h3>Export data</h3><p>Download your workspace as JSON.</p></div><a class="btn" href="/api/export" download>${icon('download')}Export</a></section><details class="settings-details"><summary>Connections & storage</summary><section class="settings-section"><div><h3>Model connections</h3><p>STT: ${esc(state.config.providers?.stt)} · LLM: ${esc(state.config.providers?.llm)} · TTS: ${esc(state.config.providers?.tts)}</p><p>Configured on the server.</p></div><span class="tag">${state.config.demo?'Demo':'Configured'}</span></section><section class="settings-section"><div><h3>Storage</h3><p>${state.config.database==='sqlite'?'Local SQLite':'PostgreSQL'}</p></div></section></details><section class="settings-section"><h3>${esc(state.user.name)}</h3><button class="btn" data-action="logout">${icon('logout')}Sign out</button></section>`,'Settings');
}
function messageHTML(m) {
  const saveable=!state.guest && state.session?.mode==='private' && state.session.status!=='revoked' && m.role==='owner';
  return `<article class="message ${esc(m.role)}" data-message="${esc(m.id)}"><div class="speaker"><strong>${esc(roleName[m.role]||m.role)}</strong><time>${dt(m.created_at)}</time>${m.role==='private_note'?'<span>Only you</span>':''}${saveable?`<button class="message-save" data-action="save-chat-memory" data-id="${esc(m.id)}" aria-label="Save this message as a memory">${icon('file')}<span>Save memory</span></button>`:''}</div><div class="text">${esc(m.content)}</div>${m.citations?.length?`<div class="citations">Based on ${countLabel(m.citations.length,'authorized memory','authorized memories')}</div>`:''}</article>`;
}
function conversation(s, canSpeak) {
  const status=sessionStatus(s),active=status==='active';
  const emptyTitle=active?(canSpeak?'Ready to talk':'Follow the conversation'):
    status==='expired'?'Authorization expired':status==='revoked'?'Conversation revoked':'Conversation ended';
  const emptyDescription=active?(canSpeak?'Start a voice conversation, or write a message below.':'Create an invitation. Your guest’s messages will appear here.'):
    'No messages were sent in this conversation.';
  const disclosure=state.guest?'You are speaking with AI. The owner can view this transcript.':!canSpeak?'Private notes are never sent to the guest.':'';
  return `<section class="conversation" aria-label="Conversation">
    <div class="transcript" id="transcript" role="log" aria-label="Transcript" aria-live="polite" tabindex="0"><div class="message-column" id="messages">${s.messages.length?s.messages.map(messageHTML).join(''):empty(emptyTitle,emptyDescription,'',active?'wave':'lock')}${!active&&!state.guest&&s.messages.length?summaryHTML(s):''}</div></div>
    <button class="btn jump-latest" data-action="latest" hidden>Latest messages ↓</button>
    <div class="composer"><div class="composer-inner">${active?`
      ${canSpeak?voiceControls(icon,state.voicePrefs):`<div class="supervision-note">${icon('shield')} Private supervision <span id="room-state">Connecting…</span></div>`}
      <div id="partial" class="partial-transcript" aria-live="off" hidden></div>
      <form id="message-form"><textarea id="message-input" rows="1" aria-label="${canSpeak?'Message':'Private note'}" placeholder="${canSpeak?'Or type a message…':'Write a private note…'}" maxlength="6000" required></textarea><button class="btn send-message" type="submit" aria-label="${canSpeak?'Send message':'Save private note'}">${icon('arrow')}<span>${canSpeak?'Send':'Save note'}</span></button></form>
      ${disclosure?`<div class="composer-caption">${disclosure}</div>`:''}`:`<p class="ended-note">${icon('lock')} ${status==='expired'?'This conversation’s authorization has expired.':status==='revoked'?'This conversation has been revoked.':'This conversation has ended.'} ${!state.guest?'<button class="btn" data-action="quick-chat">Start a new conversation</button>':''}</p>`}</div></div>
  </section>`;
}
function inspector(s) {
  if(s.mode==='private')return `<h3>${icon('shield')} Chat context</h3><dl><dt>Active domains</dt><dd>${esc(s.domain_ids.map(domainName).join(', ')||'None · General chat')}</dd><dt>Personal memories</dt><dd>${s.read_ids.length?countLabel(s.read_ids.length,'selected memory','selected memories'):s.domain_ids.length?'No confirmed memories selected yet':'Not accessed'}</dd><dt>Automatic proposals</dt><dd>${s.allow_learning?esc(domainName(s.write_domain_id))+' · Review before saving':'Off'}</dd></dl><hr><p class="dialog-help">Private chats do not expire. Return anytime to continue an active conversation.</p><p class="dialog-help">${s.domain_ids.length?'Only selected memories are available here.':'Ask general questions or share something in this conversation. Personal memories are not loaded.'}</p><p class="dialog-help">Use Save memory to choose what to keep and where it belongs.</p>`;
  const pending=s.actions.filter(a=>a.status==='pending');
  return `<h3>${icon('shield')} Authorization</h3><dl><dt>Audience</dt><dd>${esc(s.audience||'Private')}</dd><dt>Readable domains</dt><dd>${esc(s.domain_ids.map(domainName).join(', '))}</dd><dt>Authorized memories</dt><dd>${s.read_ids.length} readable · ${s.disclose_ids.length} disclosable</dd><dt>Save memories to</dt><dd>${s.allow_learning?esc(domainName(s.write_domain_id))+' · Save after review':'Do not extract memories'}</dd><dt>Action permissions</dt><dd>${s.action_policy==='ask'?'New commitments require owner approval':'Information only'}</dd><dt>Expires at</dt><dd>${dt(s.expires_at)}</dd></dl>${s.goal?`<hr><h3>Conversation goal</h3><p class="muted pre">${esc(s.goal)}</p>`:''}<hr><h3>Needs your approval ${pending.length?`· ${pending.length}`:''}</h3>${pending.length?pending.map(a=>`<div class="approval"><small>Guest request</small><p>${esc(a.request)}</p><button class="btn primary" data-action="decide" data-id="${a.id}" ${s.status!=='active'?'disabled':''}>Review request</button></div>`).join(''):'<small>No requests need your decision right now.</small>'}`;
}
function renderSession() {
  const s=state.session;
  s.status=sessionStatus(s);
  state.voicePrefs.voices=state.config.tts?.voices||[];
  state.voicePrefs.voice=s.voice?.dashscope_voice||state.config.tts?.default_voice||'';
  state.voicePrefs.customVoiceManagement=!!state.config.tts?.custom_voice_management;
  const active=s.status==='active';
  shell(`${state.config.demo?'<div class="chat-demo-note">Local demo · Text replies use authorized memories. Microphone requires a live speech service.</div>':''}
    <div class="room-layout">${conversation(s,s.mode==='private')}</div>
    <dialog class="context-drawer" id="context-drawer" aria-labelledby="context-title"><div class="context-heading"><h2 id="context-title">${s.mode==='private'?'Chat context':'Authorization & approvals'}</h2><div class="actions"><button class="icon-btn pin-context" data-action="pin-context" aria-label="Pin context beside conversation" title="Pin context beside conversation" aria-pressed="false">${icon('panel')}</button><button class="icon-btn" data-action="close-context" aria-label="Close context">${icon('close')}</button></div></div><div class="inspector" id="inspector">${inspector(s)}</div></dialog>`,'Conversations',sessionHeader(s,{icon,esc,domainName,prefs:state.voicePrefs}));
  bindSessionChrome();
  bindConversation(s.mode==='private');
  if(active&&s.mode==='private')$('#message-input')?.focus();
  if(active){ connect(s.id,false); poll=setInterval(refreshSession,3500); }
}
function bindSessionChrome() {
  const drawer=$('#context-drawer');
  if(drawer) {
    drawer.addEventListener('close',()=>{if(!drawer.open){drawer.classList.remove('pinned');$('.chat-shell')?.classList.remove('context-pinned');$$('[data-action=context]').forEach(b=>b.setAttribute('aria-expanded','false'));const pin=$('[data-action=pin-context]');pin?.setAttribute('aria-pressed','false');pin?.setAttribute('aria-label','Pin context beside conversation');if(pin)pin.title='Pin context beside conversation';$('.context-toggle')?.focus();}});
    drawer.addEventListener('click',e=>{if(e.target===drawer){const r=drawer.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)drawer.close();}});
  }
  $$('.toolbar-menu').forEach(menu=>menu.addEventListener('toggle',()=>{
    if(menu.open)$$('.toolbar-menu').filter(other=>other!==menu).forEach(other=>other.open=false);
  }));
}
function openContext() {
  const drawer=$('#context-drawer');
  if(!drawer)return;
  if(drawer.open){drawer.close();return;}
  drawer.showModal();
  $$('[data-action=context]').forEach(b=>b.setAttribute('aria-expanded','true'));
}
function pinContext() {
  const drawer=$('#context-drawer');if(!drawer?.open)return;
  const pinned=!drawer.classList.contains('pinned');
  drawer.close();drawer.classList.toggle('pinned',pinned);$('.chat-shell').classList.toggle('context-pinned',pinned);
  if(pinned)drawer.show();else drawer.showModal();
  const button=$('[data-action=pin-context]');button.setAttribute('aria-pressed',String(pinned));
  button.setAttribute('aria-label',pinned?'Unpin context':'Pin context beside conversation');button.title=pinned?'Unpin context':'Pin context beside conversation';
}
function renderVoice() { updateVoiceUI(state.voice,{icon}); }
function summaryHTML(s) {
  return `<section class="review-row"><div class="review-header"><div><h2>Conversation review</h2><p>${countLabel(s.summary.checked_replies||0,'checked reply','checked replies')} · ${countLabel(s.proposals.length,'memory proposal')}</p></div><div class="actions">${s.status==='ended'&&s.allow_learning?'<button class="btn" data-action="retry-learning">Extract memories</button>':''}<a class="btn primary" href="#review">Review updates ${icon('arrow')}</a></div></div><details><summary>Participant statements and approved decisions</summary>${(s.summary.statements||[]).map(x=>`<div class="evidence"><strong>${esc(roleName[x.speaker]||x.speaker)}</strong>: ${esc(x.text)}</div>`).join('')||'<p class="muted">No statements recorded.</p>'}</details><details><summary>Checks and authorization log · ${s.audit.length}</summary><ul class="detail-list">${s.audit.map(a=>`<li>${dt(a.created_at)} · ${esc(a.kind)} ${a.detail.kind_result?'· '+esc(a.detail.kind_result):''}</li>`).join('')}</ul></details></section>`;
}
async function refreshSession() {
  if(!state.session||state.guest)return;
  try{
    const sid=state.session.id;
    const s=await api(`/sessions/${sid}`);if(state.session?.id!==sid)return;state.session=s;
    if(sessionStatus(s)!=='active'){disconnect();renderSession();return;}
    if($('#session-title')){$('#session-title').textContent=s.title;$('#session-title').title=s.title;}
    if($('#inspector')&&!$('#inspector').contains(document.activeElement)){const html=inspector(s);if($('#inspector').innerHTML!==html){$('#inspector').innerHTML=html;bindActions($('#inspector'));}}
    const badge=$('.approval-count');if(badge){const n=s.actions.filter(a=>a.status==='pending').length;badge.hidden=!n;badge.textContent=n;$('[aria-controls=context-drawer]').setAttribute('aria-label',n?`Chat context, ${n} requests need approval`:'Chat context');}
    s.messages.forEach(appendMessage);
  }catch(err){disconnect();toast(err.message);}
}
function appendMessage(m) {
  if(state.session&&!state.session.messages.some(x=>x.id===m.id))state.session.messages.push(m);
  const box=$('#messages'), transcript=$('#transcript');if(!box||$(`[data-message="${m.id}"]`,box))return;
  const nearBottom=transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight<100;
  $('.empty',box)?.remove();box.insertAdjacentHTML('beforeend',messageHTML(m));bindActions(box.lastElementChild);
  if(nearBottom)scrollToLatest();else $('[data-action=latest]').hidden=false;
  if($('#partial')){$('#partial').textContent='';$('#partial').hidden=true;}
}
function scrollToLatest() {
  const transcript=$('#transcript');if(transcript)transcript.scrollTop=transcript.scrollHeight;
  const jump=$('[data-action=latest]');if(jump)jump.hidden=true;
}
function bindConversation(canSpeak) {
  if(canSpeak)bindVoiceOptions({prefs:state.voicePrefs,getVoice:()=>state.voice,notify:toast,onVoiceChange:async dashscope_voice=>{
    if(state.guest)return;
    const session=await api(`/sessions/${state.session.id}/voice`,'PATCH',{dashscope_voice});
    state.session.voice=session.voice;
    if(state.voice)state.voice.voice=dashscope_voice;
    toast('Reply voice updated. It will apply to the next spoken reply.');
  },onManageVoices:customVoiceDialog});
  scrollToLatest();
  const transcript=$('#transcript');if(transcript)transcript.onscroll=()=>{$('[data-action=latest]').hidden=transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight<100;};
  const form=$('#message-form');if(!form)return;
  form.onsubmit=async e=>{
    e.preventDefault();const input=$('#message-input'),value=input.value.trim();if(!value)return;
    const button=$('button[type=submit]',form);button.disabled=true;
    try{
      if(!canSpeak){const m=await api(`/sessions/${state.session.id}/notes`,'POST',{content:value});appendMessage(m);}
      else if(state.socket?.readyState===WebSocket.OPEN){state.voice.thinking=true;state.voice.changed();state.socket.send(JSON.stringify({type:'input.text',content:value}));}
      else{
        const result=await api(`${state.guest?'/guest':''}/sessions/${state.session.id}/messages`,'POST',{content:value});
        appendMessage(result.user);appendMessage(result.assistant);state.voice?.speak(result.assistant.content);
      }
      input.value='';input.style.height='auto';scrollToLatest();
    }catch(err){toast(err.message);}finally{button.disabled=false;input.focus();}
  };
  $('#message-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit();}};
  $('#message-input').oninput=e=>{e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,140)+'px';};
}

function applyVoiceCatalogue(catalogue, selected=state.voicePrefs.voice) {
  if(!state.config.tts)return;
  state.config.tts.voices=catalogue.voices||[];
  state.voicePrefs.voices=state.config.tts.voices;
  state.voicePrefs.voice=selected||catalogue.default_voice||state.config.tts.default_voice;
  const select=$('#reply-voice');
  if(!select)return;
  select.replaceChildren(...state.voicePrefs.voices.map(voice=>{
    const option=document.createElement('option');
    option.value=voice.id;option.textContent=`${voice.name} · ${voice.description}`;
    option.selected=voice.id===state.voicePrefs.voice;
    return option;
  }));
  select.dispatchEvent(new Event('input',{bubbles:true}));
}

async function customVoiceDialog() {
  const catalogue=await api('/tts/voices');
  applyVoiceCatalogue(catalogue);
  const voices=catalogue.custom_voices||catalogue.voices.filter(voice=>voice.managed);
  const list=voices.length?`<div class="custom-voice-list">${voices.map(voice=>`<div class="custom-voice-row"><div><strong>${esc(voice.name)}</strong><small>${esc(voice.description)} · ${esc(voice.status||'OK')}</small></div><button type="button" class="icon-btn danger" data-delete-voice="${esc(voice.id)}" aria-label="Delete ${esc(voice.name)}" title="Delete custom voice">${icon('trash')}</button></div>`).join('')}</div>`:'<div class="custom-voice-empty">No custom voices have been created for this model.</div>';
  const warning=catalogue.management_error?`<div class="custom-voice-warning" role="status">${esc(catalogue.management_error)} Existing preset voices remain available. Check the voice-management endpoint/key before creating a voice.</div>`:'';
  const body=`<p class="dialog-help">Custom voices are tied to <span class="mono">${esc(catalogue.model)}</span>. Once created, they appear in Reply voice for every conversation.</p>${warning}
    <h3 class="custom-voice-section">Your custom voices</h3>${list}
    <h3 class="custom-voice-section">Clone a new voice</h3>
    <div class="custom-voice-sample"><p>Use one clear speaker with no music or overlap. A quiet 10–20 second recording works best; accepted range is 5–60 seconds and up to 10 MB.</p></div>
    <div class="two-col">${field('prefix','Voice name','','text','required maxlength="10" pattern="[A-Za-z0-9]+" placeholder="e.g. myvoice"')}
      <div class="form-field"><label for="f-language">Recording language</label><select id="f-language" name="language"><option value="zh">Chinese</option><option value="en">English</option><option value="ja">Japanese</option><option value="ko">Korean</option><option value="de">German</option><option value="fr">French</option><option value="ru">Russian</option></select></div></div>
    <div class="form-field"><label for="f-file">Voice sample</label><div class="file-picker">
      <input class="file-picker-input" id="f-file" name="file" type="file" required accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" aria-describedby="voice-file-name">
      <label class="btn file-picker-button" for="f-file">Choose audio file</label><span class="file-picker-name" id="voice-file-name" aria-live="polite">No file chosen</span>
    </div></div>
    <label class="check"><input type="checkbox" name="enable_preprocess" value="true"><span><strong>Improve a noisy recording</strong><small>Alibaba Cloud will reduce noise and enhance the sample. Leave off for clean recordings.</small></span></label>
    <p class="dialog-help">The sample is sent to Alibaba Cloud temporary storage for cloning and is not saved in Echooo. Alibaba automatically removes the temporary object after 48 hours.</p>`;
  const modal=openDialog('Custom voices',body,async fd=>{
    const file=fd.get('file');
    if(!file?.size)throw new Error('Choose a voice sample.');
    if(file.size>10*1024*1024)throw new Error('The voice sample must be 10 MB or smaller.');
    const result=await api('/tts/voices/clone','POST',fd);
    const created=result.voice.id;
    if(result.voice.status!=='OK'){
      applyVoiceCatalogue(result);
      toast('Custom voice created and is being reviewed. It will become selectable after Alibaba Cloud marks it ready.');
      return;
    }
    applyVoiceCatalogue(result,created);
    try{
      const session=await api(`/sessions/${state.session.id}/voice`,'PATCH',{dashscope_voice:created});
      state.session.voice=session.voice;if(state.voice)state.voice.voice=created;
      toast('Custom voice created and selected for the next spoken reply.');
    }catch(error){toast(`Custom voice created. Select it from Reply voice when ready. ${error.message}`);}
  },'Create voice',{className:'custom-voice-dialog'});
  const fileInput=$('#f-file',modal),fileName=$('#voice-file-name',modal);
  fileInput.onchange=()=>{fileName.textContent=fileInput.files?.[0]?.name||'No file chosen';};
  if(catalogue.management_available===false){
    const submit=$('button[type=submit]',modal);
    submit.disabled=true;
    submit.title='Configure Alibaba Cloud voice management before creating a voice.';
  }
  $$('[data-delete-voice]',modal).forEach(button=>button.onclick=()=>{
    const voiceId=button.dataset.deleteVoice;
    modal.close();
    openDialog('Delete custom voice?',`<p class="dialog-help">Delete <span class="mono">${esc(voiceId)}</span> from Alibaba Cloud? Conversations using it will return to the default voice. This cannot be undone.</p>`,async()=>{
      const result=await api(`/tts/voices/${encodeURIComponent(voiceId)}`,'DELETE');
      const selected=state.voicePrefs.voice===voiceId?result.default_voice:state.voicePrefs.voice;
      applyVoiceCatalogue(result,selected);
      if(state.session?.voice?.dashscope_voice===voiceId){state.session.voice.dashscope_voice=result.default_voice;if(state.voice)state.voice.voice=result.default_voice;}
      toast(`Custom voice deleted${result.reset_sessions?` · ${result.reset_sessions} conversation${result.reset_sessions===1?'':'s'} reset`:''}.`);
    },'Delete voice');
  });
}
function connect(sid,guest) {
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/sessions/${sid}?role=${guest?'guest':'owner'}`);
  ws.binaryType='arraybuffer';state.socket=ws;
  const voice=new Voice(ws,toast,()=>{if(state.voice===voice)renderVoice();});state.voice=voice;
  voice.canSpeak=guest||state.session?.mode==='private';
  Object.assign(voice,state.voicePrefs);
  ws.onopen=()=>{voice.configureOutput();renderVoice();};
  ws.onmessage=e=>{
    if(state.socket!==ws)return;
    if(e.data instanceof ArrayBuffer){voice.pcm(e.data);return;}
    const m=JSON.parse(e.data);
    if(m.type==='message')appendMessage(m.message);
    if(m.type==='speech.checked')voice.speak(m.content);
    if(m.type==='playback.stop'){voice.thinking=false;voice.stopPlayback();if($('#room-state'))$('#room-state').textContent='Connected';}
    if(m.type==='audio.start')voice.preparePlayback(m.sample_rate);
    if(m.type==='audio.end')voice.finishPlayback();
    if(m.type==='audio.ready')voice.capture(m.sample_rate);
    if(m.type==='audio.error')voice.fail(m.message,'microphone');
    if(m.type==='transcript.partial'&&$('#partial')){$('#partial').textContent=m.content;$('#partial').hidden=!m.content;}
    if(m.type==='transcript.final'&&$('#message-input')){
      const input=$('#message-input');input.value=(input.value.trim()+' '+m.content).trim().slice(0,6000);input.dispatchEvent(new Event('input'));
      $('#partial').textContent='';$('#partial').hidden=true;
    }
    if(m.type==='session.state'){voice.thinking=m.state==='thinking';voice.changed();if($('#room-state'))$('#room-state').textContent=voice.thinking?'Checking reply':'Connected';}
    if(m.type==='session.ready'){if($('#room-state'))$('#room-state').textContent='Connected';renderVoice();}
    if(m.type==='error'){
      voice.thinking=false;
      if(m.code==='tts_unavailable'&&voice.enabled)voice.fail(m.message);
      else if(m.code!=='tts_unavailable')toast(m.message);
      renderVoice();
    }
    if(m.type==='session.closed'){voice.close();toast(m.message);if(state.guest){state.session.status='ended';renderGuest();}else refreshSession();}
  };
  ws.onclose=()=>{voice.close();if(state.socket===ws){if($('#room-state'))$('#room-state').textContent='Disconnected';renderVoice();}};
  ws.onerror=()=>{voice.close();renderVoice();};
  renderVoice();
}
function disconnect() {clearInterval(poll);poll=null;state.voice?.close();state.voice=null;if(state.socket){state.socket.onmessage=null;state.socket.onerror=null;state.socket.onclose=null;state.socket.close();state.socket=null;}}

function domainDialog(edit=false) {
  const d=edit?state.domains.find(x=>x.id===state.route[1]):null;
  const modal=openDialog(edit?'Manage domain':'Add domain',field('name','Domain name',d?.name||'','text','required maxlength="60" placeholder="e.g. Product research"')+area('description','Description',d?.description||'','maxlength="1000" placeholder="What information belongs in this domain?"')+`<div class="form-field"><label for="f-color">Label color</label><select name="color" id="f-color">${[['sage','Sage'],['blue','Blue'],['amber','Amber'],['violet','Violet'],['rose','Rose'],['slate','Slate']].map(([v,n])=>`<option value="${v}" ${d?.color===v?'selected':''}>${n}</option>`).join('')}</select></div>${edit?'<p class="dialog-help">Changes end conversations using this domain.</p><button type="button" class="btn danger" id="delete-domain">Delete this domain</button>':''}`,async fd=>{
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
  return field('title','Title',m.title||'','text','required maxlength="150"')+area('content','Memory',m.content||'','required maxlength="12000"')+`<div class="form-field"><label for="f-visibility">Visibility</label><select name="visibility" id="f-visibility"><option value="private" ${m.visibility!=='shareable'?'selected':''}>Private</option><option value="shareable" ${m.visibility==='shareable'?'selected':''}>Shareable</option></select><p class="dialog-help">Shareable memories are available in project meetings.</p></div><details class="inline-help" ${m.expires_at||m.audiences?.length?'open':''}><summary>Audience & expiry</summary>`+field('audiences','Allowed audiences',(m.audiences||[]).join(', '),'text','placeholder="Optional · Client, Team"')+field('expires_at','Expires at',exp,'datetime-local')+'<p class="dialog-help">Audience restrictions exclude a memory from meetings. Delegations still require their own disclosure permissions.</p></details>';
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
  openDialog('Add source',field('title','Source title','','text','required maxlength="150"')+area('content','Source content','','required maxlength="100000"')+'<p class="dialog-help">Private until extracted memories are reviewed.</p>',async fd=>{
    await api(`/domains/${state.route[1]}/sources`,'POST',Object.fromEntries(fd));toast('Source saved. You can now extract memories.');await renderRoute();
  },'Save source');
}
function uploadDialog() {
  openDialog('Upload source',field('file','Choose a file','','file','required accept=".txt,.md,.csv,.json,.pdf,.docx"')+'<p class="dialog-help">Up to 5 MB · Text-based PDF, DOCX, TXT, MD, CSV or JSON.</p>',async(fd)=>{
    await api(`/domains/${state.route[1]}/upload`,'POST',fd);toast('Source uploaded.');await renderRoute();
  },'Upload');
}
let startingChat=false;
async function quickChat() {
  if(startingChat)return;
  startingChat=true;
  try {
    const result=await api('/sessions/quick-chat','POST');
    if(state.session?.id!==result.id)navigate(`sessions/${result.id}`);
    else {toast('Your empty conversation is ready.');$('.shell')?.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');$('#message-input')?.focus();}
  } finally {startingChat=false;}
}
function saveChatMemoryDialog(messageId) {
  const session=state.session,messages=session.messages.filter(m=>m.role==='owner');
  if(!messages.length){toast('Send a message first, then choose what to save.');return;}
  const domains=state.domains.filter(d=>!session.domain_ids.length||session.domain_ids.includes(d.id));
  const selected=messages.find(m=>m.id===messageId)||messages[messages.length-1];let createdDomainId=null;
  const destination=domains.length?`<div class="form-field"><label for="f-destination">Destination domain</label><select id="f-destination" name="domain_id">${domains.map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div>`:field('domain_name','Create a destination domain','','text','required maxlength="60"');
  const modal=openDialog('Save a memory for review',destination+`<div class="form-field"><label for="f-evidence">Your source message</label><select id="f-evidence" name="message_id">${messages.map(m=>`<option value="${m.id}" ${m.id===selected.id?'selected':''}>${esc(m.content.slice(0,80))}</option>`).join('')}</select></div>`+field('title','Memory title',selected.content.slice(0,60),'text','required maxlength="150"')+area('content','Information to remember',selected.content,'required maxlength="12000"')+'<p class="dialog-help">This creates a proposal in the chosen domain. It is not available as a memory until you review it. The active chat does not gain access to that domain.</p>',async fd=>{
    let did=fd.get('domain_id')||createdDomainId;
    if(!did){const created=await api('/domains','POST',{name:fd.get('domain_name')});did=created.id;createdDomainId=did;state.domains.push({...created,memory_count:0,pending_count:0});}
    await api(`/sessions/${session.id}/memory-proposals`,'POST',{domain_id:did,message_id:fd.get('message_id'),title:fd.get('title'),content:fd.get('content')});
    toast('Memory proposed. Review it before it becomes available to the assistant.');
  },'Send for review');
  $('#f-evidence',modal).onchange=e=>{const m=messages.find(m=>m.id===e.target.value);$('#f-title',modal).value=m.content.slice(0,60);$('#f-content',modal).value=m.content;};
}
async function privateSessionDialog(changingContext=false) {
  const initial=state.route[0]==='domain'?[state.route[1]]:changingContext?(state.session?.domain_ids||[]):state.domains.filter(d=>d.name==='default').map(d=>d.id);
  const memories=(await Promise.all(state.domains.map(d=>api(`/domains/${d.id}/memories`)))).flat().filter(m=>!m.expires_at||m.expires_at>Date.now()/1000);
  const readIds=memories.filter(m=>!changingContext||!initial.includes(m.domain_id)||state.session.read_ids.includes(m.id)).map(m=>m.id);
  const learning=changingContext?state.session.allow_learning:initial.length>0;
  const modal=openDialog('Choose conversation domains',privateContextForm(state.domains,memories,initial,learning,{esc,icon}),async fd=>{
    const domains=fd.getAll('domains'),read=fd.getAll('read_ids');
    if(domains.length>12)throw new Error('Choose up to 12 domains for one conversation.');
    if(read.length>100)throw new Error('Choose up to 100 memories under Memory access.');
    const result=await api('/sessions','POST',{mode:'private',title:'New conversation',domain_ids:domains,read_ids:read,disclose_ids:[],
      write_domain_id:fd.has('allow_learning')?fd.get('write_domain_id'):null,allow_learning:fd.has('allow_learning'),
      action_policy:'none',goal:fd.get('goal')||''});
    toast('Conversation started with your selected domains.');navigate(`sessions/${result.id}`);
  },'Start conversation',{className:'context-picker-dialog',focusSelector:'input[name=domains],#without-memory'});
  bindPrivateContext(modal,state.domains,memories,readIds,{esc,domainName});
  if(changingContext&&state.session.write_domain_id)$('#f-write',modal).value=state.session.write_domain_id;
}
async function sessionDialog(mode, changingContext=false) {
  if(mode==='private')return privateSessionDialog(changingContext);
  if(!state.domains.length){toast(mode==='private'?'You can chat without domains. Add one when you want to use personal memories.':'Create a domain to authorize a delegation.');domainDialog();return;}
  const initial=state.route[0]==='domain'?[state.route[1]]:changingContext?(state.session?.domain_ids||[]):mode==='private'?state.domains.filter(d=>d.name==='default').map(d=>d.id):[];
  const all=(await Promise.all(state.domains.map(d=>api(`/domains/${d.id}/memories`)))).flat();
  const body=(mode==='delegate'?field('title','Conversation title','','text','required maxlength="120" placeholder="Discuss project progress with a client"'):'<p class="dialog-help">Quick chats use default. Choose domains for a different context, or deselect all to chat without memory. A new chat starts without previous conversation text.</p>')+
    (mode==='delegate'?field('audience','Audience','','text','required maxlength="80" placeholder="e.g. Client or Team"'):'')+
    `<fieldset><legend>Active domains</legend>${state.domains.map(d=>`<label class="check"><input type="checkbox" name="domains" value="${d.id}" ${initial.includes(d.id)?'checked':''}><span>${esc(d.name)}</span></label>`).join('')}</fieldset>`+
    `<fieldset><legend>${mode==='private'?'Memories available to read':'Read and disclosure permissions'}</legend><p class="dialog-help">${mode==='private'?'Used only in this private conversation.':'Guests can access only memories marked Disclose.'}</p><div class="fact-picker" id="fact-picker"></div></fieldset>`+
    `<div class="two-col"><div class="form-field"><label for="f-write">Save proposed memories to</label><select id="f-write" name="write_domain_id"></select></div><div class="form-field"><label for="f-duration">Authorization duration</label><select name="duration_minutes" id="f-duration"><option value="30">30 minutes</option><option value="60" selected>1 hour</option><option value="180">3 hours</option><option value="1440">24 hours</option></select></div></div>`+
    area('goal','Conversation goal (do not include secrets)','','maxlength="2000" placeholder="What would you like your assistant to accomplish?"')+
    `<label class="check"><input type="checkbox" name="allow_learning" ${mode==='delegate'||(changingContext&&state.session?.allow_learning)||initial.some(id=>state.domains.find(d=>d.id===id)?.name==='default')?'checked':''}><span>Propose memories when the conversation ends<small>Review before saving.</small></span></label>`+
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
  openDialog('Review memory update',`<p class="dialog-help">Save to ${esc(domainName(p.domain_id))}</p>`+memoryFields({...p,visibility:'private',audiences:[]})+`<div class="form-field"><label for="f-target">Save as</label><select name="target_id" id="f-target"><option value="">Add a new memory</option>${memories.map(m=>`<option value="${m.id}" ${m.id===p.target_id?'selected':''}>Replace: ${esc(m.title)} · v${m.version}</option>`).join('')}</select></div><details><summary>Evidence</summary>${p.evidence.map(e=>`<div class="evidence">${esc(e.speaker||'Imported source')}: ${esc(e.content)}${e.meeting_id?` <a href="#meetings/${encodeURIComponent(e.meeting_id)}">Open source meeting</a>`:''}</div>`).join('')}</details>`,async fd=>{
    const target=memories.find(m=>m.id===fd.get('target_id'));
    await api(`/proposals/${pid}/review`,'POST',{...memoryData(fd),decision:'approve',target_id:target?.id||null,expected_version:target?.id===p.target_id?p.expected_version:target?.version||null});
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
  enhanceSelects(root);
  $$('[data-action]',root).forEach(b=>b.onclick=async()=>{
    const action=b.dataset.action,id=b.dataset.id;
    try{
      const menu=b.closest('.toolbar-menu');if(menu){menu.open=false;$('summary',menu)?.focus();}
      if(action==='menu'){const open=$('.shell').classList.toggle('menu-open');b.setAttribute('aria-expanded',String(open));}
      if(action==='new-domain')domainDialog();
      if(action==='edit-domain')domainDialog(true);
      if(action==='new-memory')memoryDialog();
      if(action==='edit-memory')memoryDialog(id);
      if(action==='versions')await versionsDialog(id);
      if(action==='new-source')sourceDialog();
      if(action==='upload')uploadDialog();
      if(action==='quick-chat'){b.disabled=true;try{await quickChat();}finally{b.disabled=false;}}
      if(action==='rename-session')renameSessionDialog(id);
      if(action==='delete-session')deleteSessionDialog(id);
      if(action==='new-private')await sessionDialog('private');
      if(action==='choose-domains')await sessionDialog('private',true);
      if(action==='save-chat-memory')saveChatMemoryDialog(id);
      if(action==='context')openContext();
      if(action==='pin-context')pinContext();
      if(action==='close-context')$('#context-drawer')?.close();
      if(action==='latest')scrollToLatest();
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
      if(action==='voice'){
        if(state.voice?.active){state.voice.end();return;}
        if(!state.voice||state.socket?.readyState!==WebSocket.OPEN||state.voice.closed){disconnect();connect(state.session.id,state.guest);if(!state.guest)poll=setInterval(refreshSession,3500);toast('Reconnecting. Click Start voice when connected.');return;}
        if((state.guest?state.session.stt:state.config.providers?.stt)==='mock'){state.voice.fail('Microphone requires a live speech recognition service. You can still type messages.','microphone');return;}
        await state.voice.start();
      }
      if(action==='pause-mic')await state.voice?.pauseMic();
      if(action==='mute-voice'){state.voicePrefs.muted=!state.voice.muted;state.voice.setMuted(state.voicePrefs.muted);}
      if(action==='interrupt')state.voice?.interrupt();
      if(action==='dismiss-audio-error'){state.voice.error=null;state.voice.changed();}
      if(action==='retry-audio'){
        const voice=state.voice;if(!voice)return;
        if(voice.error?.kind==='microphone'){$('[data-action=voice]').click();return;}
        if(!voice.active||voice.closed)return;
        try{await voice.unlockPlayback();voice.error=null;voice.configureOutput();voice.send({type:'playback.retry'});voice.changed();}
        catch{voice.fail('Audio playback is blocked. Check your browser sound permissions.');}
      }
    }catch(err){toast(err.message);b.disabled=false;if(action==='extract')b.textContent='Extract memories';}
  });
}
function authPage(needsSetup) {
  $('#app').innerHTML=`<div class="auth-appearance">${themePicker()}</div><main class="auth-page" id="main">${brand}<p class="eyebrow">Personal agent workspace</p><h1>${needsSetup?'Create your private workspace':'Welcome back'}</h1><form id="auth-form"><div class="form-error" role="alert"></div>${field('name','Username','','text','required minlength="2" maxlength="60" autocomplete="username"')}${field('password','Password','','password',`required maxlength="200" autocomplete="${needsSetup?'new-password':'current-password'}"`)}<button class="btn primary" type="submit">${needsSetup?'Create workspace':'Sign in'} ${icon('arrow')}</button></form></main>`;
  $('#auth-form').onsubmit=async e=>{e.preventDefault();const b=$('button',e.target);b.disabled=true;try{const d=await api(needsSetup?'/auth/setup':'/auth/login','POST',Object.fromEntries(new FormData(e.target)));state.user=d.user;await startOwner();}catch(err){$('.form-error',e.target).textContent=err.message;}finally{b.disabled=false;}};
}
function renderGuest() {
  const s=state.session;
  $('#app').innerHTML=`<main class="guest-shell guest-chat" id="main"><header class="guest-header">${brand}<div class="guest-title"><h1>${esc(s.title)}</h1><small>Authorized guest conversation</small></div><span class="tag green">AI assistant</span>${themePicker()}</header><div class="room-layout">${conversation(s,true)}</div></main>`;
  bindActions();bindConversation(true);
}
async function startGuest(sid) {
  state.guest=true;
  try{state.session=await api(`/guest/sessions/${sid}`);renderGuest();connect(sid,true);}catch(err){$('#app').innerHTML=`<main class="auth-page" id="main">${brand}<h1>Invitation expired or conversation ended</h1><p>${esc(err.message)}</p><p>Ask the owner for a new authorization.</p></main>`;}
}
async function startOwner() {
  state.config=await api('/config');
  if(state.config.tts?.custom_voice_management){
    try{applyVoiceCatalogue(await api('/tts/voices'));}catch{/* Presets remain usable; management shows the retry error on demand. */}
  }
  await renderRoute();window.addEventListener('hashchange',renderRoute);
}
async function boot() {
  if(location.pathname==='/invite'){
    const token=location.hash.slice(1);history.replaceState(null,'','/invite');
    $('#app').innerHTML=`<div class="auth-appearance">${themePicker()}</div><main class="auth-page" id="main">${brand}<p class="eyebrow">Invitation</p><h1>Join an authorized conversation</h1><p>You will talk with the Echooo AI assistant. The owner can view this conversation, and it may produce memory proposals for their review.</p><button class="btn primary" id="join">Join conversation ${icon('arrow')}</button><p class="form-error" role="alert"></p></main>`;
    $('#join').onclick=async()=>{const b=$('#join');b.disabled=true;try{const r=await api('/guest/join','POST',{token});history.replaceState(null,'',`/room/${r.session_id}`);await startGuest(r.session_id);}catch(err){$('.form-error').textContent=err.message;b.disabled=false;}};return;
  }
  if(location.pathname.startsWith('/room/')){await startGuest(location.pathname.split('/')[2]);return;}
  try{const auth=await api('/auth');if(!auth.user)authPage(auth.needs_setup);else{state.user=auth.user;await startOwner();}}catch(err){$('#app').innerHTML=empty('Unable to connect to the workspace',err.message);}
}
window.addEventListener('resize',()=>{const panel=$('#voice-options-panel');if(panel?.matches(':popover-open'))panel.hidePopover();});
document.addEventListener('click',e=>{$$('.toolbar-menu[open]').filter(menu=>!menu.contains(e.target)).forEach(menu=>menu.open=false);const shell=$('.shell.menu-open');if(shell&&!e.target.closest('.sidebar,[data-action=menu]')){shell.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$$('.toolbar-menu[open]').forEach(menu=>{menu.open=false;$('summary',menu)?.focus();});if($('#context-drawer')?.classList.contains('pinned')&&!$('#modal')?.open){$('#context-drawer').close();e.preventDefault();}$('.shell')?.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');}});
window.addEventListener('pagehide',disconnect);
window.matchMedia('(max-width:1100px)').addEventListener('change',e=>{if(e.matches&&$('#context-drawer')?.classList.contains('pinned'))pinContext();});
boot();
