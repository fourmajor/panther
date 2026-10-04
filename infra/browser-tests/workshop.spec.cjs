const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH}=require('../dist/lib/panther-media-explorer-stack');

function sample(id,kind,status,title,stages,extra={}) {
  const common=stages.filter(s=>!s.id.startsWith('novel-')&&!s.id.startsWith('video-')).map(s=>s.id);
  const lanes=kind==='editorial'?[
    {id:'shared',label:'Shared context & correction',stageIds:common},
    ...['novel','video'].map(prefix=>({id:prefix,label:prefix==='novel'?'Novel adaptation':'Screen planning',stageIds:stages.filter(s=>s.id.startsWith(prefix+'-')).map(s=>s.id)})),
  ].filter(l=>l.stageIds.length):[{id:'sequence',label:'Reported steps',stageIds:stages.map(s=>s.id)}];
  const edges=lanes.flatMap(l=>l.stageIds.slice(1).map((to,i)=>({from:l.stageIds[i],to})));
  if(kind==='editorial'&&common.length)for(const l of lanes.filter(l=>l.id!=='shared'))edges.push({from:common.at(-1),to:l.stageIds[0]});
  const flow={schemaVersion:1,mode:kind==='editorial'?'branched':'sequence',lanes,edges,note:'Arrows show dependencies, not time remaining.'};
  return {schemaVersion:1,id:kind+'~'+id,kind,gameId:'synthetic-game',title,status,createdAt:Date.now()/1000,observedAt:Date.now()/1000,source:'durable-job',note:'Screen planning stops before paid generation.',stages,flow,activeStages:stages.filter(s=>!['done','pending'].includes(s.status)),totalStages:stages.length,completedStages:stages.filter(s=>s.status==='done').length,...extra};
}
async function fixture(page) {
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-reader'}))+'.test'})));
  const running=sample('a'.repeat(64),'editorial','running','The Lanterns at Dawn',[
    {id:'context',label:'Context selection',status:'done'},
    {id:'video-screenplay',label:'Writing the screenplay',status:'running',leaseUntil:Date.now()/1000+600,attempts:2},
    {id:'video-preflight',label:'Preflight review',status:'pending'},
  ]);
  const completed=sample('b'.repeat(64),'playback','done','Continuous session audio',[{id:'assembly',label:'Assemble and verify',status:'done'}]);
  const stale=sample('c'.repeat(64),'video-production','running','Harbor film finishing',[{id:'sound',label:'Mixing sound',status:'running'}],{source:'local-worker',reportedAt:Date.now()/1000-500});
  const failed=sample('d'.repeat(64),'model','failed','Model reconstruction',[{id:'model',label:'Reconstruction and review',status:'failed'}]);
  const state={jobs:[running,completed,stale,failed],reads:[],error:false,next:true};
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
    const url=new URL(route.request().url()),p=url.pathname;state.reads.push(url);
    const headers={'access-control-allow-origin':'https://panther.place'};
    if(p==='/workflows') {
      if(state.error)return route.fulfill({status:503,json:{error:'Workflow history is being indexed'},headers});
      const id=url.searchParams.get('id');
      if(id)return route.fulfill({json:{workflow:state.jobs.find(j=>j.id===id)},headers});
      if(url.searchParams.get('view')==='types') {
        const types=[...new Set(state.jobs.map(j=>j.kind))].map(kind=>{const rows=state.jobs.filter(j=>j.kind===kind);return {id:kind,name:({'session-finalization':'Session finalization',editorial:'Story & screen planning',playback:'Audio assembly',model:'3D modeling','asset-generation':'Asset generation','video-production':'Video finishing'})[kind],total:rows.length,successful:rows.filter(j=>j.status==='done').length,failed:rows.filter(j=>j.status==='failed').length,latestRunAt:Math.max(...rows.map(j=>j.createdAt))};});
        return route.fulfill({json:{types},headers});
      }
      const kind=url.searchParams.get('type');const rows=state.jobs.filter(j=>!kind||j.kind===kind);
      return route.fulfill({json:{workflows:url.searchParams.get('cursor')?[sample('e'.repeat(64),kind||'model','queued','Another run',[{id:'build',label:'Prepare',status:'queued'}])]:rows,cursor:!url.searchParams.get('cursor')&&state.next?'next-page':null},headers});
    }
    const game={id:'synthetic-game',name:'The Lantern Expedition',purpose:'campaign',ruleset:null};
    const bodies={'/games':{games:[game]},'/game':{game,players:[],memberships:[],characters:[],canEditGame:false},'/characters':{characters:[]},'/recordings/live':{recordings:[]},'/objects':{objects:[],prefixes:[],cursor:null}};
    return route.fulfill({json:bodies[p]||{},headers});
  });
  await page.route('https://panther.place/**',route=>{
    const p=new URL(route.request().url()).pathname;
    if(p==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file=p==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(p)?p.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return state;
}


for(const width of [1280,390]) test(`Workflow type hierarchy, exact totals and durable navigation at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});const state=await fixture(page);
 await page.goto('https://panther.place/games/synthetic-game/workflows');
 await expect(page.locator('.workflow-type')).toHaveCount(4);
 await expect(page.locator('.workflow-run')).toHaveCount(0);
 const type=page.locator('.workflow-type').filter({hasText:'Story & screen planning'});
 await expect(type).toContainText('Successful');await expect(type).toContainText('Failed');
 const box=await type.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width);
 expect(await type.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.right-15,r.top+15));})).toBe(true);
 await type.focus();await page.keyboard.press('Enter');await expect(page).toHaveURL(/workflows\/editorial$/);
 await expect(page.locator('.workflow-run')).toHaveCount(1);
 await expect(page.locator('.workflow-run')).toContainText('The Lanterns at Dawn');
 await page.getByRole('button',{name:'Load more',exact:true}).click();await expect(page.locator('.workflow-run')).toHaveCount(2);
 await page.locator('.workflow-run').first().click();await expect(page).toHaveURL(/workflows\/editorial\/editorial~a+$/);
 await expect(page.locator('.workflow-stages li')).toHaveCount(3);await expect(page.locator('.workflow-detail')).toContainText('Writing the screenplay');
 await page.reload();await expect(page.locator('.workflow-stages li')).toHaveCount(3);
 await page.locator('.workflow-back').click();await expect(page).toHaveURL(/workflows\/editorial$/);
 await page.locator('.workflow-back').click();await expect(page.locator('.workflow-type')).toHaveCount(4);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:test.info().outputPath(`workflow-types-${width}.png`),fullPage:true});
});
test('Incomplete type aggregates show an honest error instead of partial totals',async({page})=>{
 const state=await fixture(page);state.error=true;
 await page.goto('https://panther.place/games/synthetic-game/workflows');
 await expect(page.getByRole('alert')).toContainText('Workflow history is being indexed');
 await expect(page.locator('.workflow-type')).toHaveCount(0);
});

for(const width of [1280,390])test(`Compact workflow rows and zoomable output keep a single run status at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});const state=await fixture(page);
 const key='games/synthetic-game/content/shared/images/map/original/map.png';
 const output=sample('f'.repeat(64),'asset-generation','done','The riverside map',[{id:'generate',label:'Asset generation',status:'done',outputKey:key}]);
 state.jobs=[output];
 const imageUrl='https://synthetic.example/map.png';
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/object-url*',route=>route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{key,url:imageUrl,contentType:'image/png',size:250,metadata:{title:'The riverside map'}}}));
 await page.route(imageUrl,route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400"><rect width="640" height="400" fill="#304c42"/><path d="M210 0Q400 180 250 400" fill="none" stroke="#84b4c4" stroke-width="65"/><circle cx="470" cy="220" r="20" fill="#e9ba59"/></svg>'}));
 await page.goto('https://panther.place/games/synthetic-game/workflows');
 const type=page.locator('.workflow-type');await expect(type).toHaveCount(1);
 await expect(type.locator('svg.lucide-chevron-right')).toHaveCount(1);await expect(type.locator('svg.lucide-arrow-up-right')).toHaveCount(0);
 const row=await type.boundingBox();expect(row.height).toBeLessThan(width<600?120:95);
 await type.click();const run=page.locator('.workflow-run');await expect(run).toHaveCount(1);
 await expect(run.locator('img')).toHaveAttribute('src',imageUrl);await expect(run.locator('svg.lucide-chevron-right')).toHaveCount(1);
 await run.click();const detail=page.locator('.workflow-detail');
 await expect(detail.getByText('Complete',{exact:true})).toHaveCount(1);await expect(detail.locator('.workflow-stages')).toHaveCount(0);
 await expect(detail.getByText('Asset generation',{exact:true})).toHaveCount(1);await expect(detail.getByRole('button',{name:'View output',exact:true})).toHaveCount(0);
 const thumbnail=detail.getByRole('button',{name:'Preview Output',exact:true});await expect(thumbnail).toBeInViewport();await expect(thumbnail.locator('img')).toHaveAttribute('src',imageUrl);
 const bounds=await thumbnail.boundingBox();expect(bounds.width).toBeGreaterThan(150);expect(bounds.height).toBeGreaterThan(100);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
 expect(await thumbnail.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await page.screenshot({path:test.info().outputPath(`workflow-output-${width}.png`),fullPage:true});
 await thumbnail.focus();await page.keyboard.press('Enter');await expect(page.locator('#preview-dialog')).toBeVisible();await expect(page.locator('#preview-body img')).toHaveAttribute('src',imageUrl);
 await page.keyboard.press('Escape');await expect(page.locator('#preview-dialog')).not.toBeVisible();await expect(detail).toBeVisible();await expect(page).toHaveURL(/workflows\/asset-generation\/asset-generation~f+$/);
});

test('A single active stage retains real animated progress without duplicating its status badge',async({page})=>{
 const state=await fixture(page);const job=sample('9'.repeat(64),'asset-generation','running','Riverside illustration',[{id:'generate',label:'Generating illustration',status:'running'}]);state.jobs=[job];
 await page.goto(`https://panther.place/games/synthetic-game/workflows/asset-generation/${job.id}`);
 const detail=page.locator('.workflow-detail');await expect(detail.getByText('Running',{exact:true})).toHaveCount(1);
 await expect(detail.locator('.workflow-current-stage')).toHaveText('Generating illustration');
 await expect(detail.locator('.workflow-stage-meter')).toHaveAttribute('aria-label','0 of 1 stages complete');
 expect(await detail.locator('.workflow-stage-meter span').evaluate(el=>getComputedStyle(el).animationName)).toBe('pulse');
 job.status='done';job.stages[0].status='done';job.completedStages=1;await page.reload();
 await expect(detail.getByText('Complete',{exact:true})).toHaveCount(1);await expect(detail.locator('.workflow-stage-meter')).toHaveCount(0);await expect(detail.locator('.workflow-current-stage')).toHaveCount(0);
});

test('Completed screen planning remains inspectable when the independent novel branch fails',async({page})=>{
 const state=await fixture(page);
 const job=sample('8'.repeat(64),'editorial','done','Session screen planning',[
   {id:'context',label:'Context selection',status:'done'},
   {id:'novel-line-copyedit',label:'Line and copyedit',status:'failed',attempts:3},
   {id:'video-storyboards',label:'Storyboards',status:'done'},
   {id:'video-preflight',label:'Preflight review',status:'done'},
 ],{workflowVersion:5,sourceStatus:'READY_FOR_VIDEO_DISCUSSION'});
 state.jobs=[job];
 await page.goto(`https://panther.place/games/synthetic-game/workflows/editorial/${job.id}`);
 const detail=page.locator('.workflow-detail');
 await expect(detail).toContainText('Line and copyedit');
 await expect(detail).toContainText('Failed');
 await expect(detail).toContainText('Storyboards');
 await expect(detail).toContainText('Preflight review');
 await expect(detail).toContainText('Screen planning stops before paid generation.');
 await expect(detail.getByRole('button',{name:/generate video/i})).toHaveCount(0);
});
