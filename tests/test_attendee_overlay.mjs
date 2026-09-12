import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {echoooZoomChat}=createRequire(import.meta.url)('../deploy/attendee/zoom-chat.js');
const users=new Map([['2048',{deviceId:'2048',isCurrentUser:true}]]);
const message={senderId:1024,receiverId:2048,content:{messageId:'abc',t:'1789190000000',text:'secret'}};

test('Zoom private recipient survives normalization even when upstream default was everyone',()=>{
  const normalized=echoooZoomChat(message,users);
  assert.equal(normalized.to_bot,true);
  assert.equal(normalized.additional_data.echooo_audience,'private');
  assert.equal(normalized.participant_uuid,'1024');
  assert.equal(normalized.timestamp,1789190000);
});
test('only explicit public recipients allow public context',()=>{
  for(const receiverId of [0,'0']) assert.equal(echoooZoomChat({...message,receiverId},users).additional_data.echooo_audience,'public');
  assert.equal(echoooZoomChat({...message,receiverId:'',receiver:'Everyone'},users).additional_data.echooo_audience,'public');
  for(const receiverId of [undefined,null,'',4096,-1]){
    const result=echoooZoomChat({...message,receiverId},users);
    assert.equal(result.to_bot,true);
    assert.equal(result.additional_data.echooo_audience,'unknown');
  }
});
test('self messages are marked and missing self identity does not guess private scope',()=>{
  assert.equal(echoooZoomChat({...message,senderId:2048},users).additional_data.echooo_is_self,true);
  assert.equal(echoooZoomChat(message,new Map()).additional_data.echooo_audience,'unknown');
});
