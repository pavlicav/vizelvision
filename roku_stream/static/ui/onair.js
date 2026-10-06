// Putting something on air works the same on every page.
//   Play now      Front of Up next. It cuts in as soon as the source is ready, and ends a game
//                 or take that is holding master.
//   Add to queue  After everything waiting in Up next: it plays when what is before it ends.
//                 A live source asks first how long it plays; a recording plays to its end.
//   Schedule      A show or game in the schedule at its start (a recording joins Up next then).
// "Plays until" is how long a live source holds master once on: its game's final, its listed
// program's end, a time, or no set end (then the schedule's next change takes over).
// "Source", for NBC, FOX, ABC, CBS and The CW and their games: YouTube TV, or the antenna
// (TV-Thing) if YouTube TV is not ready in time (the default); YouTube TV only; or the antenna.
//
// An item is {kind: 'channel'|'program'|'game'|'recording', target, title, detail?,
//   program?: {id, title, start, end} (epoch seconds), game?: {league, game_pk, game_date,
//   title, start (ISO), state}, duration? (seconds), youtube_tv? (the channel an MLB game is on)}.
window.OnAir = (() => {
  'use strict';
  const {h, api, fmt, toast, icon, ICONS} = VV;
  const HOURS = {nfl: 3.75, ncaaf: 4, nba: 2.75, mlb: 4, nhl: 3, wnba: 2.5, nwsl: 2.25};
  const ICON = {nfl: '🏈 ', ncaaf: '🏈 ', nba: '🏀 ', mlb: '⚾ ', nhl: '🏒 ', wnba: '🏀 ', nwsl: '⚽ '};
  const LEAGUE_NAMES = {nfl: 'NFL', ncaaf: 'College Football (Power 5)', mlb: 'MLB', nba: 'NBA', nhl: 'NHL', wnba: 'WNBA', nwsl: 'NWSL'};
  const LIVE = ['in', 'live'], FINAL = ['post', 'final'];
  let label = target => VV.label(target);
  let afterChange = async () => { VV.poke('v1/queue'); VV.poke('v1/master'); };
  const now = () => Date.now() / 1000;
  const secondsOf = value => typeof value === 'number' ? value : Date.parse(value) / 1000;
  const nextHalfHour = () => new Date(Math.ceil(Date.now() / 1800e3) * 1800e3);
  function configure(options) {
    if (options.label) label = options.label;
    if (options.refresh) { const page = options.refresh; afterChange = async () => { VV.poke('v1/queue'); VV.poke('v1/master'); await page(); }; }
  }

  /* What an item is doing now ------------------------------------------------------------ */
  function start(item) {
    if (item.game?.start) return secondsOf(item.game.start);
    return item.program?.start ?? null;
  }
  // Live sources play now; a listed program or game from its start (a game up to an hour early).
  function playable(item) {
    if (item.game) return !FINAL.includes(item.game.state) && (LIVE.includes(item.game.state) || !start(item) || start(item) - now() <= 3600);
    if (item.program?.start) return item.program.start <= now() && !(item.program.end <= now());
    return true;
  }
  const schedulable = item => item.kind === 'recording' || !(item.game && FINAL.includes(item.game.state)) && !(item.program?.end <= now());
  function defaultUntil(item) {
    if (item.game) return {kind: 'game', league: item.game.league || 'mlb', game_pk: item.game.game_pk, game_date: item.game.game_date};
    if (item.program?.id && item.program.end > now() && item.program.start <= now()) return {kind: 'program', program_id: item.program.id};
    return null;
  }
  function untilText(until, item) {
    if (!until) return item.kind === 'recording' ? 'to its end' : 'with no set end';
    if (until.kind === 'game') return 'until ' + (item.game?.title || 'the game') + ' is final';
    if (until.kind === 'program') return 'until ' + (item.program?.title || 'the program') + ' ends at ' + fmt.clock(item.program.end);
    return 'until ' + fmt.clock(until.at);
  }

  /* The three actions ------------------------------------------------------------------------ */
  async function playNow(item, until = defaultUntil(item), resume = false) {
    await api('v1/queue', {target: item.target, release_type: 'now', ...(until ? {until} : {}), ...(resume ? {resume: true} : {})});
    toast('Playing next: ' + item.title + ' ' + untilText(until, item) + '. It cuts in as soon as the source is ready.', {ok: true});
    await afterChange();
  }
  async function addToQueue(item, until = defaultUntil(item)) {
    await api('v1/queue', {target: item.target, release_type: 'after_current', ...(until ? {until} : {})});
    toast('Added to the end of Up next: ' + item.title + ', ' + untilText(until, item) + '.', {ok: true});
    await afterChange();
  }
  // Add to queue as a person asks for it: a live source says how long it plays first.
  function add(item, {done} = {}) {
    if (item.kind !== 'recording') return open(item, {action: 'queue', done});
    return addToQueue(item).then(() => done?.());
  }
  function scheduleWindow(item) {
    const from = start(item) && start(item) > now() ? new Date(start(item) * 1000) : nextHalfHour();
    const hours = item.game ? HOURS[item.game.league || 'mlb'] : 1;
    const to = item.program?.end && item.program.end > from / 1000 ? new Date(item.program.end * 1000) : new Date(from.getTime() + hours * 3600e3);
    return [from, to];
  }
  async function schedule(item, from = scheduleWindow(item)[0], to = scheduleWindow(item)[1]) {
    if (item.kind === 'recording') {
      await api('v1/queue', {target: item.target, release_type: 'at_time', run_at: from.toISOString()});
    } else if (item.game) {
      const g = item.game;
      await api('v1/programming/shows', {mode: 'game', start: from.toISOString(), end: to.toISOString(),
        game: {league: g.league || 'mlb', game_pk: g.game_pk, game_date: g.game_date},
        ...(item.target && (item.target.source_id !== 'mlb' || item.target.antenna === false) ? {target: item.target} : {}),
        backup: {source_id: 'schedule', channel_id: 'schedule'}});
    } else {
      await api('v1/programming/shows', {mode: 'program', title: (item.program?.title || item.title).slice(0, 72),
        target: item.target, start: from.toISOString(), end: to.toISOString()});
    }
    toast('Scheduled ' + item.title + ' for ' + fmt.full(from) + (item.kind === 'recording' ? '. It joins Up next then.' : '. It is on the Schedule.'), {ok: true});
    await afterChange();
  }

  /* The dialog: what Play now replaces, plays until, and scheduling for later ------------------- */
  let dialog = null, current = null, opened = 0;
  const part = selector => dialog.querySelector(selector);
  function build() {
    dialog = h('dialog', {class: 'onair-dialog', 'aria-labelledby': 'onair-title'});
    dialog.innerHTML = '<div class="head"><div class="stack tight" style="gap:4px"><span class="label onair-kicker">Put on air</span><h2 id="onair-title"></h2><p class="hint onair-sub"></p></div></div>'
      + '<div class="body"><fieldset class="onair-source" hidden><legend class="label">Source</legend><div class="onair-sources"></div></fieldset>'
      + '<fieldset class="onair-until"><legend class="label">Plays until</legend><div class="onair-choices"></div>'
      + '<p class="hint onair-checking" role="status"></p></fieldset><p class="onair-file hint"></p>'
      + '<p class="onair-note note" role="status"></p>'
      + '<div class="actions"><button type="button" data-act="now" class="take">▶ Play now</button><button type="button" data-act="queue">+ Add to queue</button><button type="button" class="quiet" data-act="cancel">Cancel</button></div>'
      + '<p class="hint onair-explain"></p>'
      + '<details class="more onair-later"><summary>Schedule for later</summary><div class="fields onair-times" style="margin-top:10px"><label class="field"><span>Starts</span><input type="datetime-local" data-time="from"></label>'
      + '<label class="field" data-end><span>Ends</span><input type="datetime-local" data-time="to"></label></div><p class="hint onair-later-note" style="margin:8px 0"></p>'
      + '<button type="button" data-act="schedule">Schedule</button></details>'
      + '<p class="onair-error note bad" role="alert"></p></div>';
    document.body.append(dialog);
    part('[data-act=cancel]').onclick = () => dialog.close();
    part('[data-act=now]').onclick = () => act('now');
    part('[data-act=queue]').onclick = () => act('queue');
    part('[data-act=schedule]').onclick = () => act('schedule');
    dialog.addEventListener('close', () => { current = null; opened++; });
  }
  function choice(value, text, detail, extra) {
    const radio = h('input', {type: 'radio', name: 'onair-until', value});
    const row = h('label', {class: 'check onair-choice'}, radio, h('span', h('strong', text), detail ? h('small', detail) : null), extra || null);
    part('.onair-choices').append(row);
    return radio;
  }
  function renderChoices(item, options) {
    part('.onair-choices').replaceChildren();
    const game = item.game || options.games?.[0], program = item.program?.end > now() && item.program.start <= now() ? item.program : options.program;
    current.game = game; current.program = program;
    if (game) choice('game', 'The game is final', [game.title, game.status || game.detail].filter(Boolean).join(' · ') + (game === item.game ? '' : ' · on this channel'));
    if (program) choice('program', program.title + ' ends', fmt.clock(program.end) + ' · from the TV guide');
    choice('open', 'No set end', 'It stays on until the schedule\'s next change or the next thing you play.');
    const at = h('input', {type: 'datetime-local', 'aria-label': 'Plays until this time', style: {maxWidth: '230px', marginLeft: 'auto'}});
    at.value = fmt.local(new Date(Math.max(Date.now() + 3600e3, nextHalfHour().getTime())));
    const time = choice('time', 'A time', null, at);
    at.addEventListener('input', () => { time.checked = true; });
    const preferred = current.picked || (game ? 'game' : program ? 'program' : 'open');
    (dialog.querySelector('input[name=onair-until][value=' + preferred + ']') || dialog.querySelector('input[name=onair-until]')).checked = true;
  }
  // A network's source: YouTube TV with the antenna taking over if it is late (auto), YouTube TV
  // only, or the antenna. A target picked from TV-Thing's guide starts on the antenna.
  function renderSources(item) {
    const box = part('.onair-sources'), picked = dialog.querySelector('input[name=onair-source]:checked')?.value;
    const n = item.kind === 'recording' ? null : VV.networkOf(item.target, item.youtube_tv);
    current.network = n;
    part('.onair-source').hidden = !n;
    box.replaceChildren();
    if (!n) return;
    const station = n.antenna.number + ' ' + n.antenna.name;
    const row = (value, text, detail) => box.append(h('label', {class: 'check onair-choice'},
      h('input', {type: 'radio', name: 'onair-source', value}), h('span', h('strong', text), h('small', detail))));
    row('auto', 'YouTube TV · ' + n.network + ', else the antenna', 'If YouTube TV is not ready when this is due, the antenna (' + station + ') goes on instead.');
    row('youtube', 'YouTube TV only', 'Waits for the Roku, however long its channel change takes (often a minute or more).');
    row('antenna', 'Antenna · ' + station, 'TV-Thing tunes in a few seconds.');
    const t = item.target, initial = t.source_id === 'tv-thing-digital' ? 'antenna' : t.antenna === false ? 'youtube' : 'auto';
    box.querySelector('input[value=' + (picked || initial) + ']').checked = true;
  }
  function chosenTarget() {
    const {item, network: n} = current, value = dialog.querySelector('input[name=onair-source]:checked')?.value;
    if (!n || !value) return item.target;
    if (value === 'antenna') return {source_id: n.antenna.source_id, channel_id: n.antenna.channel_id};
    const {antenna, ...base} = item.target.source_id === 'mlb' ? item.target : {source_id: 'youtube-tv', channel_id: n.youtube_tv};
    return value === 'youtube' ? {...base, antenna: false} : base;
  }
  function chosenUntil() {
    if (current.item.kind === 'recording') return null;
    const value = dialog.querySelector('input[name=onair-until]:checked')?.value;
    if (value === 'game') { const g = current.game; return {kind: 'game', league: g.league || 'mlb', game_pk: g.game_pk, game_date: g.game_date}; }
    if (value === 'program') return {kind: 'program', program_id: current.program.id};
    if (value === 'time') {
      const d = new Date(dialog.querySelector('.onair-choice input[type=datetime-local]').value);
      if (!Number.isFinite(d.getTime()) || d <= new Date()) throw Error('Choose a future time for it to play until.');
      return {kind: 'time', at: d.toISOString()};
    }
    return null;
  }
  function renderNote() {
    const {queue, master, item} = current, note = part('.onair-note');
    const hold = queue?.hold, paused = queue?.paused && !hold, on = master?.on_air;
    note.className = 'onair-note note' + (hold || paused ? ' warn' : '');
    note.textContent = !playable(item) ? (start(item) ? 'Starts ' + fmt.full(start(item)) + '. Schedule it below, or play its channel now from the guide.' : 'This has ended.')
      : hold ? 'Play now ends what is held on air now: ' + (hold.game?.title || label(hold.target)) + (hold.detail ? ' (' + hold.detail + ')' : '') + '.'
      : paused ? 'Up next is paused (' + (queue.pause_reason || 'paused') + '). Play now resumes it.'
      : on ? 'Play now replaces ' + label(on) + ' once the source is ready.' : 'Master is on the test card: it plays as soon as the source is ready.';
    const waiting = (queue?.items || []).filter(i => i.status === 'queued' || i.status === 'blocked');
    const fill = waiting.filter(i => i.release_type === 'after_current');
    part('.onair-explain').textContent = 'Add to queue: plays after '
      + (fill.length ? fill.length + ' waiting ' + (fill.length === 1 ? 'entry' : 'entries') + ' in Up next' : on ? label(on) + (hold ? ' (' + (hold.game && !hold.cut ? 'until its final' : 'until ' + fmt.clock(hold.until)) + ')' : '') : 'nothing: master is free, so it plays now')
      + '. Live shows in the schedule still start on time.';
    const play = part('[data-act=now]');
    play.disabled = !playable(item);
    play.textContent = paused ? '▶ Play now and resume' : '▶ Play now';
    part('[data-act=queue]').disabled = !playable(item);
  }
  async function open(item, {action = 'now', done = null} = {}) {
    if (!dialog) build();
    const token = ++opened;
    current = {item, done, picked: null, queue: null, master: null, game: null, program: null};
    part('.onair-kicker').textContent = action === 'queue' ? 'Add to queue · how long it plays' : 'Put on air';
    part('#onair-title').textContent = (item.game ? ICON[item.game.league || 'mlb'] || '' : '') + item.title;
    part('.onair-sub').textContent = item.detail || label(item.target);
    part('.onair-error').textContent = '';
    const recording = item.kind === 'recording';
    part('.onair-until').hidden = recording;
    part('.onair-file').textContent = recording ? 'Plays to the end of the file' + (item.duration ? ' (' + Math.round(item.duration / 60) + ' min)' : '') + '.' : '';
    part('.onair-file').hidden = !recording;
    renderChoices(item, {});
    part('.onair-sources').replaceChildren();
    renderSources(item);
    const [from, to] = scheduleWindow(item);
    part('[data-time=from]').value = fmt.local(from); part('[data-time=to]').value = fmt.local(to);
    part('[data-end]').hidden = recording;
    part('.onair-later-note').textContent = recording ? 'It joins Up next at that time.' : item.game ? 'Added to the Schedule as a game: it holds master until final, then the schedule follows.' : 'Added to the Schedule as a show on this channel.';
    part('.onair-later').hidden = !schedulable(item);
    part('.onair-later').open = action === 'schedule' || !playable(item);
    const main = playable(item) ? action : 'schedule';
    for (const button of dialog.querySelectorAll('[data-act]')) {
      button.disabled = false;  // A finished action leaves them disabled; renderNote decides Play and Add.
      if (button.dataset.act === 'now') continue;
      button.classList.toggle('primary', button.dataset.act === main);
    }
    part('.onair-checking').textContent = '';
    renderNote();
    dialog.showModal();
    (dialog.querySelector('[data-act=' + main + ']:not(:disabled)') || part('[data-act=cancel]')).focus();
    const needsGuide = !recording && !item.game && !(item.program?.end > now());
    if (needsGuide) part('.onair-checking').textContent = 'Checking the guide and sports schedules…';
    try {
      const query = new URLSearchParams(['source_id', 'channel_id', 'date'].filter(k => item.target?.[k] != null).map(k => [k, String(item.target[k])]));
      const [queue, master, options] = await Promise.all([api('v1/queue').catch(() => null), api('v1/master').catch(() => null),
        needsGuide ? api('v1/master/end-options?' + query).catch(() => ({})) : Promise.resolve({}), VV.networks()]);
      if (token !== opened) return;
      Object.assign(current, {queue, master});
      if (!recording) renderSources(item);
      if (needsGuide) {
        const checked = dialog.querySelector('input[name=onair-until]:checked')?.value;
        current.picked = checked === 'open' ? null : checked;
        renderChoices(item, options || {});
        part('.onair-checking').textContent = (options?.warnings || []).join(' · ');
      }
      renderNote();
    } catch (error) { if (token === opened) part('.onair-checking').textContent = error.message; }
  }
  async function act(action) {
    const {item, done} = current, error = part('.onair-error');
    error.textContent = '';
    const buttons = [...dialog.querySelectorAll('[data-act]')];
    buttons.forEach(b => { b.dataset.was = b.disabled; b.disabled = true; });
    try {
      const target = chosenTarget(), chosen = {...item, target};
      if (action === 'schedule') {
        const from = new Date(part('[data-time=from]').value), to = new Date(part('[data-time=to]').value);
        if (!Number.isFinite(from.getTime()) || from <= new Date()) throw Error('Choose a future start time.');
        if (item.kind !== 'recording' && !(to > from)) throw Error('Choose an end after the start.');
        await schedule(chosen, from, to);
      } else {
        let until = chosenUntil();
        // A listed program belongs to its own source's guide: on another source it ends at the same time.
        if (until?.kind === 'program' && target.source_id !== item.target.source_id) until = {kind: 'time', at: new Date(current.program.end * 1000).toISOString()};
        if (action === 'now') await playNow(chosen, until, !!current.queue?.paused && !current.queue?.hold);
        else await addToQueue(chosen, until);
      }
      dialog.close();
      done?.();
    } catch (e) {
      error.textContent = e.message;
      buttons.forEach(b => { b.disabled = b.dataset.was === 'true'; });
    }
  }

  /* Buttons a page puts beside a channel, program, game or recording ----------------------------- */
  function buttons(item, {compact = false} = {}) {
    const box = h('div', {class: 'actions onair-buttons'});
    const button = (text, aria, handler, cls) => {
      const b = h('button', {class: cls ? cls + ' sm' : 'sm', type: 'button', 'aria-label': aria + ' ' + item.title}, text);
      b.onclick = async () => { b.disabled = true; try { await handler(); } catch (e) { toast(e.message, {error: true}); } finally { b.disabled = false; } };
      box.append(b); return b;
    };
    if (playable(item)) {
      button(compact ? '▶ Play' : '▶ Play now', 'Play now', () => open(item, {action: 'now'}), 'take');
      button(compact ? '+ Queue' : '+ Add to queue', 'Add to queue', () => add(item));
    } else if (schedulable(item) && start(item)) {
      button('Schedule', 'Schedule', () => schedule(item), 'primary');
    }
    if (!compact || !playable(item)) {
      const more = button('', 'More options for', () => open(item, {action: playable(item) ? 'now' : 'schedule'}), 'quiet icon onair-more');
      more.append(icon(ICONS.more)); more.title = 'More: plays until, schedule for later';
    }
    return box;
  }

  /* Items from the guide and the library ---------------------------------------------------------- */
  // A channel row puts its game on air, or the channel, which plays until its current program
  // ends when the guide lists one; with a program, that listed program (to schedule).
  function guideItem(source, channel, data, program) {
    const target = {source_id: source.id, channel_id: String(channel.id), ...(['mlb', 'sunday-ticket', 'thursday-night-football'].includes(source.id) && data.date ? {date: data.date} : {})};
    const where = source.name + ' · ' + (channel.number ? channel.number + ' ' : '') + channel.name;
    if (program) return {kind: 'program', target, title: program.title, detail: where, program};
    const g = channel.game;
    if (g) {
      const pk = Number(g.game_pk ?? channel.id);
      return {kind: 'game', target, title: g.title || channel.name,
        youtube_tv: g.preferred_source?.provider === 'youtube_tv' ? g.preferred_source.channel : null,
        detail: source.id === 'mlb' ? 'MLB · ' + (g.preferred_source?.label ? 'suggested ' + g.preferred_source.label : 'automatic routing') : source.name,
        game: {league: source.id === 'mlb' ? 'mlb' : 'nfl', game_pk: pk, game_date: data.date, title: g.title || channel.name, start: g.start, state: g.state, status: g.status}};
    }
    const now = channel.now?.id && channel.now.end > Date.now() / 1000 ? channel.now : null;
    return {kind: 'channel', target, title: (channel.number ? channel.number + ' · ' : '') + channel.name, detail: source.name + (now ? ' · now: ' + now.title : ''), program: now};
  }
  const recordingItem = file => ({kind: 'recording', target: {source_id: 'library', channel_id: file.id}, title: file.title,
    detail: 'Media Library · ' + VV.mediaName(file), duration: file.duration});

  /* Sports: NFL by week, other leagues for the next ten days, with the same actions ----------------- */
  function gameItem(g) {
    const target = g.suggested_target || (g.league === 'mlb' ? {source_id: 'mlb', channel_id: String(g.game_id), date: g.game_date} : null);
    return {kind: 'game', target, title: g.title, youtube_tv: g.league === 'mlb' ? g.channels?.[0] || null : null,
      detail: target?.source_id === 'mlb' ? 'MLB · automatic routing (national channel or MLB.TV)' : target?.source_id === 'sunday-ticket' ? 'NFL Sunday Ticket'
        : target?.source_id === 'thursday-night-football' ? 'Thursday Night Football · Prime Video' : target ? label(target) : 'No channel suggested',
      game: {league: g.league, game_pk: g.game_id, game_date: g.game_date, title: g.title, start: g.start_time, state: g.state, status: g.status}};
  }
  function sports(host, {scheduled = null, customize = null} = {}) {
    const leagues = h('div', {class: 'seg', role: 'radiogroup', 'aria-label': 'League'});
    let league = VV.store.get('sportsLeague', 'nfl');
    for (const [value, name] of Object.entries(LEAGUE_NAMES)) {
      const b = h('button', {type: 'button', role: 'radio', 'aria-checked': String(value === league), 'aria-pressed': String(value === league), data: {league: value}}, ICON[value] + name);
      b.onclick = () => { league = value; VV.store.set('sportsLeague', value); leagues.querySelectorAll('button').forEach(x => { x.setAttribute('aria-pressed', String(x === b)); x.setAttribute('aria-checked', String(x === b)); }); load(); };
      leagues.append(b);
    }
    const week = h('select', {'aria-label': 'NFL week', style: {width: 'auto', minWidth: '220px', maxWidth: '100%'}}, new Option('Current week', ''));
    const weekLabel = h('label', {class: 'sports-week', style: {maxWidth: '100%', minWidth: 0}}, week);
    const reload = h('button', {type: 'button', class: 'quiet sm'}, icon(ICONS.refresh), 'Refresh');
    const list = h('div', {class: 'sports-list stack'});
    host.replaceChildren(h('div', {class: 'row sports-controls'}, leagues, weekLabel, reload), list);
    let data = null, shows = null;
    async function load() {
      const [season, number] = (week.value || '').split('/');
      weekLabel.hidden = league !== 'nfl';
      list.replaceChildren(h('p', {class: 'hint'}, 'Loading games…'));
      try {
        [data, shows] = await Promise.all([
          league !== 'nfl' ? api('v1/sports/upcoming?league=' + league + '&days=10') : api('v1/sports/week?league=nfl' + (number ? '&seasontype=' + season + '&week=' + number : '')),
          scheduled ? Promise.resolve(null) : api('v1/programming').then(p => p.settings.shows).catch(() => []), VV.networks()]);
      } catch (e) { data = null; list.replaceChildren(h('p', {class: 'hint'}, 'Could not load games: ' + e.message)); return; }
      if (league === 'nfl' && data.weeks?.length) {
        const value = data.season_type + '/' + data.week;
        if (week.options.length <= 1) week.replaceChildren(...data.weeks.map(w => new Option((w.season_type === 3 ? 'Postseason · ' : '') + w.label + (w.detail ? ' · ' + w.detail : ''), w.season_type + '/' + w.week)));
        week.value = value;
      }
      render();
    }
    function render() {
      list.replaceChildren();
      if (!data) return;
      if (!data.games.length) { list.append(h('p', {class: 'hint'}, data.league !== 'nfl' ? 'No ' + LEAGUE_NAMES[data.league] + ' games in the next 10 days.' : 'No games listed for this week.')); return; }
      const booked = new Set(((scheduled ? scheduled() : shows) || []).filter(s => s.game?.league === data.league).map(s => s.game.game_pk));
      const days = new Map();
      for (const g of data.games) {
        const day = fmt.day(g.start_time_tbd && g.game_date ? new Date(g.game_date + 'T12:00') : new Date(g.start_time));
        if (!days.has(day)) days.set(day, []);
        days.get(day).push(g);
      }
      for (const [day, games] of days) {
        const cards = h('ul', {class: 'list sports-games panel'});
        for (const g of games) {
          const item = gameItem(g), begun = Date.parse(g.start_time) / 1000;
          const over = FINAL.includes(g.state) || (!LIVE.includes(g.state) && begun + HOURS[g.league] * 3600 < now());
          const live = LIVE.includes(g.state);
          const networks = [...new Set(g.broadcasts.filter(b => g.league !== 'mlb' || b.market === 'national').map(b => b.name))].join(', ');
          const backup = VV.networkOf(item.target, item.youtube_tv)?.antenna;
          const body = h('div', {class: 'grow stack tight', style: {gap: '2px'}},
            h('div', {class: 'row', style: {gap: '8px'}}, h('time', {class: 'mono small muted', dateTime: g.start_time}, g.start_time_tbd ? 'TBD' : fmt.clock(begun)),
              h('strong', g.short_title || g.title)),
            g.series ? h('small', {class: 'muted'}, g.series + (g.series_game ? ' · Game ' + g.series_game : '') + (g.if_necessary ? ' · if necessary' : '')) : null,
            h('small', {class: 'muted'}, (networks || 'No TV listing') + ' → ' + item.detail + (backup ? ' · antenna ' + backup.number + ' ' + backup.name + ' if YouTube TV is late' : '')),
            g.note ? h('small', {class: 'muted', title: g.note}, item.target?.source_id === 'sunday-ticket' ? 'Out of market · Customize to use a local station if it airs in DC' : g.note) : null);
          const tools = h('div', {class: 'actions'});
          if (booked.has(g.game_id)) tools.append(h('span', {class: 'chip pvw'}, 'Scheduled'));
          if (over) tools.append(h('span', {class: 'chip'}, 'Final'));
          else if (!item.target) tools.append(h('span', {class: 'chip warn'}, 'No channel'));
          else {
            if (live) tools.append(h('span', {class: 'chip pgm'}, h('span', {class: 'lamp pgm'}), 'Live' + (g.status && g.status !== 'In Progress' ? ' · ' + g.status : '')));
            if (playable(item)) tools.append(buttons(item, {compact: true}));
            else if (!booked.has(g.game_id) && !g.start_time_tbd) {
              const box = buttons(item);
              if (customize) box.querySelector('.onair-more').onclick = () => customize(g);
              tools.append(box);
            }
          }
          if (customize && !over && !live && (g.start_time_tbd || !item.target)) {
            const b = h('button', {type: 'button', class: 'quiet sm', 'aria-label': 'Customize ' + g.title}, 'Customize'); b.onclick = () => customize(g); tools.append(b);
          }
          cards.append(h('li', {class: 'row' + (over ? ' done' : live ? ' live' : ''), style: over ? {opacity: '.6'} : null}, body, tools));
        }
        list.append(h('div', {class: 'sports-day stack tight'}, h('h3', {class: 'label'}, day), cards));
      }
    }
    week.onchange = load; reload.onclick = load;
    return {load, render};
  }

  /* When a held take ends: the next :30, the listed program, the game, or a time ------------------ */
  let endDialog = null;
  function nextBoundary() { const d = new Date(); d.setSeconds(0, 0); d.setMinutes(d.getMinutes() < 30 ? 30 : 60); return d; }
  async function changeEnd({target, hold, queue}) {
    if (!target) return;
    endDialog?.remove();
    const boundary = nextBoundary();
    const radio = (value, text, detail, extra) => h('label', {class: 'check'}, h('input', {type: 'radio', name: 'take-end', value}), h('span', h('strong', text), detail ? h('small', detail) : null), extra || null);
    const custom = h('input', {type: 'datetime-local', id: 'take-custom', 'aria-label': 'Custom end time', style: {maxWidth: '230px', marginLeft: 'auto'}});
    const gameSelect = h('select', {id: 'take-game', 'aria-label': 'Game', style: {maxWidth: '260px', marginLeft: 'auto'}});
    const choices = h('div', {class: 'stack tight'},
      radio('boundary', (boundary.getMinutes() === 30 ? ':30' : 'Top of the hour') + ' · ' + fmt.clock(boundary)));
    const programRow = radio('program', 'When the listed program ends', 'End time from the TV guide listing'); programRow.hidden = true;
    const gameRow = radio('game', 'The game ends', 'Follows the live game status, including overtime.', gameSelect); gameRow.hidden = true;
    choices.append(programRow, gameRow, radio('custom', 'A custom end time', null, custom));
    const checking = h('p', {class: 'hint', role: 'status'}, 'Checking the guide and sports schedules…');
    const error = h('p', {class: 'note bad', role: 'alert'});
    const save = h('button', {class: 'primary', type: 'button', id: 'take-confirm'}, 'Save end time');
    const cancel = h('button', {class: 'quiet', type: 'button'}, 'Cancel');
    endDialog = h('dialog', {id: 'take-dialog', 'aria-labelledby': 'take-title'}, h('div', {class: 'head'}, h('h2', {id: 'take-title'}, hold ? 'Change end time' : 'Set end time')),
      h('div', {class: 'body'}, h('p', label(target)), h('fieldset', {class: 'take-ends'}, h('legend', {class: 'label'}, 'On air until'), choices, checking),
        h('p', {class: 'hint'}, 'Up next waits until then. Afterwards ' + (queue?.schedule_enabled ? 'master goes back to the schedule.' : 'master goes to the OFF AIR test card (the schedule is off).')), error),
      h('div', {class: 'foot'}, cancel, save));
    document.body.append(endDialog);
    const pick = value => { const r = endDialog.querySelector('input[name=take-end][value=' + value + ']'); if (r) r.checked = true; };
    let touched = false, games = [], program = null;
    endDialog.querySelectorAll('input[name=take-end]').forEach(r => r.addEventListener('click', () => { touched = true; }));
    custom.oninput = () => { touched = true; pick('custom'); };
    gameSelect.onchange = () => { touched = true; pick('game'); };
    pick('boundary');
    cancel.onclick = () => endDialog.close();
    endDialog.addEventListener('close', () => endDialog?.remove());
    save.onclick = async () => {
      let until;
      try {
        const value = endDialog.querySelector('input[name=take-end]:checked')?.value;
        if (value === 'game') { const g = games[Number(gameSelect.value) || 0]; if (!g) throw Error('No game to follow on this source.'); until = {kind: 'game', league: g.league, game_pk: g.game_pk, game_date: g.game_date}; }
        else if (value === 'program') { if (!program) throw Error('No program listing for this source.'); until = {kind: 'program', program_id: program.id}; }
        else if (value === 'custom') { const d = new Date(custom.value); if (!Number.isFinite(d.getTime()) || d <= new Date()) throw Error('Choose a future date and time.'); until = {kind: 'time', at: d.toISOString()}; }
        else until = {kind: 'time', at: nextBoundary().toISOString()};
        save.disabled = true;
        await api('v1/master/hold', {until});
        endDialog.close(); toast('End time saved.', {ok: true}); await afterChange();
      } catch (e) { error.textContent = e.message; save.disabled = false; }
    };
    endDialog.showModal();
    try {
      const query = new URLSearchParams(['source_id', 'channel_id', 'date'].filter(k => target?.[k] != null).map(k => [k, String(target[k])]));
      const options = await api('v1/master/end-options?' + query);
      if (!endDialog?.open) return;
      games = options.games || []; program = options.program && options.program.end > now() ? options.program : null;
      if (program) { programRow.hidden = false; programRow.querySelector('strong').textContent = 'When ' + program.title + ' ends · ' + fmt.clock(program.end); }
      if (games.length) {
        gameRow.hidden = false;
        games.forEach((g, i) => gameSelect.append(new Option(g.title + (g.status ? ' · ' + g.status : ''), String(i))));
        gameSelect.hidden = games.length < 2;
        if (games.length < 2) gameRow.querySelector('small').textContent = games[0].title + (games[0].status ? ' · ' + games[0].status : '');
      }
      if (!touched) pick(games.length ? 'game' : program ? 'program' : 'boundary');
      checking.textContent = (options.warnings || []).join(' · ');
    } catch (e) { checking.textContent = 'Could not check the guide or games: ' + e.message; }
  }

  return {configure, open, buttons, playNow, addToQueue, add, schedule, sports, gameItem, guideItem, recordingItem, defaultUntil, playable, changeEnd,
    ICON, HOURS, LEAGUE_NAMES};
})();
