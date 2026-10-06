// Presentation and Engineering: the off-air card, continuity, the station ID, promos, the viewer
// monitor, the API explorer. node tests/browser_ui_presentation.cjs /path/to/playwright
const {open, run, assert} = require('./ui_harness.cjs');

run(async browser => {
  let t = await open(browser, '/presentation', {api: {
    'POST /v1/production': (body, F) => ({...F.production, settings: body}),
    'POST /v1/continuity': (body, F) => ({...F.continuity, settings: {...F.continuity.settings, ...body}}),
    'POST /v1/promos': (body, F) => ({...F.promos, settings: {...F.promos.settings, ...body}}),
    'POST /v1/promos/promo/*': (body, F, where) => ({...F.promos, promos: F.promos.promos.map(p =>
      where.endsWith('/' + p.id) ? {...p, ...body} : p)}),
  }});
  let page = t.page;
  await page.waitForSelector('[data-card=master]');

  // The off-air card: previews follow the form; save sends the whole form.
  await page.locator('#master-caption').fill('VIZELVISION OFF AIR');
  assert.match(await page.locator('[data-card=master]').innerText(), /VIZELVISION OFF AIR/);
  await page.locator('#clock-enabled').check();
  assert.equal(await page.locator('.tv-clock').isVisible(), true);
  await page.locator('#save').click();
  await page.waitForTimeout(200);
  const saved = t.posts.at(-1);
  assert.equal(saved.path, '/v1/production');
  assert.equal(saved.body.captions.master, 'VIZELVISION OFF AIR');
  assert.equal(saved.body.clock.enabled, true);
  assert.deepEqual(Object.keys(saved.body).sort(), ['audio', 'captions', 'clock', 'details', 'note']);

  // Continuity: the switch saves itself; the roster paints; the script names the next program.
  await page.locator('#tab-continuity').click();
  await page.waitForSelector('[data-id=roster] .hour');
  assert.match(await page.locator('[data-id=next]').innerText(), /Steelers et les Browns/);
  await page.locator('[data-id=enabled]').uncheck();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).body.enabled, false);
  await page.locator('[data-id=brush]').selectOption('amelie');
  await page.locator('[data-id=roster] .hour[data-hour="3"]').dispatchEvent('pointerdown', {button: 0});
  await page.dispatchEvent('body', 'pointerup');
  assert.match(await page.locator('[data-id=dirty]').innerText(), /Unsaved/);
  await page.locator('[data-id=save]').click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).body.roster.length, 24);
  assert.match(page.url(), /#continuity$/);

  // The station ID tab: what the worker reports.
  await page.locator('#tab-ident').click();
  assert.match(await page.locator('#ident').innerText(), /Ready/);
  assert.match(await page.locator('#last-id').innerText(), /Sports ID/);

  // Promos: settings save themselves; each promo has its still, its live text and a switch;
  // the preview lays the live text over the video.
  await page.locator('#tab-promos').click();
  await page.waitForSelector('#promos-panel .promo');
  assert.equal(await page.locator('#promos-panel .promo').count(), t.F.promos.promos.length);
  assert.match(await page.locator('#promos-panel [data-id=master]').innerText(), /Lions at Panthers/);
  assert.match(await page.locator('#promos-panel [data-id=master]').innerText(), /61°F/);
  await page.locator('#promos-panel [data-id=every]').selectOption('30');
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/promos', body: {every: 30}});
  await page.locator('#promos-panel [data-id=fill]').check();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {fill: true});
  const legal = page.locator('#promos-panel .promo', {hasText: 'Legal ID'});
  await legal.getByRole('checkbox').uncheck();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/promos/promo/legal', body: {enabled: false}});
  await page.locator('#promos-panel .promo', {hasText: 'Time & Temperature'}).locator('.still').click();
  await page.waitForSelector('dialog.promo-preview video');
  assert.equal(await page.locator('dialog.promo-preview .stage img').count(), 4, 'its four live texts');
  await page.locator('dialog.promo-preview').getByRole('button', {name: 'Close'}).click();
  assert.ok(t.frames.some(f => f === '/v1/promos/still/time-temp.png'));
  assert.match(page.url(), /#promos$/);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // Engineering: health, the monitor, the explorer.
  t = await open(browser, '/engineering', {api: {'POST /v1/production/monitor': (body, F) => ({...F.monitor, settings: body}), 'POST /v1/queue/pause': () => ({})}});
  page = t.page;
  await page.waitForSelector('#health .panel');
  assert.ok(await page.locator('#health .panel').count() >= 8, 'a tile for every part');
  await page.getByRole('tab', {name: 'Viewer monitor'}).click();
  await page.waitForFunction(() => document.querySelector('#monitor-ip').value);
  await page.locator('#monitor-hours').fill('4');
  await page.locator('#monitor-save').click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.at(-1).body.interval_hours, 4);
  await page.getByRole('tab', {name: 'API explorer'}).click();
  await page.getByRole('button', {name: /GET v1\/crawl\/alerts/}).click();
  await page.waitForSelector('#api-out pre.json');
  assert.match(await page.locator('#api-meta').innerText(), /^200 ·/);
  // A write asks first, and sends only when confirmed.
  await page.getByRole('button', {name: /POST v1\/queue\/pause/}).click();
  await page.locator('#api-send').click();
  await page.getByRole('dialog', {name: 'Change the station?'}).getByRole('button', {name: 'Cancel'}).click();
  assert.equal(t.posts.filter(p => p.path === '/v1/queue/pause').length, 0);
  await page.locator('#api-send').click();
  await page.getByRole('dialog', {name: 'Change the station?'}).getByRole('button', {name: 'Send'}).click();
  await page.waitForTimeout(200);
  assert.equal(t.posts.filter(p => p.path === '/v1/queue/pause').length, 1);
  await page.getByRole('tab', {name: 'How it works'}).click();
  assert.match(await page.locator('#map').innerHTML(), /vizelvision-master/);
  await page.getByRole('tab', {name: 'Interface'}).click();
  await page.waitForSelector('#watchers tbody tr');
  await page.locator('#pref-machinery').check();
  assert.equal(await page.evaluate(() => document.body.classList.contains('show-machinery')), true);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
