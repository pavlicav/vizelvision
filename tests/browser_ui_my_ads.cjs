// My ads (a tab of Ads): what is on air, Next up (skip, queue by hand), the list with its limits and order,
// uploads, the break card and the corner picture, what aired, and the mix (kinds of ads). node tests/browser_ui_my_ads.cjs /path/to/playwright
const {open, run, overflow, assert} = require('./ui_harness.cjs');

const VINNY = '3f9c1a2b4d5e', ROCKET = '7a1e0c9d8b2f', HARDWARE = 'c0ffee123456';

// Does action, then waits for what it sends (and the answer to be drawn): the last request.
async function posted(t, action) {
  const n = t.posts.length;
  await action();
  for (let i = 0; i < 150 && t.posts.length === n; i++) await t.page.waitForTimeout(20);
  await t.page.waitForTimeout(40);
  return t.posts.at(-1);
}

run(async browser => {
  const added = {id: 'abcdef012345', file: 'abcdef012345.mp4', name: 'spot', duration: 30, width: 1280, height: 720, audio: true,
    lufs: -24, gain_db: 4, trim_db: 0, bytes: 2048, pics: 0, enabled: true, limit: {count: 1, minutes: 60}, present: true,
    allowed: true, again: null, played: {hour: 0, day: 0, week: 0, last: null}};
  let t = await open(browser, '/ads#my-ads', {api: {
    'POST /v1/my-ads/upload': (body, F) => ({...F.my_ads, ads: [...F.my_ads.ads, added], added: added.id}),
    'POST /v1/admute/override': () => ({override: {accepted: true}}),
    'POST /v1/my-ads/ads/*': (body, F) => F.my_ads, 'POST /v1/my-ads': (body, F) => F.my_ads, 'POST /v1/my-ads/order': (body, F) => F.my_ads,
    'DELETE /v1/my-ads/ads/*': (body, F) => F.my_ads, 'POST /v1/my-ads/next': (body, F) => F.my_ads,
  }});
  const {page} = t;
  await page.waitForSelector('#my-list li.ad');

  // On air: the ad playing, how far in, and the quick fixes.
  assert.equal(await page.locator('#my-status').textContent(), "Cousin Vinny's Pizza");
  assert.equal(await page.locator('#progress-text').textContent(), '0:12 / 0:30');
  assert.match(await page.locator('#next').textContent(), /Plays next: Rocket Lawn Care \(0:15\)/, 'Next up\'s first');
  assert.equal(await page.locator('#mode-note').isVisible(), false, 'ad mute is On');
  assert.deepEqual(await posted(t, () => page.locator('#my-unmute').click()), {method: 'POST', path: '/v1/admute/override', body: {action: 'unmute'}});

  // Next up: what you queued, the promo where its timing puts it. Skip one, skip what is on air, queue by hand.
  const next = page.locator('#nextup li');
  assert.equal(await next.count(), 3);
  assert.match(await next.nth(0).innerText(), /Rocket Lawn Care[\s\S]*Queued by you[\s\S]*0:15[\s\S]*in 0:18/i);
  assert.match(await next.nth(1).innerText(), /The VizelVision Line[\s\S]*Station promo[\s\S]*0:10[\s\S]*in 0:33/i);
  assert.match(await page.locator('#next-when').textContent(), /In this break/);
  assert.ok(t.frames.some(f => f.endsWith('/v1/promos/file/metro.png')), 'the promo\'s still');
  assert.deepEqual(await posted(t, () => next.nth(1).getByRole('button', {name: 'Skip The VizelVision Line'}).click()),
    {method: 'POST', path: '/v1/my-ads/next', body: {op: 'skip', key: 'c4d2e8f1'}});
  assert.equal(await page.locator('#skip-now').innerText(), 'Skip this ad');
  assert.deepEqual(await posted(t, () => page.locator('#skip-now').click()),
    {method: 'POST', path: '/v1/my-ads/next', body: {op: 'skip', key: '5e1f02aa'}});
  assert.equal(await page.locator('#queue-pick option[value="promo:baseball"]').isDisabled(), true, 'only during MLB games');
  await page.locator('#queue-pick').selectOption('promo:legal');
  assert.deepEqual((await posted(t, () => page.getByRole('button', {name: 'Play next'}).click())).body,
    {op: 'add', kind: 'promo', id: 'legal', next: true});
  await page.locator('#queue-pick').selectOption('ad:' + VINNY);
  assert.deepEqual((await posted(t, () => page.getByRole('button', {name: 'Add to queue'}).click())).body,
    {op: 'add', kind: 'ad', id: VINNY, next: false});
  assert.deepEqual((await posted(t, () => page.locator('#my-list li.ad').nth(1).getByRole('button', {name: 'Queue'}).click())).body,
    {op: 'add', kind: 'ad', id: ROCKET, next: false});

  // The list, in order, with what each is doing.
  const rows = page.locator('#my-list li.ad');
  assert.equal(await rows.count(), 3);
  assert.deepEqual(await rows.locator('h3').allTextContents(), ["Cousin Vinny's Pizza", 'Rocket Lawn Care', 'Hometown Hardware']);
  assert.match(await rows.nth(0).innerText(), /On air/i);
  assert.match(await rows.nth(1).innerText(), /Sits out until/i);
  assert.match(await rows.nth(1).innerText(), /levelled -3.8 dB/);
  assert.match(await rows.nth(2).innerText(), /OFF/i);
  assert.match(await rows.nth(2).innerText(), /no sound/);
  assert.ok((await rows.nth(2).getAttribute('class')).includes('off'));
  assert.equal(await rows.nth(1).locator('select[aria-label=Limit]').inputValue(), '1/60');
  assert.equal(await rows.nth(2).locator('select[aria-label=Volume]').inputValue(), '-3');
  assert.ok(t.frames.some(f => f.endsWith(`/v1/my-ads/file/${VINNY}-0.jpg`)), 'its pictures');

  // Switch one on, give one a limit (a preset and a custom one), move one down.
  assert.deepEqual(await posted(t, () => rows.nth(2).locator('.switch').click()), {method: 'POST', path: `/v1/my-ads/ads/${HARDWARE}`, body: {enabled: true}});
  assert.deepEqual((await posted(t, () => rows.nth(0).locator('select[aria-label=Limit]').selectOption('1/60'))).body, {limit: {count: 1, minutes: 60}});
  await page.locator('#my-list li.ad').nth(0).locator('select[aria-label=Limit]').selectOption('custom');
  const custom = page.getByRole('dialog', {name: 'Custom limit'});
  await custom.getByLabel('Times').fill('3');
  await custom.getByLabel('Minutes').fill('90');
  assert.deepEqual(await posted(t, () => custom.getByRole('button', {name: 'Set limit'}).click()),
    {method: 'POST', path: `/v1/my-ads/ads/${VINNY}`, body: {limit: {count: 3, minutes: 90}}});
  assert.deepEqual(await posted(t, () => page.locator('#my-list li.ad').nth(0).getByRole('button', {name: 'Move down'}).click()),
    {method: 'POST', path: '/v1/my-ads/order', body: {ids: [ROCKET, VINNY, HARDWARE]}});

  // Rename.
  await page.locator('#my-list li.ad').nth(1).getByRole('button', {name: 'Rename'}).click();
  await page.locator('#my-list li.ad').nth(1).getByLabel('Name').fill('Rocket Lawn Care (fall)');
  assert.deepEqual((await posted(t, () => page.locator('#my-list li.ad').nth(1).getByRole('button', {name: 'Save'}).click())).body,
    {name: 'Rocket Lawn Care (fall)'});

  // Order, the card, the corner.
  assert.deepEqual((await posted(t, () => page.locator('#order [data-order=list]').click())).body, {order: 'list'});
  await page.getByRole('button', {name: "WE'LL BE RIGHT BACK"}).click();
  assert.deepEqual(await posted(t, () => page.locator('#card-save').click()),
    {method: 'POST', path: '/v1/my-ads', body: {card: {text: "WE'LL BE RIGHT BACK"}}});
  assert.ok(t.frames.some(f => f.endsWith('/v1/my-ads/file/card-b5f05a075b.png')), 'the card is shown');
  assert.deepEqual((await posted(t, () => page.locator('#pip-corner').selectOption('top-left'))).body, {pip: {corner: 'top-left'}});
  assert.deepEqual((await posted(t, () => page.locator('#pip-size').selectOption('large'))).body, {pip: {size: 'large'}});

  // Upload: a video goes up as the request body; anything else is turned away here.
  const before = t.posts.length;
  await page.locator('#files').setInputFiles([{name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('hello')},
    {name: 'spot.mp4', mimeType: 'video/mp4', buffer: Buffer.alloc(2048, 7)}]);
  await page.locator('#uploads li.done').waitFor();
  const uploads = t.posts.slice(before).filter(p => p.path === '/v1/my-ads/upload');
  assert.deepEqual(uploads, [{method: 'POST', path: '/v1/my-ads/upload', body: {upload: 2048}}]);
  assert.match(await page.locator('#uploads li.failed').innerText(), /Not a video/);
  assert.match(await page.locator('#uploads li.done').innerText(), /Added · 0:30 · once an hour/);
  assert.equal(await page.locator('#my-list li.ad').count(), 4, 'listed at once');

  // Delete asks first.
  await page.locator('#my-list li.ad').nth(3).getByRole('button', {name: 'Delete'}).click();
  assert.deepEqual(await posted(t, () => page.getByRole('dialog').getByRole('button', {name: 'Delete'}).click()),
    {method: 'DELETE', path: '/v1/my-ads/ads/abcdef012345', body: null});

  // What aired: newest first; a deleted ad keeps its name; cut-short plays say so.
  const aired = page.locator('#recent tr');
  assert.equal(await aired.count(), 5);
  assert.match(await aired.nth(0).innerText(), /Cousin Vinny's Pizza\s+0:30 of 0:30\s+complete/);
  assert.match(await aired.nth(1).innerText(), /Break card\s+1:04/i);
  assert.match(await aired.nth(2).innerText(), /Old spot \(deleted\)/);
  assert.match(await aired.nth(3).innerText(), /cut short: the programme came back · didn't count/);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // The break card on air, an ad cued, and ad mute not On.
  t = await open(browser, '/ads#my-ads', {width: 390, edit: F => {
    F.my_ads.admute_mode = 'shadow';
    Object.assign(F.my_ads.status, {state: 'card', ad: null, card_since: 1790907300, cued: HARDWARE});
    F.my_ads.ads[2] = {...F.my_ads.ads[2], enabled: true, allowed: true};
  }});
  await t.page.waitForSelector('#my-list li.ad');
  assert.equal(await t.page.locator('#my-status').textContent(), 'Break card');
  assert.match(await t.page.locator('#next').textContent(), /Plays next: Rocket Lawn Care/);
  assert.equal(await t.page.locator('#skip-now').isVisible(), false, 'nothing to skip under the card');
  assert.match(await t.page.locator('#my-list li.ad').nth(2).innerText(), /Plays next/i);
  assert.match(await t.page.locator('#mode-note').innerText(), /Ad mute is in shadow: it mutes nothing/);
  assert.equal(await t.page.locator('#my-unmute').isDisabled(), true, 'no quick fixes while ad mute is not On');
  assert.equal(await overflow(t.page), 0, 'fits a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // The mix (ad_mix.py; tuned on the Mix tab, browser_ui_mix.cjs): each ad's kind and chance, the kinds' shares, a kind on upload.
  const MIX = {enabled: true, aired_day: 10,
    categories: [{key: 'local', name: 'Local & regional', weight: 1, wear: 1, about: 'Someone\'s local ad', ads: 2, day: 8},
      {key: 'cats', name: 'Cats & animals', weight: 2, wear: 1, about: 'Real animals', ads: 0, day: 0},
      {key: 'slop', name: 'AI slop & memes', weight: 0, wear: 1, about: 'Diffusion video', ads: 0, day: 0}],
    unsorted: {ads: 1, day: 2, weight: 1}};
  t = await open(browser, '/ads#my-ads', {width: 390, edit: F => {
    F.my_ads.mix = MIX;
    Object.assign(F.my_ads.ads[0], {category: 'local', plays_all: 50, seen: 30, chance: 0.004, boost: 1, wear: 1});
    Object.assign(F.my_ads.ads[1], {category: 'local', plays_all: 3, seen: 3, chance: 0.6, boost: 2, wear: 0});
    Object.assign(F.my_ads.ads[2], {category: null, plays_all: 0, seen: 0, chance: 1, boost: 0, wear: 1, enabled: true, allowed: true});
  }, api: {'POST /v1/my-ads/mix': (body, F) => F.my_ads, 'POST /v1/my-ads/ads/*': (body, F) => F.my_ads, 'POST /v1/my-ads': (body, F) => F.my_ads,
    'POST /v1/my-ads/upload': (body, F) => ({...F.my_ads, ads: [...F.my_ads.ads, {...added, category: 'cats'}], added: added.id})}});
  const mp = t.page;
  const uploadUrls = [];
  mp.on('request', r => { if (r.url().includes('/v1/my-ads/upload')) uploadUrls.push(new URL(r.url()).search); });
  await mp.waitForSelector('#mix-list li');
  assert.equal(await mp.locator('#order [data-order=mix]').getAttribute('aria-pressed'), 'true', 'mix on, order shuffle: Mix');
  assert.match(await mp.locator('#order-note').textContent(), /Kinds of ads in balance/);
  const kinds = mp.locator('#mix-list li');
  assert.equal(await kinds.count(), 4, 'three kinds and the unsorted');
  assert.match(await kinds.nth(0).innerText(), /Local & regional\s+2 ads[\s\S]*80% · due 50% · by count 67%/);
  assert.match(await kinds.nth(1).innerText(), /Cats & animals\s+0 ads\s+×2/);
  assert.match(await kinds.nth(2).innerText(), /AI slop & memes[\s\S]*off[\s\S]*0% · due 0%/);
  assert.ok((await kinds.nth(2).getAttribute('class')).includes('off'));
  assert.match(await kinds.nth(3).innerText(), /Unsorted\s+1 ad[\s\S]*20% · due 50% · by count 33%/);
  assert.match(await mp.locator('#mix-unsorted').textContent(), /1 ad has no kind yet/);
  assert.equal(await mp.getByRole('link', {name: 'Tune the mix'}).getAttribute('href'), '#mix', 'the knobs are on the Mix tab');
  const list = mp.locator('#my-list li.ad');
  assert.equal(await list.nth(0).locator('select[aria-label=Kind]').inputValue(), 'local');
  assert.match(await list.nth(0).innerText(), /50 in all\s+·\s+chance <1%/);
  assert.match(await list.nth(1).innerText(), /Never wears out[\s\S]*Boost ×2[\s\S]*chance 60%/i);
  assert.match(await list.nth(2).innerText(), /Left out of the mix/i);
  assert.deepEqual(await posted(t, () => list.nth(2).locator('select[aria-label=Kind]').selectOption('cats')),
    {method: 'POST', path: `/v1/my-ads/ads/${HARDWARE}`, body: {category: 'cats'}});
  await mp.locator('#kind-filter').selectOption('unsorted');
  assert.deepEqual(await mp.locator('#my-list li.ad h3').allTextContents(), ['Hometown Hardware']);
  assert.equal(await mp.locator('#my-list li.ad').getByRole('button', {name: 'Move up'}).isDisabled(), true, 'no reordering a part of the list');
  await mp.locator('#kind-filter').selectOption('');
  assert.equal(await mp.locator('#my-list li.ad').count(), 3);
  // Shuffle turns the mix off; Mix turns it back on.
  assert.deepEqual(await posted(t, () => mp.locator('#order [data-order=shuffle]').click()),
    {method: 'POST', path: '/v1/my-ads/mix', body: {enabled: false}});
  // An upload goes in with the kind chosen for it.
  await mp.locator('#upload-kind').selectOption('cats');
  await mp.locator('#files').setInputFiles([{name: 'tabby.mp4', mimeType: 'video/mp4', buffer: Buffer.alloc(1024, 7)}]);
  await mp.locator('#uploads li.done').waitFor();
  assert.deepEqual(uploadUrls, ['?name=tabby.mp4&category=cats']);
  assert.match(await mp.locator('#uploads li.done').innerText(), /Added · 0:30 · once an hour · Cats & animals/);
  assert.equal(await overflow(mp), 0, 'fits a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
