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
  return ['PUBLISHED','FAILED','ATTENTION','DEFERRED'].includes(status);
}

export function newAssetOperationId() { return crypto.randomUUID().replaceAll('-', ''); }
