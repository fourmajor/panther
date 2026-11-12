const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const jsonHeaders = {'access-control-allow-origin': 'https://panther.place'};
const games = [{id: 'campaign-a', name: 'Campaign A', purpose: 'campaign', ruleset: null}];

function node(id, type, title, column, row, status, message) {
  return {id, type, title, icon: 'circle', column, row, final: false, status, message, logs: [], artifacts: []};
}

const night = {
  schemaVersion: 1,
  sessionId: 'session-night',
  title: 'Night one',
  nodes: [
    node('session-audio', 'Capture', 'Session audio', 0, 0, 'done', null),
    node('transcription', 'Speech', 'Transcription', 1, 0, 'failed', 'Recognizer rejected the audio.'),
    node('correction', 'Edit', 'Transcript cleanup', 2, 0, 'running', null),
    node('storyboard-approval', 'Gate', 'Storyboard approval', 3, 1, 'paused', 'Paid video stays blocked until this storyboard revision is approved.'),
    node('video-generation', 'Render', 'Video generation', 4, 1, 'pending', null),
  ],
  edges: [
    {from: 'session-audio', to: 'transcription', status: 'done'},
    {from: 'transcription', to: 'correction', status: 'failed'},
    {from: 'storyboard-approval', to: 'video-generation', status: 'paused'},
  ],
};

function wideNight() {
  const titles = ['Session audio', 'Transcription', 'Transcript cleanup', 'Storyboard approval', 'Video generation', 'Sound and delivery', 'Narration', 'Novel chapter', 'Session video', 'Still images', 'Listening copy', 'Corrected transcript'];
  return {
    schemaVersion: 1,
    sessionId: 'session-wide',
    title: 'Long night',
    nodes: titles.map((title, index) => node(`wide-${index}`, 'Stage', title, index, index % 3, 'pending', null)),
    edges: titles.slice(1).map((_, index) => ({from: `wide-${index}`, to: `wide-${index + 1}`, status: 'pending'})),
  };
}

function pipelineBody(sessionId) {
  if (sessionId === 'session-wide') {
    return {schemaVersion: 1, source: 'job-records', sessions: [{id: 'session-wide', title: 'Long night', updatedAt: 30, status: 'pending'}], workers: [], manifest: wideNight()};
  }
  const selected = sessionId === 'session-dawn' ? 'session-dawn' : 'session-night';
  const dawn = {
    ...night,
    sessionId: 'session-dawn',
    title: 'Dawn',
    nodes: night.nodes.map(item => item.id === 'transcription' ? {...item, status: 'pending', message: null} : item),
  };
  return {
    schemaVersion: 1,
    source: 'job-records',
    sessions: [
      {id: 'session-night', title: 'Night one', updatedAt: 20, status: 'failed'},
      {id: 'session-dawn', title: 'Dawn', updatedAt: 10, status: 'pending'},
    ],
    workers: [
      {id: 'editorial', status: 'ready', seenAt: 1, message: null},
      {id: 'playback', status: 'offline', seenAt: 0, message: 'Worker offline or its Panther sign-in expired.'},
      {id: 'model', status: 'ready', seenAt: 1, message: null},
    ],
    manifest: selected === 'session-dawn' ? dawn : night,
  };
}

async function openHome(page) {
  await page.addInitScript(() => sessionStorage.setItem('panther.tokens', JSON.stringify({id_token: 'test.' + btoa(JSON.stringify({exp: Date.now() / 1000 + 3600, 'cognito:username': 'example-member'})) + '.test'})));
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/workflows' && url.searchParams.get('view') === 'session-pipeline') {
      return route.fulfill({json: pipelineBody(url.searchParams.get('sessionId')), headers: jsonHeaders});
    }
    const bodies = {
      '/games': {games},
      '/game': {game: games[0], gameSettings: {description: ''}, players: [], memberships: [], characters: [], canEditGame: true, visualStyles: []},
      '/recordings/live': {recordings: []},
      '/dashboard-recent': {complete: true, groups: {characters: [], sessions: [], episodes: [], chapters: [], assets: []}, counts: {characters: 0, sessions: 0, episodes: 0, chapters: 0, assets: 0}},
    };
    return route.fulfill({json: bodies[url.pathname] || {}, headers: jsonHeaders});
  });
  await page.route('https://panther.place/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/config.js') return route.fulfill({contentType: 'application/javascript', body: 'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file = path.join(__dirname, '../../web/media-explorer', ['/app.js', '/styles.css', '/ui-runtime.js', '/ui-system.css'].includes(pathname) ? pathname.slice(1) : 'index.html');
    return route.fulfill({body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
  });
}

async function expectGraphNode(graph, label, {fitsWithoutScroll = false} = {}) {
  const placed = await graph.locator('.pipeline-scroll').evaluate((el, args) => {
    const target = [...el.querySelectorAll('button')].find(button => button.getAttribute('aria-label') === args.label);
    const measure = () => {
      const box = target.getBoundingClientRect();
      const port = el.getBoundingClientRect();
      const title = target.querySelector('strong').getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + Math.min(24, box.width / 2), box.top + box.height / 2);
      return {
        inside: box.width >= 160 && box.left >= port.left - 1 && box.right <= port.right + 1 && box.top >= port.top - 1 && box.bottom <= port.bottom + 1 && box.left >= -1 && box.right <= window.innerWidth + 1,
        titleInside: title.left >= box.left - 1 && title.right <= box.right + 1 && title.top >= box.top - 1 && title.bottom <= box.bottom + 1,
        pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        hit: Boolean(hit && target.contains(hit)),
        scrollLeft: el.scrollLeft,
      };
    };
    if (args.fitsWithoutScroll) el.scrollLeft = 0;
    const reading = measure();
    if (!reading.inside && !args.fitsWithoutScroll) {
      target.scrollIntoView({block: 'nearest', inline: 'nearest'});
      return measure();
    }
    return reading;
  }, {label, fitsWithoutScroll});
  expect(placed.inside, label).toBe(true);
  expect(placed.titleInside, label).toBe(true);
  expect(placed.pageOverflow, label).toBe(false);
  expect(placed.hit, label).toBe(true);
}

