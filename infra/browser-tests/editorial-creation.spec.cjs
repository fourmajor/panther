const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const jwt='test.'+Buffer.from(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-editor'})).toString('base64url')+'.test';
const key=id=>`games/test-game/assets/${id}/original/raw.json`;
const transcripts=[{key:key('source-one'),name:'raw.json',kind:'raw-transcript',metadata:{title:'First session'}},{key:key('source-two'),name:'raw.json',kind:'raw-transcript',metadata:{title:'Second session'}}];
const contextAsset={key:'games/test-game/assets/context/original/lore.json',name:'lore.json',kind:'game-context',metadata:{title:'Campaign lore',category:'reference'}};
async function fixture(context){
 const submissions=[],reads=[];
 await context.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
  const fulfill=value=>route.fulfill({...value,headers:{"access-control-allow-origin":"https://panther.place"}});
  const url=new URL(route.request().url());reads.push(url.pathname);
  if(url.pathname==='/assets')return fulfill({json:{assets:url.searchParams.get('section')==='transcripts'?transcripts:url.searchParams.get('section')==='all'?[contextAsset]:[],cursor:null}});
  if(url.pathname==='/editorial-jobs'){
   if(route.request().method()==='POST'){submissions.push(route.request().postDataJSON());return fulfill({json:{jobId:'a'.repeat(64),status:'SUBMITTED'}});}
   if(!url.searchParams.has('jobId'))return fulfill({json:{jobs:[],cursor:null}});
   const creation=submissions.at(-1).creation;
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
for(const width of [1280,390])for(const target of ['novel','video'])test(`Create ${target} from selected immutable transcripts at ${width}px`,async({page,context},testInfo)=>{
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
 const submit=composer.locator('form').getByRole('button',{name:target==='novel'?'Generate chapter':'Create project',exact:true});
 await submit.scrollIntoViewIfNeeded();await expect(submit).toBeInViewport();
 await submit.click();
 await expect(composer).toContainText(target==='novel'?'Chapter ready':'Planning ready');
 expect(submissions).toHaveLength(1);
 expect(submissions[0]).toEqual({gameId:'test-game',creation:{schemaVersion:1,target,title:'The crossing',brief:'Follow the companions across the river.',sourceKeys:transcripts.map(a=>a.key),contextKeys:[contextAsset.key]}});
 expect(reads.filter(p=>p==='/assets').length).toBeGreaterThan(before);
 await page.screenshot({path:testInfo.outputPath(`editorial-${target}-${width}.png`)});
});
