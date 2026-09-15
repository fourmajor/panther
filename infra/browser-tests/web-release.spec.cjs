const { test, expect } = require('@playwright/test');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { webRelease } = require('../dist/lib/web-release');

// A real HTTP server: Playwright route mocking disables browser caching.
for (const width of [1440, 390]) test(`cached release updates without losing the route at ${width}`, async ({ page }) => {
  const source = path.join(__dirname, '../../web/media-explorer');
  const html = '<head><link rel="stylesheet" href="/styles.css"><script src="/app.js" defer></script><script src="/release.js" defer></script></head><body><h1>Release test</h1><label>Notes<input id="notes"></label></body>';
  const make = label => webRelease(html, {
    'app.js': `document.querySelector('h1').textContent=${JSON.stringify(label)}`,
    'styles.css': fs.readFileSync(path.join(source, 'styles.css'), 'utf8'),
    'release.js': fs.readFileSync(path.join(source, 'release.js'), 'utf8'),
  });
  const old = make('Old release'), next = make('New release');
  let active = old, offline = false;
  const files = { ...old.files, ...next.files }, requests = [];
  const server = http.createServer((req, res) => {
    const file = new URL(req.url, 'http://localhost').pathname.slice(1);
    requests.push(file);
    res.setHeader('Cache-Control', files[file] ? 'public,max-age=31536000,immutable' : 'no-cache');
    if (file === 'release.json') {
      res.setHeader('Content-Type', 'application/json');
      res.statusCode = offline ? 503 : 200;
      return res.end(offline ? '{}' : active.manifest);
    }
    res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(files[file] || active.html);
  });
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve));
  try {
    await page.setViewportSize({ width, height: 900 });
    const url = `http://localhost:${server.address().port}/games/example/videos?project=example#shot-3`;
    await page.goto(url);
    await expect(page.locator('h1')).toHaveText('Old release');
    await page.locator('#notes').fill('Unsaved feedback');
    offline = true;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await expect(page.locator('.release-notice')).toHaveCount(0);
    offline = false; active = next;
    await expect.poll(async () => {
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      return page.locator('.release-notice').count();
    }).toBe(1);
    await expect(page.locator('h1')).toHaveText('Old release');
    await expect(page.locator('#notes')).toHaveValue('Unsaved feedback');
    const button = page.getByRole('button', { name: 'Reload Panther' });
    await expect(button).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`release-notice-${width}.png`) });
    await button.click();
    await expect(page.locator('h1')).toHaveText('New release');
    expect(page.url()).toBe(url);
    await expect(page.locator('.release-notice')).toHaveCount(0);
    expect(requests).toContain(Object.keys(next.files).find(f => f.startsWith('app.')));
    // An old document can still retrieve the exact old release after deployment.
    const oldFile = Object.keys(old.files).find(f => f.startsWith('app.'));
    expect((await page.request.get(new URL('/' + oldFile, url).href)).status()).toBe(200);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
