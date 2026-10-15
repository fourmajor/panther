// Real deployed HTML/JS/CSS/CSP, synthetic API/media only. No real account,
// credentials, private game assets, provider requests or production writes.
const {test,expect}=require('@playwright/test');
test.use({screenshot:'only-on-failure',trace:'retain-on-failure'});
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {origin,publicRead}=require('./safety.cjs');
const root=path.resolve(__dirname,'../../web/media-explorer');
const game='qa-campaign',prefix=`games/${game}/assets/`;
const raw=prefix+'raw/original/transcript.json',corrected=prefix+'corrected/original/transcript.json';
const plain=prefix+'text/original/transcript.txt',portrait=prefix+'portrait/original/portrait.svg';
const text='[00:00] Alex: The lantern is lit.\n[00:02] Unidentified speaker: Café — <script>window.qaExecuted=true</script>\n'+('unbroken'.repeat(40)+'\n').repeat(8)+'[02:45:00] Session ends.';
const transcript={entityType:'PlayerTranscript',players:[{id:'alex',name:'Alex'}],segments:[{start:0,end:2,playerId:'alex',text:'The lantern is lit.'},{start:2,end:4,playerId:null,text:'Who brought the map?'}]};
const asset=(key,kind,type,title)=>({key,name:key.split('/').at(-1),kind,contentType:type,size:Buffer.byteLength(text),lastModified:'2020-01-01T12:00:00Z',metadata:{title,sessionId:'qa-session',sourceKeys:[],extra:{relationshipRole:'finished'}}});
const assets=[asset(raw,'raw-transcript','application/json','Original transcript'),asset(corrected,'corrected-transcript','application/json','Corrected transcript'),asset(plain,'document','text/plain','Plain text transcript'),asset(portrait,'portrait','image/svg+xml','Synthetic portrait')];
assets[1].metadata.sourceKeys=[raw];
for(const item of assets.slice(0,2))item.transcript={schemaVersion:1,state:'available',participants:[{id:'alex',name:'Alex',segmentCount:1}],segmentCount:2,unassignedSegments:1,reviewStatus:'provisional',publicationStatus:'unknown'};

test('Deployed entry point serves the current reviewed web bytes, not an old cached edition',async({request},testInfo)=>{
 const home=await request.get(origin+'/',{timeout:30000});expect(home.ok()).toBe(true);expect(home.headers()['cache-control']).toMatch(/no-cache|no-store|max-age=0/);
 const html=await home.text(),evidence=[];
 for(const name of ['app.js','styles.css','ui-runtime.js','ui-system.css']){
  const pattern=new RegExp('/'+name.replace('.', '(?:\\.[a-f0-9]{20})?\\.')+'$');
  const match=[...html.matchAll(/(?:src|href)=["']([^"']+)["']/g)].map(m=>m[1]).find(value=>pattern.test(new URL(value,origin).pathname));
  expect(match,`Missing deployed ${name}`).toBeTruthy();const url=new URL(match,origin);expect(url.origin).toBe(origin);
  const response=await request.get(url.href,{timeout:30000});expect(response.ok()).toBe(true);expect(response.headers()['content-type']).toMatch(name.endsWith('.js')?/javascript/:/text\/css/);
  const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
  const actual=hash(await response.body()),expected=hash(fs.readFileSync(path.join(root,name)));
  evidence.push({name,url:url.pathname,actual,expected});expect(actual,`Deployed ${name} differs from reviewed source`).toBe(expected);
 }
 await testInfo.attach('release-evidence',{body:JSON.stringify(evidence,null,2),contentType:'application/json'});
});

