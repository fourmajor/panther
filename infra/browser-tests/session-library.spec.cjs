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

async function fixture(page) {
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'stu'}))+'.test'})));
  await page.route(`${origin}/**`,route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:`window.PANTHER_CONFIG={apiUrl:'${api}',clientId:'test',cognitoDomain:'https://test.amazoncognito.com',redirectUri:'${origin}/'};`});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css'].includes(pathname)?pathname.slice(1):'index.html');
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
    if(u.pathname==='/assets') body=game==='test-game'?{assets:u.searchParams.get('cursor')?assets.slice(3):assets.slice(0,3),cursor:u.searchParams.get('cursor')?null:'next'}:{assets:[],cursor:null};
    if(u.pathname==='/objects') body={prefixes:[],objects:[],nextCursor:null};
    if(u.pathname==='/object-url') body={...assets.find(a=>a.key===key),url:`https://audio.example/${key.split('/').at(-1)}`,expiresIn:300};
    if(u.pathname==='/asset-document') {
      const transcript={entityType:'PlayerTranscript',players:[{id:'alex',name:'Alex'}],captureIntegrity:{warnings:['Synthetic capture gap']},segments:[{start:0,end:2,playerId:'alex',text:key===raw?'The lanturn.':'The lantern.',originalText:'The lanturn.',uncertainty:'Test spelling'}, {start:2,end:4,playerId:null,text:'<script>window.attacked=true</script> Pizza?'}]};
      body={...assets.find(a=>a.key===key),document:key===recording?{entityType:'Recording',status:'interrupted',parts:[{file:'part-0000.flac',start:0},{file:'part-0001.flac',start:.6}]}:key===raw?transcript:{stage:'corrected-transcript',reviewStatus:'ai-reviewed-unverified',payload:{transcript,review:{passed:true}}}};
    }
    return route.fulfill({json:body,headers});
  });
}

for(const width of [1280,390]) test(`audio, transcripts, lineage and readable mobile layout at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`${origin}/games/test-game/audio`);
  await expect(page.locator('.session-card')).toHaveCount(1);
  for (const name of ['Audio','Transcripts','Videos']) {
    const link=page.locator('#primary-nav').getByRole('link',{name,exact:true});
    const box=await link.boundingBox(); expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
  }
  await page.getByRole('link',{name:'Recording · session-one',exact:true}).click();
  await expect(page.locator('#preview-body')).toContainText('Recording status: interrupted');
  await expect(page.locator('#asset-links')).toContainText('raw-transcript');
  await expect(page.locator('audio')).toHaveAttribute('controls','');
  await expect(page.locator('#preview-body [role="status"]')).toContainText('Continuous playback');
  await expect(page.getByRole('button',{name:'Jump to part 2',exact:false})).toBeEnabled();
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
  await page.locator('#primary-nav').getByRole('link',{name:'Transcripts',exact:true}).click();
  await expect(page.locator('.session-card')).toHaveCount(2);
  await page.getByRole('link',{name:'raw-transcript',exact:true}).click();
  await expect(page.locator('.transcript-segment').first()).toContainText('0:00–0:02 · Alex');
  await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await expect(page.locator('.transcript-segment').last()).toContainText('Unassigned speaker');
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  await page.getByText('Capture integrity and warnings',{exact:true}).click();
  await expect(page.locator('#preview-body')).toContainText('Synthetic capture gap');
  await page.locator('#asset-links').getByRole('link',{name:'corrected-transcript',exact:true}).click();
  await expect(page.locator('.transcript-segment').first()).toContainText('The lantern.');
  await expect(page.getByText('Transcript corrections, uncertainty and provenance',{exact:true})).toBeVisible();
  await expect(page.locator('#asset-links')).toContainText('video-comparison');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`transcript-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:'Close preview'}).click();
  await page.getByRole('combobox',{name:'Game'}).selectOption('other-game');
  await expect(page.locator('#library-status')).toContainText('No transcripts yet');
  await expect(page.locator('#preview-body')).toBeEmpty();
  expect(errors).toEqual([]);
});

for(const width of [1280,390]) test(`videos are playable, linked and game scoped at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  await page.goto(`${origin}/games/test-game/videos`);
  await expect(page.locator('#library-title')).toHaveText('Videos');
  await expect(page.locator('.session-card')).toHaveCount(1);
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
  const link=page.locator('#library-list').getByRole('link',{name:'video-comparison',exact:true});
  await expect(link).toBeVisible();
  const box=await link.boundingBox(); expect(box.x+box.width).toBeLessThanOrEqual(width);
  expect(await link.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await link.click();
  const player=page.locator('#preview-body video'); await expect(player).toHaveAttribute('controls','');
  await expect.poll(()=>player.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await player.evaluate(v=>v.play()); await expect.poll(()=>player.evaluate(v=>v.currentTime)).toBeGreaterThan(0);
  await expect(page.locator('#asset-links')).toContainText('corrected-transcript');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`videos-${width}.png`),fullPage:true});
  await player.evaluate(v=>{window.previousVideo=v;});
  await page.keyboard.press('Escape'); expect(await page.evaluate(()=>window.previousVideo.paused)).toBe(true);
  await page.reload(); await expect(page.locator('.session-card')).toHaveCount(1);
  await page.getByRole('combobox',{name:'Game'}).selectOption('other-game');
  await expect(page).toHaveURL(`${origin}/games/other-game/videos`);
  await expect(page.locator('#library-status')).toContainText('No videos yet');
});

test('deep-linked transcript survives reload and expired authentication clears content',async({page})=>{
  await fixture(page); await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(raw)}`);
  await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await page.reload(); await expect(page.locator('.transcript-segment').first()).toContainText('The lanturn.');
  await page.getByRole('button',{name:'Close preview'}).click();
  await page.locator('#primary-nav').getByRole('link',{name:'Audio',exact:true}).click();
  await page.route(`${api}/assets*`,route=>route.fulfill({status:401,headers,json:{error:'Expired'}}));
  await page.route(`${origin}/auth/refresh`,route=>route.fulfill({status:401,json:{error:'Expired'}}));
  await page.locator('#library-refresh').click();
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
  await expect(page.locator('#session-library')).not.toBeVisible();
  await expect(page.locator('#library-list')).toBeEmpty();
});

