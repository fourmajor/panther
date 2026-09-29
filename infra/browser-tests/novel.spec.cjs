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
].map(c=>({...c,assetKey:`games/campaign-a/assets/chapter-${c.id.slice(0,8)}/original/chapter.json`,gameId:'campaign-a',publishedAt:c.createdAt,publicationStatus:'accepted',reviewStatus:'ai-reviewed-unverified',notice:''}));

async function fixture(page) {
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens', JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,sub:'synthetic-reader','cognito:username':'example-operator'}))+'.test'})));
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
    if(['/novel-stories','/novel-books'].includes(url.pathname)) body={records:[],cursor:null};
    if(url.pathname==='/novel') body={chapters:gameId==='campaign-a'?(url.searchParams.get('cursor')?[chapters[2]]:chapters.slice(0,2)):[],cursor:gameId==='campaign-a'&&!url.searchParams.get('cursor')?'next':null};
    if(url.pathname==='/novel-chapter') {
      const chapter=chapters.find(c=>c.id===url.searchParams.get('chapterId'));
      if(!chapter || gameId!=='campaign-a') return route.fulfill({status:404,json:{error:'Chapter not found'},headers});
      body={...chapter,markdown:'The door opened into a room of **amber light**.\n\n*Someone had been here before.*\n\n'+Array(12).fill('Rain traced the tall windows. Beyond them, a quiet harbor held its breath.').join('\n\n'),details:{review:{markdown:'Editorial audit: synthetic private note.',uncertainties:['Uncertain spelling']},revisionHistory:[{revision:1}],sourceKeys:[],rawReference:null,artifact:{},workflowVersion:2}};
    }
    return route.fulfill({json:body,headers});
  });
}

test('repeated chapter cursor fails without showing a partial library', async({page})=>{
  await fixture(page);
  let requests=0;
  await page.route(`${api}/novel?*`,route=>{requests++;return route.fulfill({headers,json:{chapters:[chapters[0]],cursor:'stuck'}});});
  await page.goto(`${origin}/games/campaign-a/novel`);
  await expect(page.locator('#novel-status')).toContainText('No partial list is shown');
  await expect(page.locator('#novel-list')).toBeEmpty();
  expect(requests).toBe(2);
});

async function booksFixture(page) {
  await fixture(page);
  const cover='games/campaign-a/assets/cover/original/cover.png';
  const story={schemaVersion:1,entityType:'NarrativeStory',gameId:'campaign-a',id:'harbor-tales',title:'Harbor Tales',synopsis:'A synthetic story about finding a path through the harbor.'};
  const book={schemaVersion:1,entityType:'NarrativeBook',gameId:'campaign-a',id:'book-one',storyId:story.id,title:'The Lantern Voyage',
    synopsis:'An explicitly ordered reading edition, not an upload timeline.',authorCredit:'Synthetic editorial team',status:'approved',classification:'grounded-adaptation',order:1,
    coverAssetKey:cover,revision:'d'.repeat(32),previousRevision:'e'.repeat(32),relatedAssetKeys:[],
    volumes:[{id:'volume-one',title:'Volume One: The Harbor',chapterKeys:[chapters[2].assetKey,chapters[1].assetKey]}]};
  await page.route(`${api}/novel-stories*`,route=>route.fulfill({headers,json:{records:[story],cursor:null}}));
  await page.route(`${api}/novel-books*`,route=>{
    const revision=new URL(route.request().url()).searchParams.get('revision');
    return route.fulfill({headers,json:revision?{record:{...book,revision,status:revision===book.previousRevision?'draft':'approved'}}:{records:[book],cursor:null}});
  });
  await page.route(`${api}/image-links`,route=>route.fulfill({headers,json:{images:{[cover]:{url:'https://images.example/cover.svg'}},expiresIn:300}}));
  await page.route('https://images.example/cover.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="220"><rect width="160" height="220" fill="#647552"/><text x="10" y="50" fill="white">Synthetic cover</text></svg>'}));
  return book;
}

