import test from 'node:test';
import assert from 'node:assert/strict';
import {interventionHTML,evidenceGroups} from '../web/meeting-interventions.js';
import {approvedRecordHTML, findingEditorHTML} from '../web/meeting-findings.js';
const p={id:'p',kind:'missing_detail',status:'proposed',question:'Who owns <script>this</script>?',reason:'Missing owner',evidence:[{utterance_id:'u',speaker:'Alice',quote:'<b>Owner needed</b>',start_ms:61000}],state:{}};
test('private suggestions escape model text and show explicit speech approval controls',()=>{
  const html=interventionHTML(p);
  assert.ok(!html.includes('<script>')&&!html.includes('<b>'));
  assert.ok(html.includes('Ask in meeting')&&html.includes('Save for later')&&html.includes('Dismiss'));
  assert.ok(!html.includes('Needs approval')&&!html.includes('Review & ask'));
  assert.ok(html.indexOf('Missing owner')<html.indexOf('<details'));
  assert.ok(html.includes('intervention-kind')&&html.includes('Supporting conversation'));
  assert.ok(html.includes('1:01')&&html.includes('Open transcript'));
});
test('chronological evidence joins adjacent fragments with one source control per speech group',()=>{
  const rows=[{id:'a',content:'So',start_ms:303000,end_ms:304000},{id:'b',content:'the project will be deployed next Friday',start_ms:304000,end_ms:309000},{id:'c',content:'deployment be done next',start_ms:345000,end_ms:349000},{id:'d',content:'Tuesday',start_ms:349000,end_ms:350000}].map(r=>({...r,recording_id:'r',speaker:'Speaker C'}));
  const evidence=rows.map(r=>({...r,utterance_id:r.id,quote:r.content})).reverse();
  const groups=evidenceGroups(evidence,rows);
  assert.deepEqual(groups.map(g=>g.quote),['So the project will be deployed next Friday','deployment be done next Tuesday']);
  assert.deepEqual(groups[0].items.map(e=>e.utterance_id),['a','b']);
  const html=interventionHTML({...p,evidence},[],false,{records:rows});
  assert.equal((html.match(/Open transcript/g)||[]).length,2);
  assert.ok(html.includes('5:03–5:09'));
});
test('evidence does not silently bridge omissions, speakers, recordings or notes',()=>{
  const a={utterance_id:'a',quote:'Ready',speaker:'Alice',recording_id:'r',start_ms:0,end_ms:1000};
  const b={...a,utterance_id:'b',quote:'tomorrow.',start_ms:1100,end_ms:2000};
  assert.equal(evidenceGroups([a,b])[0].quote,'Ready … tomorrow.');
  for(const changed of [{speaker:'Bob'},{recording_id:'other'},{recording_id:null},{start_ms:40000}])assert.equal(evidenceGroups([a,{...b,...changed}]).length,2);
  const records=[{...a,id:'a',content:'Ready but not approved'},{...b,id:'b',content:'Only tomorrow.'}];
  assert.equal(evidenceGroups([a,b],records)[0].quote,'Ready … tomorrow.');
  records.splice(1,0,{id:'other',recording_id:'r',speaker:'Bob',content:'Wait.',start_ms:1050,end_ms:1090});
  assert.equal(evidenceGroups([a,b],records).length,2);
});
test('Chinese fragments join without added spaces and evidence is not mutated',()=>{
  const records=[{id:'a',content:'计划周三',start_ms:0,end_ms:1000},{id:'b',content:'发布。',start_ms:1100,end_ms:2000}].map(r=>({...r,recording_id:'r',speaker:'A'}));
  const evidence=records.map(r=>({...r,utterance_id:r.id,quote:r.content}));
  const original=JSON.stringify(evidence);
  assert.equal(evidenceGroups(evidence,records)[0].quote,'计划周三发布。');
  assert.equal(JSON.stringify(evidence),original);
});
test('delivery state exposes cancellation; stale, dismissed and ended suggestions cannot speak',()=>{
  assert.ok(interventionHTML({...p,status:'approved'}).includes('>Stop</button>'));
  for(const status of ['stale','rejected','spoken'])assert.ok(!interventionHTML({...p,status}).includes('data-proposal-action="approve"'));
  assert.ok(!interventionHTML(p,[],true).includes('data-proposal-action="approve"'));
  assert.ok(interventionHTML({...p,status:'failed'}).includes('Ask in meeting'));
});
test('delivery is explicit and editing is inline with escaped draft text',()=>{
  assert.ok(interventionHTML(p,[],false,{local:true}).includes('Play locally'));
  const html=interventionHTML(p,[],false,{local:true,editing:{id:'p',text:'</textarea><script>bad</script>'}});
  assert.ok(html.includes('data-question-draft')&&html.includes('Cancel edit'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!interventionHTML({...p,status:'deferred'}).includes('data-proposal-action="defer"'));
});
test('review history preserves changed wording',()=>{
  assert.ok(interventionHTML(p,[{action:'approve',created_at:0,before:{question:'Original'},after:{question:'Edited'}}]).includes('Original → Edited'));
});
test('approved risks and contradictions appear in the record and category editor',()=>{
  const finding={...p,statement:'Release dates conflict.',details:{},evidence:[],evidence_current:true,kind:'contradiction'};
  assert.ok(approvedRecordHTML({contradictions:[finding],risks:[finding]}).includes('Contradictions'));
  assert.ok(approvedRecordHTML({risks:[finding]}).includes('Risks'));
  assert.ok(findingEditorHTML(finding).includes('value="contradiction"'));
});
