const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { MODEL_VIEWER_BUNDLE_PATH } = require('../dist/lib/panther-media-explorer-stack');

const games = [{ id: 'campaign-a', name: 'Campaign A', purpose: 'campaign', ruleset: null }, { id: 'test-b', name: 'A Long Test Game Name', purpose: 'test', ruleset: 'Synthetic System (First Edition)' }];
const jsonHeaders = { 'access-control-allow-origin': 'https://panther.place' };

for(const width of [1280,390]) {
  test(`navigation and headings stay still while pages load at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:900});
    await fixture(page);
    let pendingPath, release;
    let pending = Promise.resolve();
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',async route=>{
      const pathname=new URL(route.request().url()).pathname;
      if(pathname===pendingPath) await pending;
      const bodies={
        '/assets':{assets:[],cursor:null}, '/novel':{chapters:[],cursor:null},
        '/novel-stories':{records:[],cursor:null}, '/novel-books':{records:[],cursor:null},
        '/tv-series':{records:[],cursor:null}, '/tv-episodes':{records:[],cursor:null},
        '/video-collections':{collections:[],cursor:null},
      };
      if(bodies[pathname]) return route.fulfill({json:bodies[pathname],headers:jsonHeaders});
      return route.fallback();
    });
    await page.goto('https://panther.place/media');
    await expect(page.getByText('campaign-only.flac',{exact:true})).toBeVisible();
    await expect(page.locator('#explorer > #status')).not.toBeVisible();
    const toolbar=page.locator('#game-toolbar');
    const baseline=(await toolbar.boundingBox()).y;
    // Observe the brief sign-in spinner too, before cached navigation resolves.
    await page.evaluate(()=>{
      window.toolbarPositions=[];
      window.navigationObserver=new MutationObserver(()=>{
        const toolbar=document.getElementById('game-toolbar');
        if(!toolbar.hidden) window.toolbarPositions.push(toolbar.getBoundingClientRect().y);
      });
      window.navigationObserver.observe(document.querySelector('main'),{subtree:true,childList:true,attributes:true});
    });
    for(const [name,path,status,heading] of [
      ['Characters','/characters','#characters-status','#characters > .explorer-heading h1'],
      ['Sessions','/assets','#library-status','#library-title'],
      ['Novel','/novel','#novel-status','#novel > .explorer-heading h1'],
      ['Episodes','/assets','#library-status','#library-title'],
      ['Assets','/assets','#assets-library','#explorer h1'],
    ]) {
      // Reload the Assets page to exercise a cold catalog request.
      pendingPath=path; pending=new Promise(resolve=>{release=resolve;});
      await page.locator('#primary-nav').getByRole('link',{name,exact:true}).click();
      if(name==='Assets') await page.reload();
      const activity=page.locator(status).locator(name==='Assets'?'.assets-card-placeholder':'.loading-state').first();
      await expect(activity).toBeVisible();
      await expect(activity).toBeInViewport();
      const title=page.locator(heading);
      await expect(title).toBeVisible();
      const loadingTop=(await title.boundingBox()).y;
      expect((await toolbar.boundingBox()).y).toBeCloseTo(baseline,1);
      await page.screenshot({path:test.info().outputPath(`navigation-${name.toLowerCase()}-loading-${width}.png`)});
      release(); pendingPath=null;
      await expect(activity).not.toBeVisible();
      expect((await title.boundingBox()).y).toBeCloseTo(loadingTop,1);
      expect((await toolbar.boundingBox()).y).toBeCloseTo(baseline,1);
    }
    const positions=await page.evaluate(()=>{window.navigationObserver?.disconnect();return window.toolbarPositions || [document.getElementById('game-toolbar').getBoundingClientRect().y];});
    expect(positions.length).toBeGreaterThan(0);
    for(const y of positions) expect(y).toBeCloseTo(baseline,1);
  });
}

async function fixture(page, canEditGame = false, development = false) {
  const currentGames = games.map(g=>({...g}));
  const descriptions = new Map();
  const requests = [];
  const styles = new Map(games.map(g => [g.id, 'photorealistic']));
  const visualStyles = ['photorealistic','anime','illustrated-fantasy','comic-book','watercolor','oil-painting','stylized-3d','pixel-art'].map(id=>({id,label:id === 'photorealistic' ? 'Photorealistic' : id === 'anime' ? 'Anime' : id,previewImage:`/style-previews/${id}.webp`}));
  await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({ id_token: 'test.' + btoa(JSON.stringify({ exp: Date.now()/1000+3600, 'cognito:username': 'example-member' })) + '.test' })));
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', async route => {
    const url = new URL(route.request().url());
    requests.push(url);
    const posted = ['/game/style','/game/settings'].includes(url.pathname) ? route.request().postDataJSON() : null;
    const id = posted?.gameId || url.searchParams.get('gameId');
    if (posted && url.pathname === '/game/settings') {
      const game = currentGames.find(g=>g.id===id);
      if (posted.expectedName !== game.name || posted.expectedRuleset !== game.ruleset || posted.expectedDescriptionRevision !== (descriptions.get(id)?.descriptionRevision || null)) return route.fulfill({status:409,json:{error:'Settings changed'},headers:jsonHeaders});
      Object.assign(game,{name:posted.name,ruleset:posted.ruleset});
      descriptions.set(id,{description:posted.description,descriptionRevision:posted.operationId});
    }
    if (posted && url.pathname === '/game/style') {
      if (posted.expectedStyle !== styles.get(id)) return route.fulfill({status:409,json:{error:'Style changed'},headers:jsonHeaders});
      styles.set(id, posted.visualStyle);
    }
    let body = {};
    if (url.pathname === '/recordings/live') body = {recordings:[]};
    if (url.pathname === '/workflows') body = {types:[]};
    if (url.pathname === '/games') body = { games: currentGames };
    if (url.pathname === '/dashboard-recent') {
      const characters=id==='test-b'?[{id:'hero',name:'Test Hero',gameId:id},{id:'guide',name:'Lantern Guide',gameId:id}]:[];
      body={complete:true,groups:{characters,transcripts:[],videos:[],chapters:[],assets:[]},counts:{characters:characters.length,transcripts:0,videos:0,chapters:0,assets:0}};
    }
    if (url.pathname === '/game' || posted) body = { game: {...currentGames.find(g=>g.id===id), visualStyle:styles.get(id)}, visualStyles, canEditGame, gameSettings:descriptions.get(id) || {description:null,descriptionRevision:null},
      players:[{id:'person',name: id === 'test-b' ? 'Test Person' : 'Campaign Person'}],
      characters: id === 'test-b' ? [{id:'hero',name:'Test Hero',gameId:id},{id:'guide',name:'Lantern Guide',gameId:id}] : [],
      memberships:[{playerId:'person',role:'player',characterIds:['hero']}] };
    if (url.pathname === '/objects') body = { prefixes:[],objects:[{name: url.searchParams.get('prefix').includes('test-b') ? 'test-only.flac' : 'campaign-only.flac', key: url.searchParams.get('prefix')+'assets/test/original/audio.flac',size:10,lastModified:'2026-01-01T00:00:00Z'}] };
    if (url.pathname === '/characters') body = {characters: id === 'test-b' ? [{id:'hero',name:'Test Hero',gameId:id},{id:'guide',name:'Lantern Guide',gameId:id}] : [], cursor:null};
    if (url.pathname === '/character') body={character:{gameId:id,id:url.searchParams.get('characterId'),name:url.searchParams.get('characterId')==='guide'?'Lantern Guide':'Test Hero'},appearance:null,selection:null,poster:null,model:null,warnings:[]};
    if (url.pathname === '/character-versions') body={schemaVersion:2,appearances:[],selections:[],activations:[],current:null,activationRevision:null};
    return route.fulfill({ json:body, headers:jsonHeaders });
  });
  await page.route('https://panther.place/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if(pathname.startsWith('/style-previews/'))return route.fulfill({contentType:'image/webp',body:fs.readFileSync(path.join(__dirname,'../../web/media-explorer',pathname.slice(1)))});
    if (pathname === '/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/",development:'+JSON.stringify(development)+'};'});
    const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return requests;
}

for (const width of [1280, 390]) {
  test(`visual style persists per game at ${width}px`, async ({page})=>{
    await page.setViewportSize({width,height:900});
    await fixture(page,true);
    await page.goto('https://panther.place/settings');
    const style = page.getByLabel('Generated visuals');
    await expect(style).toHaveValue('photorealistic');
    await expect(page.locator('.visual-style-card')).toHaveCount(8);expect(await page.locator('#game-select-trigger').evaluate(el=>el.getBoundingClientRect().height)).toBe(36);await expect(page.getByRole('button',{name:/^Zoom /})).toHaveCount(0);for(const image of await page.locator(".visual-style-card img").all()){await image.scrollIntoViewIfNeeded();await expect.poll(()=>image.evaluate(el=>el.naturalWidth)).toBe(1536);}await expect(page.getByRole('heading',{name:'Visual style',exact:true})).toBeVisible();expect(await page.getByRole('heading',{name:'Game details',exact:true}).evaluate(el=>getComputedStyle(el).fontFamily)).toContain('Georgia');
    await page.getByRole('button',{name:'Expand Anime',exact:true}).focus();await page.getByRole('button',{name:'Expand Anime',exact:true}).click();await expect(page.locator('#style-preview-dialog')).toBeVisible();await expect(page.locator('#style-preview-image')).toBeVisible();await expect.poll(()=>page.locator('#style-preview-image').evaluate(image=>image.naturalWidth)).toBe(1536);await page.getByRole('button',{name:'Close preview',exact:true}).click();await expect(page.getByRole('button',{name:'Expand Anime',exact:true})).toBeFocused();
    await page.getByRole('button',{name:'Select Anime',exact:true}).click();
    await expect(page.getByRole('status').filter({hasText:'Style saved'})).toBeVisible();
    const box = await page.locator("#visual-style-cards").boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await page.screenshot({path:test.info().outputPath(`visual-style-${width}.png`),fullPage:true});
    await page.reload();
    await expect(style).toHaveValue('anime');
    await selectGame(page,'test-b');
    await expect(style).toHaveValue('photorealistic');
    await page.route('**/game/style', route=>route.fulfill({status:409,json:{error:'Style changed'},headers:jsonHeaders}));
    await page.getByRole('button',{name:'Expand Anime',exact:true}).focus();await page.getByRole('button',{name:'Expand Anime',exact:true}).click();await expect(page.locator('#style-preview-dialog')).toBeVisible();await expect(page.locator('#style-preview-image')).toBeVisible();await expect.poll(()=>page.locator('#style-preview-image').evaluate(image=>image.naturalWidth)).toBe(1536);await page.getByRole('button',{name:'Close preview',exact:true}).click();await expect(page.getByRole('button',{name:'Expand Anime',exact:true})).toBeFocused();
    await page.getByRole('button',{name:'Select Anime',exact:true}).click();
    await expect(page.locator('#style-status')).toContainText('Could not save');
  });
  test(`ordinary member game selector scopes media, roster, character links and reload at ${width}px`, async ({page})=>{
    await page.setViewportSize({width,height:900});
    const requests = await fixture(page);
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    await page.goto('https://panther.place/media');
    await expect(page.getByText('campaign-only.flac',{exact:true})).toBeVisible();
    await expect(page.locator('#game-ruleset')).not.toBeVisible();
    const selector=page.getByRole('combobox',{name:'Current game'});
    await expect(selector).toBeVisible();
    const box=await selector.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x+box.width).toBeLessThanOrEqual(width);
    expect(await selector.evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;})).toBe(true);
    await selectGame(page,'test-b');
    await expect(page).toHaveURL('https://panther.place/games/test-b/media');
    await expect(page.getByText('test-only.flac',{exact:true})).toBeVisible();
    await expect(page.getByText('campaign-only.flac',{exact:true})).toHaveCount(0);
    await expect(page.locator('#game-purpose')).not.toBeVisible();
    await expect(page.locator('#game-ruleset')).not.toBeVisible();
    await expect(page.locator('#breadcrumbs')).not.toContainText('Campaign A');
    await page.locator('#primary-nav').getByRole('link',{name:'Dashboard',exact:true}).click();
    await expect(page.locator('#player-roster')).toBeHidden();
    await expect(page.locator('#dashboard-sections').getByRole('link',{name:'Lantern Guide',exact:true})).toBeVisible();
    await expect(page.locator('#dashboard .dashboard-open')).toBeHidden();
    await page.locator('#primary-nav').getByRole('link',{name:'Characters',exact:true}).click();
    await expect(page.locator('#character-list')).toContainText('Played by Test Person');
    await expect(page.locator('#characters #player-roster')).toHaveCount(0);
    await expect(page.locator('#characters .character-list')).toHaveCount(1);
    await page.getByRole('button',{name:/Lantern Guide/}).click();
    await expect(page.locator('#character-name')).toHaveText('Lantern Guide');
    await page.goBack();
    await page.getByRole('button',{name:/Test Hero/}).click();
    await expect(page).toHaveURL('https://panther.place/games/test-b/characters/hero');
    await expect(page.locator('#character-portrait-empty')).toBeVisible();await expect(page.locator('#character-portrait-upload')).toBeVisible();await expect(page.locator('#character-portrait-generate')).toBeVisible();
    await page.reload();
    await expect(page.locator('#game-selector')).toHaveValue('test-b');
    await expect(page.locator('#character-name')).toHaveText('Test Hero');
    await expect(page.locator('#game-ruleset')).not.toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL('https://panther.place/games/test-b/characters');
    expect(requests.filter(u=>u.pathname==='/characters').every(u=>u.searchParams.get('gameId')==='test-b')).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({path:test.info().outputPath(`game-selector-${width}.png`),fullPage:true});
    await selectGame(page,'campaign-a');
    await expect(page.locator('#game-ruleset')).not.toBeVisible();
    await expect(page.locator('#game-ruleset')).not.toBeVisible();
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
  await selectGame(page,'test-b');
  await expect(page.getByText('current.txt',{exact:true})).toBeVisible();
  release();
  await expect(page.getByText('stale.txt',{exact:true})).toHaveCount(0);
  await expect(page.locator('#game-selector')).toHaveValue('test-b');
});

for (const width of [1280,390]) {
  test(`dashboard, header and editable game settings at ${width}px`, async({page})=>{
    await page.setViewportSize({width,height:900});
    await fixture(page,true);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto('https://panther.place/');
    await expect(page.locator('#dashboard-name')).toHaveText('Campaign A');
    await expect(page.locator('#primary-nav a').first()).toHaveText('Dashboard');await expect(page.locator('.dashboard-card-link svg.lucide-chevron-right')).toHaveCount(5);await expect(page.locator('.dashboard-card-link svg.lucide-arrow-up-right')).toHaveCount(0);
    await expect(page.locator('header #game-select-trigger')).toBeVisible();
    const selectorBox=await page.locator('#game-select-trigger').boundingBox();
    expect(selectorBox.y).toBeLessThan(100); expect(selectorBox.x).toBeLessThan(width/2);
    for(const link of await page.locator('#primary-nav a').all()) {
      await expect(link).toBeInViewport();
      expect(await link.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
    }
    await expect(page.locator('#dashboard-sections a')).toHaveCount(5);
    for(const card of await page.locator('#dashboard-sections a').all()) await expect(card).toHaveAttribute('href',/^\/games\/campaign-a\//);
    await page.screenshot({path:test.info().outputPath(`dashboard-${width}.png`),fullPage:true});
    const firstCard=page.locator('#dashboard-sections [data-section=characters]');await expect(firstCard.locator('svg')).toHaveCount(2);const box=await firstCard.boundingBox();expect(box.y+box.height).toBeLessThan(900);await page.mouse.click(box.x+box.width-8,box.y+box.height-8);await expect(page).toHaveURL('https://panther.place/');await firstCard.getByRole('link',{name:'Characters',exact:true}).click();await expect(page).toHaveURL('https://panther.place/games/campaign-a/characters');
    await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
    await expect(page.getByLabel('Game name',{exact:true})).toHaveValue('Campaign A');
    await page.getByLabel('Game name',{exact:true}).fill('The Lantern Campaign');
    await page.getByLabel('Description',{exact:false}).fill('A fictional game for testing the shared archive.');
    await page.getByRole('combobox',{name:'Game system',exact:true}).click();
    await page.getByRole('option',{name:'Other',exact:true}).click();
    await page.getByLabel('Custom game system',{exact:true}).fill('Example System');
    await page.getByRole('button',{name:'Save game details',exact:true}).click();
    await expect(page.locator('#game-settings-status')).toHaveText('Game details saved.');
    await expect(page.locator('#game-selector option:checked')).toHaveText('The Lantern Campaign');
    await page.reload();
    await expect(page.getByLabel('Game name',{exact:true})).toHaveValue('The Lantern Campaign');
    await expect(page.getByLabel('Custom game system',{exact:true})).toHaveValue('Example System');
    await page.screenshot({path:test.info().outputPath(`settings-${width}.png`),fullPage:true});
    await page.locator('#primary-nav').getByRole('link',{name:'Dashboard',exact:true}).click();
    await expect(page.locator('#dashboard-name')).toHaveText('The Lantern Campaign');
    await expect(page.locator('#dashboard-description')).toHaveText('A fictional game for testing the shared archive.');
    await expect(page.locator('#dashboard-facts')).not.toContainText('Example System');
    await selectGame(page,'test-b');
    await expect(page.locator('#dashboard-name')).toHaveText('A Long Test Game Name');
    await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
    await expect(page.getByLabel('Description',{exact:false})).toHaveValue('');
    await page.route('**/game/settings',route=>route.fulfill({status:409,json:{error:'Settings changed'},headers:jsonHeaders}));
    await page.getByLabel('Game name',{exact:true}).fill('My unsaved edit');
    await page.getByRole('button',{name:'Save game details',exact:true}).click();
    await expect(page.locator('#game-settings-status')).toContainText('Reload the page');
    await expect(page.getByLabel('Game name',{exact:true})).toHaveValue('My unsaved edit');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    expect(errors).toEqual([]);
  });
}

test('read-only members can inspect settings without editable controls',async({page})=>{
  await fixture(page);
  await page.goto('https://panther.place/settings');
  await expect(page.locator('#game-settings-access')).toBeVisible();
  await expect(page.getByLabel('Game name',{exact:true})).toHaveAttribute('readonly','');
  await expect(page.getByRole('button',{name:'Save game details',exact:true})).toBeDisabled();
  await expect(page.getByLabel('Generated visuals')).toBeDisabled();
  await expect(page.getByRole('button',{name:'Select Anime',exact:true})).toBeDisabled();
});

// Exercise the visible Radix Select, including the portal and keyboard focus.
async function selectGame(page,id) {
  const name=await page.locator(`#game-selector option[value="${id}"]`).textContent();
  await page.getByRole('combobox',{name:'Current game'}).click();
  await page.getByRole('option',{name,exact:true}).click();
}

test('warm navigation reuses catalog reads and mutations invalidate cached data',async({page})=>{
  const requests=await fixture(page,true);
  await page.goto('https://panther.place/games/campaign-a/characters');
  await expect(page.locator('#character-list')).toContainText('There are no character profiles yet.');
  const count=()=>requests.filter(u=>u.pathname==='/characters'&&!u.searchParams.has('cursor')).length;
  expect(count()).toBe(1);
  await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
  await page.locator('#primary-nav').getByRole('link',{name:'Characters',exact:true}).click();
  await expect(page.locator('#character-list')).toContainText('There are no character profiles yet.');
  expect(count()).toBe(1);
  await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByLabel('Game name',{exact:true}).fill('Updated Campaign');
  await page.getByRole('button',{name:'Save game details',exact:true}).click();
  await expect(page.locator('#game-settings-status')).toHaveText('Game details saved.');
  await page.locator('#primary-nav').getByRole('link',{name:'Characters',exact:true}).click();
  await expect(page.locator('#character-list')).toContainText('There are no character profiles yet.');
  expect(count()).toBe(1);
  expect(await page.evaluate(()=>window.PantherUI.queryClient.getQueryCache().findAll().find(query=>query.queryKey[2]==='/game').state.isInvalidated)).toBe(true);
  await expect(page.locator('.loading-spinner')).toHaveCount(0);
  await expect(page.getByRole('button',{name:/^Refresh/})).toHaveCount(0);
});

for(const width of [1280,390]) test(`React file browser search, sorting and folder history at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});await fixture(page);
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/objects*',route=>{
    const prefix=new URL(route.request().url()).searchParams.get('prefix'),child=prefix.endsWith('/artwork/');
    const names=child?['gamma.png']:['beta.png','alpha.png'];
    return route.fulfill({headers:jsonHeaders,json:{prefixes:child?[]:['games/campaign-a/artwork/'],objects:names.map((name,i)=>({key:prefix+name,name,size:1000*(i+1),lastModified:'2026-01-01T00:00:00Z',contentType:'image/png'}))}});
  });
  await page.goto('https://panther.place/games/campaign-a/media');
  const browser=page.locator('.media-browser');await expect(browser.getByRole('table')).toBeVisible();
  await browser.getByRole('searchbox',{name:'Search this folder'}).fill('alpha');
  await expect(browser.getByRole('button',{name:'alpha.png',exact:true})).toBeVisible();
  await expect(browser.getByRole('button',{name:'beta.png',exact:true})).toHaveCount(0);
  await browser.getByRole('searchbox',{name:'Search this folder'}).fill('');
  await browser.getByRole('columnheader',{name:'Name'}).getByRole('button').click();
  await expect(browser.getByRole('columnheader',{name:'Name'})).toHaveAttribute('aria-sort','ascending');
  await browser.getByRole('button',{name:'artwork',exact:true}).click();
  await expect(page).toHaveURL(/folder=games%2Fcampaign-a%2Fartwork%2F/);
  await expect(browser.getByRole('button',{name:'gamma.png',exact:true})).toBeVisible();
  await page.goBack();
  await expect(browser.getByRole('button',{name:'alpha.png',exact:true})).toBeVisible();
  await expect(browser.getByRole('searchbox',{name:'Search this folder'})).toHaveValue('');
  const selector=page.getByRole('combobox',{name:'Current game'});await expect(selector).toBeInViewport();
  await expect(page.getByRole('button',{name:/^Refresh/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`react-media-${width}.png`),fullPage:true});
});

test('foreground focus refreshes only stale visible data and preserves warm navigation',async({page})=>{
  await fixture(page);let requests=0,changed=false;
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/objects*',route=>{
    requests++;const prefix=new URL(route.request().url()).searchParams.get('prefix');
    return route.fulfill({headers:jsonHeaders,json:{prefixes:[],objects:[{key:prefix+'assets/current/original/file.txt',name:changed?'Updated file.txt':'Original file.txt',size:20,lastModified:'2026-01-01T00:00:00Z'}]}});
  });
  await page.goto('https://panther.place/games/campaign-a/media');
  await expect(page.getByRole('button',{name:'Original file.txt',exact:true})).toBeVisible();
  expect(requests).toBe(1);
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  expect(requests).toBe(1);
  changed=true;
  await page.evaluate(()=>{
    const client=window.PantherUI.queryClient;
    for(const query of client.getQueryCache().findAll()) if(query.queryKey[2]==='/objects') client.setQueryData(query.queryKey,query.state.data,{updatedAt:Date.now()-61_000});
    window.dispatchEvent(new Event('focus'));
  });
  await expect(page.getByRole('button',{name:'Updated file.txt',exact:true})).toBeVisible();
  expect(requests).toBe(2);
  await expect(page.getByRole('button',{name:/^Refresh/})).toHaveCount(0);
});

test('foreground refresh never overwrites a dirty Settings form',async({page})=>{
  const requests=await fixture(page,true);
  await page.goto('https://panther.place/games/campaign-a/settings');
  await page.getByLabel('Game name',{exact:true}).fill('Unsaved name');
  const before=requests.length;
  await page.evaluate(()=>{
    const client=window.PantherUI.queryClient;
    for(const query of client.getQueryCache().findAll()) client.setQueryData(query.queryKey,query.state.data,{updatedAt:Date.now()-61_000});
    window.dispatchEvent(new Event('focus'));
  });
  await expect(page.getByLabel('Game name',{exact:true})).toHaveValue('Unsaved name');
  expect(requests.length).toBe(before);
});

for(const width of [1280,390])test(`Current Media folder is a plain label including the game root at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/objects*',route=>{const prefix=new URL(route.request().url()).searchParams.get('prefix');return route.fulfill({headers:jsonHeaders,json:{objects:[],prefixes:prefix==='games/campaign-a/'?[prefix+'maps/']:[],nextCursor:null}});});
 await page.goto('https://panther.place/games/campaign-a/media');
 const path=page.locator('.media-path');await expect(path.locator('[aria-current=location]')).toHaveText('Campaign A');await expect(path.getByRole('button')).toHaveCount(0);
 await page.locator('.media-browser').getByRole('button',{name:'maps',exact:true}).click();
 await expect(path.locator('[aria-current=location]')).toHaveText('maps');await expect(path.getByRole('button',{name:'maps',exact:true})).toHaveCount(0);await expect(path.getByRole('button',{name:'Campaign A',exact:true})).toBeVisible();
 await path.getByRole('button',{name:'Campaign A',exact:true}).click();await expect(path.locator('[aria-current=location]')).toHaveText('Campaign A');
});

