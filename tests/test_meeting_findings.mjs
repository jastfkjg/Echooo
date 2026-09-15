import test from 'node:test';
import assert from 'node:assert/strict';
import {decisionListHTML, approvedRecordHTML} from '../web/meeting-findings.js';

const item = {id:'finding-1',status:'provisional',statement:'Use <script>alert(1)</script>',evidence_current:true,
  evidence:[{utterance_id:'u',recording_id:'r',speaker:'Alice & Bob',start_ms:1200,end_ms:3300,quote:'We decided <b>yes</b>'}]};

test('untrusted model statements, names and quotes are escaped in review and final record',()=>{
  const html=decisionListHTML([item]);
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<b>yes</b>'));
  assert.ok(html.includes('Alice &amp; Bob'));
  assert.ok(html.includes('0:01–0:03'));
  const record=approvedRecordHTML({title:'<img src=x>',decisions:[item]});
  assert.ok(!record.includes('<img'));
  assert.ok(record.includes('&lt;script&gt;'));
});

test('stale evidence and in-flight review disable approval; approved items cannot be approved twice',()=>{
  assert.ok(!decisionListHTML([{...item,evidence_current:false}]).includes('data-approve-finding'));
  assert.match(decisionListHTML([{...item,evidence_current:false,can_refresh_evidence:true}]), /Review &amp; approve/);
  assert.match(decisionListHTML([item],true), /data-approve-finding="finding-1" disabled/);
  assert.ok(!decisionListHTML([{...item,status:'approved'}]).includes('data-approve-finding'));
  assert.ok(approvedRecordHTML({decisions:[]}).includes('No approved findings'));
});

test('action metadata is escaped and all approved finding categories render',()=>{
  const action={...item,kind:'action_item',details:{owner:'<img onerror=x>',deadline_text:'Friday & Monday'}};
  const question={...item,kind:'unresolved_question',statement:'Who owns launch?'};
  const html=approvedRecordHTML({title:'Meeting',decisions:[item],action_items:[action],unresolved_questions:[question]});
  assert.ok(html.includes('Action items')&&html.includes('Unresolved questions'));
  assert.ok(html.includes('&lt;img onerror=x&gt;'));
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('Friday &amp; Monday'));
});

test('review controls include edit and reject and permit explicit re-review',()=>{
  assert.ok(decisionListHTML([item]).includes('data-reject-finding'));
  assert.ok(decisionListHTML([item]).includes('data-edit-finding'));
  const html=decisionListHTML([{...item,status:'approved',evidence_current:false,can_refresh_evidence:true}]);
  assert.ok(html.includes('Review &amp; approve'));
  assert.ok(!html.includes('data-approve-finding'));
});

test('compact queue folds reviewed items and combines evidence and history',()=>{
  const html=decisionListHTML([item,{...item,id:'done',status:'approved'}]);
  assert.match(html,/<summary>Evidence<\/summary>/);
  assert.ok(!html.includes('<summary>Review history</summary>'));
  assert.match(html,/<details class="finding-reviewed"[^>]*><summary>Reviewed · 1/);
  const deleted=decisionListHTML([{...item,evidence_current:false,can_refresh_evidence:false}]);
  assert.match(deleted,/Source deleted/);
  assert.match(deleted,/data-edit-finding="finding-1" disabled/);
  assert.match(deleted,/data-reject-finding="finding-1" >Reject/);
});

test('outdated statement is paired with its original evidence, never substituted current text',()=>{
  const f={...item,evidence_current:false,can_refresh_evidence:true,current_evidence:[{...item.evidence[0],quote:'Corrected speech'}]};
  const html=decisionListHTML([f]);
  assert.ok(html.includes('Original evidence'));
  assert.ok(html.includes('We decided &lt;b&gt;yes&lt;/b&gt;'));
  assert.ok(!html.includes('Corrected speech'));
  assert.ok(!html.includes('The transcript changed'));
  assert.match(html,/<footer><span>.*?<button[^>]+data-source-utterance="u"/);
});

test('re-review shows current evidence first and save is the single confirmation',async()=>{
  const {findingEditorHTML}=await import('../web/meeting-findings.js');
  const html=findingEditorHTML({...item,evidence_current:false,current_evidence:[{...item.evidence[0],quote:'Corrected speech'}]});
  assert.ok(html.indexOf('Corrected speech')<html.indexOf('<textarea'));
  assert.match(html,/<details><summary>Previous evidence<\/summary>/);
  assert.ok(!html.includes('checkbox'));
  assert.ok(!html.includes('name="confirmed"'));
});