test('catalog errors are recoverable without silently claiming empty results',async({page})=>{
  await fixture(page); let broken=true;
  await page.route(`${api}/assets*`,route=>broken?route.fulfill({status:503,headers,json:{error:'Storage unavailable'}}):route.fallback());
  await page.goto(`${origin}/games/test-game/transcripts`);
  await expect(page.locator('#library-status')).toContainText('Storage unavailable');
  broken=false; await page.locator('#library-refresh').click();
  await expect(page.locator('.session-card')).toHaveCount(2);
});

test('one continuous MP3 track crosses part boundaries and seeks without changing files',async({page})=>{
  const requested=[];
  page.on('request',r=>{if(r.url().startsWith(api+'/object-url')) requested.push(new URL(r.url()).searchParams.get('key'));});
  await fixture(page); await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording · session-one',exact:true}).click();
  const audio=page.locator('audio');
  await expect.poll(()=>audio.evaluate(el=>el.readyState)).toBeGreaterThan(0);
  await expect.poll(()=>audio.evaluate(el=>el.duration)).toBeCloseTo(1.2,1);
  await page.getByRole('button',{name:'Jump to part 2',exact:false}).click();
  await expect.poll(()=>audio.evaluate(el=>el.currentTime)).toBeCloseTo(.6,1);
  await page.getByRole('button',{name:'Jump to part 1',exact:false}).click();
  const src=await audio.getAttribute('src');
  await audio.evaluate(el=>el.play());
  await expect.poll(()=>audio.evaluate(el=>el.currentTime)).toBeGreaterThan(.65);
  await expect(audio).toHaveAttribute('src',src);
  expect(requested.filter(key=>key===continuous)).toHaveLength(1);
  expect(requested).not.toContain(part); expect(requested).not.toContain(part2);
  await expect(page.locator('#preview-body [role="status"]')).toContainText('Continuous playback');
  await page.evaluate(()=>{window.testAudio=document.querySelector('audio');});
  await page.keyboard.press('Escape');
  await expect(page.locator('#preview-dialog')).not.toBeVisible();
  expect(await page.evaluate(()=>window.testAudio.paused)).toBe(true);
});

test('unprepared or incomplete copies do not silently fall back to gapped part switching',async({page})=>{
  await fixture(page);
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets:assets.filter(a=>a.key!==continuous),cursor:null}}));
  await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording · session-one',exact:true}).click();
  await expect(page.locator('#preview-body')).toContainText('Continuous playback has not been prepared');
  await expect(page.locator('#preview-body audio')).not.toBeVisible();
  await expect(page.locator('#asset-links')).toContainText('recording');
});

test('continuous playback refreshes expired links without changing to a source chunk',async({page})=>{
  await fixture(page); let links=0;
  await page.route(`${api}/object-url*`,route=>{if(new URL(route.request().url()).searchParams.get('key')===continuous) links++; return route.fallback();});
  await page.goto(`${origin}/games/test-game/audio`);
  await page.getByRole('link',{name:'Recording · session-one',exact:true}).click();
  const audio=page.locator('#preview-body audio');
  await expect.poll(()=>audio.evaluate(a=>a.readyState)).toBeGreaterThan(0);
  await audio.evaluate(a=>{a.currentTime=.7;a.dispatchEvent(new Event('error'));});
  await page.getByRole('button',{name:'Refresh playback link'}).click();
  await expect.poll(()=>links).toBe(2);
  await expect.poll(()=>audio.evaluate(a=>a.currentTime)).toBeCloseTo(.7,1);
});

test('late catalog and document responses cannot populate a different game',async({page})=>{
  await fixture(page); let release, arrived;
  const waiting=new Promise(resolve=>{arrived=resolve;});
  await page.route(`${api}/assets*`,async route=>{
    if(new URL(route.request().url()).searchParams.get('gameId')!=='test-game') return route.fallback();
    arrived(); await new Promise(resolve=>{release=resolve;}); await route.fulfill({headers,json:{assets,cursor:null}});
  });
  await page.goto(`${origin}/games/test-game/audio`); await waiting;
  await page.getByRole('combobox',{name:'Game'}).selectOption('other-game');
  await expect(page.locator('#library-status')).toContainText('No recordings yet'); release();
  await expect(page.locator('#library-list')).toBeEmpty();
});
