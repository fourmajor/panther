const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const syntheticModel = require('./synthetic-model.cjs');
// Optional local-only QA inside the owned Docker test environment. Never commit
// a game model or upload this run's screenshots to GitHub.
const localModel = process.env.PANTHER_TEST_MODEL_PATH && fs.readFileSync(process.env.PANTHER_TEST_MODEL_PATH);
const localAnimation = process.env.PANTHER_TEST_ANIMATION_MODEL_PATH && fs.readFileSync(process.env.PANTHER_TEST_ANIMATION_MODEL_PATH);
if (localModel && (localModel.length > 5 * 1024 * 1024 || localModel.toString('ascii', 0, 4) !== 'glTF')) {
  throw new Error('Private workflow candidate must be a GLB within the viewer size budget');
}
if (localAnimation && (localAnimation.length > 5 * 1024 * 1024 || localAnimation.toString('ascii', 0, 4) !== 'glTF')) {
  throw new Error('Private animation study must be a GLB within the viewer size budget');
}
const { App } = require('aws-cdk-lib');
const { Template } = require('aws-cdk-lib/assertions');
const { PantherMediaExplorerStack, MODEL_VIEWER_BUNDLE_PATH } = require('../dist/lib/panther-media-explorer-stack');

const stack = new PantherMediaExplorerStack(new App(), 'BrowserTest', {
  identities: require('../dist/lib/deployment-identities').loadIdentities('000000000000'),
  env: { account: '123456789012', region: 'us-west-2' },
  certificateArn: 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000',
  cognitoDomainPrefix: 'panther-browser-test', domainName: 'panther.place', hostedZoneId: 'Z1234567890',
});
const policy = Object.values(Template.fromStack(stack).findResources('AWS::CloudFront::ResponseHeadersPolicy'))[0]
  .Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig.ContentSecurityPolicy.ContentSecurityPolicy;

const portraitKey='games/test-game/assets/portrait/original/portrait.svg';
function appearanceHistory(version,withModel) {
  const pair=(id,modelKey)=>({id,appearanceId:'ordinary',appearanceRevision:'b'.repeat(32),revision:'c'.repeat(32),portraitKey,modelKey,sourceKey:null,provenanceKey:null});
  return {schemaVersion:2,gameId:'test-game',characterId:'test-character',current:`edition-${version}`,activationRevision:'a'.repeat(32),
    appearances:[{id:'ordinary',name:'Ordinary appearance',story:{sessionId:null,eventId:null,date:null}}],
    selections:[pair(`edition-${version}`,withModel?`games/test-game/assets/model-${version}/original/model.glb`:null),...(withModel?[pair('older','games/test-game/assets/model-older/original/model.glb')]:[])],activations:[]};
}
function appearanceView(character,version,withModel,url,size=1024) {
  const history=appearanceHistory(version,withModel), selection=history.selections.find(s=>s.id===url.searchParams.get('selectionId')) || history.selections[0];
  return {character,selection,appearance:history.appearances[0],poster:{key:portraitKey,url:`https://test.s3.amazonaws.com/portrait.svg${withModel?'':`?v=${version}`}`},
    model:withModel?{key:selection.modelKey,url:`https://test.s3.amazonaws.com/model-${selection.id==='older'?'older':version}.glb`,size,cameraOrbit:'0deg 75deg auto',fieldOfView:'30deg'}:null};
}

