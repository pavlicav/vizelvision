// Every page of the control-room UI loads, asks only for endpoints the server has, fits a phone,
// marks its place in the top bar, and shares the palette, the keys and the machinery switch.
// node tests/browser_ui_pages.cjs /path/to/playwright
const {open, run, overflow, assert, PAGES} = require('./ui_harness.cjs');

const AREA = {'/sonic': 'Presentation', '/calibration': 'Engineering'};
const NAMES = {'/air': 'On Air', '/sources': 'Sources', '/schedule': 'Schedule', '/crawl': 'Crawl', '/presentation': 'Presentation', '/ads': 'Ads', '/engineering': 'Engineering'};

run(async browser => {
  for (const page of PAGES) {
    for (const width of [1440, 390]) {
      const t = await open(browser, page, {width});
      await t.page.waitForTimeout(1200);
      assert.deepEqual(t.errors, [], page + ' @' + width + ' has no script errors');
      assert.deepEqual(t.unknown, [], page + ' asks only for real endpoints');
      assert.equal(await overflow(t.page), 0, page + ' @' + width + ' fits without sideways scrolling');
      const current = await t.page.locator('nav.nav a[aria-current=page]').textContent();
      assert.equal(current.trim().replace(/\s+/g, ' '), AREA[page] || NAMES[page], page + ' marks its area');
      assert.match(await t.page.locator('.tally').innerText(), /ON AIR/, page + ' shows what is on air');
      assert.deepEqual(t.posts, [], page + ' changes nothing by being looked at');
      if (width === 1440 && page === '/air') await t.page.screenshot({path: '/tmp/vizelvision-ui-air.png', fullPage: true});
      await t.ctx.close();
    }
  }

  // The machinery: hidden until switched on (button or m), remembered, and drawn live.
  let t = await open(browser, '/crawl');
  await t.page.waitForSelector('#reg-body tr.item');
  assert.equal(await t.page.locator('.machinery').first().isVisible(), false);
  await t.page.keyboard.press('m');
  assert.equal(await t.page.locator('.machinery').first().isVisible(), true);
  assert.ok((await t.page.locator('#timeline').innerHTML()).includes('NOW'), 'the plan is drawn');
  assert.equal(await t.page.evaluate(() => localStorage.getItem('vv.machinery')), 'true');
  await t.page.locator('.tool[data-tool=machinery]').click();
  assert.equal(await t.page.locator('.machinery').first().isVisible(), false);

  // The command palette: Ctrl-K, type, Enter.
  await t.page.keyboard.press('Control+k');
  await t.page.locator('.palette input').fill('go to sched');
  await t.page.keyboard.press('Enter');
  await t.page.waitForURL(/\/schedule$/);
  await t.ctx.close();

  // g + number goes to a page; ? lists the keys.
  t = await open(browser, '/air');
  await t.page.waitForTimeout(300);
  await t.page.keyboard.press('?');
  assert.ok(await t.page.getByRole('dialog', {name: 'Keyboard shortcuts'}).isVisible());
  await t.page.keyboard.press('Escape');
  await t.page.keyboard.press('g'); await t.page.keyboard.press('4');
  await t.page.waitForURL(/\/crawl$/);
  await t.ctx.close();

  // Production's old tabs forward to where they went.
  t = await open(browser, '/presentation#crawl');
  await t.page.waitForURL(/\/crawl$/);
  await t.ctx.close();
  t = await open(browser, '/presentation#monitor');
  await t.page.waitForURL(/\/engineering#monitor$/);
  assert.equal(await t.page.locator('[data-panel=monitor]').isVisible(), true);
  await t.ctx.close();
});
