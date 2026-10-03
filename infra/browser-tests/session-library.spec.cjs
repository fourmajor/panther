const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH} = require('../dist/lib/panther-media-explorer-stack');
const origin='https://panther.place', api='https://test.execute-api.us-west-2.amazonaws.com';
const headers={'access-control-allow-origin':origin};
const prefix='games/test-game/assets/';
const part=prefix+'recording-a/original/part-0000.flac', part2=prefix+'recording-a/original/part-0001.flac';
const recording=prefix+'recording-a/original/recording.json', raw=prefix+'recording-a/original/raw.json';
const continuous=prefix+'recording-a/original/playback-v1-aaaaaaaaaaaaaaaa.mp3';
// synthetic-continuous.mp3 is a 1.2-second 440 Hz generated tone, MP3 64 kbps, seek header.
const playbackManifest=continuous.replace('.mp3','.json');
const corrected=prefix+'corrected-a/original/corrected.json', video=prefix+'video-a/original/take.mp4';
// Synthetic quarter-second 440 Hz FLAC; no private recording or user credentials.
const flac=Buffer.from('ZkxhQwAAACICQAJAAAAAAASVAfQA8AAAAAAAAAAAAAAAAAAAAAAAAAAAhAAALAwAAABMYXZmNjEuNy4xMDABAAAAFAAAAGVuY29kZXI9TGF2ZjYxLjcuMTAw//gkCADKTgAABWsKMg3FD7YPzQ4FCpTmMQqH2KXbLDk9DhuCxn3GhDapRYRihDCNVLEYlostLLqSkWUUqTCMWULJSVZWWlFIpYjKrEwjBaKSlkYTTBGFJKJhOKyyogQknNClMmBBAIhSIWckKQocpphEApJCIEEAgIacwoBBAwICAQTygQQJSFCkoXkyFDDORAIIFDAoTJ0NCkxKRSxGVWJhGC0UlLIwmmCMKSUTCcVllRZJKlZa1JQjCZaZcqSLRZUtWomFpImIwhlapRYRihDCNVLEAIEpChSULyZChhnIgEEChgUJk6GhSYZDKBBD0CIBBACkMmUIIBEiAEEAyTCIBGGhQ4UJJzQpTJgQQCIUiFmAl3X/+CQIAc1O8YfwE/CB8sX2mfuJAQEGWuYytIU6h1uuKGk+5eIG/k6AAaUlMIgHDCIEQCCSJwwoEEDCCARmhQIgQiQIhkicyZAoZnIgEEMwoTJ0NCkMOGUCCSlAiBBAOBkpQiARKAQQJkKEQIoGIFOBkzmIUzJgQQCmULOSFIUNKSmEQDhhECIBBJE4YUCCBhBAIzQoEQIRIEQyROZMgUMzkQCCGYUJk6GhSGHDKBBJSgRAggHAyUoRAIlAIIEyFCIEUDECnAyZzEKZkwIIBTKFnJCkKGlJTCIBwwiBEAgkicMKBBAwggEZoUCIEIkCIZInMmQKGZyIBBDMKEydDQpDDhlAgkpQIgQQDgZKUIgESgEECZChECKBiBTgZM5AZPj/+CQIAsRODFQIJQMA/YD4TPQB8SHwA+Yww4pGnCc+GUItwUNlfWaEATAggEQpELMkhSU9JmEQCkyIEEAgIaTMKAQQKBAQCCZhQCIEpClNMmSSFClLIgEEChgUJnocMkhzKBEypQmEYLRUpZGEyYIwpSyMTisopFKlVZZRRKEYTLTLlJItLVWlKJhaUmIwhlaUosIxYhhGpRYTEtFoE0yZJIUKUsiAQQKGBQmehwySHMoEEOYEQCCAFIcyhBAIhEAIIBmUIIEYaGGQzn0KGGEwIIBEKRCzJIUlFVaUomFpSYjCGVpSiwjFiGEalFhMS0WtWpKSSLLWuTCMWULJSqyopJFSliMqUJhGC0VKWRhMmCMKUH0G//h0CAMBDxBOA/oI/QzxD1wP9w6vC6kHQ+WaXbqQXRevWFKfdMDg/0gALZZUKJJVTJrSIoIwTKmTlpIoiytOnRMKQkTEYQZRqihQRhRDCOvTCMIsQstJrqSSFiir0YQxaQsSiq15aKEkJLEanYmEYFoKS00YRrBGEkRQjCPJssqFEkqpk1pEUEYJlTJy0kURZWnTomFIQPxi','base64');
const assets=[
  [part,'recording',[], 'audio/flac'],[part2,'recording',[],'audio/flac'],
  [recording,'recording-manifest',[part,part2],'application/json'],
  [recording.replace('recording.json','capture.json'),'recording-manifest',[],'application/json'],
  [raw,'raw-transcript',[recording],'application/json'],
  [raw.replace('.json','.md'),'raw-transcript',[recording],'text/markdown'],
  [corrected,'corrected-transcript',[raw],'application/json'],
  [video,'video-comparison',[corrected],'video/mp4'],
  [continuous,'recording-playback',[playbackManifest],'audio/mpeg'],
  [playbackManifest,'recording-playback-manifest',[recording,part,part2],'application/json'],
].map(([key,kind,sourceKeys,contentType])=>({key,kind,sourceKeys,contentType,recording:key===recording?{partCount:2,status:'interrupted'}:undefined,name:key.split('/').at(-1),size:100,lastModified:'2026-01-01T12:00:00Z',metadata:{title:kind,sessionId:'session-one'}}));
assets.find(a=>a.key===playbackManifest).playback={recordingKey:recording,audioKey:continuous,durationSeconds:1.2,sourceManifestSha256:'a'.repeat(64)};
assets.find(a=>a.key===video).metadata.extra={generation:{schemaVersion:1,method:'ai',model:'Kling 3 Pro',provider:'fal',inference:'remote',cost:{status:'billed',amount:'1.344',currency:'USD'},evidence:'Synthetic billing event'}};

async function fixture(page) {
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-operator'}))+'.test'})));
  await page.route(`${origin}/**`,route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:`window.PANTHER_CONFIG={apiUrl:'${api}',clientId:'test',cognitoDomain:'https://test.amazoncognito.com',redirectUri:'${origin}/'};`});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('https://audio.example/**',route=>route.fulfill({body:flac,contentType:'audio/flac',headers:{'accept-ranges':'bytes'}}));
  await page.route('https://audio.example/playback-*.mp3',route=>route.fulfill({body:fs.readFileSync(path.join(__dirname,'synthetic-continuous.mp3')),contentType:'audio/mpeg',headers:{'accept-ranges':'bytes'}}));
  await page.route(`${api}/**`,route=>{
    const u=new URL(route.request().url()), game=u.searchParams.get('gameId'), key=u.searchParams.get('key');
    const games=[{id:'test-game',name:'Test Game',purpose:'test'},{id:'other-game',name:'Other Game',purpose:'campaign'}];
    let body={};
    if(u.pathname==='/games') body={games};
    if(u.pathname==='/game') body={game:games.find(g=>g.id===game),players:[],memberships:[],characters:[]};
    if(u.pathname==='/assets') body=game==='test-game'?{assets,cursor:null}:{assets:[],cursor:null};
    if(['/episodes','/scenes'].includes(u.pathname))body={records:[],cursor:null};
    if(u.pathname==='/objects') body={prefixes:[],objects:[],nextCursor:null};
    if(u.pathname==='/object-url') body={...assets.find(a=>a.key===key),url:`https://audio.example/${key.split('/').at(-1)}`,expiresIn:300};
    if(u.pathname==='/asset-document') {
      const transcript={entityType:'PlayerTranscript',players:[{id:'alex',name:'Alex'}],captureIntegrity:{warnings:['Synthetic capture gap']},segments:[{start:0,end:2,playerId:'alex',text:key===raw?'The lanturn.':'The lantern.',originalText:'The lanturn.',uncertainty:'Test spelling'}, {start:2,end:4,playerId:null,text:'<script>window.attacked=true</script> Pizza?'}]};
      body={...assets.find(a=>a.key===key),document:key===recording?{entityType:'Recording',status:'interrupted',parts:[{file:'part-0000.flac',start:0},{file:'part-0001.flac',start:.6}]}:key===raw?transcript:{stage:'corrected-transcript',reviewStatus:'ai-reviewed-unverified',payload:{transcript,review:{passed:true}}}};
    }
    return route.fulfill({json:body,headers});
  });
}

