import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {nextOption, menuPosition} from '../web/select.js';

// Exercise the real keyboard handler with a small view stub; DOM placement and
// native form integration are additionally checked in the isolated browser UI.
const source=await readFile(new URL('../web/select.js',import.meta.url),'utf8');
const Control=vm.runInNewContext(`${source.replace(/^export /gm,'')}; SelectControl`,{Date});
function keyboard() {
  const control={options:[{label:'Sage'},{label:'Blue',disabled:true},{label:'Amber'},{label:'Slate'}],
    current:0,value:0,opened:false,
    open(){this.opened=true;this.current=this.value;this.typed='';},
    close(){this.opened=false;},highlight(i){this.current=i;},
    commit(){this.value=this.current;this.close();}};
  const press=key=>{
    const result={prevented:false,stopped:false};
    Control.prototype.keydown.call(control,{key,preventDefault(){result.prevented=true;},stopPropagation(){result.stopped=true;}});
    return result;
  };
  return {control,press};
}

test('Arrow navigation stays tentative until Enter commits; Enter never submits a form',()=>{
  const {control:c,press}=keyboard();
  assert.equal(press('ArrowDown').prevented,true);assert.equal(c.current,0);
  press('ArrowDown');assert.equal(c.current,2);assert.equal(c.value,0);
  assert.equal(press('Enter').prevented,true);assert.equal(c.value,2);assert.equal(c.opened,false);
});
test('Escape cancels only an open menu; Tab leaves normal focus traversal intact',()=>{
  const {control:c,press}=keyboard();
  press('End');assert.equal(c.current,3);
  assert.deepEqual(press('Escape'),{prevented:true,stopped:true});assert.equal(c.value,0);
  assert.deepEqual(press('Escape'),{prevented:false,stopped:false});
  press('ArrowDown');assert.deepEqual(press('Tab'),{prevented:false,stopped:false});assert.equal(c.opened,false);
});
test('Type-ahead supports prefixes and repeated initials, skips disabled choices',()=>{
  const {control:c,press}=keyboard();
  press('s');assert.equal(c.current,3);
  press('s');assert.equal(c.current,0);
  c.lastTyped=Date.now()-1000;press('b');assert.equal(c.current,0);
  c.lastTyped=Date.now()-1000;press('s');press('l');assert.equal(c.current,3);
  press('Enter');assert.equal(c.value,3);
});
test('Space commits after type-ahead expires, and Home selects the first enabled option',()=>{
  const {control:c,press}=keyboard();
  press('a');assert.equal(c.current,2);
  c.lastTyped=Date.now()-1000;press(' ');assert.equal(c.value,2);assert.equal(c.opened,false);
  press('Home');assert.equal(c.current,0);press(' ');assert.equal(c.value,0);
});

test('Option navigation skips disabled and hidden choices and stops at either end',()=>{
  const choices=[{}, {disabled:true}, {}, {hidden:true}, {}];
  assert.equal(nextOption(choices,0,1),2);
  assert.equal(nextOption(choices,4,-1),2);
  assert.equal(nextOption(choices,4,1),4);
  assert.equal(nextOption(choices,0,-1),0);
  assert.equal(nextOption(choices,2,'first'),0);
  assert.equal(nextOption(choices,2,'last'),4);
});
test('Empty and entirely disabled lists have no selectable option',()=>{
  assert.equal(nextOption([],0,1),-1);
  assert.equal(nextOption([{disabled:true},{hidden:true}],0,'first'),-1);
  assert.equal(nextOption([{disabled:true},{}],-1,1),1);
});
test('Menu aligns with trigger and uses available space below',()=>{
  assert.deepEqual(menuPosition({left:40,top:100,bottom:144,width:240},{width:1200,height:800},190),
    {left:40,top:150,width:240,maxHeight:320});
});
test('Menu flips above near the viewport bottom, including wrapped options',()=>{
  const result=menuPosition({left:40,top:600,bottom:644,width:280},{width:800,height:700},260);
  assert.equal(result.top,334);
  assert.ok(result.top+260<600);
});
test('Narrow and short viewports keep menus inside their edges',()=>{
  for(const viewport of [{width:375,height:667},{width:667,height:375},{width:320,height:200}]){
    const rect={left:viewport.width-160,top:viewport.height-120,bottom:viewport.height-76,width:400};
    const p=menuPosition(rect,viewport,2000);
    assert.ok(p.left>=8);assert.ok(p.left+p.width<=viewport.width-8);
    assert.ok(p.top>=8);assert.ok(p.top+p.maxHeight<=viewport.height-8);
  }
});
test('Workspace and modal render boundaries both enhance all single selects',async()=>{
  const app=await readFile(new URL('../web/app.js',import.meta.url),'utf8');
  assert.match(app,/import \{enhanceSelects\} from '\.\/select.js'/);
  assert.match(app,/enhanceSelects\(modal\)/);
  assert.match(app,/function bindActions\(root=document\) \{\s+enhanceSelects\(root\)/);
  const html=await readFile(new URL('../web/index.html',import.meta.url),'utf8');
  assert.match(html,/href="\/static\/select.css"/);
});