for(const width of [1280,390]) test(`organized book and pinned editions are usable at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000});
  const book=await booksFixture(page);
  await page.goto(`${origin}/games/campaign-a/novel`);
  await expect(page.getByRole('heading',{name:'Harbor Tales',exact:true})).toBeVisible();
  const title=page.getByRole('link',{name:'The Lantern Voyage',exact:true});
  await accessibleInViewport(title,width);
  await expect(page.getByRole('img',{name:'Cover for The Lantern Voyage'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`novel-book-library-${width}.png`),fullPage:true});
  await title.click();
  await expect(page.getByRole('heading',{name:'Volume One: The Harbor'})).toBeVisible();
  await expect(page.locator('#novel-list ol a')).toHaveText(['The Earlier Lantern','Beyond the Harbor']);
  await page.getByRole('link',{name:'The Earlier Lantern',exact:true}).click();
  await expect(page.locator('#novel-title')).toHaveText('The Earlier Lantern');
  await expect(page.locator('#novel-notice')).toContainText('Approved private selection');
  await expect(page.locator('#novel-pagination a')).toHaveText(['Beyond the Harbor →']);
  await expect(page.locator('#novel-pagination a')).toHaveAttribute('href',new RegExp(`bookRevision=${book.revision}`));
  await page.getByRole('button',{name:'← All chapters'}).click();
  await page.getByRole('link',{name:'Previous book revision'}).click();
  await expect(page.locator('#novel-list')).toContainText('Private draft');
  await page.getByRole('link',{name:'The Earlier Lantern',exact:true}).click();
  await page.getByRole('button',{name:'Details',exact:true}).click();
  const latest=page.locator(`#novel-details a[href$="/${first}"]`);
  await expect(latest).toHaveCount(1);
  await latest.click();
  await expect(page.locator('#novel-title')).toHaveText('The Lantern Room');
  expect(new URL(page.url()).searchParams.has('book')).toBe(false);
});

test('reading position is stored per account and game and resumes explicitly',async({page})=>{
  await fixture(page);
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-title')).toHaveText('The Lantern Room');
  await page.mouse.wheel(0,750);
  await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('panther.reading.v1:synthetic-reader:campaign-a')||'null')?.paragraph || 0)).toBeGreaterThan(0);
  const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('panther.reading.v1:synthetic-reader:campaign-a')));
  expect(saved.chapterId).toBe(first); expect(saved.percent).toBeGreaterThan(0);
  await page.reload();
  const resume=page.getByRole('button',{name:new RegExp('Resume at .*saved on this device')});
  await expect(resume).toBeVisible(); await resume.click();
  await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(0);
  await page.evaluate(()=>{const tokens=JSON.parse(sessionStorage.getItem('panther.tokens'));tokens.id_token='test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,sub:'different-synthetic-reader','cognito:username':'example-operator'}))+'.test';sessionStorage.setItem('panther.tokens',JSON.stringify(tokens));});
  await page.reload();
  await expect(page.locator('#novel-title')).toHaveText('The Lantern Room');
  await expect(page.locator('#novel-resume')).toBeHidden();
});

