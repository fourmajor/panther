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
