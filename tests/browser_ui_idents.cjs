// Ads › Idents: the ID card, what is on air and cued for the next break, every ident with its
// picture and preview, and what aired. node tests/browser_ui_idents.cjs /path/to/playwright
const {open, run, assert, overflow} = require('./ui_harness.cjs');

run(async browser => {
  let t = await open(browser, '/ads#idents');
  let page = t.page;
  await page.waitForSelector('#idt-grid .ident');
  assert.equal(await page.locator('#tab-idents').getAttribute('aria-selected'), 'true');

  // The ID card: the legal ID's picture, the station's name, and who and what is on it now.
  await page.waitForFunction(() => document.getElementById('idt-face').src.startsWith('blob:'));
  assert.ok(t.frames.includes('/v1/promos/file/legal.png'));
  assert.match(await page.locator('#panel-idents .who .name').textContent(), /VizelVision 19.*Cable\s*70/);
  assert.match(await page.locator('#panel-idents .who .legal').textContent(), /WVHZ-DB\s+Washington/);
  const card = await page.locator('#idt-card').textContent();
  assert.match(card, /Amélie is on duty/);
  assert.match(card, /at least one every 15 min/);

  // On air: nothing now; the next break is Amélie's announced ID, then the cued promo.
  assert.equal(await page.locator('#idt-status').textContent(), 'No ident on air');
  const next = await page.locator('#idt-next').textContent();
  assert.match(next, /Station ID, announced by Amélie/);
  assert.match(next, /les Phillies et les Braves → les Steelers et les Browns/);
  assert.match(next, /Time & Temperature, opening the next break/);
  assert.equal(await page.locator('#idt-lines li').count(), 4);
  assert.equal(await page.locator('#idt-chip').textContent(), 'ID ready');

  // The idents: the two IDs, then the promos in their order, each with its picture.
  const idents = page.locator('#idt-grid .ident');
  assert.equal(await idents.count(), 2 + t.F.promos.promos.length);
  assert.equal(await page.locator('#idt-count').textContent(), 2 + t.F.promos.promos.length + ' idents');
  assert.match(await idents.nth(0).locator('h3').textContent(), /Station ID.*next break/);
  assert.doesNotMatch(await idents.nth(1).locator('h3').textContent(), /next break|on air/);
  assert.match(await idents.nth(1).textContent(), /VizelVision Sports.*voiced by Jupiter/);
  assert.match(await idents.nth(2).locator('h3').textContent(), /Time & Temperature.*cued/);
  await page.waitForFunction(() => [...document.querySelectorAll('#idt-grid .still img')].every(i => i.src.startsWith('blob:')));
  for (const f of ['/v1/idents/station-id.png', '/v1/idents/sports-id.png', '/v1/promos/still/legal.png']) assert.ok(t.frames.includes(f), f);

  // What aired: the last Sports break (from master) and the promos, newest first.
  const aired = page.locator('#idt-recent tr');
  assert.equal(await aired.count(), 3);
  assert.match(await aired.nth(0).textContent(), /You're Watching VizelVision.*cut short, didn't count/);
  assert.match(await aired.nth(1).textContent(), /Legal ID.*0:05 of 0:05 · complete/);
  assert.match(await aired.nth(2).textContent(), /Sports break.*After .*NBC/);
  assert.match(await idents.nth(1).textContent(), /last 1 h 38 min ago/);

  // An ID plays in a dialog; a promo in the promo preview, its live text over it.
  await idents.nth(0).locator('.still').click();
  await page.waitForSelector('dialog.ident-preview video');
  await page.waitForFunction(() => document.querySelector('dialog.ident-preview video').src.startsWith('blob:'));
  assert.ok(t.frames.includes('/v1/idents/station-id.mp4'));
  await page.locator('dialog.ident-preview').getByRole('button', {name: 'Close'}).click();
  assert.equal(await page.locator('dialog.ident-preview').count(), 0);
  await idents.nth(2).locator('.still').click();
  await page.waitForSelector('dialog.promo-preview video');
  assert.equal(await page.locator('dialog.promo-preview .stage img').count(), 4, 'its four live texts');
  await page.locator('dialog.promo-preview').getByRole('button', {name: 'Close'}).click();

  // The tab is remembered, its machinery polls only while it shows, and it fits a phone.
  assert.match(page.url(), /#idents$/);
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);
  await t.ctx.close();

  // The Sports break on air, holding its end card for the game.
  t = await open(browser, '/ads#idents', {width: 390, height: 844, edit: F => {
    F.master.ident = {...F.master.ident, on_air: true, held: true, file: 'sports-65d45ff77e80f0e7.mp4'};
    F.continuity.next = {...F.continuity.next, kind: 'sports', name: 'Amélie, then VizelVision Sports'};
  }});
  page = t.page;
  await page.waitForSelector('#idt-grid .ident');
  await page.waitForFunction(() => document.getElementById('idt-status').textContent !== '—');
  assert.equal(await page.locator('#idt-status').textContent(), 'Sports break · holding');
  assert.match(await page.locator('#idt-detail').textContent(), /Holding its end card/);
  assert.match(await page.locator('#idt-lamp').getAttribute('class'), /pgm/);
  assert.match(await page.locator('#idt-grid .ident').nth(1).locator('h3').textContent(), /VizelVision Sports.*on air/);
  assert.doesNotMatch(await page.locator('#idt-grid .ident').nth(0).locator('h3').textContent(), /on air|next break/);
  assert.equal(await overflow(page), 0, 'no sideways scroll on a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
