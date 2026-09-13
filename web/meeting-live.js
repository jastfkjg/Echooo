// Keep results received during an HTTP request from being replaced by its older snapshot.
export class TranscriptUpdates {
  constructor() { this.version=0; this.rows=new Map(); }
  receive(row) { this.rows.set(row.id,{version:++this.version,row}); }
  merge(snapshot,since) {
    const rows=new Map(snapshot.map(row=>[row.id,row]));
    for(const update of this.rows.values())if(update.version>since)rows.set(update.row.id,update.row);
    return [...rows.values()];
  }
}
