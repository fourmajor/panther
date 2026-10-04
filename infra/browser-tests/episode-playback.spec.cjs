const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const jwt='test.'+Buffer.from(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-editor'})).toString('base64url')+'.test';
const key=id=>`games/test-game/assets/${id}/original/take.webm`;
async function fixture(page,context,{failSecond=false,uncertainSelection=false,development=false}={}){
 let episode={schemaVersion:1,entityType:'Episode',gameId:'test-game',id:'arrival',name:'Arrival',description:'',revision:'a'.repeat(32),sceneIds:['gate','river']};
 const scenes=['gate','river'].map((id,index)=>({schemaVersion:1,entityType:'Scene',gameId:'test-game',id,episodeId:'arrival',name:index?'River crossing':'City gate',description:'',type:'travel',revision:(index?'c':'b').repeat(32),position:index,selectedOutputKey:null,selectedOutputSceneRevision:null}));
 const videos=scenes.map(scene=>({key:key(scene.id),kind:'video',name:scene.id+'.webm',contentType:'video/webm',size:100,lastModified:'2026-10-01T00:00:00Z',metadata:{title:scene.name+' take',extra:{relationshipRole:'finished',sceneRef:{episodeId:'arrival',sceneId:scene.id,revision:scene.revision}}}}));
 videos.push({...videos[0],key:key('gate-alt'),name:'gate-alt.webm',metadata:{...videos[0].metadata,title:'City gate second take'}});
 const changes=[],requests=[];let selectionFailed=false;
 await context.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
  const req=route.request(),url=new URL(req.url()),respond=json=>route.fulfill({json,headers:{'access-control-allow-origin':'https://panther.place'}});requests.push(url.pathname);
  if(url.pathname==='/episodes'){if(req.method()==='POST'){const body=req.postDataJSON();changes.push(body);episode={...episode,...body,revision:'d'.repeat(32)};return respond({record:episode});}return respond(url.searchParams.has('id')?{record:episode}:{records:[episode],cursor:null});}
  if(url.pathname==='/scenes'){if(req.method()==='POST'){const body=req.postDataJSON();changes.push(body);const index=scenes.findIndex(s=>s.id===body.id);scenes[index]={...scenes[index],...body,revision:(index?'e':'f').repeat(32),selectedOutputSceneRevision:videos[index].metadata.extra.sceneRef.revision};if(uncertainSelection&&!selectionFailed){selectionFailed=true;return route.abort('failed');}return respond({record:scenes[index]});}return respond(url.searchParams.has('id')?{record:scenes.find(s=>s.id===url.searchParams.get('id'))}:{records:scenes,cursor:null});}
  if(url.pathname==='/episode-composition')return respond({episode,ready:scenes.every(s=>s.selectedOutputKey),compositionHash:'test-hash',scenes:episode.sceneIds.map(id=>({scene:scenes.find(s=>s.id===id),assetKey:scenes.find(s=>s.id===id).selectedOutputKey}))});
  if(url.pathname==='/assets')return respond({assets:videos,cursor:null});
  if(url.pathname==='/object-url')return respond({url:`https://audio.example/${url.searchParams.get('key').includes('/river/')?'river':url.searchParams.get('key').includes('/gate-alt/')?'gate-alt':'gate'}.webm`,contentType:'video/webm'});
  if(url.pathname==='/video-collections')return respond({collections:[],cursor:null});
  if(url.pathname==='/editorial-jobs')return respond({jobs:[],cursor:null});
  return respond({games:[{id:'test-game',name:'Test Game'}],game:{id:'test-game',name:'Test Game'},players:[],memberships:[],characters:[],chapters:[],assets:[],objects:[],prefixes:[],cursor:null});
 });
 await context.route('https://panther.place/**',route=>{
  const pathname=new URL(route.request().url()).pathname;
  if(pathname.startsWith('/auth/'))return route.fulfill({json:{id_token:jwt,expires_in:3600}});
  if(pathname==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/",development:'+JSON.stringify(development)+'};'});
  if(pathname==='/vendor/model-viewer.min.js')return route.fulfill({contentType:'application/javascript',body:''});
  const root=path.resolve(__dirname,'../../web/media-explorer');let source=path.resolve(root,'.'+pathname);if(!source.startsWith(root+path.sep)||!fs.existsSync(source)||!fs.statSync(source).isFile())source=path.join(root,'index.html');
  return route.fulfill({body:fs.readFileSync(source),contentType:source.endsWith('.js')?'application/javascript':source.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('https://panther.place/games/test-game/episodes');
 // Two-second synthetic video captured entirely inside the isolated test browser.
 const bytes=await page.evaluate(async()=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];recorder.ondataavailable=e=>parts.push(e.data);const done=new Promise(resolve=>recorder.onstop=resolve);recorder.start();for(let i=0;i<20;i++){canvas.getContext('2d').fillRect(0,0,160,90);await new Promise(resolve=>setTimeout(resolve,100));}recorder.stop();await done;stream.getTracks().forEach(track=>track.stop());return Array.from(new Uint8Array(await new Blob(parts).arrayBuffer()));});
 await context.route('https://audio.example/**',route=>route.fulfill({contentType:'video/webm',body:failSecond&&route.request().url().includes('river')?Buffer.from('invalid synthetic clip'):Buffer.from(bytes)}));
 await page.getByRole('button',{name:'Arrival',exact:true}).click();
 return{changes,requests,scenes,episode};
}
for(const width of [1280,390])test(`Explicit episode order and continuous preview at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{changes}=await fixture(page,context);const host=page.locator('#episode-workspace');
 await expect(host.getByRole('button',{name:'Preview episode',exact:true})).toBeDisabled();
 const down=host.getByRole('button',{name:'Reorder City gate',exact:true});await expect(down).toBeInViewport();await down.focus();await page.keyboard.press('Space');await expect(host.locator('[data-dragging=true]')).toHaveCount(1);await expect(page.locator('[id^=DndLiveRegion]')).toContainText('over droppable area gate');await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.keyboard.press(width<500?'ArrowRight':'ArrowDown');await expect(page.locator('[id^=DndLiveRegion]')).toContainText('over droppable area river');await page.keyboard.press('Space');
 await expect(host.locator('.scene-order-row .scene-card').first()).toContainText('River crossing');expect(changes[0].sceneIds).toEqual(['river','gate']);
 await host.getByRole('button',{name:'Reorder City gate',exact:true}).focus();await page.keyboard.press('Space');await expect(host.locator('[data-dragging=true]')).toHaveCount(1);await expect(page.locator('[id^=DndLiveRegion]')).toContainText('over droppable area gate');await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.keyboard.press(width<500?'ArrowLeft':'ArrowUp');await expect(page.locator('[id^=DndLiveRegion]')).toContainText('over droppable area river');await page.keyboard.press('Space');await expect(host.locator('.scene-order-row .scene-card').first()).toContainText('City gate');
 await host.getByRole('button',{name:'Edit episode',exact:true}).click();await expect(page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Episode editor',exact:true})})).toBeVisible();await page.getByRole('form',{name:'Episode editor',exact:true}).getByRole('button',{name:'Save changes',exact:true}).click();await expect.poll(()=>changes.length).toBe(3);expect(changes[2].expectedRevision).toBe('d'.repeat(32));
 await host.getByRole('button',{name:'City gate',exact:true}).click();const first=host.getByRole('button',{name:'Use in episode: City gate take',exact:true});await first.scrollIntoViewIfNeeded();await expect(first).toBeInViewport();await first.click();
 await host.getByRole('button',{name:'Edit scene',exact:true}).click();await expect(page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Scene editor',exact:true})})).toBeVisible();await page.getByRole('form',{name:'Scene editor',exact:true}).getByRole('button',{name:'Save changes',exact:true}).click();await expect.poll(()=>changes.length).toBe(5);expect(changes[4].expectedRevision).toBe('f'.repeat(32));
 await host.getByRole('button',{name:'River crossing',exact:true}).click();const second=host.getByRole('button',{name:'Use in episode: River crossing take',exact:true});await second.scrollIntoViewIfNeeded();await expect(second).toBeInViewport();await second.click();
 expect([...new Set(changes.filter(body=>body.selectedOutputKey).map(body=>body.selectedOutputKey))]).toEqual([key('gate'),key('river')]);
 const start=host.getByRole('button',{name:'Preview episode',exact:true});await expect(start).toBeEnabled();await start.scrollIntoViewIfNeeded();await start.click();
 const player=page.getByRole('dialog',{name:'Episode preview',exact:true}).locator('video[aria-label="Episode preview"]');await expect(page.getByRole('dialog',{name:'Episode preview',exact:true})).toBeVisible();await expect(player).toBeVisible();await expect(player).toHaveAttribute('src','https://audio.example/gate.webm');
 await expect(player).toHaveAttribute('src','https://audio.example/river.webm',{timeout:10000});await expect(page.locator('.episode-preview-status')).toContainText('2 of 2');
 await page.screenshot({path:testInfo.outputPath(`episode-playback-${width}.png`)});
 await expect(page.locator('.episode-preview-status')).toHaveText('Preview complete.',{timeout:10000});await expect(player).toHaveCount(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Episode preview stops visibly on a broken selected clip',async({page,context})=>{
 await fixture(page,context,{failSecond:true});const host=page.locator('#episode-workspace');
 for(const name of ['City gate','River crossing']){await host.getByRole('button',{name,exact:true}).click();await host.getByRole('button',{name:`Use in episode: ${name} take`,exact:true}).click();}
 await host.getByRole('button',{name:'Preview episode',exact:true}).click();
 await expect(page.locator('.episode-preview-status')).toContainText('Preview stopped at River crossing',{timeout:10000});
 await expect(page.locator('.episode-preview-status')).not.toHaveText('Preview complete.');
});

test('Selecting another take invalidates the cached episode composition immediately',async({page,context})=>{
 const{requests}=await fixture(page,context);const host=page.locator('#episode-workspace');
 for(const name of ['City gate','River crossing']){await host.getByRole('button',{name,exact:true}).click();await host.getByRole('button',{name:`Use in episode: ${name} take`,exact:true}).click();}
 await expect(host.getByRole('button',{name:'Preview episode',exact:true})).toBeEnabled();
 await expect.poll(()=>requests.filter(path=>path==='/episode-composition').length).toBeGreaterThan(0);const before=requests.filter(path=>path==='/episode-composition').length;
 await host.getByRole('button',{name:'City gate',exact:true}).click();await host.getByRole('button',{name:'Use in episode: City gate second take',exact:true}).click();
 await expect.poll(()=>requests.filter(path=>path==='/episode-composition').length).toBeGreaterThan(before);
 await host.getByRole('button',{name:'Preview episode',exact:true}).click();const player=page.getByRole('dialog',{name:'Episode preview',exact:true}).locator('video[aria-label="Episode preview"]');await expect(player).toHaveAttribute('src','https://audio.example/gate-alt.webm');
 await expect.poll(()=>player.evaluate(video=>video.paused)).toBe(false);
 const capturedPlayer=await player.elementHandle();await page.getByRole('dialog',{name:'Episode preview',exact:true}).getByRole('button',{name:'Close',exact:true}).click();
 await expect.poll(()=>capturedPlayer.evaluate(video=>video.paused)).toBe(true);await expect(player).toHaveCount(0);
 await page.getByRole('link',{name:'Dashboard',exact:true}).click();await expect(page.getByRole('dialog',{name:'Episode preview',exact:true})).toHaveCount(0);
});

test('An uncertain selection response is reconciled without repeating the write',async({page,context})=>{
 const{changes}=await fixture(page,context,{uncertainSelection:true});const host=page.locator('#episode-workspace');
 await host.getByRole('button',{name:'City gate',exact:true}).click();await host.getByRole('button',{name:'Use in episode: City gate take',exact:true}).click();
 await expect(host.getByRole('button',{name:'Selected: City gate take',exact:true})).toBeDisabled();
 await expect(host.getByRole('status').filter({hasText:'Selected for this episode.'})).toHaveCount(1);expect(changes).toHaveLength(1);
});

for(const width of [1280,390])test(`local scene generation sends prompt and restores real rendered output at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page,context,{development:true});let posted,reads=0;
 await page.route('**/scene-renders**',route=>{const request=route.request();if(request.method()==='POST'){posted=request.postDataJSON();return route.fulfill({json:{jobId:'scene-job',status:'QUEUED',sceneRef:{sceneId:'gate',revision:'f'.repeat(32)}},headers:{'access-control-allow-origin':'https://panther.place'}});}if(!new URL(request.url()).searchParams.has('jobId'))return route.fulfill({json:{jobs:[]},headers:{'access-control-allow-origin':'https://panther.place'}});reads++;return route.fulfill({json:{jobId:'scene-job',status:reads===1?'RUNNING':'DONE',phase:'Rendering footage',outputKey:key('gate'),sceneRef:{episodeId:'arrival',sceneId:'gate',revision:'f'.repeat(32)}},headers:{'access-control-allow-origin':'https://panther.place'}});});
 await expect(page.getByRole('button',{name:'Create Episode',exact:true})).not.toBeVisible();
 await page.getByRole('button',{name:'Edit scene',exact:true}).click();const sceneEditor=page.getByRole('dialog',{name:'Edit scene',exact:true});await sceneEditor.getByLabel('Prompt',{exact:true}).fill('Travelers enter the city at sunrise');await sceneEditor.getByRole('button',{name:'Save changes',exact:true}).click();const composer=page.locator('#scene-video-composer');await expect(composer.locator('textarea,input[type=checkbox]')).toHaveCount(0);await composer.getByRole('button',{name:'Generate',exact:true}).click();
 const dialog=page.locator('.local-generation-inline[aria-label="Scene video"]');await expect(dialog).toBeVisible();await expect(page.getByRole('dialog',{name:'Scene video',exact:true})).toHaveCount(0);await expect(page.locator('.scene-prompt')).toHaveText('Travelers enter the city at sunrise');await expect(dialog).not.toContainText('Travelers enter the city at sunrise');await expect(dialog.getByRole('progressbar')).toBeVisible();await expect(page.locator('[data-scene-edit]')).toBeDisabled();
 await expect(dialog.locator('video')).toBeVisible({timeout:10000});await expect(dialog.locator('video')).toHaveAttribute('src','https://audio.example/gate.webm');
 expect(posted.sceneId).toBe('gate');expect(posted.episodeId).toBe('arrival');expect(posted.prompt).toContain('sunrise');expect(posted.operationId).toMatch(/^[a-f0-9]{32}$/);expect(posted.sourceKeys).toEqual([]);expect(posted.contextKeys).toEqual([]);
 await expect.poll(()=>control.scenes[0].selectedOutputKey).toBe(key('gate'));await expect(page.locator('[data-scene-edit]')).toBeEnabled();await page.screenshot({path:test.info().outputPath(`scene-render-${width}.png`)});
 await page.getByRole('button',{name:'← Episodes',exact:true}).click();await expect(page.getByRole('button',{name:'Create Episode',exact:true})).toBeVisible();
});

