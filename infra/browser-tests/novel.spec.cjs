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
    if(url.pathname==='/game') body={game:games.find(g=>g.id===gameId),players:[],memberships:[],characters:gameId==='campaign-a'?[{id:'mira',name:'Mira Vale'},{id:'ren-one',name:'Ren Vale'},{id:'ren-two',name:'Ren Vale'}]:[]};
    if(url.pathname==='/assets') body={assets:gameId==='campaign-a'?[{key:'games/campaign-a/assets/chart-a/original/map.png',name:'map.png',kind:'map',contentType:'image/png',metadata:{title:'Harbor chart',characterIds:['mira']},sourceKeys:[],lastModified:'2026-01-01T00:00:00Z'}]:[],cursor:null};
    if(url.pathname==='/character') return route.fulfill({status:404,headers,json:{error:'Character not found'}});
    if(url.pathname==='/characters') body={characters:[]};
    if(url.pathname==='/novel') body={chapters:gameId==='campaign-a'?(url.searchParams.get('cursor')?[chapters[2]]:chapters.slice(0,2)):[],cursor:gameId==='campaign-a'&&!url.searchParams.get('cursor')?'next':null};
    if(url.pathname==='/novel-chapter') {
      const chapter=chapters.find(c=>c.id===url.searchParams.get('chapterId'));
      if(!chapter || gameId!=='campaign-a') return route.fulfill({status:404,json:{error:'Chapter not found'},headers});
      body={...chapter,markdown:'The door opened into a room of **amber light**.\n\n*Someone had been here before.*\n\n'+Array(12).fill('Rain traced the tall windows. Beyond them, a quiet harbor held its breath.').join('\n\n'),details:{review:{markdown:'Editorial audit: synthetic private note.',uncertainties:['Uncertain spelling']},revisionHistory:[{revision:1}],sourceKeys:[],rawReference:null,artifact:{},workflowVersion:2}};
    }
    return route.fulfill({json:body,headers});
  });
}

