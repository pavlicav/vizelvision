const {open, run, assert, overflow} = require('./ui_harness.cjs');

run(async browser => {
  const t = await open(browser, '/presentation#captions', {api: {
    'POST /v1/captions': (body, F) => {
      F.captions.settings = {...F.captions.settings, ...body};
      F.captions.status = {enabled: F.captions.settings.enabled, state: 'listening',
        text: '<b>Literal speech & captions</b>', error: null, programme_delay: {seconds: 6}};
      return F.captions;
    },
  }});
  const page = t.page;
  await page.waitForSelector('#captions-enabled:enabled');
  assert.equal(await page.locator('#captions-enabled').isChecked(), false);
  await page.locator('#captions-enabled').check();
  await page.waitForFunction(() => document.querySelector('#caption-status').textContent === 'Listening');
  assert.deepEqual(t.posts.at(-1).body, {enabled: true});
  assert.equal(await page.locator('#caption-preview').innerText(), '<b>Literal speech & captions</b>');
  assert.equal(await page.locator('#caption-preview b').count(), 0);
  assert.match(await page.locator('#caption-timing').innerText(), /Shared programme delay: 6 s/);
  await page.locator('#caption-model').selectOption('small');
  await page.locator('#caption-language').selectOption('fr');
  // Polling status must not discard unsaved choices.
  await page.waitForTimeout(2300);
  assert.equal(await page.locator('#caption-language').inputValue(), 'fr');
  await page.locator('#caption-save').click();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {model: 'small', language: 'fr'});
  await page.locator('#captions-enabled').uncheck();
  await page.waitForTimeout(200);
  assert.deepEqual(t.posts.at(-1).body, {enabled: false});
  assert.match(await page.locator('#caption-preview').innerText(), /off/);
  await page.setViewportSize({width: 390, height: 844});
  assert.ok(await overflow(page) <= 1);
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);
  await t.ctx.close();

  const failed = await open(browser, '/presentation#captions', {api: {
    'POST /v1/captions': () => ({status: 400, json: {error: {message: 'Missing model'}}}),
  }, edit: F => { F.captions.master_error = 'Master is unavailable'; }});
  await failed.page.waitForSelector('#captions-enabled:enabled');
  assert.match(await failed.page.locator('#caption-error').innerText(), /Master is unavailable/);
  assert.equal(await failed.page.locator('#caption-preview').innerText(), '');
  await failed.page.locator('#captions-enabled').check();
  await failed.page.waitForTimeout(200);
  assert.equal(await failed.page.locator('#captions-enabled').isChecked(), false);
  assert.equal(await failed.page.locator('#captions-enabled').isEnabled(), true);
  assert.deepEqual(failed.errors, []);
  await failed.ctx.close();
});
