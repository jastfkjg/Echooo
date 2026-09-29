import test from 'node:test';
import assert from 'node:assert/strict';
import {answerLink,answerSourceGroups,answerSources,answerTriggers} from '../web/answer-sources.js';
import {renderAnswerTiming} from '../web/meeting-debug.js';

test('answer evidence shows original words, speaker, time and durable source navigation',()=>{
  const html=answerSources({citations:[{id:'source',kind:'utterance',title:'<Alice>',content:'We chose Telegram.',recording_id:'r',start_ms:65000,end_ms:68000}]},'meeting','old-answer');
  assert.ok(html.includes('Sources · 1'));
  assert.ok(html.includes('&lt;Alice&gt; · 1:05–1:08'));
  assert.ok(html.includes('We chose Telegram.'));
  assert.ok(html.includes('data-citation-jump="source"'));
  assert.ok(html.includes(answerLink('meeting','old-answer','source')));
});

test('direct question trigger shows its own transcript source and changed state',()=>{
  const html=answerTriggers([{utterance_id:'question',speaker:'<Alice>',content:'Echooo, which option?',start_ms:4000,changed:true}]);
  assert.match(html,/Question in transcript/);
  assert.match(html,/&lt;Alice&gt; · 0:04 · Transcript changed/);
  assert.match(html,/data-trigger-jump="question"/);
  assert.match(html,/View current transcript/);
});

test('changed and deleted sources never masquerade as original evidence',()=>{
  const html=answerSources({citations:[{id:'a',kind:'utterance',title:'Alice',changed:true,content:'MUST NOT DISPLAY'},
    {id:'b',unavailable:true,content:'MUST NOT DISPLAY'}]},'m','e');
  assert.ok(html.includes('Source changed')&&html.includes('Source unavailable'));
  assert.ok(!html.includes('MUST NOT DISPLAY'));
  assert.ok(!html.includes('data-citation-play'));
  assert.ok(html.includes('View current transcript'));
});

test('fragmented source shows its nearby turn while marking exact cited fragments',()=>{
  const utterances=[
    {id:'a',recording_id:'r',speaker:'Alice',content:'We need the document,',start_ms:4000,end_ms:7000},
    {id:'b',recording_id:'r',speaker:'Alice',content:'the design document by Friday.',start_ms:7800,end_ms:11000},
    {id:'c',recording_id:'r',speaker:'Bob',content:'Agreed.',start_ms:11500,end_ms:12500},
  ];
  const citations=utterances.slice(0,2).map(u=>({id:u.id,kind:'utterance',title:'Alice',content:u.content,recording_id:'r',start_ms:u.start_ms,end_ms:u.end_ms}));
  const html=answerSources({citations},'m','e',utterances);
  assert.equal(answerSourceGroups(citations,utterances).length,1);
  assert.match(html,/Sources · 1/);
  assert.match(html,/0:04–0:11/);
  assert.match(html,/<mark[^>]*>We need the document,<\/mark> <mark[^>]*>the design document by Friday\.<\/mark>/);
  assert.ok(!html.includes('Agreed.'));
  assert.match(html,/data-citation-ids="\[&quot;a&quot;,&quot;b&quot;\]"/);
  assert.match(html,/class="answer-source-player"/);
});

test('changed source never includes neighboring transcript as original evidence',()=>{
  const citations=[{id:'a',kind:'utterance',title:'Alice',content:'Old claim',recording_id:'r',changed:true}];
  const html=answerSources({citations},'m','e',[{id:'a',recording_id:'r',speaker:'Alice',content:'New claim',start_ms:0,end_ms:1000}]);
  assert.match(html,/Source changed/);
  assert.ok(!html.includes('New claim'));
  assert.ok(!html.includes('Transcript context'));
});

test('insufficient evidence and old records have honest empty states',()=>{
  assert.match(answerSources({check:{support:'insufficient'}},'m','e'),/No supported answer/);
  assert.match(answerSources({},'m','e'),/No source citations were saved/);
});

test('timing distinguishes missing stages, backlog estimates and actual output reports',()=>{
  const html=renderAnswerTiming({stages:{tts_requested:200,tts_first_chunk:500,playback_authorized:700,first_audio_report_received:800},client:{question_to_first_audio_ms:1200}});
  assert.ok(html.includes('300 ms')&&html.includes('1200 ms')&&html.includes('—'));
  assert.ok(html.includes('STT backlog is an estimate'));
  assert.ok(html.includes('overlapping stages must not be added'));
  assert.match(renderAnswerTiming(null),/not recorded/);
});
