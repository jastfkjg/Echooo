export function speakerName(value) {
  if (!value || /^(Unknown speaker|Speaker (PENDING|UNKNOWN)(\s|·|$))/i.test(value)) return 'Unidentified speaker';
  return value.replace(/^((?:Recovered speaker|Speaker) .+?)\s*·\s*[a-f0-9]+$/i, '$1');
}

// Presentation groups only: original utterances and audio anchors stay intact.
export function groupTranscript(records) {
  const normalized=text=>text.normalize('NFKC').toLocaleLowerCase().replace(/[\s\p{P}]/gu,'');
  const replyTexts=new Set(records.filter(u=>u.assistant).map(u=>normalized(u.content)));
  const groups = [];
  for (const record of records) {
    const last = groups.at(-1), speaker = speakerName(record.speaker);
    if (last && !replyTexts.has(normalized(record.content)) && !replyTexts.has(normalized(last.records.at(-1).content)) && !record.assistant && !last.records[0].assistant && last.speaker === speaker && last.recordingId === record.recording_id &&
        record.start_ms - last.records.at(-1).end_ms <= 12000 &&
        record.start_ms - last.records[0].start_ms <= 45000 &&
        last.length + record.content.length <= 450) {
      last.records.push(record);
      last.length += record.content.length;
    } else {
      groups.push({speaker, recordingId:record.recording_id, records:[record], length:record.content.length});
    }
  }
  // An uncertain presentation association, never a source reclassification.
  const replies=groups.filter(g=>g.records.length===1&&g.records[0].assistant&&!g.records[0].timing_estimated&&g.recordingId);
  const folded=new Set();
  for(const g of groups){
    if(g.records.some(u=>u.assistant||u.user_edited)||!g.recordingId||!/^Speaker [A-Z]+(?: \(connection \d+\))?$/.test(g.speaker))continue;
    const text=normalized(g.records.map(u=>u.content).join(' '));
    if(text.length<40)continue;
    const matches=replies.filter(reply=>{
      const a=reply.records[0],start=g.records[0].start_ms,end=g.records.at(-1).end_ms;
      return reply.recordingId===g.recordingId&&a.end_ms>a.start_ms&&
        start>=a.start_ms-250&&start<=a.end_ms&&end>=a.start_ms&&end<=a.end_ms+2000&&
        normalized(a.content)===text;
    });
    if(matches.length===1){(matches[0].echoGroups??=[]).push(g);folded.add(g);}
  }
  return groups.filter(g=>!folded.has(g));
}

export const transcriptRecords = meeting => [...meeting.utterances,...(meeting.assistant_utterances||[])];

export function recordingContent(meeting, recordingId) {
  const records = transcriptRecords(meeting).filter(u=>u.recording_id === (recordingId==='notes'?null:recordingId)).sort((a,b)=>a.start_ms-b.start_ms||a.end_ms-b.end_ms||(a.created_at||0)-(b.created_at||0));
  const humanRecords=records.filter(u=>!u.assistant);
  const ids = new Set(humanRecords.map(u=>u.id));
  const sections = meeting.sections.filter(s=>s.status!=='stale' && s.evidence_ids.length && s.evidence_ids.every(id=>ids.has(id)));
  const overview = [...(meeting.overviews||[])].reverse().find(s=>s.scope_key===recordingId);
  const covered = new Set(overview?.evidence_ids||[]);
  return {records, sections, overview, overviewCurrent:!!overview && overview.revision===meeting.revision && humanRecords.every(u=>covered.has(u.id))};
}

export function transcriptMatches(records, query) {
  const needle = query.trim().toLocaleLowerCase();
  return needle ? records.filter(u=>u.content.replace(/\s+/g,' ').toLocaleLowerCase().includes(needle)).map(u=>u.id) : [];
}

// Use literal matching, not a user-supplied regular expression or HTML.
export function searchParts(text, query) {
  const needle = query.trim();
  if (!needle) return [{text, match:false}];
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const matches = text.matchAll(new RegExp(escaped, 'giu'));
  const parts=[]; let offset=0;
  for (const match of matches) {
    if(match.index>offset)parts.push({text:text.slice(offset,match.index),match:false});
    parts.push({text:match[0],match:true});offset=match.index+match[0].length;
  }
  if(offset<text.length)parts.push({text:text.slice(offset),match:false});
  return parts;
}

export function playingUtterance(records, ms) {
  // Half-open intervals prevent the preceding sentence winning at a boundary.
  return records.find(u=>!u.assistant && u.recording_id && u.start_ms<=ms && ms<u.end_ms)?.id || null;
}

export const findingTypes = [
  {key:'knowledge',label:'Knowledge points',kinds:['knowledge'],description:'Concepts, procedures, constraints and examples explained in this meeting.'},
  {key:'decision',label:'Decisions',kinds:['decision'],description:'Explicitly adopted choices; not suggestions or descriptions of existing rules.'},
  {key:'action',label:'Follow-up actions',kinds:['action','commitment'],description:'Concrete future work requested or promised. Missing owners and dates remain unspecified.'},
  {key:'question',label:'Open questions',kinds:['question'],description:'Questions still unresolved, not teaching questions already answered.'},
  {key:'contradiction',label:'Possible conflicts',kinds:['contradiction'],description:'Potentially incompatible statements with sources for both sides.'},
  {key:'gap',label:'Missing action details',kinds:['gap'],description:'Missing information needed for an actual follow-up, not a mandatory checklist.'},
];

export function findingGroups(sections) {
  const items=sections.filter(s=>!['rejected','stale'].includes(s.status)).flatMap(s=>s.items||[]);
  return findingTypes.map(type=>({...type,items:items.filter(item=>type.kinds.includes(item.kind))})).filter(group=>group.items.length);
}

export function minutesContent(meeting, recordingId) {
  const minutes=(meeting.minutes||[]).find(s=>s.scope_key===recordingId);
  const records=meeting.utterances.filter(u=>u.recording_id===(recordingId==='notes'?null:recordingId));
  const covered=new Set(minutes?.evidence_ids||[]);
  return {minutes, current:!!minutes && minutes.revision===meeting.revision && minutes.status==='ready' && records.every(u=>covered.has(u.id))};
}
