// Semantic display types preserve explicit kinds; file formats stay separate.
const types=new Set(['map','blueprint','location','portrait']);
export const assetTypeLabels={map:'Map',blueprint:'Blueprint',location:'Location',portrait:'Portrait',artwork:'Artwork',video:'Video',audio:'Audio',document:'Document','model-3d':'3D',other:'Other'};
export const assetUploadTypes=['map','blueprint','location','portrait','artwork','video','audio','document','model-3d','other'];
export function assetTypeLabel(type){return assetTypeLabels[type]||String(type).replace(/[-_]+/g,' ').replace(/^./,value=>value.toUpperCase());}
export function assetLibraryType(asset) {
  if(types.has(asset.kind))return asset.kind;
  const tag=(Array.isArray(asset.tags)?asset.tags:asset.metadata?.tags||[]).find(value=>types.has(value));
  if(tag)return tag;
  const kind=asset.kind||asset.metadata?.kind;
  if(kind==='image')return 'artwork';
  if(kind&&!['unknown','unclassified','other'].includes(kind))return kind;
  return 'other';
}
const processingKinds=new Set(['transcript-summary','episode-composition','context','correction','capture-health','novel-brief','novel-options','novel-outline','novel-developmental-edit','novel-revision','novel-continuity','novel-line-copyedit','novel-proof','video-source-brief','video-treatment','video-screenplay','video-script-edit','video-shooting-script','video-breakdown','video-design','video-voice-casting','video-blocking','video-shot-list','video-edit-sound-vfx','video-preflight']);
export function ordinaryLibraryAsset(asset){
 const kind=asset.kind||asset.metadata?.kind||'',extra=asset.metadata?.extra||{};
 return !processingKinds.has(kind)&&!['processing','intermediate','internal'].includes(extra.relationshipRole)&&extra.browserPart===undefined&&!/(?:^|-)(?:provenance|receipts?|manifest|checkpoint|migration|audit|metadata|plans?|draft|storyboards?|packets?)(?:-|$)|^editorial-/.test(kind);
}
export function definitiveValidationError(error) {
  return Number(error?.status ?? error?.statusCode)===400;
}
export function generationTerminal(status) {
  return ['PUBLISHED','FAILED','ATTENTION','DEFERRED','BLOCKED','UNKNOWN'].includes(status);
}

export function newAssetOperationId() { return crypto.randomUUID().replaceAll('-', ''); }

// File format describes bytes, independently from the creative asset type.
export function assetFileFormat(asset) {
  const filename=asset.filename||asset.key?.split('/').at(-1)||asset.name||'';
  const extension=filename.match(/\.([a-z0-9]{1,12})$/i)?.[1]?.toUpperCase();
  if(extension)return extension;
  const mime=asset.contentType?.split(';')[0]?.toLowerCase();
  const formats={'application/json':'JSON','audio/wav':'WAV','audio/x-wav':'WAV','audio/mpeg':'MP3','video/mp4':'MP4','image/png':'PNG','image/jpeg':'JPG','image/webp':'WEBP','application/pdf':'PDF','text/plain':'TXT','model/gltf-binary':'GLB'};
  return formats[mime]||'File';
}


// Extensions only identify a displayable file format, never creative meaning.
export function assetIsImage(asset) {
  const contentType=asset.contentType?.split(';')[0]?.toLowerCase();
  if(contentType?.startsWith('image/'))return true;
  if(contentType&&contentType!=='application/octet-stream')return false;
  return ['PNG','JPG','JPEG','WEBP','GIF','AVIF','SVG','BMP'].includes(assetFileFormat(asset));
}