for(const width of [1280,390])test(`episode-owned scenes can be created without finished clips at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);const episodes=[],scenes=[],writes=[];
 await page.route(`${api}/episodes*`,route=>{if(route.request().method()==='POST'){const body=route.request().postDataJSON();writes.push(body);const record={...body,revision:'a'.repeat(32),position:0};episodes.push(record);return route.fulfill({headers,json:{record}});}return route.fulfill({headers,json:{records:episodes,cursor:null}});});
 await page.route(`${api}/scenes*`,route=>{if(route.request().method()==='POST'){const body=route.request().postDataJSON();writes.push(body);const record={...body,revision:'b'.repeat(32),position:0};scenes.push(record);const parent=episodes.find(episode=>episode.id===record.episodeId);const episodeRecord={...parent,sceneIds:[...parent.sceneIds,record.id],revision:'c'.repeat(32)};episodes[episodes.indexOf(parent)]=episodeRecord;return route.fulfill({headers,json:{record,episodeRecord}});}return route.fulfill({headers,json:{records:scenes,cursor:null}});});
 await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets:[],cursor:null}}));
 await page.goto(`${origin}/games/test-game/videos`);
 await expect(page.getByRole('button',{name:'TV episodes',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Generate video',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Create Episode',exact:true}).click();
 const episodeDialog=page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Episode editor'})});await expect(episodeDialog).toBeVisible();await expect(episodeDialog).toBeInViewport();
 const episodeBox=await episodeDialog.boundingBox();expect(episodeBox.width).toBeLessThanOrEqual(width-16);expect(episodeBox.height).toBeLessThan(850);
 expect(await page.getByRole('form',{name:'Episode editor'}).evaluate(form=>Boolean(form.closest('[role=dialog]')))).toBe(true);
 await page.getByLabel('Episode title',{exact:true}).fill('The crossing');
 await page.getByRole('form',{name:'Episode editor'}).getByRole('button',{name:'Create Episode',exact:true}).click();
 await expect(episodeDialog).toHaveCount(0);await page.getByRole('button',{name:'Add scene',exact:true}).click();
 const sceneDialog=page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Scene editor'})});await expect(sceneDialog).toBeVisible();await expect(sceneDialog).toBeInViewport();
 await page.getByLabel('Scene title',{exact:true}).fill('Lanterns on the river');
 await page.getByRole('combobox',{name:'Scene type',exact:true}).click();await page.getByRole('option',{name:'Action',exact:true}).click();
 await page.getByRole('form',{name:'Scene editor'}).getByRole('button',{name:'Add scene',exact:true}).click();
 const workspace=page.locator('#episode-workspace');await expect(workspace.getByRole('heading',{name:'Lanterns on the river',exact:true})).toBeVisible();
 expect(writes).toHaveLength(2);expect(writes[1].episodeId).toBe(writes[0].id);expect(writes[1].type).toBe('action');expect(writes[1]).not.toHaveProperty('assetKeys');
 await expect(sceneDialog).toHaveCount(0);await expect(workspace.getByRole('button',{name:'Generate video',exact:true})).toHaveCount(0);
 await expect(workspace.locator('#scene-video-composer')).toBeVisible();
 await expect(workspace.locator('.episode-cards')).toBeHidden();await expect(workspace.locator('.episode-scenes-panel').getByRole('button',{name:'Lanterns on the river',exact:true})).toBeVisible();
 const toolbarActions=[workspace.getByRole('button',{name:'Add scene',exact:true}),workspace.getByRole('button',{name:'Edit episode',exact:true}),workspace.getByRole('button',{name:'Edit scene',exact:true})];
 const actionBoxes=[];for(const action of toolbarActions){await expect(action).toBeVisible();await expect(action).toBeInViewport();const bounds=await action.boundingBox();expect(bounds.height).toBeLessThanOrEqual(48);actionBoxes.push(bounds);expect(await action.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);}
 expect(Math.max(...actionBoxes.map(box=>box.height))-Math.min(...actionBoxes.map(box=>box.height))).toBeLessThanOrEqual(2);
 const list=await workspace.locator('.episode-scenes-panel').boundingBox(),focused=await workspace.locator('.episode-scene-panel').boundingBox();
 if(width>800){expect(list.x+list.width).toBeLessThanOrEqual(focused.x);expect(Math.max(list.y,focused.y)).toBeLessThan(Math.min(list.y+list.height,focused.y+focused.height));}else expect(list.y+list.height).toBeLessThanOrEqual(focused.y);
 const back=workspace.getByRole('button',{name:'← Video Episodes',exact:true});await expect(back).toBeVisible();
 await expect(workspace.locator('textarea')).toHaveCount(0);await expect(workspace.locator('#scene-video-composer').getByRole('button',{name:'Generate',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath(`episodes-scenes-${width}.png`),fullPage:true});
 await page.reload();await expect(workspace.getByRole('heading',{name:'Lanterns on the river',exact:true})).toBeVisible();
 await workspace.getByRole('button',{name:'← Video Episodes',exact:true}).click();await expect(workspace.locator('.episode-cards')).toBeVisible();await expect(page.getByLabel('Search episodes',{exact:true})).toBeVisible();await expect(page).not.toHaveURL(/episode=/);
 await workspace.getByRole('button',{name:'The crossing',exact:true}).click();await expect(workspace.getByRole('heading',{name:'Lanterns on the river',exact:true})).toBeVisible();
 await workspace.getByRole('button',{name:'Edit scene',exact:true}).click();const editDialog=page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Scene editor'})});await editDialog.getByLabel('Scene title',{exact:true}).fill('Unsaved title');await editDialog.getByRole('button',{name:'Cancel',exact:true}).click();await expect(editDialog).toHaveCount(0);expect(writes).toHaveLength(2);await expect(workspace.getByRole('heading',{name:'Lanterns on the river',exact:true})).toBeVisible();
});
for(const status of [403,503])test(`episode creation remains available when finished videos fail with ${status}`,async({page})=>{
 await fixture(page);await page.route(`${api}/assets*`,route=>route.fulfill({status,headers,json:{error:'Synthetic catalog failure'}}));
 await page.goto(`${origin}/games/test-game/videos?view=episodes&episode=old-unmigrated`);
 await expect(page.locator('#library-status')).toContainText(status===403?'cannot access finished videos':'Finished videos unavailable');
 await expect(page.locator('#episode-workspace')).toContainText('This episode is unavailable');
 await page.getByRole('button',{name:'Create Episode',exact:true}).click();await expect(page.getByLabel('Episode title',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'TV episodes',exact:true})).toHaveCount(0);
});

for(const width of [1280,390]) test(`Video assets retain playable captions outside episode library at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000});await fixture(page);
  const second=prefix+'second-video/original/take.webm',poster=prefix+'poster-a/original/frame.svg';
  const caption=video.slice(0,video.lastIndexOf('/')+1)+'captions.vtt';
  const clip=(key,title,category,tags)=>({key,name:key.split('/').at(-1),kind:'silly-video',contentType:'video/webm',size:100,lastModified:'2026-01-01T12:00:00Z',sourceKeys:[],metadata:{title,description:'Synthetic test clip',category,tags,characterIds:['hero'],extra:{creator:'Example Artist',preview:{schemaVersion:1,imageKey:poster}}}});
  const videos=[clip(video,'Practice joke','playful-derivative',['table-joke','canonical']),clip(second,'Scene test','creative-reimagining',['experiment'])];
  const captionAsset={key:caption,name:'captions.vtt',kind:'video-captions',contentType:'text/vtt',size:80,lastModified:'2026-01-01T12:00:00Z',sourceKeys:[],metadata:{title:'Synthetic captions'}};
  let galleryRequests=0;
  await page.route(`${api}/assets?**`,route=>route.fulfill({headers,json:{assets:new URL(route.request().url()).searchParams.get('section')==='videos'?videos:[...videos,captionAsset],cursor:null}}));
  await page.route(`${api}/game?**`,route=>route.fulfill({headers,json:{game:{id:'test-game',name:'Test Game',purpose:'test'},players:[],memberships:[],characters:[{id:'hero',name:'Example Hero'}]}}));
  const collection={schemaVersion:1,entityType:'VideoCollection',id:'favorites',name:'Favorite takes',description:'Ordered synthetic clips',assetKeys:[second,video],revision:'a'.repeat(32)};
  await page.route(`${api}/video-collections?**`,route=>route.fulfill({headers,json:new URL(route.request().url()).searchParams.get('id')?{collection,assets:[videos[1],videos[0]],warnings:[]}:{collections:[collection],cursor:null}}));
  await page.route(`${api}/image-links`,route=>{galleryRequests++;return route.fulfill({headers,json:{images:{[poster]:{url:'https://audio.example/frame.svg'}},expiresIn:300}});});
  await page.route('https://audio.example/frame.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#647552"/></svg>'}));
  await page.route(`${api}/object-url?**`,route=>{
    const key=new URL(route.request().url()).searchParams.get('key');
    return route.fulfill({headers,json:{...(videos.find(a=>a.key===key)||captionAsset),expiresIn:300,url:key===caption?'https://audio.example/captions.vtt':'https://audio.example/test.webm'}});
  });
  await page.route('https://audio.example/captions.vtt',route=>route.fulfill({headers,contentType:'text/vtt',body:'WEBVTT\n\n00:00.000 --> 00:01.000\nSynthetic caption\n'}));
  await page.goto(`${origin}/games/test-game/videos`);
  // Browser-created footage is synthetic and remains inside the isolated test runner.
  const bytes=await page.evaluate(async()=>{
    const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;
    const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];
    recorder.ondataavailable=e=>parts.push(e.data);const done=new Promise(r=>recorder.onstop=r);recorder.start();
    for(let i=0;i<12;i++){canvas.getContext('2d').fillRect(0,0,160,90);await new Promise(r=>setTimeout(r,100));}
    recorder.stop();await done;stream.getTracks().forEach(t=>t.stop());return Array.from(new Uint8Array(await new Blob(parts).arrayBuffer()));
  });
  await page.route('https://audio.example/test.webm',route=>route.fulfill({contentType:'video/webm',body:Buffer.from(bytes)}));
  await expect(page.locator('.video-card')).toHaveCount(0);
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(video)}`);
  const body=page.locator('#preview-body');await expect(page.locator('#preview-title')).toHaveText('Practice joke');
  await expect(body.getByRole('heading',{name:'Caption tracks'})).toBeVisible();
  await body.getByRole('button',{name:'Load selected captions'}).click();
  await expect(body).toContainText('Selected captions loaded');
  await expect.poll(()=>body.locator('video track').evaluate(t=>t.readyState)).toBe(2);
  expect(await body.locator('video track').evaluate(t=>t.track.mode)).toBe('showing');
  const original=body.getByRole('link',{name:'Open caption export · Synthetic captions'});
  await expect(original).toBeVisible();
  const viewport=await body.boundingBox();await page.mouse.move(viewport.x+viewport.width/2,viewport.y+viewport.height/2);
  for(let scrolls=0;scrolls<5;scrolls++) {
    const box=await original.boundingBox();if(box.y+box.height<viewport.y+viewport.height)break;
    await page.mouse.wheel(0,200);await expect.poll(async()=>(await original.boundingBox()).y).toBeLessThan(box.y);
  }
  await expect(original).toBeInViewport();
  expect(await original.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await page.screenshot({path:test.info().outputPath(`video-captions-${width}.png`)});
  await page.keyboard.press('Escape');await expect(page.locator('#preview-body')).toBeEmpty();
});

test('Legacy collection query does not add a second video library',async({page})=>{
 await fixture(page);let reads=0;await page.route(`${api}/video-collections?**`,route=>{reads++;return route.fulfill({status:503,headers,json:{error:'Try later'}});});
 await page.goto(`${origin}/games/test-game/videos?collection=favorites`);await expect(page.locator('.video-card')).toHaveCount(0);await expect(page.getByText('Create your first episode.',{exact:true})).toBeVisible();expect(reads).toBe(0);
});

for (const width of [1280,390]) test(`transcript search, versions, canonical choice and continuous source at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900}); await fixture(page);
  const records=assets.map(a=>({...a,metadata:{...a.metadata,extra:{...a.metadata.extra,
    version:{schemaVersion:1,seriesId:a.key===corrected?'corrected-series':'raw-series',number:1}}},
    ...([raw,corrected].includes(a.key)?{transcript:{state:'available',participants:[{id:'alex',name:'Alex',segmentCount:1}],unassignedSegments:1,reviewStatus:a.key===raw?'unreviewed':'ai-reviewed-unverified'}}:{})}));
  await page.route(`${api}/assets?**`,route=>route.fulfill({headers,json:{assets:records,cursor:null}}));
  let selection=null,submitted;
  await page.route(`${api}/transcript-selection**`,route=>{
    if(route.request().method()==='POST') {
      submitted=route.request().postDataJSON();
      expect(submitted.key).toBe(raw); expect(submitted.expectedRevision).toBeNull();
      expect(submitted.operationId).toMatch(/^[a-f0-9]{32}$/);
      selection={...submitted,revision:'a'.repeat(32)};
    }
    return route.fulfill({headers,json:{selection}});
  });
  await page.goto(`${origin}/games/test-game/transcripts`);
  await expect(page.locator('.transcript-session')).toHaveCount(1);
  await expect(page.locator('.transcript-session')).toContainText('Alex');
  await page.locator('.transcript-session').getByRole('link',{name:'raw-transcript',exact:true}).click();
  const body=page.locator('#preview-body'),tools=page.getByRole('dialog',{name:'Transcript tools',exact:true});
  await expect(body).toContainText('No canonical reading version has been designated');
  await expect(body.locator('.transcript-segment')).toHaveCount(2);
  await expect(body.locator('details,summary')).toHaveCount(0);
  const navigationButton=body.getByRole('button',{name:'Transcript tools',exact:true});
  await navigationButton.click();await expect(page.getByRole('dialog',{name:'Transcript tools',exact:true}).getByLabel('Search speech or player names')).toBeVisible();
  await expect(tools.getByRole('button',{name:'Close',exact:true})).toBeFocused();
  await tools.evaluate(async node=>{await Promise.all(node.getAnimations({subtree:true}).filter(animation=>Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation=>animation.finished.catch(()=>{})));});
  await page.keyboard.press('Escape');await expect(navigationButton).toBeFocused();
  await expect(page.getByRole('dialog',{name:'Transcript tools',exact:true}).getByLabel('Search speech or player names')).not.toBeVisible();
  await expect(body.locator('.transcript-segment').first()).toBeInViewport();
  await page.screenshot({path:test.info().outputPath(`transcript-first-${width}.png`)});
  await expect(body.locator('.transcript-seek').first()).toBeEnabled();
  await body.locator('.transcript-seek').first().click();
  await expect(tools.locator('audio')).toBeVisible();
  await expect(page.getByRole('dialog',{name:'Transcript tools',exact:true}).getByLabel('Search speech or player names')).toBeVisible();
  const search=page.getByRole('dialog',{name:'Transcript tools',exact:true}).getByLabel('Search speech or player names');
  await search.fill('Pizza'); await search.press('Enter');
  await expect(page.getByRole('dialog',{name:'Transcript tools',exact:true})).toContainText('Match 1 of 1');
  await expect(body.locator('.transcript-current-match')).toContainText('Pizza?');
  await expect(body.locator('.transcript-segment')).toHaveCount(2);
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  await expect(tools.locator('audio')).toBeVisible();
  await expect(body.locator('.transcript-seek').first()).toBeEnabled();
  await expect.poll(()=>tools.locator('audio').evaluate(a=>a.paused)).toBe(false);
  await tools.getByRole('button',{name:'Choose this canonical reading version',exact:true}).click();
  await page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByLabel('Selection reason').fill('Prefer original evidence for this test');
  await page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByRole('checkbox').check();
  await page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByRole('button',{name:'Use this version as canonical'}).click();
  await expect(page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true})).toContainText('Selection saved. Immutable transcripts and review state are unchanged');
  await page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByRole('button',{name:'Close',exact:true}).click();
  await expect(tools).toContainText('Viewing the canonical reading version');
  expect(submitted.reason).toBe('Prefer original evidence for this test');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`transcript-reader-${width}.png`)});
  await tools.getByLabel('Session transcript version').selectOption(corrected);
  await expect(body).toContainText('The lantern.');
  await expect(body).toContainText('Viewing a non-canonical version');
  await body.getByRole('button',{name:'Transcript tools',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Transcript tools',exact:true}).getByRole('link',{name:'Open canonical reading version'})).toBeVisible();
  await expect(body).toContainText('ai-reviewed-unverified');
});

