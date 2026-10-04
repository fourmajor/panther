import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assetLibraryType} from '../src/assets-library-data.js';
test('asset filters follow explicit kind or tags without guessing from names',()=>{
  assert.equal(assetLibraryType({kind:'map',tags:['location']}),'map');
  assert.equal(assetLibraryType({kind:'image',tags:['blueprint']}),'blueprint');
  assert.equal(assetLibraryType({kind:'location'}),'location');
  assert.equal(assetLibraryType({kind:'unknown',title:'Map of the coast',key:'maps/coast.png'}),'other');
  assert.equal(assetLibraryType({tags:'map'}),'other');
});
import {definitiveValidationError,generationTerminal} from '../src/assets-library-data.js';
test('only rejected validation permits replacing the immutable submission',()=>{
  assert.equal(definitiveValidationError({status:400}),true);
  assert.equal(definitiveValidationError({statusCode:400}),true);
  for(const error of [new Error('Failed to fetch'),{status:503},{status:409},{}])assert.equal(definitiveValidationError(error),false);
});
test('polling stops for durable outcomes without treating queued work as finished',()=>{
  for(const status of ['PUBLISHED','FAILED','ATTENTION','DEFERRED'])assert.equal(generationTerminal(status),true);
  for(const status of ['QUEUED','RUNNING','GENERATING','PENDING',undefined])assert.equal(generationTerminal(status),false);
});

import {newAssetOperationId} from '../src/assets-library-data.js';
test('asset operation identities use the exact backend 32-hex contract',()=>{
  const first=newAssetOperationId(),second=newAssetOperationId();
  assert.match(first,/^[0-9a-f]{32}$/);assert.match(second,/^[0-9a-f]{32}$/);assert.notEqual(first,second);
});


import {assetFileFormat} from '../src/assets-library-data.js';
test('file format stays distinct from semantic type and display title',()=>{
 assert.equal(assetFileFormat({kind:'map',name:'Riverlands',key:'games/demo/coast.png'}),'PNG');
 assert.equal(assetFileFormat({kind:'unknown',key:'games/demo/notes.json'}),'JSON');
 assert.equal(assetFileFormat({key:'games/demo/recording',contentType:'audio/wav'}),'WAV');
 assert.equal(assetFileFormat({kind:'map',name:'Coast'}),'File');
 assert.equal(assetFileFormat({filename:'room.WAV',contentType:'audio/wav'}),'WAV');
});


import {assetIsImage} from '../src/assets-library-data.js';
test('real image keys support thumbnails when result projections omit MIME',()=>{
 assert.equal(assetIsImage({key:'games/demo/assets/map/original/route.png'}),true);
 assert.equal(assetIsImage({key:'games/demo/assets/map/original/route.webp',contentType:'application/octet-stream'}),true);
 assert.equal(assetIsImage({key:'games/demo/assets/map/original/file',contentType:'image/png'}),true);
 assert.equal(assetIsImage({key:'games/demo/assets/map/original/route.png',contentType:'application/json'}),false);
 assert.equal(assetIsImage({key:'games/demo/assets/map/original/notes.json',kind:'map'}),false);
});


import {assetTypeLabel,ordinaryLibraryAsset} from '../src/assets-library-data.js';
test('all-library semantic types remain open and finished media keeps its kind',()=>{
 for(const kind of ['portrait','video','audio','document','model-3d','battle-map'])assert.equal(assetLibraryType({kind}),kind);
 assert.equal(assetLibraryType({kind:'image'}),'artwork');assert.equal(assetTypeLabel('battle-map'),'Battle map');
 assert.equal(ordinaryLibraryAsset({kind:'generation-provenance'}),false);
 assert.equal(ordinaryLibraryAsset({kind:'video',metadata:{extra:{relationshipRole:'processing'}}}),false);
 assert.equal(ordinaryLibraryAsset({kind:'portrait',metadata:{extra:{relationshipRole:'finished'}}}),true);
});
