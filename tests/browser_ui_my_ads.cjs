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
    'POST /v1/my-ads/ads/*': (body, F) => F.my_ads, 'POST /v1/my-ads/order': (body, F) => F.my_ads,
    // Reset all limits: every ad switched on may air again.
    'POST /v1/my-ads': (body, F) => !body.limits_from ? F.my_ads : {...F.my_ads, settings: {...F.my_ads.settings, limits_from: 1790908800},
      ads: F.my_ads.ads.map(a => ({...a, allowed: a.enabled, again: null}))},
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
  // Out of an MLB game, Baseball may still be queued by hand; a promo that cannot air at all may not.
  const baseball = page.locator('#queue-pick option[value="promo:baseball"]');
  assert.equal(await baseball.isDisabled(), false, 'queued by hand, a sports promo airs during any programme');
  assert.match(await baseball.textContent(), /off its league: airs when queued/);
  assert.equal(await page.locator('#queue-pick option[value="promo:time-temp"]').isDisabled(), true, 'no temperature reading');
  // The search narrows the picker and chooses the first match; Enter adds it to the queue.
  await page.locator('#queue-find').fill('BASE');
  assert.deepEqual(await page.locator('#queue-pick option[value]:not([value=""])').evaluateAll(os => os.map(o => o.value)), ['promo:baseball']);
  assert.equal(await page.locator('#queue-pick').inputValue(), 'promo:baseball');
  assert.deepEqual((await posted(t, () => page.locator('#queue-find').press('Enter'))).body,
    {op: 'add', kind: 'promo', id: 'baseball', next: false});
  await page.locator('#queue-find').fill('zzz no such');
  assert.equal(await page.locator('#queue-pick option').first().textContent(), 'Nothing matches');
  await page.locator('#queue-find').fill('');
  await page.waitForTimeout(500);      // the page fetches My ads again 0.4 s after a command
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

  // Reset all limits: lit while an ad sits out, saying which; then every ad switched on may air.
  const reset = page.locator('#reset-limits');
  assert.equal(await page.locator('#limits-note').textContent(), 'Rocket Lawn Care sits out over its limit now.');
  assert.ok((await reset.getAttribute('class')).includes('primary'));
  assert.deepEqual(await posted(t, () => reset.click()), {method: 'POST', path: '/v1/my-ads', body: {limits_from: 'now'}});
  assert.match(await page.locator('.toasts .toast').last().textContent(), /^Limits reset: Rocket Lawn Care may air now\.$/);
  assert.match(await page.locator('#limits-note').textContent(), /^No ad is over its limit now\. Last reset (\w{3} )?\d{1,2}:\d\d\s?[AP]M\.$/);
  assert.equal((await reset.getAttribute('class')).includes('primary'), false);
  assert.doesNotMatch(await rows.nth(1).innerText(), /Sits out until/i);

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

  // A channel instead: our channels to choose from, an ident opening the break, then the channel.
  const TV = 'http://127.0.0.1:8080/stream/';
  const OURS = [{id: 'internet:cabride', name: 'Trains', number: 1, note: 'Train cab rides', url: TV + 'internet/cabride/index.m3u8'},
    {id: 'internet:pentulive', name: 'pen2live', number: 2, note: 'Yle\'s puppy cam', url: TV + 'internet/pentulive/index.m3u8'},
    {id: 'slides:sports-guide', name: 'VizelVision Sports Guide', number: 6, note: null, url: TV + 'sports-guide/index.m3u8'}];
  t = await open(browser, '/ads#my-ads', {width: 390, edit: F => {
    Object.assign(F.my_ads.settings, {breaks: 'channel', channel_ident: true,
      break_channel: {url: OURS[0].url, name: 'Trains', number: 1}});
    F.my_ads.channels = {channels: OURS, error: null};
    Object.assign(F.my_ads.status, {state: 'promo', ad: null, breaks: 'channel', channel_ident: true,
      promo: {id: 'forecast', name: 'The VizelVision Forecast', duration: 10, position: 3, since: 1790907300}});
    F.my_ads.recent.unshift({kind: 'channel', id: 'channel', name: '1 Trains', at: 1790907000, seconds: 150.1});
  }, api: {'POST /v1/my-ads': (body, F) => F.my_ads}});
  const cp = t.page;
  await cp.waitForSelector('#break-channel option', {state: 'attached'});
  assert.equal(await cp.locator('#breaks-channel').textContent(), 'Channel 1');
  assert.equal(await cp.locator('#breaks-channel').getAttribute('aria-pressed'), 'true');
  assert.equal(await cp.locator('#my-status').textContent(), 'The VizelVision Forecast');
  assert.match(await cp.locator('#my-status-detail').textContent(), /A VizelVision ident opens this break; then 1 Trains, live/);
  assert.equal(await cp.locator('#state-chip').textContent(), 'ident');
  assert.deepEqual(await cp.locator('#break-channel option').allTextContents(), ['1 Trains', '2 pen2live', '6 VizelVision Sports Guide']);
  assert.equal(await cp.locator('#channel-ident').isChecked(), true);
  assert.match(await cp.locator('#channel-note').textContent(), /Train cab rides\. The ident is the next station promo/);
  assert.match(await cp.locator('#recent').innerText(), /Channel\s+1 Trains\s+2:30/i);
  assert.deepEqual(await posted(t, () => cp.locator('#break-channel').selectOption({label: '2 pen2live'})),
    {method: 'POST', path: '/v1/my-ads', body: {break_channel: {url: OURS[1].url, name: 'pen2live', number: 2}}});
  assert.deepEqual(await posted(t, () => cp.locator('#channel-ident').uncheck()),
    {method: 'POST', path: '/v1/my-ads', body: {channel_ident: false}});
  assert.equal(await overflow(cp), 0, 'fits a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // A saved channel TV Thing no longer lists: still shown, and said so.
  t = await open(browser, '/ads#my-ads', {edit: F => {
    Object.assign(F.my_ads.settings, {breaks: 'channel', channel_ident: false,
      break_channel: {url: 'http://127.0.0.1:8791/cab/index.m3u8', name: 'Cab Ride', number: 144}});
    F.my_ads.channels = {channels: OURS, error: null};
    Object.assign(F.my_ads.status, {state: 'idle', ad: null, active: true});
  }});
  await t.page.waitForSelector('#break-channel option', {state: 'attached'});
  assert.equal(await t.page.locator('#breaks-channel').textContent(), 'Channel 144');
  assert.equal(await t.page.locator('#break-channel option').first().textContent(), '144 Cab Ride (not in Our channels now)');
  assert.match(await t.page.locator('#channel-note').textContent(), /not one of our channels any more[\s\S]*cut straight to the channel/);
  assert.match(await t.page.locator('#my-status-detail').textContent(), /The next break ad mute mutes shows 144 Cab Ride, live/);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
