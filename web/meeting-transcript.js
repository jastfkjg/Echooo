export function speakerName(value) {
  if (!value || /^(Unknown speaker|Speaker (PENDING|UNKNOWN)(\s|·|$))/i.test(value)) return 'Unidentified speaker';
  return value.replace(/^(Speaker \S+)\s*·\s*[a-f0-9]+$/i, '$1');
}

// Presentation groups only: original utterances and audio anchors stay intact.
export function groupTranscript(records) {
  const groups = [];
  for (const record of records) {
    const last = groups.at(-1), speaker = speakerName(record.speaker);
    if (last && last.speaker === speaker && last.recordingId === record.recording_id &&
        record.start_ms - last.records.at(-1).end_ms <= 30000 &&
        record.start_ms - last.records[0].start_ms <= 120000 &&
        last.length + record.content.length <= 600) {
      last.records.push(record);
      last.length += record.content.length;
    } else {
      groups.push({speaker, recordingId:record.recording_id, records:[record], length:record.content.length});
    }
  }
  return groups;
}

export function recordingContent(meeting, recordingId) {
  const records = meeting.utterances.filter(u=>u.recording_id === (recordingId==='notes'?null:recordingId));
  const ids = new Set(records.map(u=>u.id));
  const sections = meeting.sections.filter(s=>s.status!=='stale' && s.evidence_ids.length && s.evidence_ids.every(id=>ids.has(id)));
  const overview = [...(meeting.overviews||[])].reverse().find(s=>s.scope_key===recordingId);
  const covered = new Set(overview?.evidence_ids||[]);
  return {records, sections, overview, overviewCurrent:!!overview && overview.revision===meeting.revision && records.every(u=>covered.has(u.id))};
}