test('canonical selection failure never claims success and retries the exact operation',async({page})=>{
  await fixture(page); let attempts=[];
  await page.route(`${api}/transcript-selection**`,route=>{
    if(route.request().method()==='POST') {
      attempts.push(route.request().postDataJSON());
      return route.fulfill({status:409,headers,json:{error:'Selection changed; reload'}});
    }
    return route.fulfill({headers,json:{selection:null}});
  });
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(raw)}`);
  const body=page.locator('#preview-body');
  await body.getByRole('button',{name:'Transcript tools',exact:true}).click();
  await page.getByRole('dialog',{name:'Transcript tools',exact:true}).getByRole('button',{name:'Choose this canonical reading version',exact:true}).click();
  await page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByLabel('Selection reason').fill('Reading preference');
  await page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByRole('checkbox').check();
  const save=page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true}).getByRole('button',{name:'Use this version as canonical'});
  await save.click(); await expect(page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true})).toContainText('Selection not confirmed');
  await save.click(); await expect.poll(()=>attempts.length).toBe(2);
  expect(attempts[1]).toEqual(attempts[0]);
  await expect(page.getByRole('dialog',{name:'Choose this canonical reading version',exact:true})).not.toContainText('Selection saved');
});

for(const width of [1280,390])test(`Episode catalog loading and pagination preserve visible records at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);let firstRelease,secondRelease,reads=0;const first=new Promise(resolve=>firstRelease=resolve),second=new Promise(resolve=>secondRelease=resolve);
 await page.route(`${api}/episodes?**`,async route=>{reads++;const cursor=new URL(route.request().url()).searchParams.get('cursor');await(cursor?second:first);return route.fulfill({headers,json:{records:[{id:cursor?'later':'first',name:cursor?'Later episode':'First episode',sceneIds:[],revision:'a'.repeat(32)}],cursor:cursor?null:'next'}});});
 await page.goto(`${origin}/games/test-game/videos`);const status=page.locator('#episode-workspace [data-episode-empty]');await expect(status.locator('.loading-skeleton')).toBeVisible();expect(await status.locator('.loading-skeleton').evaluate(node=>getComputedStyle(node).animationName)).toBe('panther-pulse');await page.emulateMedia({reducedMotion:'reduce'});expect(await status.locator('.loading-skeleton').evaluate(node=>getComputedStyle(node).animationName)).toBe('none');firstRelease();await expect(page.locator('.episode-card')).toHaveCount(1);const more=page.getByRole('button',{name:'More episodes',exact:true});await more.click();await expect(page.locator('.episode-card')).toHaveCount(1);await expect(page.locator('.episode-card')).toHaveAccessibleName('First episode');secondRelease();await expect(page.locator('.episode-card')).toHaveCount(2);expect(reads).toBe(2);await expect(more).toHaveCount(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('Asset preview omits version navigation while retaining immutable original download', async ({page}) => {
  await fixture(page);
  const earlier = prefix + 'video-earlier/original/take.mp4';
  const series = 'synthetic-film-series';
  const pair = [
    {...assets.find(asset => asset.key === video), metadata: {title:'Newer cut', extra:{version:{schemaVersion:1,seriesId:series,number:2,previousKey:earlier}}}},
    {key:earlier, name:'take.mp4', kind:'video-comparison', contentType:'video/mp4', size:100,
      lastModified:'2025-12-31T12:00:00Z', sourceKeys:[], metadata:{title:'Earlier cut', extra:{version:{schemaVersion:1,seriesId:series,number:1}}}},
  ];
  const mutations=[];
  page.on('request',request=>{if(request.url().startsWith(api)&&!['GET','OPTIONS'].includes(request.method()))mutations.push(request.url());});
  await page.route(`${api}/assets?**`, route => route.fulfill({headers,json:{assets:pair,cursor:null}}));
  const catalogResponse=page.waitForResponse(response=>response.url().startsWith(`${api}/assets?`));
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(video)}`);
  await expect(page.getByRole('heading',{name:'Versions',exact:true})).toHaveCount(0);await expect(page.locator('#asset-versions')).toHaveCount(0);await expect(page.getByRole('link',{name:'Download',exact:true})).toHaveAttribute('href','https://audio.example/take.mp4');
  const served=(await(await catalogResponse).json()).assets;
  expect(served.find(asset=>asset.key===video).metadata.extra.version.previousKey).toBe(earlier);
  expect(served.find(asset=>asset.key===earlier).metadata.extra.version.number).toBe(1);
  expect(mutations).toEqual([]);
});

test('failed catalog removes activity and offers recovery', async ({page}) => {
  await fixture(page);
  await page.route(`${api}/assets?**`,route=>route.fulfill({status:503,json:{error:'Temporarily unavailable'},headers}));
  await page.goto(`${origin}/games/test-game/videos`);
  await expect(page.locator('#library-status')).toContainText('Temporarily unavailable');
  await expect(page.locator('#library-status .loading-state')).toHaveCount(0);
});

for (const width of [1280,390]) for (const filename of ['portrait.png','take.mp4','model.blend']) {
  test(`original download uses selected revision and fresh attachment link: ${filename} at ${width}`, async ({page}) => {
    await page.setViewportSize({width,height:900}); await fixture(page);
    const key=prefix+'revision-two/original/'+filename;
    let signed=0;
    await page.route(`${api}/object-url?**`, route => {
      const query=new URL(route.request().url()).searchParams;
      expect(query.get('key')).toBe(key);
      const downloading=query.get('download')==='true';
      if(downloading) signed++;
      const contentType=filename.endsWith('.png')?'image/png':filename.endsWith('.mp4')?'video/mp4':'application/octet-stream';
      return route.fulfill({headers,json:{key,filename,size:14,contentType,expiresIn:300,
        url:downloading?`https://audio.example/download/${signed}`:'https://audio.example/preview'}});
    });
    await page.route('https://audio.example/download/**',route=>route.fulfill({contentType:'application/octet-stream',
      headers:{'content-disposition':`attachment; filename="${filename}"`},body:Buffer.from('original bytes')}));
    await page.route('https://audio.example/preview',route=>route.fulfill({contentType:'image/svg+xml',
      body:'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240"><rect width="400" height="240" fill="#334436"/></svg>'}));
    await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(key)}`);
    const button=page.getByRole('link',{name:'Download',exact:true});
    await expect(button).toBeEnabled();
    await page.locator('#preview-dialog').evaluate(el=>el.scrollTop=el.scrollHeight);
    await expect(button).toBeInViewport();
    await expect(page.getByRole('link',{name:'Open original',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Download original',exact:true})).toHaveCount(0);await expect(page.locator('#preview-details')).toHaveCount(0);
    for(let i=0;i<2;i++) {
      const pending=page.waitForEvent('download'); await button.click();
      const downloaded=await pending;
      expect(downloaded.suggestedFilename()).toBe(filename);
      expect(fs.readFileSync(await downloaded.path(),'utf8')).toBe('original bytes');
    }
    expect(signed).toBe(2);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:test.info().outputPath(`download-${filename}-${width}.png`)});
  });
}

test('download permission failure is actionable and does not navigate away',async({page})=>{
  await fixture(page); await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(video)}`);
  await expect(page.getByRole('link',{name:'Download',exact:true})).toBeEnabled();
  await page.route(`${api}/object-url?**`,route=>route.fulfill({status:403,headers,json:{error:'Not permitted'}}));
  await page.getByRole('link',{name:'Download',exact:true}).click();
  await expect(page.locator('#asset-download-status')).toContainText('Download unavailable');
  await expect(page.locator('#preview-dialog')).toBeVisible();
  await expect(page.getByRole('link',{name:'Download',exact:true})).toBeEnabled();
});

