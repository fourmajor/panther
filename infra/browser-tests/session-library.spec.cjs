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
    if(u.pathname==='/assets') body=game==='test-game'?{assets,cursor:null}:{assets:[],cursor:null};
    if(u.pathname==='/objects') body={prefixes:[],objects:[],nextCursor:null};
    if(u.pathname==='/object-url') body={...assets.find(a=>a.key===key),url:`https://audio.example/${key.split('/').at(-1)}`,expiresIn:300};
    if(u.pathname==='/asset-document') {
      const transcript={entityType:'PlayerTranscript',players:[{id:'alex',name:'Alex'}],captureIntegrity:{warnings:['Synthetic capture gap']},segments:[{start:0,end:2,playerId:'alex',text:key===raw?'The lanturn.':'The lantern.',originalText:'The lanturn.',uncertainty:'Test spelling'}, {start:2,end:4,playerId:null,text:'<script>window.attacked=true</script> Pizza?'}]};
      body={...assets.find(a=>a.key===key),document:key===recording?{entityType:'Recording',status:'interrupted',parts:[{file:'part-0000.flac',start:0},{file:'part-0001.flac',start:.6}]}:key===raw?transcript:{stage:'corrected-transcript',reviewStatus:'ai-reviewed-unverified',payload:{transcript,review:{passed:true}}}};
    }
    return route.fulfill({json:body,headers});
  });
}

