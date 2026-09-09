import test from 'node:test';
import assert from 'node:assert/strict';
import {groupTranscript,speakerName,recordingContent,transcriptMatches,searchParts,playingUtterance,findingGroups} from '../web/meeting-transcript.js';
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

test('literal transcript search handles Chinese, punctuation and case without rewriting source',()=>{
  const records=[row('a','KT：介绍 API（v1.0）\n调用。'),row('b','这里演示 api 调用。'),row('c','<b>[.*]</b>')];
  assert.deepEqual(transcriptMatches(records,' API '),['a','b']);
  assert.deepEqual(transcriptMatches(records,'介绍'),['a']);
  assert.deepEqual(transcriptMatches(records,'[.*]'),['c']);
  assert.deepEqual(transcriptMatches(records,'  '),[]);
  assert.deepEqual(searchParts('<b>[.*]</b>','[.*]'),[{text:'<b>',match:false},{text:'[.*]',match:true},{text:'</b>',match:false}]);
  assert.deepEqual(searchParts('API api','api').filter(p=>p.match).map(p=>p.text),['API','api']);
  assert.equal(records[0].content.includes('\n'),true);
});

test('playback selects only timed audio utterances, clears in silence and at end',()=>{
  const records=[row('a','First',0),row('b','Second',3000),row('c','Later',10000),row('note','Note',15000,{recording_id:null})];
  assert.equal(playingUtterance(records,0),'a');
  assert.equal(playingUtterance(records,3000),'b');
  assert.equal(playingUtterance(records,6000),null);
  assert.equal(playingUtterance(records,10000),'c');
  assert.equal(playingUtterance(records,13000),null);
  assert.equal(playingUtterance(records,15000),null);
});

test('KT shows knowledge only; absent, excluded and stale categories stay hidden',()=>{
  const sections=[{status:'pending',items:[{kind:'knowledge',text:'A system explanation.'}]},{status:'rejected',items:[{kind:'action'}]},{status:'stale',items:[{kind:'decision'}]}];
  assert.deepEqual(findingGroups(sections).map(g=>g.key),['knowledge']);
  assert.deepEqual(findingGroups([]),[]);
  sections.push({status:'confirmed',items:[{kind:'commitment'},{kind:'action'}]});
  assert.equal(findingGroups(sections).find(g=>g.key==='action').items.length,2);
});
