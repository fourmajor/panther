// Exact event-time guard from radix-ui/primitives PR #4147 (commit b07b597).
// Remove after a stable upstream fix; never silently patch another release.
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
const version='1.1.19';
const digests={
  "js": {
    "original": "041f442853dfb1c6ff9255fc5f0e8c2fa4e50bef906ef8f4fe9b4a1f581f4f6a",
    "patched": "25231ca9c3f0ef517f5724574890cf0e04413710ddfeb68e317ff4fcac1d7057"
  },
  "mjs": {
    "original": "01df449a23d65bab1f2f2215a953cba74741419496ebd9a7932533f267cc873d",
    "patched": "b440bbad8d3f828d6145309540678be652585ca554cb645524fcfe40453e39ae"
  }
};
const guard=`      // Re-read the layer set at event time rather than trusting the value
      // captured during render. A layer registers itself in an effect, so
      // between that registration and the layers below it re-rendering with
      // their new index, they still see themselves as the highest layer and
      // would dismiss alongside it.
      // See: https://github.com/radix-ui/primitives/issues/4143
      const currentLayers = Array.from(context.layers);
      if (node && currentLayers[currentLayers.length - 1] !== node) {
        return;
      }

`;
export function patchSource(source,extension){
 const expected=digests[extension];
 if(!expected)throw new Error('Unsupported Radix module format');
 const digest=createHash('sha256').update(source).digest('hex');
 if(digest===expected.patched)return source;
 if(digest!==expected.original)throw new Error('Radix source changed; review the upstream fix before building');
 const result=source.replace('      onEscapeKeyDown?.(event);',guard+'      onEscapeKeyDown?.(event);');
 if(createHash('sha256').update(result).digest('hex')!==expected.patched)throw new Error('Radix patch verification failed');
 return result;
}
export async function applyPatch(){
 const root=fileURLToPath(new URL('../node_modules/@radix-ui/react-dismissable-layer/',import.meta.url));
 if(JSON.parse(await readFile(path.join(root,'package.json'),'utf8')).version!==version)throw new Error('Radix version changed; remove or review the nested Escape patch');
 const files=await Promise.all(['js','mjs'].map(async extension=>{
  const filename=path.join(root,'dist',`index.${extension}`),source=await readFile(filename,'utf8');
  return {filename,source,patched:patchSource(source,extension)};
 }));
 // Verify both distributions before modifying either one.
 for(const file of files)if(file.source!==file.patched)await writeFile(file.filename,file.patched);
 console.log(`Verified Radix DismissableLayer ${version} nested Escape guard`);
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)await applyPatch();
