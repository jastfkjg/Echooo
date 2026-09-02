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
const brand = `<a class="brand" href="/" aria-label="Echooo 工作区">${icon('wave')}<span>echooo<span class="muted">.</span></span></a>`;
const dt = t => new Date(t * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const roleName = {assistant:'Echooo',guest:'受邀参与者',owner:'你',owner_approved:'本人已确认',private_note:'私人笔记'};
const statusName = s => ({active:'进行中',ended:'已结束',revoked:'已撤销'}[s.status] || s.status) + (s.status==='active' && s.expires_at < Date.now()/1000 ? ' · 已过期' : '');
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
    throw new Error(detail || '操作未完成，请重试。');
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
function openDialog(title,body,submit,label='保存') {
  const modal=$('#modal');
  modal.innerHTML=`<form id="dialog-form"><div class="dialog-head"><h2 id="dialog-title">${esc(title)}</h2><button class="icon-btn" type="button" data-close aria-label="关闭">${icon('close')}</button></div><div class="dialog-body"><div class="form-error" role="alert"></div>${body}</div><div class="dialog-footer"><button type="button" class="btn subtle" data-close>取消</button><button type="submit" class="btn primary">${esc(label)}</button></div></form>`;
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
const domainName=id=>state.domains.find(d=>d.id===id)?.name || '已移除领域';
function navigate(hash) { if(location.hash==='#'+hash) renderRoute(); else location.hash=hash; }
function shell(body,crumb='我的领域') {
  const pending=state.proposals.filter(p=>p.status==='pending').length;
  $('#app').innerHTML=`<div class="shell"><aside class="sidebar">${brand}<a class="navlink ${!state.route[0]?'active':''}" href="#">${icon('grid')}<span>我的领域</span></a><a class="navlink ${state.route[0]==='sessions'?'active':''}" href="#sessions">${icon('chat')}<span>委托与会话</span><span class="count">${state.sessions.length||''}</span></a><a class="navlink ${state.route[0]==='review'?'active':''}" href="#review">${icon('review')}<span>待审核</span>${pending?`<span class="count">${pending}</span>`:''}</a><div class="label">知识领域 · ${state.domains.length}</div><nav class="domain-nav" aria-label="领域">${state.domains.map(d=>`<a class="navlink ${state.route[1]===d.id?'active':''}" href="#domain/${d.id}/memories"><i class="domain-dot ${esc(d.color)}"></i><span class="name">${esc(d.name)}</span><span class="count">${d.memory_count}</span></a>`).join('')}</nav><button class="navlink" data-action="new-domain">${icon('plus')}<span>添加领域</span></button><div class="side-bottom"><a class="navlink ${state.route[0]==='settings'?'active':''}" href="#settings">${icon('settings')}<span>工作区设置</span></a><div class="profile"><span class="avatar">${esc(state.user.name.slice(0,1).toUpperCase())}</span><div><strong>${esc(state.user.name)}</strong><small>私人工作区</small></div></div></div></aside><main class="main" id="main"><header class="topbar"><div class="path"><button class="icon-btn mobile-menu" data-action="menu" aria-label="打开导航">${icon('menu')}</button><span>个人工作区</span><span>/</span><strong>${esc(crumb)}</strong></div><span class="status">领域隔离已启用</span></header><div class="workspace">${body}</div></main></div>`;
  bindActions();
}
const demoBanner=()=>state.config.demo?`<div class="banner">${icon('info')}<span>本地演示模式：使用已授权记忆生成示例回复。连接真实模型后可进行自然对话，数据与授权流程保持一致。</span></div>`:'';

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
  } catch(err){shell(empty('暂时无法打开',err.message,`<button class="btn" data-action="refresh">重新加载</button>`),'加载失败');}
}
function renderHome() {
  shell(`<div class="heading"><div><p class="eyebrow">Your knowledge, your boundaries</p><h1>我的领域</h1><p>按你的生活与工作方式组织记忆。每一次委托，由你决定助手可以使用什么。</p></div><button class="btn primary" data-action="new-domain">${icon('plus')}添加领域</button></div>${demoBanner()}${state.domains.length?`<div class="grid-summary"><div><small>知识领域</small><strong>${state.domains.length}</strong></div><div><small>已确认记忆</small><strong>${state.domains.reduce((n,d)=>n+d.memory_count,0)}</strong></div><div><small>等待你审核</small><strong>${state.proposals.filter(p=>p.status==='pending').length}</strong></div></div><div class="list-head"><h3>领域列表</h3><small>领域之间不会自动共享记忆</small></div>${state.domains.map(d=>`<a class="session-row" href="#domain/${d.id}/memories"><div><h3><i class="domain-dot ${esc(d.color)}"></i> ${esc(d.name)}</h3><p class="muted">${esc(d.description||'尚未添加领域说明')}</p><div class="meta"><span>${d.memory_count} 条记忆</span><span>${d.pending_count} 条待审核</span></div></div>${icon('arrow')}</a>`).join('')}`:empty('从你的第一个领域开始','一个项目、一项兴趣，或一段生活安排。领域名称和边界都由你定义。',`<button class="btn primary" data-action="new-domain">${icon('plus')}创建第一个领域</button>`)} `);
}
function renderDomain(d,tab) {
  const body=`<div class="heading"><div><p class="eyebrow">Knowledge space</p><h1>${esc(d.name)}</h1><p>${esc(d.description||'在这个领域中，整理资料、确认记忆，并为每次交流选择授权。')}</p></div><div class="actions"><button class="btn" data-action="new-private">${icon('chat')}私下交流</button><button class="btn primary" data-action="new-delegate">${icon('arrow')}创建委托</button><button class="icon-btn" data-action="edit-domain" aria-label="管理领域">${icon('settings')}</button></div></div><nav class="tabs" aria-label="领域内容"><a class="${tab==='memories'?'active':''}" href="#domain/${d.id}/memories">已确认记忆 <small>${state.memories.length}</small></a><a class="${tab==='sources'?'active':''}" href="#domain/${d.id}/sources">原始资料 <small>${state.sources.length}</small></a></nav>${tab==='sources'?`<div class="list-head"><small>原始资料仅你可见。提取的记忆需要审核后才能使用。</small><div class="actions"><button class="btn" data-action="upload">${icon('upload')}上传文件</button><button class="btn primary" data-action="new-source">${icon('plus')}粘贴资料</button></div></div><div id="source-list">${sourceList()}</div>`:`<div class="list-head"><input class="search" id="memory-search" aria-label="搜索本领域记忆" placeholder="搜索这个领域的记忆…"><button class="btn primary" data-action="new-memory">${icon('plus')}添加记忆</button></div><div id="memory-list">${memoryList()}</div>`}`;
  shell(body,d.name);
  if($('#memory-search')) $('#memory-search').oninput=e=>{state.filter=e.target.value;$('#memory-list').innerHTML=memoryList();bindActions($('#memory-list'));};
}
function memoryList() {
  const filtered=state.memories.filter(m=>(m.title+m.content).toLowerCase().includes(state.filter.toLowerCase()));
  if(!filtered.length)return empty(state.memories.length?'没有匹配的记忆':'这里还没有记忆',state.memories.length?'换个关键词试试。':'添加你确认的信息，或从原始资料提取。新记忆默认仅你可见。','', 'file');
  return filtered.map(m=>`<article class="memory-row"><span class="row-symbol">${icon(m.visibility==='private'?'lock':'file')}</span><div><h3>${esc(m.title)}</h3><div class="excerpt">${esc(m.content)}</div><div class="meta"><span class="tag ${m.visibility==='shareable'?'green':''}">${icon(m.visibility==='private'?'lock':'shield')}${m.visibility==='private'?'仅本人':'可授权披露'}</span>${m.audiences.length?`<span>对象：${esc(m.audiences.join('、'))}</span>`:''}<span>v${m.version}</span><span>${dt(m.updated_at)}</span>${m.expires_at?`<span class="${m.expires_at<Date.now()/1000?'tag warn':''}">${m.expires_at<Date.now()/1000?'已过期':'有效至 '+dt(m.expires_at)}</span>`:''}</div></div><div class="row-actions"><button class="icon-btn" data-action="edit-memory" data-id="${m.id}" aria-label="编辑 ${esc(m.title)}">${icon('edit')}</button><button class="icon-btn" data-action="versions" data-id="${m.id}" aria-label="查看版本与来源">${icon('history')}</button></div></article>`).join('');
}
function sourceList() {
  if(!state.sources.length)return empty('为这个领域添加资料','支持文字、Markdown、PDF、DOCX、CSV 和 JSON。资料不会直接向受邀者开放。','', 'upload');
  return state.sources.map(s=>`<article class="memory-row"><span class="row-symbol">${icon('file')}</span><div><h3>${esc(s.title)}</h3><p class="excerpt">${esc(s.content.slice(0,180))}${s.content.length>180?'…':''}</p><div class="meta"><span class="tag">原始资料 · 仅本人</span><span>${s.content.length.toLocaleString()} 字符</span><span>${dt(s.created_at)}</span></div></div><div class="row-actions"><button class="btn" data-action="extract" data-id="${s.id}">提取记忆</button><button class="icon-btn" data-action="delete-source" data-id="${s.id}" aria-label="删除资料">${icon('trash')}</button></div></article>`).join('');
}
function renderSessions() {
  shell(`<div class="heading"><div><p class="eyebrow">Delegated conversations</p><h1>委托与会话</h1><p>每段交流都有独立的授权范围。结束后，查看记录并审核新的记忆。</p></div><button class="btn primary" data-action="new-delegate">${icon('plus')}创建委托</button></div>${demoBanner()}${state.sessions.length?state.sessions.map(s=>`<a class="session-row" href="#sessions/${s.id}"><div><h3>${esc(s.title)}</h3><div class="meta"><span>${s.mode==='private'?'私人交流':esc(s.audience)}</span><span>${esc(s.domain_ids.map(domainName).join(' / '))}</span><span>${dt(s.created_at)}</span></div></div><span class="tag ${s.status==='active'?'green':''}">${esc(statusName(s))}</span></a>`).join(''):empty('还没有会话','选择一个领域，开始私人交流，或让助手代表你与他人沟通。','', 'chat')}`,'委托与会话');
}
function renderReview() {
  const pending=state.proposals.filter(p=>p.status==='pending');
  shell(`<div class="heading"><div><p class="eyebrow">Memory review</p><h1>待审核 <span class="muted">${pending.length}</span></h1><p>检查来源、纠正表述，再决定是否记住。新的记忆默认仅你可见。</p></div></div>${pending.length?pending.map(p=>`<article class="review-row"><div class="review-header"><div><span class="tag">${esc(domainName(p.domain_id))}</span><h3>${esc(p.title)}</h3></div><div class="actions"><button class="btn subtle" data-action="reject-proposal" data-id="${p.id}">忽略</button><button class="btn primary" data-action="review-proposal" data-id="${p.id}">审核并保存 ${icon('arrow')}</button></div></div><p>${esc(p.content)}</p><details><summary>查看原始依据 · ${p.evidence.length} 条</summary>${p.evidence.map(e=>`<div class="evidence"><strong>${esc(e.speaker||'导入资料')}</strong>：${esc(e.content)}</div>`).join('')}</details><small>${p.session_id?'来自会话':'来自资料提取'} · ${dt(p.created_at)} · 尚未用于助手回答</small></article>`).join(''):empty('当前没有待审核更新','导入资料或结束一段交流后，新的记忆建议会出现在这里。','', 'check')}<p class="muted"><small>已处理 ${state.proposals.length-pending.length} 条更新。对方的意见不会自动成为你的决定。</small></p>`,'待审核');
}
function renderSettings() {
  shell(`<div class="heading"><div><p class="eyebrow">Workspace</p><h1>工作区设置</h1><p>查看运行状态，管理你的数据与登录。</p></div></div>${demoBanner()}<section class="settings-section"><div><h3>模型连接</h3><p>识别：${esc(state.config.providers?.stt)} · 推理：${esc(state.config.providers?.llm)} · 合成：${esc(state.config.providers?.tts)}</p><p>服务连接通过部署配置管理；API 密钥保留在服务端。</p></div><span class="tag">${state.config.demo?'本地演示':'已配置服务'}</span></section><section class="settings-section"><div><h3>持久化数据</h3><p>${state.config.database==='sqlite'?'本地 SQLite':'PostgreSQL · 行级权限'} · 已确认记忆保留版本与来源。</p></div></section><section class="settings-section"><div><h3>导出我的数据</h3><p>包含领域、资料、记忆、会话和审核记录。请在私人环境保存。</p></div><a class="btn" href="/api/export" download>${icon('download')}导出 JSON</a></section><section class="settings-section"><div><h3>当前登录：${esc(state.user.name)}</h3><p>退出将使当前登录凭证失效。</p></div><button class="btn" data-action="logout">${icon('logout')}退出登录</button></section>`,'工作区设置');
}
function messageHTML(m) {
  return `<article class="message ${esc(m.role)}" data-message="${m.id}"><div class="speaker"><strong>${esc(roleName[m.role]||m.role)}</strong><time>${dt(m.created_at)}</time>${m.role==='private_note'?'<span>仅你可见</span>':''}</div><div class="text">${esc(m.content)}</div>${m.citations?.length?`<div class="citations">依据 ${m.citations.length} 条获准记忆</div>`:''}</article>`;
}
function conversation(s, canSpeak) {
  return `<section class="conversation" aria-label="交流记录"><div class="conversation-top"><span>${canSpeak?'与 Echooo 交流':'实时旁听 · 私人监督'}</span><span class="status" id="room-state">${esc(statusName(s))}</span></div><div class="transcript" id="transcript" role="log" aria-label="对话记录" aria-live="polite">${s.messages.length?s.messages.map(messageHTML).join(''):empty('等待交流开始',canSpeak?'可以输入文字，或开启麦克风。':'创建邀请并交给对方，交流内容会同步到这里。','', 'wave')}</div><div class="composer">${s.status==='active'?`<form id="message-form"><textarea id="message-input" aria-label="${canSpeak?'交流内容':'私人笔记'}" placeholder="${canSpeak?'输入你想说的话…':'记录私人笔记，不会发送给对方…'}" maxlength="6000" required></textarea><button class="btn primary" type="submit">${canSpeak?'发送':'记下'} ${icon('arrow')}</button></form><div class="foot"><span id="partial" class="muted"><small>${canSpeak?'个人事实来自本次授权；新的决定需要本人确认。':'笔记不会进入对外回复或自动记忆提取。'}</small></span>${canSpeak?`<div class="actions"><label><input type="checkbox" id="speak-toggle">朗读回复</label><button class="icon-btn" data-action="mic" aria-label="开启麦克风">${icon('mic')}</button><button class="icon-btn" data-action="interrupt" aria-label="打断回复">${icon('stop')}</button></div>`:''}</div>`:`<p class="muted"><small>会话已经结束。新的交流需要重新授权。</small></p>`}</div></section>`;
}
function inspector(s) {
  const pending=s.actions.filter(a=>a.status==='pending');
  return `<h3>${icon('shield')} 本次授权</h3><dl><dt>交流对象</dt><dd>${esc(s.audience||'仅本人')}</dd><dt>读取领域</dt><dd>${esc(s.domain_ids.map(domainName).join('、'))}</dd><dt>获准记忆</dt><dd>${s.read_ids.length} 条读取 · ${s.disclose_ids.length} 条可披露</dd><dt>记忆写入</dt><dd>${s.allow_learning?esc(domainName(s.write_domain_id))+' · 审核后保存':'不提取记忆'}</dd><dt>行动范围</dt><dd>${s.action_policy==='ask'?'新承诺需本人确认':'仅信息交流'}</dd><dt>有效至</dt><dd>${dt(s.expires_at)}</dd></dl>${s.goal?`<hr><h3>交流目标</h3><p class="muted pre">${esc(s.goal)}</p>`:''}<hr><h3>待你确认 ${pending.length?`· ${pending.length}`:''}</h3>${pending.length?pending.map(a=>`<div class="approval"><small>对方提出</small><p>${esc(a.request)}</p><button class="btn primary" data-action="decide" data-id="${a.id}" ${s.status!=='active'?'disabled':''}>处理请求</button></div>`).join(''):'<small>目前没有需要你决定的请求。</small>'}`;
}
function renderSession() {
  const s=state.session,active=s.status==='active' && s.expires_at>Date.now()/1000;
  if(!active && s.status==='active')s.status='expired';
  shell(`<div class="heading"><div><p class="eyebrow">${s.mode==='private'?'Private conversation':'Scoped delegation'}</p><h1>${esc(s.title)}</h1><p>${s.mode==='private'?'只有你参与的领域交流。':'助手以 AI 身份参与交流。你可以旁听、确认请求，并随时收回授权。'}</p></div><div class="actions">${active?`${s.mode==='delegate'?'<button class="btn" data-action="invite">'+icon('link')+'创建邀请</button>':''}<button class="btn" data-action="end-session">结束并回顾</button><button class="icon-btn" data-action="revoke-session" aria-label="立即撤销授权">${icon('shield')}</button>`:''}</div></div>${demoBanner()}<div class="room-layout">${conversation(s,s.mode==='private')}<aside class="inspector" id="inspector">${inspector(s)}</aside></div>${!active?summaryHTML(s):''}`,'委托与会话');
  bindConversation(s.mode==='private');
  if(active){ connect(s.id,false); poll=setInterval(refreshSession,3500); }
}
function summaryHTML(s) {
  return `<section class="review-row"><div class="review-header"><div><h2>会后回顾</h2><p>${s.summary.checked_replies||0} 条核验回复 · ${s.proposals.length} 条记忆建议</p></div><div class="actions">${s.status==='ended'&&s.allow_learning?'<button class="btn" data-action="retry-learning">提取记忆</button>':''}<a class="btn primary" href="#review">审核更新 ${icon('arrow')}</a></div></div><details><summary>参与者陈述与已确认决定</summary>${(s.summary.statements||[]).map(x=>`<div class="evidence"><strong>${esc(roleName[x.speaker]||x.speaker)}</strong>：${esc(x.text)}</div>`).join('')||'<p class="muted">没有陈述记录。</p>'}</details><details><summary>核验与授权记录 · ${s.audit.length}</summary><ul class="detail-list">${s.audit.map(a=>`<li>${dt(a.created_at)} · ${esc(a.kind)} ${a.detail.kind_result?'· '+esc(a.detail.kind_result):''}</li>`).join('')}</ul></details></section>`;
}
async function refreshSession() {
  if(!state.session||state.guest)return;
  try{
    const s=await api(`/sessions/${state.session.id}`); state.session=s;
    if(s.status!=='active'||s.expires_at<Date.now()/1000){disconnect();renderSession();return;}
    if($('#inspector')){$('#inspector').innerHTML=inspector(s);bindActions($('#inspector'));}
    s.messages.forEach(appendMessage);
  }catch(err){disconnect();toast(err.message);}
}
function appendMessage(m) {
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
    if(m.type==='session.state'&&$('#room-state'))$('#room-state').textContent=({thinking:'核验回复中',listening:'等待发言',speaking:'正在回复'}[m.state]||m.state)+(m.reply_ms?` · ${(m.reply_ms/1000).toFixed(1)}s`:'');
    if(m.type==='session.ready'&&$('#room-state'))$('#room-state').textContent='已连接';
    if(m.type==='error'){toast(m.message);$('[data-action=mic]')?.classList.remove('recording');}
    if(m.type==='session.closed'){state.voice?.close();toast(m.message);if($('#room-state'))$('#room-state').textContent='授权已结束';if(state.guest){state.session.status='ended';renderGuest();}else refreshSession();}
  };
  ws.onclose=()=>{voice.close();if(state.socket===ws&&$('#room-state'))$('#room-state').textContent='连接已断开';};
  ws.onerror=()=>toast('实时连接暂不可用，可以继续使用文字输入。');
}
function disconnect() {clearInterval(poll);poll=null;state.voice?.close();state.voice=null;if(state.socket){state.socket.onmessage=null;state.socket.onerror=null;state.socket.onclose=null;state.socket.close();state.socket=null;}}

