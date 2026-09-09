const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { App } = require('aws-cdk-lib');
const { Template } = require('aws-cdk-lib/assertions');
const { PantherMediaExplorerStack, MODEL_VIEWER_BUNDLE_PATH } = require('../dist/lib/panther-media-explorer-stack');

const stack = new PantherMediaExplorerStack(new App(), 'AuthBrowserTest', {
  env: { account: '123456789012', region: 'us-west-2' },
  certificateArn: 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000',
  cognitoDomainPrefix: 'panther-browser-test', domainName: 'panther.place', hostedZoneId: 'Z1234567890',
});
const policy = Object.values(Template.fromStack(stack).findResources('AWS::CloudFront::ResponseHeadersPolicy'))[0]
  .Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig.ContentSecurityPolicy.ContentSecurityPolicy;
const COOKIE = '__Host-panther-refresh';
const jwt = (expired = false) => 'test.' + Buffer.from(JSON.stringify({ exp: Date.now() / 1000 + (expired ? -60 : 3600), 'cognito:username': 'test' })).toString('base64url') + '.test';

async function fixture(context, { remembered = true } = {}) {
  const state = { refreshes: 0, exchanges: [], revocations: 0, failure: 0, apiFailureOnce: false, apiTokens: [] };
  if (remembered) await context.addCookies([{ name: COOKIE, value: 'synthetic-cookie', domain: 'panther.place', path: '/', httpOnly: true, secure: true, sameSite: 'Strict', expires: Math.floor(Date.now()/1000) + 34560000 }]);
  await context.route('https://test.execute-api.us-west-2.amazonaws.com/**', async route => {
    state.apiTokens.push(route.request().headers().authorization);
    if (state.apiFailureOnce) {
      state.apiFailureOnce = false;
      return route.fulfill({ status: 401, json: {}, headers: { 'access-control-allow-origin': 'https://panther.place' } });
    }
    return route.fulfill({ json: { prefix: 'games/', prefixes: [], objects: [], characters: [] }, headers: { 'access-control-allow-origin': 'https://panther.place' } });
  });
  await context.route('https://test.amazoncognito.com/logout*', route => route.fulfill({ contentType: 'text/html', body: 'Signed out of Cognito' }));
  await context.route('https://panther.place/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.startsWith('/auth/')) {
      const headers = route.request().headers();
      expect(route.request().method()).toBe('POST');
      expect(headers.origin).toBe('https://panther.place');
      expect(headers['content-type']).toBe('application/json');
      const expiredCookie = `${COOKIE}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict`;
      if (pathname === '/auth/logout') {
        state.revocations += 1;
        if (state.failure) return route.fulfill({ status: state.failure, json: {} });
        return route.fulfill({ json: { signedOut: true }, headers: { 'set-cookie': expiredCookie } });
      }
      if (pathname === '/auth/session') state.exchanges.push(route.request().postDataJSON());
      else state.refreshes += 1;
      if (state.failure || (pathname === '/auth/refresh' && !headers.cookie?.includes(COOKIE))) {
        const status = state.failure || 401;
        return route.fulfill({ status, json: {}, headers: status === 401 ? { 'set-cookie': expiredCookie } : {} });
      }
      return route.fulfill({ json: { id_token: jwt(), expires_in: 3600 }, headers: {
        'set-cookie': `${COOKIE}=synthetic-rotated; Max-Age=34560000; Path=/; Secure; HttpOnly; SameSite=Strict`, 'cache-control': 'no-store',
      } });
    }
    if (pathname === '/config.js') return route.fulfill({ contentType: 'application/javascript', body: 'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};' });
    const file = pathname === '/vendor/model-viewer.min.js' ? MODEL_VIEWER_BUNDLE_PATH : path.join(__dirname, '../../web/media-explorer', ['/app.js', '/styles.css'].includes(pathname) ? pathname.slice(1) : 'index.html');
    return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', headers: { 'content-security-policy': policy } });
  });
  return state;
}

