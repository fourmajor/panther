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
async function fixture(context){
 const submissions=[],reads=[];
 await context.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
  const fulfill=value=>route.fulfill({...value,headers:{"access-control-allow-origin":"https://panther.place"}});
  const url=new URL(route.request().url());reads.push(url.pathname);
  if(url.pathname==='/episodes')return fulfill({json:{records:[{id:sceneRef.episodeId,name:'First episode',description:'',revision:'episode-revision',sceneIds:[sceneRef.sceneId]}],cursor:null}});
  if(url.pathname==='/scenes')return fulfill({json:{records:[{id:sceneRef.sceneId,episodeId:sceneRef.episodeId,name:'A moonlit crossing',description:'',revision:sceneRef.revision,position:0}],cursor:null}});
  if(url.pathname==='/video-collections')return fulfill({json:{collections:[],cursor:null}});
  if(url.pathname==='/characters')return fulfill({json:{characters,cursor:null}});
  if(url.pathname==='/assets')return fulfill({json:{assets:url.searchParams.get('section')==='transcripts'?transcripts:url.searchParams.get('section')==='all'?[contextAsset,internalAsset]:[],cursor:null}});
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
 return{submissions,reads};
}
for(const width of [1280,390])for(const target of ['novel'])test(`Create ${target} from selected immutable transcripts at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:900});const{submissions,reads}=await fixture(context);
 await page.goto(`https://panther.place/games/test-game/${target==='novel'?'novel':'videos'}`);
 const composer=page.locator(`#editorial-${target}-composer`);
 await expect(composer).toBeVisible();
 const before=reads.filter(p=>p==='/assets').length;
 await composer.getByRole('button',{name:target==='novel'?'Generate chapter':'Create video project',exact:true}).click();
 await composer.getByLabel('Title',{exact:true}).fill('The crossing');
 await composer.getByLabel('Direction',{exact:true}).fill('Follow the companions across the river.');
 await composer.getByLabel('First session',{exact:true}).check();
 await composer.getByLabel('Second session',{exact:true}).check();
 await composer.getByText('Add context',{exact:true}).click();
 await composer.getByLabel('Campaign lore',{exact:true}).check();
 await expect(composer.getByText('Migration provenance audit',{exact:true})).toHaveCount(0);
 const submit=composer.locator('form').getByRole('button',{name:target==='novel'?'Generate chapter':'Create project',exact:true});
 await submit.scrollIntoViewIfNeeded();await expect(submit).toBeInViewport();
 await submit.click();
 await expect(composer).toContainText(target==='novel'?'Chapter ready':'Planning ready');
 expect(submissions).toHaveLength(1);
 expect(submissions[0]).toEqual({gameId:'test-game',creation:{schemaVersion:1,target,title:'The crossing',brief:'Follow the companions across the river.',sourceKeys:transcripts.map(a=>a.key),contextKeys:[contextAsset.key]}});
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
