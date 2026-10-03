const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const jwt='test.'+Buffer.from(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-editor'})).toString('base64url')+'.test';
const key=id=>`games/test-game/assets/${id}/original/raw.json`;
const transcripts=[{key:key('source-one'),name:'raw.json',kind:'raw-transcript',metadata:{title:'First session'}},{key:key('source-two'),name:'raw.json',kind:'raw-transcript',metadata:{title:'Second session'}}];
const internalAsset={key:'games/test-game/assets/migration-audit/original/provenance.json',name:'provenance.json',kind:'game-context',metadata:{title:'Migration provenance audit',category:'reference'}};
const sceneRef={episodeId:'episode-one',sceneId:'scene-one',revision:'scene-revision'};
async function openScene(page){await page.getByRole('button',{name:'First episode',exact:true}).click();await page.getByRole('button',{name:'A moonlit crossing',exact:true}).click();await expect(page.locator('#scene-video-composer')).toBeVisible();}
const characters=[{id:'lantern-guide',characterId:'lantern-guide',name:'Lantern Guide'},{id:'river-scout',characterId:'river-scout',name:'River Scout'}];
const contextAsset={key:'games/test-game/assets/context/original/lore.json',name:'lore.json',kind:'game-context',metadata:{title:'Campaign lore',category:'reference'}};
const mapAsset={key:'games/test-game/assets/atlas/original/map.png',name:'map.png',kind:'map',contentType:'image/png',metadata:{title:'Riverlands atlas',category:'reference'}};
const secondMap={...mapAsset,key:'games/test-game/assets/coast/original/map.png',metadata:{title:'Coastal atlas',category:'reference'}};
async function fixture(context,{mapScene=false,technicalSources=false,automatic=false}={}){
 const submissions=[],reads=[],sceneWrites=[];
 let sceneRecord={id:sceneRef.sceneId,episodeId:sceneRef.episodeId,name:'A moonlit crossing',description:'',revision:sceneRef.revision,position:0,type:mapScene?'map':'general',mapAssetKey:null};
 await context.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
  const fulfill=value=>route.fulfill({...value,headers:{"access-control-allow-origin":"https://panther.place"}});
  const url=new URL(route.request().url());reads.push(url.pathname);
  if(url.pathname==='/transcript-summaries')return fulfill({json:{status:'READY',recordedAt:'2026-01-02T18:30:00Z',participants:[{id:'fictional-speaker',name:'Morgan'}],summary:{...(technicalSources?{title:'The river crossing'}:{}),summary:'The companions discuss crossing the river.'}}});
  if(url.pathname==='/asset-document')return fulfill({json:{document:{players:[{id:'fictional-speaker',name:'Morgan'}],segments:[{playerId:'fictional-speaker',text:'We should cross before sunset.'}]}}});
  if(url.pathname==='/episodes')return fulfill({json:{records:[{id:sceneRef.episodeId,name:'First episode',description:'',revision:'episode-revision',sceneIds:[sceneRef.sceneId]}],cursor:null}});
  if(url.pathname==='/scenes'){if(route.request().method()==='POST'){const body=route.request().postDataJSON();sceneWrites.push(body);sceneRecord={...sceneRecord,...body,revision:'map-scene-revision'};return fulfill({json:{record:sceneRecord}});}return fulfill({json:{records:[sceneRecord],cursor:null}});}
  if(url.pathname==='/video-collections')return fulfill({json:{collections:[],cursor:null}});
  if(url.pathname==='/characters')return fulfill({json:{characters,cursor:null}});
  if(url.pathname==='/object-url')return fulfill({json:{url:'https://maps.example/atlas.png',contentType:'image/png',metadata:url.searchParams.get('key')===secondMap.key?secondMap.metadata:mapAsset.metadata}});
  if(url.pathname==='/assets'&&mapScene&&url.searchParams.get('section')==='all')return fulfill({json:url.searchParams.has('cursor')?{assets:[secondMap],cursor:null}:{assets:[mapAsset,{...mapAsset,key:'games/other-game/assets/foreign/original/map.png',metadata:{title:'Foreign map'}},{...mapAsset,key:'games/test-game/assets/audit/original/image.png',metadata:{title:'Internal audit image',extra:{relationshipRole:'internal'}}},{...mapAsset,key:'games/test-game/assets/svg/original/map.svg',contentType:'image/svg+xml',metadata:{title:'Unsupported SVG'}}],cursor:'map-page-two'}});
  if(url.pathname==='/assets')return fulfill({json:{assets:url.searchParams.get('section')==='transcripts'?(technicalSources?transcripts.map(asset=>({...asset,name:'089c592c-47bd-49ad-abcc-447755aa11ff.json',metadata:{title:'089c592c-47bd-49ad-abcc-447755aa11ff.json'},lastModified:'2026-02-01T12:00:00Z'})):transcripts):url.searchParams.get('section')==='all'?[contextAsset,internalAsset]:[],cursor:null}});
  if(url.pathname==='/editorial-jobs'){
   if(route.request().method()==='POST'){submissions.push(route.request().postDataJSON());return fulfill({json:{jobId:'a'.repeat(64),status:'SUBMITTED'}});}
   if(automatic){if(!url.searchParams.has('jobId'))return fulfill({json:{jobs:[{jobId:'a'.repeat(64),sessionId:'test-session'}],cursor:null}});return fulfill({json:{job:{jobId:'a'.repeat(64),sessionId:'test-session',status:'READY_FOR_VIDEO_DISCUSSION'},tasks:[{stage:'video-screenplay',status:'DONE',output:{key:'games/test-game/assets/plan/original/screenplay.json'}}]}});}
   if(!url.searchParams.has('jobId'))return fulfill({json:{jobs:submissions.map(submission=>({jobId:'a'.repeat(64),creation:{...submission.creation,title:'A moonlit crossing'},createdAt:1,status:'READY_FOR_VIDEO_DISCUSSION'})),cursor:null}});
   const creation={...submissions.at(-1).creation,title:submissions.at(-1).creation.title||'A moonlit crossing'};
   return fulfill({json:{job:{jobId:'a'.repeat(64),creation,status:creation.target==='novel'?'NOVEL_READY':'READY_FOR_VIDEO_DISCUSSION'},tasks:[{stage:creation.target==='novel'?'novel-draft':'video-treatment',status:'DONE'}]}});
  }
  if(url.pathname.startsWith('/novel-'))return fulfill({json:{records:[],cursor:null}});
  return fulfill({json:{games:[{id:'test-game',name:'Test Game'}],game:{id:'test-game',name:'Test Game'},players:[],memberships:[],chapters:[],assets:[],characters:[],objects:[],prefixes:[],cursor:null}});
 });
 await context.route('https://panther.place/**',route=>{
  const pathname=new URL(route.request().url()).pathname;
  if(pathname.startsWith('/auth/'))return route.fulfill({json:{id_token:jwt,expires_in:3600}});
  if(pathname==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
  if(pathname==='/vendor/model-viewer.min.js')return route.fulfill({contentType:'application/javascript',body:''});
  const root=path.resolve(__dirname,'../../web/media-explorer');let source=path.resolve(root,'.'+pathname);if(!source.startsWith(root+path.sep)||!fs.existsSync(source)||!fs.statSync(source).isFile())source=path.join(root,'index.html');
  return route.fulfill({body:fs.readFileSync(source),contentType:source.endsWith('.js')?'application/javascript':source.endsWith('.css')?'text/css':'text/html'});
 });
 return{submissions,reads,sceneWrites};
}
for(const width of [1280,390])for(const target of ['novel'])test(`Create ${target} from selected immutable transcripts at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{submissions,reads}=await fixture(context);
 await page.goto(`https://panther.place/games/test-game/${target==='novel'?'novel':'videos'}`);
 const composer=page.locator(`#editorial-${target}-composer`);
 const before=reads.filter(p=>p==='/assets').length;
 await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'Generate chapter',exact:true})).toBeVisible();
 await expect.poll(async()=>{const r=await page.getByRole('dialog',{name:'Generate chapter',exact:true}).boundingBox();return Math.abs(r.x+r.width/2-width/2);}).toBeLessThan(2);
 const dialogGeometry=await page.getByRole('dialog',{name:'Generate chapter',exact:true}).boundingBox();
 expect(dialogGeometry.x).toBeGreaterThanOrEqual(0);expect(dialogGeometry.y).toBeGreaterThanOrEqual(0);
 expect(dialogGeometry.x+dialogGeometry.width).toBeLessThanOrEqual(width);
 expect(dialogGeometry.y+dialogGeometry.height).toBeLessThanOrEqual(900);
 await expect(page.locator('dialog')).toHaveCount(0);
 await expect(page.getByLabel('Title',{exact:true})).toHaveCount(0);
 await expect(page.getByLabel('Direction',{exact:true})).toHaveCount(0);
 await page.getByLabel('Prompt',{exact:true}).fill('Follow the companions across the river.');
 await expect(page.getByRole('dialog',{name:'Generate chapter',exact:true}).getByText('The companions discuss crossing the river.').first()).toBeVisible();
 await page.getByRole('button',{name:'Review First session',exact:true}).click();
 const review=page.getByRole('dialog',{name:'Transcript review',exact:true});await expect(review).toContainText('We should cross before sunset.');await expect(review).toContainText('Morgan');
 await review.getByRole('button',{name:'Regenerate summary',exact:true}).click();
 await review.getByRole('button',{name:'Close',exact:true}).click();
 await page.getByLabel('First session',{exact:true}).check();
 await page.getByLabel('Second session',{exact:true}).check();
 await page.getByRole('button',{name:'Add context',exact:true}).click();
 await page.getByRole('dialog',{name:'Add context',exact:true}).getByLabel('Campaign lore',{exact:true}).check();
 await expect(composer.getByText('Migration provenance audit',{exact:true})).toHaveCount(0);
 await page.getByRole('dialog',{name:'Add context',exact:true}).getByRole('button',{name:'Close',exact:true}).click();
 const submit=page.locator('#editorial-video-composer form, .novel-composer-dialog[data-panther-dialog] form').getByRole('button',{name:target==='novel'?'Generate chapter':'Create project',exact:true});
 await expect(submit).toBeInViewport();
 expect(await submit.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await page.screenshot({path:testInfo.outputPath(`editorial-form-${width}.png`),fullPage:true});
 await submit.click();
 await expect(composer).toContainText(target==='novel'?'Chapter ready':'awaiting your approval before video generation');
 expect(submissions).toHaveLength(1);
 expect(submissions[0]).toEqual({gameId:'test-game',creation:{schemaVersion:3,target,brief:'Follow the companions across the river.',sourceKeys:transcripts.map(a=>a.key),contextKeys:[contextAsset.key]}});
 expect(reads.filter(p=>p==='/assets').length).toBeGreaterThan(before);
 await page.screenshot({path:testInfo.outputPath(`editorial-${target}-${width}.png`)});
});