async function fixture(page){
 const response=await page.request.get(origin+'/config.js',{timeout:30000});expect(response.ok()).toBe(true);
 const match=(await response.text()).match(/["']?apiUrl["']?\s*:\s*["']([^"']+)["']/);expect(match,'Deployed API configuration missing').toBeTruthy();
 const api=new URL(match[1]);expect(api.protocol).toBe('https:');expect(api.hostname).toMatch(/\.execute-api\.[a-z0-9-]+\.amazonaws\.com$/);
 const unexpected=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().route('**/*',route=>{
  const request=route.request(),url=new URL(request.url());
  if(publicRead(url.href,request.method(),request.isNavigationRequest()))return route.continue();
  unexpected.push({method:request.method(),origin:url.origin,path:url.pathname});return route.abort('blockedbyclient');
 });
 const headers={'access-control-allow-origin':origin,'access-control-allow-headers':'authorization,content-type','access-control-allow-methods':'GET,POST,OPTIONS'};
 await page.context().route(api.href.replace(/\/$/,'')+'/**',route=>{
  const request=route.request(),url=new URL(request.url()),key=url.searchParams.get('key');
  if(request.method()==='OPTIONS')return route.fulfill({status:204,headers});
  const games=[{id:game,name:'QA Campaign',purpose:'test'}];let body;
  if(url.pathname==='/image-links')body={images:{[portrait]:{url:origin+'/__qa__/portrait.svg'}}};
  else if(request.method()!=='GET'){unexpected.push({method:request.method(),path:url.pathname});return route.abort();}
  else if(url.pathname==='/games')body={games};
  else if(url.pathname==='/game')body={game:games[0],players:[],memberships:[],characters:[]};
  else if(url.pathname==='/assets')body={assets:url.searchParams.get('section')==='sessions'?assets.slice(0,2):assets,cursor:null};
  // Chromium's native download path can bypass Playwright request routing. Use
  // an entirely in-memory attachment; never send a fixture download to production.
  else if(url.pathname==='/object-url'){const found=assets.find(a=>a.key===key);body=found?{...found,url:url.searchParams.get('download')==='true'?'data:text/plain;charset=utf-8,'+encodeURIComponent(text):origin+'/__qa__/'+(key===portrait?'portrait.svg':'transcript.txt'),expiresIn:300}:{error:'Unknown QA asset'};}
  else if(url.pathname==='/asset-document')body={...assets.find(a=>a.key===key),document:transcript};
  else if(url.pathname==='/transcript-selection')body={selection:null};
  else if(url.pathname==='/transcript-summary')body={state:'unavailable'};
  else if(['/live-recordings','/recordings/live'].includes(url.pathname))body={recordings:[]};
  else if(url.pathname==='/notifications')body={notifications:[],unreadCount:0,cursor:null};
  else if(['/characters','/players'].includes(url.pathname))body={characters:[],players:[],cursor:null};
  else if(url.pathname==='/objects')body={prefixes:[],objects:[],nextCursor:null};
  else if(['/episodes','/scenes','/workflows'].includes(url.pathname))body={records:[],workflows:[],cursor:null};
  else if(url.pathname==='/tags')body={tags:[]};
  else if(url.pathname==='/asset-generation')body=url.searchParams.get('view')==='options'?{images:false,generationTypes:[]}:{jobs:[],cursor:null};
  else if(url.pathname==='/generation-capabilities')body={images:false,generationTypes:[]};
  else if(url.pathname==='/browser-recording/capabilities')body={canRecord:false,transcriptionAvailable:false,playbackAvailable:false,transcriptionUnavailableReason:'Recording is disabled in this read-only QA fixture.'};
  else if(url.pathname==='/transcript-summaries')body={summaries:[],state:'unavailable'};
  else {unexpected.push({method:request.method(),path:url.pathname});body={error:'Unmodelled QA read'};}
  return route.fulfill({json:body,headers});
 });
 await page.context().route(origin+'/auth/**',route=>new URL(route.request().url()).pathname==='/auth/account'?route.fulfill({json:{username:'example-qa',name:'Example QA',picture:''}}):route.fulfill({status:401,json:{error:'No real account used by deployed-shell tests'}}));
 await page.context().route(origin+'/__qa__/transcript.txt',route=>route.fulfill({contentType:'text/plain; charset=utf-8',body:text,headers:{'content-security-policy':"frame-ancestors 'none'",'x-frame-options':'DENY'}}));
 await page.context().route(origin+'/__qa__/portrait.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#246"/><text x="25" y="100" fill="white">Synthetic portrait</text></svg>'}));
 await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-qa'}))+'.test'})));
 return {unexpected,errors};
}

for(const width of [1280,390]){
 test(`Deployed plain-text reader is readable and inert at ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});const state=await fixture(page);
  await page.goto(origin+`/games/${game}/assets?asset=`+encodeURIComponent(plain));
  const reader=page.locator('#preview-body .plain-text-asset');await expect(reader).toHaveText(text);await expect(reader).toBeVisible();await reader.focus();await expect(reader).toBeFocused();
  expect(await reader.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);await expect(page.locator('#preview-body iframe')).toHaveCount(0);expect(await page.evaluate(()=>window.qaExecuted)).toBeUndefined();
  await expect(page.locator('#asset-download')).toBeInViewport();await page.screenshot({path:testInfo.outputPath(`deployed-text-${width}.png`),animations:'disabled'});
  const pending=page.waitForEvent('download');await page.locator('#asset-download').click();const download=await pending;expect(fs.readFileSync(await download.path(),'utf8')).toBe(text);
  await page.getByRole('button',{name:'Close preview',exact:true}).click();await expect(reader).not.toBeVisible();expect(state.errors).toEqual([]);expect(state.unexpected).toEqual([]);
 });
 test(`Deployed Sessions exposes a readable corrected transcript at ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});const state=await fixture(page);await page.goto(origin+`/games/${game}/sessions`);
  const link=page.getByRole('link',{name:'Corrected transcript',exact:true});await expect(link).toBeInViewport();await link.click();await expect(page.locator('.transcript-segment')).toHaveCount(2);await expect(page.locator('.transcript-segment').first()).toContainText('The lantern is lit.');
  await expect(page.getByRole('button',{name:'Download text',exact:true})).toBeVisible();await page.screenshot({path:testInfo.outputPath(`deployed-session-${width}.png`),animations:'disabled'});expect(state.errors).toEqual([]);expect(state.unexpected).toEqual([]);
 });
 test(`Deployed image preview decodes actual pixels at ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});const state=await fixture(page);await page.goto(origin+`/games/${game}/assets?asset=`+encodeURIComponent(portrait));
  const image=page.locator('#preview-body img');await expect(image).toBeVisible();await expect.poll(()=>image.evaluate(el=>el.complete&&el.naturalWidth===320)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`deployed-image-${width}.png`),animations:'disabled'});expect(state.errors).toEqual([]);expect(state.unexpected).toEqual([]);
 });
}