test('local active scene generation is restored on reload without another submission',async({page,context})=>{
 await fixture(page,context,{development:true});let posts=0;await page.route('**/scene-renders**',route=>{if(route.request().method()==='POST')posts++;return route.fulfill({json:new URL(route.request().url()).searchParams.has('jobId')?{jobId:'existing',status:'IN_QUEUE',queuePosition:2,sceneRef:{episodeId:'arrival',sceneId:'gate',revision:'b'.repeat(32)},prompt:'A remembered prompt'}:{jobs:[{jobId:'existing',createdAt:10,status:'RUNNING',sceneRef:{episodeId:'arrival',sceneId:'gate',revision:'b'.repeat(32)},prompt:'A remembered prompt'}]},headers:{'access-control-allow-origin':'https://panther.place'}});});
 await page.reload();await expect(page.locator('[data-scene-edit]')).toBeDisabled();await expect(page.locator('#scene-video-composer form')).not.toBeVisible();await expect(page.locator('.local-generation-inline')).toBeVisible();await expect(page.locator('.local-generation-inline')).not.toContainText('A remembered prompt');await expect(page.locator('.local-generation-inline').getByRole('progressbar')).toBeVisible();await expect(page.getByRole('dialog')).toHaveCount(0);expect(posts).toBe(0);
});

