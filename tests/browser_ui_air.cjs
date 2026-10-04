// On Air: master's output and Up next. What each button sends, and that the dangerous ones ask first.
// node tests/browser_ui_air.cjs /path/to/playwright
const {open, run, assert} = require('./ui_harness.cjs');

const QUEUED = 'd33ae12bfbcb4257ab79c634f851d074', BLOCKED = '21d1b99b6eb14d51b7bc06a85106676d';

run(async browser => {
  const t = await open(browser, '/air', {api: {'POST /v1/queue/*': () => ({}), 'DELETE /v1/queue/*': () => ({}), 'POST /v1/master/*': () => ({})}});
  const page = t.page;
  await page.waitForSelector(`#queue-items [data-id="${QUEUED}"]`);

  // What is on master, named from the guide.
  assert.match(await page.locator('#pgm-title').innerText(), /WRC-HD/);
  assert.match(await page.locator('#master-state').innerText(), /live/i);
  assert.match(await page.locator('#queue-state').innerText(), /Paused/);

  // Up next: resume, move, retry, remove.
  await page.locator('#queue-toggle').click();
  await page.locator(`[data-id="${QUEUED}"] [data-action=movedown]`).click();
  await page.locator(`[data-id="${BLOCKED}"] [data-action=retry]`).click();
  await page.locator(`[data-id="${QUEUED}"] [data-action=remove]`).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.map(p => [p.method, p.path, p.body]), [
    ['POST', '/v1/queue/resume', {}], ['POST', '/v1/queue/' + QUEUED + '/move', {direction: 'down'}],
    ['POST', '/v1/queue/' + BLOCKED + '/retry', {}], ['DELETE', '/v1/queue/' + QUEUED, null]]);
  t.posts.length = 0;

  // Clear asks first; cancelling sends nothing.
  await page.locator('#queue-clear').click();
  await page.getByRole('dialog', {name: 'Clear Up next'}).getByRole('button', {name: 'Cancel'}).click();
  assert.deepEqual(t.posts, []);
  await page.locator('#queue-clear').click();
  await page.getByRole('dialog', {name: 'Clear Up next'}).getByRole('button', {name: 'Clear'}).click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.map(p => p.path), ['/v1/queue/clear']);
  t.posts.length = 0;

  // A live channel can be given an end time: the next :30 or hour by default.
  await page.locator('#hold-change').click();
  const dialog = page.locator('#take-dialog');
  await dialog.waitFor();
  await dialog.getByRole('button', {name: 'Save end time'}).click();
  await page.waitForTimeout(150);
  assert.equal(t.posts[0].path, '/v1/master/hold');
  assert.equal(t.posts[0].body.until.kind, 'time');
  assert.equal(new Date(t.posts[0].body.until.at).getTime(), new Date('2026-10-02T02:30:00Z').getTime());
  t.posts.length = 0;

  // Return to fallback cuts master: it asks, and only then sends.
  await page.locator('#fallback').click();
  await page.getByRole('dialog', {name: 'Return to fallback'}).getByRole('button', {name: 'Cut to fallback'}).click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.map(p => [p.path, p.body]), [['/v1/master/fallback', {}]]);

  // Watching master asks for its stream; with none, the page says so and carries on.
  await page.locator('#watch-master').click();
  await page.waitForTimeout(800);
  assert.equal(await page.locator('#stop-monitor').isDisabled(), false);
  await page.locator('#stop-monitor').click();
  assert.match(await page.locator('#monitor-status').innerText(), /off/i);

  // The tiles: the bar, the next break, the schedule.
  assert.match(await page.locator('#break-who').innerText(), /Amélie/i);
  assert.match(await page.locator('#break-what').innerText(), /Steelers et les Browns/);
  assert.match(await page.locator('#crawl-state').innerText(), /Bar off|pop-up|Important|Override/);

  // Find, in Up next: / goes to the box; a live channel asks how long it plays.
  t.posts.length = 0;
  const find = page.locator('#find-input'), options = page.locator('#find-results [role=option]');
  await page.locator('body').click({position: {x: 5, y: 300}});
  await page.keyboard.press('/');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'find-input');
  await find.fill('wttg');
  await options.first().waitFor();
  assert.equal(await options.count(), 1);
  assert.match(await options.first().innerText(), /5\.1 · WTTG-DT[\s\S]*\+ Queue/i);
  await find.press('Enter');
  const add = page.locator('.onair-dialog');
  await add.waitFor();
  assert.match(await add.locator('.onair-kicker').innerText(), /how long it plays/i);
  assert.deepEqual(t.posts, [], 'nothing is queued before the answer');
  await add.locator('.onair-choice input[type=datetime-local]').fill('2026-10-01T23:30');
  await add.getByRole('button', {name: /Add to queue/}).click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.map(p => [p.path, p.body.target.channel_id, p.body.release_type, p.body.until?.kind]),
    [['/v1/queue', 'wttg_dt_5_1', 'after_current', 'time']]);
  assert.equal(await find.inputValue(), '', 'the box clears once it is added');
  t.posts.length = 0;

  // A recording goes straight in, to its end; arrow keys choose among matches.
  await find.fill('jeopardy');
  await options.first().waitFor();
  assert.ok(await options.count() >= 2);
  await find.press('ArrowDown');
  assert.equal(await options.nth(1).getAttribute('aria-selected'), 'true');
  const second = await options.nth(1).innerText();
  assert.match(second, /Recording/);
  await options.nth(1).click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.length, 1);
  assert.deepEqual(Object.keys(t.posts[0].body).sort(), ['release_type', 'target']);
  assert.equal(t.posts[0].body.target.source_id, 'library');
  t.posts.length = 0;

  // A game under way is marked live; a later program can only be scheduled; no match says so.
  await find.fill('steelers');
  await options.first().waitFor();
  assert.match(await options.first().getAttribute('class'), /live/);
  await find.fill('news4 at 11');
  await options.first().waitFor();
  assert.match(await options.first().innerText(), /Schedule/i);
  await find.fill('zzzz');
  await page.waitForFunction(() => /Nothing matches/.test(document.querySelector('.find-status').textContent));
  await find.press('Escape');
  assert.equal(await find.inputValue(), '');
  assert.equal(await page.locator('.find-pop').isHidden(), true);
  assert.deepEqual(t.posts, []);
  assert.deepEqual(t.unknown, []);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // A held game in its closing stretch: the schedule's block is prepared on the Roku meanwhile.
  const held = await open(browser, '/air', {edit: F => {
    F.queue.hold = {id: 'h', target: {source_id: 'tv-thing-digital', channel_id: 'wttg_dt_5_1'}, detail: 'Top 9th', until: null,
      game: {league: 'mlb', game_pk: 1, game_date: '2026-10-01', title: 'Phillies at Braves'}};
    F.queue.warm = {target: {source_id: 'youtube-tv', channel_id: 'ESPN'}, title: 'SportsCenter', ends: 'Phillies at Braves', state: 'ready', error: null};
  }});
  await held.page.waitForFunction(() => /ready on the Roku/.test(document.querySelector('#queue-state')?.textContent || ''));
  assert.match(await held.page.locator('#queue-state').textContent(),
    /until Phillies at Braves ends \(Top 9th\).* SportsCenter is ready on the Roku for when Phillies at Braves ends\.$/);
  assert.deepEqual(held.errors, []);
  await held.ctx.close();

  // A game put back on from the antenna: YouTube TV is prepared beside it, then replaces it.
  const back = await open(browser, '/air', {edit: F => {
    F.queue.hold = {id: 'h', target: {source_id: 'tv-thing-digital', channel_id: 'wttg_dt_5_1'}, detail: '9:04 - 4th', until: null,
      game: {league: 'nfl', game_pk: 1, game_date: '2026-10-04', title: 'Colts at Commanders'},
      program_target: {source_id: 'youtube-tv', channel_id: 'NFL Network'}};
    F.queue.upgrade = {target: {source_id: 'youtube-tv', channel_id: 'NFL Network', antenna: false}, input_id: 'a',
      from: {source_id: 'tv-thing-digital', channel_id: 'wttg_dt_5_1'}, state: 'preparing', error: null, attempt: 1};
  }});
  await back.page.waitForFunction(() => /Preparing YouTube TV · NFL Network/.test(document.querySelector('#queue-state')?.textContent || ''));
  assert.match(await back.page.locator('#queue-state').textContent(),
    /until Colts at Commanders ends \(9:04 - 4th\).* Preparing YouTube TV · NFL Network on the Roku; it replaces the antenna once ready\.$/);
  assert.deepEqual(back.errors, []);
  await back.ctx.close();
});