for (const width of [1280, 390]) {
  test(`page actions share one compact scale and unobstructed hit areas at ${width}px`, async ({page}) => {
    await page.setViewportSize({width,height:1000});
    await fixture(page,true);
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', route => {
      const pathname=new URL(route.request().url()).pathname;
      const bodies={
        '/assets':{assets:[],cursor:null},
        '/novel':{chapters:[{id:'chapter-one',title:'A real chapter',gameId:'campaign-a',assetKey:'games/campaign-a/assets/chapter-one/original/chapter.json',publishedAt:100}],cursor:null},
        '/novel-stories':{records:[],cursor:null}, '/novel-books':{records:[],cursor:null},
        '/tv-series':{records:[],cursor:null},'/tv-episodes':{records:[],cursor:null},
        '/video-collections':{collections:[],cursor:null}, '/scenes':{records:[],cursor:null},
        '/editorial/creations':{jobs:[],cursor:null},
        '/browser-recording/capabilities':{canRecord:true,transcriptionAvailable:true},
        '/asset-generation':{generationTypes:[{id:'map',name:'Map',available:true,models:[{id:'image-model',name:'Image model'}],defaultModel:'image-model',styles:[]}]},
      };
      return bodies[pathname]?route.fulfill({json:bodies[pathname],headers:jsonHeaders}):route.fallback();
    });
    let baseline;
    for(const [section,selector] of [
      ['characters','#character-create'],['sessions','#room-start'],
      ['novel','#novel .explorer-heading [data-generation-action]'],
      ['videos','#episode-create-action'],['assets','.assets-actions .ui-button-primary'],
    ]) {
      await page.goto(`https://panther.place/games/campaign-a/${section}`);
      const button=page.locator(selector);
      await expect(button).toBeVisible();await expect(button).toBeEnabled();
      await expect(button).toBeInViewport();
      const measured=await button.evaluate(el=>{
        const style=getComputedStyle(el),rect=el.getBoundingClientRect();
        const hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);
        const heading=el.closest('.explorer-heading')||el.closest('.assets-toolbar');
        const headingRect=heading.getBoundingClientRect();
        const group=el.closest('.assets-actions')||el;const groupRect=group.getBoundingClientRect();
        return {height:rect.height,fontSize:style.fontSize,fontWeight:style.fontWeight,lineHeight:style.lineHeight,paddingLeft:style.paddingLeft,paddingRight:style.paddingRight,border:style.borderWidth,radius:style.borderRadius,background:style.backgroundColor,color:style.color,fontFamily:style.fontFamily,letterSpacing:style.letterSpacing,textTransform:style.textTransform,hit:el===hit||el.contains(hit),right:groupRect.right,toolbarRight:headingRect.right};
      });
      expect(measured.height).toBe(36);
      expect(measured.hit).toBe(true);
      expect(measured.right).toBeCloseTo(measured.toolbarRight,0);
      const {hit,right,toolbarRight,...scale}=measured;
      baseline ||= scale;
      expect(scale).toEqual(baseline);
      if(section==='assets')expect((await page.getByRole('button',{name:'Upload',exact:true}).boundingBox()).height).toBe(36);
      for(const action of await page.getByRole('button',{name:/^(Upload|Generate)(?: |$)/}).all()){
        if(!await action.isVisible())continue;
        const menu=await action.getAttribute('aria-haspopup')==='menu';await expect(action.locator('svg')).toHaveCount(menu?2:1);for(const icon of await action.locator('svg').all())await expect(icon).toHaveAttribute('aria-hidden','true');if(menu)await expect(action.locator('svg').last()).toHaveClass(/lucide-chevron-down/);
        await expect(action.locator('svg').first()).toHaveClass((await action.textContent()).trim().startsWith('Upload')?/lucide-upload/:/lucide-sparkles/);
        const actionStyle=await action.evaluate(el=>{const c=getComputedStyle(el);return {height:el.getBoundingClientRect().height,border:c.borderTopStyle};});expect(actionStyle.height).toBe(36);expect(actionStyle.border).toBe('solid');
      }
      for(const select of await page.getByRole('combobox').all())if(await select.isVisible()){
        const border=await select.evaluate(el=>{const c=getComputedStyle(el.closest('.panther-multi-select-control')||el);return {style:c.borderTopStyle,width:c.borderTopWidth};});expect(border).toEqual({style:'solid',width:'1px'});
      }
      await page.screenshot({path:test.info().outputPath(`action-${section}-${width}.png`)});
    }
    await page.goto('https://panther.place/games/campaign-a/settings');
    const save=page.getByRole('button',{name:'Save game details',exact:true});
    await expect(save).toBeVisible();
    expect((await save.boundingBox()).height).toBe(36);
    await page.goto('https://panther.place/account');
    const back=page.getByRole('link',{name:'Back to game',exact:true});
    await expect(back).toBeVisible();
    expect((await back.boundingBox()).height).toBe(44);
  });
}

