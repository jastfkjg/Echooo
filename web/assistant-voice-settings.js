import {serverAudioURL} from './server-audio.js?v=1';
import {enhanceSelects} from './select.js';
export function mountAssistantVoice(root,api,{Audio=globalThis.Audio}={}){
  let audio=null,url=null,sequence=0,disposed=false;
  const stop=()=>{sequence++;if(audio){audio.pause();audio.removeAttribute('src');audio.load();audio=null;}if(url){URL.revokeObjectURL(url);url=null;}};
  root.innerHTML=`<div><h3>Assistant voice</h3><p class="assistant-voice-description">For local recording and online meetings.</p>
    <form><div class="form-field"><label for="assistant-service">Speech service</label><select id="assistant-service" required disabled></select></div>
    <div class="form-field"><label for="assistant-voice">Voice</label><div class="assistant-voice-choice"><select id="assistant-voice" required disabled></select>
    <button type="button" class="btn assistant-voice-preview" id="assistant-preview" aria-label="Preview voice" title="Preview voice" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4Z M15 8a6 6 0 0 1 0 8 M18 5a10 10 0 0 1 0 14"/></svg></button></div></div>
    <div class="assistant-voice-footer"><p role="status" aria-live="polite">Loading voices…</p><button type="submit" class="btn primary" disabled>Save</button></div></form></div>`;
  const form=root.querySelector('form'),service=root.querySelector('select'),voice=root.querySelector('#assistant-voice'),
    preview=root.querySelector('#assistant-preview'),save=root.querySelector('[type=submit]'),status=root.querySelector('[role=status]');
  let services=[];
  const value=()=>({provider:service.value,voice:voice.value});
  const voices=(selected)=>{
    stop();voice.replaceChildren();
    for(const v of services.find(s=>s.id===service.value)?.voices||[]){const o=document.createElement('option');o.value=v.id;o.textContent=v.name||v.id;voice.append(o);}
    if(selected&&!Array.from(voice.options).some(o=>o.value===selected)){const o=document.createElement('option');o.value=selected;o.textContent='Unavailable voice — choose another';o.disabled=true;voice.prepend(o);}
    if(selected)voice.value=selected;
    voice.disabled=!voice.options.length;
    preview.disabled=save.disabled=!voice.value||!!voice.selectedOptions[0]?.disabled;
  };
  api('/settings/assistant-voice').then(data=>{
    if(disposed)return;
    services=data.services;
    for(const s of services){const o=document.createElement('option');o.value=s.id;o.textContent=s.name;service.append(o);}
    const available=services.some(s=>s.id===data.provider);
    if(available)service.value=data.provider;
    service.disabled=!services.length;voices(available?data.voice:null);
    status.textContent=!services.length?'No server speech service is configured.':!available&&data.provider?'The saved speech service is unavailable. Choose and save a replacement.':'';
  }).catch(e=>{if(!disposed)status.textContent=e.message;});
  service.onchange=()=>{voices();status.textContent='';};
  voice.onchange=()=>{stop();preview.disabled=save.disabled=false;status.textContent='';};
  form.onsubmit=async e=>{
    e.preventDefault();stop();save.disabled=preview.disabled=service.disabled=voice.disabled=true;status.textContent='Saving…';
    try{await api('/settings/assistant-voice','PUT',value());if(!disposed)status.textContent='Saved. Applies to the next reply.';}
    catch(e){if(!disposed)status.textContent=e.message;}
    finally{if(!disposed)save.disabled=preview.disabled=service.disabled=voice.disabled=false;}
  };
  preview.onclick=async()=>{
    stop();const run=sequence;preview.disabled=true;status.textContent='Preparing preview…';
    try{
      const result=await api('/settings/assistant-voice/preview','POST',value());
      if(disposed||run!==sequence)return;
      url=serverAudioURL(result.audio);
      audio=new Audio(url);
      audio.onended=()=>{if(run===sequence){status.textContent='';stop();}};
      audio.onerror=()=>{if(run===sequence){status.textContent='Preview playback failed.';stop();}};
      await audio.play();if(!disposed&&run===sequence)status.textContent='Playing preview…';
    }catch(e){if(!disposed&&run===sequence)status.textContent=e.name==='NotAllowedError'?'Allow sound for this site to play the preview.':e.message;}
    finally{if(!disposed)preview.disabled=false;}
  };
  enhanceSelects(root);
  return ()=>{disposed=true;stop();};
}