for(const width of [1280,390])test(`Local assembly and narration continue inline and restore at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});
 const control=await fixture(page,context,{development:true});const bodies=[];const headers={'access-control-allow-origin':'https://panther.place'};
 await page.route('**/episode-renders**',route=>{const post=route.request().method()==='POST';if(post)bodies.push(route.request().postDataJSON());const job={jobId:'assembled',status:'DONE',outputKey:key('gate')};return route.fulfill({headers,json:post||new URL(route.request().url()).searchParams.has('jobId')?job:{jobs:bodies.some(body=>!body.text)?[job]:[]}});});
 await page.route('**/narration-voices**',route=>route.fulfill({headers,json:{voices:[{id:'examplevoice123',name:'Storyteller'}]}}));
 await page.route('**/narration-jobs**',route=>{const post=route.request().method()==='POST';if(post)bodies.push(route.request().postDataJSON());const job={jobId:'narrated',status:'DONE',outputKey:'games/test-game/assets/narration/original/narration.mp3'};return route.fulfill({headers,json:post||new URL(route.request().url()).searchParams.has('jobId')?job:{jobs:bodies.some(body=>body.text)?[job]:[]}});});
 for(const name of ['City gate','River crossing']){await page.getByRole('button',{name,exact:true}).click();await page.getByRole('button',{name:`Use in episode: ${name} take`,exact:true}).click();}
 const assemble=page.getByRole('button',{name:'Assemble',exact:true});await expect(assemble).toBeEnabled();await assemble.click();let dialog=page.getByRole('region',{name:'Episode video',exact:true});await expect(dialog.locator('video')).toBeVisible();expect(bodies[0].episodeId).toBe('arrival');await expect(page.locator('dialog[open]')).toHaveCount(0);
 await page.getByRole('button',{name:'Narration',exact:true}).click();const editor=page.getByRole('dialog',{name:'Episode Narration',exact:true});await expect(editor.getByLabel('Narration text')).toHaveAttribute('maxlength','5000');await expect(editor.getByLabel('Performance direction')).toHaveAttribute('maxlength','2000');await editor.getByLabel('Narration text').fill('Beyond the harbor, the journey begins.');await editor.locator('button[role=combobox][aria-label=Voice]').click();await page.getByRole('option',{name:'Storyteller',exact:true}).click();await editor.getByLabel('Performance direction').fill('Warm and adventurous');await editor.getByRole('button',{name:'Generate Narration',exact:true}).click();dialog=page.getByRole('region',{name:'Narration',exact:true});await expect(dialog.locator('audio')).toBeVisible();expect(bodies[1]).toMatchObject({episodeId:'arrival',voiceId:'examplevoice123',text:'Beyond the harbor, the journey begins.',direction:'Warm and adventurous'});expect(control.changes).toHaveLength(2);await expect(editor).not.toBeVisible();await page.reload();await expect(page.getByRole('region',{name:'Episode video',exact:true}).locator('video')).toBeVisible();await expect(page.getByRole('region',{name:'Narration',exact:true}).locator('audio')).toBeVisible();expect(bodies).toHaveLength(2);await expect(page.locator('dialog[open]')).toHaveCount(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [1280,390])test(`Scene drag handle persists pointer order at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});const {changes}=await fixture(page,context);const host=page.locator('#episode-workspace');
 const add=host.getByRole('button',{name:'Create Scene',exact:true}),scenesHeading=host.getByRole('heading',{name:'Scenes',exact:true});await expect(add).toBeInViewport();expect(await add.evaluate(el=>Boolean(el.closest('.episode-scenes-panel')))).toBe(true);expect((await add.boundingBox()).y).toBeGreaterThanOrEqual((await scenesHeading.boundingBox()).y+(await scenesHeading.boundingBox()).height);
 const handle=host.getByRole('button',{name:'Reorder City gate',exact:true}),target=host.locator('.scene-order-row').nth(1);await expect(handle).toBeInViewport();const start=await handle.boundingBox(),end=await target.boundingBox();
 expect(start.width).toBeGreaterThanOrEqual(36);expect(start.height).toBeGreaterThanOrEqual(36);expect(await handle.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);expect(await target.evaluate(el=>parseFloat(getComputedStyle(el).paddingLeft))).toBe(0);
 await page.screenshot({path:test.info().outputPath(`scene-sidebar-${width}.png`)});
 await page.mouse.move(start.x+start.width/2,start.y+start.height/2);await page.mouse.down();await page.mouse.move(end.x+end.width/2,end.y+end.height/2,{steps:12});await page.mouse.up();
 await expect(host.locator('.scene-order-row .scene-card').first()).toContainText('River crossing');expect(changes[0].sceneIds).toEqual(['river','gate']);await expect(host.getByRole('button',{name:/Move .* (up|down)/})).toHaveCount(0);
});

