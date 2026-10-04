import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {patchSource} from '../scripts/patch-radix-layer.mjs';
for(const extension of ['js','mjs'])test(`Radix ${extension} patch verifies originals, is idempotent and rejects changed source`,async()=>{
 const installed=await readFile(new URL(`../node_modules/@radix-ui/react-dismissable-layer/dist/index.${extension}`,import.meta.url),'utf8');
 const original=installed.replace(/      \/\/ Re-read the layer set[\s\S]*?(?=      onEscapeKeyDown\?\.\(event\);)/,'');
 assert.notEqual(original,installed);
 assert.equal(patchSource(original,extension),installed);
 assert.equal(patchSource(installed,extension),installed);
 assert.throws(()=>patchSource(original+'\n',extension),/source changed/);
});
