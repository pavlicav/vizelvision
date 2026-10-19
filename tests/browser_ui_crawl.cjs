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
    edit: F => {
      F.alerts.items.unshift(severe, muted); F.alerts.counts.looping = 1; F.alerts.counts.muted = 1;
      // A new item on the bar during Sunday Night Football: its own colour and a NEW box, along the top.
      Object.assign(F.crawl.status, {on_air: true, kind: 'bulletin', label: 'DC ALERTS', flag: 'NEW', style: 'new', position: 'top',
        items: [{tag: 'ALERTDC', heading: '', text: 'Red Mass road closures until 1 PM.'}]});
      Object.assign(F.crawl.rotation, {context: 'game', mode: 'popups', position: 'top', league: 'nfl', next_round: Date.now() / 1000 + 600});
    },
    api: {'POST /v1/favorites': (body, F) => Object.assign(F.favorites, body), 'POST /v1/crawl/*': (body, F) => F.crawl, 'POST /v1/crawl': (body, F) => {
      for (const [segment, options] of Object.entries(body.segments || {})) {
        assert.ok(Object.keys(options).every(key => ['enabled', 'every', 'changed_only'].includes(key)), 'only valid segment fields are sent');
        Object.assign(F.crawl.settings.segments[segment], options);
      }
      return F.crawl;
    }}});
  const page = t.page;
  await page.waitForSelector(`#reg-body tr.item[data-id="${BUS}"]`);
  const row = id => page.locator(`#reg-body tr.item[data-id="${id}"]`);

  // The bar now: the NEW box in front of the label, along the top during football.
  const bar = page.locator('#screen .crawlbar');
  assert.equal(await bar.locator('.boxlabel .flag').innerText(), 'NEW');
  assert.match(await bar.locator('.boxlabel').innerText(), /NEW\s*DC ALERTS/);
  assert.match(await page.locator('#bar-note').innerText(), /New items, on their own[\s\S]*Along the top/);
  assert.match(await page.locator('#state').innerText(), /Next round ≈[\s\S]*Bar at the top · NFL/i);

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
  await page.locator('[data-id=round]').fill('20');
  await page.locator('[data-id=top-leagues]').getByRole('checkbox', {name: 'NBA', exact: true}).check();
  await page.locator('[data-id=top-leagues]').getByRole('checkbox', {name: 'College Football'}).uncheck();
  await page.locator('[data-id=save-rules]').click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {rules: {round_minutes: 20, gap_minutes: 5, top_leagues: ['nfl', 'nba'], program: 'always', game: 'quiet', off_air: 'always', ident: 'quiet'}});
  await page.locator('[data-tab=segments]').click();
  const alertDC = page.locator('.seg-card[data-segment=dc_alerts]').getByRole('checkbox', {name: 'AlertDC', exact: true});
  await alertDC.uncheck();
  await page.waitForFunction(() => !document.querySelector('[data-segment=dc_alerts][data-field=enabled]').disabled);
  assert.deepEqual(t.posts.at(-1).body, {segments: {dc_alerts: {enabled: false}}});
  assert.equal(await page.locator('[data-id=segments-dirty]').innerText(), '', 'switch saves without Save segments');
  await page.reload();
  await alertDC.waitFor();
  assert.equal(await alertDC.isChecked(), false, 'AlertDC stays off after reloading');
  const weather = page.locator('.seg-card[data-segment=weather]');
  await weather.getByLabel('New items pop up at once (once each)').check();
  await page.locator('[data-id=save-segments]').click();
  await page.waitForTimeout(300);
  const [segments, feeds] = t.posts.slice(-2);
  assert.equal(segments.path, '/v1/crawl');
  assert.deepEqual(segments.body.segments.dc_alerts, {every: t.F.crawl.settings.segments.dc_alerts.every, changed_only: t.F.crawl.settings.segments.dc_alerts.changed_only});
  assert.equal(t.F.crawl.settings.segments.dc_alerts.enabled, false, 'saving other options keeps AlertDC off');
  assert.equal(feeds.path, '/v1/crawl/feeds');
  assert.equal(feeds.body.segments.weather.new_now, true);
  assert.deepEqual(feeds.body.segments.weather.contexts, ['off_air']);
  await weather.getByRole('button', {name: 'Run Weather now'}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {segment: 'weather'});
  await alertDC.check();
  await page.waitForFunction(() => !document.querySelector('[data-segment=dc_alerts][data-field=enabled]').disabled);
  assert.deepEqual(t.posts.at(-1).body, {segments: {dc_alerts: {enabled: true}}});
  await page.reload();
  await alertDC.waitFor();
  assert.equal(await alertDC.isChecked(), true, 'AlertDC can be turned back on permanently');

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
  // Favorites: ranked, whole playoffs among them, and their games with what the planner did.
  await page.locator('[data-tab=teams]').click();
  const favorites = page.locator('[data-id=followed] li');
  await page.waitForFunction(() => document.querySelector('[data-id=followed] li')?.textContent.includes('Detroit Red Wings'));
  assert.deepEqual(await favorites.evaluateAll(rows => rows.map(r => r.children[1].textContent)),
    ['NHL · Detroit Red Wings', 'MLB · All playoffs, through the World Series', 'NHL · Washington Capitals']);
  const games = page.locator('[data-id=fav-games] li');
  assert.match(await games.nth(0).textContent(), /Detroit Tigers at Cleveland Guardians.*★ 2 · MLB · All playoffs.*On the Schedule/);
  assert.match(await games.nth(1).textContent(), /On ESPN\+: not a channel VizelVision gets.*No channel/);
  assert.equal(await page.locator('[data-id=fav-air]').isChecked(), true);
  await page.getByRole('button', {name: 'Move MLB · All playoffs, through the World Series up'}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/favorites', body: {favorites: ['mlb:playoffs', 'nhl:5', 'nhl:23']}});
  await page.waitForFunction(() => document.querySelector('[data-id=followed] li')?.textContent.includes('All playoffs'));
  await page.locator('[data-id=league]').selectOption('ncaaf');
  const pick = page.locator('[data-panel=teams] .pick label');
  await page.waitForFunction(() => document.querySelector('[data-panel=teams] .pick label')?.textContent !== 'All playoffs, through the World Series');
  assert.equal(await pick.first().textContent(), 'All bowls and playoffs', 'whole playoffs come first');
  await pick.first().locator('input').check();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {favorites: ['mlb:playoffs', 'nhl:5', 'nhl:23', 'ncaaf:playoffs']});
  await page.locator('[data-id=league]').selectOption('nhl');
  await page.waitForFunction(() => document.querySelector('[data-panel=teams] .pick label')?.textContent === 'All playoffs');
  await page.getByRole('checkbox', {name: 'Boston Bruins'}).check();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).body.favorites.at(-1), 'nhl:1');
  await page.getByRole('button', {name: 'Remove NHL · Detroit Red Wings'}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body.favorites, ['mlb:playoffs', 'nhl:23', 'ncaaf:playoffs', 'nhl:1']);
  await page.locator('[data-id=fav-air]').uncheck();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {air: false});
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
