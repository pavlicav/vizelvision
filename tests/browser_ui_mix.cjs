// Ads › Mix (mix.js): the kinds' shares and wear, the seen-a-lot knobs and chart, the rest, new uploads,
// the balance, each ad's own boost and wear, the preview, and Save. node tests/browser_ui_mix.cjs /path/to/playwright
//
// tests/fixtures/ui/my_ads_mix*.json come from the real ads and plays (trimmed to 36 ads, moved to the
// harness's clock), with each ad's chance as ad_mix.chance works it out: the page must agree.
const {open, run, overflow, assert} = require('./ui_harness.cjs');

// The server's side of a save: the mix with the changes, the page's view back.
function saveMix(body, F) {
  const mix = structuredClone(F.my_ads_mix.mix);
  if ('enabled' in body) mix.enabled = body.enabled;
  Object.assign(mix.tuning, body.tuning || {});
  for (const [key, change] of Object.entries(body.kinds || {})) Object.assign(mix.categories.find(c => c.key === key), change);
  for (const [id, own] of Object.entries(body.overrides || {})) {
    if (own === null) delete mix.overrides[id]; else mix.overrides[id] = {boost: 1, wear: 1, ...mix.overrides[id], ...own};
  }
  F.my_ads_mix = {...F.my_ads_mix, mix};
  return F.my_ads_mix;
}
const API = {'POST /v1/my-ads/mix': saveMix, 'POST /v1/my-ads/mix/preview': (body, F) => F.my_ads_mix_preview, 'POST /v1/my-ads': (body, F) => F.my_ads};

// Does action, then waits for what it sends to path: the last such request.
async function sent(t, path, action) {
  const n = t.posts.length;
  await action();
  for (let i = 0; i < 200 && !t.posts.slice(n).some(p => p.path === path); i++) await t.page.waitForTimeout(20);
  await t.page.waitForTimeout(40);
  return t.posts.slice(n).filter(p => p.path === path).at(-1);
}

