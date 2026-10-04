const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH} = require('../dist/lib/panther-media-explorer-stack');

async function fixture(page) {
  await page.addInitScript(() => sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-member'}))+'.test'})));
  const reads=[];
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    reads.push(pathname);
    const game={id:'synthetic-game',name:'The Lantern Expedition',purpose:'campaign',ruleset:'Synthetic Rules',visualStyle:'photorealistic'};
    const bodies={
      '/games':{games:[game]},
      '/game':{game,canEditGame:true,gameSettings:{description:'A fictional campaign for interface testing.',descriptionRevision:null},visualStyles:[{id:'photorealistic',label:'Photorealistic'}],players:[{id:'person',name:'Example Player'}],characters:[],memberships:[{playerId:'person',role:'player',characterIds:[]}]},
      '/dashboard-recent':{complete:true,groups:{characters:[],transcripts:[],videos:[],chapters:[]},counts:{characters:0,transcripts:0,videos:0,chapters:0}},
      '/recordings/live':{recordings:[]},
      '/characters':{characters:[],cursor:null},
      '/objects':{prefixes:[],objects:[],cursor:null},
      '/assets':{assets:[{key:'games/synthetic-game/assets/review/original/plan.json',kind:'movie-review-plan',name:'plan.json',metadata:{title:'Last session storyboard',sessionId:'synthetic-session'}}],cursor:null},
      '/workflows':{workflows:[],cursor:null},
    };
    await route.fulfill({json:bodies[pathname] || {},headers:{'access-control-allow-origin':'https://panther.place'}});
  });
  await page.route('https://panther.place/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return reads;
}

async function accessible(locator, width) {
  await expect(locator).toBeVisible();
  await expect(locator).toBeInViewport();
  const box=await locator.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(-1);
  expect(box.x+box.width).toBeLessThanOrEqual(width+1);
  expect(await locator.evaluate(element=>{const r=element.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return hit===element||element.contains(hit);})).toBe(true);
}


for(const width of [1440,390])test(`First paint uses the stable Panther theme without exploration scaffolding at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});const errors=[];page.on('pageerror',error=>errors.push(error.message));const reads=await fixture(page);
 await page.addInitScript(()=>{localStorage.setItem('panther.interface.v1','poster');window.bootFrames=[];const sample=()=>{if(document.body){const header=document.querySelector('.masthead'),welcome=document.getElementById('welcome');window.bootFrames.push({atlas:document.body.innerText.includes('Design Atlas'),welcome:welcome&&!welcome.hidden,header:header?.getBoundingClientRect().height,background:getComputedStyle(document.documentElement).backgroundColor});}if(window.bootFrames.length<150)requestAnimationFrame(sample);};requestAnimationFrame(sample);});
 let release;const held=new Promise(resolve=>release=resolve);await page.route('https://panther.place/ui-runtime.js',async route=>{await held;await route.fulfill({body:fs.readFileSync(path.join(__dirname,'../../web/media-explorer/ui-runtime.js')),contentType:'application/javascript'});});
 await page.goto('https://panther.place/games/synthetic-game/dashboard?ui=poster',{waitUntil:'commit'});
 await expect(page.locator('.masthead')).toBeVisible();await expect(page.locator('#welcome')).toBeHidden();await expect(page.locator('#style-preview-dialog')).toBeHidden();await expect(page.getByText('Design Atlas',{exact:true})).toHaveCount(0);
 await expect(page.locator('#primary-nav')).toHaveCSS('visibility','hidden');const pending=await page.locator('.masthead').boundingBox();await page.screenshot({path:test.info().outputPath(`first-paint-${width}.png`),fullPage:true});release();
 await expect(page.locator('#dashboard-name')).toHaveText('The Lantern Expedition');await expect(page.locator('html')).not.toHaveAttribute('data-booting','');
 const ready=await page.locator('.masthead').boundingBox();expect(Math.abs(ready.height-pending.height)).toBeLessThan(4);await expect(page.locator('html')).not.toHaveAttribute('data-interface','poster');
 const frames=await page.evaluate(()=>window.bootFrames);expect(frames.length).toBeGreaterThan(0);expect(frames.some(frame=>frame.atlas||frame.welcome)).toBe(false);expect(frames.every(frame=>frame.background==='rgb(17, 17, 15)')).toBe(true);
 for(const link of await page.locator('#primary-nav a').all())await accessible(link,width);
 const before=reads.filter(path=>path==='/game').length;await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();await expect(page.locator('#game-name')).toHaveValue('The Lantern Expedition');await page.locator('#game-description').fill('An unsaved fictional setting.');
 await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).focus();await page.keyboard.press('Shift+D');await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.locator('#game-description')).toHaveValue('An unsaved fictional setting.');expect(reads.filter(path=>path==='/game').length).toBe(before);expect(errors).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:test.info().outputPath(`stable-panther-${width}.png`),fullPage:true});

});

test('storyboard approval doorway is game-scoped and does not generate or approve anything',async({page})=>{
  const reads=await fixture(page);
  await page.goto('https://panther.place/games/synthetic-game/dashboard');
  const entry=page.locator('#storyboard-entry');
  await expect(entry).toHaveAttribute('href','/games/synthetic-game/episodes?review=1');
  await entry.click();
  await expect(page.locator('#video-approval-inbox')).toContainText('Last session storyboard');
  await expect(page.locator('#video-approval-inbox .approval-card a')).toHaveAttribute('href',/episodes\?project=games%2Fsynthetic-game/);
  expect(reads.every(path=>!path.includes('generate')&&!path.includes('submit'))).toBe(true);
});

test('failed session preparation is clearly distinct from an approvable storyboard',async({page})=>{
  await fixture(page);
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/workflows**',route=>route.fulfill({json:{workflows:[{id:'editorial~synthetic-run',kind:'editorial',gameId:'synthetic-game',sessionId:'latest-session',status:'failed',createdAt:100}],cursor:null},headers:{'access-control-allow-origin':'https://panther.place'}}));
  await page.goto('https://panther.place/games/synthetic-game/dashboard');
  const row=page.locator('.approval-preparation-row');
  await expect(row).toContainText('Session latest-session');
  await expect(row).toContainText('Preparation failed');
  await expect(row).toContainText('not a ready-to-approve storyboard');
  await expect(row.getByRole('link')).toHaveAttribute('href','/games/synthetic-game/workflows/editorial/editorial~synthetic-run');
});