for (const width of [1280,390]) test(`image previews keep technical generation metadata off the viewing surface at ${width}`, async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const key=prefix+'portrait-a/original/portrait.png';
  let generation={schemaVersion:1,method:'ai-assisted',provider:'OpenAI',inference:'remote',execution:'local',tool:'Codex CLI + Blender',cost:{status:'subscription'}};
  await page.route(`${api}/object-url?**`,route=>route.fulfill({headers,contentType:'application/json',body:JSON.stringify({key,size:100,contentType:'image/png',expiresIn:300,url:'https://audio.example/portrait.png',metadata:{extra:{generation}}})}));
  await page.route('https://audio.example/portrait.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6ZQAAAABJRU5ErkJggg==','base64')}));
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(key)}`);
  const details=page.locator('#asset-generation');
  await expect(page.locator('#preview-body img')).toBeVisible();const trigger=details.getByRole('button',{name:'Generation details',exact:true});await expect(trigger).toHaveAttribute('aria-expanded','false');await expect(details.getByText('Provider-hosted',{exact:true})).toBeHidden();await expect(page.locator('#preview-dialog').getByRole('heading',{name:'Versions',exact:true})).toHaveCount(0);
  const download=page.getByRole('link',{name:'Download',exact:true});await expect(download).toBeVisible();await expect(download).toHaveAttribute('download','portrait.png');
  const image=await page.locator('#preview-body img').boundingBox(),link=await download.boundingBox();expect(link.y).toBeGreaterThanOrEqual(image.y+image.height);expect(link.x+link.width).toBeLessThanOrEqual(width);expect(link.height).toBeLessThan(36);
  const close=page.getByRole('button',{name:'Close preview'});expect(await close.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await trigger.click();await expect(trigger).toHaveAttribute('aria-expanded','true');await expect(details.getByText('Provider-hosted',{exact:true})).toBeVisible();await trigger.click();await expect(details.getByText('Provider-hosted',{exact:true})).toBeHidden();
  await page.screenshot({path:test.info().outputPath(`clean-image-preview-${width}.png`)});

});

for(const width of [1280,390]) test(`audio, transcripts, lineage and readable mobile layout at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`${origin}/games/test-game/audio`);
  await expect(page.locator('.session-card')).toHaveCount(3);
  for (const name of ['Sessions','Video Episodes']) {
    const link=page.locator('#primary-nav').getByRole('link',{name,exact:true});
    const box=await link.boundingBox(); expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
  }
  await page.getByRole('link',{name:'Recording',exact:true}).click();
  await expect(page.locator('#preview-body')).not.toContainText('Recording status:');
  await expect(page.locator('#asset-links [data-connections="outputs"]')).toContainText('Original transcript');
  await expect(page.locator('audio')).toHaveAttribute('controls','');
  await expect(page.locator('#preview-body audio')).toBeVisible();
  await expect(page.getByRole('button',{name:/Jump to part/})).toHaveCount(0);
  const playerBox=await page.locator('audio').boundingBox();
  expect(playerBox.x).toBeGreaterThanOrEqual(0);
  expect(playerBox.x+playerBox.width).toBeLessThanOrEqual(width);
  expect(playerBox.y+playerBox.height).toBeLessThan(1000);
  const close=page.getByRole('button',{name:'Close preview'});
  const closeBox=await close.boundingBox();
  expect(closeBox.x+closeBox.width).toBeLessThanOrEqual(width);
  expect(await close.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await page.screenshot({path:test.info().outputPath(`audio-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:'Close preview'}).click();
  await page.locator('#primary-nav').getByRole('link',{name:'Sessions',exact:true}).click();
  await expect(page.locator('.session-card')).toHaveCount(3);
  await page.getByRole('link',{name:'raw-transcript',exact:true}).click();
  await expect(page.locator('.transcript-segment').first()).toContainText('0:00–0:02 · Alex');
  await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await expect(page.locator('.transcript-segment').last()).toContainText('Unassigned speaker');
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  await page.getByRole('button',{name:'Capture integrity and warnings',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Capture integrity and warnings',exact:true})).toContainText('Synthetic capture gap');
  await page.getByRole('dialog',{name:'Capture integrity and warnings',exact:true}).getByRole('button',{name:'Close',exact:true}).click();
  await page.locator('#asset-links [data-connections="outputs"]').getByRole('link',{name:'Corrected transcript · session-one',exact:true}).click();
  await expect(page.locator('.transcript-segment').first()).toContainText('The lantern.');
  await expect(page.getByRole('button',{name:'Transcript corrections, uncertainty and provenance',exact:true})).toBeVisible();
  await expect(page.locator('#asset-links [data-connections="outputs"]')).toContainText('Video');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`transcript-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:'Close preview'}).click();
  await selectGame(page,'other-game');
  await expect(page.locator('#library-status')).toContainText('No saved sessions yet');
  await expect(page.locator('#preview-body')).toBeEmpty();
  expect(errors).toEqual([]);
});