for (const width of [1280, 390]) {
  test(`session pipeline is the landing graph at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await openHome(page);
    await page.goto('https://panther.place/');
    await expect(page).toHaveURL('https://panther.place/games/campaign-a/pipeline');
    await expect(page.getByRole('navigation', {name: 'Panther sections'}).getByRole('link', {name: 'Pipeline', exact: true})).toHaveAttribute('aria-current', 'page');
    const graph = page.getByRole('region', {name: 'Pipeline'});
    await expect(graph.getByRole('heading', {name: 'Pipeline', exact: true})).toBeVisible();
    await expect(graph.locator('.pipeline-session')).toHaveText('Night one');
    const done = graph.getByRole('button', {name: 'Session audio, Done'});
    const failed = graph.getByRole('button', {name: 'Transcription, Failed'});
    const running = graph.getByRole('button', {name: 'Transcript cleanup, Running'});
    const gate = graph.getByRole('button', {name: 'Storyboard approval, Needs approval'});
    const waiting = graph.getByRole('button', {name: 'Video generation, Not started'});
    await expect(done).toBeVisible();
    await expect(failed).toContainText('×');
    await expect(running).toBeVisible();
    await expect(gate).toBeVisible();
    await expect(waiting).toBeVisible();
    const color = async element => element.evaluate(node => getComputedStyle(node).borderTopColor);
    expect(await color(done)).toBe('rgb(31, 138, 86)');
    expect(await color(failed)).toBe('rgb(196, 60, 60)');
    expect(await color(running)).toBe('rgb(59, 130, 246)');
    expect(await color(waiting)).toBe('rgb(109, 106, 98)');
    expect(await color(gate)).toBe('rgb(230, 183, 92)');
    expect(await running.evaluate(node => getComputedStyle(node).animationName)).toBe('pipeline-pulse');
    await expectGraphNode(graph, 'Session audio, Done', {fitsWithoutScroll: true});
    await expectGraphNode(graph, 'Video generation, Not started', {fitsWithoutScroll: width === 1280});
    const scrollport = await graph.locator('.pipeline-scroll').evaluate(el => {
      const box = el.getBoundingClientRect();
      return {overflows: el.scrollWidth > el.clientWidth + 1, barVisible: box.bottom <= window.innerHeight + 1 && box.top >= 0};
    });
    expect(scrollport.overflows).toBe(width !== 1280);
    if (width === 390) expect(scrollport.barVisible).toBe(true);
    await expect(graph.getByRole('list', {name: 'Workers'})).toContainText('Editorial online');
    await expect(graph.getByRole('listitem').filter({hasText: 'Playback offline'})).toBeVisible();
    await expect(graph.getByRole('alert')).toContainText('Worker offline or its Panther sign-in expired.');
    await failed.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('alert')).toContainText('Recognizer rejected the audio.');
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await gate.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog')).toContainText('Paid video stays blocked until this storyboard revision is approved.');
    await page.keyboard.press('Escape');
    await graph.getByRole('combobox', {name: 'Session'}).click();
    await page.getByRole('option', {name: 'Dawn', exact: true}).click();
    await expect(page).toHaveURL('https://panther.place/games/campaign-a/pipeline/session-dawn');
    const quiet = graph.getByRole('button', {name: 'Transcription, Not started'});
    await expect(quiet).toBeVisible();
    await quiet.scrollIntoViewIfNeeded();
    expect(await quiet.evaluate(element => {
      const box = element.getBoundingClientRect();
      const hit = document.elementFromPoint(box.x + Math.min(24, box.width / 2), box.y + box.height / 2);
      return element.contains(hit);
    })).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.getByRole('link', {name: 'Dashboard', exact: true}).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.getByRole('link', {name: 'Panther home'}).click();
    await expect(page).toHaveURL('https://panther.place/games/campaign-a/pipeline');
    await expect(graph.getByRole('button', {name: 'Transcription, Failed'})).toBeVisible();
  });
}

for (const width of [1280, 390]) {
  test(`a long session pipeline scrolls inside the graph at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await openHome(page);
    await page.goto('https://panther.place/games/campaign-a/pipeline/session-wide');
    const graph = page.getByRole('region', {name: 'Pipeline'});
    await expect(graph.locator('.pipeline-session')).toHaveText('Long night');
    const scroller = graph.locator('.pipeline-scroll');
    const last = graph.getByRole('button', {name: 'Corrected transcript, Not started'});
    const columnWidth = await graph.locator('.pipeline-column').first().evaluate(node => node.getBoundingClientRect().width);
    expect(columnWidth).toBeGreaterThanOrEqual(180);
    const clipped = await scroller.evaluate(el => {
      const target = [...el.querySelectorAll('button')].find(button => button.getAttribute('aria-label') === 'Corrected transcript, Not started');
      const box = target.getBoundingClientRect();
      return box.right > el.getBoundingClientRect().right + 1;
    });
    expect(clipped).toBe(true);
    await expectGraphNode(graph, 'Corrected transcript, Not started');
    expect(await last.evaluate(node => node.getBoundingClientRect().width)).toBeGreaterThanOrEqual(160);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}
