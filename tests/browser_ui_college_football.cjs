// College football can be selected and scheduled on desktop and mobile.
const {open, run, assert, overflow} = require('./ui_harness.cjs');

run(async browser => {
  for (const width of [1440, 390]) {
    const t = await open(browser, '/sources', {width, storage: {sourcesFilter: 'sports'}, api: {
      'GET /v1/sports/upcoming': (url, F) => {
        assert.equal(url.searchParams.get('league'), 'ncaaf');
        return {league: 'ncaaf', games: [{...F.nfl.games[0], league: 'ncaaf', game_id: 123,
          title: 'Notre Dame at Navy', short_title: 'ND @ NAVY', state: 'pre', status: 'Scheduled',
          start_time: '2026-10-03T16:00:00Z', game_date: '2026-10-03', start_time_tbd: false,
          broadcasts: [{name: 'ESPN', market: 'national'}],
          suggested_target: {source_id: 'youtube-tv', channel_id: 'ESPN'}, note: null}]};
      },
    }});
    await t.page.getByRole('radio', {name: /College Football \(Power 5\)/}).click();
    await t.page.getByRole('button', {name: 'Schedule Notre Dame at Navy', exact: true}).click();
    await t.page.waitForTimeout(200);
    const scheduled = t.posts.find(p => p.path === '/v1/programming/shows').body;
    assert.equal(scheduled.game.league, 'ncaaf');
    assert.equal(scheduled.game.game_pk, 123);
    assert.equal(Date.parse(scheduled.end) - Date.parse(scheduled.start), 4 * 3600e3);
    assert.equal(await overflow(t.page), 0);
    assert.deepEqual(t.errors, []);
    assert.deepEqual(t.unknown, []);
    await t.ctx.close();
  }
});
