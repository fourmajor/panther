// A creative asset's meaning comes from explicit metadata, never its filename.
const types=new Set(['map','blueprint','location']);
export function assetLibraryType(asset) {
  if(types.has(asset.kind))return asset.kind;
  const tag=(Array.isArray(asset.tags)?asset.tags:[]).find(value=>types.has(value));
  return tag || 'other';
}
export function definitiveValidationError(error) {
  return Number(error?.status ?? error?.statusCode)===400;
}
export function generationTerminal(status) {
  return ['PUBLISHED','FAILED','ATTENTION','DEFERRED','BLOCKED'].includes(status);
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
