const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const jwt='test.'+Buffer.from(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-editor'})).toString('base64url')+'.test';
const key=id=>`games/test-game/assets/${id}/original/raw.json`;
const transcripts=[{key:key('source-one'),name:'raw.json',kind:'raw-transcript',metadata:{title:'First session'}},{key:key('source-two'),name:'raw.json',kind:'raw-transcript',metadata:{title:'Second session'}}];
const internalAsset={key:'games/test-game/assets/migration-audit/original/provenance.json',name:'provenance.json',kind:'game-context',metadata:{title:'Migration provenance audit',category:'reference'}};
const sceneRef={episodeId:'episode-one',sceneId:'scene-one',revision:'scene-revision'};
async function openScene(page){await page.getByRole('button',{name:'First episode',exact:true}).click();await page.getByRole('button',{name:'A moonlit crossing',exact:true}).click();await page.getByRole('button',{name:'Generate video',exact:true}).click();}
const characters=[{id:'lantern-guide',characterId:'lantern-guide',name:'Lantern Guide'},{id:'river-scout',characterId:'river-scout',name:'River Scout'}];
const contextAsset={key:'games/test-game/assets/context/original/lore.json',name:'lore.json',kind:'game-context',metadata:{title:'Campaign lore',category:'reference'}};
const mapAsset={key:'games/test-game/assets/atlas/original/map.png',name:'map.png',kind:'map',contentType:'image/png',metadata:{title:'Riverlands atlas',category:'reference'}};
const secondMap={...mapAsset,key:'games/test-game/assets/coast/original/map.png',metadata:{title:'Coastal atlas',category:'reference'}};
async function fixture(context,{mapScene=false,technicalSources=false}={}){
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
 await page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(composer).toBeVisible();
 await expect(composer.getByLabel('Title',{exact:true})).toHaveCount(0);
 await expect(composer.getByLabel('Direction',{exact:true})).toHaveCount(0);
 await composer.getByLabel('Prompt',{exact:true}).fill('Follow the companions across the river.');
 await expect(composer.getByText('The companions discuss crossing the river.').first()).toBeVisible();
 await composer.getByRole('button',{name:'Review First session',exact:true}).click();
 const review=page.getByRole('dialog');await expect(review).toContainText('We should cross before sunset.');await expect(review).toContainText('Morgan');
 await review.getByRole('button',{name:'Regenerate summary',exact:true}).click();
 await review.getByRole('button',{name:'Close',exact:true}).click();
 await composer.getByLabel('First session',{exact:true}).check();
 await composer.getByLabel('Second session',{exact:true}).check();
 await composer.getByText('Add context',{exact:true}).click();
 await composer.getByLabel('Campaign lore',{exact:true}).check();
 await expect(composer.getByText('Migration provenance audit',{exact:true})).toHaveCount(0);
 const submit=composer.locator('form').getByRole('button',{name:target==='novel'?'Generate chapter':'Create project',exact:true});
 await expect(submit).toBeInViewport();
 expect(await submit.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await page.screenshot({path:testInfo.outputPath(`editorial-form-${width}.png`),fullPage:true});
 await submit.click();
 await expect(composer).toContainText(target==='novel'?'Chapter ready':'Planning ready');
 expect(submissions).toHaveLength(1);
 expect(submissions[0]).toEqual({gameId:'test-game',creation:{schemaVersion:3,target,brief:'Follow the companions across the river.',sourceKeys:transcripts.map(a=>a.key),contextKeys:[contextAsset.key]}});
 expect(reads.filter(p=>p==='/assets').length).toBeGreaterThan(before);
 await page.screenshot({path:testInfo.outputPath(`editorial-${target}-${width}.png`)});
});

for(const width of [1280,390])for(const withSources of [false,true])test(`Prompt-led video with ${withSources?'optional transcripts':'characters only'} at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{submissions,reads}=await fixture(context);
 await page.goto('https://panther.place/games/test-game/videos');
 const composer=page.locator('#editorial-video-composer');
 await openScene(page);
 await expect(composer.getByLabel('Title',{exact:true})).toHaveCount(0);
 await composer.getByLabel('Lantern Guide',{exact:true}).check();
 await composer.getByLabel('River Scout',{exact:true}).check();
 await expect(composer.locator('.editorial-cast-preview')).toHaveText('Lantern Guide · River Scout');
 await composer.getByLabel('Prompt',{exact:true}).fill('A moonlit crossing');
 await expect(composer.getByText('Add context',{exact:true})).toHaveCount(0);
 await expect(composer.getByText('Migration provenance audit',{exact:true})).toHaveCount(0);
 if(withSources){await composer.getByText('Sources',{exact:true}).click();await composer.getByLabel('First session',{exact:true}).check();}
 else await expect(composer.getByLabel('First session',{exact:true})).toHaveCount(0);
 const submit=composer.locator('form').getByRole('button',{name:'Generate',exact:true});
 await expect(submit).toBeEnabled();await submit.scrollIntoViewIfNeeded();await expect(submit).toBeInViewport();
 await page.screenshot({path:testInfo.outputPath(`prompt-video-${withSources?'sources':'characters'}-${width}.png`),fullPage:true});
 await submit.click();await expect(composer).toContainText('Video plan ready');await expect(composer).toContainText('Rendering requires approval');
 expect(submissions).toEqual([{gameId:'test-game',creation:{schemaVersion:2,target:'video',brief:'A moonlit crossing',characterIds:['lantern-guide','river-scout'],sourceKeys:withSources?[transcripts[0].key]:[],contextKeys:[],sceneRef}}]);
 expect(reads.filter(p=>p==='/assets').length).toBe(withSources?2:1);
 await page.reload();await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');
});

test('video submission failure preserves the prompt and selected characters',async({page,context})=>{
 await fixture(context);await page.goto('https://panther.place/games/test-game/videos');
 const composer=page.locator('#editorial-video-composer');await openScene(page);
 await composer.getByLabel('Prompt',{exact:true}).fill('A river scout meets the lantern guide');await composer.getByLabel('Lantern Guide',{exact:true}).check();
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/editorial-jobs',route=>route.request().method()==='POST'?route.fulfill({status:503,headers:{'access-control-allow-origin':'https://panther.place'},json:{error:'Temporarily unavailable'}}):route.fallback());
 await composer.locator('form').getByRole('button',{name:'Generate',exact:true}).click();
 await expect(composer).toContainText('Temporarily unavailable');await expect(composer.getByLabel('Prompt',{exact:true})).toHaveValue('A river scout meets the lantern guide');
 await expect(composer.getByLabel('Lantern Guide',{exact:true})).toBeChecked();await expect(composer.locator('form').getByRole('button',{name:'Generate',exact:true})).toBeEnabled();
});


async function mapImage(page,context){
 const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=640;canvas.height=280;const c=canvas.getContext('2d');c.fillStyle='#e7d8b0';c.fillRect(0,0,640,280);c.strokeStyle='#8caaaf';c.lineWidth=24;c.beginPath();c.moveTo(50,0);c.bezierCurveTo(380,60,170,210,540,280);c.stroke();c.fillStyle='#40372e';c.font='24px serif';c.fillText('Riverlands',250,38);c.font='18px serif';c.fillText('Harbor',85,210);c.fillText('Hills',485,105);c.beginPath();c.arc(120,180,5,0,7);c.arc(515,80,5,0,7);c.fill();return canvas.toDataURL('image/png').split(',')[1];});
 await context.route('https://maps.example/**',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
}
for(const width of [1280,390])test(`Map image and route prompt persist before generation at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const {submissions,sceneWrites}=await fixture(context,{mapScene:true});
 await page.goto('https://panther.place/games/test-game/videos');await mapImage(page,context);await openScene(page);
 const composer=page.locator('#editorial-video-composer'),submit=composer.getByRole('button',{name:'Generate',exact:true});
 await expect(submit).toBeDisabled();await composer.getByRole('combobox',{name:'Map image',exact:true}).click();
 await expect(page.getByRole('option',{name:'Foreign map',exact:true})).toHaveCount(0);await expect(page.getByRole('option',{name:'Internal audit image',exact:true})).toHaveCount(0);await expect(page.getByRole('option',{name:'Unsupported SVG',exact:true})).toHaveCount(0);
 await page.getByRole('option',{name:'Riverlands atlas',exact:true}).click();await expect(composer.getByAltText('Selected map',{exact:true})).toBeVisible();
 await composer.getByRole('button',{name:'More images',exact:true}).click();await composer.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Coastal atlas',exact:true}).click();
 await composer.getByLabel('Prompt',{exact:true}).fill('The travelers move from Harbor to the Hills.');
 await submit.scrollIntoViewIfNeeded();await expect(submit).toBeInViewport();await page.screenshot({path:testInfo.outputPath(`map-video-${width}.png`),fullPage:true});await submit.click();
 await expect(composer).toContainText('Video plan ready');expect(sceneWrites).toHaveLength(1);expect(sceneWrites[0]).toMatchObject({type:'map',mapAssetKey:secondMap.key,expectedRevision:sceneRef.revision});
 expect(submissions).toHaveLength(1);expect(submissions[0].creation).toMatchObject({brief:'The travelers move from Harbor to the Hills.',sourceKeys:[],sceneRef:{...sceneRef,revision:'map-scene-revision'}});
 await page.reload();await expect(page.locator('#scene-work-progress')).toContainText('Video plan ready');await page.getByRole('button',{name:'Edit scene',exact:true}).click();
 await expect(page.getByRole('combobox',{name:'Scene type',exact:true})).toHaveText('Map');await expect(page.getByRole('combobox',{name:'Map image',exact:true})).toHaveText('Coastal atlas');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Scene editor can set Map type and image with only a title',async({page,context})=>{
 const{sceneWrites}=await fixture(context,{mapScene:true});await page.goto('https://panther.place/games/test-game/videos');await mapImage(page,context);await page.getByRole('button',{name:'First episode',exact:true}).click();await page.getByRole('button',{name:'A moonlit crossing',exact:true}).click();await page.getByRole('button',{name:'Edit scene',exact:true}).click();
 const editor=page.getByRole('form',{name:'Scene editor',exact:true});await editor.getByRole('combobox',{name:'Scene type',exact:true}).click();await page.getByRole('option',{name:'General',exact:true}).click();await expect(editor.getByRole('combobox',{name:'Map image',exact:true})).toBeHidden();
 await editor.getByRole('combobox',{name:'Scene type',exact:true}).click();await page.getByRole('option',{name:'Map',exact:true}).click();await editor.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Riverlands atlas',exact:true}).click();await editor.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect.poll(()=>sceneWrites.length).toBe(1);expect(sceneWrites[0]).toMatchObject({type:'map',mapAssetKey:mapAsset.key,description:''});await page.getByRole('button',{name:'Generate video',exact:true}).click();await expect(page.locator('#editorial-video-composer').getByRole('button',{name:'Generate',exact:true})).toBeEnabled();
});
test('A failed map save retains the image and prompt and retries the same operation',async({page,context})=>{
 const {submissions,sceneWrites}=await fixture(context,{mapScene:true});await page.goto('https://panther.place/games/test-game/videos');await mapImage(page,context);await openScene(page);
 const composer=page.locator('#editorial-video-composer');await composer.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Riverlands atlas',exact:true}).click();await composer.getByLabel('Prompt',{exact:true}).fill('Travel from Harbor to Hills');
 let failedBody;await page.route('https://test.execute-api.us-west-2.amazonaws.com/scenes',route=>{if(route.request().method()==='POST'&&!failedBody){failedBody=route.request().postDataJSON();return route.fulfill({status:503,headers:{'access-control-allow-origin':'https://panther.place'},json:{error:'Map save temporarily unavailable'}});}return route.fallback();});
 await composer.getByRole('button',{name:'Generate',exact:true}).click();await expect(composer).toContainText('Map save temporarily unavailable');expect(submissions).toHaveLength(0);await expect(composer.getByLabel('Prompt',{exact:true})).toHaveValue('Travel from Harbor to Hills');await expect(composer.getByRole('combobox',{name:'Map image',exact:true})).toHaveText('Riverlands atlas');
 await composer.getByRole('button',{name:'Generate',exact:true}).click();await expect(composer).toContainText('Video plan ready');expect(sceneWrites).toEqual([failedBody]);expect(submissions).toHaveLength(1);
});

