// Schedule: painting the week, the automation switch, shows and games, and what will air.
// node tests/browser_ui_schedule.cjs /path/to/playwright
const {open, run, assert} = require('./ui_harness.cjs');

run(async browser => {
  const t = await open(browser, '/schedule', {api: {
    'POST /v1/programming': (body, F) => ({...F.programming, settings: {...F.programming.settings, ...body}}),
    'POST /v1/programming/shows': () => ({status: 201, json: {}}),
    'POST /v1/programming/follow-games': (body, F) => ({...F.programming, changes: [{title: 'Phillies at Braves', text: 'Moved to 8 PM'}]}),
    'DELETE /v1/programming/shows/*': (body, F) => F.programming,
  }});
  const page = t.page;
  await page.waitForSelector('#grid td[data-day=fri][data-cell="20"]');
  const server = JSON.parse(JSON.stringify(t.F.programming.settings));

  // What is on and next, from the projection.
  assert.match(await page.locator('#on-now').innerText(), /Phillies/i);
  assert.ok(await page.locator('#airs .chipx').count() > 0, 'what will air is drawn over the grid');

  // Paint Friday 10:00 with Jeopardy; the switch then saves only itself, not the unsaved paint.
  await page.locator('.brush', {hasText: 'Jeopardy'}).click();
  await page.locator('#grid td[data-day=fri][data-cell="20"]').dispatchEvent('pointerdown', {button: 0});
  await page.dispatchEvent('body', 'pointerup');
  assert.match(await page.locator('#dirty').innerText(), /Unsaved/);
  await page.locator('#enabled').uncheck();
  await page.waitForTimeout(200);
  const toggle = t.posts.at(-1);
  assert.equal(toggle.path, '/v1/programming');
  assert.equal(toggle.body.enabled, false);
  assert.deepEqual(toggle.body.grid, server.grid, 'the unsaved paint was not saved by the switch');
  assert.match(await page.locator('#dirty').innerText(), /Unsaved/, 'and is still waiting to be saved');

  // Save sends the paint.
  await page.locator('#save').click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).body.grid.fri[20], 'muelbpzvjazj65fh');

  // A new block.
  await page.locator('#new-block').click();
  await page.locator('#block-name').fill('Late movie');
  await page.locator('#block-target select').first().selectOption('tv-thing-digital');
  await page.waitForFunction(() => document.querySelectorAll('#block-target select')[1]?.options.length > 1);
  await page.locator('#block-dialog').getByRole('button', {name: 'Save block'}).click();
  assert.equal(await page.locator('.brush', {hasText: 'Late movie'}).getAttribute('aria-pressed'), 'true', 'the new block is the brush');

  // A network on YouTube TV: the antenna goes on if YouTube TV is late, unless the block waits for it.
  await page.locator('#new-block').click();
  await page.locator('#block-name').fill('News 4');
  await page.locator('#block-target select').first().selectOption('youtube-tv');
  await page.waitForFunction(() => document.querySelectorAll('#block-target select')[1]?.options.length > 1);
  await page.locator('#block-target select').nth(1).selectOption('NBC');
  const late = page.locator('#block-target').getByLabel('If YouTube TV is late');
  await late.waitFor();
  assert.match(await late.locator('option').first().textContent(), /Antenna 4\.1 WRC-HD goes on/);
  await late.selectOption('wait');
  await page.locator('#block-dialog').getByRole('button', {name: 'Save block'}).click();
  assert.match(await page.locator('.brush', {hasText: 'News 4'}).textContent(), /YouTube TV only/);
  await page.locator('#save').click();
  await page.waitForTimeout(200);
  const saved = t.posts.filter(p => p.path === '/v1/programming').at(-1).body.blocks.find(b => b.name === 'News 4');
  assert.deepEqual(saved.target, {source_id: 'youtube-tv', channel_id: 'NBC', antenna: false});
  // A cable channel has no antenna, so no such choice.
  await page.locator('#new-block').click();
  await page.locator('#block-target select').first().selectOption('youtube-tv');
  await page.waitForFunction(() => document.querySelectorAll('#block-target select')[1]?.options.length > 1);
  await page.locator('#block-target select').nth(1).selectOption('PBS');
  assert.equal(await late.isHidden(), true);
  await page.locator('#block-dialog').getByRole('button', {name: 'Cancel'}).click();

  // Shows: the feeds check, and adding a program.
  await page.locator('#follow-games').click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).path, '/v1/programming/follow-games');
  await page.locator('[data-tab=add]').click();
  await page.locator('#show-title').fill('Election night');
  await page.locator('#show-target select').first().selectOption('tv-thing-digital');
  await page.waitForFunction(() => document.querySelectorAll('#show-target select')[1]?.options.length > 1);
  await page.locator('#add-show').click();
  await page.waitForTimeout(200);
  const show = t.posts.find(p => p.path === '/v1/programming/shows');
  assert.equal(show.body.mode, 'program');
  assert.equal(show.body.title, 'Election night');
  assert.equal(show.body.target.source_id, 'tv-thing-digital');

  // A game: league, date, game, then its window fills in.
  await page.locator('[name=mode][value=game]').check();
  await page.locator('#load-games').click();
  await page.waitForFunction(() => document.querySelector('#game').options.length > 1);
  await page.locator('#game').selectOption({index: 1});
  assert.notEqual(await page.locator('#show-end').inputValue(), '');

  // Sports: the shared list, with Customize filling the form.
  await page.locator('[data-tab=sports]').click();
  await page.waitForSelector('#sports-list .sports-games li');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
