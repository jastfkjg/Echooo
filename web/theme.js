// Run before stylesheets: saved appearance is applied before the first paint.
// Kept as a small external classic script to respect the app's strict CSP.
(() => {
  const key='echooo.theme';
  const normalize=value=>value==='dark'?'dark':'light';
  function apply(value) {
    const theme=normalize(value);
    document.documentElement.dataset.theme=theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',theme==='dark'?'#141715':'#ffffff');
    document.querySelectorAll('[data-theme-choice]').forEach(button=>{
      button.setAttribute('aria-pressed',String(button.dataset.themeChoice===theme));
    });
  }
  let saved;
  try { saved=localStorage.getItem(key); } catch { /* Storage may be disabled. */ }
  apply(saved); // Light is the default, regardless of the OS color scheme.
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-theme-choice]');
    if(!button||!['light','dark'].includes(button.dataset.themeChoice))return;
    apply(button.dataset.themeChoice);
    try { localStorage.setItem(key,button.dataset.themeChoice); } catch { /* Still works for this page. */ }
  });
  window.addEventListener('storage',event=>{
    // Changing/clearing the preference in another tab keeps open pages in sync.
    if(event.key===key||event.key===null) {
      try { if(event.storageArea!==localStorage)return; } catch { return; }
      apply(event.newValue);
    }
  });
})();
