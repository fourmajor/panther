const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH} = require('../dist/lib/panther-media-explorer-stack');
const origin = 'https://panther.place', api = 'https://test.execute-api.us-west-2.amazonaws.com';
const headers = {'access-control-allow-origin':origin};

function recording(overrides = {}) {
  return {recordingId:'recording-'+'a'.repeat(32), sessionId:'synthetic-session', captureState:'recording',
    heartbeatAgeSeconds:0, connectionStale:false, previewState:'waiting-for-chunk', omittedChunks:0,
    segments:[{start:1,end:3,text:'The synthetic lantern is lit.'}], ...overrides};
}
async function fixture(page) {
  const state = {records:[recording()], fail:false, reads:0};
  await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'stu'}))+'.test'})));
  await page.route(`${origin}/**`, route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/config.js') return route.fulfill({contentType:'application/javascript', body:`window.PANTHER_CONFIG={apiUrl:'${api}',clientId:'test',cognitoDomain:'https://test.amazoncognito.com',redirectUri:'${origin}/'};`});
    const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname,'../../web/media-explorer', ['/app.js','/styles.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route(`${api}/**`, route => {
    const u = new URL(route.request().url()), game = u.searchParams.get('gameId');
    const games = [{id:'test-game',name:'Synthetic Game',purpose:'test'}, {id:'other-game',name:'Other Game',purpose:'campaign'}];
    let body = {};
    if (u.pathname === '/recordings/live') {
      state.reads++;
      if (state.fail) return route.abort('failed');
      body = {recordings:game==='test-game'?state.records:[],staleAfterSeconds:75};
    }
    if (u.pathname === '/games') body = {games};
    if (u.pathname === '/game') body = {game:games.find(g=>g.id===game),players:[],memberships:[],characters:[]};
    if (u.pathname === '/assets') body = {assets:[],cursor:null};
    if (u.pathname === '/characters') body = {characters:[]};
    if (u.pathname === '/objects') body = {prefixes:[],objects:[],nextCursor:null};
    return route.fulfill({headers,json:body});
  });
  return state;
}

for (const width of [1280,390]) test(`live transcript, accessible red badge and stale states at ${width}`, async({page}) => {
  await page.setViewportSize({width,height:1000}); const feed = await fixture(page);
  const errors = []; page.on('pageerror', e=>errors.push(e.message));
  await page.goto(`${origin}/games/test-game/transcripts`);
  const badge = page.locator('#recording-badge'), panel = page.getByRole('region',{name:'Live transcript',exact:true});
  await expect(badge).toBeVisible(); await expect(badge).toHaveText('Recording in progress');
  await expect(panel).toBeVisible(); await expect(panel).toContainText('The synthetic lantern is lit.');
  await expect(panel).toContainText('speakers not yet identified');
  await expect(page.locator('#library-status')).toContainText('No transcripts yet');
  expect(await badge.locator('.recording-dot').evaluate(el=>getComputedStyle(el).animationName)).toBe('recording-pulse');
  for (const target of [badge,page.getByRole('button',{name:'Refresh live feed'})]) {
    const box = await target.boundingBox(); expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
    expect(box.y+box.height).toBeLessThanOrEqual(1000);
    expect(await target.evaluate(el=>{const r=el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  }
  await page.screenshot({path:test.info().outputPath(`live-${width}.png`),fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  expect(await badge.locator('.recording-dot').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  feed.records[0].segments.push({start:4,end:8,approximateTiming:true,text:'<img src=x onerror=window.attacked=true> Synthetic second line.'});
  await page.getByRole('button',{name:'Refresh live feed'}).click();
  await expect(panel).toContainText('Synthetic second line.'); await expect(panel.locator('img')).toHaveCount(0);
  await expect(panel.locator('time').last()).toHaveText('~0:04');
  expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  feed.records[0].segments.push({start:30,end:60,kind:'preview-gap',text:'Must not appear as spoken dialogue.'});
  feed.records[0].segments.push({start:61,end:65,text:'Valid speech after the gap.'});
  await page.getByRole('button',{name:'Refresh live feed'}).click();
  const gap = panel.getByRole('note');
  await expect(gap).toBeVisible(); await expect(gap).toContainText('Preview gap: invalid recognizer output');
  await expect(gap).toContainText('not silence');
  await expect(panel).not.toContainText('Must not appear as spoken dialogue');
  await expect(panel).toContainText('Valid speech after the gap.');
  await expect(badge).toHaveText('Recording in progress');
  const gapBox = await gap.boundingBox();
  expect(gapBox.x).toBeGreaterThanOrEqual(0); expect(gapBox.x+gapBox.width).toBeLessThanOrEqual(width);
  expect(gapBox.y+gapBox.height).toBeLessThanOrEqual(1000);
  await page.screenshot({path:test.info().outputPath(`live-gap-${width}.png`),fullPage:true});
  feed.records[0].captureState = 'stalled';
  await page.getByRole('button',{name:'Refresh live feed'}).click();
  await expect(badge).toHaveText('Recording progress stalled');
  expect(await badge.locator('.recording-dot').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  feed.records[0].captureState = 'recording'; feed.records[0].heartbeatAgeSeconds = 80; feed.records[0].connectionStale = true;
  await page.getByRole('button',{name:'Refresh live feed'}).click();
  await expect(badge).toHaveText('Recording signal lost');
  feed.records = [recording({captureState:'stopped',previewState:'stopped',heartbeatAgeSeconds:200,connectionStale:true})];
  await page.getByRole('button',{name:'Refresh live feed'}).click();
  await expect(badge).toHaveText('Recording stopped');
  feed.fail = true; await page.getByRole('button',{name:'Refresh live feed'}).click();
  await expect(badge).toHaveText('Recording signal lost');
  await expect(page.locator('#live-status')).toContainText('may still be running locally');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('automatic feed polling, cross-game isolation and sign-out cleanup', async({page}) => {
  const feed = await fixture(page); await page.clock.install();
  await page.goto(`${origin}/games/test-game/audio`);
  await expect(page.locator('#recording-badge')).toHaveText('Recording in progress');
  feed.records[0].segments.push({start:10,end:12,text:'Arrived automatically.'});
  await page.clock.fastForward(21000);
  await expect(page.locator('#live-recordings')).toContainText('Arrived automatically.');
  expect(feed.reads).toBeGreaterThanOrEqual(2);
  await page.locator('#recording-badge').click();
  await expect(page).toHaveURL(`${origin}/games/test-game/transcripts`);
  await page.getByRole('combobox',{name:'Game'}).selectOption('other-game');
  await expect(page.locator('#live-recordings')).toBeEmpty();
  await expect(page.locator('#recording-badge')).toBeHidden();
  await expect(page.locator('#live-status')).toContainText('No live recording reported');
  await page.getByRole('combobox',{name:'Game'}).selectOption('test-game');
  await expect(page.locator('#live-recordings')).toContainText('Arrived automatically.');
  await page.evaluate(()=>window.dispatchEvent(new StorageEvent('storage',{key:'panther.signed-out',newValue:'true'})));
  await expect(page.locator('#live-recordings')).toBeEmpty();
  await expect(page.locator('#recording-badge')).toBeHidden();
  const requests = feed.reads; await page.clock.fastForward(40000); expect(feed.reads).toBe(requests);
});