for(const width of [1280,390]) test(`videos are playable, linked and game scoped at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  await page.goto(`${origin}/games/test-game/videos`);
  await expect(page.locator('#library-title')).toHaveText('Video Episodes');
  await expect(page.locator('.session-card')).toHaveCount(0);
  // Generate synthetic footage inside the isolated test browser; no real game media in Git.
  const bytes=await page.evaluate(async()=>{
    const canvas=document.createElement('canvas'); canvas.width=160; canvas.height=90;
    const ctx=canvas.getContext('2d'),stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm'}),chunks=[];
    recorder.ondataavailable=e=>chunks.push(e.data);
    const stopped=new Promise(resolve=>recorder.onstop=resolve); recorder.start();
    for(let i=0;i<12;i++) { ctx.fillStyle=i%2?'#bca675':'#303840';ctx.fillRect(0,0,160,90); await new Promise(r=>setTimeout(r,100)); }
    recorder.stop(); await stopped; stream.getTracks().forEach(t=>t.stop());
    return Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()));
  });
  await page.route('https://audio.example/take.mp4',route=>route.fulfill({contentType:'video/webm',body:Buffer.from(bytes)}));
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(video)}`);await page.getByRole('button',{name:'Generation details',exact:true}).click();
  await expect(page.locator('#asset-generation')).toContainText('Kling 3 Pro');
  await expect(page.locator('#asset-generation')).toContainText('Provider-hosted');
  await expect(page.locator('#asset-generation')).toContainText('USD 1.344 · Billed');
  const player=page.locator('#preview-body video'); await expect(player).toHaveAttribute('controls','');
  await expect.poll(()=>player.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await player.evaluate(v=>v.play()); await expect.poll(()=>player.evaluate(v=>v.currentTime)).toBeGreaterThan(0);
  await expect(page.locator('#asset-links [data-connections="inputs"]')).toContainText('Corrected transcript');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`videos-${width}.png`),fullPage:true});
  await player.evaluate(v=>{window.previousVideo=v;});
  await page.keyboard.press('Escape'); expect(await page.evaluate(()=>window.previousVideo.paused)).toBe(true);
  await expect(page.locator('#asset-generation')).toBeEmpty();
  await page.reload(); await expect(page.locator('.session-card')).toHaveCount(0);
  await expect(page.locator('#preview-body video')).toBeVisible();
  await page.getByRole('button',{name:'Close preview',exact:true}).click();
  await selectGame(page,'other-game');
  await expect(page).toHaveURL(`${origin}/games/other-game/media`);await page.getByRole('link',{name:'Video Episodes',exact:true}).click();
  await expect(page.getByText('Create your first episode.',{exact:true})).toBeVisible();
});

