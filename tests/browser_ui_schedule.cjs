// Schedule: the week as planned beside what will air, slots that follow the listings, sports
// slots, clashes, ideas, and an Undo for every change.
// node tests/browser_ui_schedule.cjs /path/to/playwright
const {open, run, assert} = require('./ui_harness.cjs');

// The server answers a slot or sports change with the whole schedule, and what changed.
const answers = {
  'POST /v1/programming': (body, F) => ({...F.programming, settings: {...F.programming.settings, ...body}}),
  'POST /v1/programming/slots': (body, F) => ({...F.programming, changed: {id: body.id || 'newslot', priority: 'normal', enabled: true, skip: [], ...body}}),
  'POST /v1/programming/slots/*': (body, F, where) => {
    const id = where.split('/')[4], slot = F.programming.settings.slots.find(s => s.id === id);
    return where.endsWith('/skip') ? {...F.programming, changed: {...slot, skip: body.skip === false ? [] : [body.date]}} : {...F.programming, changed: {...slot, ...body}};
  },
  'DELETE /v1/programming/slots/*': (body, F, where) => ({...F.programming, removed_slot: F.programming.settings.slots.find(s => s.id === where.split('/')[4])}),
  'POST /v1/programming/sports/preview': () => ({games: [{slot: 'x', slot_title: 'x', league: 'nfl', game_pk: 7, title: 'Giants at Eagles', start_time: '2026-10-09T00:15:00+00:00', networks: ['Prime Video'], favorites: [], status: 'would'}]}),
  'POST /v1/programming/sports': (body, F) => ({...F.programming, changed: {id: 'newsport', ...body}}),
  'POST /v1/programming/sports/*': (body, F) => ({...F.programming, changed: body}),
  'DELETE /v1/programming/sports/*': (body, F) => ({...F.programming, removed_slot: F.programming.settings.sports[0]}),
  'POST /v1/programming/shows': body => ({status: 201, json: {id: 'newshow', ...body}}),
  'POST /v1/programming/shows/*': (body, F) => F.programming,
  'DELETE /v1/programming/shows/*': (body, F) => F.programming,
  'POST /v1/programming/follow-games': (body, F) => ({...F.programming, changes: [{title: 'Phillies at Braves', text: 'Moved to 8 PM'}]}),
};
const settle = page => page.waitForTimeout(250);