for(const width of [1280,390])test(`Novel has one prompt action and supports a chapter without transcripts at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});const {submissions}=await fixture(context);
 await page.goto('https://panther.place/games/test-game/novel');
 const action=page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true});
 await expect(action).toBeVisible();await expect(action).toBeInViewport();
 expect(await action.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await expect(page.getByRole('button',{name:'Add chapter',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Write manually',exact:true})).toHaveCount(0);
 await action.click();const composer=page.locator('#editorial-novel-composer');
 await expect(composer.locator('textarea')).toHaveCount(1);await expect(composer.getByLabel('Title',{exact:true})).toHaveCount(0);
 await composer.getByLabel('Prompt',{exact:true}).fill('Describe a fictional sunrise over the harbor.');
 const generate=composer.locator('form').getByRole('button',{name:'Generate chapter',exact:true});await expect(generate).toBeEnabled();await generate.click();
 await expect(composer).toContainText('Chapter ready');
 expect(submissions[0].creation).toEqual({schemaVersion:3,target:'novel',brief:'Describe a fictional sunrise over the harbor.',sourceKeys:[],contextKeys:[]});
});

for(const width of [1280,390])test(`Transcript picker replaces technical names with reviewed summary titles at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(context,{technicalSources:true});
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter'}).click();
 const composer=page.locator('#editorial-novel-composer');await expect(composer.getByRole('checkbox',{name:'The river crossing'})).toHaveCount(2);
 await expect(composer).not.toContainText('089c592c');await expect(composer).toContainText('Recorded');await expect(composer).toContainText('Morgan');
 await composer.getByRole('button',{name:'Review The river crossing'}).first().click();await expect(page.getByRole('dialog').getByRole('heading')).toHaveText('The river crossing');
});