test('deep-linked transcript survives reload and expired authentication clears content',async({page})=>{
  await fixture(page); await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(raw)}`);
  await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await page.reload(); await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await page.getByRole('button',{name:'Close preview'}).click();
  await page.locator('#primary-nav').getByRole('link',{name:'Sessions',exact:true}).click();
  await expect(page.locator('#session-library')).toBeVisible();
  await expect(page.locator('.session-card')).toHaveCount(3);
  await page.route(`${api}/assets*`,route=>route.fulfill({status:401,headers,json:{error:'Expired'}}));
  await page.route(`${origin}/auth/refresh`,route=>route.fulfill({status:401,json:{error:'Expired'}}));
  await page.reload();
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
  await expect(page.locator('#session-library')).not.toBeVisible();
  await expect(page.locator('#library-list')).toBeEmpty();
});

test('organized physical storage resolves to the unchanged transcript identity and finished connections',async({page})=>{
  await fixture(page);
  const physical='games/test-game/content/sessions/session-one/transcripts/raw/recording-a/raw.json';
  const requested=[];
  const oldPayloadRequests=[];
  page.on('request',r=>{if(r.url().startsWith('https://audio.example/games/test-game/assets/')) oldPayloadRequests.push(r.url());});
  page.on('request',r=>{if(r.url().startsWith(api+'/asset-document')) requested.push(new URL(r.url()).searchParams.get('key'));});
  await page.route(`${api}/object-url*`,route=>{
    if(new URL(route.request().url()).searchParams.get('key')!==physical) return route.fallback();
    return route.fulfill({headers,json:{...assets.find(a=>a.key===raw),storageKey:physical,
      url:`https://audio.example/${physical}`,expiresIn:300}});
  });
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(physical)}`);
  await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await expect(page.locator('#open-original')).toHaveCount(0);
  await expect(page.getByRole('link',{name:'Download',exact:true})).toHaveAttribute('href',`https://audio.example/${physical}`);
  await expect(page.locator('#asset-links [data-connections="outputs"]')).toContainText('Corrected transcript');
  expect(requested).toContain(raw); expect(requested).not.toContain(physical);
  await page.reload();
  await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await page.locator('#asset-links [data-connections="outputs"]').getByRole('link',{name:'Corrected transcript · session-one'}).click();
  await expect(page.locator('.transcript-segment').first()).toContainText('The lantern.');
  expect(oldPayloadRequests).toEqual([]);
});

test('catalog errors are recoverable without silently claiming empty results',async({page})=>{
  await fixture(page); let broken=true;
  await page.route(`${api}/assets*`,route=>broken?route.fulfill({status:503,headers,json:{error:'Storage unavailable'}}):route.fallback());
  await page.goto(`${origin}/games/test-game/transcripts`);
  await expect(page.locator('#library-status')).toContainText('Storage unavailable');
  broken=false; await page.reload();
  await expect(page.locator('.session-card')).toHaveCount(3);
});

