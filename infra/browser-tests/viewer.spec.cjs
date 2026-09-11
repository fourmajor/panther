const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const syntheticModel = require('./synthetic-model.cjs');
// Optional local-only QA inside the owned Docker test environment. Never commit
// a game model or upload this run's screenshots to GitHub.
const localModel = process.env.PANTHER_TEST_MODEL_PATH && fs.readFileSync(process.env.PANTHER_TEST_MODEL_PATH);
if (localModel && (localModel.length > 5 * 1024 * 1024 || localModel.toString('ascii', 0, 4) !== 'glTF')) {
  throw new Error('Private workflow candidate must be a GLB within the viewer size budget');
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

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`portrait-only character remains usable at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const character = { gameId: 'test-game', id: 'test-character', name: 'Test character', title: 'Swashbuckler', summary: 'Synthetic portrait-only fixture.' };
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', route => route.fulfill({
      json: { games:[{id:'test-game',name:'Test Game',purpose:'test'}], game:{id:'test-game',name:'Test Game',purpose:'test'}, players:[], memberships:[], characters:[], assets:[], cursor:null, character, model:null, poster:{url:'https://test.s3.amazonaws.com/portrait.svg'} },
      headers: {'access-control-allow-origin':'https://panther.place'},
    }));
    await page.route('https://test.s3.amazonaws.com/portrait.svg', route => route.fulfill({ contentType:'image/svg+xml', body:'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536"><rect width="1024" height="1536" fill="tan"/></svg>' }));
    await page.route('https://panther.place/**', route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
      const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname, '../../web/media-explorer', ['/app.js','/styles.css'].includes(pathname) ? pathname.slice(1) : 'index.html');
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',headers:{'content-security-policy':policy}});
    });
    await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'test'}))+'.test'})));
    await page.goto('https://panther.place/characters/test-game/test-character');
    const portrait = page.locator('#character-portrait-only');
    await expect(portrait).toBeVisible();
    await expect.poll(() => portrait.evaluate(el => el.naturalWidth)).toBe(1024);
    await expect(page.locator('#model-load')).toBeHidden();
    await expect(page.getByText('Portrait ready. No 3D model has been published yet.', {exact:true})).toBeVisible();
    const bounds = await portrait.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x+bounds.width).toBeLessThanOrEqual(viewport.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    const screenshot = testInfo.outputPath('portrait-only-page.png');
    await page.screenshot({path:screenshot,fullPage:true});
    await testInfo.attach('portrait-only-page',{path:screenshot,contentType:'image/png'});
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
      json: { games:[{id:'test-game',name:'Test Game',purpose:'test'}], game:{id:'test-game',name:'Test Game',purpose:'test'}, players:[], memberships:[], characters:[], assets:[], cursor:null, character, model: { url: `https://test.s3.amazonaws.com/model-${version}.glb`, size: localModel ? localModel.length : 1024, cameraOrbit: '0deg 75deg auto', fieldOfView: '30deg' }, poster: { url: 'https://test.s3.amazonaws.com/portrait.svg' } },
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
      const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname, '../../web/media-explorer', ['/app.js', '/styles.css'].includes(pathname) ? pathname.slice(1) : 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', headers: { 'content-security-policy': policy } });
    });
    await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({ id_token: 'test.' + btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600, 'cognito:username': 'test' })) + '.test' })));
    await page.goto('https://panther.place/characters/test-game/test-character');
    await page.waitForFunction(() => customElements.get('model-viewer') && document.querySelector('#character-poster').naturalHeight > 0);
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
    await expect(page.locator('#model-fallback')).toBeHidden();
    // A new profile selection must request the new immutable URL after refresh.
    version = 2;
    await page.reload();
    await page.waitForFunction(() => customElements.get('model-viewer') && document.querySelector('#character-poster').naturalHeight > 0);
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
    await page.mouse.move(area.x + area.width * .3, area.y + area.height * .5, { steps: 20 });
    await page.mouse.up();
    await expect.poll(() => viewer.evaluate(el => el.getCameraOrbit().theta)).not.toBeCloseTo(initial, 1);
    await testInfo.attach('rotated-model', { body: await viewer.screenshot(), contentType: 'image/png' });
    await page.locator('#model-reset').click();
    await expect.poll(() => viewer.evaluate(el => el.getCameraOrbit().theta)).toBeCloseTo(initial, 2);
    expect(errors).toEqual([]);
    broken = true; version = 3;
    await page.reload();
    await page.locator('#model-load').click();
    await expect(page.locator('#model-fallback')).toBeVisible();
    await expect(page.locator('#fallback-poster')).toBeVisible();
    await expect(page.locator('#model-reset')).toBeDisabled();
  });
}
