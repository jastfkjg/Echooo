import test from 'node:test';
import assert from 'node:assert/strict';
import {groupTranscript,speakerName,recordingContent,transcriptMatches,searchParts,playingUtterance,findingGroups,minutesContent} from '../web/meeting-transcript.js';
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

test('backfilled passages are read in audio order, and reconnect speaker labels stay distinct',()=>{
  const meeting={revision:1,utterances:[row('later','Later',10000),row('early','Early',1000)],sections:[],overviews:[]};
  assert.deepEqual(recordingContent(meeting,'r1').records.map(u=>u.id),['early','later']);
  assert.equal(speakerName('Speaker A (connection 2) · abcd'),'Speaker A (connection 2)');
  assert.equal(speakerName('Recovered speaker B · abcd'),'Recovered speaker B');
});

test('stopping microphone capture flushes a short last frame before its acknowledgment',async()=>{
  const {readFile}=await import('node:fs/promises'),{default:vm}=await import('node:vm');
  let Processor;const messages=[];
  vm.runInNewContext(await readFile(new URL('../web/capture-worklet.js',import.meta.url),'utf8'),{
    AudioWorkletProcessor:class{port={postMessage:message=>messages.push(message)};},sampleRate:48000,
    registerProcessor:(name,processor)=>{Processor=processor;},Int16Array,
  });
  const capture=new Processor({processorOptions:{targetSampleRate:16000,chunkSamples:1600}});
  capture.process([[new Float32Array(480).fill(.5)]]);
  assert.equal(messages.length,0);
  capture.port.onmessage({data:{type:'flush'}});
  assert.equal(messages[0].byteLength,320);
  assert.equal(messages[1].type,'flushed');
  capture.process([[new Float32Array(480).fill(.5)]]);
  assert.equal(messages.length,2);
});

test('minutes are scoped to the selected recording and warn about new or corrected evidence',()=>{
  const meeting={revision:1,utterances:[row('1','First'),row('2','Other',0,{recording_id:'r2'})],minutes:[{scope_key:'r1',revision:1,status:'ready',evidence_ids:['1']}]};
  assert.equal(minutesContent(meeting,'r1').current,true);
  assert.equal(minutesContent(meeting,'r2').minutes,undefined);
  assert.equal(minutesContent({...meeting,revision:2},'r1').current,false);
  assert.equal(minutesContent({...meeting,utterances:[...meeting.utterances,row('3','New')]},'r1').current,false);
  assert.equal(minutesContent({...meeting,minutes:[{...meeting.minutes[0],status:'building'}]},'r1').current,false);
});

test('completed assistant speech interleaves with people and is searchable without altering human evidence',()=>{
  const human=row('h','What is the repo?',1000,{speaker:'Alice'});
  const assistant=row('a','https://github.com/example/assembly',6000,{speaker:'Echooo AI',assistant:true});
  const meeting={utterances:[human],assistant_utterances:[assistant],sections:[],overviews:[{scope_key:'r1',revision:1,evidence_ids:['h']}],revision:1};
  const content=recordingContent(meeting,'r1');
  assert.deepEqual(content.records.map(u=>u.id),['h','a']);
  assert.deepEqual(transcriptMatches(content.records,'github'),['a']);
  assert.equal(content.overviewCurrent,true);
  assert.equal(playingUtterance(content.records,6500),null); // Outbound TTS may be absent from the recording.
  assert.deepEqual(meeting.utterances,[human]);
  assert.equal(recordingContent(meeting,'notes').records.length,0);
});

test('assistant responses retain individual turns even when consecutive',()=>{
  const rows=[row('a','First reply',1000,{speaker:'Echooo AI',assistant:true}),row('b','Second reply',4500,{speaker:'Echooo AI',assistant:true})];
  assert.equal(groupTranscript(rows).length,2);
});

const replyText="Hello! I'm Echooo, your independent meeting assistant. How can I help you today?";
const spoken=(extra={})=>row('reply',replyText,10000,{speaker:'Echooo AI',assistant:true,end_ms:15000,timing_estimated:false,...extra});
const captured=(extra={})=>row('capture',replyText,10100,{speaker:'Speaker A · 4764',end_ms:15200,...extra});

test('exact concurrent playback capture folds under AI without mutating source records',()=>{
  const records=[spoken(),captured()],before=JSON.stringify(records);
  const groups=groupTranscript(records);
  assert.equal(groups.length,1);
  assert.equal(groups[0].speaker,'Echooo AI');
  assert.equal(groups[0].echoGroups[0].records[0].id,'capture');
  assert.equal(JSON.stringify(records),before);
  assert.deepEqual(transcriptMatches(records,'independent'),['reply','capture']);
  assert.equal(playingUtterance(records,11000),'capture');
});