run(async browser => {
  let t = await open(browser, '/ads#mix', {api: API});
  const {page, F} = t;
  const kinds = F.my_ads_mix.mix.categories;
  await page.waitForSelector('#mx-kinds li[data-kind]');
  await page.waitForSelector('#mx-pv .stats');
  const kind = key => page.locator(`#mx-kinds li[data-kind="${key}"]`);
  const share = key => kind(key).locator('input[type=range]').first();
  const savebar = page.locator('#mx-savebar');

  // The kinds: each with its ads, an even share, the last day against it.
  assert.equal(await page.locator('#mx-kinds li[data-kind]').count(), kinds.length);
  assert.match(await kind('tv').innerText(), /TV & sports\s+\d+ ads?[\s\S]*9%\s*by count \d+%[\s\S]*Normally[\s\S]*% · due 9%/);
  assert.equal(await page.locator('#mx-on [data-on=true]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#mx-note').isVisible(), false);
  assert.equal(await savebar.isVisible(), false, 'nothing to save yet');

  // Every ad's chance, worked out here, is ad_mix's.
  const rows = page.locator('#mx-ads li');
  assert.equal(await rows.count(), F.my_ads_mix.ads.length);
  const mine = await rows.evaluateAll(lis => lis.map(li => [li.dataset.id, +li.dataset.chance]));
  for (const [id, value] of mine) {
    const want = F.my_ads_mix_chances[id];
    assert.ok(Math.abs(value - want) <= 1e-9 + 1e-6 * want, `${id}: the page says ${value}, ad_mix ${want}`);
  }
  // The most seen first, held back and saying why.
  const worn = rows.first(), wornId = await worn.getAttribute('data-id');
  assert.match(await worn.locator('.chance').innerText(), /<1%\s*of a new ad's[\s\S]*seen a lot/);

  // The preview: as saved, the next 3 days, beside the shuffle.
  const firstPreview = t.posts.find(p => p.path === '/v1/my-ads/mix/preview');
  assert.equal(firstPreview.body.days, 3);
  const pv = F.my_ads_mix_preview;
  assert.match(await page.locator('#mx-pv').innerText(), new RegExp(`30 most seen\\s+${Math.round(pv.mix.worn_share * 100)}%[\\s\\S]*shuffle ${Math.round(pv.shuffle.worn_share * 100)}%`, 'i'));
  assert.match(await page.locator('#mx-pv').innerText(), /as saved, beside the plain shuffle/);

  // A share up: its reading, the others', the unsaved bar, the preview asked again with the draft.
  const asked = await sent(t, '/v1/my-ads/mix/preview', () => share('tv').fill('600'));
  assert.equal(asked.body.kinds.tv.weight, 3);
  assert.match(await kind('tv').locator('output').first().innerText(), /^23%\s*×3 · by count \d+%$/, '3 of 13');
  assert.match(await kind('cats').locator('output').first().innerText(), /^8%\s*by count \d+%$/, '1 of 13');
  assert.ok((await kind('tv').locator('.fader').first().getAttribute('class')).includes('changed'));
  assert.equal(await savebar.isVisible(), true);
  assert.equal(await page.locator('#mx-dirty').innerText(), '1 change not saved yet');
  assert.equal(await page.locator('#mx-dirty-list').innerText(), 'TV & sports share');

  // Keep the most seen ad fresh: it wears no more, so only its rest holds it back.
  await worn.getByRole('button', {name: 'Keep fresh'}).click();
  await page.waitForTimeout(80);
  assert.equal(await worn.getByRole('button', {name: 'Keep fresh'}).getAttribute('aria-pressed'), 'true');
  assert.ok((await worn.getAttribute('class')).includes('own'));
  assert.match(await worn.locator('.chance').innerText(), /kept fresh/);
  assert.ok(+await worn.getAttribute('data-chance') > F.my_ads_mix_chances[wornId], 'its chance went up');
  assert.match(await page.locator('#mx-worn-legend').innerText(), /1 kept fresh/);

  // Seen a lot: a knob turned moves the chart's counts; a double-click puts it back to its default.
  const familiar = page.locator('#mx-worn-knobs .fader').first();
  const held = async () => +(await page.locator('#mx-worn-legend').innerText()).match(/(\d+) held back/)[1];
  const before = await held();
  await familiar.locator('input').fill('1000');
  await page.waitForTimeout(80);
  assert.match(await familiar.locator('output').innerText(), /60 plays/);
  assert.ok(await held() < before, 'more plays before an ad feels familiar: fewer held back');
  await familiar.locator('input').dblclick();
  await page.waitForTimeout(80);
  assert.match(await familiar.locator('output').innerText(), /^6 plays$/);
  assert.equal(await held(), before);
  assert.equal(await page.locator('#mx-dirty').innerText(), '2 changes not saved yet');

  // New uploads: no boost until they last some days.
  const newKnobs = page.locator('#mx-new-knobs .fader');
  assert.equal(await newKnobs.nth(1).locator('input').isDisabled(), true);
  await newKnobs.nth(0).locator('input').fill('233');
  await page.waitForTimeout(80);
  assert.match(await newKnobs.nth(0).locator('output').innerText(), /^7 days$/);
  assert.equal(await newKnobs.nth(1).locator('input').isDisabled(), false);
  assert.match(await page.locator('#mx-new-say').innerText(), /uploaded in the last 7 days get[s]? ×2 their chance/);

  // Save: the whole draft, the ad's own wear with it; the page then shows it as saved.
  const save = await sent(t, '/v1/my-ads/mix', () => page.locator('#mx-save').click());
  assert.equal(save.body.kinds.tv.weight, 3);
  assert.equal(save.body.tuning.new_days, 7);
  assert.equal(save.body.tuning.familiar, 6);
  assert.deepEqual(save.body.overrides, {[wornId]: {boost: 1, wear: 0}});
  await page.waitForTimeout(100);
  assert.equal(await savebar.isVisible(), false);
  assert.equal(F.my_ads_mix.mix.overrides[wornId].wear, 0);
  assert.equal(await kind('tv').locator('.fader').first().getAttribute('class'), 'fader compact', 'saved: no longer lit');

  // By ad count: each kind's share as its count of ads (the readings agree), and its mark on the fader.
  const sizes = {};
  for (const a of F.my_ads_mix.ads) if (a.enabled) sizes[a.kind] = (sizes[a.kind] || 0) + 1;
  const all = Object.values(sizes).reduce((a, b) => a + b, 0);
  await page.locator('#mx-count').click();
  await page.waitForTimeout(80);
  for (const key of ['transit', 'tv', 'house']) {
    const want = Math.round(100 * sizes[key] / all);
    const [got, count] = (await kind(key).locator('output').first().innerText()).match(/(\d+)%[\s\S]*by count (\d+)%/).slice(1).map(Number);
    assert.equal(count, want, key);
    assert.ok(Math.abs(got - want) <= 1, `${key}: ${got}% as set, ${want}% by count`);
  }
  assert.equal(await kind('tv').locator('.notch.count').isVisible(), true);
  await page.locator('#mx-discard').click();
  await page.waitForTimeout(60);

  // Discard puts a change back; Back to defaults takes the ad's own setting away too (until saved).
  await share('cats').fill('0');
  await page.waitForTimeout(60);
  assert.match(await kind('cats').locator('output').first().innerText(), /^Off/);
  await page.locator('#mx-discard').click();
  await page.waitForTimeout(60);
  assert.match(await kind('cats').locator('output').first().innerText(), /^\d+%\s*by count/);
  assert.equal(await savebar.isVisible(), false);
  await page.locator('#mx-defaults').click();
  await page.waitForTimeout(80);
  assert.match(await page.locator('#mx-dirty-list').innerText(), /New for · TV & sports share · .+/);
  const toDefaults = await sent(t, '/v1/my-ads/mix', () => page.keyboard.press('ControlOrMeta+s'));
  assert.deepEqual(toDefaults.body.overrides, {[wornId]: null}, 'its own setting removed');
  assert.equal(toDefaults.body.kinds.tv.weight, 1);

  // The preview's days; the mix off at once (not a draft).
  assert.equal((await sent(t, '/v1/my-ads/mix/preview', () => page.locator('#mx-days [data-days="7"]').click())).body.days, 7);
  assert.deepEqual((await sent(t, '/v1/my-ads/mix', () => page.locator('#mx-on [data-on=false]').click())).body, {enabled: false});
  assert.equal(await page.locator('#mx-note').isVisible(), true);
  assert.match(await page.locator('#mx-note').innerText(), /The mix is off/);

  // Finding ads: by name, and those with their own settings.
  const name = F.my_ads_mix.ads.find(a => a.id === wornId).name;
  await page.locator('#mx-q').fill(name);
  await page.waitForTimeout(250);
  assert.equal(await rows.count(), 1);
  await page.locator('#mx-q').fill('');
  await page.locator('#mx-own').check();
  await page.waitForTimeout(100);
  assert.equal(await rows.count(), 0, 'the defaults saved: none has its own settings');
  assert.equal(await page.locator('#mx-ads-empty').isVisible(), true);
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);
  await t.ctx.close();

  // List order: the mix waits, and says so. A phone fits it all.
  t = await open(browser, '/ads#mix', {width: 390, api: API, edit: F => { F.my_ads_mix.order = 'list'; }});
  await t.page.waitForSelector('#mx-pv .stats');
  assert.match(await t.page.locator('#mx-note').innerText(), /list order now, so the mix waits/);
  assert.equal(await t.page.locator('#mx-on [data-on=true]').getAttribute('aria-pressed'), 'false');
  assert.equal(await overflow(t.page), 0, 'fits a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
