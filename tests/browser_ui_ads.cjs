// Ad database (a tab of Ads): every known clip with its script and pictures; search, filters,
// naming, forgetting. Then the Ads page's tabs. node tests/browser_ui_ads.cjs /path/to/playwright
const {open, run, assert, overflow} = require('./ui_harness.cjs');

const CLIPS = [
  {id: 12, kind: 'ad', known: true, breaks: 3, need: 2, first: 1790900000, last: 1790906700, dur: 29.5, src: 'TBS', seed: null, hashes: 900,
    pics: 4, name: null, script: [[0.4, 'Fifteen minutes could save you'], [2.9, 'fifteen percent or more on car insurance.']], script_cover: 1, script_from: 'broadcast'},
  {id: 7, kind: 'show', known: true, breaks: 2, first: 1790800000, last: 1790905000, dur: 9.0, src: 'Jeopardy! - 7.1 WJLA - 2026-09-28 1930.mp4',
    seed: 'extra', hashes: 280, pics: 0, script: [[0, 'This is Jeopardy!']], script_cover: 1},
  {id: 53, kind: 'ad', known: false, breaks: 1, need: 2, spot: 'pod', first: 1790906000, last: 1790906000, dur: 15.0, src: 'TBS', seed: null,
    hashes: 400, pics: 0, script: null},
  {id: 2, kind: 'ad', known: true, breaks: 1, need: 2, first: 1790000000, last: 1790000000, dur: 247.0, src: 'Jeopardy! - 7.1 WJLA - 2026-09-23 1930.mp4',
    seed: 'extra-20261003-103008', hashes: 7997, pics: 2, name: 'Taco Bell Luxe Box', script: Array.from({length: 12}, (_, i) => [i * 20, `line ${i} of the break`]),
    script_cover: 0.4, script_from: 'recording'},
  {id: 60, kind: 'ad', known: true, breaks: 2, need: 3, first: 1790906100, last: 1790906600, dur: 30.0, src: 'FOX', seed: null, hashes: 800, pics: 1, script: []},
];