for (const width of [1280,390]) test(`chapter Details connects finished assets at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const prefix='games/campaign-a/assets/';
  const raw=prefix+'raw/original/raw.json', corrected=prefix+'corrected/original/corrected.json';
  const proof=prefix+'proof/original/novel-proof.json', chapter=prefix+'chapter/original/novel-chapter.json';
  const assets=[[raw,'raw-transcript',[]],[corrected,'corrected-transcript',[raw]],
    [proof,'novel-proof',[corrected]],[chapter,'novel-chapter',[proof]]].map(([key,kind,sourceKeys])=>
    ({key,kind,sourceKeys,name:key.split('/').at(-1),metadata:{title:kind},contentType:'application/json'}));
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets,cursor:null}}));
  await page.route(`${api}/novel-chapter*`,route=>route.fulfill({headers,json:{...chapters[0],
    markdown:'A finished chapter.', details:{review:{},artifact:{key:chapter},sourceKeys:[proof],rawReference:{key:raw}}}}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await page.getByRole('button',{name:'Details',exact:true}).click();
  const links=page.locator('#novel-details [data-connections]');
  await expect(links.getByRole('link')).toHaveText(['Corrected transcript']);
  expect((await links.allTextContents()).join('\n')).not.toContain('novel-proof');
  const link=links.getByRole('link',{name:'Corrected transcript',exact:true});
  // Details is a normal document: reach its below-the-fold connections with user scrolling,
  // then verify hit-testing (no forced clicks or scrolling a clipped element into place).
  for (let scrolls=0; scrolls<5 && (await link.boundingBox()).y>900; scrolls++) {
    const before=(await link.boundingBox()).y;
    await page.mouse.wheel(0,350);
    await expect.poll(async()=> (await link.boundingBox()).y).toBeLessThan(before-1);
  }
  await accessibleInViewport(link,width);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`chapter-connections-${width}.png`),fullPage:true});
  await expect(page.getByText('Full provenance and revision history',{exact:true})).toBeVisible();
});

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

for (const width of [1280,390]) test(`typed narrative links and character appearances at ${width}px`, async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const key='games/campaign-a/assets/chart-a/original/map.png';
  const markdown='**Mira Vale** consulted the Harbor chart. Mira Vale’s compass pointed north.\n\nThe navigator waited with Ren Vale. Mira Valerian did not appear.\n\nThe next chapter was Beyond the Harbor. Unknown relic stayed mysterious.\n\n[Harbor chart](javascript:alert(1))';
  await page.route(`${api}/novel-chapter*`,route=>route.fulfill({headers,json:{...chapters[0],markdown,readerReferences:{schemaVersion:1,mentions:[
    {text:'The navigator',target:{type:'character',id:'mira'}},
    {text:'Beyond the Harbor',target:{type:'chapter',id:second}},
    {text:'Unknown relic',target:{type:'future-relic',id:'unknown'}},
    {text:'Mira Valerian',target:{type:'character',id:'mira',gameId:'other-game'}},
  ]},details:{review:{},sourceKeys:[]}}}));
  await page.route(`${api}/object-url*`,route=>route.fulfill({headers,json:{key,contentType:'image/png',url:'https://image.example/map.png',size:100}}));
  await page.route('https://image.example/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="tan"/></svg>'}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  const prose=page.locator('#novel-prose');
  await expect(prose.locator('a')).toHaveCount(5);
  await expect(prose.getByRole('link',{name:'Mira Vale',exact:true})).toHaveCount(2);
  await expect(prose.getByRole('link',{name:'Ren Vale',exact:true})).toHaveCount(0);
  await expect(prose).toHaveText(markdown.replaceAll('**','').replaceAll('\n\n',''));
  const chart=prose.getByRole('link',{name:'Harbor chart',exact:true});
  await accessibleInViewport(chart,width);
  expect(await chart.evaluate(a=>getComputedStyle(a).color===getComputedStyle(a.parentElement).color)).toBe(true);
  await chart.focus(); expect(await chart.evaluate(a=>getComputedStyle(a).outlineStyle)).not.toBe('none');
  await page.screenshot({path:test.info().outputPath(`novel-links-${width}.png`),fullPage:true});
  await chart.click(); await expect(page.locator('#preview-body img')).toBeVisible();
  await page.getByRole('button',{name:'Close preview'}).click();
  await expect(prose).toBeVisible();
  const download=page.waitForEvent('download'); await page.getByRole('button',{name:'Download story'}).click();
  expect(fs.readFileSync(await (await download).path(),'utf8')).toContain(markdown);
  await prose.getByRole('link',{name:'The navigator',exact:true}).click();
  await expect(page).toHaveURL(`${origin}/games/campaign-a/characters/mira`);
  await expect(page.locator('#character-name')).toHaveText('Mira Vale');
  const appearance=page.locator('#character-assets-list').getByRole('link',{name:'Harbor chart',exact:true});
  await accessibleInViewport(appearance,width);
  await page.screenshot({path:test.info().outputPath(`character-assets-${width}.png`),fullPage:true});
  await appearance.click(); await expect(page.locator('#preview-body img')).toBeVisible();
  await page.getByRole('button',{name:'Close preview'}).click();
  await page.reload(); await expect(appearance).toBeVisible();
});

test('ambiguous titles, explicit disambiguation, missing and hostile targets are safe',async({page})=>{
  await fixture(page);
  const key='games/campaign-a/assets/chart-a/original/map.png';
  const assets=[key,key.replace('chart-a','chart-b')].map(key=>({key,metadata:{title:'Harbor chart'},sourceKeys:[]}));
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets,cursor:null}}));
  let explicit=false;
  await page.route(`${api}/novel-chapter*`,route=>route.fulfill({headers,json:{...chapters[0],markdown:'Harbor chart. Ren Vale. Missing portrait. Unsafe URL. Conflicting alias. Mira Vale.',readerReferences:{schemaVersion:1,mentions:[
    ...(explicit?[{text:'Harbor chart',target:{type:'asset',key}},{text:'Ren Vale',target:{type:'character',id:'ren-one'}}]:[]),
    {text:'Missing portrait',target:{type:'asset',key:'games/other-game/assets/x/original/a.png'}},
    {text:'Mira Vale',target:{type:'character',id:'mira',gameId:'other-game'}},
    {text:'Unsafe URL',target:{type:'__proto__',id:'javascript:alert(1)'}},
    {text:'Conflicting alias',target:{type:'character',id:'mira'}},
    {text:'Conflicting alias',target:{type:'character',id:'ren-one'}},
  ]},details:{review:{},sourceKeys:[]}}}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-prose')).toContainText('Harbor chart');
  await expect(page.locator('#novel-prose a')).toHaveCount(0);
  explicit=true; await page.getByRole('button',{name:'Refresh chapters'}).click();
  await expect(page.locator('#novel-prose a')).toHaveCount(2);
  await expect(page.locator('#novel-prose').getByRole('link',{name:'Ren Vale'})).toHaveAttribute('href','/games/campaign-a/characters/ren-one');
});

test('late link enrichment cannot repopulate another game; catalog outages keep story readable',async({page})=>{
  await fixture(page); let release, arrived;
  const waiting=new Promise(resolve=>{arrived=resolve;});
  await page.route(`${api}/assets*`,async route=>{arrived(); await new Promise(resolve=>{release=resolve;}); await route.fulfill({headers,json:{assets:[],cursor:null}});});
  await page.goto(`${origin}/games/campaign-a/novel/${first}`); await waiting;
  await expect(page.locator('#novel-prose')).toContainText('amber light');
  await page.getByRole('combobox',{name:'Game'}).selectOption('test-b'); release();
  await expect(page.locator('#novel-prose')).toBeEmpty();
  await page.route(`${api}/assets*`,route=>route.fulfill({status:503,headers,json:{error:'Unavailable'}}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-status')).toContainText('Some asset links could not be loaded');
  await expect(page.locator('#novel-prose')).toContainText('amber light');
});

test('character assets use tags across kinds, not names or provenance; refresh errors and stale results are safe',async({page})=>{
  await fixture(page); let broken=true;
  const base={contentType:'video/mp4',kind:'silly-video',sourceKeys:[],lastModified:'2026-01-01T00:00:00Z'};
  const assets=[
    {...base,key:'games/campaign-a/assets/a/original/video.mp4',metadata:{title:'Tagged video',characterIds:['mira']}},
    {...base,key:'games/campaign-a/assets/b/original/video.mp4',metadata:{title:'Mira Vale',characterIds:['ren-one']}},
    {...base,key:'games/campaign-a/assets/c/original/video.mp4',metadata:{title:'Untagged derived video'},sourceKeys:['games/campaign-a/assets/a/original/video.mp4']},
  ];
  await page.route(`${api}/assets*`,route=>broken?route.fulfill({headers,status:503,json:{error:'Unavailable'}}):route.fulfill({headers,json:{assets,cursor:null}}));
  await page.goto(`${origin}/games/campaign-a/characters/mira`);
  await expect(page.locator('#character-assets-status')).toContainText('Unavailable');
  broken=false; await page.getByRole('button',{name:'Refresh assets'}).click();
  await expect(page.locator('#character-assets-list a')).toHaveCount(1);
  await expect(page.locator('#character-assets-list')).toContainText('Tagged video');
  let release, arrived; const waiting=new Promise(r=>{arrived=r;});
  await page.route(`${api}/assets*`,async route=>{arrived(); await new Promise(r=>{release=r;}); await route.fulfill({headers,json:{assets,cursor:null}});});
  await page.getByRole('button',{name:'Refresh assets'}).click(); await waiting;
  await page.getByRole('combobox',{name:'Game'}).selectOption('test-b'); release();
  await expect(page).toHaveURL(`${origin}/games/test-b/characters`);
  await expect(page.locator('#character-profile')).not.toBeVisible();
  await expect(page.locator('#character-assets-list')).not.toContainText('Tagged video');
});

test('migrated metadata refreshes character associations without changing the file URL',async({page})=>{
  await fixture(page); let migrated=false;
  const key='games/campaign-a/assets/chart-a/original/map.png';
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets:[{
    key, name:'map.png', contentType:'image/png', kind:'map', sourceKeys:[], lastModified:'2026-01-01T00:00:00Z',
    metadata:{schemaVersion:1,title:'Harbor chart',category:'reference',characterIds:migrated?['mira']:[],tags:[],sourceKeys:[],extra:{relationshipRole:'finished'}}
  }],cursor:null}}));
  await page.goto(`${origin}/games/campaign-a/characters/mira`);
  await expect(page.locator('#character-assets-list a')).toHaveCount(0);
  migrated=true; await page.getByRole('button',{name:'Refresh assets'}).click();
  const link=page.locator('#character-assets-list').getByRole('link',{name:'Harbor chart',exact:true});
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('href',`/games/campaign-a/media?asset=${encodeURIComponent(key)}`);
});
