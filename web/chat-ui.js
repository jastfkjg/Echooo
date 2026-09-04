import {domainControl} from './session-ui.js';

// Presentational helpers keep the conversation surface separate from workspace pages.
export function voiceControls(icon) {
  return `<div class="voice-bar" id="voice-bar">
    <div class="voice-feedback"><span class="voice-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><div><span id="voice-status" role="status" aria-live="polite">Voice is off</span><small id="voice-hint">Speak naturally. Echooo replies aloud.</small></div></div>
    <div class="voice-buttons"><button class="icon-btn" data-action="pause-mic" aria-label="Pause microphone" title="Pause microphone" hidden>${icon('mic')}</button><button class="icon-btn" data-action="mute-voice" aria-label="Mute replies" title="Mute replies" aria-pressed="false" hidden>${icon('volume')}</button><button class="btn voice-interrupt" data-action="interrupt" hidden>${icon('stop')}Interrupt reply</button><button class="btn primary voice-start" data-action="voice" aria-pressed="false">${icon('wave')}<span>Start voice</span></button></div>
  </div><div class="voice-error" id="voice-error" hidden><p role="status"></p><div class="actions"><button class="btn subtle" data-action="retry-audio">Retry audio</button><button class="btn subtle" data-action="dismiss-audio-error">Dismiss</button></div></div>`;
}

export function sessionHeader(s, {icon, esc, domainName, prefs}) {
  const active=s.status==='active', privateChat=s.mode==='private', pending=s.actions.filter(a=>a.status==='pending').length;
  return `<div class="session-identity"><button class="icon-btn mobile-menu" data-action="menu" aria-label="Open navigation" aria-expanded="false">${icon('menu')}</button><div><h1 id="session-title" title="${esc(s.title)}">${esc(s.title)}</h1>${privateChat?'':'<span class="session-kind">Delegated conversation</span>'}</div></div>
    ${domainControl(s,{icon,esc,domainName})}
    <div class="session-tools">${!privateChat&&active?`<button class="btn invite-button" data-action="invite">${icon('link')}<span>Invite guest</span></button><button class="btn danger revoke-button" data-action="revoke-session">${icon('shield')}<span>Revoke access</span></button>`:''}
      <button class="btn context-toggle" data-action="context" aria-label="Chat context" aria-expanded="false" aria-controls="context-drawer">${icon('panel')}<span>Context</span><span class="approval-count" ${pending?'':'hidden'}>${pending}</span></button>
      <details class="toolbar-menu"><summary class="icon-btn" aria-label="Conversation settings" title="Conversation settings">${icon('settings')}</summary><div class="toolbar-popover"><h2>Conversation settings</h2>${privateChat?`<button data-action="choose-domains">${icon('folder')}Choose domains</button><p>Changing domains starts a new conversation.</p>`:''}${privateChat&&active?`<hr><label><input type="checkbox" id="dictation-toggle" ${prefs.dictation?'checked':''}><span>Dictation only<small>Transcribe into the input. Send when ready.</small></span></label><label><input type="checkbox" id="mute-toggle" ${prefs.muted?'checked':''}><span>Mute replies<small>Keep voice input, read the replies.</small></span></label>`:''}<hr><p>${icon('shield')} Only authorized memories are available here.</p></div></details>
      <details class="toolbar-menu"><summary class="icon-btn" aria-label="More conversation actions" title="More">${icon('more')}</summary><div class="toolbar-popover action-menu"><h2>Conversation actions</h2><button data-action="rename-session">${icon('edit')}Rename conversation</button>${privateChat?`<button data-action="save-chat-memory">${icon('file')}Save a memory…</button><button data-action="new-delegate">${icon('arrow')}Delegate…</button>`:''}${active?`<hr><button data-action="end-session">${icon('check')}End conversation & review</button><p>Ends this conversation, not just voice.</p>${privateChat?`<button class="danger" data-action="revoke-session">${icon('shield')}Revoke access</button>`:''}`:''}<hr><button class="danger" data-action="delete-session">${icon('trash')}Delete conversation…</button></div></details>
    </div>`;
}

export function updateVoiceUI(voice, {root=document, icon}) {
  const $=s=>root.querySelector(s), bar=$('#voice-bar');
  if(!bar||!voice)return;
  const connected=voice.socket.readyState===WebSocket.OPEN&&!voice.closed;
  const connecting=voice.socket.readyState===0&&!voice.closed;
  const busy=voice.thinking||voice.speaking||voice.preparing;
  const status=connecting?'Connecting…':!connected?'Disconnected':voice.micPending?'Connecting microphone…':voice.speaking?'Echooo is speaking':voice.thinking?'Thinking…':voice.preparing?'Preparing voice reply…':voice.micReady?(voice.dictation?'Dictating…':'Listening'):voice.active?'Microphone paused':'Voice is off';
  $('#voice-status').textContent=status;
  $('#voice-hint').textContent=!connected?'Text is available. Reconnect to use voice.':voice.error?'Audio needs attention — see below.':voice.dictation?'Speech goes into your draft. Send when ready.':voice.muted?'Replies are muted.':voice.active?'End voice anytime. Your conversation stays here.':'Speak naturally. Echooo replies aloud.';
  bar.dataset.state=voice.speaking?'speaking':voice.thinking||voice.preparing||voice.micPending?'working':voice.micReady?'listening':'off';
  const start=$('[data-action=voice]');
  start.disabled=connecting;
  start.classList.toggle('voice-end',voice.active);
  start.setAttribute('aria-pressed',String(voice.active));
  start.innerHTML=icon(voice.active?'stop':'wave')+`<span>${connecting?'Connecting…':!connected?'Reconnect':voice.active?'End voice':voice.dictation?'Start dictation':'Start voice'}</span>`;
  const pause=$('[data-action=pause-mic]'), mute=$('[data-action=mute-voice]'), interrupt=$('[data-action=interrupt]');
  pause.hidden=!voice.active;mute.hidden=!voice.active||voice.dictation;interrupt.hidden=!busy;
  const paused=!voice.micReady&&!voice.micPending;
  pause.setAttribute('aria-label',paused?'Resume microphone':'Pause microphone');pause.title=paused?'Resume microphone':'Pause microphone';pause.setAttribute('aria-pressed',String(paused));
  mute.setAttribute('aria-pressed',String(voice.muted));mute.setAttribute('aria-label',voice.muted?'Unmute replies':'Mute replies');mute.title=voice.muted?'Unmute replies':'Mute replies';
  if($('#mute-toggle'))$('#mute-toggle').checked=voice.muted;
  const error=$('#voice-error');error.hidden=!voice.error;
  error.querySelector('p').textContent=voice.error?.message||'';
  $('[data-action=retry-audio]').textContent=voice.error?.kind==='microphone'?'Retry microphone':'Retry audio';
  $('[data-action=retry-audio]').disabled=connecting||(voice.error?.kind==='playback'&&!voice.enabled);
  if(!voice.micReady&&!voice.micPending){$('#partial').textContent='';$('#partial').hidden=true;}
}
