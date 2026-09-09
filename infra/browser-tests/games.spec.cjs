const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { MODEL_VIEWER_BUNDLE_PATH } = require('../dist/lib/panther-media-explorer-stack');

const games = [{ id: 'campaign-a', name: 'Campaign A', purpose: 'campaign', ruleset: null }, { id: 'test-b', name: 'A Long Test Game Name', purpose: 'test', ruleset: 'Synthetic System (First Edition)' }];
const jsonHeaders = { 'access-control-allow-origin': 'https://panther.place' };
async function fixture(page) {
  const requests = [];
  await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({ id_token: 'test.' + btoa(JSON.stringify({ exp: Date.now()/1000+3600, 'cognito:username': 'test' })) + '.test' })));
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', async route => {
    const url = new URL(route.request().url());
    requests.push(url);
    const id = url.searchParams.get('gameId');
    let body = {};
    if (url.pathname === '/games') body = { games };
    if (url.pathname === '/game') body = { game: games.find(g=>g.id===id),
      players:[{id:'person',name: id === 'test-b' ? 'Test Person' : 'Campaign Person'}],
      characters: id === 'test-b' ? [{id:'hero',name:'Test Hero',gameId:id}] : [],
      memberships:[{playerId:'person',role:'dungeon-master',characterIds:[]}] };
    if (url.pathname === '/objects') body = { prefixes:[],objects:[{name: url.searchParams.get('prefix').includes('test-b') ? 'test-only.flac' : 'campaign-only.flac', key: url.searchParams.get('prefix')+'assets/test/original/audio.flac',size:10,lastModified:'2026-01-01T00:00:00Z'}] };
    if (url.pathname === '/characters') body = {characters:[]};
    if (url.pathname === '/character') return route.fulfill({status:404,json:{error:'Character not found'},headers:jsonHeaders});
    return route.fulfill({ json:body, headers:jsonHeaders });
  });
  await page.route('https://panther.place/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return requests;
}

for (const width of [1280, 390]) {
  test(`game selector scopes media, roster, character links and reload at ${width}px`, async ({page})=>{
    await page.setViewportSize({width,height:900});
    const requests = await fixture(page);
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    await page.goto('https://panther.place/media');
    await expect(page.getByText('campaign-only.flac',{exact:true})).toBeVisible();
    await expect(page.locator('#game-ruleset')).toHaveText('System not set');
    const selector=page.getByRole('combobox',{name:'Game'});
    await expect(selector).toBeVisible();
    const box=await selector.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
    expect(await selector.evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;})).toBe(true);
    await selector.selectOption('test-b');
    await expect(page).toHaveURL('https://panther.place/games/test-b/media');
    await expect(page.getByText('test-only.flac',{exact:true})).toBeVisible();
    await expect(page.getByText('campaign-only.flac',{exact:true})).toHaveCount(0);
    await expect(page.locator('#game-purpose')).toContainText('Test game');
    await expect(page.locator('#game-ruleset')).toHaveText('System: Synthetic System (First Edition)');
    await expect(page.locator('#game-ruleset')).toBeVisible();
    const systemBox = await page.locator('#game-ruleset').boundingBox();
    expect(systemBox.x + systemBox.width).toBeLessThanOrEqual(width);
    await expect(page.locator('#breadcrumbs')).not.toContainText('Campaign A');
    await page.getByRole('link',{name:'Characters',exact:true}).click();
    await expect(page.locator('#player-roster')).toContainText('Test Person — Dungeon Master');
    await page.getByRole('button',{name:/Test Hero/}).click();
    await expect(page).toHaveURL('https://panther.place/games/test-b/characters/hero');
    await expect(page.locator('#character-no-model')).toBeVisible();
    await page.reload();
    await expect(selector).toHaveValue('test-b');
    await expect(page.locator('#character-name')).toHaveText('Test Hero');
    await expect(page.locator('#game-ruleset')).toContainText('Synthetic System (First Edition)');
    await page.goBack();
    await expect(page).toHaveURL('https://panther.place/games/test-b/characters');
    expect(requests.filter(u=>u.pathname==='/characters').every(u=>u.searchParams.get('gameId')==='test-b')).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({path:test.info().outputPath(`game-selector-${width}.png`),fullPage:true});
    await selector.selectOption('campaign-a');
    await expect(page.locator('#game-ruleset')).toHaveText('System not set');
    await expect(page.locator('#game-ruleset')).not.toContainText('Synthetic System');
  });
}

test('late response from a previous game cannot replace the selected media', async ({page})=>{
  await fixture(page);
  let release; let pending;
  const arrived = new Promise(resolve=>{pending=resolve;});
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/objects*', async route=>{
    const prefix=new URL(route.request().url()).searchParams.get('prefix');
    if(prefix.includes('campaign-a')) { pending(); await new Promise(resolve=>{release=resolve;}); }
    await route.fulfill({json:{prefixes:[],objects:[{key:prefix+'assets/a/original/a.txt',name:prefix.includes('campaign-a')?'stale.txt':'current.txt',size:2,lastModified:'2026-01-01'}]},headers:jsonHeaders});
  });
  await page.goto('https://panther.place/media');
  await arrived;
  await page.getByRole('combobox',{name:'Game'}).selectOption('test-b');
  await expect(page.getByText('current.txt',{exact:true})).toBeVisible();
  release();
  await expect(page.getByText('stale.txt',{exact:true})).toHaveCount(0);
  await expect(page.locator('#game-selector')).toHaveValue('test-b');
});
