const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { MODEL_VIEWER_BUNDLE_PATH } = require('../dist/lib/panther-media-explorer-stack');

const origin = 'https://panther.place';
const api = 'https://test.execute-api.us-west-2.amazonaws.com';
const headers = {'access-control-allow-origin': origin};
const first = 'a'.repeat(64), second = 'b'.repeat(64), old = 'c'.repeat(64);
const games = [{id:'campaign-a',name:'Campaign A',purpose:'campaign'}, {id:'test-b',name:'Test Game',purpose:'test'}];
const chapters = [
  {id:first,title:'The Lantern Room',sessionId:'session-one',createdAt:200},
  {id:second,title:'Beyond the Harbor',sessionId:'session-two',createdAt:300},
  {id:old,title:'The Earlier Lantern',sessionId:'session-one',createdAt:100},
].map(c=>({...c,gameId:'campaign-a',publishedAt:c.createdAt,publicationStatus:'accepted',reviewStatus:'ai-reviewed-unverified',notice:''}));

async function fixture(page) {
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens', JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'stu'}))+'.test'})));
  await page.route(`${origin}/**`, route=>{
    const pathname = new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:`window.PANTHER_CONFIG={apiUrl:'${api}',clientId:'test',cognitoDomain:'https://test.amazoncognito.com',redirectUri:'${origin}/'};`});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route(`${api}/**`, route=>{
    const url=new URL(route.request().url()), gameId=url.searchParams.get('gameId');
    let body={};
    if(url.pathname==='/games') body={games};
    if(url.pathname==='/game') body={game:games.find(g=>g.id===gameId),players:[],memberships:[],characters:[]};
    if(url.pathname==='/novel') body={chapters:gameId==='campaign-a'?(url.searchParams.get('cursor')?[chapters[2]]:chapters.slice(0,2)):[],cursor:gameId==='campaign-a'&&!url.searchParams.get('cursor')?'next':null};
    if(url.pathname==='/novel-chapter') {
      const chapter=chapters.find(c=>c.id===url.searchParams.get('chapterId'));
      if(!chapter || gameId!=='campaign-a') return route.fulfill({status:404,json:{error:'Chapter not found'},headers});
      body={...chapter,markdown:'The door opened into a room of **amber light**.\n\n*Someone had been here before.*\n\n'+Array(12).fill('Rain traced the tall windows. Beyond them, a quiet harbor held its breath.').join('\n\n'),details:{review:{markdown:'Editorial audit: synthetic private note.',uncertainties:['Uncertain spelling']},revisionHistory:[{revision:1}],sourceKeys:[],rawReference:null,artifact:{},workflowVersion:2}};
    }
    return route.fulfill({json:body,headers});
  });
}