for(const width of [1280,390]) test(`unselected animated model deep link and edition switching at ${width}px`,async({page},testInfo)=>{
  test.setTimeout(180000);await page.setViewportSize({width,height:900});
  const bytes=localAnimation||syntheticModel(1,undefined,true),currentBytes=syntheticModel(1);
  const character={gameId:'test-game',id:'test-character',name:'Synthetic preview character'};
  const history=appearanceHistory(1,true);
  const preview={...history.selections[0],id:'preview',modelKey:'games/test-game/assets/preview/original/model.glb'};
  const posts=[];
  let releaseCurrent,currentRequested=false;
  const currentGate=new Promise(resolve=>{releaseCurrent=resolve;});
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
    const url=new URL(route.request().url());if(route.request().method()==='POST')posts.push(url.pathname);
    if(url.pathname==='/character-versions')return route.fulfill({json:history,headers:{'access-control-allow-origin':'https://panther.place'}});
    const isPreview=url.searchParams.get('selectionId')==='preview';
    const view=appearanceView(character,1,true,url,currentBytes.length);
    if(isPreview){view.selection=preview;view.model={...view.model,key:preview.modelKey,url:'https://test.s3.amazonaws.com/model-preview.glb',size:bytes.length};}
    return route.fulfill({json:{games:[{id:'test-game',name:'Test Game',purpose:'test'}],game:{id:'test-game',name:'Test Game',purpose:'test'},players:[],memberships:[],characters:[],assets:[],cursor:null,...view},headers:{'access-control-allow-origin':'https://panther.place'}});
  });
  await page.route('https://test.s3.amazonaws.com/model-*.glb',async route=>{
    if(route.request().url().endsWith('model-1.glb')){currentRequested=true;await currentGate;}
    return route.fulfill({contentType:'model/gltf-binary',body:route.request().url().endsWith('model-preview.glb')?bytes:currentBytes,headers:{'access-control-allow-origin':'https://panther.place'}});
  });
  await page.route('https://test.s3.amazonaws.com/portrait.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="60"><rect width="40" height="60" fill="tan"/></svg>'}));
  await page.route('https://panther.place/**',route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',headers:{'content-security-policy':policy}});
  });
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'synthetic'}))+'.test'})));
  await page.goto('https://panther.place/games/test-game/characters/test-character?appearance=ordinary&selection=preview');
  const menu=page.locator('#model-version'),viewer=page.locator('#character-model');
  await expect(menu).toHaveValue('preview');await expect(page.locator('#appearance-status')).toContainText('unselected edition');
  await viewer.scrollIntoViewIfNeeded();await page.locator('#model-load').click();
  await expect.poll(()=>viewer.evaluate(el=>el.loaded),{timeout:30000}).toBe(true);
  await expect.poll(()=>viewer.evaluate(el=>el.src),{timeout:30000}).toBe('https://test.s3.amazonaws.com/model-preview.glb');
  await expect(page.locator('#model-animation-clip')).toHaveValue('Panther Idle');
  await viewer.scrollIntoViewIfNeeded();await expect.poll(()=>viewer.evaluate(el=>el.paused),{timeout:30000}).toBe(false);const start=await viewer.evaluate(el=>el.currentTime);
  await expect.poll(()=>viewer.evaluate(el=>el.currentTime),{timeout:30000}).not.toBe(start);
  const screenshot=testInfo.outputPath('unselected-animated-model.png');await page.screenshot({path:screenshot,fullPage:true});
  await menu.selectOption('edition-1');await expect(menu).toHaveValue('edition-1');
  await expect.poll(()=>viewer.evaluate(el=>el.src),{timeout:30000}).toBe('https://test.s3.amazonaws.com/model-1.glb');
  await expect.poll(()=>currentRequested).toBe(true);
  await expect.poll(()=>viewer.evaluate(el=>el.loaded)).toBe(false);
  await menu.selectOption('preview');await expect.poll(()=>viewer.evaluate(el=>el.src),{timeout:30000}).toBe('https://test.s3.amazonaws.com/model-preview.glb');
  releaseCurrent();
  await expect.poll(()=>viewer.evaluate(el=>el.loaded),{timeout:30000}).toBe(true);
  await expect(page.locator('#model-animation-clip')).toHaveValue('Panther Idle');
  await expect(menu).toHaveValue('preview');await expect(page.locator('#appearance-status')).toContainText('unselected edition');
  expect(posts).toEqual([]);
});

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`portrait-only character remains usable at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const character = { gameId: 'test-game', id: 'test-character', name: 'Test character', title: 'Swashbuckler', summary: 'Synthetic portrait-only fixture.' };
    let portraitVersion = 1;
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', route => route.fulfill({
      json: new URL(route.request().url()).pathname === '/character-versions'
        ? appearanceHistory(portraitVersion,false)
        : { games:[{id:'test-game',name:'Test Game',purpose:'test'}], game:{id:'test-game',name:'Test Game',purpose:'test'}, players:[], memberships:[], characters:[], assets:[], cursor:null,...appearanceView(character,portraitVersion,false,new URL(route.request().url())) },
      headers: {'access-control-allow-origin':'https://panther.place'},
    }));
    await page.route('https://test.s3.amazonaws.com/portrait.svg?*', route => route.fulfill({ contentType:'image/svg+xml', body:'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536"><rect width="1024" height="1536" fill="tan"/></svg>' }));
    await page.route('https://panther.place/**', route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
      const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname, '../../web/media-explorer', ['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname) ? pathname.slice(1) : 'index.html');
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',headers:{'content-security-policy':policy}});
    });
    await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'test'}))+'.test'})));
    await page.goto('https://panther.place/characters/test-game/test-character');
    await page.getByRole('button',{name:'Appearances & 3D',exact:true}).click();
    const portrait = page.locator('#character-portrait-only');
    await expect(portrait).toBeVisible();
    await expect.poll(() => portrait.evaluate(el => el.naturalWidth)).toBe(1024);
    await expect(page.locator('#model-load')).toBeHidden();
    await expect(page.locator('#character-no-model')).toBeHidden();
    const bounds = await portrait.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x+bounds.width).toBeLessThanOrEqual(viewport.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    const screenshot = testInfo.outputPath('portrait-only-page.png');
    await page.screenshot({path:screenshot,fullPage:true});
    await testInfo.attach('portrait-only-page',{path:screenshot,contentType:'image/png'});
    portraitVersion = 2;
    await page.reload();await openAppearances(page);
    await expect(portrait).toBeVisible();
    await expect(portrait).toHaveAttribute('src', /v=2$/);
    await expect.poll(() => portrait.evaluate(el => el.naturalWidth)).toBe(1024);
    await expect(page.locator('#model-load')).toBeHidden();
  });
  test(`published model loads, rotates, resets and preserves fallback at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport);
    const errors = [];
    const textureErrors = [];
    page.on('console', message => {
      if (/Content Security Policy|violates.*directive|load texture/i.test(message.text())) textureErrors.push(message.text());
    });
    // Exercise both GLTF loader paths: ImageBitmap fetch and HTMLImageElement.
    // A colored material without an embedded image cannot catch texture CSP failures.
    if (viewport.width === 390) await page.addInitScript(() => { window.createImageBitmap = undefined; });
    const texturePng = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 4;
      const context = canvas.getContext('2d'); context.fillStyle = '#c52018'; context.fillRect(0, 0, 4, 4);
      return canvas.toDataURL('image/png').split(',')[1];
    }), 'base64');
    const modelBytes = localModel || syntheticModel(1, texturePng);
    const gltf = JSON.parse(modelBytes.subarray(20, 20 + modelBytes.readUInt32LE(12)));
    const expectedTextures = (gltf.materials || []).filter(material => material.pbrMetallicRoughness?.baseColorTexture).length;
    let version = 1;
    let broken = false;
    page.on('pageerror', error => errors.push(error.message));
    const character = { gameId: 'test-game', id: 'test-character', name: 'Test character', title: 'Test', summary: 'Synthetic browser fixture, not game data.' };
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', route => route.fulfill({
      json: new URL(route.request().url()).pathname === '/character-versions'
        ? appearanceHistory(version,true)
        : { games:[{id:'test-game',name:'Test Game',purpose:'test'}], game:{id:'test-game',name:'Test Game',purpose:'test'}, players:[], memberships:[], characters:[], assets:[], cursor:null,...appearanceView(character,version,true,new URL(route.request().url()),modelBytes.length) },
      headers: { 'access-control-allow-origin': 'https://panther.place' },
    }));
    await page.route('https://test.s3.amazonaws.com/model-*.glb', route => route.fulfill({
      status: broken ? 404 : 200, contentType: 'model/gltf-binary', body: broken ? Buffer.from('missing') : modelBytes,
      headers: { 'access-control-allow-origin': 'https://panther.place' },
    }));
    await page.route('https://test.s3.amazonaws.com/portrait.svg', route => route.fulfill({
      contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536"><rect width="1024" height="1536" fill="tan"/></svg>',
    }));
    await page.route('https://panther.place/**', route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/config.js') return route.fulfill({ contentType: 'application/javascript', body: 'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};' });
      const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname, '../../web/media-explorer', ['/app.js', '/styles.css', '/ui-runtime.js', '/ui-system.css'].includes(pathname) ? pathname.slice(1) : 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', headers: { 'content-security-policy': policy } });
    });
    await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({ id_token: 'test.' + btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600, 'cognito:username': 'test' })) + '.test' })));
    await page.goto('https://panther.place/characters/test-game/test-character');
    await page.getByRole('button',{name:'Appearances & 3D',exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>Boolean(customElements.get("model-viewer")))).toBe(true);
    await expect.poll(()=>page.locator("#character-poster").evaluate(image=>image.naturalHeight)).toBeGreaterThan(0);
    await expect(page).toHaveTitle('Panther');
    await expect(page.getByRole('link', { name: 'Panther home' })).toBeVisible();
    await expect(page.getByText('Media archive', { exact: true })).toHaveCount(0);
    const viewer = page.locator('#character-model');
    await viewer.scrollIntoViewIfNeeded();
    const frame = await viewer.boundingBox();
    const button = await page.locator('#model-load').boundingBox();
    expect(button.y).toBeGreaterThanOrEqual(frame.y);
    expect(button.y + button.height).toBeLessThanOrEqual(frame.y + frame.height);
    expect(button.x).toBeGreaterThanOrEqual(frame.x);
    expect(button.x + button.width).toBeLessThanOrEqual(frame.x + frame.width);
    // Do not click/scroll the button first: browser automation can scroll clipped
    // overflow content into view and conceal the exact regression being tested.
    expect(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.id, { x: button.x + button.width / 2, y: button.y + button.height / 2 })).toBe('model-load');
    expect(errors).toEqual([]);
    await page.locator('#model-load').click();
    await expect.poll(() => viewer.evaluate(el => el.loaded), { timeout: 30000 }).toBe(true);
    if (!localModel) expect(expectedTextures).toBeGreaterThan(0);
    expect(await viewer.evaluate(el => el.model.materials.filter(material => material.pbrMetallicRoughness.baseColorTexture.texture).length)).toBe(expectedTextures);
    expect(textureErrors).toEqual([]);
    if (!localModel) {
      const redPixels = await viewer.evaluate(async el => {
        const image = new Image(); image.src = el.toDataURL('image/png'); await image.decode();
        const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
        const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        let count = 0;
        for (let i = 0; i < pixels.length; i += 4) if (pixels[i] > 80 && pixels[i] > pixels[i + 1] * 2 && pixels[i] > pixels[i + 2] * 2 && pixels[i + 3] > 200) count++;
        return count;
      });
      expect(redPixels).toBeGreaterThan(100);
    }
    const initialScreenshot = testInfo.outputPath('textured-model.png');
    await viewer.screenshot({ path: initialScreenshot });
    await testInfo.attach('textured-model', { path: initialScreenshot, contentType: 'image/png' });
    const dimensions = await viewer.evaluate(el => {
      const d = el.getDimensions(); return [d.x, d.y, d.z];
    });
    expect(dimensions.every(value => Number.isFinite(value) && value > 0)).toBe(true);
    await expect(page.locator('#model-reset')).toBeEnabled();
    if (!localModel) {
      await expect(page.locator('#model-animation-controls')).toBeHidden();
      await expect(page.locator('#model-animation-empty')).toBeVisible();
    }
    await expect(page.locator('#model-version option')).toHaveCount(2);
    const orbitBeforeZoom = await viewer.evaluate(el => el.getCameraOrbit().radius);
    await page.locator('#model-zoom-in').click();
    await expect.poll(() => viewer.evaluate(el => el.getCameraOrbit().radius)).toBeLessThan(orbitBeforeZoom);
    const targetBeforePan = await viewer.evaluate(el => el.getCameraTarget().y);
    await page.locator('#model-pan-up').click();
    await expect.poll(() => viewer.evaluate(el => el.getCameraTarget().y)).toBeGreaterThan(targetBeforePan);
    await page.locator('#model-reset').click();
    await expect(page.locator('#model-fallback')).toBeHidden();
    // A new profile selection must request the new immutable URL after refresh.
    version = 2;
    await page.reload();await openAppearances(page);
    await expect.poll(()=>page.evaluate(()=>Boolean(customElements.get("model-viewer")))).toBe(true);
    await expect.poll(()=>page.locator("#character-poster").evaluate(image=>image.naturalHeight)).toBeGreaterThan(0);
    await page.locator('#character-model').scrollIntoViewIfNeeded();
    await page.locator('#model-load').click();
    // Confirm the fresh URL before checking render completion. Software WebGL in the
    // isolated runner may keep the page busy beyond the default five-second poll budget.
    await expect.poll(() => viewer.evaluate(el => el.src), { timeout: 30000 }).toMatch(/model-2\.glb$/);
    await expect.poll(() => viewer.evaluate(el => el.loaded), { timeout: 30000 }).toBe(true);
    const initial = await viewer.evaluate(el => el.getCameraOrbit().theta);
    const area = await viewer.boundingBox();
    await page.mouse.move(area.x + area.width * .6, area.y + area.height * .5);
    await page.mouse.down();
    // One movement is enough to prove rotation. Many interpolated moves can starve the
    // Playwright event loop when the isolated Linux runner uses software WebGL.
    await page.mouse.move(area.x + area.width * .3, area.y + area.height * .5);
    await page.mouse.up();
    await expect.poll(() => viewer.evaluate(el => el.getCameraOrbit().theta)).not.toBeCloseTo(initial, 1);
    await testInfo.attach('rotated-model', { body: await viewer.screenshot(), contentType: 'image/png' });
    await page.locator('#model-reset').click();
    await expect.poll(() => viewer.evaluate(el => el.getCameraOrbit().theta)).toBeCloseTo(initial, 2);
    expect(errors).toEqual([]);
    await page.locator('#model-version').selectOption('older');
    await expect(page).toHaveURL(/appearance=ordinary&selection=older/);
    await expect.poll(() => viewer.evaluate(el => el.src), { timeout: 30000 }).toMatch(/model-older\.glb$/);
    await expect.poll(() => viewer.evaluate(el => el.loaded), { timeout: 30000 }).toBe(true);
    broken = true; version = 3;
    await page.reload();await openAppearances(page);
    await page.locator('#model-load').click();
    await expect(page.locator('#model-fallback')).toBeVisible();
    await expect(page.locator('#fallback-poster')).toBeVisible();
    await expect(page.locator('#model-reset')).toBeDisabled();
  });
}

