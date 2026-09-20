import test from 'node:test';
import assert from 'node:assert/strict';
import {decisionListHTML, approvedRecordHTML} from '../web/meeting-findings.js';

const item = {id:'finding-1',status:'provisional',statement:'Use <script>alert(1)</script>',evidence_current:true,
  evidence:[{utterance_id:'u',recording_id:'r',speaker:'Alice & Bob',start_ms:1200,end_ms:3300,quote:'We decided <b>yes</b>'}]};

test('untrusted model statements, names and quotes are escaped in review and final record',()=>{
  const html=decisionListHTML([item]);
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<b>yes</b>'));
  assert.ok(html.includes('Alice &amp; Bob'));
  assert.ok(html.includes('0:01–0:03'));
  const record=approvedRecordHTML({title:'<img src=x>',decisions:[item]});
  assert.ok(!record.includes('<img'));
  assert.ok(record.includes('&lt;script&gt;'));
});

test('stale evidence and in-flight review disable approval; approved items cannot be approved twice',()=>{
  assert.ok(!decisionListHTML([{...item,evidence_current:false}]).includes('data-approve-finding'));
  assert.match(decisionListHTML([{...item,evidence_current:false,can_refresh_evidence:true}]), /Review changes/);
  assert.match(decisionListHTML([item],true), /data-approve-finding="finding-1" disabled/);
  assert.ok(!decisionListHTML([{...item,status:'approved'}]).includes('data-approve-finding'));
  assert.ok(approvedRecordHTML({decisions:[]}).includes('No approved findings'));
});

test('action metadata is escaped and all approved finding categories render',()=>{
  const action={...item,kind:'action_item',details:{owner:'<img onerror=x>',deadline_text:'Friday & Monday'}};
  const question={...item,kind:'unresolved_question',statement:'Who owns launch?'};
  const html=approvedRecordHTML({title:'Meeting',decisions:[item],action_items:[action],unresolved_questions:[question]});
  assert.ok(html.includes('Action items')&&html.includes('Open questions'));
  assert.ok(html.includes('&lt;img onerror=x&gt;'));
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('Friday &amp; Monday'));
});

test('review controls include edit and reject and permit explicit re-review',()=>{
  assert.ok(decisionListHTML([item]).includes('data-reject-finding'));
  assert.ok(decisionListHTML([item]).includes('data-edit-finding'));
  const html=decisionListHTML([{...item,status:'approved',evidence_current:false,can_refresh_evidence:true}]);
  assert.ok(html.includes('Review changes'));
  assert.ok(!html.includes('data-approve-finding'));
});

test('compact queue folds reviewed items and combines evidence and history',()=>{
  const html=decisionListHTML([item,{...item,id:'done',status:'approved'}]);
  assert.match(html,/<summary>Source<\/summary>/);
  assert.ok(!html.includes('<summary>Review history</summary>'));
  assert.match(html,/<details class="finding-reviewed"[^>]*><summary>Reviewed · 1/);
  const deleted=decisionListHTML([{...item,evidence_current:false,can_refresh_evidence:false}]);
  assert.match(deleted,/Source deleted/);
  assert.match(deleted,/data-edit-finding="finding-1" disabled/);
  assert.match(deleted,/data-reject-finding="finding-1" >Reject/);
});

test('outdated statement is paired with its original evidence, never substituted current text',()=>{
  const f={...item,evidence_current:false,can_refresh_evidence:true,current_evidence:[{...item.evidence[0],quote:'Corrected speech'}]};
  const html=decisionListHTML([f]);
  assert.ok(html.includes('Previous transcript'));
  assert.ok(html.includes('We decided &lt;b&gt;yes&lt;/b&gt;'));
  assert.ok(!html.includes('Corrected speech'));
  assert.ok(!html.includes('The transcript changed'));
  assert.match(html,/<footer><span[^>]*>.*?<button[^>]+data-source-utterance="u"/);
});

test('re-review shows current evidence first and save is the single confirmation',async()=>{
  const {findingEditorHTML}=await import('../web/meeting-findings.js');
  const html=findingEditorHTML({...item,evidence_current:false,current_evidence:[{...item.evidence[0],quote:'Corrected speech'}]});
  assert.ok(html.indexOf('Corrected speech')<html.indexOf('<textarea'));
  assert.match(html,/<details><summary>Previous transcript<\/summary>/);
  assert.ok(!html.includes('checkbox'));
  assert.ok(!html.includes('name="confirmed"'));
});

