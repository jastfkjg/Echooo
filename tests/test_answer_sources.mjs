import test from 'node:test';
import assert from 'node:assert/strict';
import {answerLink,answerSources} from '../web/answer-sources.js';
import {renderAnswerTiming} from '../web/meeting-debug.js';

test('answer evidence shows original words, speaker, time and durable source navigation',()=>{
  const html=answerSources({citations:[{id:'source',kind:'utterance',title:'<Alice>',content:'We chose Telegram.',recording_id:'r',start_ms:65000,end_ms:68000}]},'meeting','old-answer');
  assert.ok(html.includes('Sources · 1'));
  assert.ok(html.includes('&lt;Alice&gt; · 1:05–1:08'));
  assert.ok(html.includes('We chose Telegram.'));
  assert.ok(html.includes('data-citation-jump="source"'));
  assert.ok(html.includes(answerLink('meeting','old-answer','source')));
});

test('changed and deleted sources never masquerade as original evidence',()=>{
  const html=answerSources({citations:[{id:'a',kind:'utterance',title:'Alice',changed:true,content:'MUST NOT DISPLAY'},
    {id:'b',unavailable:true,content:'MUST NOT DISPLAY'}]},'m','e');
  assert.ok(html.includes('Source changed')&&html.includes('Source unavailable'));
  assert.ok(!html.includes('MUST NOT DISPLAY'));
  assert.ok(!html.includes('data-citation-play'));
  assert.ok(html.includes('View current transcript'));
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
