const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH}=require('../dist/lib/panther-media-explorer-stack');
const origin='https://panther.place',api='https://test.execute-api.us-west-2.amazonaws.com';
const headers={'access-control-allow-origin':origin,'access-control-allow-headers':'authorization,content-type','access-control-allow-methods':'GET,POST,OPTIONS'};
async function fixture(page,{human=false,conflict=false,planning=false,multi=false,local=false,long=false,failed=false,take=false}={}) {
  const writes=[],errors=[];page.on('pageerror',error=>errors.push(error.message));
  const chapter='c'.repeat(64),jobId='d'.repeat(64),frame='games/test-game/assets/frame/original/frame.png';
  let episode={schemaVersion:1,entityType:'Episode',gameId:'test-game',id:'pilot',name:'The crossing',description:'At the gates',revision:'a'.repeat(32),sceneIds:planning?[]:['arrival'],...(planning?{production:{state:'planning',jobId}}:{})};
  let scene={schemaVersion:1,entityType:'Scene',gameId:'test-game',episodeId:'pilot',id:'arrival',name:'Arrival',description:'The gates open.',type:'general',revision:'b'.repeat(32),selectedOutputKey:null,planningState:human?'ready':'needs-approval',storyboard:{schemaVersion:1,origin:human?'human':'ai',revision:'e'.repeat(64),decision:null,shots:[{shotId:'gate',description:'The party arrives at dusk.',camera:'Wide, slow push-in',durationSeconds:8,narration:'At dusk, they arrived.',frameKey:frame}]}};
  let published=!planning;
  if(multi){scene.storyboard.shots[0].durationSeconds=4;scene.storyboard.shots.push({shotId:'reaction',description:'The travelers react.',camera:'Close',durationSeconds:3,frameKey:null,narration:''});}
  if(long)scene.storyboard.shots[0].durationSeconds=18;
  const takes=multi||long||take?scene.storyboard.shots.map((shot,i)=>({key:`games/test-game/assets/take-${i}/original/video.webm`,contentType:'video/webm',name:`Take ${i+1}`,lastModified:'2026-01-01T00:00:00Z',metadata:{title:`Take ${i+1}`,contentType:'video/webm',extra:{relationshipRole:'finished',sceneRef:{episodeId:'pilot',sceneId:'arrival',revision:scene.revision},storyboardShotRef:{revision:scene.storyboard.revision,shotId:shot.shotId},mediaProbe:{format:{duration:'8'}}}}})):[];
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-editor'}))+'.test'})));
  await page.route(`${origin}/**`,route=>{
    const p=new URL(route.request().url()).pathname;
    if(p==='/config.js')return route.fulfill({contentType:'application/javascript',body:`window.PANTHER_CONFIG={apiUrl:'${api}',development:${local},clientId:'test',cognitoDomain:'https://test.amazoncognito.com',redirectUri:'${origin}/'};`});
    const file=p==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(p)?p.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('https://images.example/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="960" height="540" fill="#263b40"/></svg>'}));
  await page.route(`${api}/**`,async route=>{
    const u=new URL(route.request().url()),post=route.request().method()==='POST';
    if(route.request().method()==='OPTIONS')return route.fulfill({status:204,headers});
    const game={id:'test-game',name:'A fictional campaign',purpose:'campaign'};let body={};
    if(u.pathname==='/games')body={games:[game]};
    if(u.pathname==='/game')body={game,players:[],characters:[],memberships:[]};
    if(u.pathname==='/assets')body={assets:takes,cursor:null};
    if(u.pathname==='/scene-assemblies'){if(post)writes.push(route.request().postDataJSON());body={jobId:'9'.repeat(64),status:'QUEUED'};}
    if(u.pathname==='/scene-renders'){if(post){writes.push(route.request().postDataJSON());body={jobId:'f'.repeat(64),status:'QUEUED'};}else body={jobs:failed?[{jobId:'f'.repeat(64),status:'FAILED',message:'The provider rejected the video prompt because it exceeds its length limit.'}]:[]};}
    if(u.pathname==='/object-url'){const take=takes.find(item=>item.key===u.searchParams.get('key'));body={url:'https://videos.example/take.webm',contentType:'video/webm',metadata:take?.metadata};}
    if(u.pathname==='/characters')body={characters:[],cursor:null};
    if(u.pathname==='/episodes')body=u.searchParams.has('id')?{record:episode}:{records:[episode],cursor:null};
    if(u.pathname==='/scenes'){
      if(post){const request=route.request().postDataJSON();writes.push(request);if(conflict)return route.fulfill({status:409,headers,json:{error:'This scene changed. Reopen it before saving.'}});
        if(request.storyboardDecision){scene={...scene,planningState:request.storyboardDecision.action==='approved'?'ready':'changes-requested',storyboard:{...scene.storyboard,decision:request.storyboardDecision}};}
        if(request.shotSelection){const selection=request.shotSelection,shot=scene.storyboard.shots.find(item=>item.shotId===selection.shotId);scene={...scene,shotTakes:{...scene.shotTakes,[shot.shotId]:{...selection,durationSeconds:shot.durationSeconds}}};}
        if(request.storyboardShots){const changed=JSON.stringify(request.storyboardShots)!==JSON.stringify(scene.storyboard.shots);scene={...scene,planningState:changed?'ready':scene.planningState,storyboard:{...scene.storyboard,origin:changed?'human':scene.storyboard.origin,shots:request.storyboardShots,decision:changed?null:scene.storyboard.decision}};}
        body={record:scene};
      }else body={records:published?[scene]:[],cursor:null};
    }
    if(u.pathname==='/image-links')body={images:{[frame]:{url:'https://images.example/frame.svg'}}};
    if(u.pathname==='/novel')body=u.searchParams.has('id')?{chapter:{id:chapter,gameId:'test-game',title:'The crossing',markdown:'The party crossed the river.',details:{}}}:{chapters:[{id:chapter,gameId:'test-game',title:'The crossing'}],cursor:null};
    if(['/novel-stories','/novel-books'].includes(u.pathname))body={records:[],cursor:null};
    if(u.pathname==='/novel-chapter')body={id:chapter,gameId:'test-game',title:'The crossing',markdown:'The party crossed the river.',sessionId:'fictional-session',createdAt:1700000000,details:{sourceKeys:[],review:{markdown:'',uncertainties:[]}} };
    if(u.pathname==='/editorial-jobs'){
      if(post){writes.push(route.request().postDataJSON());episode={...episode,sceneIds:[],production:{state:'planning',jobId}};published=false;body={jobId,episodeRef:{episodeId:'pilot',revision:episode.revision}};}
      else if(u.searchParams.has('jobId'))body={job:{jobId,status:published?'READY_FOR_VIDEO_DISCUSSION':'PROCESSING'},tasks:[]};
      else body={jobs:[]};
    }
    return route.fulfill({headers,json:body});
  });
  return {writes,errors,chapter,publish(){published=true;episode={...episode,sceneIds:['arrival'],production:{state:'planned',jobId}};}};
}
for(const width of [1280,871,390]) {
 test(`each storyboard shot owns generation and its selected cut at ${width}px`,async({page})=>{
   await page.setViewportSize({width,height:1000});const {writes,errors}=await fixture(page,{human:true,multi:true,local:true});
   await page.route('https://videos.example/**',route=>route.fulfill({contentType:'video/webm',body:fs.readFileSync(path.join(__dirname,'fixtures/storyboard-take.webm'))}));
   await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
   const board=page.getByRole('region',{name:'Scene storyboard'});
   await board.getByRole('button',{name:'Generate shot 2',exact:true}).click();
   expect(writes[0].shotId).toBe('reaction');expect(writes[0].prompt).toContain('The travelers react.');
   await board.getByRole('combobox',{name:'Take for shot 1'}).click();await page.getByRole('option',{name:'Take 1 · 8s'}).click();
   expect(writes[1].shotSelection).toEqual({storyboardRevision:'e'.repeat(64),shotId:'gate',assetKey:'games/test-game/assets/take-0/original/video.webm',startSeconds:0});
   const video=board.locator('video[aria-label="Shot 1 video"]');
   await expect(video).toBeVisible();
   const selector=board.getByRole('combobox',{name:'Take for shot 1'});
   const bounds=await selector.evaluate(el=>{const card=el.closest('li'),box=el.getBoundingClientRect(),parent=card.getBoundingClientRect(),style=getComputedStyle(card);return {left:box.left,right:box.right,innerLeft:parent.left+parseFloat(style.paddingLeft),innerRight:parent.right-parseFloat(style.paddingRight)};});
   expect(bounds.left).toBeGreaterThanOrEqual(bounds.innerLeft-1);
   expect(bounds.right).toBeLessThanOrEqual(bounds.innerRight+1);
   const playerBounds=await video.boundingBox(),selectorBounds=await selector.boundingBox();
   expect(selectorBounds.width).toBeLessThanOrEqual(playerBounds.width+1);
   await expect.poll(()=>video.evaluate(el=>el.readyState)).toBeGreaterThan(0);
   expect(await video.evaluate(el=>el.duration)).toBeCloseTo(8,1);
   await video.evaluate(el=>{el.currentTime=4;el.dispatchEvent(new Event('timeupdate'));});
   expect(await video.evaluate(el=>el.currentTime)).toBeCloseTo(0,1);
   await expect(board.locator('video[aria-label="Shot 2 video"]')).toHaveCount(0);
   await expect(board.getByLabel('Trim start (seconds)')).toBeVisible();
   await expect(board.getByRole('button',{name:'Assemble',exact:true})).toBeDisabled();
   await expect(page.getByRole('button',{name:'Generate',exact:true})).toHaveCount(0);
   const actions=board.getByRole('group',{name:'Storyboard actions'});
   const edit=actions.getByRole('button',{name:'Edit',exact:true}),assembly=actions.getByRole('button',{name:'Assemble',exact:true});
   await expect(edit).toBeVisible();await expect(assembly).toBeVisible();
   await expect(assembly.locator('svg.lucide-hammer')).toHaveCount(1);
   const editBox=await edit.boundingBox(),assemblyBox=await assembly.boundingBox();
   expect(Math.abs(editBox.y-assemblyBox.y)).toBeLessThanOrEqual(1);
   expect(assemblyBox.x).toBeGreaterThan(editBox.x+editBox.width);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
   await expect(page.getByText(/Finished videos unavailable/)).toHaveCount(0);expect(errors).toEqual([]);
   await page.screenshot({path:test.info().outputPath(`shot-takes-${width}.png`),fullPage:true});
   await board.getByRole('combobox',{name:'Take for shot 2'}).click();await page.getByRole('option',{name:'Take 1 · 8s'}).click();
   await expect(board.getByRole('button',{name:'Assemble',exact:true})).toBeEnabled();
   await board.getByRole('button',{name:'Assemble',exact:true}).click();
   await expect.poll(()=>writes.some(item=>item.sceneId==='arrival'&&!item.shotId&&!item.shotSelection)).toBe(true);
 });
 test(`AI storyboard approval belongs to its scene at ${width}px`,async({page})=>{
   await page.setViewportSize({width,height:1000});const {writes,errors}=await fixture(page);
   await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
   const board=page.getByRole('region',{name:'Scene storyboard'});
   await expect(page.getByRole('img',{name:'Storyboard needs approval',exact:true})).toBeVisible();
   await expect(board).toContainText('Needs approval');await expect(board).toContainText('The party arrives at dusk.');
   await expect(board.getByRole('button',{name:'Generate shot 1',exact:true})).toBeDisabled();
   const frame=board.getByRole('button',{name:'Open storyboard frame for shot 1'});await frame.hover();
   const hover=await frame.evaluate(el=>getComputedStyle(el).borderColor);await page.mouse.move(0,0);expect(hover).not.toBe(await frame.evaluate(el=>getComputedStyle(el).borderColor));
   await board.getByRole('button',{name:'Approve',exact:true}).click();await expect(board.getByRole('button',{name:'Approve',exact:true})).toHaveCount(0);
   expect(writes[0].storyboardDecision).toEqual({revision:'e'.repeat(64),action:'approved'});
   await expect(page.getByRole('img',{name:'Storyboard needs approval',exact:true})).toHaveCount(0);
   await expect(page.getByRole('img',{name:'Storyboard approved',exact:true})).toBeVisible();
   await expect(board.getByRole('button',{name:'Generate shot 1',exact:true})).toBeEnabled();
   await expect(page.locator('#storyboard-entry,#approval-inbox,#video-approval-inbox,#session-video-plans')).toHaveCount(0);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
   await page.screenshot({path:test.info().outputPath(`owned-storyboard-${width}.png`),fullPage:true});expect(errors).toEqual([]);
 });
 test(`rejected storyboard has a scene-list icon at ${width}px`,async({page})=>{
   await page.setViewportSize({width,height:1000});await fixture(page);
   await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
   const board=page.getByRole('region',{name:'Scene storyboard'});
   await board.getByRole('button',{name:'Request changes',exact:true}).click();
   await expect(page.getByRole('img',{name:'Storyboard rejected',exact:true})).toBeVisible();
   await expect(page.getByRole('img',{name:'Storyboard approved',exact:true})).toHaveCount(0);
   await expect(board.getByRole('button',{name:'Generate shot 1',exact:true})).toBeDisabled();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 });
 test(`human storyboards save through the scene without approval at ${width}px`,async({page})=>{
   await page.setViewportSize({width,height:1000});const {writes}=await fixture(page,{human:true});await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
   const board=page.getByRole('region',{name:'Scene storyboard'});await expect(board.getByRole('button',{name:'Approve',exact:true})).toHaveCount(0);
   await board.getByRole('group',{name:'Storyboard actions'}).getByRole('button',{name:'Edit',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Edit storyboard'});
   await dialog.getByLabel('Action and composition').fill('The gates close behind the travelers.');
   await dialog.getByRole('button',{name:'Save storyboard'}).click();await expect(dialog).toHaveCount(0);
   expect(writes[0].storyboardShots[0].description).toBe('The gates close behind the travelers.');expect(writes[0].origin).toBeUndefined();await expect(board).toContainText('The gates close behind the travelers.');
 });
 test(`chapter adaptation creates one owned pending Episode at ${width}px`,async({page})=>{
   await page.setViewportSize({width,height:1000});const state=await fixture(page);
   await page.goto(`${origin}/games/test-game/episodes`);await page.getByRole('button',{name:'Create Episode options'}).click();const menu=page.getByRole('menuitem',{name:'Create from Novel…'});await menu.hover();await menu.click();
   const dialog=page.getByRole('dialog',{name:'Create TV Episode'});await dialog.getByRole('combobox').click();await page.getByRole('option',{name:'The crossing'}).click();await page.keyboard.press('Escape');
   await dialog.getByRole('button',{name:'Create TV Episode',exact:true}).click();await expect(page).toHaveURL(/episodes\/pilot$/);await expect(page.getByRole('region',{name:'Episode preparation'})).toContainText('Preparing episode');
   expect(state.writes[0]).toEqual({gameId:'test-game',creation:{schemaVersion:4,target:'video',chapterId:state.chapter}});
   state.publish();await expect(page.getByRole('region',{name:'Scene storyboard'})).toBeVisible({timeout:10000});await expect(page.getByRole('region',{name:'Episode preparation'})).toHaveCount(0);expect(state.errors).toEqual([]);
 });
}
test('conflicting storyboard decisions stay visible and never claim approval',async({page})=>{
 await fixture(page,{conflict:true});await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);const board=page.getByRole('region',{name:'Scene storyboard'});await board.getByRole('button',{name:'Approve',exact:true}).click();await expect(board.getByRole('alert')).toContainText('This scene changed');await expect(board.getByRole('button',{name:'Generate shot 1',exact:true})).toBeDisabled();
});

for(const width of [1280,390])test(`chapter reader starts the same episode adaptation at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});const state=await fixture(page);
 await page.goto(`${origin}/games/test-game/novel/${state.chapter}`);
 const action=page.getByRole('button',{name:'Create TV Episode',exact:true});await expect(action).toBeVisible();await expect(action).toBeInViewport();await action.click();
 await expect(page).toHaveURL(/episodes\/pilot$/);await expect(page.getByRole('region',{name:'Episode preparation'})).toContainText('Preparing episode');
 expect(state.writes[0]).toEqual({gameId:'test-game',creation:{schemaVersion:4,target:'video',chapterId:state.chapter}});expect(state.errors).toEqual([]);
});

for(const width of [1280,871,390])test(`long storyboard cuts explain missing footage at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});await fixture(page,{human:true,local:true,long:true});
 await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
 const board=page.getByRole('region',{name:'Scene storyboard'});
 await board.getByRole('combobox',{name:'Take for shot 1'}).click();
 await expect(page.getByRole('option',{name:'Take 1 · 8s — needs 18s',exact:true})).toBeDisabled();
 await page.keyboard.press('Escape');
 await expect(board.getByRole('button',{name:'Assemble',exact:true})).toBeDisabled();
 await expect(board).toContainText('Split this item into shots of eight seconds or less');
});
test('a failed earlier scene request explains why no shot take exists',async({page})=>{
 await fixture(page,{human:true,local:true,failed:true});await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
 const board=page.getByRole('region',{name:'Scene storyboard'});
 await expect(board.getByRole('status')).toContainText('exceeds its length limit');
 await expect(board).toContainText('No take generated for this shot.');
 await expect(board.getByRole('button',{name:'Generate shot 1',exact:true})).toBeEnabled();
});

test('an eight-second take is selectable for an eight-second shot',async({page})=>{
 await fixture(page,{human:true,local:true,take:true});await page.goto(`${origin}/games/test-game/episodes/pilot/scenes/arrival`);
 await page.getByRole('combobox',{name:'Take for shot 1'}).click();
 await expect(page.getByRole('option',{name:'Take 1 · 8s',exact:true})).toBeEnabled();
});
