import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const script=await readFile(new URL('../web/theme.js',import.meta.url),'utf8');
function setup(saved,{blocked=false}={}) {
  const events={},writes=[],root={dataset:{}},meta={setAttribute(k,v){this[k]=v;}};
  const buttons=['light','dark','light','dark'].map(theme=>({dataset:{themeChoice:theme},setAttribute(k,v){this[k]=v;}}));
  const storage={getItem(){if(blocked)throw Error('Blocked');return saved;},setItem(k,v){if(blocked)throw Error('Blocked');writes.push([k,v]);}};
  const document={documentElement:root,querySelector:()=>meta,querySelectorAll:()=>buttons,addEventListener:(type,handler)=>events[type]=handler};
  vm.runInNewContext(script,{document,localStorage:storage,window:{addEventListener:(type,handler)=>events[type]=handler}});
  return {root,meta,buttons,storage,writes,events,choose(theme){events.click({target:{closest:()=>({dataset:{themeChoice:theme}})}});}};
}

test('First visit and invalid preferences default to light, independent of the OS',()=>{
  for(const value of [null,undefined,'','system','unknown'])assert.equal(setup(value).root.dataset.theme,'light');
  assert.equal(setup('dark').root.dataset.theme,'dark');
  assert.equal(setup('light').root.dataset.theme,'light');
});
test('Theme choice persists and updates all controls without navigation',()=>{
  const page=setup(null);page.choose('dark');
  assert.equal(page.root.dataset.theme,'dark');
  assert.deepEqual(page.writes,[['echooo.theme','dark']]);
  assert.equal(page.meta.content,'#141715');
  assert.deepEqual(page.buttons.map(b=>b['aria-pressed']),['false','true','false','true']);
  assert.equal(setup(page.writes.at(-1)[1]).root.dataset.theme,'dark');
  page.choose('light');assert.equal(page.meta.content,'#ffffff');
  page.choose('invalid');assert.equal(page.writes.length,2);
});
test('Appearance still works when storage access is unavailable',()=>{
  const page=setup(null,{blocked:true});assert.equal(page.root.dataset.theme,'light');
  assert.doesNotThrow(()=>page.choose('dark'));assert.equal(page.root.dataset.theme,'dark');
});
test('Other tabs synchronize only the local appearance preference',()=>{
  const page=setup(null);
  page.events.storage({key:'echooo.theme',newValue:'dark',storageArea:page.storage});
  assert.equal(page.root.dataset.theme,'dark');assert.equal(page.writes.length,0);
  page.events.storage({key:'unrelated',newValue:'light',storageArea:page.storage});
  page.events.storage({key:'echooo.theme',newValue:'light',storageArea:{}});
  assert.equal(page.root.dataset.theme,'dark');
  page.events.storage({key:null,newValue:null,storageArea:page.storage});
  assert.equal(page.root.dataset.theme,'light');
});
test('Saved theme loads before styles and the application, using CSP-safe external script',async()=>{
  const html=await readFile(new URL('../web/index.html',import.meta.url),'utf8');
  assert.match(html,/<html[^>]+data-theme="light"/);
  assert.ok(html.indexOf('src="/static/theme.js"')<html.indexOf('rel="stylesheet"'));
  assert.ok(html.indexOf('src="/static/theme.js"')<html.indexOf('src="/static/app.js"'));
  assert.doesNotMatch(html,/<script[^>]*>\s*[^<\s]/);
});

function luminance(hex) {
  const channels=hex.slice(1).match(/../g).map(c=>parseInt(c,16)/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4);
  return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
test('Both palettes meet text, action, placeholder, and input-boundary contrast',async()=>{
  const css=await readFile(new URL('../web/theme.css',import.meta.url),'utf8');
  const blocks=[...css.matchAll(/:root(?:\[data-theme="dark"\])?\s*\{([^}]+)\}/g)];
  assert.equal(blocks.length,2);
  for(const [i,block] of blocks.entries()) {
    const palette=Object.fromEntries([...block[1].matchAll(/--([\w-]+):\s*(#[a-f\d]{6});/g)].map(m=>[m[1],m[2]]));
    for(const fg of ['fg','muted','faint','accent','danger','warning'])for(const bg of ['bg','sidebar','panel','soft','hover'])
      assert.ok(contrast(palette[fg],palette[bg])>=4.5,`${i?'dark':'light'} ${fg}/${bg}: ${contrast(palette[fg],palette[bg]).toFixed(2)}`);
    for(const [fg,bg] of [['on-primary','primary'],['on-primary','primary-hover'],['on-accent','accent']])
      assert.ok(contrast(palette[fg],palette[bg])>=4.5,`${fg}/${bg}`);
    for(const bg of ['bg','sidebar','panel'])assert.ok(contrast(palette['control-line'],palette[bg])>=3,`input boundary / ${bg}`);
  }
});