for (const width of [1280,390]) for (const reduced of [false,true]) {
  test(`character idle playback, visibility and motion controls at ${width}px reduced=${reduced}`, async ({page},testInfo) => {
    test.setTimeout(90000);
    await page.setViewportSize({width,height:900});
    await page.emulateMedia({reducedMotion:reduced?'reduce':'no-preference'});
    // Candidate GLBs need not contain an idle animation yet. Exercise animation
    // controls with the dedicated animated fixture, while the tests above load
    // and inspect the actual candidate supplied by PANTHER_TEST_MODEL_PATH.
    const bytes=syntheticModel(1,undefined,true);
    const character={gameId:'test-game',id:'test-character',name:'Synthetic animated fixture'};
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>{
      const url=new URL(route.request().url());
      return route.fulfill({json:url.pathname==='/character-versions'?appearanceHistory(1,true):{
        games:[{id:'test-game',name:'Test Game',purpose:'test'}],game:{id:'test-game',name:'Test Game',purpose:'test'},
        players:[],memberships:[],characters:[],assets:[],cursor:null,
        ...appearanceView(character,1,true,url,bytes.length)},headers:{'access-control-allow-origin':'https://panther.place'}});
    });
    await page.route('https://test.s3.amazonaws.com/model-*.glb',route=>route.fulfill({contentType:'model/gltf-binary',body:bytes,headers:{'access-control-allow-origin':'https://panther.place'}}));
    await page.route('https://test.s3.amazonaws.com/portrait.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="60"><rect width="40" height="60" fill="tan"/></svg>'}));
    await page.route('https://panther.place/**',route=>{
      const pathname=new URL(route.request().url()).pathname;
      if(pathname==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
      const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',headers:{'content-security-policy':policy}});
    });
    await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'synthetic'}))+'.test'})));
    await page.goto('https://panther.place/characters/test-game/test-character');
    await page.getByRole('button',{name:'Appearances & 3D',exact:true}).click();
    await page.locator('#character-model').scrollIntoViewIfNeeded();
    await page.locator('#model-load').click();
    const viewer=page.locator('#character-model'),button=page.locator('#model-animation-toggle');
    await expect.poll(()=>viewer.evaluate(el=>el.loaded),{timeout:30000}).toBe(true);
    await expect(page.locator('#model-animation-clip')).toHaveValue('Panther Idle');
    await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(reduced);
    if(reduced)await button.click();
    // Keep the model actually on screen; mobile scrolling to controls may pause it.
    await viewer.scrollIntoViewIfNeeded();
    await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(false);
    const initial=await viewer.evaluate(el=>el.currentTime);
    await expect.poll(()=>viewer.evaluate(el=>el.currentTime)).not.toBe(initial);
    const orbit=await viewer.evaluate(el=>el.getCameraOrbit().theta);
    await viewer.evaluate(el=>{el.cameraOrbit='30deg 75deg auto';el.jumpCameraToGoal();});
    await expect.poll(()=>viewer.evaluate(el=>el.getCameraOrbit().theta)).not.toBe(orbit);
    await page.evaluate(()=>window.scrollTo(0,0));
    if(width===390)await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(true);
    await viewer.scrollIntoViewIfNeeded();
    await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(false);
    await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
    await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(true);
    await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
    await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(false);
    await button.click();
    await expect.poll(()=>viewer.evaluate(el=>el.paused)).toBe(true);
    await expect(button).toHaveAttribute('aria-pressed','false');
    await expect(page.locator('#model-status')).toHaveText('Model ready. Drag, zoom, or use the keyboard to explore.');
    const bounds=await button.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({path:testInfo.outputPath('animated-controls.png'),fullPage:true});
  });
}

async function openAppearances(page){const button=page.getByRole('button',{name:'Appearances & 3D',exact:true});await expect(button).toBeVisible();if(await button.getAttribute('aria-expanded')!=='true')await button.click();}
