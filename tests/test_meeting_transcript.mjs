import test from 'node:test';
import assert from 'node:assert/strict';
import {groupTranscript,speakerName,recordingContent} from '../web/meeting-transcript.js';
const row=(id,text,start=0,extra={})=>({id,content:text,speaker:'Speaker PENDING · 4764',recording_id:'r1',start_ms:start,end_ms:start+3000,...extra});
test('continuous short turns read as prose without losing evidence IDs',()=>{
  const rows=[row('1','发现异常时，',0),row('2','关联订单和物料。',4000),row('3','嗯。',9000)];
  const groups=groupTranscript(rows);
  assert.equal(groups.length,1);assert.equal(groups[0].speaker,'Unidentified speaker');
  assert.deepEqual(groups[0].records.map(r=>r.id),['1','2','3']);
  assert.equal(rows[0].speaker,'Speaker PENDING · 4764');
});
test('speaker changes, recordings, pauses, and long text split reading groups',()=>{
  for(const second of [row('2','next',4000,{speaker:'Alice'}),row('2','next',4000,{recording_id:'r2'}),row('2','next',40000),row('2','x'.repeat(650),4000)]){
    assert.equal(groupTranscript([row('1','first'),second]).length,2);
  }
  assert.equal(speakerName('王芳'),'王芳');
  assert.equal(speakerName('Speaker A · abcd'),'Speaker A');
});
test('recording selection filters full transcript, highlights and overview together',()=>{
  const a=row('a','First'),b=row('b','Second',0,{recording_id:'r2'});
  const meeting={revision:1,utterances:[a,b],sections:[{id:'s1',status:'pending',evidence_ids:['a']},{id:'mixed',status:'pending',evidence_ids:['a','b']}],overviews:[{scope_key:'r1',revision:1,evidence_ids:['a'],summary:'First overview'}]};
  const first=recordingContent(meeting,'r1'),second=recordingContent(meeting,'r2');
  assert.deepEqual(first.records,[a]);assert.equal(first.sections.length,1);assert.equal(first.overviewCurrent,true);
  assert.deepEqual(second.records,[b]);assert.equal(second.sections.length,0);assert.equal(second.overview,undefined);
  meeting.utterances.push(row('c','More'));
  assert.equal(recordingContent(meeting,'r1').overviewCurrent,false);
});