run(async browser => {
  const t = await open(browser, '/schedule', {width: 1440, height: 1000, api: answers});
  const page = t.page, last = () => t.posts.at(-1);
  const undo = async () => { await page.locator('.toast button', {hasText: 'Undo'}).last().click(); await settle(page); };
  await page.waitForSelector('.ev.slot');
  assert.equal(t.posts.length, 0, 'looking changes nothing');

  // The plan and what becomes of it: seven days, the projection's edge, and each card's outcome.
  assert.equal(await page.locator('.cal .dayhead').count(), 7);
  assert.match(await page.locator('#on-now').innerText(), /Phillies/i);
  assert.ok(await page.locator('.air i').count() >= 5, 'what will air runs down each day');
  assert.ok(await page.locator('.air i.game').count() >= 1);
  const friday = page.locator('.col').nth(1);
  assert.match(await friday.locator('.ev.slot', {hasText: 'Jeopardy!'}).innerText(), /Won't air/i, 'the game runs through it');
  assert.match(await friday.locator('.ev.slot', {hasText: 'Jeopardy!'}).innerText(), /7\.1 WJLA/, 'found on its channel by the listings');
  assert.match(await page.locator('.ev.nothing', {hasText: 'Sunday Film'}).innerText(), /Not listed/i, 'a programme no channel lists has nothing to air');
  assert.match(await page.locator('.ev.slot', {hasText: "How It's Made"}).first().innerText(), /Library · How It's Made S01E01/);
  assert.equal(await page.locator('.ev.game .tag.hi').count() >= 1, true, 'the sports slot made its game High');

  // A slot's airing: where it comes from, and Skip this one (with its Undo).
  await friday.locator('.ev.slot', {hasText: 'Jeopardy!'}).click();
  const info = page.locator('#info-dialog');
  assert.match(await info.innerText(), /from the listings · “Tournament of Champions” · new/);
  assert.match(await info.innerText(), /Follows “Jeopardy!” through the listings; usually 7\.1 WJLA/);
  assert.match(await info.innerText(), /Its slot ends before Philadelphia Phillies at Atlanta Braves does/);
  await info.getByRole('button', {name: 'Skip this one'}).click(); await settle(page);
  assert.deepEqual([last().path, last().body], ['/v1/programming/slots/slot04/skip', {date: '2026-10-02', skip: true}]);
  await undo();
  assert.deepEqual(last().body, {date: '2026-10-02', skip: false});

  // Edit the slot: every field goes, the unchanged ones as they were.
  await friday.locator('.ev.slot', {hasText: 'Jeopardy!'}).click();
  await info.getByRole('button', {name: 'Edit slot'}).click();
  const dialog = page.locator('#slot-dialog');
  assert.equal(await dialog.locator('#program-search').inputValue(), 'Jeopardy!');
  assert.equal(await dialog.locator('#slot-days [aria-pressed=true]').count(), 5);
  await dialog.locator('#slot-start').fill('20:00');
  assert.match(await dialog.locator('#slot-ends').inputValue(), /8:30 PM/);
  await dialog.getByRole('button', {name: 'Save'}).click(); await settle(page);
  assert.equal(last().path, '/v1/programming/slots/slot04');
  assert.deepEqual([last().body.start, last().body.minutes, last().body.days.length, last().body.what.kind, last().body.what.target.channel_id],
    ['20:00', 30, 5, 'program', 'wjla_7_1']);
  await undo();
  assert.equal(last().body.start, '19:30', 'Undo puts the old time back');

  // Remove it from its dialog; Undo adds it back with its id.
  await friday.locator('.ev.slot', {hasText: 'Jeopardy!'}).click();
  await info.getByRole('button', {name: 'Edit slot'}).click();
  await dialog.getByRole('button', {name: 'Remove slot'}).click(); await settle(page);
  assert.deepEqual([last().method, last().path], ['DELETE', '/v1/programming/slots/slot04']);
  await undo();
  assert.deepEqual([last().method, last().path, last().body.id, last().body.title], ['POST', '/v1/programming/slots', 'slot04', 'Jeopardy!']);

  // Tapping an empty time offers what to add there; nothing is added until the dialog is saved.
  const before = t.posts.length, wrap = await page.locator('#cal-wrap').boundingBox();
  await page.evaluate(() => { document.getElementById('cal-wrap').scrollTop = 0; });   // Saturday morning: nothing is on.
  const saturday = await page.locator('.col').nth(2).boundingBox();
  await page.mouse.click(saturday.x + saturday.width / 2, wrap.y + 120);
  const menu = page.locator('.addmenu');
  assert.match(await menu.innerText(), /Add at Sat \d+:\d\d [AP]M/i);
  assert.equal(t.posts.length, before);
  await page.keyboard.press('Escape');
  assert.equal(await menu.count(), 0, 'Escape closes it');
  await page.mouse.click(saturday.x + saturday.width / 2, wrap.y + 120);
  const when = (await menu.locator('.label').innerText()).match(/(\d+):(\d\d) ([AP])M/i);
  const tapped = (+when[1] % 12 + (when[3].toUpperCase() === 'P' ? 12 : 0)) * 60 + +when[2];
  await menu.getByRole('button', {name: /A channel/}).click();
  assert.equal(await dialog.locator('#slot-days [aria-pressed=true]').innerText(), 'SAT');
  assert.equal(await dialog.locator('#slot-start').inputValue(), String(Math.floor(tapped / 60)).padStart(2, '0') + ':' + String(tapped % 60).padStart(2, '0'));
  await dialog.locator('#channel-target select').first().selectOption('youtube-tv');
  await page.waitForFunction(() => document.querySelectorAll('#channel-target select')[1]?.options.length > 1);
  await dialog.locator('#channel-target select').nth(1).selectOption('NBC');
  // A network on YouTube TV: the antenna goes on if YouTube TV is late, unless the slot waits for it.
  const late = dialog.locator('#channel-target').getByLabel('If YouTube TV is late');
  assert.match(await late.locator('option').first().textContent(), /Antenna 4\.1 WRC-HD goes on/);
  await late.selectOption('wait');
  await dialog.locator('#slot-title').fill('Saturday Night Live');
  await dialog.locator('#slot-minutes').selectOption('90');
  await dialog.getByRole('button', {name: 'Add to the lineup'}).click(); await settle(page);
  assert.equal(last().path, '/v1/programming/slots');
  assert.deepEqual({...last().body, start: 'x', color: 'x'}, {title: 'Saturday Night Live', color: 'x', days: ['sat'], start: 'x', minutes: 90, priority: 'normal',
    what: {kind: 'channel', target: {source_id: 'youtube-tv', channel_id: 'NBC', antenna: false}}});
  await undo();
  assert.deepEqual([last().method, last().path], ['DELETE', '/v1/programming/slots/newslot']);

  // A programme by name: the search fills in its channel and time, and weekdays is one tap.
  await page.locator('#add').click();
  await menu.getByRole('button', {name: /A programme/}).click();
  await dialog.locator('#program-search').fill('jeop');
  await dialog.locator('#program-results button').first().click();
  assert.match(await dialog.locator('#program-note').innerText(), /Listed .* for 30 min on 7\.1 WJLA/);
  assert.equal(await dialog.locator('#slot-start').inputValue(), '19:30');
  assert.equal(await dialog.locator('#slot-title').inputValue(), 'Jeopardy!');
  await dialog.getByRole('button', {name: 'Weekdays'}).click();
  assert.match(await dialog.locator('#slot-warning').innerText(), /Overlaps Jeopardy!/, 'it says what it would overlap');
  await dialog.getByRole('button', {name: 'Add to the lineup'}).click(); await settle(page);
  assert.deepEqual([last().body.days, last().body.what], [['mon', 'tue', 'wed', 'thu', 'fri'], {kind: 'program', title: 'Jeopardy!', follow: true, target: {source_id: 'tv-thing-digital', channel_id: 'wjla_7_1'}}]);

  // Just once: a show on a date, on the channel chosen.
  await page.locator('#add').click();
  await menu.getByRole('button', {name: /A channel/}).click();
  await dialog.getByRole('button', {name: 'Just once'}).click();
  await dialog.locator('#slot-date').fill('2026-10-03');
  await dialog.locator('#slot-start').fill('21:00');
  await dialog.locator('#slot-title').fill('Election special');
  await dialog.locator('#channel-target select').first().selectOption('tv-thing-digital');
  await page.waitForFunction(() => document.querySelectorAll('#channel-target select')[1]?.options.length > 1);
  await dialog.getByRole('button', {name: 'Add this once'}).click(); await settle(page);
  const once = t.posts.filter(p => p.path === '/v1/programming/shows').at(-1);
  assert.deepEqual([once.body.mode, once.body.title, once.body.start, once.body.end, once.body.target.source_id],
    ['program', 'Election special', '2026-10-04T01:00:00.000Z', '2026-10-04T01:30:00.000Z', 'tv-thing-digital']);

  // From the library: the folder sets the order and the length; ad breaks only where they were found.
  await page.locator('#add').click();
  await menu.getByRole('button', {name: /From the library/}).click();
  await page.waitForFunction(() => document.querySelector('#library-folder')?.options.length >= 1 && document.querySelector('#library-folder').value);
  assert.match(await dialog.locator('#library-folder option').first().textContent(), /How It's Made · Jellyfin TV · 8 files/);
  assert.equal(await dialog.locator('#library-order').inputValue(), 'next');
  assert.equal(await dialog.getByRole('button', {name: 'Just once'}).isDisabled(), true);
  await dialog.getByRole('button', {name: 'Add to the lineup'}).click(); await settle(page);
  assert.deepEqual(last().body.what, {kind: 'library', root: 'jellyfin-tv', order: 'next', path: "How It's Made/", ad_breaks: 120});
  assert.equal(last().body.title, "How It's Made");

  // The automation switch saves only itself.
  await page.locator('#enabled').uncheck(); await settle(page);
  assert.deepEqual([last().path, last().body], ['/v1/programming', {enabled: false}]);
  await page.locator('#enabled').check(); await settle(page);

  // A game: its priority from its card, and what the sports slot did.
  await page.locator('.ev.game', {hasText: 'Atlanta Falcons'}).first().click();
  assert.match(await info.innerText(), /The sports slot Monday Night Football/);
  await info.getByRole('button', {name: 'normal'}).click(); await settle(page);
  assert.deepEqual([last().path.split('/').slice(0, 4).join('/'), last().body], ['/v1/programming/shows', {priority: 'normal'}]);
  await undo();
  assert.deepEqual(last().body, {priority: 'high'});

  // Dragging with a mouse moves the slot for all its days, by five minutes.
  const view = page.locator('.col').nth(1).locator('.ev.slot', {hasText: 'The View'});
  await page.evaluate(() => { window.scrollTo(0, 0); document.getElementById('cal-wrap').scrollTop = 250; });
  const box = await view.boundingBox();
  await page.mouse.move(box.x + 30, box.y + 8); await page.mouse.down();
  await page.mouse.move(box.x + 30, box.y + 30, {steps: 3}); await page.mouse.move(box.x + 30, box.y + 8 + 33, {steps: 3});
  assert.match(await page.locator('.dragtip').innerText(), /11:30 AM – 12:30 PM/);
  await page.mouse.up(); await settle(page);
  assert.deepEqual([last().path, last().body], ['/v1/programming/slots/slot01', {start: '11:30'}]);
  assert.equal(await info.evaluate(d => d.open), false, 'a drag is not a click');

  // Ideas: one click adds; a fix-up changes its slot; a sports idea adds the slot.
  await page.locator('[data-tab=ideas]').click();
  await page.waitForSelector('#ideas .card');
  assert.equal(await page.locator('#ideas-count').innerText(), '5');
  await page.locator('#ideas .card', {hasText: 'Wheel of Fortune'}).getByRole('button', {name: 'Add'}).click(); await settle(page);
  assert.deepEqual([last().path, last().body.title, last().body.what.kind, last().body.days.length], ['/v1/programming/slots', 'Wheel of Fortune', 'program', 5]);
  await page.waitForSelector('#ideas .card');
  await page.locator('#ideas .card', {hasText: 'The View'}).getByRole('button', {name: 'Do it'}).click(); await settle(page);
  assert.deepEqual([last().path, last().body.what.kind, last().body.what.title], ['/v1/programming/slots/slot01', 'program', 'The View']);
  await page.waitForSelector('#ideas .card');
  await page.locator('#ideas .card', {hasText: 'Sunday Night Football'}).getByRole('button', {name: 'Add'}).click(); await settle(page);
  assert.deepEqual([last().path, last().body.preset, last().body.priority], ['/v1/programming/sports', 'nfl-snf', 'high']);
  await page.waitForSelector('#ideas .card');
  await page.locator('#ideas .card', {hasText: 'Dancing With the Stars'}).getByRole('button', {name: 'Add'}).click(); await settle(page);
  assert.deepEqual([last().path, last().body.mode, last().body.title], ['/v1/programming/shows', 'program', 'Dancing With the Stars']);

  // Draft a week: suggestions appear on the week, on the days they fit; Add all adds each.
  await page.waitForSelector('#ideas .card');
  await page.locator('#draft').click();
  assert.equal(await page.locator('.ev.ghost', {hasText: 'Wheel of Fortune'}).count(), 4, 'Monday to Thursday, as the draft says');
  assert.match(await page.locator('#draftbar').innerText(), /2 suggestions are shown/);
  const added = t.posts.length;
  await page.locator('#draftbar').getByRole('button', {name: 'Add all 2'}).click(); await page.waitForTimeout(600);
  const drafted = t.posts.slice(added).filter(p => p.path === '/v1/programming/slots');
  assert.deepEqual(drafted.map(p => [p.body.title, p.body.days.length]), [['Wheel of Fortune', 4], ['Cab Rides', 2]]);
  // Hide: an idea goes away and stays away.
  await page.waitForSelector('#ideas .card');
  await page.locator('#ideas .card', {hasText: 'Cab Rides'}).getByRole('button', {name: 'Hide', exact: true}).click();
  assert.equal(await page.locator('#ideas .card', {hasText: 'Cab Rides'}).count(), 0);
  assert.equal(await page.locator('#ideas-count').innerText(), '4');

  // Sports: the slot there is, a ready-made one set up, and a priority changed in the list.
  await page.locator('[data-tab=sports]').click();
  await page.waitForSelector('#sports-slots li');
  assert.match(await page.locator('#sports-slots li').first().innerText(), /Monday Night Football[\s\S]*Mon · games starting 7:00 PM–11:30 PM · on ESPN, ABC[\s\S]*Atlanta Falcons/);
  await page.locator('#sports-slots .card', {hasText: 'Thursday Night Football'}).getByRole('button', {name: 'Set up'}).click();
  const sports = page.locator('#sports-dialog');
  await page.waitForSelector('#sp-preview li .chip');
  assert.match(await sports.locator('#sp-preview').innerText(), /Giants at Eagles[\s\S]*Prime Video[\s\S]*Airs/i);
  assert.equal(await sports.locator('[name=sp-priority]:checked').inputValue(), 'high');
  await sports.locator('[name=sp-priority][value=normal]').check();
  await sports.getByRole('button', {name: 'Add sports slot'}).click(); await settle(page);
  assert.deepEqual(last().body, {title: 'Thursday Night Football', league: 'nfl', days: ['thu'], from: '19:00', to: '23:30', networks: [], teams: [],
    pick: 'all', priority: 'normal', lead_minutes: 0, preset: 'nfl-tnf'});
  await page.locator('#sports-slots li select').first().selectOption('low'); await settle(page);
  assert.deepEqual([last().path, last().body], ['/v1/programming/sports/sportmnf', {priority: 'low'}]);

  // Clashes: a game the projection has joining late can be given the time.
  await page.locator('[data-tab=clashes]').click();
  assert.ok(await page.locator('#clashes').innerText());
  // The lineup as a list: a slot switched off from there.
  await page.locator('[data-tab=lineup]').click();
  assert.equal(await page.locator('#lineup li').count(), 6);
  assert.match(await page.locator('#lineup li[data-slot=slotfilm]').innerText(), /Follows “The Sunday Film” · skipped when not listed/);
  await page.locator('#lineup li[data-slot=slot02] input').uncheck(); await settle(page);
  assert.deepEqual([last().path, last().body], ['/v1/programming/slots/slot02', {enabled: false}]);
  await page.locator('#follow-games').click(); await settle(page);
  assert.equal(last().path, '/v1/programming/follow-games');
  await page.locator('[data-tab=rundown]').click();
  assert.ok(await page.locator('#rundown li').count() >= 5);
  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);

  // A phone: one day at a time, nothing scrolls sideways, a tap opens and never drags.
  const phone = await open(browser, '/schedule', {width: 390, height: 844, api: answers});
  await phone.page.waitForSelector('.ev');
  assert.equal(await phone.page.locator('.cal .dayhead').count(), 1, 'a phone opens on one day');
  assert.ok(await phone.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no sideways scroll');
  await phone.page.locator('#day-next').click();
  assert.match(await phone.page.locator('.cal .dayhead').innerText(), /Fri 10\/2/i);
  await phone.page.locator('.ev.slot', {hasText: 'The View'}).tap().catch(() => phone.page.locator('.ev.slot', {hasText: 'The View'}).click());
  assert.match(await phone.page.locator('#info-dialog').innerText(), /Always this channel/);
  await phone.page.locator('#info-close').click();
  await phone.page.locator('#view-week').click();
  assert.equal(await phone.page.locator('.cal .dayhead').count(), 7);
  assert.equal(phone.posts.length, 0);
  assert.deepEqual(phone.errors, []);
  console.log('Schedule: ok');
});
