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
  assert.match(decisionListHTML([{...item,evidence_current:false,can_refresh_evidence:true}]), /Review changes/);
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
  assert.ok(html.includes('Review changes'));
  assert.ok(!html.includes('data-approve-finding'));
});