for(const width of [1280,390])test(`all main page titles use one heading scale and top inset at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page,true);
 let baseline;
 for(const section of ['dashboard','characters','sessions','novel','videos','assets','workflows']){
  await page.goto(`https://panther.place/games/campaign-a/${section}`);const title=page.locator('main .page-heading h1:visible').first();await expect(title).toBeVisible();
  const readScale=()=>title.evaluate(el=>{const s=getComputedStyle(el);return{size:s.fontSize,lineHeight:s.lineHeight,weight:s.fontWeight,marginTop:s.marginTop,marginBottom:s.marginBottom};});await expect.poll(async()=>Boolean((await readScale()).size)).toBe(true);baseline ||= await readScale();await expect.poll(readScale).toEqual(baseline);
  const mainPadding=await page.locator('main').evaluate(el=>getComputedStyle(el).paddingTop);expect(mainPadding).toBe(width===390?'12px':'16px');
  const headingPadding=await title.evaluate(el=>getComputedStyle(el.closest('.page-heading')).paddingTop);expect(headingPadding).toBe('8px');
 }
});

for(const width of [1280,1920,390])test(`Settings tags are managed in a list and reused in episode filters at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page,true,true);let tags=['canonical'];const writes=[];
 await page.route('**/tags**',route=>{if(route.request().method()==='POST'){const body=route.request().postDataJSON();writes.push(body);if(body.action==='rename')tags=tags.map(tag=>tag===body.name?body.newName:tag);else if(body.action==='delete')tags=tags.filter(tag=>tag!==body.name);else tags.push(body.name);return route.fulfill({json:{tag:body.name,tags},headers:jsonHeaders});}return route.fulfill({json:{tags},headers:jsonHeaders});});
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{const path=new URL(route.request().url()).pathname;const data={'/episodes':{records:[],cursor:null},'/assets':{assets:[],cursor:null},'/video-collections':{collections:[],cursor:null}};return data[path]?route.fulfill({json:data[path],headers:jsonHeaders}):route.fallback();});
 await page.goto('https://panther.place/games/campaign-a/settings');const manager=page.locator('#game-tags-control');const tagHeading=manager.getByRole('heading',{name:'Tags',exact:true}),addTag=manager.getByRole('button',{name:'Add Tag',exact:true});await expect(addTag).toBeVisible();const [headingBox,addBox,managerBox]=await Promise.all([tagHeading.boundingBox(),addTag.boundingBox(),manager.boundingBox()]);expect(Math.abs(headingBox.y+headingBox.height/2-addBox.y-addBox.height/2)).toBeLessThan(2);expect(Math.abs(addBox.x+addBox.width-managerBox.x-managerBox.width)).toBeLessThan(2);const outer=await page.locator('#game-tags').evaluate(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return{right:r.right,padding:Number.parseFloat(s.paddingRight),border:Number.parseFloat(s.borderRightWidth)};});expect(Math.abs(addBox.x+addBox.width-(outer.right-outer.padding-outer.border))).toBeLessThan(2);const headingStyle=await tagHeading.evaluate(el=>{const s=getComputedStyle(el);return{font:s.fontFamily,size:s.fontSize,weight:s.fontWeight,lineHeight:s.lineHeight};});expect(headingStyle).toEqual(await page.locator('#game-settings .settings-card-intro h2').first().evaluate(el=>{const s=getComputedStyle(el);return{font:s.fontFamily,size:s.fontSize,weight:s.fontWeight,lineHeight:s.lineHeight};}));expect(addBox.height).toBe(36);expect(await addTag.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);await expect(manager.getByRole('combobox')).toHaveCount(0);await expect(manager.getByRole('button',{name:'Rename tag canonical',exact:true})).toBeVisible();await manager.getByRole('button',{name:'Add Tag',exact:true}).click();let dialog=page.getByRole('dialog',{name:'Add Tag',exact:true});await dialog.getByRole('textbox',{name:'Tag name',exact:true}).fill('Adventure');await dialog.getByRole('button',{name:'Add Tag',exact:true}).click();await expect(manager.getByText('Adventure',{exact:true})).toBeVisible();expect(writes[0]).toEqual({gameId:'campaign-a',name:'Adventure'});
 await manager.getByRole('button',{name:'Rename tag Adventure',exact:true}).click();dialog=page.getByRole('dialog',{name:'Rename Tag',exact:true});await dialog.getByRole('textbox',{name:'Tag name',exact:true}).fill('Voyage');await dialog.getByRole('button',{name:'Save',exact:true}).click();await expect(manager.getByText('Voyage',{exact:true})).toBeVisible();await expect(manager.getByText('Adventure',{exact:true})).toHaveCount(0);expect(writes[1]).toMatchObject({gameId:'campaign-a',action:'rename',name:'Adventure',newName:'Voyage'});expect(writes[1].operationId).toMatch(/^[a-f0-9]{32}$/);
 await manager.getByRole('button',{name:'Delete tag canonical',exact:true}).click();dialog=page.getByRole('dialog',{name:'Delete Tag?',exact:true});await dialog.getByRole('button',{name:'Cancel',exact:true}).click();expect(writes).toHaveLength(2);await manager.getByRole('button',{name:'Delete tag canonical',exact:true}).click();await page.getByRole('dialog',{name:'Delete Tag?',exact:true}).getByRole('button',{name:'Delete',exact:true}).click();await expect(manager.getByText('canonical',{exact:true})).toHaveCount(0);expect(writes[2]).toMatchObject({gameId:'campaign-a',action:'delete',name:'canonical'});await page.screenshot({path:test.info().outputPath(`tag-manager-${width}.png`)});
 await page.getByRole('link',{name:'Episodes',exact:true}).click();const filter=page.getByRole('combobox',{name:'Tags',exact:true});await filter.locator('..').click();await expect(page.getByRole('combobox',{name:'Search tags',exact:true})).toBeFocused();await page.keyboard.type('Voy');await expect(page.getByRole('option',{name:'Voyage',exact:true})).toBeVisible();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'Remove Voyage from tags',exact:true})).toBeVisible();expect(writes).toHaveLength(3);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for (const width of [1280,390]) {
  test(`game selector creates a game without redundant header labels at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:900});await fixture(page,true,true);
    let created;
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/games',async route=>{
      if(route.request().method()==='POST'){created=route.request().postDataJSON();return route.fulfill({headers:jsonHeaders,json:{game:created}});}
      return route.fulfill({headers:jsonHeaders,json:{games:[...games,...(created?[created]:[])]}});
    });
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/game?*',async route=>{
      const id=new URL(route.request().url()).searchParams.get('gameId');
      const game=created?.id===id?created:games.find(g=>g.id===id);
      return route.fulfill({headers:jsonHeaders,json:{game,gameSettings:{description:''},players:[],memberships:[],characters:[],canEditGame:true,visualStyles:[]}});
    });
    await page.goto('https://panther.place/games/campaign-a/dashboard');
    await expect(page.getByText('Current game',{exact:true})).toHaveCount(0);
    await page.locator('#game-select-root').getByRole('combobox').click();
    await page.getByRole('option',{name:'Create Game…',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'Create Game',exact:true});await expect(dialog).toBeVisible();
    await dialog.getByLabel('Name',{exact:true}).fill('Imaginary Voyage');
    await dialog.getByRole('combobox',{name:'Game system',exact:true}).click();
    await page.getByRole('option',{name:'Other',exact:true}).click();
    await dialog.getByLabel('Custom game system',{exact:true}).fill('Imaginary Rules');
    await dialog.getByRole('button',{name:'Create Game',exact:true}).click();
    await expect(page).toHaveURL(/\/games\/imaginary-voyage-[a-f0-9]+\/dashboard$/);
    await expect(dialog).toHaveCount(0);
    await expect(page.locator('#game-select-root').getByRole('combobox')).toContainText('Imaginary Voyage');
    expect(created).toMatchObject({name:'Imaginary Voyage',ruleset:'Imaginary Rules',purpose:'campaign',players:[],characters:[],memberships:[]});
  });
}