test('later repetitions, corrections, quotations, other recordings and uncertain timing stay visible',()=>{
  const variants=[
    captured({start_ms:18000,end_ms:23000}),captured({recording_id:'r2'}),
    captured({user_edited:true}),captured({speaker:'Alice'}),
    captured({content:'You said: '+replyText}),captured({content:replyText+' I disagree.'}),
    captured({start_ms:9000}),captured({content:'Hello!'})
  ];
  for(const u of variants)assert.equal(groupTranscript([spoken(),u]).length,2);
  assert.equal(groupTranscript([spoken({timing_estimated:true}),captured()]).length,2);
  assert.equal(groupTranscript([spoken({recording_id:null}),captured({recording_id:null})]).length,2);
});

test('new participant speech never gets absorbed into a collapsed capture',()=>{
  const after=row('human','Let us discuss the release.',15500,{speaker:'Speaker A · 4764'});
  const groups=groupTranscript([spoken(),captured(),after]);
  assert.equal(groups.length,2);
  assert.equal(groups[0].echoGroups[0].records.length,1);
  assert.equal(groups[1].records[0].id,'human');
});

test('playback grouping does not change evidence coverage or the underlying recording data',()=>{
  const records=[captured()];
  const meeting={revision:1,utterances:records,assistant_utterances:[spoken()],sections:[{status:'pending',evidence_ids:['capture']}],
    overviews:[{scope_key:'r1',revision:1,evidence_ids:['capture']}]};
  const content=recordingContent(meeting,'r1');
  assert.equal(content.records.length,2);
  assert.equal(content.sections.length,1);
  assert.equal(content.overviewCurrent,true);
  assert.equal(meeting.utterances,records);
});

const splitCapture=()=>[
  captured({id:'part-1',content:"Hello, I'm Echooo, your independent meeting assistant.",end_ms:12500}),
  captured({id:'part-2',content:'How can I help you today?',start_ms:12600,end_ms:15200,speaker:'Speaker UNKNOWN · 4764'}),
];
test('complete playback split across automatic and unidentified speakers is hidden',()=>{
  const records=[spoken(),...splitCapture()],before=JSON.stringify(records);
  const groups=groupTranscript(records);
  assert.deepEqual(groups.flatMap(g=>g.records.map(u=>u.id)),['reply']);
  assert.deepEqual(groups[0].echoGroups.flatMap(g=>g.records.map(u=>u.id)),['part-1','part-2']);
  assert.equal(JSON.stringify(records),before);
  assert.deepEqual(transcriptMatches(groups.flatMap(g=>g.records),'help'),['reply']);
});
test('split playback is matched before adjacent real speech can be merged into it',()=>{
  const parts=splitCapture();parts[1].speaker=parts[0].speaker;
  const human=row('human','We should discuss the deployment next.',15500,{speaker:parts[0].speaker});
  assert.deepEqual(groupTranscript([spoken(),...parts,human]).flatMap(g=>g.records.map(u=>u.id)),['reply','human']);
});
test('incomplete, interrupted, edited, named and out-of-window split matches remain visible',()=>{
  const variants=[
    splitCapture().slice(0,1),
    [splitCapture()[0],row('interrupt','Please stop for a moment.',12550),splitCapture()[1]],
    splitCapture().map((u,i)=>i?{...u,user_edited:true}:u),
    splitCapture().map((u,i)=>i?{...u,speaker:'Alice'}:u),
    splitCapture().map((u,i)=>i?{...u,start_ms:18000,end_ms:20000}:u),
    splitCapture().map((u,i)=>i?{...u,recording_id:'r2'}:u),
  ];
  for(const parts of variants){
    const groups=groupTranscript([spoken(),...parts]);
    assert.equal(groups.flatMap(g=>g.records).length,parts.length+1);
    assert.equal(groups[0].echoGroups,undefined);
  }
});
test('matching supports arbitrary multi-part multilingual replies and rejects ambiguous playback',()=>{
  const parts=['本次讨论确定先完成接口验证，','随后开展客户端联调并整理测试结果。','发布计划需要等到所有验收场景完成以后，再由负责人最终确认。'];
  const reply=spoken({content:parts.join('')});
  const captures=parts.map((content,i)=>captured({id:`segment-${i}`,content,start_ms:10100+i*1500,end_ms:11500+i*1500,speaker:i%2?'Speaker PENDING · 4764':'Speaker B · 4764'}));
  assert.equal(groupTranscript([reply,...captures]).length,1);
  const ambiguous=groupTranscript([reply,{...reply,id:'other-reply'},...captures]);
  assert.equal(ambiguous.flatMap(g=>g.records).length,5);
});
