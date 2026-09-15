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
  assert.match(decisionListHTML([{...item,evidence_current:false}]), /data-approve-finding="finding-1" disabled/);
  assert.match(decisionListHTML([item],true), /data-approve-finding="finding-1" disabled/);
  assert.ok(!decisionListHTML([{...item,status:'approved'}]).includes('data-approve-finding'));
  assert.ok(approvedRecordHTML({decisions:[]}).includes('No approved decisions'));
});