async function editSceneInputs(page,prompt,{characters=[],transcript=false}={}) {
 await page.getByRole('button',{name:'Edit scene',exact:true}).click();
 const editor=page.getByRole('form',{name:'Scene editor',exact:true});
 await editor.getByLabel('Prompt',{exact:true}).fill(prompt);
 for(const name of characters){await editor.getByRole('combobox',{name:'Characters',exact:true}).click();await page.getByRole('combobox',{name:'Search characters',exact:true}).fill(name);await page.getByRole('option',{name,exact:true}).click();}
 if(transcript)await editor.getByLabel('First session',{exact:true}).check();
 await editor.getByRole('button',{name:'Save changes',exact:true}).click();await expect(editor).not.toBeVisible();
}
for(const width of [1280,390])for(const withSources of [false,true])test(`Prompt-led video with ${withSources?'optional transcripts':'characters only'} at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{submissions}=await fixture(context);
 await page.goto('https://panther.place/games/test-game/videos');await openScene(page);
 await editSceneInputs(page,'A moonlit crossing',{characters:['Lantern Guide','River Scout'],transcript:withSources});
 const composer=page.locator('#scene-video-composer');
 await expect(composer.locator('.scene-cast-summary')).toHaveText('Lantern Guide · River Scout');
 await expect(composer.locator('textarea,input')).toHaveCount(0);
 await expect(composer).not.toContainText('Migration provenance audit');
 const submit=composer.getByRole('button',{name:'Generate',exact:true});await expect(submit).toBeInViewport();
 await page.screenshot({path:testInfo.outputPath(`prompt-video-${withSources?'sources':'characters'}-${width}.png`),fullPage:true});
 await submit.click();await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');
 expect(submissions).toEqual([{gameId:'test-game',creation:{schemaVersion:2,target:'video',brief:'A moonlit crossing',characterIds:['lantern-guide','river-scout'],sourceKeys:withSources?[transcripts[0].key]:[],contextKeys:[],sceneRef:{...sceneRef,revision:'map-scene-revision'}}}]);
 await page.reload();await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');
});
test('video submission failure preserves saved prompt and selected characters',async({page,context})=>{
 await fixture(context);await page.goto('https://panther.place/games/test-game/videos');await openScene(page);
 await editSceneInputs(page,'A river scout meets the lantern guide',{characters:['Lantern Guide']});
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/editorial-jobs',route=>route.request().method()==='POST'?route.fulfill({status:503,headers:{'access-control-allow-origin':'https://panther.place'},json:{error:'Temporarily unavailable'}}):route.fallback());
 const composer=page.locator('#scene-video-composer');await composer.getByRole('button',{name:'Generate',exact:true}).click();await expect(composer).toContainText('Temporarily unavailable');
 await page.getByRole('button',{name:'Edit scene',exact:true}).click();const editor=page.getByRole('form',{name:'Scene editor',exact:true});
 await expect(editor.getByLabel('Prompt',{exact:true})).toHaveValue('A river scout meets the lantern guide');await expect(editor).toContainText('Lantern Guide');
});


async function mapImage(page,context){
 const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=640;canvas.height=280;const c=canvas.getContext('2d');c.fillStyle='#e7d8b0';c.fillRect(0,0,640,280);c.strokeStyle='#8caaaf';c.lineWidth=24;c.beginPath();c.moveTo(50,0);c.bezierCurveTo(380,60,170,210,540,280);c.stroke();c.fillStyle='#40372e';c.font='24px serif';c.fillText('Riverlands',250,38);c.font='18px serif';c.fillText('Harbor',85,210);c.fillText('Hills',485,105);c.beginPath();c.arc(120,180,5,0,7);c.arc(515,80,5,0,7);c.fill();return canvas.toDataURL('image/png').split(',')[1];});
 await context.route('https://maps.example/**',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
}
for(const width of [1280,390])test(`Map image and route prompt persist before generation at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const {submissions,sceneWrites}=await fixture(context,{mapScene:true});
 await page.goto('https://panther.place/games/test-game/videos');await mapImage(page,context);await openScene(page);
 await page.getByRole('button',{name:'Edit scene',exact:true}).click();const editor=page.getByRole('form',{name:'Scene editor',exact:true});
 await editor.getByRole('combobox',{name:'Map image',exact:true}).click();
 for(const name of ['Foreign map','Internal audit image','Unsupported SVG'])await expect(page.getByRole('option',{name,exact:true})).toHaveCount(0);
 await page.getByRole('option',{name:'Riverlands atlas',exact:true}).click();await expect(editor.getByAltText('Selected map',{exact:true})).toBeVisible();
 await editor.getByRole('button',{name:'More images',exact:true}).click();await editor.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Coastal atlas',exact:true}).click();
 await editor.getByLabel('Prompt',{exact:true}).fill('The travelers move from Harbor to the Hills.');await editor.getByRole('button',{name:'Save changes',exact:true}).click();await expect(editor).not.toBeVisible();
 const submit=page.locator('#scene-video-composer').getByRole('button',{name:'Generate',exact:true});await expect(submit).toBeInViewport();await page.screenshot({path:testInfo.outputPath(`map-video-${width}.png`),fullPage:true});await submit.click();
 await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');expect(sceneWrites).toHaveLength(1);expect(sceneWrites[0]).toMatchObject({type:'map',mapAssetKey:secondMap.key,expectedRevision:sceneRef.revision});
 expect(submissions).toHaveLength(1);expect(submissions[0].creation).toMatchObject({brief:'The travelers move from Harbor to the Hills.',sourceKeys:[],sceneRef:{...sceneRef,revision:'map-scene-revision'}});
 await page.reload();await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');await page.getByRole('button',{name:'Edit scene',exact:true}).click();
 await expect(editor.getByRole('combobox',{name:'Scene type',exact:true})).toHaveText('Map');await expect(editor.getByRole('combobox',{name:'Map image',exact:true})).toHaveText('Coastal atlas');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Scene editor can set Map type and image with only a title',async({page,context})=>{
 const{sceneWrites}=await fixture(context,{mapScene:true});await page.goto('https://panther.place/games/test-game/videos');await mapImage(page,context);await openScene(page);await page.getByRole('button',{name:'Edit scene',exact:true}).click();
 const editor=page.getByRole('form',{name:'Scene editor',exact:true});await editor.getByRole('combobox',{name:'Scene type',exact:true}).click();await page.getByRole('option',{name:'General',exact:true}).click();await expect(editor.getByRole('combobox',{name:'Map image',exact:true})).toBeHidden();
 await editor.getByRole('combobox',{name:'Scene type',exact:true}).click();await page.getByRole('option',{name:'Map',exact:true}).click();await editor.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Riverlands atlas',exact:true}).click();await editor.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect.poll(()=>sceneWrites.length).toBe(1);expect(sceneWrites[0]).toMatchObject({type:'map',mapAssetKey:mapAsset.key,description:''});await expect(page.locator('#scene-video-composer').getByRole('button',{name:'Generate',exact:true})).toBeEnabled();
});
test('A failed map save retains the image and prompt and retries the same operation',async({page,context})=>{
 const {submissions,sceneWrites}=await fixture(context,{mapScene:true});await page.goto('https://panther.place/games/test-game/videos');await mapImage(page,context);await openScene(page);await page.getByRole('button',{name:'Edit scene',exact:true}).click();
 const editor=page.getByRole('form',{name:'Scene editor',exact:true});await editor.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Riverlands atlas',exact:true}).click();await editor.getByLabel('Prompt',{exact:true}).fill('Travel from Harbor to Hills');
 let failedBody;await page.route('https://test.execute-api.us-west-2.amazonaws.com/scenes',route=>{if(route.request().method()==='POST'&&!failedBody){failedBody=route.request().postDataJSON();return route.fulfill({status:503,headers:{'access-control-allow-origin':'https://panther.place'},json:{error:'Map save temporarily unavailable'}});}return route.fallback();});
 await editor.getByRole('button',{name:'Save changes',exact:true}).click();await expect(editor).toContainText('Map save temporarily unavailable');expect(submissions).toHaveLength(0);await expect(editor.getByLabel('Prompt',{exact:true})).toHaveValue('Travel from Harbor to Hills');await expect(editor.getByRole('combobox',{name:'Map image',exact:true})).toHaveText('Riverlands atlas');
 await editor.getByRole('button',{name:'Retry save',exact:true}).click();await expect(editor).not.toBeVisible();expect(sceneWrites).toEqual([failedBody]);
 await page.locator('#scene-video-composer').getByRole('button',{name:'Generate',exact:true}).click();await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');expect(submissions).toHaveLength(1);
});