run(async browser => {
  let t = await open(browser, '/ads#database', {api: {
    'GET /v1/admute/known': () => ({updated: 1790907300, clips: CLIPS}),
    'POST /v1/admute/name': () => ({ok: true}),
    'POST /v1/admute/forget': () => ({}),
  }});
  const page = t.page;
  await page.waitForSelector('#db-ads .ad');
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);

  // The tally, and ads (not show sounds) by default, most recently heard first.
  assert.equal(await page.locator('#n-known').textContent(), '3');
  assert.equal(await page.locator('#n-learning').textContent(), '1');
  assert.equal(await page.locator('#n-show').textContent(), '1');
  assert.equal(await page.locator('#n-scripted').textContent(), '3 / 4');
  assert.equal(await page.locator('#db-ads .ad').count(), 4);
  const titles = await page.locator('#db-ads .ad .title h2').allTextContents();
  assert.deepEqual(titles, ['“Fifteen minutes could save you”', 'Ad #60', 'Ad #53', 'Taco Bell Luxe Box']);

  // Each ad: its status, what it said (with times), and where the words stand.
  const geico = page.locator('#db-ads .ad').nth(0);
  assert.match(await geico.locator('.chip').textContent(), /Known ad/i);
  assert.match(await geico.locator('.script').textContent(), /0:00Fifteen minutes could save you0:03fifteen percent/);
  assert.match(await geico.locator('.facts').textContent(), /heard 3×.*from TBS/);
  assert.match(await page.locator('#db-ads .ad').nth(1).locator('.script').textContent(), /No words: music or sound only/);
  const pod = page.locator('#db-ads .ad').nth(2);
  assert.match(await pod.locator('.chip').textContent(), /needs 1 more airing/i);
  assert.match(await pod.locator('.script').textContent(), /next time this ad airs/);
  assert.match(await pod.locator('.pics').textContent(), /No pictures yet/);
  const taco = page.locator('#db-ads .ad').nth(3);
  assert.match(await taco.textContent(), /Partial: 40% of it heard so far/);
  assert.match(await taco.locator('.facts').textContent(), /from Jeopardy! - 7.1 WJLA - 2026-09-23 1930/);
  assert.ok(await taco.locator('.script.folded').count(), 'a long script folds');
  await taco.getByRole('button', {name: 'All 12 lines'}).click();
  assert.equal(await taco.locator('.script.folded').count(), 0);

  // Pictures load as they scroll into view, with the API key.
  await page.waitForFunction(() => [...document.querySelectorAll('#db-ads .ad .pics img')].some(i => i.src.startsWith('blob:')));
  assert.ok(t.frames.includes('/v1/admute/ad/12-0.jpg'));

  // Search finds words in scripts (and marks them), names and programmes.
  await page.fill('#find', 'percent');
  assert.equal(await page.locator('#db-ads .ad').count(), 1);
  assert.equal(await page.locator('#db-ads .ad mark').first().textContent(), 'percent');
  await page.fill('#find', 'luxe');
  assert.deepEqual(await page.locator('#db-ads .ad .title h2').allTextContents(), ['Taco Bell Luxe Box']);
  await page.fill('#find', 'nothing like this');
  assert.ok(await page.locator('#db-empty').isVisible());
  await page.fill('#find', '');

  // Filters and sort.
  await page.click('[data-filter=show]');
  assert.deepEqual(await page.locator('#db-ads .ad .title h2').allTextContents(), ['“This is Jeopardy!”']);
  assert.match(await page.locator('#db-ads .ad .chip').textContent(), /Show sound/i);
  await page.click('[data-filter=learning]');
  assert.equal(await page.locator('#db-ads .ad').count(), 1);
  await page.click('[data-filter=ads]');
  await page.selectOption('#sort', 'dur');
  assert.equal(await page.locator('#db-ads .ad .title h2').first().textContent(), 'Taco Bell Luxe Box');
  await page.selectOption('#sort', 'last');

  // Name an ad.
  await geico.getByRole('button', {name: 'Name'}).click();
  await page.fill('#db-ads .ad .title input', 'GEICO');
  await page.click('#db-ads .ad .title button[type=submit]');
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/admute/name', body: {clip: 12, name: 'GEICO'}});
  await page.waitForFunction(() => !document.querySelector('#db-ads .ad .title form'));
  assert.equal(await page.locator('#db-ads .ad .title h2').first().textContent(), 'GEICO');

  // Forget one (asks first).
  await page.locator('#db-ads .ad').nth(2).getByRole('button', {name: 'Forget'}).click();
  await page.getByRole('dialog').getByRole('button', {name: 'Forget'}).click();
  await page.waitForFunction(() => document.querySelectorAll('#db-ads .ad').length === 3);
  assert.deepEqual(t.posts.at(-1).body, {clips: [53]});

  // "/" focuses the search; the nav names the page.
  await page.locator('body').click({position: {x: 5, y: 600}});
  await page.keyboard.press('/');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'find');
  assert.match(await page.locator('header.topbar [aria-current=page]').textContent(), /Ads/i);
  await t.ctx.close();

  // Phone width: no sideways scroll.
  t = await open(browser, '/ads#database', {width: 390, height: 844, api: {'GET /v1/admute/known': () => ({updated: 1, clips: CLIPS})}});
  await t.page.waitForSelector('#db-ads .ad');
  assert.equal(await overflow(t.page), 0);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // The tabs: Ad mute first, each at its #name, the last one remembered; only the tab on screen
  // is polled; the quick-fix keys belong to their tab; links between tabs switch them.
  const watched = p => p.evaluate(() => [...VV.watchers.keys()].filter(k => k.startsWith('v1/admute') || k.startsWith('v1/my-ads')).sort());
  const shown = p => p.evaluate(() => [...document.querySelectorAll('[role=tabpanel]')].filter(n => !n.hidden).map(n => n.id));
  t = await open(browser, '/ads', {edit: F => { F.my_ads.admute_mode = 'shadow'; },
    api: {'GET /v1/admute/known': () => ({updated: 1, clips: CLIPS}), 'POST /v1/admute/override': () => ({override: {accepted: true}})}});
  await t.page.waitForSelector('#spans tr');
  assert.deepEqual(await shown(t.page), ['panel-admute']);
  assert.match(t.page.url(), /\/ads#admute$/);
  assert.equal(await t.page.locator('#tab-admute').getAttribute('aria-selected'), 'true');
  assert.deepEqual(await watched(t.page), ['v1/admute', 'v1/admute/recordings']);
  await t.page.getByRole('tab', {name: 'My ads'}).click();
  await t.page.waitForSelector('#my-list li.ad');
  assert.deepEqual(await shown(t.page), ['panel-my-ads']);
  assert.match(t.page.url(), /#my-ads$/);
  assert.deepEqual(await watched(t.page), ['v1/my-ads']);
  assert.equal(await t.page.evaluate(() => localStorage.getItem('vv.adsTab')), '"my-ads"');
  await t.page.locator('#mode-note a').click();
  await t.page.waitForFunction(() => !document.getElementById('panel-admute').hidden);
  assert.deepEqual(await shown(t.page), ['panel-admute'], 'My ads sends you to turn ad mute On');
  await t.page.locator('a[href="#database"]').click();
  await t.page.waitForSelector('#db-ads .ad');
  assert.deepEqual(await shown(t.page), ['panel-database']);
  assert.deepEqual(await watched(t.page), ['v1/admute/known']);
  const sent = t.posts.length;
  await t.page.locator('body').click({position: {x: 5, y: 600}});
  await t.page.keyboard.press('u');
  await t.page.waitForTimeout(150);
  assert.equal(t.posts.length, sent, 'no quick fix from the database tab');
  await t.page.locator('#tab-database').focus();
  await t.page.keyboard.press('ArrowLeft');
  assert.deepEqual(await shown(t.page), ['panel-admute']);
  await t.page.keyboard.press('u');
  await t.page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/admute/override', body: {action: 'unmute'}});
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);
  await t.ctx.close();
  t = await open(browser, '/ads', {storage: {adsTab: 'database'}, api: {'GET /v1/admute/known': () => ({updated: 1, clips: CLIPS})}});
  await t.page.waitForSelector('#db-ads .ad');
  assert.deepEqual(await shown(t.page), ['panel-database'], 'the last tab, when the address names none');
  await t.ctx.close();
});
