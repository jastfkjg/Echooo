import test from 'node:test';
import assert from 'node:assert/strict';
import {TranscriptUpdates} from '../web/meeting-live.js';

test('an older HTTP response cannot erase a new turn or roll back a correction',()=>{
  const live=new TranscriptUpdates(),since=live.version;
  live.receive({id:'1',speaker:'Speaker A',content:'corrected'});
  live.receive({id:'2',speaker:'Speaker A',content:'new turn'});
  assert.deepEqual(live.merge([{id:'1',speaker:'Unknown speaker',content:'old'}],since),[
    {id:'1',speaker:'Speaker A',content:'corrected'}, {id:'2',speaker:'Speaker A',content:'new turn'},
  ]);
  // A later snapshot includes edits/deletions made elsewhere and is authoritative.
  assert.deepEqual(live.merge([{id:'1',content:'human edit'}],live.version),[{id:'1',content:'human edit'}]);
});
