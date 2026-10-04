// My ads (a tab of Ads): what is on air, the list with its limits and order, uploads, the break card and the
// corner picture, and what aired. node tests/browser_ui_my_ads.cjs /path/to/playwright
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
    'DELETE /v1/my-ads/ads/*': (body, F) => F.my_ads,
  }});
  const {page} = t;
  await page.waitForSelector('#my-list li.ad');

  // On air: the ad playing, how far in, and the quick fixes.
  assert.equal(await page.locator('#my-status').textContent(), "Cousin Vinny's Pizza");
  assert.equal(await page.locator('#progress-text').textContent(), '0:12 / 0:30');
  assert.match(await page.locator('#next').textContent(), /readying the next/);
  assert.equal(await page.locator('#mode-note').isVisible(), false, 'ad mute is On');
  assert.deepEqual(await posted(t, () => page.locator('#my-unmute').click()), {method: 'POST', path: '/v1/admute/override', body: {action: 'unmute'}});

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
  assert.match(await t.page.locator('#next').textContent(), /Plays next: Hometown Hardware/);
  assert.match(await t.page.locator('#my-list li.ad').nth(2).innerText(), /Plays next/i);
  assert.match(await t.page.locator('#mode-note').innerText(), /Ad mute is in shadow: it mutes nothing/);
  assert.equal(await t.page.locator('#my-unmute').isDisabled(), true, 'no quick fixes while ad mute is not On');
  assert.equal(await overflow(t.page), 0, 'fits a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
