const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH}=require('../dist/lib/panther-media-explorer-stack');
const origin='https://panther.place',api='https://test.execute-api.us-west-2.amazonaws.com';
const key='games/test-game/assets/movie-plan/original/plan.json',frame='games/test-game/assets/frame/original/frame.svg';
const headers={'access-control-allow-origin':origin,'access-control-allow-headers':'authorization,content-type','access-control-allow-methods':'GET,POST,OPTIONS'};
async function fixture(page,{blocked=false,conflict=false}={}) {
  const writes=[];
  const plan={schemaVersion:1,entityType:'MovieReviewPlan',gameId:'test-game',projectId:'lantern',revisionId:'draft-01',sessionId:'session-one',title:'The House Beneath the Tide',summary:'A locked gate. An impossible light. Two companions discover that the abandoned lighthouse is not as empty as it seems.',
    screenplay:'## INT. LIGHTHOUSE — NIGHT\n\nSalt water drips from the ceiling. Mira lifts her lantern.\n\n**MIRA**\n\nSomeone left the light on.\n\n<svg onload="window.attacked=true">',
    sourceKeys:[frame],characters:[{id:'mira',name:'Mira Vale',portraitKey:frame}],budget:{capUsd:'10.00',currency:'USD',notes:'The ceiling includes retries. No automatic generation.'},
    shots:[{id:'gate',title:'The last light',description:'Mira stands in the doorway, lantern raised. A pale light answers from the far end of the hall.',camera:'Slow push-in. Eye-level, 35 mm. Hold the doorway on screen left.',continuity:'Lantern stays in the right hand. Wet blue stone, warm amber practical light.',model:'Veo 3.1 Fast',modelReason:'Atmospheric establishing shot.',durationSeconds:8,characterIds:['mira'],referenceKeys:[frame],frameKey:blocked?null:frame,costUsd:blocked?null:'0.80',warnings:blocked?[{severity:'blocker',message:'Character identity needs checking.'}]:[]},
      {id:'answer',title:'Someone is still here',description:'A close-up on Mira as the realization lands. She does not turn away from the light.',camera:'Locked close-up, 85 mm. Leave room in her eyeline.',continuity:'Same wet costume and lantern position.',dialogue:'MIRA: Someone left the light on.',model:'MiniMax H3 Max',modelReason:'Character performance and dialogue.',durationSeconds:8,characterIds:['mira'],referenceKeys:[frame],frameKey:frame,costUsd:'0.32',warnings:[{severity:'note',message:'Dialogue is adapted, not quoted from the recording.'}]}]};
  let review=null;
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-operator'}))+'.test'})));
  await page.route(`${origin}/**`,route=>{
    const p=new URL(route.request().url()).pathname;
    if(p==='/config.js') return route.fulfill({contentType:'application/javascript',body:`window.PANTHER_CONFIG={apiUrl:'${api}',clientId:'test',cognitoDomain:'https://test.amazoncognito.com',redirectUri:'${origin}/'};`});
    const file=p==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css'].includes(p)?p.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('https://images.example/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><defs><radialGradient id="a"><stop stop-color="#c29554"/><stop offset="1" stop-color="#263b40"/></radialGradient></defs><rect width="960" height="540" fill="#17252b"/><path d="M300 500V120Q480 -70 660 120V500" fill="url(#a)"/><path d="M350 500V170Q480 35 610 170V500" fill="#101e23"/><circle cx="460" cy="275" r="22" fill="#e2bf77"/><path d="M465 500V330L505 305L530 500" fill="#344c51"/><path d="M0 500H960" stroke="#9b9271" stroke-width="4"/></svg>'}));
  await page.route(`${api}/**`,route=>{
    const u=new URL(route.request().url());
    if(route.request().method()==='OPTIONS') return route.fulfill({status:204,headers});
    const games=[{id:'test-game',name:'The Saltwater Campaign',purpose:'campaign'},{id:'other-game',name:'Other game',purpose:'test'}];
    let body={};
    if(u.pathname==='/games') body={games};
    if(u.pathname==='/game') body={game:games.find(g=>g.id===u.searchParams.get('gameId')),players:[],characters:[],memberships:[]};
    if(u.pathname==='/assets') body={assets:u.searchParams.get('gameId')==='test-game'?[{key,kind:'movie-review-plan',name:'plan.json',contentType:'application/json',lastModified:'2026-01-01T00:00:00Z',metadata:{title:plan.title,description:plan.summary}}]:[]};
    if(u.pathname==='/movie-review') {
      if(route.request().method()==='POST') {
        writes.push(route.request().postDataJSON());
        if(conflict) return route.fulfill({status:409,headers,json:{error:'Plan or review changed. Refresh before saving.'}});
        review={id:'saved-review',action:writes.at(-1).action,createdAt:1700000000,comments:writes.at(-1).comments}; body={review,generationStarted:false};
      } else body={plan,sha256:'a'.repeat(64),review,canApprove:true,readiness:{knownCostUsd:blocked?'0.32':'1.12',costComplete:!blocked,durationSeconds:16,ready:!blocked,blockers:blocked?['gate: starting composition has not been prepared','gate: generation cost is not quoted','gate: Character identity needs checking.']:[]}};
    }
    if(u.pathname==='/object-url') body={url:'https://images.example/frame.svg',contentType:'image/svg+xml'};
    return route.fulfill({headers,json:body});
  });
  return writes;
}
async function open(page) {await page.goto(`${origin}/games/test-game/videos?project=${encodeURIComponent(key)}`);await expect(page.getByRole('heading',{name:'The House Beneath the Tide',exact:true})).toBeVisible();}
for(const width of [1440,390]) test(`professional review layout, screenplay and explicit approval at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); const writes=await fixture(page); const errors=[]; page.on('pageerror',e=>errors.push(e.message)); await open(page);
  await expect(page.locator('.movie-frame img')).toHaveCount(2);
  await expect(page.locator('.movie-budget')).toContainText('$1.12');
  await expect(page.getByRole('button',{name:'Review approval…'})).toBeDisabled();
  await page.screenshot({path:test.info().outputPath(`movie-storyboard-${width}.png`),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByLabel('I have reviewed this shot').check();
  await page.getByRole('button',{name:'Inspect shot 2: Someone is still here'}).click();
  await page.getByLabel('I have reviewed this shot').check();
  await page.getByRole('button',{name:'Screenplay',exact:true}).click();
  await expect(page.getByRole('article',{name:'Movie screenplay'})).toContainText('Someone left the light on.');
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  await page.screenshot({path:test.info().outputPath(`movie-screenplay-${width}.png`),fullPage:true});
  const approve=page.getByRole('button',{name:'Review approval…'}); await approve.scrollIntoViewIfNeeded();
  expect(await approve.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await approve.click();
  await expect(page.getByRole('button',{name:'Approve this plan',exact:true})).toBeDisabled();
  await page.getByLabel('I approve this exact plan and budget ceiling.').check(); await page.getByRole('button',{name:'Approve this plan',exact:true}).click();
  await expect(page.locator('.movie-feedback-status')).toContainText('Review saved');
  expect(writes).toHaveLength(1); expect(writes[0].action).toBe('approved'); expect(writes[0].capUsd).toBe('10.00'); expect(writes[0].reviewedShotIds).toEqual(['gate','answer']);
  await page.reload(); await expect(page.locator('.movie-budget')).toContainText('This revision was approved');
  await page.getByRole('combobox',{name:'Game',exact:true}).selectOption('other-game'); await expect(page.locator('#movie-workspace')).not.toContainText('The House Beneath the Tide');
  expect(errors).toEqual([]);
});
test('blocked plan saves shot feedback, never pretends missing prices are zero',async({page})=>{
  const writes=await fixture(page,{blocked:true}); await open(page);
  await expect(page.locator('.movie-cost')).toContainText('Unquoted'); await expect(page.locator('.movie-frame').first()).toContainText('Composition to be prepared');
  await page.getByLabel('Request a change to this shot').fill('Keep the lantern in her right hand.');
  await page.getByRole('button',{name:'Save change requests'}).click(); await expect(page.locator('.movie-feedback-status')).toContainText('Review saved');
  expect(writes[0].comments).toEqual([{shotId:'gate',text:'Keep the lantern in her right hand.'}]);
  await expect(page.getByRole('button',{name:'Review approval…'})).toBeDisabled();
});
test('conflicts retain unsaved feedback and do not show success',async({page})=>{
  await fixture(page,{conflict:true});await open(page); await page.getByLabel('Request a change to this shot').fill('Change this shot.');
  await page.getByRole('button',{name:'Save change requests'}).click();await expect(page.locator('.movie-feedback-status')).toContainText('Refresh before saving');
  await expect(page.getByLabel('Request a change to this shot')).toHaveValue('Change this shot.');
});