test('record keeps content focused and discloses edit status with its source',()=>{
  const html=approvedRecordHTML({title:'2',unresolved_questions:[item,{...item,id:'b',status:'edited'},{...item,id:'c'}]});
  assert.ok(!html.includes("Meeting: 2"));
  assert.ok(!html.includes("3 approved items"));
  assert.match(html,/<h2>Confirmed results<\/h2>/);
  assert.match(html,/<h3>Open questions<\/h3>/);
  assert.match(html,/<summary>Source<\/summary><p class="record-edit-label">Edited &amp; approved/);
  assert.match(html,/data-source-utterance="u"/);
});

test('adjacent evidence shares a block but retains exact quotes and individual anchors',async()=>{
  const {groupEvidence}=await import('../web/meeting-findings.js');
  const a={...item.evidence[0],speaker:'Speaker A · 6c7b',quote:'啊这怎么',start_ms:344895,end_ms:350899};
  const b={...a,utterance_id:'v',quote:'下呀',start_ms:349824,end_ms:351226};
  const before=JSON.stringify([a,b]);
  assert.equal(groupEvidence([a,b]).length,1);
  const html=approvedRecordHTML({unresolved_questions:[{...item,evidence:[a,b]}]});
  assert.equal((html.match(/<blockquote>/g)||[]).length,1);
  assert.ok(!html.includes('6c7b'));
  assert.match(html,/5:44–5:51/);
  assert.match(html,/data-source-utterances="\[&quot;u&quot;,&quot;v&quot;\]"/);
  assert.ok(html.includes(a.quote)&&html.includes(b.quote));
  assert.equal(JSON.stringify([a,b]),before);
  for(const change of [{speaker:'Speaker B · 6c7b'},{recording_id:'other'},{start_ms:360000,end_ms:362000},{speaker:'Speaker A · abcd'}]){
    assert.equal(groupEvidence([a,{...b,...change}]).length,2);
  }
});

test('review tab count includes stale approvals but excludes completed and superseded findings',async()=>{
  const {needsReview}=await import('../web/meeting-findings.js');
  const findings=[item,{...item,status:'approved'},{...item,status:'rejected'},
    {...item,status:'edited',evidence_current:false},{...item,superseded:true}];
  assert.equal(findings.filter(needsReview).length,2);
});


test('summary scopes confirmed results to selected recording and preserves source context',()=>{
  const first={...item,id:'first',evidence:[{...item.evidence[0],recording_id:'r1'}]};
  const second={...item,id:'second',evidence:[{...item.evidence[0],recording_id:'r2'}]};
  const note={...item,id:'note',evidence:[{...item.evidence[0],recording_id:null}]};
  const record={decisions:[first,second,note]};
  const html=approvedRecordHTML(record,'r1');
  assert.ok(html.includes('data-record-evidence="first"'));
  assert.ok(!html.includes('data-record-evidence="second"'));
  assert.ok(!html.includes('data-record-evidence="note"'));
  assert.ok(approvedRecordHTML(record,'notes').includes('data-record-evidence="note"'));
  assert.equal(approvedRecordHTML(record,'missing'),'');
  assert.equal(record.decisions.length,3);
});

test('history omits unchanged content and escapes changed type and summary',async()=>{
  const {findingHistoryHTML}=await import('../web/meeting-findings.js');
  const approved=findingHistoryHTML([{action:'approve',created_at:1,before:item,after:item}],item.id);
  assert.match(approved,/Approved/);
  assert.ok(!approved.includes('finding-change-before'));
  const edited=findingHistoryHTML([{action:'edit',created_at:1,before:item,after:{...item,kind:'action_item',statement:'<script>changed</script>'}}],item.id);
  assert.match(edited,/Action item/);
  assert.match(edited,/&lt;script&gt;changed&lt;\/script&gt;/);
});

test('speaker is separated only using cited names and aliases remain escaped',async()=>{
  const {findingContentHTML,findingEditorHTML}=await import('../web/meeting-findings.js');
  const f={...item,statement:'Speaker D asked about the schedule.',evidence:[{...item.evidence[0],speaker:'Speaker D'}],details:{speaker_names:{u:'Alice <Admin>'}}};
  const html=findingContentHTML(f);
  assert.match(html,/Alice &lt;Admin&gt;/);
  assert.match(html,/<p class="finding-statement">asked about the schedule\.<\/p>/);
  assert.ok(!html.includes('Speaker D'));
  assert.match(findingContentHTML({...f,statement:'Speaker Z asked about the schedule.'}),/Speaker Z asked/);
  assert.match(findingEditorHTML(f),/name="speaker_0"/);
});