test('Scene drag handle supports touch dragging on mobile',async({browser})=>{
 const context=await browser.newContext({viewport:{width:390,height:900},hasTouch:true,isMobile:true});const page=await context.newPage();try{const {changes}=await fixture(page,context);const host=page.locator('#episode-workspace'),handle=host.getByRole('button',{name:'Reorder City gate',exact:true}),target=host.locator('.scene-order-row').nth(1);await expect(handle).toBeInViewport();const start=await handle.boundingBox(),end=await target.boundingBox(),session=await context.newCDPSession(page);const x=start.x+start.width/2,y=start.y+start.height/2;
 await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1}]});await expect(host.locator('[data-dragging=true]')).toHaveCount(1);for(let i=1;i<=8;i++)await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+(end.x+end.width/2-x)*i/8,y:y+(end.y+end.height/2-y)*i/8,id:1}]});await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await expect(host.locator('.scene-order-row .scene-card').first()).toContainText('River crossing');expect(changes[0].sceneIds).toEqual(['river','gate']);}finally{await context.close();}
});


test('Scene prompt composition stays locked and restores after navigation',async({page,context})=>{
 await fixture(page,context,{development:true});let posts=0;await page.route('**/scene-renders**',route=>{const query=new URL(route.request().url()).searchParams;if(route.request().method()==='POST')posts++;const job={jobId:'composing-job',status:'COMPOSING',sceneRef:{episodeId:'arrival',sceneId:'gate',revision:'b'.repeat(32)},prompt:'Travelers enter the city'};return route.fulfill({json:query.has('jobId')?job:{jobs:[job]},headers:{'access-control-allow-origin':'https://panther.place'}});});
 await page.reload();const status=page.locator('.local-generation-inline');await expect(status).toContainText('Preparing video prompt…');await expect(status.getByRole('progressbar')).toBeVisible();await expect(page.locator('[data-scene-edit]')).toBeDisabled();await expect(page.locator('#scene-video-composer form')).not.toBeVisible();
 await page.getByRole('button',{name:'River crossing',exact:true}).click();await expect(page.locator('[data-scene-edit]')).toBeEnabled();await page.getByRole('button',{name:'City gate',exact:true}).click();await expect(status).toContainText('Preparing video prompt…');await expect(page.locator('[data-scene-edit]')).toBeDisabled();expect(posts).toBe(0);await expect(page.getByRole('dialog')).toHaveCount(0);
});

