// Crawl: the register of everything the crawl can air, with its status and actions, and every
// control of the rotation. node tests/browser_ui_crawl.cjs /path/to/playwright
const {open, run, assert, overflow} = require('./ui_harness.cjs');

const BUS = 'bus:d8eab872-cd51-4230-9b50-7b1612fd0cc7', DC = 'alertdc:2b70cb9c97';
const base = {segment: 'alerts', segment_name: 'Weather alerts', label: 'WEATHER', kind: 'alert', tag: '', first_seen: 1790906000, muted: false, new: false,
  issued: '2026-10-02T02:00:00Z', expires: '2026-10-02T03:00:00Z', areas: 'District of Columbia', by: 'NWS Sterling VA', next_at: null, next_how: null};
const severe = {...base, id: 'eas:42', source: 'eas', source_name: 'EAS', layer: 'important', status: 'looping', airing: 'first', air_count: 1, heading: 'TORNADO WARNING',
  text: 'The National Weather Service has issued a Tornado Warning for District of Columbia until 11 PM.', severity: 'warning', event: 'Tornado Warning',
  first_aired: 1790906100, last_aired: 1790906100, airings: [{at: 1790906100, ended: null, how: null, key: 'important', context: 'game', layer: 'important', forced: false, new: false}],
  why: 'Important: runs continuously over everything until it expires'};
const muted = {...base, id: 'nws:urn:oid:2.49.0.1', source: 'nws', source_name: 'NWS', layer: 'rotation', status: 'muted', airing: 'first', air_count: 0, heading: 'FLOOD WATCH',
  text: 'Flood Watch until 8 PM.', severity: 'Moderate', first_aired: null, last_aired: null, airings: [], why: 'Dismissed: taken out of the crawl'};

