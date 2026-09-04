const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { App } = require('aws-cdk-lib');
const { Template } = require('aws-cdk-lib/assertions');
const { PantherMediaExplorerStack, MODEL_VIEWER_BUNDLE_PATH } = require('../dist/lib/panther-media-explorer-stack');

const stack = new PantherMediaExplorerStack(new App(), 'BrowserTest', {
  env: { account: '123456789012', region: 'us-west-2' },
  certificateArn: 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000',
  cognitoDomainPrefix: 'panther-browser-test', domainName: 'panther.place', hostedZoneId: 'Z1234567890',
});
const policy = Object.values(Template.fromStack(stack).findResources('AWS::CloudFront::ResponseHeadersPolicy'))[0]
  .Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig.ContentSecurityPolicy.ContentSecurityPolicy;

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`portrait and 3D load control fit the viewer at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const character = { gameId: 'test-game', id: 'test-character', name: 'Test character', title: 'Test', summary: 'Synthetic browser fixture, not game data.' };
    await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', route => route.fulfill({
      json: { character, model: { url: 'https://test.s3.amazonaws.com/model.glb', size: 1024, cameraOrbit: '0deg 75deg auto', fieldOfView: '30deg' }, poster: { url: 'https://test.s3.amazonaws.com/portrait.svg' } },
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
  });
}
