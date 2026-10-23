// Ad mute: its tab of Ads (mode, quick fixes, recent breaks, settings, the last hour) and its
// tally and buttons on On Air. node tests/browser_ui_admute.cjs /path/to/playwright
const {open, run, assert} = require('./ui_harness.cjs');

run(async browser => {
  const view = (F, settings) => ({...F.admute, settings: {...F.admute.settings, ...settings}});
  let t = await open(browser, '/ads#admute', {api: {
    // Like the real server, a change sticks: the page's own polling must not undo it.
    'POST /v1/admute': (body, F) => (F.admute = view(F, body)),
    'POST /v1/admute/override': (body, F) => ({...F.admute, override: {accepted: true}}),
    'POST /v1/admute/label': (body, F) => F.admute,
    'POST /v1/admute/pause': (body, F) => (F.admute = view(F, body.resume ? {paused_until: null, paused_input: null} : {paused_until: Date.now() / 1000 + 3600, paused_input: F.admute.on_air.id})),
    'POST /v1/admute/forget': (body, F) => F.admute,
    'POST /v1/admute/recordings/cancel': (body, F) => F.admute_recordings,
    'GET /v1/admute/known': () => ({updated: 1790907300, clips: [
      {id: 12, kind: 'ad', known: true, breaks: 3, first: 1790900000, last: 1790906700, dur: 118.5, src: 'Phillies at Braves', seed: 'game-849844', hashes: 3700},
      {id: 7, kind: 'show', known: true, breaks: 2, first: 1790800000, last: 1790905000, dur: 9.0, src: 'Jeopardy! - 7.1 WJLA - 2026-09-28 1930.mp4', seed: 'extra', hashes: 280},
      {id: 53, kind: 'ad', known: false, breaks: 1, first: 1790906000, last: 1790906000, dur: 95.0, src: 'break', seed: null, hashes: 3000}]}),
  }});
  const page = t.page;
  await page.waitForSelector('#spans tr');

  // What is on air, and how sure the detector is.
  assert.match(await page.locator('#status').textContent(), /Listening/);
  assert.match(await page.locator('#status-detail').textContent(), /Phillies at Braves.*MLB feed live/);
  assert.equal(await page.locator('#mode [data-mode=shadow]').getAttribute('aria-pressed'), 'true');
  assert.match(await page.locator('#detector-chip').textContent(), /linked/);
  assert.equal(await page.locator('#unmute').textContent(), "It's the show", 'shadow mode labels, not mutes');

  // Pictures: what is on master now (the detector saw it `delay` seconds ago), and the
  // half-minute before, so the operator can find what their own player is showing.
  const now = Math.floor(Date.parse('2026-10-02T02:16:40Z') / 1000) - 6, key = t.F.admute.on_air.id;
  await page.waitForFunction(() => document.getElementById('now-img').src.startsWith('blob:'));
  assert.ok(t.frames.includes(`/v1/admute/frame/${key}/${now}.jpg`), 'the picture on master now');
  assert.match(await page.locator('#now-stamp').textContent(), /\d:\d\d:\d\d/);
  assert.equal(await page.locator('#strip .frame').count(), 10);
  assert.equal(await page.locator('#strip .frame').last().locator('.t').textContent(), '−1 s');
  assert.equal(await page.locator('#strip .frame').first().locator('.t').textContent(), '−28 s');
  assert.match(await page.locator('#heard').textContent(), /Hears: “swung on and missed/);

  // Known ads: the database, this game's learning, what it learnt lately (each forgettable).
  assert.match(await page.locator('#status-detail').textContent(), /a known ad is playing/);
  assert.equal(await page.locator('#why').textContent(), 'Why: 95% · KNOWN AD — Braves at Dodgers · heard 3x');
  assert.equal(await page.locator('#known-chip').textContent(), '31 known');
  assert.match(await page.locator('#known-summary').textContent(), /31 known ads, 29 of them from recordings and games, plus 13 heard once .* 3 show sounds/);
  assert.match(await page.locator('#game-learning').textContent(), /6 so far \(4 new ads\) · the broadcast runs 38 s behind the feed/);
  const log = page.locator('#known-log li');
  assert.equal(await log.count(), 5);
  assert.match(await log.first().textContent(), /Forgot an ad: it's the show/);
  assert.match(await log.nth(2).textContent(), /3 breaks learnt from MLB's play-by-play, 2 of them new/);
  await log.nth(2).getByText('Forget').click();
  await page.waitForTimeout(150);
  assert.deepEqual([t.posts.at(-1).path, t.posts.at(-1).body], ['/v1/admute/forget', {clips: [52, 53, 12]}]);
  await page.locator('#known-all summary').click();
  await page.waitForSelector('#known-table tr');
  assert.equal(await page.locator('#known-table tr').count(), 3);
  assert.match(await page.locator('#known-table tr').nth(1).textContent(), /show sound/);
  await page.locator('#known-table tr').nth(2).getByText('Forget').click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {clips: [53]});

  // Training recordings: TV-Thing timers for over-the-air games, and what was learnt from them.
  await page.waitForSelector('#rec-table tr');
  const recs = page.locator('#rec-table tr');
  assert.equal(await recs.count(), 2);
  assert.match(await recs.first().textContent(), /Atlanta Braves at Los Angeles Dodgers.*WTTG-DT.*scheduled \(your timer\)/);
  assert.match(await recs.nth(1).textContent(), /learnt · 14 breaks fingerprinted · training labels saved · in the library/);
  assert.equal(await recs.nth(1).locator('button').count(), 0, 'nothing to cancel once done');
  assert.equal(await page.locator('#rec-chip').textContent(), '1 planned');
  assert.match(await page.locator('#rec-skipped').textContent(), /White Sox .* cable only/);
  await recs.first().getByText('Cancel').click();
  await page.locator('dialog.confirm button.primary').click();
  await page.waitForTimeout(150);
  assert.deepEqual([t.posts.at(-1).path, t.posts.at(-1).body], ['/v1/admute/recordings/cancel', {game: 'mlb-849828'}]);

  // Recent breaks, newest first; marking one is a training label.
  const rows = await page.locator('#spans tr').count();
  assert.ok(rows >= 5, 'the last hour\'s breaks are listed');
  await page.locator('#spans tr').first().getByText('Was the show').click();
  await page.waitForTimeout(150);
  let post = t.posts.at(-1);
  assert.equal(post.path, '/v1/admute/label');
  assert.equal(post.body.label, 'show');
  assert.match(post.body.span_id, /^86bb133f-/);

  // Each break shows its edges; clicking them opens the whole break to judge it by.
  const newest = t.F.admute.detector.inputs[0].spans.at(-1);
  assert.match(await page.locator('#spans tr').first().textContent(), /known ad/, 'its sound matched a known ad');
  assert.doesNotMatch(await page.locator('#spans tr').nth(1).textContent(), /known ad/);
  assert.match(await page.locator('#spans tr').nth(1).textContent(), /90% · PICTURE — no station or score bug \+ fast cutting · black frame/);
  assert.equal(await page.locator('#spans tr').first().locator('.edges .shot').count(), 3);
  assert.ok(t.frames.includes(`/v1/admute/frame/${key}/${Math.round(newest.start - 3)}.jpg`), 'just before the break');
  await page.locator('#spans tr').first().locator('button.frame').click();
  const sheet = page.locator('dialog.break');
  await sheet.waitFor();
  const cells = await sheet.locator('.sheet .shot').count();
  assert.ok(cells >= 8 && cells <= 20, `a contact sheet of the break (${cells})`);
  assert.ok(await sheet.locator('.sheet .call-bar.ad').count() >= 1, 'the muted part is marked under its pictures');
  await sheet.getByText('Ad ✓').click();
  await page.waitForTimeout(150);
  assert.deepEqual([t.posts.at(-1).path, t.posts.at(-1).body.label, t.posts.at(-1).body.span_id], ['/v1/admute/label', 'ad', newest.id]);
  assert.equal(await page.locator('dialog.break').count(), 0);

  // The quick fixes: buttons and keys.
  await page.locator('#unmute').click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1), {...t.posts.at(-1), path: '/v1/admute/override', body: {action: 'unmute'}});
  await page.keyboard.press('a');
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {action: 'mute'});

  // Turning it on asks first.
  await page.locator('#mode [data-mode=on]').click();
  await page.locator('dialog.confirm button.primary').click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {mode: 'on'});
  assert.equal(await page.locator('#mode [data-mode=on]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#unmute').textContent(), "It's the show · unmute");

  // Settings: the whole form, and the radio level only with Cairo radio.
  assert.equal(await page.locator('#radio-level-row').isVisible(), false);
  await page.locator('#sound').selectOption('radio');
  assert.equal(await page.locator('#radio-level-row').isVisible(), true);
  await page.locator('#sensitivity').fill('0.2');
  assert.match(await page.locator('#sens-text').textContent(), /cautious/);
  await page.locator('#exceptions').fill('Jeopardy!\nNightly News');
  await page.locator('#save').click();
  await page.waitForTimeout(150);
  post = t.posts.at(-1);
  assert.equal(post.path, '/v1/admute');
  assert.equal(post.body.sound, 'radio');
  assert.equal(post.body.sensitivity, 0.2);
  assert.deepEqual(post.body.exceptions, ['Jeopardy!', 'Nightly News']);
  assert.deepEqual(Object.keys(post.body).sort(), ['badge', 'diagnostic', 'exceptions', 'known_ads', 'learn', 'learn_ads', 'learn_games', 'lookahead', 'max_mute', 'radio_db', 'record_games', 'sensitivity', 'sound', 'sources', 'speech', 'sports_gate']);
  assert.equal(post.body.diagnostic, false);
  assert.equal(post.body.known_ads, true);

  // Pause for this program, then resume.
  await page.locator('#pause').click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {hours: 6});
  assert.equal(await page.locator('#resume').isVisible(), true);
  await page.locator('#resume').click();
  await page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {resume: true});

  // The last hour is drawn behind the machinery switch.
  await page.keyboard.press('m');
  assert.equal(await page.locator('#timeline').isVisible(), true);
  assert.match(await page.locator('#model').textContent(), /Whisper base\.en · busy 41%/);
  assert.match(await page.locator('#model').textContent(), /31 known ads \(13 heard once\) · 3 show sounds/);
  const painted = await page.evaluate(() => { const c = document.getElementById('timeline'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) n += d[i] > 0; return n; });
  assert.ok(painted > 1000, 'the timeline is painted');
  assert.equal(await page.locator('#speech-model-row').isVisible(), false, 'the captured web app has no model setting');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // The Whisper model, from a web app that has the setting; how late the words come.
  t = await open(browser, '/ads#admute', {edit: F => { F.admute.settings.speech_model = 'base.en'; F.admute.detector.speech.lag = 5.2; },
    api: {'POST /v1/admute': (body, F) => view(F, body)}});
  await t.page.waitForSelector('#spans tr');
  assert.equal(await t.page.locator('#speech-model').inputValue(), 'base.en');
  await t.page.locator('#speech-model').selectOption('small.en');
  await t.page.locator('#save').click();
  await t.page.waitForTimeout(150);
  assert.equal(t.posts.at(-1).body.speech_model, 'small.en');
  await t.page.keyboard.press('m');
  assert.match(await t.page.locator('#model').textContent(), /words up to 5\.2 s late/);
  assert.deepEqual(t.errors, []);
  await t.ctx.close();

  // A web app older than the Whisper switch: the switch is off limits, and saving leaves it out.
  t = await open(browser, '/ads#admute', {edit: F => { for (const k of ['speech', 'known_ads', 'learn_ads', 'learn_games', 'diagnostic', 'record_games']) delete F.admute.settings[k]; },
    api: {'POST /v1/admute': (body, F) => view(F, body)}});
  await t.page.waitForSelector('#spans tr');
  assert.equal(await t.page.locator('#speech').isDisabled(), true);
  await t.page.locator('#sensitivity').fill('0.3');
  await t.page.locator('#save').click();
  await t.page.waitForTimeout(150);
  assert.equal('speech' in t.posts.at(-1).body, false);
  assert.equal('known_ads' in t.posts.at(-1).body, false);
  assert.equal('learn_games' in t.posts.at(-1).body, false);
  assert.equal(await t.page.locator('#learn-games').isDisabled(), true);
  assert.equal(await t.page.locator('#known-ads').isDisabled(), true);
  await t.ctx.close();

  // Classic or new detector: saved at once, and the page says what actually runs.
  t = await open(browser, '/ads#admute', {
    edit: F => { F.admute.settings.detector = 'classic'; F.admute.detector.detector = {selected: 'classic', running: 'classic', error: null, available: ['classic', 'new'], clip_ms: null}; },
    api: {'POST /v1/admute': (body, F) => (F.admute = {...view(F, body), detector: {...F.admute.detector, detector: {selected: body.detector, running: 'classic', error: 'CLIP cannot load: no model', available: ['classic', 'new'], clip_ms: null}}})},
  });
  await t.page.waitForTimeout(800);
  assert.equal(await t.page.locator('#detector [data-detector=classic]').getAttribute('aria-pressed'), 'true');
  assert.match(await t.page.locator('#detector-note').textContent(), /^Classic/);
  await t.page.locator('#detector [data-detector=new]').click();
  await t.page.waitForTimeout(300);
  assert.deepEqual([t.posts.at(-1).path, t.posts.at(-1).body], ['/v1/admute', {detector: 'new'}]);
  assert.equal(await t.page.locator('#detector [data-detector=new]').getAttribute('aria-pressed'), 'true');
  assert.match(await t.page.locator('#detector-note').textContent(), /cannot run: CLIP cannot load.*classic one is running/);
  await t.ctx.close();
  // A web app without the choice: the switch is off.
  t = await open(browser, '/ads#admute');
  await t.page.waitForTimeout(800);
  assert.equal(await t.page.locator('#detector [data-detector=new]').isDisabled(), true);
  assert.match(await t.page.locator('#detector-note').textContent(), /predates/);
  assert.equal(await t.page.locator('#judge-row').isHidden(), true, 'nor the judge');
  await t.ctx.close();

  // The transcript judge: saved with the settings; the page says what it costs, or why it is not asking.
  const judge = {model: 'claude-haiku-5-5', effort: 'medium', calls_today: 412, usd_today: 0.0371, budget: 1, queued: 0,
                 dropped: 0, failed: 0, error: null, ms_p50: 1300, ms_p95: 2500, why_not: null, on: true, used: true};
  const judging = extra => F => {
    Object.assign(F.admute.settings, {detector: 'new', judge: true, judge_budget: 1});
    F.admute.detector.detector = {selected: 'new', running: 'new', error: null, available: ['classic', 'new'], clip_ms: 160};
    F.admute.detector.judge = {...judge, ...extra};
  };
  t = await open(browser, '/ads#admute', {edit: judging({}), api: {'POST /v1/admute': (body, F) => (F.admute = view(F, body))}});
  await t.page.waitForTimeout(800);
  assert.equal(await t.page.locator('#judge').isChecked(), true);
  assert.equal(await t.page.locator('#judge-budget').inputValue(), '1');
  assert.match(await t.page.locator('#judge-note').textContent(), /412 calls today, \$0\.04 of \$1\.00 · 1\.3 s typical, 2\.5 s slow\.$/);
  await t.page.locator('#judge').uncheck();
  await t.page.locator('#judge-budget').fill('2.5');
  await t.page.locator('#save').click();
  await t.page.waitForTimeout(300);
  assert.deepEqual([t.posts.at(-1).body.judge, t.posts.at(-1).body.judge_budget], [false, 2.5]);
  assert.match(await t.page.locator('#judge-note').textContent(), /^Off/);
  await t.ctx.close();
  t = await open(browser, '/ads#admute', {edit: judging({why_not: 'no ANTHROPIC_API_KEY (environment or keys file)'})});
  await t.page.waitForTimeout(800);
  assert.match(await t.page.locator('#judge-note').textContent(), /^Not asking: no ANTHROPIC_API_KEY/);
  await t.ctx.close();
  t = await open(browser, '/ads#admute', {edit: judging({calls_today: 600, pictures_today: 188})});
  await t.page.waitForTimeout(800);
  assert.match(await t.page.locator('#judge-note').textContent(), /looks at the picture when the detector is unsure.*600 calls today \(188 on pictures\), \$0\.04/);
  await t.ctx.close();
  t = await open(browser, '/ads#admute', {edit: judging({calls_today: 300, skipped_today: 900})});
  await t.page.waitForTimeout(800);
  assert.match(await t.page.locator('#judge-note').textContent(), /300 calls today, \$0\.04 of \$1\.00 · 900 not needed \(the detector was already sure\) · 1\.3 s typical/);
  await t.ctx.close();

  // Lookahead: up to 12 s (Haiku's verdicts land before a break's first black frame airs).
  t = await open(browser, '/ads#admute', {api: {'POST /v1/admute': (body, F) => (F.admute = view(F, body))}});
  await t.page.waitForTimeout(800);
  await t.page.locator('summary', {hasText: 'Lookahead'}).click();
  await t.page.locator('#lookahead').fill('12');
  assert.equal(await t.page.locator('#lookahead').evaluate(e => e.checkValidity()), true);
  await t.page.locator('#save').click();
  await t.page.waitForTimeout(300);
  assert.equal(t.posts.at(-1).body.lookahead, 12);
  await t.page.locator('#lookahead').fill('12.5');
  assert.equal(await t.page.locator('#lookahead').evaluate(e => e.checkValidity()), false, 'past 12: the page refuses it');
  await t.ctx.close();

  // With the detector down, the page says nothing is muted.
  t = await open(browser, '/ads#admute', {edit: F => { F.admute.detector_stale = true; }});
  await t.page.waitForTimeout(800);
  assert.match(await t.page.locator('#error').textContent(), /not running: nothing is muted/);
  await t.ctx.close();

  // On Air: the tally and the two buttons while a break is (would be) muted.
  t = await open(browser, '/air', {
    edit: F => { F.master.admute = {connected: true, mode: 'shadow', error: null, on_air: {state: 'muted', p_ad: 0.97, override: null, fresh: true}}; },
    api: {'POST /v1/admute/override': (body, F) => ({...F.admute, override: {accepted: true}})},
  });
  await t.page.waitForTimeout(1000);
  assert.match(await t.page.locator('#bug').textContent(), /AD · shadow/i);
  assert.equal(await t.page.locator('#admute-row').isVisible(), true);
  assert.match(await t.page.locator('#admute-text').textContent(), /would mute: ad break · 97%/);
  await t.page.waitForFunction(() => document.querySelector('#admute-shot img').src.startsWith('blob:'));
  assert.ok(t.frames.some(f => f.startsWith('/v1/admute/frame/' + t.F.master.on_air.id + '/')), 'On Air shows what a fix applies to');
  await t.page.locator('#admute-show').click();
  await t.page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {action: 'unmute'});
  await t.page.keyboard.press('a');
  await t.page.waitForTimeout(150);
  assert.deepEqual(t.posts.at(-1).body, {action: 'mute'});
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
  console.log('ad mute UI: ok');
});
