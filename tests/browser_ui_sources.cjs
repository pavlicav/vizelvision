// Sources: the three ways on air from the guide, the source cards, the library and sports.
// node tests/browser_ui_sources.cjs /path/to/playwright
const {open, run, assert, overflow} = require('./ui_harness.cjs');

const REC = 'tv-recordings/Jeopardy! - 7.1 WJLA - 2026-09-26 0430.mp4';

run(async browser => {
  const t = await open(browser, '/sources', {api: {'POST /v1/queue': () => ({status: 201, json: {id: 'new'}}), 'POST /v1/programming/shows': () => ({status: 201, json: {}})}});
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

  // The library: a recording plays to its end; a collection can be queued in order.
  await page.locator('#sources [data-source=library]').click();
  await page.waitForSelector('.media-row');
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

  const phone = await open(browser, '/sources', {width: 390});
  await phone.page.waitForSelector('.row-channel');
  assert.equal(await overflow(phone.page), 0);
  await phone.ctx.close();
});