for(const width of [1280,390])test(`Novel has one prompt action and supports a chapter without transcripts at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});const {submissions}=await fixture(context);
 await page.goto('https://panther.place/games/test-game/novel');
 const action=page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true});
 await expect(action).toBeVisible();await expect(action).toBeInViewport();
 expect(await action.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await expect(page.getByRole('button',{name:'Add chapter',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Write manually',exact:true})).toHaveCount(0);
 await action.click();const composer=page.locator('#editorial-novel-composer');
 await expect(page.getByRole('dialog',{name:'Generate chapter',exact:true}).locator('textarea')).toHaveCount(1);await expect(page.getByLabel('Title',{exact:true})).toHaveCount(0);
 await page.getByLabel('Prompt',{exact:true}).fill('Describe a fictional sunrise over the harbor.');
 const generate=page.locator('#editorial-video-composer form, .novel-composer-dialog[data-panther-dialog] form').getByRole('button',{name:'Generate chapter',exact:true});await expect(generate).toBeEnabled();await generate.click();
 await expect(composer).toContainText('Chapter ready');
 expect(submissions[0].creation).toEqual({schemaVersion:3,target:'novel',brief:'Describe a fictional sunrise over the harbor.',sourceKeys:[],contextKeys:[]});
});

for(const width of [1280,390])test(`Transcript picker replaces technical names with reviewed summary titles at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(context,{technicalSources:true});
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 const composer=page.getByRole('dialog',{name:'Generate chapter',exact:true});await expect(composer.getByRole('checkbox',{name:'The river crossing'})).toHaveCount(2);
 await expect(composer).not.toContainText('089c592c');await expect(composer).toContainText('Recorded');await expect(composer).toContainText('Morgan');
 await page.getByRole('dialog',{name:'Generate chapter',exact:true}).getByRole('button',{name:'Review The river crossing'}).first().click();await expect(page.getByRole('dialog',{name:'Transcript review',exact:true}).getByRole('heading')).toHaveText('The river crossing');
});