test('one continuous MP3 track crosses part boundaries and seeks without changing files',async({page})=>{
  const requested=[];
  page.on('request',r=>{if(r.url().startsWith(api+'/object-url')) requested.push(new URL(r.url()).searchParams.get('key'));});
  await fixture(page); await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording',exact:true}).click();
  const audio=page.locator('audio');
  await expect.poll(()=>audio.evaluate(el=>el.readyState)).toBeGreaterThan(0);
  await expect.poll(()=>audio.evaluate(el=>el.duration)).toBeCloseTo(1.2,1);
  await audio.evaluate(el=>{el.currentTime=.6;});
  await expect.poll(()=>audio.evaluate(el=>el.currentTime)).toBeCloseTo(.6,1);
  await audio.evaluate(el=>{el.currentTime=0;});
  const src=await audio.getAttribute('src');
  await audio.evaluate(el=>el.play());
  await expect.poll(()=>audio.evaluate(el=>el.currentTime)).toBeGreaterThan(.65);
  await expect(audio).toHaveAttribute('src',src);
  expect(requested.filter(key=>key===continuous)).toHaveLength(1);
  expect(requested).not.toContain(part); expect(requested).not.toContain(part2);
  await expect(page.locator('#preview-body')).not.toContainText('No file switches');
  await page.evaluate(()=>{window.testAudio=document.querySelector('audio');});
  await page.keyboard.press('Escape');
  await expect(page.locator('#preview-dialog')).not.toBeVisible();
  expect(await page.evaluate(()=>window.testAudio.paused)).toBe(true);
});

test('unprepared or incomplete copies do not silently fall back to gapped part switching',async({page})=>{
  await fixture(page);
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets:assets.filter(a=>a.key!==continuous),cursor:null}}));
  await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording',exact:true}).click();
  await expect(page.locator('#preview-body')).toContainText('Playback is not ready yet');
  await expect(page.locator('#preview-body audio')).not.toBeVisible();
  await expect(page.locator('#asset-links')).toContainText('Original transcript');
});

test('continuous playback refreshes expired links without changing to a source chunk',async({page})=>{
  await fixture(page); let links=0;
  await page.route(`${api}/object-url*`,route=>{if(new URL(route.request().url()).searchParams.get('key')===continuous) links++; return route.fallback();});
  await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording',exact:true}).click();
  const audio=page.locator('#preview-body audio');
  await expect.poll(()=>audio.evaluate(a=>a.readyState)).toBeGreaterThan(0);
  await audio.evaluate(a=>{a.currentTime=.7;a.dispatchEvent(new Event('error'));});
  await expect(page.getByRole('button',{name:'Refresh playback link'})).toHaveCount(0);
  await expect.poll(()=>links).toBe(2);
  await expect.poll(()=>audio.evaluate(a=>a.currentTime)).toBeCloseTo(.7,1);
});

for (const width of [1280,390]) test(`finished connections hide workflow internals and retain useful links at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const middle=prefix+'work/original/correction.json', proof=prefix+'work/original/novel-proof.json';
  const shots=prefix+'work/original/video-shot-list.json', chapter=prefix+'chapter/original/novel-chapter.json';
  const extra=(key,kind,sourceKeys)=>({key,name:key.split('/').at(-1),kind,sourceKeys,contentType:'application/json',
    metadata:{title:kind,sessionId:'session-one'},lastModified:'2026-01-01T00:00:00Z'});
  const graph=assets.map(a=>a.key===corrected?{...a,sourceKeys:[middle]}:a.key===video?{...a,sourceKeys:[shots]}:a);
  graph.push(extra(middle,'correction',[raw]),extra(proof,'novel-proof',[corrected]),extra(shots,'video-shot-list',[corrected]),
    {...extra(chapter,'novel-chapter',[proof]),metadata:{title:'novel-chapter',sessionId:'session-one',extra:{jobId:'c'.repeat(64)}}},
    extra(chapter.replace('.json','.md'),'novel-chapter',[proof]));
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets:graph,cursor:null}}));
  await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording',exact:true}).click();
  const connections=page.locator('#asset-links [data-connections]');
  await expect(connections.getByRole('link')).toHaveText(['Original transcript · session-one']);
  await connections.getByRole('link',{name:'Original transcript · session-one'}).click();
  await expect(connections.getByRole('link')).toHaveText(['Audio · session-one','Corrected transcript · session-one']);
  await connections.getByRole('link',{name:'Corrected transcript · session-one'}).click();
  await expect(connections.getByRole('link')).toHaveText(['Original transcript · session-one','Novel chapter · session-one','Video · session-one']);
  await expect(connections.getByRole('link',{name:'Novel chapter · session-one'})).toHaveAttribute('href',`/games/test-game/novel/${'c'.repeat(64)}`);
  const connectionText=(await connections.allTextContents()).join('\n');
  for (const text of ['novel-proof','video-shot-list','correction.json','playback-v1','part-0000']) expect(connectionText).not.toContain(text);
  await page.screenshot({path:test.info().outputPath(`finished-connections-${width}.png`),fullPage:true});
  await connections.getByRole('link',{name:'Video · session-one'}).click();
  await expect(page.locator('#preview-body video')).toBeVisible();
  await expect(connections.getByRole('link')).toHaveText(['Corrected transcript · session-one']);
});

test('late catalog and document responses cannot populate a different game',async({page})=>{
  await fixture(page); let release, arrived;
  const waiting=new Promise(resolve=>{arrived=resolve;});
  await page.route(`${api}/assets*`,async route=>{
    if(new URL(route.request().url()).searchParams.get('gameId')!=='test-game') return route.fallback();
    arrived(); await new Promise(resolve=>{release=resolve;}); await route.fulfill({headers,json:{assets,cursor:null}});
  });
  await page.goto(`${origin}/games/test-game/audio`); await waiting;
  await selectGame(page,'other-game');
  await expect(page.locator('#library-status')).toContainText('No saved sessions yet'); release();
  await expect(page.locator('#library-list')).toBeEmpty();
});

// Exercise the visible Radix Select, including the portal and keyboard focus.
async function selectGame(page,id) {
  const name=await page.locator(`#game-selector option[value="${id}"]`).textContent();
  await page.getByRole('combobox',{name:'Current game'}).click();
  await page.getByRole('option',{name,exact:true}).click();
}