for(const width of [1280,390])test(`Create game searches rules editions and persists its selection at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page,true,true);let created;
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/games',route=>{if(route.request().method()==='POST'){created=route.request().postDataJSON();return route.fulfill({headers:jsonHeaders,json:{game:created}});}return route.fulfill({headers:jsonHeaders,json:{games:[...games,...(created?[created]:[])]}});});
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/game?*',route=>route.fulfill({headers:jsonHeaders,json:{game:created||games[0],gameSettings:{description:''},players:[],memberships:[],characters:[],canEditGame:true,visualStyles:[]}}));
 await page.goto('https://panther.place/games/campaign-a/dashboard');await page.locator('#game-select-root').getByRole('combobox').click();await page.getByRole('option',{name:'Create Game…',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Create Game',exact:true});await dialog.getByLabel('Name',{exact:true}).fill('Edition Voyage');await dialog.getByRole('combobox',{name:'Game system',exact:true}).click();const search=page.getByRole('combobox',{name:'Search game systems',exact:true});await search.fill('D&D');
 await expect(page.getByRole('option',{name:'Dungeons & Dragons — 5.5e (2024)',exact:true})).toBeVisible();await expect(page.getByRole('option',{name:'Dungeons & Dragons — 5e (2014)',exact:true})).toBeVisible();
 await search.fill('Pathfinder');const option=page.getByRole('option',{name:'Pathfinder — 2e Remaster',exact:true});await expect(option).toBeInViewport();expect(await option.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await page.screenshot({path:test.info().outputPath(`game-systems-${width}.png`)});await search.press('Enter');await expect(dialog).toBeVisible();await expect(dialog.getByRole('combobox',{name:'Game system',exact:true})).toHaveText('Pathfinder — 2e Remaster');await expect(dialog.getByLabel('Custom game system',{exact:true})).toHaveCount(0);
 await dialog.getByRole('button',{name:'Create Game',exact:true}).click();await expect(page).toHaveURL(/\/games\/edition-voyage-[a-f0-9]+\/dashboard$/);expect(created.ruleset).toBe('Pathfinder — 2e Remaster');
 await page.getByRole('link',{name:'Settings',exact:true}).click();await expect(page.getByRole('combobox',{name:'Game system',exact:true})).toHaveText('Pathfinder — 2e Remaster');
});

for(const width of [1280,390])test(`Account header uses an accessible borderless icon at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);await page.goto('https://panther.place/games/campaign-a/dashboard');
 const account=page.getByRole('button',{name:'Account',exact:true});await expect(account).toBeVisible();await expect(account).toBeInViewport();
 expect(await account.innerText()).toBe('');await expect(account.locator('svg')).toBeVisible();
 const appearance=await account.evaluate(el=>{const style=getComputedStyle(el),r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return{border:style.borderTopWidth,shadow:style.boxShadow,hit:el===hit||el.contains(hit),width:r.width,height:r.height};});
 expect(appearance.border).toBe('0px');expect(appearance.shadow).toBe('none');expect(appearance.hit).toBe(true);expect(appearance.width).toBeGreaterThanOrEqual(36);expect(appearance.height).toBeGreaterThanOrEqual(36);
 await account.hover();expect(await account.evaluate(el=>getComputedStyle(el).borderTopWidth)).toBe('0px');
 await account.focus();await expect(account).toBeFocused();expect(await account.evaluate(el=>getComputedStyle(el).boxShadow)).not.toBe('none');
 await account.press('Enter');await expect(page).toHaveURL('https://panther.place/account');
});