for (const width of [1280, 390]) {
  test(`remembered sign-in survives a browser-context restart at ${width}px without JS-readable refresh credentials`, async ({ browser }) => {
    const first = await browser.newContext({ viewport: { width, height: 900 } });
    await fixture(first);
    const page = await first.newPage();
    await page.goto('https://panther.place/media');
    await expect(page.locator('#account')).toBeVisible();
    expect(await page.evaluate(() => document.cookie)).not.toContain(COOKIE);
    expect(await page.evaluate(() => sessionStorage.getItem('panther.tokens'))).not.toContain('refresh');
    const storageState = await first.storageState();
    expect(storageState.cookies[0].httpOnly).toBe(true);
    expect(storageState.cookies[0].secure).toBe(true);
    await first.close();
    const second = await browser.newContext({ storageState, viewport: { width, height: 900 } });
    const state = await fixture(second, { remembered: false });
    const reopened = await second.newPage();
    await reopened.goto('https://panther.place/media');
    await expect(reopened.locator('#account')).toBeVisible();
    expect(state.refreshes).toBe(1);
    await second.close();
  });

  test(`expired ID renews and API 401 retries once at ${width}px`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const state = await fixture(context);
    await context.addInitScript(value => sessionStorage.setItem('panther.tokens', JSON.stringify({ id_token: value })), jwt(true));
    state.apiFailureOnce = true;
    const page = await context.newPage();
    await page.goto('https://panther.place/media');
    await expect(page.locator('#account')).toBeVisible();
    await expect.poll(() => state.apiTokens.length).toBe(2);
    expect(state.refreshes).toBe(2);
    expect(state.apiTokens.every(value => value?.startsWith('Bearer test.'))).toBe(true);
    await context.close();
  });
}

test('temporary failure preserves the cookie; revoked refresh clears it', async ({ context, page }) => {
  const state = await fixture(context);
  state.failure = 503;
  await page.goto('https://panther.place/media');
  await expect(page.locator('#auth-error')).toContainText('temporarily unavailable');
  expect((await context.cookies()).some(c => c.name === COOKIE)).toBe(true);
  state.failure = 0;
  await page.reload();
  await expect(page.locator('#account')).toBeVisible();
  state.failure = 401;
  const newTab = await context.newPage();
  await newTab.goto('https://panther.place/media');
  await expect(newTab.locator('#welcome')).toBeVisible();
  expect((await context.cookies()).some(c => c.name === COOKIE)).toBe(false);
});

test('logout revokes remembered sign-in and signs out other tabs', async ({ context, page }) => {
  const state = await fixture(context);
  const other = await context.newPage();
  await page.goto('https://panther.place/media');
  await other.goto('https://panther.place/media');
  await expect(other.locator('#account')).toBeVisible();
  await page.locator('#logout-button').click();
  await expect(page).toHaveURL(/test.amazoncognito.com\/logout/);
  await expect(other.locator('#welcome')).toBeVisible();
  expect(state.revocations).toBe(1);
  expect((await context.cookies()).some(c => c.name === COOKIE)).toBe(false);
  await other.reload();
  await expect(other.locator('#welcome')).toBeVisible();
  await expect(other.locator('#account')).toBeHidden();
});

test('failed logout stays locally signed out and can retry revocation', async ({ context, page }) => {
  const state = await fixture(context);
  await page.goto('https://panther.place/media');
  await expect(page.locator('#account')).toBeVisible();
  state.failure = 503;
  await page.locator('#logout-button').click();
  await expect(page.locator('#auth-error')).toContainText('Could not revoke');
  expect(await page.evaluate(() => sessionStorage.getItem('panther.tokens'))).toBeNull();
  const other = await context.newPage();
  await other.goto('https://panther.place/media');
  await expect(other.locator('#welcome')).toBeVisible();
  state.failure = 0;
  await page.locator('#logout-button').click();
  await expect(page).toHaveURL(/test.amazoncognito.com\/logout/);
  expect((await context.cookies()).some(c => c.name === COOKIE)).toBe(false);
});

test('OAuth callback uses server code exchange and retains PKCE/state validation', async ({ context, page }) => {
  const state = await fixture(context, { remembered: false });
  await context.addInitScript(() => sessionStorage.setItem('panther.oauth', JSON.stringify({ state: 'expected', verifier: 'x'.repeat(43), returnPath: '/media' })));
  await page.goto('https://panther.place/?code=synthetic-code&state=wrong');
  await expect(page.locator('#auth-error')).toContainText('could not be verified');
  expect(state.exchanges).toEqual([]);
  await page.goto('https://panther.place/?code=synthetic-code&state=expected');
  await expect(page.locator('#account')).toBeVisible();
  await expect(page).toHaveURL('https://panther.place/media');
  expect(state.exchanges).toEqual([{ code: 'synthetic-code', codeVerifier: 'x'.repeat(43) }]);
  expect(await page.evaluate(() => sessionStorage.getItem('panther.tokens'))).not.toContain('refresh');
});