for(const width of [1280,390]) test(`playful video filters, ordered collections and captions at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000});await fixture(page);
  const second=prefix+'second-video/original/take.webm',poster=prefix+'poster-a/original/frame.svg';
  const caption=video.slice(0,video.lastIndexOf('/')+1)+'captions.vtt';
  const clip=(key,title,category,tags)=>({key,name:key.split('/').at(-1),kind:'silly-video',contentType:'video/webm',size:100,lastModified:'2026-01-01T12:00:00Z',sourceKeys:[],metadata:{title,description:'Synthetic test clip',category,tags,characterIds:['hero'],extra:{creator:'Example Artist',preview:{schemaVersion:1,imageKey:poster}}}});
  const videos=[clip(video,'Practice joke','playful-derivative',['table-joke']),clip(second,'Scene test','creative-reimagining',['experiment'])];
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
  const cards=page.locator('.video-card');await expect(cards).toHaveCount(2);
  await expect(cards.first().locator('img')).toBeVisible();expect(galleryRequests).toBe(1);
  await page.getByLabel('Relationship to the game').selectOption('playful-derivative');await expect(cards).toHaveCount(1);
  await expect(cards.first()).toHaveClass(/playful-video/);
  await page.getByLabel('Search loaded videos').fill('practice');await expect(cards).toHaveCount(1);
  await page.getByLabel('Search loaded videos').fill('missing');await expect(cards).toHaveCount(0);
  await page.getByLabel('Search loaded videos').fill('');await page.getByLabel('Relationship to the game').selectOption('all');
  await page.getByLabel('Tag',{exact:true}).selectOption('experiment');await expect(cards).toHaveCount(1);
  await page.getByLabel('Tag',{exact:true}).selectOption('');
  expect(galleryRequests).toBe(1); // Filtering does not re-sign every thumbnail.
  await page.getByLabel('Ordered collection').selectOption('favorites');
  await expect(cards.first()).toContainText('Scene test');await expect(cards).toHaveCount(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`video-collections-${width}.png`),fullPage:true});
  await cards.first().getByRole('link',{name:'Scene test',exact:true}).click();
  const body=page.locator('#preview-body');await expect(body).toContainText('1 of 2 available videos');
  await expect(body.getByRole('button',{name:'Previous collection video'})).toBeDisabled();
  await body.getByRole('button',{name:'Next collection video'}).click();
  await expect(page.locator('#preview-title')).toHaveText('Practice joke');
  await body.getByText('Caption tracks',{exact:true}).click();
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

test('unavailable collection never substitutes library videos',async({page})=>{
  await fixture(page);
  await page.route(`${api}/video-collections?**`,route=>new URL(route.request().url()).searchParams.get('id')
    ?route.fulfill({status:503,headers,json:{error:'Try later'}}):route.fulfill({headers,json:{collections:[{id:'favorites',name:'Favorites',assetKeys:[video]}],cursor:null}}));
  await page.goto(`${origin}/games/test-game/videos`);
  await page.getByLabel('Ordered collection').selectOption('favorites');
  await expect(page.locator('#library-list')).toContainText('Collection not loaded; no partial playlist');
  await expect(page.locator('.video-card')).toHaveCount(0);
  await page.getByLabel('Ordered collection').selectOption('');await expect(page.locator('.video-card')).toHaveCount(1);
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
  const body=page.locator('#preview-body');
  await expect(body).toContainText('No canonical reading version has been designated');
  await expect(body.locator('.transcript-segment')).toHaveCount(2);
  const search=body.getByLabel('Search speech or player names');
  await search.fill('Pizza'); await search.press('Enter');
  await expect(body).toContainText('Match 1 of 1');
  await expect(body.locator('.transcript-current-match')).toContainText('Pizza?');
  await expect(body.locator('.transcript-segment')).toHaveCount(2);
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  await body.getByText('Source recording · listen at a transcript timestamp',{exact:true}).click();
  await expect(body.locator('audio')).toBeVisible();
  await expect(body.locator('.transcript-seek').first()).toBeEnabled();
  await body.locator('.transcript-seek').first().click();
  await expect.poll(()=>body.locator('audio').evaluate(a=>a.paused)).toBe(false);
  await body.getByText('Choose this canonical reading version',{exact:true}).click();
  await body.getByLabel('Selection reason').fill('Prefer original evidence for this test');
  await body.getByRole('checkbox').check();
  await body.getByRole('button',{name:'Use this version as canonical'}).click();
  await expect(body).toContainText('Selection saved. Immutable transcripts and review state are unchanged');
  await expect(body).toContainText('Viewing the canonical reading version');
  expect(submitted.reason).toBe('Prefer original evidence for this test');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`transcript-reader-${width}.png`)});
  await body.getByLabel('Session transcript version').selectOption(corrected);
  await expect(body).toContainText('The lantern.');
  await expect(body).toContainText('Viewing a non-canonical version');
  await expect(body.getByRole('link',{name:'Open canonical reading version'})).toBeVisible();
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
  await body.getByText('Choose this canonical reading version',{exact:true}).click();
  await body.getByLabel('Selection reason').fill('Reading preference');
  await body.getByRole('checkbox').check();
  const save=body.getByRole('button',{name:'Use this version as canonical'});
  await save.click(); await expect(body).toContainText('Selection not confirmed');
  await save.click(); await expect.poll(()=>attempts.length).toBe(2);
  expect(attempts[1]).toEqual(attempts[0]);
  await expect(body).not.toContainText('Selection saved');
});

for (const width of [1280,390]) test(`loading feedback reports real catalog progress at ${width}`, async ({page}) => {
  await page.setViewportSize({width,height:900});
  await fixture(page);
  let releaseFirst, releaseSecond;
  const first = new Promise(resolve => { releaseFirst=resolve; });
  const second = new Promise(resolve => { releaseSecond=resolve; });
  let catalogRequests=0;
  await page.route(`${api}/assets?**`, async route => {
    catalogRequests++;
    const u=new URL(route.request().url());
    expect(u.searchParams.get('section')).toBe('videos');
    await (u.searchParams.get('cursor') ? second : first);
    await route.fulfill({headers,json:{assets:[assets.find(a=>a.key===video)],cursor:u.searchParams.get('cursor')?null:'next'}});
  });
  await page.clock.install();
  await page.goto(`${origin}/games/test-game/videos`);
  const status=page.locator('#library-status');
  await expect(status).toContainText('Fetching videos from the catalog');
  await expect(status.locator('.loading-spinner')).toBeVisible();
  expect(await status.locator('.loading-spinner').evaluate(el=>getComputedStyle(el).animationName)).toBe('panther-loading');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.clock.fastForward(16000);
  await expect(status).toContainText('Taking longer than usual');
  await expect(status).not.toContainText('%');
  await page.screenshot({path:test.info().outputPath(`loading-${width}.png`),fullPage:true});
  releaseFirst();
  await expect(page.locator('.session-card')).toHaveCount(1);
  const more=page.getByRole('button',{name:'Load more videos'});
  await expect(more).toBeVisible();
  await expect(status.locator('.loading-state')).toHaveCount(0);
  expect(catalogRequests).toBe(1);
  await page.screenshot({path:test.info().outputPath(`catalog-first-page-${width}.png`),fullPage:true});
  await more.click();
  await expect(page.locator('.session-card')).toHaveCount(1);
  await page.emulateMedia({reducedMotion:'reduce'});
  expect(await status.locator('.loading-spinner').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  releaseSecond();
  await expect(status).toContainText('Episodes, experiments');
  await expect(status.locator('.loading-state')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Load more videos'})).toHaveCount(0);
  await expect(page.locator('.session-card')).toHaveCount(1);
});

test('an asset preview links its immutable earlier and later versions', async ({page}) => {
  await fixture(page);
  const earlier = prefix + 'video-earlier/original/take.mp4';
  const series = 'synthetic-film-series';
  const pair = [
    {...assets.find(asset => asset.key === video), metadata: {title:'Newer cut', extra:{version:{schemaVersion:1,seriesId:series,number:2,previousKey:earlier}}}},
    {key:earlier, name:'take.mp4', kind:'video-comparison', contentType:'video/mp4', size:100,
      lastModified:'2025-12-31T12:00:00Z', sourceKeys:[], metadata:{title:'Earlier cut', extra:{version:{schemaVersion:1,seriesId:series,number:1}}}},
  ];
  await page.route(`${api}/assets?**`, route => route.fulfill({headers,json:{assets:pair,cursor:null}}));
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(video)}`);
  const history = page.locator('#asset-versions');
  await expect(history.getByRole('link',{name:'Version 1 · Earlier cut'})).toBeVisible();
  await expect(history.getByRole('link',{name:'Version 2 · Newer cut'})).toBeVisible();
  await history.getByRole('link',{name:'Version 1 · Earlier cut'}).click();
  await expect(page.locator('#preview-title')).toHaveText('Version 1 · Earlier cut');
});

