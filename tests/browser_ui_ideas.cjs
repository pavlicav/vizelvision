// Engineering › Ideas: the board grouped by status, adding, editing in place, moving and deleting.
// node tests/browser_ui_ideas.cjs /path/to/playwright
const {open, run, assert, overflow, NOW} = require('./ui_harness.cjs');

// A board the mocked server keeps, so each write answers with the board as it now is.
function server() {
  let next = 0;
  const find = (F, where) => F.ideas.ideas.find(i => i.id === where.split('/').pop());
  return {
    'POST /v1/ideas': (body, F) => {
      const idea = {id: 'new' + next++, note: '', status: 'idea', created: NOW / 1000, updated: NOW / 1000, ...body};
      F.ideas.ideas.push(idea);
      return {...F.ideas, added: idea.id};
    },
    'POST /v1/ideas/*': (body, F, where) => { Object.assign(find(F, where), body, {updated: NOW / 1000}); return F.ideas; },
    'DELETE /v1/ideas/*': (body, F, where) => { F.ideas.ideas = F.ideas.ideas.filter(i => i !== find(F, where)); return F.ideas; },
  };
}

run(async browser => {
  let t = await open(browser, '/engineering#ideas', {api: server()});
  const page = t.page;
  await page.waitForSelector('#ideas .idea');
  assert.equal(await page.locator('[role=tab][data-tab=ideas]').getAttribute('aria-selected'), 'true');

  // Grouped by status, Next before Ideas, with the count.
  const groups = page.locator('#ideas section');
  assert.deepEqual(await groups.locator('h2').allTextContents(), ['Next', 'Ideas']);
  assert.equal(await page.locator('#idea-count').textContent(), '3 ideas');
  assert.equal(await groups.nth(1).locator('.idea').count(), 2);
  assert.equal(await page.locator('.idea[data-id=b2c3d4e5f6a1] textarea').inputValue(), 'More feed.json devices. Depends on the source registry.');
  assert.match(await page.locator('.idea[data-id=b2c3d4e5f6a1]').textContent(), /changed/);

  // Add one: title and area; it lands in Ideas and the field clears.
  await page.locator('#idea-title').fill('Roku navigation as its own process');
  await page.locator('#idea-area').selectOption('tv-thing');
  await page.locator('#idea-save').click();
  await page.waitForFunction(() => document.getElementById('idea-count').textContent === '4 ideas');
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/ideas', body: {title: 'Roku navigation as its own process', area: 'tv-thing'}});
  assert.equal(await page.locator('#idea-title').inputValue(), '');
  assert.equal(await groups.nth(1).locator('.idea').count(), 3);

  // An empty title is not sent.
  const sent = t.posts.length;
  await page.locator('#idea-save').click();
  assert.equal(t.posts.length, sent);

  // Edit a note in place: it is sent on change, and the board is not redrawn under the cursor.
  const note = page.locator('.idea[data-id=c3d4e5f6a1b2] textarea');
  await note.fill('Its feeds start on demand.');
  await note.blur();
  for (let i = 0; i < 50 && t.posts.at(-1).path !== '/v1/ideas/c3d4e5f6a1b2'; i++) await page.waitForTimeout(20);
  assert.deepEqual(t.posts.at(-1), {method: 'POST', path: '/v1/ideas/c3d4e5f6a1b2', body: {note: 'Its feeds start on demand.'}});
  assert.equal(await note.evaluate(n => n.isConnected), true, 'not redrawn');

  // Moving it to Doing redraws: Doing comes first.
  await page.locator('.idea[data-id=c3d4e5f6a1b2] select[aria-label=Status]').selectOption('doing');
  await page.waitForFunction(() => document.querySelector('#ideas section h2').textContent === 'Doing');
  assert.deepEqual(await groups.locator('h2').allTextContents(), ['Doing', 'Next', 'Ideas']);
  assert.deepEqual(t.posts.at(-1).body, {status: 'doing'});

  // Delete asks first; Cancel keeps it, Delete removes it.
  await page.locator('.idea[data-id=a1b2c3d4e5f6]').getByRole('button', {name: 'Delete'}).click();
  await page.locator('dialog.confirm').getByRole('button', {name: 'Cancel'}).click();
  assert.equal(await page.locator('.idea[data-id=a1b2c3d4e5f6]').count(), 1);
  await page.locator('.idea[data-id=a1b2c3d4e5f6]').getByRole('button', {name: 'Delete'}).click();
  await page.locator('dialog.confirm').getByRole('button', {name: 'Delete'}).click();
  await page.waitForFunction(() => !document.querySelector('.idea[data-id=a1b2c3d4e5f6]'));
  assert.deepEqual(t.posts.at(-1), {method: 'DELETE', path: '/v1/ideas/a1b2c3d4e5f6', body: null});
  assert.deepEqual(await groups.locator('h2').allTextContents(), ['Doing', 'Ideas']);

  assert.deepEqual(t.errors, []);
  assert.deepEqual(t.unknown, []);
  await t.ctx.close();

  // An empty board says so, and the page fits a phone.
  t = await open(browser, '/engineering#ideas', {width: 390, height: 844, edit: F => { F.ideas.ideas = []; }});
  await t.page.waitForSelector('#ideas .hint');
  assert.match(await t.page.locator('#ideas').textContent(), /No ideas yet/);
  assert.equal(await t.page.locator('#idea-count').textContent(), '0 ideas');
  assert.ok(await overflow(t.page) <= 0, 'no sideways scroll on a phone');
  assert.deepEqual(t.errors, []);
  await t.ctx.close();
});