for (const width of [1280,390]) test(`chapter Details connects finished assets at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:1000}); await fixture(page);
  const prefix='games/campaign-a/assets/';
  const raw=prefix+'raw/original/raw.json', corrected=prefix+'corrected/original/corrected.json';
  const proof=prefix+'proof/original/novel-proof.json', chapter=prefix+'chapter/original/novel-chapter.json';
  const assets=[[raw,'raw-transcript',[]],[corrected,'corrected-transcript',[raw]],
    [proof,'novel-proof',[corrected]],[chapter,'novel-chapter',[proof]]].map(([key,kind,sourceKeys])=>
    ({key,kind,sourceKeys,name:key.split('/').at(-1),metadata:{title:kind},contentType:'application/json'}));
  assets.find(a=>a.key===chapter).metadata.extra={generation:{schemaVersion:1,method:'ai-assisted',provider:'OpenAI',inference:'remote',execution:'local',tool:'Codex CLI',cost:{status:'subscription'}}};
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets,cursor:null}}));
  await page.route(`${api}/novel-chapter*`,route=>route.fulfill({headers,json:{...chapters[0],
    markdown:'A finished chapter.', details:{review:{},artifact:{key:chapter},sourceKeys:[proof],rawReference:{key:raw}}}}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await page.getByRole('button',{name:'Details',exact:true}).click();
  await expect(page.locator('#novel-details .generation-details')).toContainText('Subscription-covered');
  await expect(page.locator('#novel-prose')).not.toContainText('Subscription-covered');
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

async function previewFixture(page) {
  await fixture(page);
  const portrait='games/campaign-a/assets/mira-portrait/original/portrait.png';
  const chart='games/campaign-a/assets/chart-a/original/map.png';
  // Synthetic one-pixel PNG, never private artwork.
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
  await page.route('https://images.example/**',route=>route.fulfill({body:png,contentType:'image/png'}));
  await page.route(`${api}/character-details*`,route=>route.fulfill({headers,json:{character:{id:'mira',name:'Mira Vale',details:{
    overview:'A patient navigator who charts the harbor and keeps careful records.',thumbnailAssetKey:portrait}}}}));
  await page.route(`${api}/object-url*`,route=>route.fulfill({headers,json:{key:new URL(route.request().url()).searchParams.get('key'),
    url:'https://images.example/portrait.png',size:png.length,contentType:'image/png',expiresIn:300}}));
  await page.route(`${api}/assets*`,route=>route.fulfill({headers,json:{assets:[{key:chart,name:'map.png',kind:'map',contentType:'image/png',size:png.length,
    metadata:{title:'Harbor chart',characterIds:['mira'],extra:{preview:{schemaVersion:1,summary:'A chart of the harbor, its shoals and marked approaches.'}}},sourceKeys:[]}],cursor:null}}));
  await page.route(`${api}/novel-chapter*`,route=>{
    if(new URL(route.request().url()).searchParams.get('chapterId')!==first) return route.fallback();
    return route.fulfill({headers,json:{...chapters[0],markdown:'Mira Vale studied the Harbor chart. She recalled Beyond the Harbor.',
      readerReferences:{schemaVersion:1,mentions:[{text:'Beyond the Harbor',target:{type:'chapter',id:second}}]},details:{review:{},sourceKeys:[]}}});
  });
}

test('explicit novel references can preview and open same-game video collections',async({page})=>{
  await fixture(page);
  const collection={schemaVersion:1,entityType:'VideoCollection',gameId:'campaign-a',id:'favorites',name:'Favorite scenes',description:'A private collection of illustrated scenes.',assetKeys:[],revision:'a'.repeat(32)};
  const requested=[];
  await page.route(`${api}/video-collections*`,route=>{
    const url=new URL(route.request().url());requested.push(url.searchParams.get('id'));
    return route.fulfill({headers,json:url.searchParams.get('id')?{collection,...(url.searchParams.get('metadataOnly')?{}:{assets:[],warnings:[]})}:{collections:[collection],cursor:null}});
  });
  await page.route(`${api}/novel-chapter*`,route=>route.fulfill({headers,json:{...chapters[0],markdown:'The Favorite scenes were recalled. Other memories remain uncertain.',
    readerReferences:{schemaVersion:1,mentions:[{text:'Favorite scenes',target:{type:'collection',id:'favorites'}},{text:'Other memories',target:{type:'collection',id:'other',gameId:'campaign-b'}}]},details:{review:{},sourceKeys:[]}}}));
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  const link=page.locator('#novel-prose').getByRole('link',{name:'Favorite scenes',exact:true});
  await expect(link).toBeVisible();await expect(page.locator('#novel-prose').getByRole('link')).toHaveCount(1);
  await link.focus();const preview=page.getByRole('dialog',{name:'Link preview'});
  await expect(preview).toContainText('A private collection of illustrated scenes.');
  expect(requested).not.toContain('other');
  await preview.getByRole('link',{name:'Open linked page'}).click();
  await expect(page).toHaveURL(`${origin}/games/campaign-a/videos?collection=favorites`);
  await expect(page.getByLabel('Ordered collection')).toHaveValue('favorites');
});

for(const width of [1280,390]) test(`novel hover previews show summaries and images without obscuring controls at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900}); await previewFixture(page);
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  const prose=page.locator('#novel-prose'), link=prose.getByRole('link',{name:'Mira Vale',exact:true});
  await expect(prose.getByRole('link')).toHaveCount(3);
  const original=await prose.innerText();
  await link.hover();
  const card=page.getByRole('dialog',{name:'Link preview'});
  await expect(card).toContainText('A patient navigator');
  await expect(card.getByRole('img',{name:'Portrait of Mira Vale'})).toBeVisible();
  await expect.poll(()=>card.locator('img').evaluate(i=>i.naturalWidth)).toBeGreaterThan(0);
  const box=await card.boundingBox(); expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x+box.width).toBeLessThanOrEqual(width); expect(box.y+box.height).toBeLessThanOrEqual(900);
  await accessibleInViewport(card.getByRole('button',{name:'Close link preview'}),width);
  await card.hover(); await expect(card).toBeVisible();
  await page.screenshot({path:test.info().outputPath(`novel-preview-${width}.png`),fullPage:true});
  await page.keyboard.press('Escape'); await expect(card).not.toBeVisible();
  expect(await prose.innerText()).toBe(original);
  await prose.getByRole('link',{name:'Harbor chart',exact:true}).focus();
  await expect(card).toContainText('A chart of the harbor');
  await expect(card.locator('img')).toBeVisible();
  await page.keyboard.press('Escape');
  await prose.getByRole('link',{name:'Beyond the Harbor',exact:true}).focus();
  await expect(card).toContainText('Opening excerpt');
  await expect(card).toContainText('The door opened');
  await expect(card).not.toContainText('Editorial audit');
  await card.getByRole('link',{name:'Open linked page'}).click();
  await expect(page).toHaveURL(`${origin}/games/campaign-a/novel/${second}`);
  await expect(card).not.toBeVisible();
});