test('evidence contributors do not become joint authors and order-only history is hidden',async()=>{
  const {findingContentHTML,findingHistoryHTML}=await import('../web/meeting-findings.js');
  const a={...item.evidence[0],speaker:'Speaker A'},b={...item.evidence[0],utterance_id:'v',speaker:'Speaker B'};
  const before={...item,statement:'Speaker A asked about the project.',evidence:[a,b]};
  const after={...before,evidence:[b,a]};
  const content=findingContentHTML(after);
  assert.match(content,/Speaker A/);
  assert.ok(!content.includes('Speaker B'));
  assert.equal(findingHistoryHTML([{action:'extraction_revision',created_at:1,before,after}],item.id),'');
  assert.ok(!findingContentHTML({...after,statement:'The project needs review.'}).includes('finding-speakers'));
  const changed=findingHistoryHTML([{action:'extraction_revision',created_at:1,before,after:{...after,statement:'Speaker B asked about the project.'}}],item.id);
  assert.equal(changed,'');
});

test('review UI keeps evidence and resolution consequences distinct without redundant pending badges',()=>{
  const normal=decisionListHTML([item]);
  assert.ok(!normal.includes('Needs review'));
  const stale=decisionListHTML([{...item,evidence_current:false,can_refresh_evidence:true}]);
  assert.match(stale,/Source changed/);
  assert.match(stale,/Review changes/);
  assert.ok(!stale.includes('data-approve-finding'));
  const resolution=decisionListHTML([{...item,kind:'unresolved_question',details:{resolved:true,answer:'The integration has been tested.'}}]);
  assert.match(resolution,/Answer found/);
  assert.match(resolution,/Confirm answer/);
  assert.ok(!resolution.includes('Answered ·'));
  assert.match(resolution,/Answered questions/);
});

test('answers are reviewable content and confirmed answers have a collapsed result section',()=>{
  const f={...item,kind:'unresolved_question',statement:'Who owns the launch?',details:{resolved:true,answer:'Bob <owner>'}};
  const html=decisionListHTML([f]);
  assert.match(html,/Suggested answer/);
  assert.match(html,/Bob &lt;owner&gt;/);
  assert.match(html,/Confirm answer/);
  assert.match(html,/Keep open/);
  assert.ok(!html.includes('data-reject-finding'));
  const record=approvedRecordHTML({answered_questions:[{...f,status:'approved'}]});
  assert.match(record,/<details class="answered-questions" data-record-evidence="answered-questions">/);
  assert.match(record,/Bob &lt;owner&gt;/);
  assert.match(record,/data-source-utterance="u"/);
  const legacy=decisionListHTML([{...f,details:{resolved:true}}]);
  assert.match(legacy,/Review answer/);
  assert.ok(!legacy.includes('data-approve-finding'));
});

import {findingsForRecording,nextReviewRecording,needsReview} from '../web/meeting-findings.js';
test('recording review scopes shared findings without copying their review state',()=>{
  const first={...item,id:'first',evidence:[{recording_id:'r1'}]};
  const shared={...item,id:'shared',evidence:[{recording_id:'r1'},{recording_id:'r2'}]};
  const second={...item,id:'second',evidence:[{recording_id:'r2'}]};
  const note={...item,id:'note',evidence:[{recording_id:null}]};
  const items=[first,shared,second,note];
  assert.deepEqual(findingsForRecording(items,'r1').map(f=>f.id),['first','shared']);
  assert.deepEqual(findingsForRecording(items,'r2').map(f=>f.id),['shared','second']);
  assert.deepEqual(findingsForRecording(items,'notes'),[note]);
  assert.deepEqual(findingsForRecording(items,'missing'),[]);
  assert.deepEqual(nextReviewRecording(items,'r1'),{id:'r2',count:2});
  shared.status='approved';
  assert.equal(findingsForRecording(items,'r2').filter(needsReview).length,1);
  assert.deepEqual(nextReviewRecording(items,'r1'),{id:'r2',count:1});
  second.status='rejected';note.status='approved';first.status='approved';
  assert.equal(nextReviewRecording(items,'r1'),null);
});

