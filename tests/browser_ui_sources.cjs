// Sources: the three ways on air from the guide, the source cards, the library and sports.
// node tests/browser_ui_sources.cjs /path/to/playwright
const {open, run, assert, overflow} = require('./ui_harness.cjs');

const REC = 'tv-recordings/Jeopardy! - 7.1 WJLA - 2026-09-26 0430.mp4';

run(async browser => {
  const api = {'POST /v1/queue': () => ({status: 201, json: {id: 'new'}}), 'POST /v1/programming/shows': () => ({status: 201, json: {}})};
  const t = await open(browser, '/sources', {api});
  const page = t.page;
  await page.waitForSelector('.row-channel[data-channel="wrc_hd_4_1"]');

  // Play now from the guide: the dialog says what it replaces and how long it plays; the queue is paused, so it resumes.
  await page.getByRole('button', {name: 'Play now 4.1 · WRC-HD'}).click();
  const dialog = page.locator('.onair-dialog');
  await dialog.waitFor();
  assert.match(await dialog.locator('#onair-title').innerText(), /WRC-HD/);
  assert.match(await dialog.locator('.onair-note').innerText(), /paused/i);
  assert.equal(await dialog.locator('input[value=program]').isChecked(), true, 'until the listed program ends, by default');
  await dialog.locator('input[value=open]').check();
  await dialog.getByRole('button', {name: /Play now and resume/}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {target: {source_id: 'tv-thing-digital', channel_id: 'wrc_hd_4_1'}, release_type: 'now', resume: true});

  // Until the next scheduled show starts, OFF AIR passed over: once the server names it, the default over the program's end.
  api['GET /v1/master/end-options'] = () => ({games: [], program: null, warnings: [], next_show: {title: 'Jeopardy', kind: 'block', start: '2026-10-02T03:00:00+00:00'}});
  await page.getByRole('button', {name: 'Play now 4.1 · WRC-HD'}).click();
  await dialog.locator('input[value=next]').waitFor();
  assert.equal(await dialog.locator('input[value=next]').isChecked(), true, 'until the next scheduled show, by default');
  assert.match(await dialog.locator('.onair-choices').innerText(), /The next scheduled show starts\s+Jeopardy/);
  await dialog.getByRole('button', {name: /Play now/}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body.until, {kind: 'time', at: '2026-10-02T03:00:00.000Z'});
  delete api['GET /v1/master/end-options'];

  // NBC, FOX, ABC, CBS and The CW: from YouTube TV or the antenna. Picked from TV-Thing's guide, the antenna.
  await page.getByRole('button', {name: 'Play now 4.1 · WRC-HD'}).click();
  await dialog.waitFor();
  await dialog.locator('.onair-source:not([hidden])').waitFor();
  assert.equal(await dialog.locator('input[name=onair-source][value=antenna]').isChecked(), true);
  assert.match(await dialog.locator('.onair-sources').innerText(), /YouTube TV · NBC, else the antenna/);
  await dialog.getByRole('button', {name: 'Cancel'}).click();

  // On YouTube TV the default is YouTube TV, with the antenna going on if it is not ready in time.
  await page.locator("#sources [data-source=roku]").click();
  const nbc = page.getByRole('button', {name: 'Play now NBC', exact: true});
  await nbc.click();
  await dialog.locator('.onair-source:not([hidden])').waitFor();
  assert.equal(await dialog.locator('input[name=onair-source][value=auto]').isChecked(), true);
  assert.match(await dialog.locator('.onair-sources').innerText(), /4\.1 WRC-HD/);
  await dialog.locator('input[value=open]').check();
  await dialog.getByRole('button', {name: /Play now/}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body.target, {source_id: 'youtube-tv', channel_id: 'NBC'});
  await nbc.click();
  await dialog.locator('input[name=onair-source][value=youtube]').check();
  await dialog.locator('input[value=open]').check();
  await dialog.getByRole('button', {name: /Play now/}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body.target, {source_id: 'youtube-tv', channel_id: 'NBC', antenna: false});
  await nbc.click();
  await dialog.locator('input[name=onair-source][value=antenna]').check();
  await dialog.locator('input[value=open]').check();
  await dialog.getByRole('button', {name: /Play now/}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body.target, {source_id: 'tv-thing-digital', channel_id: 'wrc_hd_4_1'});
  // PBS is on both too, but not one of the five: no choice.
  await page.getByRole('button', {name: 'Play now PBS', exact: true}).click();
  await dialog.waitFor();
  assert.equal(await dialog.locator('.onair-source').isHidden(), true);
  await dialog.getByRole('button', {name: 'Cancel'}).click();
  await page.locator('#sources [data-source=all]').click();

  // Add to queue asks how long it plays: until the listed program ends, by default.
  t.posts.length = 0;
  await page.getByRole('button', {name: 'Add to queue 7.1 · WJLA'}).click();
  await dialog.waitFor();
  assert.match(await dialog.locator('.onair-kicker').innerText(), /how long it plays/i);
  assert.equal(await dialog.locator('input[value=program]').isChecked(), true);
  assert.deepEqual(t.posts, [], 'nothing is queued before the answer');
  await dialog.getByRole('button', {name: /Add to queue/}).click();
  await page.waitForTimeout(200);
  let added = t.posts.at(-1).body;
  assert.equal(added.release_type, 'after_current');
  assert.equal(added.until.kind, 'program');

  // A channel with no listing (WTTG): a stop time can be given.
  await page.getByRole('button', {name: 'Add to queue 5.1 · WTTG-DT'}).click();
  await dialog.waitFor();
  assert.equal(await dialog.locator('input[value=program]').count(), 0);
  await dialog.locator('.onair-choice input[type=datetime-local]').fill('2026-10-01T23:30');
  assert.equal(await dialog.locator('input[value=time]').isChecked(), true);
  await dialog.getByRole('button', {name: /Add to queue/}).click();
  await page.waitForTimeout(200);
  added = t.posts.at(-1).body;
  assert.deepEqual([added.target.channel_id, added.release_type, added.until.kind], ['wttg_dt_5_1', 'after_current', 'time']);
  assert.equal(new Date(added.until.at).getTime(), new Date('2026-10-01T23:30').getTime());

  // A future program: Schedule puts it on the schedule as a show.
  const schedule = page.getByRole('button', {name: /^Schedule / }).first();
  await schedule.click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).path, '/v1/programming/shows');
  assert.equal(t.posts.at(-1).body.mode, 'program');

  // The library: TV-Thing's recordings fold away, closed until opened (remembered); a recording
  // plays to its end; a folder can be queued in order.
  await page.locator('#sources [data-source=library]').click();
  const folder = page.locator('.collection .fold', {hasText: 'TV Recordings'});
  await folder.waitFor();
  assert.equal(await folder.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('.media-row').count(), 0);
  await folder.click();
  await page.waitForSelector(`.media-row[data-id="${REC}"]`);
  assert.equal(await page.locator('.media-row').count(), 5, 'one programme: its recordings straight in the folder');
  assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('vv.libraryFolds'))), {'folder:TV Recordings': true});
  t.posts.length = 0;
  await page.locator(`.media-row[data-id="${REC}"]`).getByRole('button', {name: /^Add to queue/}).click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts[0].body, {target: {source_id: 'library', channel_id: REC}, release_type: 'after_current'});
  t.posts.length = 0;
  await page.getByRole('button', {name: /Add all of .* to the queue in order/}).click();
  await page.waitForTimeout(400);
  assert.equal(t.posts.length, 5, 'every file of the collection, one by one');
  assert.ok(t.posts.every(p => p.body.release_type === 'after_current'));

  // Roku: one card for every Roku service, with its controls.
  await page.locator('#sources [data-source=roku]').click();
  const roku = page.locator('.input-card[data-source=roku]');
  assert.equal(await roku.isVisible(), true);
  assert.ok(await roku.locator('optgroup').count() >= 2, 'one group per Roku service');
  // The Roku itself is TV Thing's: what it is doing, and the way there.
  assert.equal(await page.locator('#roku-live').isVisible(), true);
  await page.waitForFunction(() => /^Showing .*NBC.* · held by VizelVision master$/.test(document.querySelector('#roku-live-detail').textContent));
  assert.match(await page.locator('#roku-live a.btn').getAttribute('href'), /\/tv\/#roku$/);

  // Sports: games by league with the same buttons; the filter is remembered.
  await page.locator('#sources [data-source=sports]').click();
  await page.waitForSelector('.sports-games li');
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('vv.sourcesFilter'))), 'sports');
  await page.getByRole('radio', {name: /MLB/}).click();
  await page.waitForSelector('.sports-games li');

  // Search narrows the guide.
  await page.locator('#sources [data-source=all]').click();
  await page.locator('#search').fill('nashville');
  assert.equal(await page.locator('.row-channel').count(), 1);
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);
  await t.ctx.close();

  // A folder of several programmes: one recorded more than once folds by itself, the others are rows.
  const mixed = await open(browser, '/sources', {storage: {sourcesFilter: 'library', libraryFolds: {'folder:TV Recordings': true}}, edit: F => {
    const library = F.programs.library, one = library.items[0];
    library.items.push({...one, id: 'tv-recordings/Celtics at Pistons (ad training).mp4', path: 'Celtics at Pistons (ad training).mp4', title: 'Celtics at Pistons (ad training)', aired: one.aired + 86400});
  }});
  const jeopardy = mixed.page.locator('.season-title .fold', {hasText: 'Jeopardy!'});
  await jeopardy.waitFor();
  assert.equal(await jeopardy.getAttribute('aria-expanded'), 'false');
  assert.match(await jeopardy.innerText(), /5 recordings/);
  assert.equal(await mixed.page.locator('.media-row').count(), 1, 'only the programme recorded once');
  await jeopardy.click();
  await mixed.page.waitForSelector('.media-row.nested');
  assert.equal(await mixed.page.locator('.media-row.nested').count(), 5);
  assert.deepEqual(mixed.errors, []);
  await mixed.ctx.close();

  // NHL on ESPN Unlimited: a Roku source whose rows are the day's games; queued, a game keeps
  // its date and holds until its final.
  const kraken = {end: null, end_kind: 'game_status', id: 'nhl:401802671', networks: [], start: 1792720800, state: 'live', status: 'In Progress',
    title: 'Utah Mammoth at Seattle Kraken', note: 'NHL on ESPN Unlimited in YouTube TV (an ESPN+ exclusive)', espn_unlimited: {exclusive: true, blackout: {}, home: [], away: []}};
  const espn = {source_id: 'nhl', channel_id: '401802610', date: '2026-10-01'};
  const upcoming = {league: 'nhl', games: [{league: 'nhl', game_id: 401802610, title: 'Detroit Red Wings at Vancouver Canucks', short_title: 'DET @ VAN',
    start_time: '2026-10-02T02:00Z', game_date: '2026-10-01', state: 'in', status: 'In Progress', channels: [], suggested_target: espn, espn_unlimited_target: espn,
    broadcasts: [{name: 'ESPN+', market: 'national'}, {name: 'SNP', market: 'home'}],
    note: 'NHL on ESPN Unlimited in YouTube TV (out of market); the Roku takes 3-4 minutes to find it. Blacked out if YouTube TV places the Roku in Lansing (DET).'}]};
  const hockey = await open(browser, '/sources', {storage: {sourcesFilter: 'nhl', sportsLeague: 'nhl'}, api: {...api, 'GET /v1/sports/upcoming': () => upcoming}, edit: F => {
    F.sources.sources.push({...F.sources.sources.find(s => s.id === 'sunday-ticket'), id: 'nhl', name: 'NHL on ESPN Unlimited', selection: null});
    F.programs.nhl = {source_id: 'nhl', date: '2026-10-22', guide: {available: true, kind: 'games'}, stale: false,
      channels: [{id: '401802671', name: kraken.title, number: null, now: kraken, upcoming: [], game: kraken}]};
  }});
  await hockey.page.waitForSelector('.row-channel[data-channel="401802671"]');
  await hockey.page.getByRole('button', {name: 'Add to queue Utah Mammoth at Seattle Kraken'}).click();
  await hockey.page.locator('.onair-dialog').waitFor();
  await hockey.page.locator('.onair-dialog').getByRole('button', {name: /Add to queue/}).click();
  await hockey.page.waitForTimeout(200);
  const queued = hockey.posts.find(p => p.path === '/v1/queue').body;
  assert.deepEqual(queued.target, {source_id: 'nhl', channel_id: '401802671', date: '2026-10-22'});
  assert.deepEqual(queued.until, {kind: 'game', league: 'nhl', game_pk: 401802671, game_date: '2026-10-22'});
  await hockey.page.locator('#sources [data-source=roku]').click();
  assert.equal(await hockey.page.locator('.input-card[data-source=roku] optgroup[label="NHL on ESPN Unlimited"]').count(), 1, 'one of the Roku services');
  // Sports: an ESPN+ game says where it goes on air, and where it is blacked out.
  await hockey.page.locator('#sources [data-source=sports]').click();
  const row = hockey.page.locator('.sports-games li', {hasText: 'DET @ VAN'});
  await row.waitFor();
  assert.match(await row.textContent(), /ESPN\+, SNP → NHL on ESPN Unlimited · YouTube TV/);
  assert.match(await row.textContent(), /Blacked out if YouTube TV places the Roku in Lansing/);
  hockey.posts.length = 0;
  await row.getByRole('button', {name: 'Add to queue Detroit Red Wings at Vancouver Canucks'}).click();
  await hockey.page.locator('.onair-dialog').getByRole('button', {name: /Add to queue/}).click();
  await hockey.page.waitForTimeout(200);
  assert.deepEqual(hockey.posts.at(-1).body.target, espn);
  assert.deepEqual(hockey.errors, []);
  await hockey.ctx.close();

  // Internet streams: TV Thing's relays, numbered as in its lineup; live around the clock, no listings.
  const web = await open(browser, '/sources', {api, storage: {sourcesFilter: 'internet'}, edit: F => {
    F.sources.sources.push({...F.sources.sources.find(s => s.id === 'tv-thing-digital'), id: 'internet', name: 'Internet streams',
      resource_id: 'tv_thing:internet', guide_kind: 'streams', selection: null, count: 1});
    F.programs.internet = {source_id: 'internet', stale: false, warnings: [], guide: {available: false, kind: 'streams', reason: 'Live streams have no listings'},
      channels: [{id: 'pentulive', number: '29', name: 'Pentulive', note: "Yle's puppy cam, 24/7 through early December 2026", now: null, upcoming: []}]};
  }});
  const pentulive = web.page.locator('.row-channel[data-channel="pentulive"]');
  await pentulive.waitFor();
  assert.match(await pentulive.textContent(), /29Pentulive.*puppy cam.*Live stream.*No listings/);
  assert.equal(await web.page.locator('.input-card[data-source=internet] select option').textContent(), '29 · Pentulive');
  await web.page.getByRole('button', {name: 'Play now 29 · Pentulive'}).click();
  await web.page.locator('.onair-dialog').waitFor();
  assert.match(await web.page.locator('.onair-dialog').textContent(), /Internet streams · Yle's puppy cam/);
  await web.page.locator('.onair-dialog').getByRole('button', {name: /Play now/}).click();
  await web.page.waitForTimeout(200);
  assert.deepEqual(web.posts.at(-1).body.target, {source_id: 'internet', channel_id: 'pentulive'});
  assert.deepEqual(web.errors, []);
  await web.ctx.close();

  const phone = await open(browser, '/sources', {width: 390});
  await phone.page.waitForSelector('.row-channel');
  assert.equal(await overflow(phone.page), 0);
  await phone.ctx.close();
});
