import test from 'node:test';
import assert from 'node:assert/strict';
import {interventionHTML} from '../web/meeting-interventions.js';
import {approvedRecordHTML, findingEditorHTML} from '../web/meeting-findings.js';
const p={id:'p',kind:'missing_detail',status:'proposed',question:'Who owns <script>this</script>?',reason:'Missing owner',evidence:[{utterance_id:'u',speaker:'Alice',quote:'<b>Owner needed</b>',start_ms:61000}],state:{}};
test('private suggestions escape model text and show explicit speech approval controls',()=>{
  const html=interventionHTML(p);
  assert.ok(!html.includes('<script>')&&!html.includes('<b>'));
  assert.ok(html.includes('Review & ask')&&html.includes('Later')&&html.includes('Dismiss'));
  assert.ok(html.includes('1:01')&&html.includes('Open transcript'));
});
test('delivery state exposes cancellation; stale, dismissed and ended suggestions cannot speak',()=>{
  assert.ok(interventionHTML({...p,status:'approved'}).includes('Cancel speech'));
  for(const status of ['stale','rejected','spoken'])assert.ok(!interventionHTML({...p,status}).includes('data-proposal-action="approve"'));
  assert.ok(!interventionHTML(p,[],true).includes('data-proposal-action="approve"'));
  assert.ok(interventionHTML({...p,status:'failed'}).includes('Review & ask'));
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