run(async browser => {
  const t = await open(browser, '/crawl', {
    edit: F => { F.alerts.items.unshift(severe, muted); F.alerts.counts.looping = 1; F.alerts.counts.muted = 1; },
    api: {'POST /v1/crawl/*': (body, F) => F.crawl, 'POST /v1/crawl': (body, F) => F.crawl}});
  const page = t.page;
  await page.waitForSelector(`#reg-body tr.item[data-id="${BUS}"]`);
  const row = id => page.locator(`#reg-body tr.item[data-id="${id}"]`);

  // Alerts first, each with where it stands and when it airs next.
  assert.equal(await page.locator('#reg-body tr.item').count(), 8, 'alerts only: EAS, NWS, Metro and AlertDC');
  assert.match(await row('eas:42').innerText(), /Looping[\s\S]*FIRST[\s\S]*Continuous/i);
  assert.match(await row(BUS).innerText(), /Next[\s\S]*FIRST[\s\S]*≈ 11:\d\d PM[\s\S]*after the game/i);
  assert.match(await row(muted.id).innerText(), /Muted/i);
  assert.equal(await row('eas:42').getByRole('button', {name: /^Air now/}).count(), 0, 'severe alerts already run continuously');
  await page.locator('[data-scope=all]').click();
  assert.equal(await page.locator('#reg-body tr.item').count(), 12, 'everything: weather and Cairo too');
  assert.match(await page.locator('#reg-body').innerText(), /Everything else/i);
  await page.locator('[data-status=held]').click();
  assert.equal(await page.locator('#reg-body tr.item').count(), 0);
  await page.locator('[data-status=""]').click();
  await page.locator('#reg-search').fill('red mass');
  assert.equal(await page.locator('#reg-body tr.item').count(), 1);
  await page.locator('#reg-search').fill('');
  await page.locator('[data-scope=alert]').click();

  // Details: the item's id, times and airings.
  await row('eas:42').click();
  const detail = page.locator('#reg-body tr.detail');
  assert.match(await detail.innerText(), /eas:42[\s\S]*Tornado Warning[\s\S]*Airings/i);
  await row('eas:42').click();
  assert.equal(await detail.count(), 0);

  // Actions: air now, mute, unmute; hold puts it in the override slot.
  await row(BUS).getByRole('button', {name: /^Air now/}).click();
  await row(DC).getByRole('button', {name: /^Mute/}).click();
  await row(muted.id).getByRole('button', {name: /^Unmute/}).click();
  await page.waitForTimeout(300);
  assert.deepEqual(t.posts.map(p => [p.path, p.body]), [['/v1/crawl/alerts/' + encodeURIComponent(BUS), {action: 'air'}],
    ['/v1/crawl/alerts/' + encodeURIComponent(DC), {action: 'mute'}], ['/v1/crawl/alerts/' + encodeURIComponent(muted.id), {action: 'unmute'}]]);
  t.posts.length = 0;
  await row(DC).getByRole('button', {name: /^Hold/}).click();
  const hold = page.getByRole('dialog', {name: 'Hold an item on the bar'});
  await hold.getByRole('combobox').selectOption('60');
  await hold.getByRole('button', {name: 'Hold on the bar'}).click();
  await page.waitForTimeout(200);
  assert.equal(t.posts[0].path, '/v1/crawl/override');
  assert.deepEqual({...t.posts[0].body, text: t.posts[0].body.text.slice(0, 13)}, {text: 'National Capi', label: 'ALERTDC', minutes: 60, style: 'station'});
  t.posts.length = 0;

  // The important message asks first.
  await page.locator('[data-tab=manual]').click();
  await page.locator('[data-id=important-text]').fill('Shelter in place');
  await page.locator('[data-id=important-go]').click();
  await page.getByRole('dialog', {name: 'Important message'}).getByRole('button', {name: 'Put on air'}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.map(p => [p.path, p.body]), [['/v1/crawl/important', {text: 'Shelter in place', label: 'IMPORTANT', minutes: 60}]]);
  t.posts.length = 0;

  // Rules and segments save what changed; segment options go to the feed settings too.
  await page.locator('[data-tab=rules]').click();
  await page.locator('[data-context=program]').selectOption('always');
  await page.locator('[data-id=save-rules]').click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {rules: {per_hour: 4, gap_minutes: 5, program: 'always', game: 'quiet', off_air: 'always', ident: 'quiet'}});
  await page.locator('[data-tab=segments]').click();
  const weather = page.locator('.seg-card[data-segment=weather]');
  await weather.getByLabel('New items pop up at once (once each)').check();
  await page.locator('[data-id=save-segments]').click();
  await page.waitForTimeout(300);
  const [segments, feeds] = t.posts.slice(-2);
  assert.equal(segments.path, '/v1/crawl');
  assert.equal(feeds.path, '/v1/crawl/feeds');
  assert.equal(feeds.body.segments.weather.new_now, true);
  assert.deepEqual(feeds.body.segments.weather.contexts, ['off_air']);
  await weather.getByRole('button', {name: 'Run Weather now'}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {segment: 'weather'});

  // Sources, teams and messages.
  await page.locator('[data-tab=feeds]').click();
  await page.locator('[data-id=nws]').check();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {nws: true});
  await page.locator('[data-id=route-filter]').fill('x2');
  await page.getByRole('checkbox', {name: /X2/}).check();
  await page.locator('[data-id=save-transit]').click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body.transit.routes.slice(-2), ['C91', 'X2']);
  await page.locator('[data-tab=teams]').click();
  await page.locator('[data-id=league]').selectOption('nhl');
  await page.locator('[data-panel=teams] .pick label').first().locator('input').check();
  await page.waitForTimeout(200);
  assert.ok(t.posts.at(-1).body.teams.some(team => team.startsWith('nhl:')));
  await page.locator('[data-tab=messages]').click();
  await page.locator('[data-id=add-message]').click();
  await page.locator('[data-id=messages] textarea').last().fill('Game 3 tonight at 8');
  await page.locator('[data-id=save-messages]').click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).body.messages.at(-1).text, 'Game 3 tonight at 8');
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('vv.crawlTab'))), 'messages');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  const phone = await open(browser, '/crawl', {width: 390});
  await phone.page.waitForSelector('#reg-body tr.item');
  assert.equal(await overflow(phone.page), 0);
  await phone.ctx.close();
});
