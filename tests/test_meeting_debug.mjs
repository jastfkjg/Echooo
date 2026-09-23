import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evidenceDiff} from '../web/meeting-debug.js';

test('debug identifies exact chunks removed from model input',()=>{
  const a={id:'same-source',offset:0,content:'First chunk',score:2};
  const b={id:'same-source',offset:1300,content:'Second chunk',score:1};
  const result=evidenceDiff({search:{result:{passages:[a,b]}},calls:[{context:{retrieval:{passages:[b]}}}]});
  assert.deepEqual(result.map(p=>p.sent),[false,true]);
  assert.equal(result[0].score,2);
  assert.deepEqual(evidenceDiff(null),[]);
});

test('trace separates actual model input and output and escapes source text',async()=>{
  const {renderAnswerTrace}=await import('../web/meeting-debug.js');
  const html=renderAnswerTrace({event:{request:'Question',response:'Answer'},trace:{calls:[{
    status:'validated',system:'STALE SYSTEM',context:{question:'STALE QUESTION'},
    request:{messages:[{role:'system',content:'Actual prompt\nSecond line'},
      {role:'user',content:JSON.stringify({question:'<script>unsafe</script>',discussion:[]})}]},
    result:{action:'search',queries:['project start']},
  },{status:'validated',result:{action:'answer',reply:'January',citations:['source']}}],
    search:{queries:['project start'],result:{passages:[]}}}});
  assert.ok(html.includes('aria-label="Input"')&&html.includes('aria-label="Output"'));
  assert.ok(html.includes('Actual prompt\nSecond line'));
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.indexOf('LLM 1')<html.indexOf('Search / retrieval'));
  assert.ok(html.indexOf('Search / retrieval')<html.indexOf('LLM 2'));
});

test('grouped evidence renders readable turns and matches original sources',async()=>{
  const {renderAnswerTrace}=await import('../web/meeting-debug.js');
  const a={id:'a',recording_id:'r',offset:0,content:'The project'};
  const b={id:'b',recording_id:'r',offset:0,content:'started <January>.'};
  const missing={id:'b',recording_id:'r',offset:1500,content:'Another excerpt.'};
  const context={retrieval:{passages:[{recording_id:'r',turns:[{
    speaker:'Human',source_ids:['a','b'],content:'The project started <January>.'}]}]}};
  const trace={search:{result:{passages:[a,b,missing]}},calls:[{status:'validated',context}]};
  assert.deepEqual(evidenceDiff(trace).map(p=>p.sent),[true,true,false]);
  const html=renderAnswerTrace({trace,event:{}});
  assert.ok(html.includes('The project started &lt;January&gt;.'));
  assert.ok(html.includes('Evidence block 1'));
  assert.ok(!html.includes('started <January>'));
});
