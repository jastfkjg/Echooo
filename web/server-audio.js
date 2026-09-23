// Blob URLs work with the app's media CSP and are revoked after every playback.
export function serverAudioURL(encoded){
  if(typeof encoded!=='string'||!encoded)throw new Error('The speech service returned no audio.');
  const bytes=Uint8Array.from(atob(encoded),char=>char.charCodeAt(0));
  return URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
}