for(const width of [1280,390])test(`Scene details use nested URLs and persist editing inputs at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page,context,{development:true}),headers={'access-control-allow-origin':'https://panther.place'},transcript='games/test-game/assets/session/original/transcript.json';
 await page.route('**/characters**',route=>route.fulfill({headers,json:{characters:[{characterId:'ronin',name:'Ronin'},{characterId:'maximus',name:'Maximus'}],cursor:null}}));
 await page.route('**/assets?**',route=>route.fulfill({headers,json:{assets:new URL(route.request().url()).searchParams.get('section')==='transcripts'?[{key:transcript,kind:'raw-transcript',contentType:'application/json',metadata:{title:'Evening session'},lastModified:'2026-10-01T18:00:00Z'}]:[],cursor:null}}));
 await page.route('**/transcript-summaries**',route=>route.fulfill({headers,json:{status:'READY',summary:{title:'Evening session',summary:'The party enters the city.'},participants:[{name:'Alex'}]}}));
 await page.route('**/object-url?**',route=>route.fulfill({headers,json:{url:'https://audio.example/gate.webm',contentType:'application/json',metadata:{title:'Evening session'}}}));
 let posted;await page.route('**/scene-renders**',route=>{if(route.request().method()==='POST'){posted=route.request().postDataJSON();return route.fulfill({headers,json:{jobId:'saved-inputs',status:'COMPOSING',sceneRef:{episodeId:'arrival',sceneId:'gate',revision:'f'.repeat(32)}}});}return route.fulfill({headers,json:{jobs:[]}});});
 await expect(page).toHaveURL('https://panther.place/games/test-game/episodes/arrival/scenes/gate');await expect(page.getByRole('heading',{name:'Episodes',exact:true,level:1})).not.toBeVisible();await expect(page.getByRole('button',{name:'Create Episode',exact:true})).not.toBeVisible();
 await page.getByRole('button',{name:'Edit scene',exact:true}).click();const editor=page.getByRole('dialog',{name:'Edit scene',exact:true});await editor.getByLabel('Prompt',{exact:true}).fill('The party enters the city at sunset.');
 const chooseCharacter=async name=>{await editor.getByRole('combobox',{name:'Characters',exact:true}).click();await page.getByRole('combobox',{name:'Search characters',exact:true}).fill(name);await page.keyboard.press('Enter');await expect(editor.getByRole('combobox',{name:'Characters',exact:true})).toHaveAttribute('aria-expanded','false');};await chooseCharacter('Ron');await chooseCharacter('Max');await editor.getByRole('button',{name:'Remove Maximus from characters',exact:true}).click();await expect(editor.getByRole('button',{name:'Remove Ronin from characters',exact:true})).toBeVisible();await expect(editor.getByRole('button',{name:'Remove Maximus from characters',exact:true})).toHaveCount(0);await chooseCharacter('Max');await editor.getByRole('checkbox',{name:'Evening session',exact:true}).check();await editor.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect(editor).not.toBeVisible();expect(control.changes.at(-1).generationInputs).toEqual({schemaVersion:1,characterIds:['ronin','maximus'],sourceKeys:[transcript],contextKeys:[]});await expect(page.locator('.scene-prompt')).toHaveText('The party enters the city at sunset.');await expect(page.locator('.scene-cast-summary')).toHaveText('Ronin · Maximus');await expect(page.locator('.scene-source-summary')).toContainText('Evening session');await expect(page.locator('.selected-scene textarea,.selected-scene input[type=checkbox]')).toHaveCount(0);await expect(page.getByRole('button',{name:'Choose sources',exact:true})).toHaveCount(0);
 await page.reload();await expect(page.locator('.scene-prompt')).toHaveText('The party enters the city at sunset.');await expect(page.locator('.scene-cast-summary')).toHaveText('Ronin · Maximus');await page.locator('#scene-video-composer').getByRole('button',{name:'Generate',exact:true}).click();await expect.poll(()=>posted).toBeTruthy();expect(posted).toMatchObject({prompt:'The party enters the city at sunset.',characterIds:['ronin','maximus'],sourceKeys:[transcript],contextKeys:[]});await expect(page.locator('[data-scene-edit]')).toBeDisabled();await expect(page.locator('.local-generation-inline')).not.toContainText('The party enters the city at sunset.');
 await page.screenshot({path:testInfo.outputPath(`scene-details-${width}.png`)});await page.getByRole('button',{name:'← Episodes',exact:true}).click();await expect(page).toHaveURL('https://panther.place/games/test-game/episodes');await expect(page.getByRole('heading',{name:'Episodes',exact:true,level:1})).toBeVisible();
});
for(const width of [1280,390])test(`Episode library uses real first-scene thumbnail without duplicate videos at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page,context),thumbnail='games/test-game/assets/preview/original/first-frame.jpg';
 const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;const context=canvas.getContext('2d');context.fillStyle='#b99647';context.fillRect(0,0,320,180);context.fillStyle='#132b40';context.fillRect(20,30,100,130);return canvas.toDataURL('image/png').split(',')[1];});
 control.episode.thumbnailKey=thumbnail;await page.route('**/object-url?**',route=>new URL(route.request().url()).searchParams.get('key')===thumbnail?route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{url:'https://audio.example/first-frame.png',contentType:'image/png'}}):route.fallback());await page.route('https://audio.example/first-frame.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
 await page.getByRole('button',{name:'← Episodes',exact:true}).click();await page.reload();await expect(page.getByRole('heading',{name:'Episodes',exact:true,level:1})).toBeVisible();await expect(page.getByRole('button',{name:'Create Episode',exact:true})).toBeVisible();await expect(page.locator('.video-library-cards')).toHaveCount(0);await expect(page.locator('.episode-card')).toHaveCount(1);const image=page.locator('.episode-card-thumbnail img');await expect(image).toBeVisible();await expect.poll(()=>image.evaluate(node=>node.naturalWidth)).toBe(320);await page.screenshot({path:testInfo.outputPath(`episode-library-${width}.png`)});
});

for(const width of [1280,390])test(`Previous video links redirect to episode pages at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(page,context);
 await page.goto('https://panther.place/games/test-game/videos?episode=arrival&scene=gate');
 await expect(page).toHaveURL('https://panther.place/games/test-game/episodes/arrival/scenes/gate');
 await expect(page.getByRole('heading',{name:'City gate',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Create Episode',exact:true})).not.toBeVisible();
 await page.goto('https://panther.place/games/test-game/videos/arrival/scenes/river');
 await expect(page).toHaveURL('https://panther.place/games/test-game/episodes/arrival/scenes/river');
 await expect(page.getByRole('heading',{name:'River crossing',exact:true})).toBeVisible();
});
