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
  return {schemaVersion:1,id:kind+'~'+id,kind,gameId:'synthetic-game',title,status,createdAt:100,observedAt:Date.now()/1000,source:'durable-job',note:'Screen planning stops before paid generation.',stages,flow,activeStages:stages.filter(s=>!['done','pending'].includes(s.status)),totalStages:stages.length,completedStages:stages.filter(s=>s.status==='done').length,...extra};
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
      return route.fulfill({json:{workflows:url.searchParams.get('cursor')?[sample('e'.repeat(64),'model','queued','Another workbench',[{id:'build',label:'Waiting for references',status:'queued'}])]:state.jobs,cursor:!url.searchParams.get('cursor')&&state.next?'next-page':null},headers});
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

for(const width of [1440,390]) for(const design of ['studio','chronicle','cinema','mission','poster','field']) {
  test(`Workshop workbenches in ${design} at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:1000});
    await fixture(page);
    await page.goto(`https://panther.place/games/synthetic-game/workflows?ui=${design}`);
    await expect(page.locator('.workshop-card')).toHaveCount(4);
    await expect(page.locator('.workshop-group')).toHaveCount(6);
    await expect(page.locator('.workshop-group[data-kind=editorial]')).toContainText('The Lanterns at Dawn');
    await expect(page.locator('.workshop-group[data-kind=playback]')).toContainText('Continuous session audio');
    await expect(page.locator('#primary-nav a[aria-current]')).toHaveText('Workflows');
    await expect(page.locator('.workshop-card .is-working')).toHaveCount(1);
    await expect(page.locator('#workshop')).toContainText('Local worker signal lost');
    await expect(page.locator('#workshop')).toContainText('1 of 3 stages complete');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    const button=page.locator('#workshop-refresh');await expect(button).toBeInViewport();
    expect(await button.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
    await page.screenshot({path:test.info().outputPath(`workshop-${design}-${width}.png`),fullPage:true});
  });
}

for(const width of [1440,390]) test(`Workflow detail, filters and pagination at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1000});await fixture(page);
  await page.goto('https://panther.place/games/synthetic-game/workflows');
  await expect(page.locator('.workshop-card')).toHaveCount(4);
  await page.locator('[data-filter=working]').click();await expect(page.locator('.workshop-card')).toHaveCount(1);
  await page.locator('.workshop-card').click();
  await expect(page.locator('#workshop-detail')).toBeVisible();
  await expect(page.locator('.workshop-stages li')).toHaveCount(3);
  await expect(page.locator('.workshop-flowchart')).toBeVisible();
  await expect(page.locator('.workshop-flow-lines path')).toHaveCount(4);
  await expect(page.locator('.workshop-stages .is-working')).toHaveCount(1);
  await expect(page.locator('#workshop-detail')).toContainText('Attempt 2');
  await expect(page.locator('#workshop-detail')).toContainText('Preflight review');
  await expect(page.locator('#workshop-detail')).toContainText('Not started');
  await page.screenshot({path:test.info().outputPath(`workshop-detail-${width}.png`),fullPage:true});
  await page.reload();await expect(page.locator('.workshop-stages li')).toHaveCount(3);
  await page.locator('.workshop-back').click();await page.locator('[data-filter=all]').click();
  await page.locator('#workshop-more').click();await expect(page.locator('.workshop-card')).toHaveCount(5);
  await expect(page.locator('#workshop-more')).toBeHidden();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('Live polling stays fresh, stops on navigation, and respects reduced motion',async({page})=>{
  await page.clock.install();await page.emulateMedia({reducedMotion:'reduce'});const state=await fixture(page);state.next=false;
  await page.goto('https://panther.place/games/synthetic-game/workflows');
  await expect(page.locator('.workshop-card')).toHaveCount(4);
  await page.locator('.workshop-group[data-kind=playback] > summary').click();
  await expect(page.locator('.workshop-group[data-kind=playback] .workshop-card')).toBeHidden();
  expect(await page.locator('.workshop-card .is-working .pixel-cat').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  state.jobs[0].stages[1].status='done';state.jobs[0].completedStages=2;state.jobs[0].activeStages=[];
  await page.clock.fastForward(16000);
  await expect(page.locator('#workshop')).toContainText('2 of 3 stages complete');
  await expect(page.locator('.workshop-group[data-kind=playback] .workshop-card')).toBeHidden();
  expect(state.reads.filter(u=>u.pathname==='/workflows').length).toBeGreaterThan(1);
  await page.locator('#primary-nav').getByRole('link',{name:'Characters',exact:true}).click();
  await expect(page.locator('#workshop')).toBeHidden();
  const count=state.reads.filter(u=>u.pathname==='/workflows').length;
  await page.clock.fastForward(32000);
  expect(state.reads.filter(u=>u.pathname==='/workflows').length).toBe(count);
});

for(const width of [1440,390]) test(`Parallel adaptation flowchart at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1000});const state=await fixture(page);
  const job=sample('f'.repeat(64),'editorial','running','Two paths from one transcript',[
    {id:'context',label:'Context',status:'done'},
    {id:'corrected-transcript',label:'Corrected transcript',status:'done'},
    {id:'novel-draft',label:'Novel draft',status:'running',leaseUntil:Date.now()/1000+600},
    {id:'novel-proof',label:'Novel proof',status:'pending'},
    {id:'video-screenplay',label:'Screenplay',status:'running',leaseUntil:Date.now()/1000+600},
    {id:'video-preflight',label:'Preflight',status:'pending'},
  ]);state.jobs.push(job);
  await page.goto('https://panther.place/games/synthetic-game/workflows?workflow='+job.id);
  await expect(page.locator('.workshop-flow-lane')).toHaveCount(3);
  await expect(page.locator('.workshop-flow-lines path')).toHaveCount(10);
  await expect(page.locator('.workshop-stages .is-working')).toHaveCount(2);
  const positions=await page.locator('.workshop-flow-lane').evaluateAll(lanes=>lanes.map(l=>{const r=l.getBoundingClientRect();return {top:r.top,left:r.left,width:r.width};}));
  if(width>600) {expect(Math.abs(positions[1].top-positions[2].top)).toBeLessThan(2);expect(positions[2].left).toBeGreaterThan(positions[1].left);}
  else expect(positions[2].top).toBeGreaterThan(positions[1].top);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`flowchart-parallel-${width}.png`),fullPage:true});
});

test('Incomplete history and refresh failures are visible, never a fake empty library',async({page})=>{
  const state=await fixture(page);state.error=true;
  await page.goto('https://panther.place/games/synthetic-game/workflows');
  await expect(page.locator('#workshop-health')).toContainText('being indexed');
  await expect(page.locator('.workshop-empty')).toHaveCount(0);
  state.error=false;await page.locator('#workshop-refresh').click();await expect(page.locator('.workshop-card')).toHaveCount(4);
  state.error=true;await page.locator('#workshop-refresh').click();
  await expect(page.locator('#workshop-health')).toContainText('out of date');
  await expect(page.locator('.workshop-card')).toHaveCount(4);
});
