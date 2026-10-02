const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const jwt='test.'+Buffer.from(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-editor'})).toString('base64url')+'.test';
const key=id=>`games/test-game/assets/${id}/original/take.webm`;
async function fixture(page,context,{failSecond=false,uncertainSelection=false}={}){
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
  if(pathname==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
  if(pathname==='/vendor/model-viewer.min.js')return route.fulfill({contentType:'application/javascript',body:''});
  const root=path.resolve(__dirname,'../../web/media-explorer');let source=path.resolve(root,'.'+pathname);if(!source.startsWith(root+path.sep)||!fs.existsSync(source)||!fs.statSync(source).isFile())source=path.join(root,'index.html');
  return route.fulfill({body:fs.readFileSync(source),contentType:source.endsWith('.js')?'application/javascript':source.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('https://panther.place/games/test-game/videos');
 // Two-second synthetic video captured entirely inside the isolated test browser.
 const bytes=await page.evaluate(async()=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];recorder.ondataavailable=e=>parts.push(e.data);const done=new Promise(resolve=>recorder.onstop=resolve);recorder.start();for(let i=0;i<20;i++){canvas.getContext('2d').fillRect(0,0,160,90);await new Promise(resolve=>setTimeout(resolve,100));}recorder.stop();await done;stream.getTracks().forEach(track=>track.stop());return Array.from(new Uint8Array(await new Blob(parts).arrayBuffer()));});
 await context.route('https://audio.example/**',route=>route.fulfill({contentType:'video/webm',body:failSecond&&route.request().url().includes('river')?Buffer.from('invalid synthetic clip'):Buffer.from(bytes)}));
 await page.getByRole('button',{name:'Arrival',exact:true}).click();
 return{changes,requests};
}
for(const width of [1280,390])test(`Explicit episode order and continuous preview at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{changes}=await fixture(page,context);const host=page.locator('#episode-workspace');
 await expect(host.getByRole('button',{name:'Preview episode',exact:true})).toBeDisabled();
 await expect(host.getByRole('button',{name:'Move City gate up',exact:true})).toBeDisabled();
 const down=host.getByRole('button',{name:'Move City gate down',exact:true});await expect(down).toBeInViewport();await down.click();
 await expect(host.locator('.scene-order-row .scene-card').first()).toHaveText('River crossing');expect(changes[0].sceneIds).toEqual(['river','gate']);
 await host.getByRole('button',{name:'Move City gate up',exact:true}).click();await expect(host.locator('.scene-order-row .scene-card').first()).toHaveText('City gate');
 await host.getByRole('button',{name:'Edit episode',exact:true}).click();await expect(page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Episode editor',exact:true})})).toBeVisible();await page.getByRole('form',{name:'Episode editor',exact:true}).getByRole('button',{name:'Save changes',exact:true}).click();await expect.poll(()=>changes.length).toBe(3);expect(changes[2].expectedRevision).toBe('d'.repeat(32));
 await host.getByRole('button',{name:'City gate',exact:true}).click();const first=host.getByRole('button',{name:'Use in episode: City gate take',exact:true});await first.scrollIntoViewIfNeeded();await expect(first).toBeInViewport();await first.click();
 await host.getByRole('button',{name:'Edit scene',exact:true}).click();await expect(page.getByRole('dialog').filter({has:page.getByRole('form',{name:'Scene editor',exact:true})})).toBeVisible();await page.getByRole('form',{name:'Scene editor',exact:true}).getByRole('button',{name:'Save changes',exact:true}).click();await expect.poll(()=>changes.length).toBe(5);expect(changes[4].expectedRevision).toBe('f'.repeat(32));
 await host.getByRole('button',{name:'River crossing',exact:true}).click();const second=host.getByRole('button',{name:'Use in episode: River crossing take',exact:true});await second.scrollIntoViewIfNeeded();await expect(second).toBeInViewport();await second.click();
 expect([...new Set(changes.filter(body=>body.selectedOutputKey).map(body=>body.selectedOutputKey))]).toEqual([key('gate'),key('river')]);
 const start=host.getByRole('button',{name:'Preview episode',exact:true});await expect(start).toBeEnabled();await start.scrollIntoViewIfNeeded();await start.click();
 const player=host.locator('video[aria-label="Episode preview"]');await expect(page.getByRole('dialog',{name:'Episode preview',exact:true})).toBeVisible();await expect(player).toBeVisible();await expect(player).toHaveAttribute('src','https://audio.example/gate.webm');
 await expect(player).toHaveAttribute('src','https://audio.example/river.webm',{timeout:10000});await expect(host.locator('.episode-preview-status')).toContainText('2 of 2');
 await page.screenshot({path:testInfo.outputPath(`episode-playback-${width}.png`)});
 await expect(host.locator('.episode-preview-status')).toHaveText('Preview complete.',{timeout:10000});await expect(player).toHaveCount(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Episode preview stops visibly on a broken selected clip',async({page,context})=>{
 await fixture(page,context,{failSecond:true});const host=page.locator('#episode-workspace');
 for(const name of ['City gate','River crossing']){await host.getByRole('button',{name,exact:true}).click();await host.getByRole('button',{name:`Use in episode: ${name} take`,exact:true}).click();}
 await host.getByRole('button',{name:'Preview episode',exact:true}).click();
 await expect(host.locator('.episode-preview-status')).toContainText('Preview stopped at River crossing',{timeout:10000});
 await expect(host.locator('.episode-preview-status')).not.toHaveText('Preview complete.');
});

test('Selecting another take invalidates the cached episode composition immediately',async({page,context})=>{
 const{requests}=await fixture(page,context);const host=page.locator('#episode-workspace');
 for(const name of ['City gate','River crossing']){await host.getByRole('button',{name,exact:true}).click();await host.getByRole('button',{name:`Use in episode: ${name} take`,exact:true}).click();}
 await expect(host.getByRole('button',{name:'Preview episode',exact:true})).toBeEnabled();
 await expect.poll(()=>requests.filter(path=>path==='/episode-composition').length).toBeGreaterThan(0);const before=requests.filter(path=>path==='/episode-composition').length;
 await host.getByRole('button',{name:'City gate',exact:true}).click();await host.getByRole('button',{name:'Use in episode: City gate second take',exact:true}).click();
 await expect.poll(()=>requests.filter(path=>path==='/episode-composition').length).toBeGreaterThan(before);
 await host.getByRole('button',{name:'Preview episode',exact:true}).click();const player=host.locator('video[aria-label="Episode preview"]');await expect(player).toHaveAttribute('src','https://audio.example/gate-alt.webm');
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