test('speaker editing keeps attribution out of the content field and preserves it on save',async()=>{
  const {findingEditorHTML,editedFindingStatement,findingContentHTML}=await import('../web/meeting-findings.js');
  const f={...item,statement:'Speaker B asked about Speaker A.',evidence:[{...item.evidence[0],speaker:'Speaker B'}]};
  assert.match(findingEditorHTML(f),/<legend>Rename speakers<\/legend>/);
  assert.match(findingEditorHTML(f),/>asked about Speaker A\.<\/textarea>/);
  assert.equal(editedFindingStatement(f,'asked about timing.'),'Speaker B asked about timing.');
  const renamed={...f,statement:editedFindingStatement(f,'asked about timing.'),details:{speaker_names:{u:'Alice'}}};
  assert.match(findingContentHTML(renamed),/Alice/);
  assert.ok(!findingContentHTML(renamed).includes('Speaker B'));
  assert.equal(editedFindingStatement(item,'A neutral summary.'),'A neutral summary.');
});

test('explicit speaker aliases render independently of question wording and in source',()=>{
  const f={...item,kind:'unresolved_question',statement:'Which option should we choose?',details:{speaker_names:{u:'Jason'}},status:'edited'};
  const html=approvedRecordHTML({unresolved_questions:[f]});
  assert.match(html,/Attributed speaker/);
  assert.match(html,/<span>Jason<\/span>/);
  assert.match(html,/Jason · 0:01/);
  assert.doesNotMatch(html,/Alice &amp; Bob/);
});

test('source text separates distinct speaker anchors and rename fields distinguish identities',async()=>{
  const {findingEditorHTML,findingSpeakers}=await import('../web/meeting-findings.js');
  const a={...item.evidence[0],speaker:'Speaker B · abcd',quote:'Which option',start_ms:0,end_ms:1200};
  const b={...a,utterance_id:'v',speaker:'Speaker B · efab',quote:'works?',start_ms:1200,end_ms:1800};
  const f={...item,evidence:[a,b]};
  const html=findingEditorHTML(f);
  assert.equal((html.match(/<blockquote>/g)||[]).length,2);
  assert.match(html,/>Which option<\/p>/);assert.match(html,/>works\?<\/p>/);
  assert.match(html,/data-source-utterance="u"/);
  assert.match(html,/data-source-utterance="v"/);
  assert.equal((html.match(/name="speaker_/g)||[]).length,1);
  assert.equal(findingSpeakers({...f,evidence:[a,{...a,utterance_id:'v'}]}).length,1);
  assert.equal(findingSpeakers(f).length,1);
});

test('source collapses duplicate references, keeps recordings distinct, and exposes subsecond timing',async()=>{
  const {evidenceTimeRange}=await import('../web/meeting-findings.js');
  assert.equal(evidenceTimeRange(162023,162119),'2:42.023–2:42.119');
  assert.equal(evidenceTimeRange(162023,162023),'2:42');
  const a={...item.evidence[0],recording_id:'abcd',speaker:'Speaker A',quote:'A repeated excerpt.'};
  const b={...a,utterance_id:'other',recording_id:'efab'};
  const html=approvedRecordHTML({decisions:[{...item,evidence:[a,a,b]}]});
  assert.equal((html.match(/A repeated excerpt\./g)||[]).length,2);
  assert.match(html,/Recording · abcd/);assert.match(html,/Recording · efab/);
  assert.equal((html.match(/data-source-utterance="u"/g)||[]).length,1);
});

test('uncertain adjacent fragments read together without assigning an unsupported speaker',()=>{
 const a={...item.evidence[0],speaker:'Unknown speaker',quote:'Which option',start_ms:71000,end_ms:75000};
 const b={...a,utterance_id:'tail',speaker:'Speaker B',quote:'works?',start_ms:75470,end_ms:75919};
 const html=approvedRecordHTML({decisions:[{...item,evidence:[a,b]}]});
 assert.equal((html.match(/<blockquote>/g)||[]).length,1);
 assert.match(html,/Which option works\?/);
 assert.match(html,/Unidentified speaker · 1:11–1:15/);
 assert.doesNotMatch(html,/source segments|Speaker B/);
 assert.match(html,/&quot;tail&quot;/);
});