test('failed catalog removes activity and offers recovery', async ({page}) => {
  await fixture(page);
  await page.route(`${api}/assets?**`,route=>route.fulfill({status:503,json:{error:'Temporarily unavailable'},headers}));
  await page.goto(`${origin}/games/test-game/videos`);
  await expect(page.locator('#library-status')).toContainText('Use Refresh to retry');
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
    const button=page.getByRole('button',{name:'Download original',exact:true});
    await expect(button).toBeEnabled();
    await page.locator('#preview-dialog').evaluate(el=>el.scrollTop=el.scrollHeight);
    await expect(button).toBeInViewport();
    await expect(page.getByRole('link',{name:'Open original',exact:true})).toBeInViewport();
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
  await expect(page.getByRole('button',{name:'Download original',exact:true})).toBeEnabled();
  await page.route(`${api}/object-url?**`,route=>route.fulfill({status:403,headers,json:{error:'Not permitted'}}));
  await page.getByRole('button',{name:'Download original',exact:true}).click();
  await expect(page.locator('#asset-download-status')).toContainText('Download unavailable');
  await expect(page.locator('#preview-dialog')).toBeVisible();
  await expect(page.getByRole('button',{name:'Download original',exact:true})).toBeEnabled();
});

for (const width of [1280,390]) test(`image creation metadata distinguishes costs and inference at ${width}`, async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const key=prefix+'portrait-a/original/portrait.png';
  let generation={schemaVersion:1,method:'ai-assisted',provider:'OpenAI',inference:'remote',execution:'local',tool:'Codex CLI + Blender',cost:{status:'subscription'}};
  await page.route(`${api}/object-url?**`,route=>route.fulfill({headers,contentType:'application/json',body:JSON.stringify({key,size:100,contentType:'image/png',expiresIn:300,url:'https://audio.example/portrait.png',metadata:{extra:{generation}}})}));
  await page.route('https://audio.example/portrait.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6ZQAAAABJRU5ErkJggg==','base64')}));
  await page.goto(`${origin}/games/test-game/media?asset=${encodeURIComponent(key)}`);
  const details=page.locator('#asset-generation');
  await expect(details).toContainText('Unknown / not recorded');
  await expect(details).toContainText('Provider-hosted');
  await expect(details).toContainText('Local computer');
  await expect(details).toContainText('Subscription-covered');
  await expect(details).not.toContainText('USD 0');
  // Scroll the scrollable dialog as a person would; the sticky close control stays usable.
  await page.locator('#preview-dialog').evaluate(el=>el.scrollTop=el.scrollHeight);
  const box=await details.boundingBox(); expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
  const close=page.getByRole('button',{name:'Close preview'});
  expect(await close.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await page.screenshot({path:test.info().outputPath(`generation-${width}.png`),fullPage:true});
  for (const [cost,text] of [[{status:'unknown'},'Unknown / not reconciled'],[{status:'not-applicable'},'No metered generation charge'],[{status:'estimated',amount:'2.4318',currency:'USD'},'USD 2.4318 · Estimate, not a charge'],[{status:'billed',amount:'0',currency:'USD'},'USD 0 · Billed']]) {
    generation={schemaVersion:1,method:'ai',model:'<img src=x onerror=window.attacked=true>',cost,evidence:'Synthetic evidence'};
    await page.reload(); await expect(details).toContainText(text);
    await expect(details.locator('img')).toHaveCount(0);
    expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  }
});

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
  await expect(page.locator('#asset-links [data-connections="outputs"]')).toContainText('Original transcript');
  await expect(page.locator('audio')).toHaveAttribute('controls','');
  await expect(page.locator('#preview-body p[role="status"]', {hasText:'Continuous playback'})).toBeVisible();
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
  await page.locator('#asset-links [data-connections="outputs"]').getByRole('link',{name:'Corrected transcript · session-one',exact:true}).click();
  await expect(page.locator('.transcript-segment').first()).toContainText('The lantern.');
  await expect(page.getByText('Transcript corrections, uncertainty and provenance',{exact:true})).toBeVisible();
  await expect(page.locator('#asset-links [data-connections="outputs"]')).toContainText('Video');
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
  // New library filters/posters extend the page. Test normal document scrolling,
  // then retain the hit-test so clipping/overlays cannot be hidden by click automation.
  await link.scrollIntoViewIfNeeded();await expect(link).toBeInViewport();
  const box=await link.boundingBox(); expect(box.x+box.width).toBeLessThanOrEqual(width);
  expect(await link.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await link.click();
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
  await expect(page.locator('#open-original')).toHaveAttribute('href',`https://audio.example/${physical}`);
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
  await page.getByRole('link',{name:'Recording · session-one',exact:true}).click();
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
  await page.getByRole('combobox',{name:'Game'}).selectOption('other-game');
  await expect(page.locator('#library-status')).toContainText('No recordings yet'); release();
  await expect(page.locator('#library-list')).toBeEmpty();
});