for(const width of [1280,390,320])test(`header Create Game stays beside the selector and reuses its dialog at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});await fixture(page,true,true);
  await page.goto('https://panther.place/games/campaign-a/dashboard');
  const create=page.locator('#game-create-button'),selector=page.locator('#game-select-root').getByRole('combobox');
  await expect(create).toBeVisible();await expect(create).toBeInViewport();await expect(create).toHaveAccessibleName('Create Game');
  await expect(create).toHaveAttribute('data-button-variant','outline');await expect(create.locator('svg')).toBeVisible();
  const [a,b]=await Promise.all([selector.boundingBox(),create.boundingBox()]);
  expect(b.x).toBeGreaterThanOrEqual(a.x+a.width);expect(Math.abs(b.y-a.y)).toBeLessThanOrEqual(4);
  expect(b.x+b.width).toBeLessThanOrEqual(width);expect(a.width).toBeGreaterThanOrEqual(70);
  expect(await create.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  if(width>=390)await expect(create.locator('.game-create-label')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`header-create-game-${width}.png`)});
  await create.click();let dialog=page.getByRole('dialog',{name:'Create Game',exact:true});await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('Name',{exact:true})).toBeFocused();await expect(dialog.getByRole('button',{name:'Create Game',exact:true})).toBeDisabled();
  await dialog.getByRole('button',{name:'Cancel',exact:true}).click();await expect(dialog).toHaveCount(0);await expect(create).toBeFocused();
  await create.press('Enter');dialog=page.getByRole('dialog',{name:'Create Game',exact:true});await expect(dialog).toBeVisible();await expect(dialog.getByLabel('Name',{exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(create).toBeFocused();
  await page.getByRole('button',{name:'Account',exact:true}).click();await expect(create).toBeHidden();
});

for(const width of [1280,390]) {
  test(`dashboard explains empty sections and shows counted recent thumbnails at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:1000});
    await fixture(page);
    await page.goto('https://panther.place/games/campaign-a/dashboard');
    await expect(page.locator('.dashboard-hero')).toHaveCSS('border-bottom-width','0px');
    for(const [section,text] of [['characters','The people and creatures'],['sessions','Recordings of you and your friends'],['novel','Write chapters yourself'],['videos','Plan episodes'],['assets','Images, maps, videos, audio']]){
      await expect(page.locator(`[data-section="${section}"] p`)).toContainText(text);
    }
    const image='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="gold"/></svg>');
    const assets=Array.from({length:6},(_,i)=>({key:`games/test-b/assets/picture-${i}/original/image.png`,title:`Picture ${i}`,contentType:'image/png'}));
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/dashboard-recent*',route=>route.fulfill({json:{complete:true,groups:{characters:[],sessions:[],episodes:[],chapters:[],assets},counts:{characters:10,sessions:5,episodes:2,chapters:4,assets:9}},headers:jsonHeaders}));
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/image-links',route=>route.fulfill({json:{images:Object.fromEntries(assets.map(a=>[a.key,{url:image}]))},headers:jsonHeaders}));
    await selectGame(page,'test-b');
    for(const label of ['10 Characters','5 Sessions','2 Episodes','4 Chapters','9 Assets'])await expect(page.getByRole('link',{name:label,exact:true})).toBeVisible();
    const card=page.locator('#dashboard-sections [data-section="assets"]');
    await expect(card.locator('img')).toHaveCount(6);
    await expect(card.getByRole('link',{name:'and 3 more',exact:true})).toBeVisible();
    const boxes=await card.locator('img').evaluateAll(images=>images.map(img=>{const r=img.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}));
    expect(boxes[0].y).toBeCloseTo(boxes[2].y,1);expect(boxes[3].y).toBeGreaterThan(boxes[0].y);
    for(const box of boxes){expect(box.width).toBeGreaterThan(50);expect(box.height).toBeCloseTo(box.width,0);expect(box.x+box.width).toBeLessThanOrEqual(width);}
    const picture=card.getByRole('link',{name:'Picture 0',exact:true});
    const original=await card.evaluate(el=>({background:getComputedStyle(el).backgroundColor,border:getComputedStyle(el).borderColor}));
    await picture.hover();
    await expect(picture).toHaveCSS('outline-width','2px');
    expect(await picture.evaluate(el=>getComputedStyle(el).outlineColor)).not.toBe('rgba(0, 0, 0, 0)');
    expect(await card.evaluate(el=>({background:getComputedStyle(el).backgroundColor,border:getComputedStyle(el).borderColor}))).toEqual(original);
    const cardBox=await card.boundingBox();
    await page.mouse.click(cardBox.x+cardBox.width-8,cardBox.y+cardBox.height-8);
    await expect(page).toHaveURL('https://panther.place/games/test-b/dashboard');
    await expect(card.getByRole('link',{name:'9 Assets',exact:true})).toHaveCSS('text-decoration-line','none');
    await picture.focus();
    await expect(picture).toBeFocused();
    expect(await picture.evaluate(el=>getComputedStyle(el).outlineColor)).not.toBe('rgba(0, 0, 0, 0)');
    await page.screenshot({path:test.info().outputPath(`dashboard-counted-assets-${width}.png`),fullPage:true});
    await card.getByRole('link',{name:'and 3 more',exact:true}).click();
    await expect(page).toHaveURL('https://panther.place/games/test-b/assets');
  });
}