async function accessibleInViewport(locator, width) {
  await expect(locator).toBeVisible();
  const box=await locator.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
  expect(await locator.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
}

for(const width of [1280,390]) {
  test(`clean reader, details, versions and game switching at ${width}px`, async({page})=>{
    await page.setViewportSize({width,height:1000}); await fixture(page);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`${origin}/games/campaign-a/novel`);
    await expect(page.locator('.novel-card')).toHaveCount(2);
    await expect(page.getByRole('link',{name:'The Earlier Lantern',exact:true})).toHaveCount(0);
    const link=page.getByRole('link',{name:'The Lantern Room',exact:true});
    await accessibleInViewport(link,width); await link.click();
    await expect(page.locator('#novel-title')).toHaveText('The Lantern Room');
    await expect(page.locator('#novel-prose strong')).toHaveText('amber light');
    await expect(page.locator('#novel-manuscript')).not.toContainText('Editorial audit');
    await expect(page.getByText('Editorial audit: synthetic private note.',{exact:true})).not.toBeVisible();
    const details=page.getByRole('button',{name:'Details',exact:true});
    await accessibleInViewport(details,width);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:test.info().outputPath(`novel-reader-${width}.png`),fullPage:true});
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'Download story'}).click();
    const saved=await download, text=fs.readFileSync(await saved.path(),'utf8');
    expect(text).toContain('# The Lantern Room'); expect(text).not.toContain('Editorial audit'); expect(text).not.toContain('Uncertain spelling');
    await details.click();
    await expect(page.locator('#novel-manuscript')).not.toBeVisible();
    await expect(page.getByText('Editorial audit: synthetic private note.',{exact:true})).toBeVisible();
    await page.getByRole('link',{name:/Earlier ·.*The Earlier Lantern/}).click();
    await expect(page.locator('#novel-title')).toHaveText('The Earlier Lantern');
    await expect(page.locator('#novel-notice')).toContainText('earlier version');
    await page.reload(); await expect(page.locator('#novel-title')).toHaveText('The Earlier Lantern');
    await page.locator('#novel-pagination a').click();
    await expect(page.locator('#novel-title')).toHaveText('Beyond the Harbor');
    await page.getByRole('combobox',{name:'Game'}).selectOption('test-b');
    await expect(page).toHaveURL(`${origin}/games/test-b/novel`);
    await expect(page.locator('#novel-status')).toContainText('No chapters yet');
    await expect(page.locator('#novel-prose')).toBeEmpty();
    await expect(page.locator('#novel-details')).toBeEmpty();
    expect(errors).toEqual([]);
  });
}

test('untrusted manuscript is inert and working-draft notices stay outside prose', async({page})=>{
  await fixture(page);
  await page.route(`${api}/novel-chapter*`,route=>route.fulfill({headers,json:{...chapters[0],publicationStatus:'accepted-with-notes',markdown:'<img src=x onerror="window.attacked=true">\n\n[Danger](javascript:alert(1))\n\n<script>window.attacked=true</script>',details:{review:{},sourceKeys:[]}}}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-notice')).toContainText('Working draft');
  await expect(page.locator('#novel-manuscript')).not.toContainText('Working draft');
  await expect(page.locator('#novel-prose img, #novel-prose script, #novel-prose a')).toHaveCount(0);
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
});

test('late chapter response cannot leak into another game', async({page})=>{
  await fixture(page);
  let release, arrived;
  const waiting=new Promise(resolve=>{arrived=resolve;});
  await page.route(`${api}/novel-chapter*`,async route=>{
    arrived(); await new Promise(resolve=>{release=resolve;});
    await route.fulfill({headers,json:{...chapters[0],markdown:'STALE CHAPTER',details:{review:{},sourceKeys:[]}}});
  });
  await page.goto(`${origin}/games/campaign-a/novel/${first}`); await waiting;
  await page.getByRole('combobox',{name:'Game'}).selectOption('test-b');
  await expect(page.locator('#novel-status')).toContainText('No chapters yet'); release();
  await expect(page.locator('#novel-prose')).toBeEmpty();
});

test('errors are recoverable; expired authentication hides and clears the manuscript', async({page})=>{
  await fixture(page);
  let failed=true;
  await page.route(`${api}/novel*`,route=>{
    if(failed) return route.fulfill({status:503,headers,json:{error:'Temporarily unavailable'}});
    return route.fallback();
  });
  await page.goto(`${origin}/novel`);
  await expect(page.locator('#novel-status')).toContainText('Temporarily unavailable');
  failed=false; await page.getByRole('button',{name:'Refresh chapters'}).click();
  await page.getByRole('link',{name:'The Lantern Room',exact:true}).click();
  await expect(page.locator('#novel-prose')).toContainText('amber light');
  await page.route(`${api}/novel*`,route=>route.fulfill({status:401,headers,json:{error:'Unauthorized'}}));
  await page.route(`${origin}/auth/refresh`,route=>route.fulfill({status:401,json:{error:'Expired'}}));
  await page.getByRole('button',{name:'Refresh chapters'}).click();
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
  await expect(page.locator('#novel')).not.toBeVisible();
  await expect(page.locator('#novel-prose')).toBeEmpty();
});
