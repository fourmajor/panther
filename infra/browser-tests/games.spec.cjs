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
      ['Audio','/assets','#library-status','#library-title'],
      ['Transcripts','/assets','#library-status','#library-title'],
      ['Novel','/novel','#novel-status','#novel > .explorer-heading h1'],
      ['Videos','/assets','#library-status','#library-title'],
      ['Media','/objects','#explorer > #status','#explorer h1'],
    ]) {
      // Media is cached on return; refresh exercises its loading state.
      pendingPath=path; pending=new Promise(resolve=>{release=resolve;});
      await page.locator('#primary-nav').getByRole('link',{name,exact:true}).click();
      if(name==='Media') await page.getByRole('button',{name:'Refresh',exact:true}).click();
      const activity=page.locator(status).locator('.loading-state');
      await expect(activity).toBeVisible();
      await expect(activity).toBeInViewport();
      const title=page.locator(heading);
      await expect(title).toBeVisible();
      const loadingTop=(await title.boundingBox()).y;
      expect((await toolbar.boundingBox()).y).toBeCloseTo(baseline,1);
      await page.screenshot({path:test.info().outputPath(`navigation-${name.toLowerCase()}-loading-${width}.png`)});
      release(); pendingPath=null;
      await expect(activity).toHaveCount(0);
      expect((await title.boundingBox()).y).toBeCloseTo(loadingTop,1);
      expect((await toolbar.boundingBox()).y).toBeCloseTo(baseline,1);
    }
    const positions=await page.evaluate(()=>{window.navigationObserver.disconnect();return window.toolbarPositions;});
    expect(positions.length).toBeGreaterThan(0);
    for(const y of positions) expect(y).toBeCloseTo(baseline,1);
  });
}

async function fixture(page, canEditGame = false) {
  const currentGames = games.map(g=>({...g}));
  const descriptions = new Map();
  const requests = [];
  const styles = new Map(games.map(g => [g.id, 'photorealistic']));
  const visualStyles = ['photorealistic','anime','illustrated-fantasy','comic-book','watercolor','oil-painting','stylized-3d','pixel-art'].map(id=>({id,label:id === 'photorealistic' ? 'Photorealistic' : id === 'anime' ? 'Anime' : id}));
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
    if (url.pathname === '/games') body = { games: currentGames };
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
    if (pathname === '/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css'].includes(pathname)?pathname.slice(1):'index.html');
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
    await expect(style.locator('option')).toHaveCount(8);
    await style.selectOption('anime');
    await page.getByRole('button',{name:'Save style'}).click();
    await expect(page.getByRole('status').filter({hasText:'Style saved'})).toBeVisible();
    const box = await style.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await page.screenshot({path:test.info().outputPath(`visual-style-${width}.png`),fullPage:true});
    await page.reload();
    await expect(style).toHaveValue('anime');
    await page.getByRole('combobox',{name:'Game',exact:true}).selectOption('test-b');
    await expect(style).toHaveValue('photorealistic');
    await page.route('**/game/style', route=>route.fulfill({status:409,json:{error:'Style changed'},headers:jsonHeaders}));
    await style.selectOption('anime');
    await page.getByRole('button',{name:'Save style'}).click();
    await expect(page.locator('#style-status')).toContainText('Could not save');
  });
  test(`ordinary member game selector scopes media, roster, character links and reload at ${width}px`, async ({page})=>{
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
    await page.locator('#primary-nav').getByRole('link',{name:'Dashboard',exact:true}).click();
    await expect(page.locator('#player-roster')).toContainText('Test Person');
    await expect(page.locator('#player-roster')).not.toContainText('Lantern Guide');
    await page.locator('#primary-nav').getByRole('link',{name:'Characters',exact:true}).click();
    await expect(page.locator('#character-list')).toContainText('Played by Test Person');
    await expect(page.locator('#characters #player-roster')).toHaveCount(0);
    await expect(page.locator('#characters .character-list')).toHaveCount(1);
    await page.getByRole('button',{name:/Lantern Guide/}).click();
    await expect(page.locator('#character-name')).toHaveText('Lantern Guide');
    await page.goBack();
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

for (const width of [1280,390]) {
  test(`dashboard, header and editable game settings at ${width}px`, async({page})=>{
    await page.setViewportSize({width,height:900});
    await fixture(page,true);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto('https://panther.place/');
    await expect(page.locator('#dashboard-name')).toHaveText('Campaign A');
    await expect(page.locator('#primary-nav a').first()).toHaveText('Dashboard');
    await expect(page.locator('header #game-selector')).toBeVisible();
    const selectorBox=await page.locator('#game-selector').boundingBox();
    expect(selectorBox.y).toBeLessThan(100); expect(selectorBox.x).toBeLessThan(width/2);
    for(const link of await page.locator('#primary-nav a').all()) {
      await expect(link).toBeInViewport();
      expect(await link.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
    }
    await expect(page.locator('#dashboard-sections a')).toHaveCount(6);
    for(const card of await page.locator('#dashboard-sections a').all()) await expect(card).toHaveAttribute('href',/^\/games\/campaign-a\//);
    await page.screenshot({path:test.info().outputPath(`dashboard-${width}.png`),fullPage:true});
    await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
    await expect(page.getByLabel('Game name',{exact:true})).toHaveValue('Campaign A');
    await page.getByLabel('Game name',{exact:true}).fill('The Lantern Campaign');
    await page.getByLabel('Description',{exact:false}).fill('A fictional game for testing the shared archive.');
    await page.getByLabel('Game system',{exact:true}).fill('Example System');
    await page.getByRole('button',{name:'Save game details',exact:true}).click();
    await expect(page.locator('#game-settings-status')).toHaveText('Game details saved.');
    await expect(page.locator('#game-selector option:checked')).toHaveText('The Lantern Campaign');
    await page.reload();
    await expect(page.getByLabel('Game name',{exact:true})).toHaveValue('The Lantern Campaign');
    await expect(page.getByLabel('Game system',{exact:true})).toHaveValue('Example System');
    await page.screenshot({path:test.info().outputPath(`settings-${width}.png`),fullPage:true});
    await page.locator('#primary-nav').getByRole('link',{name:'Dashboard',exact:true}).click();
    await expect(page.locator('#dashboard-name')).toHaveText('The Lantern Campaign');
    await expect(page.locator('#dashboard-description')).toHaveText('A fictional game for testing the shared archive.');
    await expect(page.locator('#dashboard-facts')).toContainText('Example System');
    await page.locator('#game-selector').selectOption('test-b');
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
  await expect(page.getByRole('button',{name:'Save style',exact:true})).toBeDisabled();
});