function domainDialog(edit=false) {
  const d=edit?state.domains.find(x=>x.id===state.route[1]):null;
  const modal=openDialog(edit?'管理领域':'添加领域',field('name','领域名称',d?.name||'','text','required maxlength="60" placeholder="由你命名，如产品研究、音乐创作…"')+area('description','领域说明',d?.description||'','maxlength="1000" placeholder="这个领域包含哪些信息？"')+`<div class="form-field"><label for="f-color">标记颜色</label><select name="color" id="f-color">${[['sage','苔绿'],['blue','雾蓝'],['amber','琥珀'],['violet','淡紫'],['rose','玫瑰'],['slate','石灰']].map(([v,n])=>`<option value="${v}" ${d?.color===v?'selected':''}>${n}</option>`).join('')}</select></div>${edit?'<p class="dialog-help">修改领域会撤销使用该领域的现有会话，避免旧授权继续生效。</p><button type="button" class="btn danger" id="delete-domain">删除这个领域</button>':''}`,async fd=>{
    const result=await api(edit?`/domains/${d.id}`:'/domains',edit?'PUT':'POST',Object.fromEntries(fd));
    toast(edit?'领域已更新；相关会话授权已撤销。':'领域已创建。');navigate(`domain/${result.id}/memories`);
  },edit?'保存更改':'创建领域');
  if(edit)$('#delete-domain',modal).onclick=()=>{
    modal.close();openDialog('删除领域',`<p class="dialog-help">将删除「${esc(d.name)}」的资料、记忆、版本及相关会话记录，并停止正在进行的交流。由相关会话派生的记忆也会移除，可能涉及其他领域。此操作不能撤销。</p>`+field('confirm','输入领域名称确认','','text','required'),async fd=>{
      if(fd.get('confirm')!==d.name)throw new Error('名称不匹配。');
      await api(`/domains/${d.id}`,'DELETE');toast('领域及相关数据已删除。');navigate('');
    },'确认删除');
  };
}
function memoryFields(m={}) {
  const exp=m.expires_at?new Date(m.expires_at*1000-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16):'';
  return field('title','记忆标题',m.title||'','text','required maxlength="150"')+area('content','已确认的信息',m.content||'','required maxlength="12000"')+`<div class="two-col"><div class="form-field"><label for="f-visibility">披露范围</label><select name="visibility" id="f-visibility"><option value="private" ${m.visibility!=='shareable'?'selected':''}>仅本人</option><option value="shareable" ${m.visibility==='shareable'?'selected':''}>可在授权会话中披露</option></select></div>${field('expires_at','有效至（可选）',exp,'datetime-local')}</div>`+field('audiences','允许的交流对象（可选）',(m.audiences||[]).join('，'),'text','placeholder="逗号分隔，如客户、团队；留空表示由会话授权决定"')+'<p class="dialog-help">“可披露”不会自动向外开放。创建委托时仍需明确选中这条记忆。</p>';
}
function memoryData(fd) {
  return {title:fd.get('title'),content:fd.get('content'),visibility:fd.get('visibility'),
    audiences:fd.get('audiences').split(/[,，]/).map(x=>x.trim()).filter(Boolean),
    expires_at:fd.get('expires_at')?new Date(fd.get('expires_at')).getTime()/1000:null};
}
function memoryDialog(mid) {
  const m=state.memories.find(x=>x.id===mid);
  const modal=openDialog(m?'编辑记忆':'添加记忆',memoryFields(m)+(m?'<p class="dialog-help">修改记忆将撤销使用它的授权会话。</p><button type="button" class="btn danger" id="delete-memory">删除记忆</button>':''),async fd=>{
    const data=memoryData(fd);if(m)data.expected_version=m.version;
    await api(m?`/memories/${m.id}`:`/domains/${state.route[1]}/memories`,m?'PUT':'POST',data);
    toast(m?'记忆已更新。':'记忆已保存。');await renderRoute();
  });
  if(m)$('#delete-memory',modal).onclick=()=>{modal.close();openDialog('删除记忆','<p class="dialog-help">将同时删除记忆版本及曾使用此记忆的会话记录，停止相关交流。</p>',async()=>{await api(`/memories/${m.id}`,'DELETE');toast('记忆已删除。');await renderRoute();},'删除记忆');};
}
async function versionsDialog(mid) {
  const m=state.memories.find(x=>x.id===mid),versions=await api(`/memories/${mid}/versions`);
  const modal=openDialog('版本与来源',`<p class="dialog-help">${esc(m.title)} · 当前 v${m.version}</p>${versions.reverse().map(v=>`<article class="review-row"><strong>v${v.version}</strong> <small>${dt(v.created_at)}</small><p>${esc(v.snapshot.content)}</p><small>来源：${esc(v.snapshot.provenance?.kind==='owner'?'本人直接确认':'本人审核确认')}</small>${(v.snapshot.provenance?.evidence||[]).map(e=>`<div class="evidence">${esc(e.speaker||'原始资料')}：${esc(e.content)}</div>`).join('')}${v.version!==m.version?`<button type="button" class="btn" data-restore="${v.version}">恢复此版本内容</button>`:''}</article>`).join('')}`,async()=>{},'完成');
  $$('[data-restore]',modal).forEach(b=>b.onclick=()=>{const v=versions.find(v=>v.version===Number(b.dataset.restore));modal.close();openDialog('恢复记忆内容',memoryFields(v.snapshot),async fd=>{await api(`/memories/${mid}`,'PUT',{...memoryData(fd),expected_version:m.version});toast('已保存为新版本。');await renderRoute();},'确认恢复');});
}
function sourceDialog() {
  openDialog('添加原始资料',field('title','资料名称','','text','required maxlength="150"')+area('content','资料内容','','required maxlength="100000"')+'<p class="dialog-help">资料仅保存在当前领域。保存后可提取记忆，审核前不会用于对外回答。</p>',async fd=>{
    await api(`/domains/${state.route[1]}/sources`,'POST',Object.fromEntries(fd));toast('资料已保存，可以提取记忆。');await renderRoute();
  },'保存资料');
}
function uploadDialog() {
  openDialog('上传资料',field('file','选择文件','','file','required accept=".txt,.md,.csv,.json,.pdf,.docx"')+'<p class="dialog-help">最大 5 MB；PDF 需含可提取文字。资料将保存在当前领域，仅你可见。</p>',async(fd)=>{
    await api(`/domains/${state.route[1]}/upload`,'POST',fd);toast('资料已上传。');await renderRoute();
  },'上传');
}
async function sessionDialog(mode) {
  if(!state.domains.length){toast('请先创建一个领域。');domainDialog();return;}
  const initial=state.route[0]==='domain'?state.route[1]:state.domains[0].id;
  const all=(await Promise.all(state.domains.map(d=>api(`/domains/${d.id}/memories`)))).flat();
  const body=field('title','会话名称','','text',`required maxlength="120" placeholder="${mode==='private'?'整理最近的想法':'与客户讨论项目进度'}"`)+
    (mode==='delegate'?field('audience','交流对象','','text','required maxlength="80" placeholder="如客户、团队，需匹配记忆的对象限制"'):'')+
    `<fieldset><legend>开启的领域</legend>${state.domains.map(d=>`<label class="check"><input type="checkbox" name="domains" value="${d.id}" ${d.id===initial?'checked':''}><span>${esc(d.name)}</span></label>`).join('')}</fieldset>`+
    `<fieldset><legend>${mode==='private'?'允许读取的记忆':'本次可读取与可披露的记忆'}</legend><p class="dialog-help">${mode==='private'?'仅在这次私人交流中使用。':'对外回复模型只接收勾选“披露”的信息。私有或对象不匹配的记忆不能披露。'}</p><div class="fact-picker" id="fact-picker"></div></fieldset>`+
    `<div class="two-col"><div class="form-field"><label for="f-write">会后记忆写入</label><select id="f-write" name="write_domain_id"></select></div><div class="form-field"><label for="f-duration">授权有效期</label><select name="duration_minutes" id="f-duration"><option value="30">30 分钟</option><option value="60" selected>1 小时</option><option value="180">3 小时</option><option value="1440">24 小时</option></select></div></div>`+
    area('goal','交流目标（不要填写秘密）','','maxlength="2000" placeholder="希望助手帮助你完成什么？"')+
    `<label class="check"><input type="checkbox" name="allow_learning" checked><span>结束后提取记忆建议<small>只进入选定领域的待审核区，不自动修改已确认记忆。</small></span></label>`+
    (mode==='delegate'?`<div class="form-field"><label for="f-action">行动权限</label><select name="action_policy" id="f-action"><option value="ask">新承诺需我确认</option><option value="none">只交流信息，不受理决定</option></select></div>`:'')+
    '<p class="dialog-help">会话创建后授权范围固定。需要切换领域或扩大权限，请结束并创建新会话。</p>';
  const modal=openDialog(mode==='private'?'开始私人交流':'创建一次委托',body,async fd=>{
    const domains=fd.getAll('domains');if(!domains.length)throw new Error('至少选择一个领域。');
    const selected=fd.getAll('read_ids');const disclose=fd.getAll('disclose_ids');
    const result=await api('/sessions','POST',{title:fd.get('title'),mode,audience:fd.get('audience')||'',goal:fd.get('goal'),
      domain_ids:domains,read_ids:[...new Set([...selected,...disclose])],disclose_ids:disclose,write_domain_id:fd.get('write_domain_id'),
      allow_learning:fd.has('allow_learning'),action_policy:fd.get('action_policy')||'none',duration_minutes:Number(fd.get('duration_minutes'))});
    toast('会话已创建。');navigate(`sessions/${result.id}`);
  },mode==='private'?'开始交流':'创建授权会话');
  function updatePicker(){
    const ids=$$('input[name=domains]:checked',modal).map(e=>e.value),aud=$('#f-audience',modal)?.value.trim()||'';
    const facts=all.filter(m=>ids.includes(m.domain_id)&&(!m.expires_at||m.expires_at>Date.now()/1000));
    $('#fact-picker').innerHTML=`<div class="fact-choice picker-header"><span>记忆</span><span>读取</span>${mode==='delegate'?'<span>披露</span>':''}</div>`+facts.map(m=>{
      const allowed=m.visibility==='shareable'&&(!m.audiences.length||m.audiences.includes(aud));
      return `<div class="fact-choice"><div><p>${esc(m.title)}</p><small>${esc(domainName(m.domain_id))} · ${m.visibility==='private'?'仅本人':m.audiences.length?esc(m.audiences.join('、')):'可授权披露'}</small></div><label class="check"><input aria-label="读取 ${esc(m.title)}" type="checkbox" name="read_ids" value="${m.id}" checked></label>${mode==='delegate'?`<label class="check"><input aria-label="披露 ${esc(m.title)}" type="checkbox" name="disclose_ids" value="${m.id}" ${allowed?'':'disabled'}></label>`:''}</div>`;
    }).join('')+(facts.length?'':'<p class="dialog-help">当前选择中没有有效记忆。可以先创建会话，用于收集信息。</p>');
    const current=$('#f-write').value;$('#f-write').innerHTML=state.domains.filter(d=>ids.includes(d.id)).map(d=>`<option value="${d.id}" ${d.id===current?'selected':''}>${esc(d.name)}</option>`).join('');
  }
  $$('input[name=domains]',modal).forEach(e=>e.onchange=updatePicker);
  if($('#f-audience'))$('#f-audience').oninput=updatePicker;
  updatePicker();
}
async function proposalDialog(pid) {
  const p=state.proposals.find(x=>x.id===pid);
  const memories=await api(`/domains/${p.domain_id}/memories`);
  openDialog('审核记忆更新',`<p class="dialog-help">写入领域：${esc(domainName(p.domain_id))}。核实说话者与事实，必要时编辑。不会跨领域写入。</p>`+memoryFields({...p,visibility:'private',audiences:[]})+`<div class="form-field"><label for="f-target">保存方式</label><select name="target_id" id="f-target"><option value="">新增一条记忆</option>${memories.map(m=>`<option value="${m.id}">替换：${esc(m.title)} · v${m.version}</option>`).join('')}</select></div><details><summary>原始依据</summary>${p.evidence.map(e=>`<div class="evidence">${esc(e.speaker||'导入资料')}：${esc(e.content)}</div>`).join('')}</details>`,async fd=>{
    const target=memories.find(m=>m.id===fd.get('target_id'));
    await api(`/proposals/${pid}/review`,'POST',{...memoryData(fd),decision:'approve',target_id:target?.id||null,expected_version:target?.version||null});
    toast('更新已确认并保存。');await renderRoute();
  },'确认保存');
}
async function inviteDialog() {
  const sid=state.session.id;
  openDialog('创建邀请','<p class="dialog-help">邀请只适用于本次会话，可兑换一次。创建新邀请会收回此前的访客凭证。请只交给指定的交流对象。</p>',async()=>{
    const data=await api(`/sessions/${sid}/invite`,'POST');
    const link=`${location.origin}/invite#${data.token}`;
    // Opening a follow-up dialog after the current form closes keeps native focus management intact.
    setTimeout(()=>{
      const m=openDialog('邀请已创建',field('link','复制后交给对方',link,'text','readonly')+`<p class="dialog-help">有效至 ${dt(data.expires_at)}。对方只能与本次获准的助手交流，无法进入你的私人工作区。</p>`,async()=>{},'完成');
      const input=$('#f-link',m);input.onclick=()=>input.select();input.select();
      const copy=document.createElement('button');copy.type='button';copy.className='btn';copy.textContent='复制邀请链接';
      copy.onclick=async()=>{try{await navigator.clipboard.writeText(link);toast('邀请已复制。');}catch{input.select();toast('请复制已选中的链接。');}};
      $('.dialog-body',m).append(copy);
    },0);
  },'创建单次邀请');
}
function decisionDialog(aid) {
  const a=state.session.actions.find(a=>a.id===aid);
  openDialog('处理请求',`<p class="dialog-help">对方提出：${esc(a.request)}</p><div class="form-field"><label for="f-decision">你的决定</label><select id="f-decision" name="decision"><option value="approve">批准下面的表述</option><option value="reject">拒绝这项请求</option></select></div>`+area('response','发送给对方的确切表述','','maxlength="2000" placeholder="批准时请明确填写；拒绝时可选填说明。"')+'<p class="dialog-help">此处确认的是对外表达。不会自动向第三方日历、支付或邮件系统执行操作。</p>',async fd=>{
    await api(`/actions/${aid}/decision`,'POST',Object.fromEntries(fd));toast('你的决定已发送到会话。');await refreshSession();
  },'确认并发送');
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
      if(action==='new-private')await sessionDialog('private');
      if(action==='new-delegate')await sessionDialog('delegate');
      if(action==='extract'){
        b.disabled=true;b.textContent='正在提取…';const p=await api(`/sources/${id}/extract`,'POST');toast(`已生成 ${p.length} 条待审核记忆。`);await renderRoute();
      }
      if(action==='delete-source')openDialog('删除原始资料','<p class="dialog-help">同时删除从此资料新增的记忆、提取建议和相关会话。不能撤销。</p>',async()=>{await api(`/sources/${id}`,'DELETE');toast('资料已删除。');await renderRoute();},'确认删除');
      if(action==='review-proposal')await proposalDialog(id);
      if(action==='reject-proposal'){const p=state.proposals.find(p=>p.id===id);await api(`/proposals/${id}/review`,'POST',{title:p.title,content:p.content,decision:'reject'});toast('已忽略这条更新。');await renderRoute();}
      if(action==='invite')await inviteDialog();
      if(action==='decide')decisionDialog(id);
      if(action==='end-session'){
        b.disabled=true;b.textContent='正在整理…';const result=await api(`/sessions/${state.session.id}/end`,'POST');toast(result.warning||'会话已结束，更新建议等待你审核。');await renderRoute();
      }
      if(action==='revoke-session'){await api(`/sessions/${state.session.id}/revoke`,'POST');toast('授权已立即撤销；不会自动提取记忆。');await renderRoute();}
      if(action==='retry-learning'){b.disabled=true;const p=await api(`/sessions/${state.session.id}/learn`,'POST');toast(`${p.length} 条更新可供审核。`);await renderRoute();}
      if(action==='refresh')await renderRoute();
      if(action==='logout'){await api('/auth/logout','POST');disconnect();location.href='/';}
      if(action==='mic'){
        if(!state.voice||state.socket?.readyState!==WebSocket.OPEN)throw new Error('请先连接会话。');
        if((state.guest?state.session.stt:state.config.providers?.stt)==='mock')throw new Error('本地演示使用文字输入；配置 AssemblyAI 后可启用语音识别。');
        const enabled=await state.voice.toggleMic();b.classList.toggle('recording',enabled);b.setAttribute('aria-label',enabled?'关闭麦克风':'开启麦克风');
      }
      if(action==='interrupt'){state.voice?.stopPlayback();if(state.socket?.readyState===WebSocket.OPEN)state.socket.send(JSON.stringify({type:'interrupt'}));}
    }catch(err){toast(err.message);b.disabled=false;if(action==='extract')b.textContent='提取记忆';}
  });
}
function authPage(needsSetup) {
  $('#app').innerHTML=`<main class="auth-page" id="main">${brand}<p class="eyebrow">Personal agent workspace</p><h1>${needsSetup?'建立你的私人工作区':'欢迎回来'}</h1><p>${needsSetup?'创建登录凭证，开始管理你的领域与记忆。':'登录以管理记忆、授权会话和待审核更新。'}</p><form id="auth-form"><div class="form-error" role="alert"></div>${field('name','用户名','','text','required minlength="2" maxlength="60" autocomplete="username"')}${field('password','密码','','password',`required minlength="10" maxlength="200" autocomplete="${needsSetup?'new-password':'current-password'}"`)}<button class="btn primary" type="submit">${needsSetup?'创建工作区':'登录'} ${icon('arrow')}</button></form><p class="footnote">${needsSetup?'密码至少 10 位。此部署的首次设置只创建一个所有者账户。':'资料访问需要登录；邀请链接只授予单次会话权限。'}</p></main>`;
  $('#auth-form').onsubmit=async e=>{e.preventDefault();const b=$('button',e.target);b.disabled=true;try{const d=await api(needsSetup?'/auth/setup':'/auth/login','POST',Object.fromEntries(new FormData(e.target)));state.user=d.user;await startOwner();}catch(err){$('.form-error',e.target).textContent=err.message;}finally{b.disabled=false;}};
}
function renderGuest() {
  const s=state.session;
  $('#app').innerHTML=`<main class="guest-shell" id="main"><header class="guest-header">${brand}<span class="tag green">受邀交流</span></header><div class="heading"><div><p class="eyebrow">An authorized conversation</p><h1>${esc(s.title)}</h1><p>你正在与本人授权的 AI 助手交流。新的承诺需本人确认。</p></div></div>${s.demo?'<div class="banner">'+icon('info')+'本地演示模式：回复由授权记忆生成。</div>':''}<div class="room-layout">${conversation(s,true)}</div><p class="muted"><small>交流记录对本人可见。会话仅在授权有效期内开放。</small></p></main>`;
  bindActions();bindConversation(true);
}
async function startGuest(sid) {
  state.guest=true;
  try{state.session=await api(`/guest/sessions/${sid}`);renderGuest();connect(sid,true);}catch(err){$('#app').innerHTML=`<main class="auth-page" id="main">${brand}<h1>邀请已失效或会话已结束</h1><p>${esc(err.message)}</p><p>请联系本人重新授权。</p></main>`;}
}
async function startOwner() {
  state.config=await api('/config');await renderRoute();window.addEventListener('hashchange',renderRoute);
}
async function boot() {
  if(location.pathname==='/invite'){
    const token=location.hash.slice(1);history.replaceState(null,'','/invite');
    $('#app').innerHTML=`<main class="auth-page" id="main">${brand}<p class="eyebrow">Invitation</p><h1>加入授权交流</h1><p>你将与 Echooo AI 助手交流。对话会向邀请人展示，并可能形成待本人审核的记忆建议。</p><button class="btn primary" id="join">加入会话 ${icon('arrow')}</button><p class="form-error" role="alert"></p></main>`;
    $('#join').onclick=async()=>{const b=$('#join');b.disabled=true;try{const r=await api('/guest/join','POST',{token});history.replaceState(null,'',`/room/${r.session_id}`);await startGuest(r.session_id);}catch(err){$('.form-error').textContent=err.message;b.disabled=false;}};return;
  }
  if(location.pathname.startsWith('/room/')){await startGuest(location.pathname.split('/')[2]);return;}
  try{const auth=await api('/auth');if(!auth.user)authPage(auth.needs_setup);else{state.user=auth.user;await startOwner();}}catch(err){$('#app').innerHTML=empty('无法连接工作区',err.message);}
}
document.addEventListener('click',e=>{const shell=$('.shell.menu-open');if(shell&&!e.target.closest('.sidebar,[data-action=menu]')){shell.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('.shell')?.classList.remove('menu-open');$('[data-action=menu]')?.setAttribute('aria-expanded','false');}});
window.addEventListener('pagehide',disconnect);
boot();