test('An uncertain summary regeneration retries the same operation',async({page,context})=>{
 await fixture(context);const operations=[];
 await context.route('https://test.execute-api.us-west-2.amazonaws.com/transcript-summaries**',route=>{
  if(route.request().method()==='POST'){operations.push(route.request().postDataJSON().operationId);if(operations.length===1)return route.fulfill({status:503,json:{error:'Connection interrupted'},headers:{'access-control-allow-origin':'https://panther.place'}});}
  return route.fulfill({json:{status:'READY',participants:[],summary:{summary:'The river crossing.'}},headers:{'access-control-allow-origin':'https://panther.place'}});
 });
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await page.getByRole('button',{name:'Review First session',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Transcript review',exact:true});
 await dialog.getByRole('button',{name:'Regenerate summary',exact:true}).click();await dialog.getByRole('button',{name:'Retry summary',exact:true}).click();
 await expect.poll(()=>operations.length).toBe(2);expect(operations[0]).toMatch(/^[a-f0-9]{32}$/);expect(operations[1]).toBe(operations[0]);
});

for(const width of [1280,390]) test(`Chapter progress shows real activity and actionable failure at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(context);let status='RUNNING';
 await page.route('**/editorial-jobs?*',route=>{
  if(!new URL(route.request().url()).searchParams.has('jobId'))return route.fallback();
  return route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{job:{jobId:'a'.repeat(64),status,creation:{title:'A river crossing',brief:'Follow the party across the river.'},...(status==='FAILED'?{message:'The worker stopped before finishing. Start the worker to continue.'}:{})},tasks:status==='FAILED'?[]:[{stage:'novel-draft',status:'RUNNING'}]}});
 });
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 const composer=page.locator('#editorial-novel-composer');await page.getByLabel('Prompt',{exact:true}).fill('Follow the party across the river.');await page.locator('#editorial-video-composer form, .novel-composer-dialog[data-panther-dialog] form').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(page.locator('#novel .explorer-heading [data-generation-action]')).toBeVisible();
 await expect(page.getByRole('region',{name:'Create your first chapter',exact:true})).toBeHidden();
 await expect(composer.getByRole('progressbar',{name:'Generation stages'})).toBeVisible();await expect(composer.getByRole('progressbar')).toHaveAttribute('aria-valuenow','0');await expect(composer.getByRole('progressbar')).toHaveAttribute('aria-valuemax','1');
 expect(await composer.getByRole('progressbar').locator('[data-state=active]').evaluate(el=>getComputedStyle(el).animationName)).toBe('panther-pulse');
 await page.screenshot({path:test.info().outputPath(`chapter-active-progress-${width}.png`),fullPage:true});
 await expect(composer.locator('[data-section=prompt]')).toBeVisible();await expect(composer).toContainText('Follow the party across the river.');
 status='FAILED';await expect(composer).toContainText('Generation failed',{timeout:10000});await expect(composer.getByRole('alert')).toContainText('Start the worker');
 await expect(composer.locator('summary').filter({hasText:/^Stages$/})).toHaveCount(0);await expect(composer.locator('summary').filter({hasText:'Processing details'})).toHaveCount(0);
 await expect(composer.locator('[data-section=prompt]')).toContainText('Follow the party across the river.');
 await expect(page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true})).toBeVisible();
 await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(page.getByLabel('Prompt',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Prompt',{exact:true})).toHaveValue('');
 await expect(page.getByRole('dialog',{name:'Generate chapter',exact:true}).getByRole('alert')).toHaveCount(0);
});

for(const width of [1280,390])test(`Empty Novel explains its purpose and offers usable prompts at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});const {submissions}=await fixture(context);await page.goto('https://panther.place/games/test-game/novel');
 const empty=page.getByRole('region',{name:'Create your first chapter',exact:true});await expect(empty).toBeVisible();await expect(empty).toContainText('Transcripts are optional');
 const action=empty.getByRole('button',{name:'Generate chapter',exact:true});await expect(action).toHaveCount(1);await expect(action).toBeInViewport();
 const centered=await action.boundingBox();expect(Math.abs(centered.x+centered.width/2-width/2)).toBeLessThan(5);
 expect(await action.evaluate(el=>{const box=el.getBoundingClientRect();return el.contains(document.elementFromPoint(box.x+box.width/2,box.y+box.height/2));})).toBe(true);
 await page.screenshot({path:test.info().outputPath(`novel-empty-${width}.png`),fullPage:true});
 const prompt='Retell the session from one character’s point of view.';await empty.getByRole('button',{name:prompt,exact:true}).click();
 const composer=page.locator('#editorial-novel-composer');await expect(page.getByLabel('Prompt',{exact:true})).toHaveValue(prompt);await expect(page.getByLabel('Prompt',{exact:true})).toBeFocused();
 await expect(empty).toBeHidden();expect(submissions).toHaveLength(0);await expect(page.getByRole('dialog',{name:'Generate chapter',exact:true}).getByRole('button',{name:'Generate chapter',exact:true})).toBeEnabled();
 await page.getByRole('dialog',{name:'Generate chapter',exact:true}).getByRole('button',{name:'Cancel',exact:true}).click();await expect(empty).toBeVisible();await action.click();await expect(page.getByLabel('Prompt',{exact:true})).toBeVisible();await expect(empty).toBeHidden();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [1280,390])test(`Automatic session plans remain reviewable before spending at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{submissions}=await fixture(context,{automatic:true});
 await page.goto('https://panther.place/games/test-game/videos');
 const composer=page.locator('#session-video-plans');
 const project=composer.getByRole('button',{name:'Session test-session · automatic',exact:true});
 await expect(project).toBeVisible();const box=await project.boundingBox();if(box.y+box.height>900)await page.mouse.wheel(0,box.y-450);await expect(project).toBeInViewport();await project.click();
 const progress=page.getByRole('dialog',{name:'Session test-session · automatic',exact:true});await expect(progress).toContainText('Video plan ready');await expect(progress).toContainText('Rendering requires approval');
 await expect(progress.locator('details,summary')).toHaveCount(0);
 const screenplay=progress.getByRole('button',{name:'View Screenplay',exact:true});
 await expect(screenplay).toBeVisible();
 await expect(screenplay).toHaveAttribute('data-output-key','games/test-game/assets/plan/original/screenplay.json');
 expect(submissions).toHaveLength(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:testInfo.outputPath(`automatic-session-${width}.png`)});
});

for(const width of [1280,390])test(`Completed chapter replaces its job without a reload at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(context);let complete=false,jobReads=0;
 await page.route('**/editorial-jobs?*',route=>{
  const url=new URL(route.request().url());if(!url.searchParams.has('jobId'))return route.fallback();
  complete=++jobReads>1;return route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{job:{jobId:'a'.repeat(64),status:complete?'NOVEL_READY':'RUNNING',chapterId:complete?'chapter-river':undefined,creation:{target:'novel',title:'The crossing',brief:'Retell the crossing.'}},tasks:[{stage:'novel-draft',status:complete?'DONE':'RUNNING'}]}});
 });
 await page.route('**/novel?*',route=>route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{chapters:complete?[{id:'chapter-river',sessionId:'session-river',title:'The crossing',createdAt:1000,assetKey:'games/test-game/assets/chapter-river/original/chapter.md'}]:[],cursor:null}}));
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 const composer=page.locator('#editorial-novel-composer');await page.getByLabel('Prompt',{exact:true}).fill('Retell the crossing.');await page.locator('#editorial-video-composer form, .novel-composer-dialog[data-panther-dialog] form').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'Generate chapter',exact:true})).not.toBeVisible();
 await expect(page.locator('.novel-card').getByRole('link',{name:'The crossing',exact:true})).toBeVisible({timeout:10000});await expect(page.locator('.novel-job-card')).toHaveCount(0);await expect(page.locator('#novel-empty-state')).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [1280,390])test(`Stage outputs open a readable nested preview and retain generation at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});await fixture(context);let reads=0;
 const output='games/test-game/assets/outline/original/report.json';
 await page.route('**/editorial-jobs?*',route=>{if(!new URL(route.request().url()).searchParams.has('jobId'))return route.fallback();reads++;return route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{job:{jobId:'a'.repeat(64),status:'RUNNING',creation:{target:'novel',title:'The river approach',brief:'Follow the party across the river.'},progress:{completedStages:1,totalStages:11},currentStage:'novel-draft'},tasks:[{stage:'novel-outline',status:'DONE',output:{key:output}},{stage:'novel-draft',status:'RUNNING'}]}});});
 await page.route('**/object-url?*',route=>new URL(route.request().url()).searchParams.get('key')===output?route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{key:output,filename:'report.json',contentType:'application/json',size:800,url:'https://files.example/report.json',metadata:{title:'The river approach'}}}):route.fallback());
 await page.route('**/asset-document?*',route=>new URL(route.request().url()).searchParams.get('key')===output?route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{key:output,kind:'novel-outline',document:{schemaVersion:1,entityType:'EditorialArtifact',stage:'novel-outline',payload:{title:'The river approach',markdown:'## The crossing\n\nThe companions approach the river at dusk.',uncertainties:['The destination is not yet established.'],decisions:[{decision:'Use the guide’s perspective.',reason:'The guide leads this scene.'}]}}}}):route.fallback());
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();const composer=page.locator('#editorial-novel-composer');await page.getByLabel('Prompt',{exact:true}).fill('Follow the party across the river.');await page.locator('#editorial-video-composer form, .novel-composer-dialog[data-panther-dialog] form').getByRole('button',{name:'Generate chapter',exact:true}).click();
 const progress=page.getByRole('region',{name:'Chapter progress',exact:true});await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow','1');await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuemax','11');await expect(progress.locator('[data-section=prompt] em')).toHaveText('Follow the party across the river.');await expect(progress.locator('ol')).toHaveCount(0);
 await progress.getByRole('button',{name:'View Outline',exact:true}).click();const preview=page.locator('#preview-dialog');await expect(preview).toBeVisible();await expect.poll(()=>preview.evaluate(node=>getComputedStyle(node.closest('[role=dialog]')).opacity)).toBe('1');await expect(page.locator('#preview-body')).toContainText('The companions approach the river at dusk.');await expect(page.locator('#preview-body')).toContainText('The destination is not yet established.');await expect(page.locator('#preview-body')).not.toContainText('"schemaVersion"');await expect(page).toHaveURL('https://panther.place/games/test-game/novel');
 await page.screenshot({path:testInfo.outputPath(`editorial-output-${width}.png`)});await expect.poll(()=>reads,{timeout:10000}).toBeGreaterThan(1);await page.getByRole('button',{name:'Close preview',exact:true}).click();await expect(preview).not.toBeVisible();await expect(progress).toBeVisible();await expect(progress.getByRole('button',{name:'View Outline',exact:true})).toBeFocused();await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuemax','11');await page.screenshot({path:testInfo.outputPath(`editorial-progress-${width}.png`)});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await progress.getByRole('button',{name:'View Outline',exact:true}).click();await expect(preview).toBeVisible();await page.keyboard.press('Escape');await expect(preview).not.toBeVisible();await expect(page.locator('#preview-body')).toBeEmpty();await expect(progress.getByRole('button',{name:'View Outline',exact:true})).toBeFocused();
});

for(const width of [1280,390])test(`Novel generation continues after navigation and restores on reload at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(context);let submitted=false,reads=0;
 await page.route('**/editorial-jobs**',route=>{const request=route.request(),url=new URL(request.url());if(request.method()==='POST'){submitted=true;return route.fulfill({json:{jobId:'a'.repeat(64),status:'SUBMITTED'},headers:{'access-control-allow-origin':'https://panther.place'}});}const job={jobId:'a'.repeat(64),status:'RUNNING',creation:{target:'novel',brief:'Follow the party across the river.'},progress:{completedStages:1,totalStages:11}};if(url.searchParams.has('jobId')){reads++;return route.fulfill({json:{job,tasks:[{stage:'novel-draft',status:'RUNNING'}]},headers:{'access-control-allow-origin':'https://panther.place'}});}return route.fulfill({json:{jobs:submitted?[job]:[],cursor:null},headers:{'access-control-allow-origin':'https://panther.place'}});});
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();const composer=page.locator('#editorial-novel-composer');await page.getByLabel('Prompt',{exact:true}).fill('Follow the party across the river.');await page.locator('#editorial-video-composer form, .novel-composer-dialog[data-panther-dialog] form').getByRole('button',{name:'Generate chapter',exact:true}).click();const progress=page.getByRole('region',{name:'Chapter progress',exact:true});await expect(progress).toBeVisible();await expect(page.getByRole('dialog')).toHaveCount(0);
 const initialReads=reads;await page.getByRole('link',{name:'Dashboard',exact:true}).click();await expect(page).toHaveURL(/dashboard$/);await expect.poll(()=>reads,{timeout:10000}).toBeGreaterThan(initialReads);await page.getByRole('navigation',{name:'Panther sections'}).getByRole('link',{name:'Novel',exact:true}).click();await expect(progress).toBeVisible();await page.reload();await expect(progress).toContainText('Follow the party across the river.');await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow','1');await expect(page.locator('.novel-job-card')).toHaveCount(1);await expect(page.getByRole('dialog')).toHaveCount(0);
});