for(const width of [1280,390])test(`Sessions combines recordings and transcripts while legacy links preserve state at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});await fixture(page);const sections=[];page.on('request',request=>{const url=new URL(request.url());if(url.pathname==='/assets')sections.push(url.searchParams.get('section'));});
 await page.goto(`${origin}/games/test-game/audio?session=example#recording`);await expect(page).toHaveURL(`${origin}/games/test-game/sessions?session=example#recording`);
 const nav=page.locator('#primary-nav');await expect(nav.getByRole('link',{name:'Sessions',exact:true})).toHaveCount(1);await expect(nav.getByRole('link',{name:'Audio',exact:true})).toHaveCount(0);await expect(nav.getByRole('link',{name:'Transcripts',exact:true})).toHaveCount(0);
 await expect(page.locator('.session-group')).toHaveCount(1);await expect(page.locator('.session-card')).toHaveCount(3);await expect(page.getByRole('region',{name:'Live transcript',exact:true})).toBeHidden();
 expect(sections).toContain('sessions');await page.screenshot({path:testInfo.outputPath(`sessions-${width}.png`)});
 await page.goto(`${origin}/games/test-game/transcripts?session=example#text`);await expect(page).toHaveURL(`${origin}/games/test-game/sessions?session=example#text`);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [1280,390])test(`Videos search and compact creation action stay at the top at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);
 await page.route(`${api}/episodes*`,route=>route.fulfill({headers,json:{records:[{id:'crossing',name:'River crossing',description:'Lanterns on the river',revision:'a'.repeat(32),sceneIds:[]},{id:'city',name:'City arrival',description:'',revision:'b'.repeat(32),sceneIds:[]}],cursor:null}}));
 await page.goto(`${origin}/games/test-game/videos`);
 const search=page.getByLabel('Search episodes',{exact:true}),create=page.locator('#session-library > .explorer-heading').getByRole('button',{name:'Create Episode',exact:true});
 for(const control of [search,create]){await expect(control).toBeVisible();await expect(control).toBeInViewport();expect(await control.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);}
 const heading=await page.locator('#library-title').boundingBox(),action=await create.boundingBox(),box=await search.boundingBox();expect(action.x).toBeGreaterThan(heading.x+heading.width);expect(action.height).toBeLessThanOrEqual(48);expect(box.y).toBeLessThan((await page.locator('.episode-cards').boundingBox()).y);
 await search.fill('river');await expect(page.locator('.episode-card')).toHaveCount(1);await expect(page.locator('.episode-card')).toHaveAccessibleName('River crossing');await expect(page.locator('.episode-card strong')).toHaveText('River crossing');await expect(page.locator('.episode-card span')).toHaveText('0 scenes');
 await search.fill('unavailable phrase');await expect(page.locator('.episode-card')).toHaveCount(0);await search.fill('');await expect(page.locator('.episode-card')).toHaveCount(2);
 for(const name of ['Tags','Characters']){await expect(page.getByRole('combobox',{name,exact:true})).toBeVisible();await expect(page.getByRole('combobox',{name,exact:true})).toBeInViewport();}
 await expect(page.locator('#session-library details,#session-library summary')).toHaveCount(0);await expect(page.getByText('Relationship to the game',{exact:true})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:test.info().outputPath(`videos-top-toolbar-${width}.png`),fullPage:true});
 await page.locator('#primary-nav').getByRole('link',{name:'Sessions',exact:true}).click();await expect(page.getByRole('button',{name:'Create Episode',exact:true})).toBeHidden();await page.locator('#primary-nav').getByRole('link',{name:'Video Episodes',exact:true}).click();await expect(create).toBeVisible();await create.click();await expect(page.getByRole('form',{name:'Episode editor'})).toBeVisible();
});

async function addFilter(page,label,query){await page.getByRole('combobox',{name:label,exact:true}).click();const input=page.getByRole('combobox',{name:`Search ${label.toLowerCase()}`,exact:true});await input.fill(query);await expect(page.getByRole('listbox',{name:`${label} suggestions`})).toBeVisible();await input.press('Enter');await page.keyboard.press('Escape');}
async function clearFilters(page,label){const buttons=page.getByRole('button',{name:new RegExp(`^Remove .* from ${label}$`)});while(await buttons.count())await buttons.first().click();}

for(const width of [1280,390])test(`Multiple tags and characters add with Enter and filter together at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);
 await page.route(`${api}/game?**`,route=>route.fulfill({headers,json:{game:{id:'test-game',name:'Test Game'},players:[],memberships:[],characters:[{id:'ronin',name:'Ronin'},{id:'maximus',name:'Maximus'}]}}));
 const clip=(id,title,characterIds,tags)=>({key:`${prefix}${id}/original/take.mp4`,name:'take.mp4',kind:'video',contentType:'video/mp4',size:20,lastModified:'2026-01-01T12:00:00Z',metadata:{title,characterIds,tags}});
 const videos=[clip('duo','Both heroes',['ronin','maximus'],['battle','canonical']),clip('ronin','Ronin alone',['ronin'],['battle']),clip('maximus','Maximus alone',['maximus'],['canonical'])];
 await page.route(`${api}/assets?**`,route=>route.fulfill({headers,json:{assets:videos,cursor:null}}));await page.route(`${api}/episodes*`,route=>route.fulfill({headers,json:{records:videos.map((asset,index)=>({id:['duo','ronin','maximus'][index],name:asset.metadata.title,description:'',revision:'a'.repeat(32),sceneIds:[],characterIds:asset.metadata.characterIds,tags:asset.metadata.tags})),cursor:null}}));
 await page.goto(`${origin}/games/test-game/videos`);const cards=page.locator('.episode-card');await expect(cards).toHaveCount(3);
 await addFilter(page,'Characters','ro');await expect(cards).toHaveCount(2);await addFilter(page,'Characters','max');await expect(cards).toHaveCount(1);await expect(cards).toContainText('Both heroes');
 await addFilter(page,'Tags','bat');await addFilter(page,'Tags','can');await expect(cards).toHaveCount(1);await expect(page.getByRole('button',{name:'Remove canonical from tags'})).toBeVisible();
 await page.getByRole('button',{name:'Remove Ronin from characters'}).click();await clearFilters(page,'tags');await expect(cards).toHaveCount(2);
 await expect(page.getByRole('button',{name:'Create collection',exact:true})).toHaveCount(0);await expect(page.getByText('Finished videos',{exact:true})).toHaveCount(0);await expect(page.getByText('No episodes yet.',{exact:true})).toHaveCount(0);await expect(page.getByText('No videos yet.',{exact:true})).toHaveCount(0);
 await page.screenshot({path:test.info().outputPath(`video-multiselect-${width}.png`),fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('combobox',{name:'Characters',exact:true}).click();await page.getByRole('combobox',{name:'Search characters',exact:true}).fill('ro');await expect(page.getByRole('listbox',{name:'Characters suggestions'})).toBeVisible();await page.locator('#primary-nav').getByRole('link',{name:'Novel',exact:true}).click();await expect(page.getByRole('listbox',{name:'Characters suggestions'})).toHaveCount(0);
});

for(const width of [1280,390])test(`Empty Videos has one helpful empty state at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);await page.route(`${api}/assets?**`,route=>route.fulfill({headers,json:{assets:[],cursor:null}}));await page.route(`${api}/episodes*`,route=>route.fulfill({headers,json:{records:[],cursor:null}}));
 await page.goto(`${origin}/games/test-game/videos`);await expect(page.getByText('Create your first episode.',{exact:true})).toBeVisible();await expect(page.getByText('No videos yet.',{exact:true})).toHaveCount(0);await expect(page.getByText('No episodes yet.',{exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Create collection',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Finished videos',exact:true})).toHaveCount(0);
 await page.locator('#primary-nav').getByRole('link',{name:'Sessions',exact:true}).click();await expect(page.getByRole('button',{name:'Create Episode',exact:true})).toHaveCount(0);
});

for(const width of [1280,390]) test(`recording result suppresses contradictory empty session message at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);
 await page.route(`${api}/browser-recording/capabilities`,route=>route.fulfill({headers,json:{canRecord:true,transcriptionAvailable:false}}));
 let release;const pending=new Promise(resolve=>{release=resolve;});
 await page.route(`${api}/assets?*`,async route=>{await pending;await route.fulfill({headers,json:{assets:[],cursor:null}});});
 await page.goto(`${origin}/games/test-game/sessions`);
 await expect(page.locator('#library-status .loading-state')).toBeVisible();
 await page.evaluate(()=>{const result=document.getElementById('room-result');result.hidden=false;document.getElementById('room-result-name').textContent='Session · Oct 2, 2026, 11:28 PM';});
 release();await expect(page.locator('#library-status .loading-state')).toHaveCount(0);
 await expect(page.locator('#room-result')).toBeVisible();await expect(page.locator('#library-status')).not.toBeVisible();
});
