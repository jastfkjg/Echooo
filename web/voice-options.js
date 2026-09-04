import {menuPosition} from './select.js';

export function voiceOptions(prefs = {}) {
  return `<button type="button" id="voice-options-trigger" class="icon-btn voice-options-trigger" popovertarget="voice-options-panel" aria-label="Voice options" title="Voice options" aria-expanded="false" aria-controls="voice-options-panel"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg></button>
    <div id="voice-options-panel" class="voice-options-panel" popover="auto" role="group" aria-label="Voice options">
      <fieldset class="voice-mode-picker"><legend>Input mode</legend>
        <label><input type="radio" name="voice-mode" id="voice-mode-chat" ${prefs.dictation?'':'checked'}><span>Voice conversation</span></label>
        <label><input type="radio" name="voice-mode" id="voice-mode-dictation" ${prefs.dictation?'checked':''}><span>Dictation only<small>Transcribe into your draft.</small></span></label>
      </fieldset>
      <label class="voice-reply-choice"><input type="checkbox" id="voice-replies-toggle" ${prefs.muted?'':'checked'} ${prefs.dictation?'disabled':''}><span>Read replies aloud</span></label>
    </div>`;
}

export function syncVoiceOptions(prefs, root = document) {
  const chat = root.querySelector('#voice-mode-chat'), dictation = root.querySelector('#voice-mode-dictation');
  const replies = root.querySelector('#voice-replies-toggle');
  if (chat) chat.checked = !prefs.dictation;
  if (dictation) dictation.checked = !!prefs.dictation;
  if (replies) { replies.checked = !prefs.muted; replies.disabled = !!prefs.dictation; }
}

export function bindVoiceOptions({root = document, prefs, getVoice}) {
  const $ = s => root.querySelector(s), panel = $('#voice-options-panel'), trigger = $('#voice-options-trigger');
  if (!panel || !trigger) return;
  const update = () => {
    syncVoiceOptions(prefs, root);
    if (!getVoice()) {
      $('[data-action=voice] span').textContent = prefs.dictation ? 'Start dictation' : 'Start voice';
      $('#voice-hint').textContent = prefs.dictation ? 'Speech goes into your draft. Send when ready.' : prefs.muted ? 'Replies are muted.' : 'Speak naturally. Echooo replies aloud.';
    }
  };
  $('#voice-mode-chat').onchange = () => { prefs.dictation = false; getVoice()?.setDictation(false); update(); };
  $('#voice-mode-dictation').onchange = () => { prefs.dictation = true; getVoice()?.setDictation(true); update(); };
  $('#voice-replies-toggle').onchange = e => { prefs.muted = !e.target.checked; getVoice()?.setMuted(prefs.muted); update(); };
  const position = height => {
    const doc = panel.ownerDocument.documentElement;
    const rect = trigger.getBoundingClientRect();
    const layout = menuPosition({...rect.toJSON(), left: rect.right - 280, width: 280}, {width: doc.clientWidth, height: doc.clientHeight}, height);
    for (const [key, value] of Object.entries(layout)) panel.style[key] = `${value}px`;
  };
  panel.addEventListener('beforetoggle', e => {
    if (e.newState === 'open') {
      root.querySelectorAll('.toolbar-menu[open]').forEach(menu => { menu.open = false; });
      position(220);
    }
  });
  panel.addEventListener('toggle', e => {
    trigger.setAttribute('aria-expanded', String(e.newState === 'open'));
    if (e.newState === 'open') position(panel.scrollHeight + 2);
  });
  panel.addEventListener('focusout', e => {
    if (e.relatedTarget && !panel.contains(e.relatedTarget) && e.relatedTarget !== trigger && panel.matches(':popover-open')) panel.hidePopover();
  });
  // Keep Escape local so it cannot also close a pinned context inspector.
  const escape = e => {
    if (e.key === 'Escape' && panel.matches(':popover-open')) {
      e.preventDefault(); e.stopPropagation(); panel.hidePopover(); trigger.focus();
    }
  };
  panel.addEventListener('keydown', escape);
  trigger.addEventListener('keydown', escape);
  update();
}