for(const width of [1280,390])test(`Add scene types stay visible above the dialog and support keyboard selection at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});await fixture(context);await page.goto('https://panther.place/games/test-game/videos');await page.getByRole('button',{name:'First episode',exact:true}).click();await page.getByRole('button',{name:'Add scene',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Add scene',exact:true}),select=dialog.getByRole('combobox',{name:'Scene type',exact:true});const transcriptCopy=dialog.locator('.editorial-source-copy').first();await expect(transcriptCopy).toBeVisible();expect((await transcriptCopy.boundingBox()).width).toBeGreaterThanOrEqual(160);expect((await transcriptCopy.locator('strong').boundingBox()).height).toBeLessThan(60);await select.click();const menu=page.getByRole('listbox');await expect(menu).toBeVisible();await expect.poll(()=>menu.evaluate(node=>getComputedStyle(node).opacity)).toBe('1');
 expect(await menu.evaluate(node=>node.closest('[role=dialog]'))).toBeNull();const bounds=await menu.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.y).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);expect(bounds.y+bounds.height).toBeLessThanOrEqual(900);
 for(const name of ['General','Opener','Map','Travel','Action','Dialogue']){const option=page.getByRole('option',{name,exact:true});await expect(option).toBeInViewport();expect(await option.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);}
 await page.screenshot({path:testInfo.outputPath(`scene-type-menu-${width}.png`)});await page.getByRole('option',{name:'Dialogue',exact:true}).click();await expect(dialog).toBeVisible();await expect(select).toHaveText('Dialogue');await select.focus();await page.keyboard.press('Space');await expect(page.getByRole('option',{name:'Dialogue',exact:true})).toBeFocused();await page.keyboard.press('Home');await expect(page.getByRole('option',{name:'General',exact:true})).toBeFocused();await page.keyboard.press('Enter');await expect(select).toHaveText('General');await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'Cancel',exact:true}).click();await expect(dialog).not.toBeVisible();
});

for(const width of [1280,390])test(`Escape during nested dialog registration preserves its composer at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});const{submissions}=await fixture(context);
 await page.goto('https://panther.place/games/test-game/novel');
 const composer=page.getByRole('dialog',{name:'Generate chapter',exact:true,includeHidden:true});
 await page.locator('#novel > .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await composer.getByLabel('Prompt',{exact:true}).fill('Keep this unsent draft.');
 // Exercise Radix #4143 at its actual registration boundary, rather than
 // sleeping until the stale parent listener has happened to update.
 await page.evaluate(()=>{
  const escapeDuringRegistration=()=>{
   const child=document.querySelector('[role="dialog"][aria-label="Transcript review"]');
   if(!child)return;
   document.removeEventListener('dismissableLayer.update',escapeDuringRegistration);
   child.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  };
  document.addEventListener('dismissableLayer.update',escapeDuringRegistration);
 });
 await page.getByRole('button',{name:'Review First session',exact:true}).click();
 await expect(composer).toBeVisible();await expect(composer.getByLabel('Prompt',{exact:true})).toHaveValue('Keep this unsent draft.');
 expect(submissions).toEqual([]);
 const review=page.getByRole('dialog',{name:'Transcript review',exact:true});
 if(await review.isVisible())await review.getByRole('button',{name:'Close',exact:true}).click();
 await expect(page.getByRole('button',{name:'Review First session',exact:true})).toBeFocused();
});