test('An uncertain summary regeneration retries the same operation',async({page,context})=>{
 await fixture(context);const operations=[];
 await context.route('https://test.execute-api.us-west-2.amazonaws.com/transcript-summaries**',route=>{
  if(route.request().method()==='POST'){operations.push(route.request().postDataJSON().operationId);if(operations.length===1)return route.fulfill({status:503,json:{error:'Connection interrupted'},headers:{'access-control-allow-origin':'https://panther.place'}});}
  return route.fulfill({json:{status:'READY',participants:[],summary:{summary:'The river crossing.'}},headers:{'access-control-allow-origin':'https://panther.place'}});
 });
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter'}).click();
 await page.getByRole('button',{name:'Review First session',exact:true}).click();const dialog=page.getByRole('dialog');
 await dialog.getByRole('button',{name:'Regenerate summary',exact:true}).click();await dialog.getByRole('button',{name:'Retry summary',exact:true}).click();
 expect(operations).toHaveLength(2);expect(operations[0]).toMatch(/^[a-f0-9]{32}$/);expect(operations[1]).toBe(operations[0]);
});

for(const width of [1280,390]) test(`Chapter progress shows real activity and actionable failure at ${width}px`,async({page,context})=>{
 await page.setViewportSize({width,height:900});await fixture(context);let status='RUNNING';
 await page.route('**/editorial-jobs?*',route=>{
  if(!new URL(route.request().url()).searchParams.has('jobId'))return route.fallback();
  return route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{job:{jobId:'a'.repeat(64),status,creation:{title:'A river crossing',brief:'Follow the party across the river.'},...(status==='FAILED'?{message:'The worker stopped before finishing. Start the worker to continue.'}:{})},tasks:status==='FAILED'?[]:[{stage:'novel-draft',status:'RUNNING'}]}});
 });
 await page.goto('https://panther.place/games/test-game/novel');await page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 const composer=page.locator('#editorial-novel-composer');await composer.getByLabel('Prompt',{exact:true}).fill('Follow the party across the river.');await composer.locator('form').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(composer.getByRole('progressbar',{name:'Generation stages'})).toBeVisible();await expect(composer.getByRole('progressbar')).not.toHaveAttribute('value');
 expect(await composer.getByRole('progressbar').evaluate(el=>getComputedStyle(el).animationName)).toBe('panther-pulse');
 await page.screenshot({path:test.info().outputPath(`chapter-active-progress-${width}.png`),fullPage:true});
 await composer.locator('summary').filter({hasText:/^Prompt$/}).click();await expect(composer).toContainText('Follow the party across the river.');
 status='FAILED';await expect(composer).toContainText('Generation failed',{timeout:10000});await expect(composer.getByRole('alert')).toContainText('Start the worker');
 await expect(composer.locator('summary').filter({hasText:/^Stages$/})).toHaveCount(0);await expect(composer.locator('summary').filter({hasText:'Processing details'})).toHaveCount(0);
 await expect(composer.locator('details[open]')).toContainText('Follow the party across the river.');
 await expect(page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true})).toBeVisible();
 await page.locator('#novel .explorer-heading').getByRole('button',{name:'Generate chapter',exact:true}).click();
 await expect(composer.getByLabel('Prompt',{exact:true})).toBeVisible();
 await expect(composer.getByLabel('Prompt',{exact:true})).toHaveValue('');
 await expect(composer.getByRole('alert')).toHaveCount(0);
});