test('touch opens a preview first and its explicit open link navigates',async({browser})=>{
  const context=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  const page=await context.newPage(); await previewFixture(page);
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-prose a')).toHaveCount(3);
  await page.locator('#novel-prose').getByRole('link',{name:'Beyond the Harbor',exact:true}).tap();
  await expect(page).toHaveURL(`${origin}/games/campaign-a/novel/${first}`);
  const card=page.getByRole('dialog',{name:'Link preview'});
  await expect(card).toContainText('The door opened');
  await accessibleInViewport(card.getByRole('link',{name:'Open linked page'}),390);
  await card.getByRole('link',{name:'Open linked page'}).tap();
  await expect(page).toHaveURL(`${origin}/games/campaign-a/novel/${second}`);
  await context.close();
});

test('late or failed previews never leak across games and never prevent navigation',async({page})=>{
  await previewFixture(page); let release, arrived;
  const waiting=new Promise(resolve=>{arrived=resolve;});
  await page.route(`${api}/character-details*`,async route=>{
    arrived(); await new Promise(resolve=>{release=resolve;});
    await route.fulfill({headers,json:{character:{details:{overview:'STALE CHARACTER DESCRIPTION'}}}});
  });
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-prose a')).toHaveCount(3);
  await page.locator('#novel-prose').getByRole('link',{name:'Mira Vale'}).hover(); await waiting;
  await page.getByRole('combobox',{name:'Game'}).selectOption('test-b');
  release(); await expect(page.getByRole('dialog',{name:'Link preview'})).not.toBeVisible();
  await expect(page.locator('body')).not.toContainText('STALE CHARACTER DESCRIPTION');
});

test('unsafe summary text and unavailable images remain inert and text-only',async({page})=>{
  await previewFixture(page);
  await page.route(`${api}/character-details*`,route=>route.fulfill({headers,json:{character:{details:{overview:'<script>window.attacked=true</script>',thumbnailAssetKey:'games/foreign/assets/portrait/original/x.png'}}}}));
  const imageRequests=[]; page.on('request',r=>{if(r.url().includes('/object-url'))imageRequests.push(r.url());});
  await page.goto(`${origin}/games/campaign-a/novel/${first}`);
  await expect(page.locator('#novel-prose a')).toHaveCount(3);
  await page.locator('#novel-prose').getByRole('link',{name:'Mira Vale'}).focus();
  const card=page.getByRole('dialog',{name:'Link preview'});
  await expect(card).toContainText('<script>window.attacked=true</script>');
  await expect(card.locator('img,script')).toHaveCount(0);
  expect(imageRequests).toEqual([]); expect(await page.evaluate(()=>window.attacked)).toBeUndefined();
  await page.keyboard.press('Escape'); await expect(card).not.toBeVisible();
});

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
  await appearance.scrollIntoViewIfNeeded();
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
