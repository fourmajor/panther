import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import { query, clear, invalidate, revalidate, queryClient,createReadScheduler } from "../src/data-layer.js";
afterEach(clear);
test("read scheduler bounds concurrency and prioritizes an opened document",async()=>{
 const schedule=createReadScheduler({limit:2}),releases=[],started=[];
 const work=id=>schedule(()=>new Promise(resolve=>{started.push(id);releases.push(resolve);}));
 const first=work('a'),second=work('b'),background=work('thumbnail');
 const opened=schedule(async()=>{started.push('document');return 'read';},{priority:1});
 assert.deepEqual(started,['a','b']);releases.shift()();await first;await opened;
 assert.deepEqual(started,['a','b','document','thumbnail']);
 releases.shift()();releases.shift()();await Promise.all([second,background]);
});
test("transient GET errors retry only twice; permanent failures are not retried",async()=>{
 const schedule=createReadScheduler({wait:async()=>{}});let calls=0;
 assert.equal(await schedule(async()=>{calls++;if(calls<3)throw Object.assign(new Error('busy'),{status:503});return 'document';}),'document');assert.equal(calls,3);
 calls=0;await assert.rejects(schedule(async()=>{calls++;throw Object.assign(new Error('busy'),{status:429});}));assert.equal(calls,3);
 calls=0;await assert.rejects(schedule(async()=>{calls++;throw Object.assign(new Error('denied'),{status:403});}));assert.equal(calls,1);
});
test("concurrent reads deduplicate and warm navigation avoids another request", async () => {
  let calls = 0;
  const input = { scope: "fictional-reader", path: "/characters", parameters: { gameId: "campaign-a" }, fetcher: async () => { calls++; return { characters: [] }; } };
  await Promise.all([query(input), query(input)]);
  await query(input);
  assert.equal(calls, 1);
  await invalidate(input.scope);
  await query(input);
  assert.equal(calls, 2);
});
test("account and game cache keys cannot share data", async () => {
  const input = { scope: "fictional-reader", path: "/characters", parameters: { gameId: "campaign-a" }, fetcher: async () => "first" };
  assert.equal(await query(input), "first");
  assert.equal(await query({ ...input, parameters: { gameId: "campaign-b" }, fetcher: async () => "second" }), "second");
  assert.equal(await query({ ...input, scope: "other-reader", fetcher: async () => "third" }), "third");
});
test("live and signed URL reads can explicitly bypass freshness", async () => {
  let calls = 0;
  const input = { scope: "fictional-reader", path: "/object-url", parameters: { key: "asset-a" }, staleTime: 0, fetcher: async () => ++calls };
  await query(input); await query(input);
  assert.equal(calls, 2);
});
test("mutation invalidation preserves unrelated games and endpoint caches", async () => {
  const calls = new Map();
  const read = (gameId,path) => query({scope:"fictional-reader",path,parameters:{gameId},fetcher:async()=>{
    const id=gameId+path;calls.set(id,(calls.get(id)||0)+1);return {id};
  }});
  await read("game-a","/characters");await read("game-b","/characters");await read("game-a","/assets");
  await invalidate("fictional-reader",["/characters"],"game-a");
  await read("game-a","/characters");await read("game-b","/characters");await read("game-a","/assets");
  assert.equal(calls.get("game-a/characters"),2);
  assert.equal(calls.get("game-b/characters"),1);
  assert.equal(calls.get("game-a/assets"),1);
});
test("foreground revalidation requests stale visible data only and reports real changes", async () => {
  let calls=0;
  const input={scope:"fictional-reader",path:"/objects",parameters:{prefix:"games/game-a/"},fetcher:async()=>({revision:++calls})};
  await query(input);
  const view={scope:input.scope,paths:["/objects"],gameId:"game-a",filters:{"/objects":{prefix:"games/game-a/"}}};
  assert.deepEqual(await revalidate(view),[]);assert.equal(calls,1);
  queryClient.setQueryData(["api",input.scope,input.path,input.parameters],{revision:1},{updatedAt:Date.now()-61_000});
  const changed=await revalidate(view);
  assert.equal(calls,2);assert.equal(changed[0].data.revision,2);
});
