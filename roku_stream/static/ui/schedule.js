// Schedule: the weekly grid, shows and games, the sports feeds, and what will air.
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], CELLS = 48, OFF = {source_id: 'off-air', channel_id: 'off-air'};
  const COLORS = ['#3a6f8f', '#7a4f9a', '#2f7d5b', '#a0582f', '#8f3a4f', '#5a6f2f', '#2f5f9a', '#9a8a2f'];
  const LEAGUE_HOURS = OnAir.HOURS, LEAGUE_ICON = OnAir.ICON;
  let data = null, draft = null, sources = [], channels = new Map(), brush = null, painting = false, editing = null, queue = null, playback = null;
  const say = (text, error) => toast(text, {error, ok: !error});
  const post = (path, body) => api(path, body);
  const pad = n => String(n).padStart(2, '0');
  const hm = d => d.getHours() + ':' + pad(d.getMinutes());
  const cellTime = i => Math.floor(i / 2) + ':' + (i % 2 ? '30' : '00');
  const day = d => d.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
  // The grid is in the schedule's time zone: weekday (Mon 0), date and minute of the day there.
  function zoned(d) {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone: data?.timezone || undefined, weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23'}).formatToParts(d).map(x => [x.type, x.value]));
    return {day: NAMES.indexOf(p.weekday), date: p.year + '-' + pad(p.month) + '-' + pad(p.day), month: +p.month, dom: +p.day, minutes: (+p.hour % 24) * 60 + +p.minute};
  }
  // Seven days from today (from local noon, so a clock change never repeats or skips a date), and their end.
  function week() { const now = Date.now(), noon = now + (720 - zoned(new Date(now)).minutes) * 6e4; return DAYS.map((_, i) => zoned(new Date(noon + i * 864e5))); }
  function weekEnd() { const now = new Date(), p = zoned(now); return new Date(now.getTime() + (7 * 1440 - p.minutes) * 6e4); }

  /* Targets ------------------------------------------------------------------------------------------- */
  async function channelsFor(source) {
    if (!channels.has(source)) channels.set(source, api('v1/sources/' + encodeURIComponent(source) + '/programs').then(r => r.channels || []).catch(() => []));
    return channels.get(source);
  }
  function targetLabel(t) {
    if (!t || t.source_id === 'off-air') return 'OFF AIR · test card';
    if (t.source_id === 'schedule') return 'the weekly grid';
    const s = sources.find(x => x.id === t.source_id);
    return (s?.name || t.source_id) + ' · ' + (t.label || t.channel_id) + (t.antenna === false ? ' · YouTube TV only' : '');
  }
  async function label(t) {
    if (!t || t.source_id === 'off-air' || t.source_id === 'mlb') return t;
    const list = await channelsFor(t.source_id), c = list.find(c => String(c.id) === String(t.channel_id));
    return {...t, label: c ? (c.number ? c.number + ' ' : '') + c.name : t.channel_id};
  }
  function targetPicker(host, initial, auto, ticket, schedule, prime, espn) {
    const ss = h('select', {'aria-label': 'Source'}), cs = h('select', {'aria-label': 'Channel'});
    const sl = h('label', {class: 'field'}, h('span', 'Source'), ss), cl = h('label', {class: 'field'}, h('span', 'Channel'), cs);
    // NBC, FOX, ABC, CBS and The CW are also on the antenna (TV-Thing), which tunes in seconds.
    const late = h('select', {'aria-label': 'If YouTube TV is late'}, new Option('The antenna goes on', 'antenna'), new Option('Wait for YouTube TV', 'wait'));
    const ll = h('label', {class: 'field', hidden: true}, h('span', 'If YouTube TV is late'), late);
    late.value = initial?.antenna === false ? 'wait' : 'antenna';
    function showLate() {
      const n = ss.value === 'youtube-tv' ? VV.networkOf({source_id: 'youtube-tv', channel_id: cs.value}) : null;
      ll.hidden = !n && ss.value !== 'auto';
      late.options[0].text = n ? 'Antenna ' + n.antenna.number + ' ' + n.antenna.name + ' goes on' : 'The antenna goes on (NBC, FOX, ABC, CBS, The CW)';
    }
    cs.onchange = showLate;
    VV.networks().then(showLate);
    host.antenna = () => ll.hidden || late.value !== 'wait';
    host.replaceChildren(h('div', {class: 'fields'}, sl, cl, ll));
    if (schedule) ss.append(new Option('Return to schedule · the weekly grid', 'schedule'));
    if (auto) ss.append(new Option('Automatic · MLB national channel or MLB.TV', 'auto')); else ss.append(new Option('OFF AIR · test card', 'off-air'));
    if (ticket) ss.append(new Option('NFL Sunday Ticket · this game (read from the guide)', 'sunday-ticket'));
    if (prime) ss.append(new Option('Thursday Night Football · this game on Prime Video', 'thursday-night-football'));
    if (espn) ss.append(new Option('NHL on ESPN Unlimited · this game in YouTube TV', 'nhl'));
    for (const s of sources.filter(s => !['mlb', 'sunday-ticket', 'thursday-night-football', 'nhl'].includes(s.id) && s.configured)) ss.append(new Option(s.name, s.id));
    async function fill(selected) {
      cs.replaceChildren(); cl.hidden = ['off-air', 'auto', 'sunday-ticket', 'thursday-night-football', 'nhl', 'schedule'].includes(ss.value); host.dispatchEvent(new Event('change'));
      showLate();
      if (cl.hidden) return;
      cs.append(new Option('Loading…', ''));
      const list = await channelsFor(ss.value);
      cs.replaceChildren(...list.map(c => new Option((c.number ? c.number + ' ' : '') + c.name, c.id)));
      if (!list.length) cs.append(new Option('No channels listed', ''));
      if (selected != null) cs.value = String(selected);
      showLate();
    }
    host.source = () => ss.value;
    ss.onchange = () => fill();
    ss.value = initial?.source_id === 'thursday-night-football' && prime ? 'thursday-night-football' : initial?.source_id === 'sunday-ticket' && ticket ? 'sunday-ticket'
      : initial?.source_id === 'nhl' && espn ? 'nhl'
      : initial?.source_id === 'schedule' && schedule ? 'schedule' : initial && sources.some(s => s.id === initial.source_id) ? initial.source_id : schedule ? 'schedule' : auto ? 'auto' : 'off-air';
    fill(initial?.channel_id);
    host.value = () => {
      if (ss.value === 'auto') return null;
      if (ss.value === 'schedule') return {source_id: 'schedule', channel_id: 'schedule'};
      if (ss.value === 'sunday-ticket') return {...ticket};
      if (ss.value === 'thursday-night-football') return {...prime};
      if (ss.value === 'nhl') return {...espn};
      if (ss.value === 'off-air') return {...OFF};
      if (!cs.value) throw Error('Choose a channel');
      return {source_id: ss.value, channel_id: cs.value, ...(ss.value === 'youtube-tv' && !host.antenna() ? {antenna: false} : {})};
    };
  }

  /* Blocks and grid ---------------------------------------------------------------------------------------- */
  const blockOf = id => draft.blocks.find(b => b.id === id);
  const dirty = () => JSON.stringify({e: draft.enabled, b: draft.blocks, g: draft.grid}) !== JSON.stringify({e: data.settings.enabled, b: data.settings.blocks, g: data.settings.grid});
  function markDirty() {
    const d = dirty();
    $('dirty').textContent = d ? 'Unsaved changes. Save to update the queue.' : 'No unsaved changes.';
    $('dirty').style.color = d ? 'var(--warn)' : '';
    $('save').disabled = !d; $('revert').disabled = !d;
  }
  function renderBlocks() {
    const list = $('blocks'); list.replaceChildren();
    const add = (id, name, detail, color) => {
      const sw = h('span', {class: 'swatch' + (id ? '' : ' off'), style: color ? {background: color} : null});
      const b = h('button', {class: 'brush', type: 'button', 'aria-pressed': String(brush === id)}, sw, h('span', h('strong', name), h('small', detail)));
      b.onclick = () => { brush = id; renderBlocks(); };
      const li = h('li', b);
      if (id) { const e = h('button', {class: 'quiet sm', type: 'button', 'aria-label': 'Edit ' + name}, 'Edit'); e.onclick = () => openBlock(id); li.append(e); }
      list.append(li);
    };
    add(null, 'OFF AIR', 'Test card · erases', null);
    for (const b of draft.blocks) add(b.id, b.name, targetLabel(b.target), b.color);
  }
  function renderGrid() {
    // Columns run from today; each paints its weekday, which repeats every week.
    const table = $('grid'); table.replaceChildren();
    const head = h('tr', h('th', {class: 'time'}, '')), here = zoned(new Date()), nowCell = Math.floor(here.minutes / 30), dates = week();
    dates.forEach((date, col) => head.append(h('th', {class: col ? '' : 'today', scope: 'col'}, (col ? NAMES[date.day] : 'Today') + ' ' + date.month + '/' + date.dom)));
    table.append(h('thead', head));
    const body = h('tbody');
    for (let i = 0; i < CELLS; i++) {
      const tr = h('tr', {class: i % 2 ? '' : 'hour'}, h('td', {class: 'time'}, i % 2 ? '' : cellTime(i)));
      dates.forEach((date, col) => {
        const d = DAYS[date.day], blockId = draft.grid[d][i], b = blockOf(blockId);
        const td = h('td', {class: 'cell' + (b ? '' : ' off'), data: {day: d, cell: i}});
        if (b) { td.style.background = b.color; if (i === 0 || draft.grid[d][i - 1] !== blockId) { td.textContent = b.name; td.classList.add('run'); } }
        if (col === 0 && i === nowCell) td.classList.add('now');
        if (col === 0 && i < nowCell) td.classList.add('past');
        td.title = NAMES[date.day] + ' ' + cellTime(i) + ' · ' + (b ? b.name + ' · ' + targetLabel(b.target) : 'OFF AIR');
        tr.append(td);
      });
      body.append(tr);
    }
    table.append(body); renderAirs();
  }
  /* What will air, drawn over the painted grid ------------------------------------------------------------- */
  const KIND_CLASS = {game: 'game', show: 'show', recording: 'recording', manual: 'manual', off_air: 'off_air'};
  function score(s) { const g = s.game; if (!g) return ''; if (queue?.hold?.game?.game_pk === g.game_pk && queue.hold.detail) return queue.hold.detail; return queue?.games?.[(g.league || 'mlb') + ':' + g.game_pk]?.summary || ''; }
  const airTitle = s => s.title || targetLabel(s.target);
  const offAir = s => s.kind === 'off_air' || s.target?.source_id === 'off-air';
  // A block's own target carries its channel's name.
  const named = t => draft?.blocks.find(b => b.target.source_id === t?.source_id && String(b.target.channel_id) === String(t?.channel_id))?.target || t;
  const routed = t => t?.source_id === 'mlb' ? 'automatic routing' + (t.antenna === false ? ' · YouTube TV only' : '') : t?.source_id === 'sunday-ticket' ? 'NFL Sunday Ticket' : t?.source_id === 'thursday-night-football' ? 'Prime Video' : t?.source_id === 'nhl' ? 'ESPN Unlimited' : targetLabel(t);
  function airDetail(s) {
    const cut = (s.notes || []).some(n => n.startsWith('Cut when'));
    const parts = s.kind === 'game' ? [(s.game?.league || 'mlb').toUpperCase() + ' · ' + routed(s.target), score(s), cut ? '' : 'until its final' + (s.estimated ? ' (estimated)' : '')]
      : s.kind === 'recording' ? ['Recording from Up next'] : s.kind === 'manual' ? ['Queued in Up next · ' + targetLabel(named(s.target))] : offAir(s) ? ['Test card'] : s.kind === 'ident' ? ['Station ID']
      : [targetLabel(named(s.target)) + (s.kind === 'show' ? ' · scheduled show' : '')];
    return [...parts, ...(s.notes || [])].filter(Boolean).join(' · ');
  }
  // Drawn: games, shows, recordings, entries queued by hand, and anything not airing as painted.
  function drawn(s) {
    if (['game', 'show', 'recording', 'manual'].includes(s.kind)) return true;
    if (s.kind === 'ident') return false;
    if (s.notes?.length) return true;
    const p = zoned(new Date(s.start)), b = blockOf(draft.grid[DAYS[p.day]][Math.floor(p.minutes / 30)]);
    return offAir(s) ? !!b : !b || b.name !== s.title;
  }
  function renderAirs() {
    const layer = $('airs'), body = $('grid').tBodies[0]; layer.replaceChildren(); layer.hidden = !$('show-airs').checked;
    if (!playback || !body || layer.hidden) return;
    const dates = week().map(d => d.date);
    const place = (col, from, to, node) => {
      const a = body.rows[Math.floor(from / 30)]?.cells[col + 1], b = body.rows[Math.min(CELLS - 1, Math.floor((to - 1) / 30))]?.cells[col + 1];
      if (!a || !b) return;
      const top = a.offsetTop + (from % 30) / 30 * a.offsetHeight, bottom = b.offsetTop + ((to - 1) % 30 + 1) / 30 * b.offsetHeight;
      node.style.top = top + 'px'; node.style.left = (a.offsetLeft + 2) + 'px'; node.style.width = (a.offsetWidth - 4) + 'px';
      if (node.className !== 'airs-now') node.style.height = Math.max(bottom - top, 12) + 'px';
      layer.append(node);
    };
    for (const s of playback.segments) {
      if (!drawn(s)) continue;
      const a = zoned(new Date(s.start)), b = zoned(new Date(s.end)), first = dates.indexOf(a.date), endCol = dates.indexOf(b.date);
      if (first < 0) continue;
      const last = endCol < 0 ? 6 : endCol, lastTo = endCol < 0 ? 1440 : b.minutes;
      for (let c = first; c <= last; c++) {
        const from = c === first ? a.minutes : 0, to = c === last ? lastTo : 1440;
        if (to <= from) continue;
        const chip = h('div', {class: 'chipx ' + (offAir(s) ? 'off_air' : KIND_CLASS[s.kind] || '') + (s.estimated ? ' estimated' : '') + (s.notes?.includes('Joins in progress') ? ' late' : '')},
          h('strong', (s.kind === 'game' ? LEAGUE_ICON[s.game?.league || 'mlb'] || '' : '') + airTitle(s)),
          c === first ? h('small', hm(new Date(s.start)) + '–' + (s.estimated ? '~' : '') + hm(new Date(s.end)) + (airDetail(s) ? ' · ' + airDetail(s) : '')) : null);
        place(c, from, to, chip);
      }
    }
    const now = zoned(new Date()), col = dates.indexOf(now.date);
    if (col >= 0) place(col, now.minutes, now.minutes + 1, h('div', {class: 'airs-now'}));
  }
  $('show-airs').onchange = renderAirs;
  new ResizeObserver(() => renderAirs()).observe($('grid-wrap'));
  function paint(td) {
    if (!td?.dataset?.day) return;
    const d = td.dataset.day, i = +td.dataset.cell;
    if (draft.grid[d][i] === brush) return;
    draft.grid[d][i] = brush; renderGrid(); markDirty();
  }
  $('grid').addEventListener('pointerdown', e => { if (e.button !== 0) return; painting = true; paint(e.target.closest('td')); e.preventDefault(); });
  window.addEventListener('pointermove', e => { if (painting) paint(document.elementFromPoint(e.clientX, e.clientY)?.closest('td.cell')); });
  window.addEventListener('pointerup', () => { painting = false; }); window.addEventListener('pointercancel', () => { painting = false; });

  function openBlock(id) {
    editing = id; const b = id ? blockOf(id) : null;
    $('block-dialog-title').textContent = b ? 'Edit block' : 'New block';
    $('block-name').value = b?.name || ''; $('block-color').value = b?.color || COLORS[draft.blocks.length % COLORS.length];
    $('block-delete').hidden = !b; targetPicker($('block-target'), b?.target); $('block-dialog').showModal();
  }
  $('new-block').onclick = () => openBlock(null); $('block-cancel').onclick = () => $('block-dialog').close();
  $('block-form').onsubmit = async e => {
    e.preventDefault();
    try {
      const target = await label($('block-target').value()), name = $('block-name').value.trim();
      if (!name) throw Error('Name the block');
      if (editing) Object.assign(blockOf(editing), {name, color: $('block-color').value, target});
      else { const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 10); draft.blocks.push({id, name, color: $('block-color').value, target}); brush = id; }
      $('block-dialog').close(); renderBlocks(); renderGrid(); markDirty();
    } catch (err) { say(err.message, true); }
  };
  $('block-delete').onclick = async () => {
    if (!await VV.confirm('Delete this block? Its cells become OFF AIR.', {title: 'Delete block', ok: 'Delete', danger: true})) return;
    draft.blocks = draft.blocks.filter(b => b.id !== editing);
    for (const d of DAYS) draft.grid[d] = draft.grid[d].map(c => c === editing ? null : c);
    if (brush === editing) brush = null;
    $('block-dialog').close(); renderBlocks(); renderGrid(); markDirty();
  };
  async function save(enabled = draft.enabled, grid = true) {
    const settings = grid ? draft : data.settings;
    const body = {enabled, blocks: settings.blocks.map(({id, name, color, target}) => ({id, name, color, target: {source_id: target.source_id, channel_id: target.channel_id, ...(target.date ? {date: target.date} : {}), ...(target.antenna === false ? {antenna: false} : {})}})), grid: settings.grid};
    data = await post('v1/programming', body); await adopt(!grid);
  }
  $('save').onclick = async () => { $('save').disabled = true; try { await save(); say('Schedule saved. Upcoming changes are queued in Up next.'); } catch (e) { say(e.message, true); markDirty(); } };
  $('revert').onclick = () => { draft = structuredClone(data.settings); renderAll(); say('Changes discarded.'); };
  // The switch saves only itself: unsaved grid edits stay unsaved.
  $('enabled').onchange = async () => {
    const on = $('enabled').checked;
    try { await save(on, false); say(on ? 'Schedule running. Upcoming changes will be queued.' : 'Schedule stopped. Its waiting entries were withdrawn from the queue.'); }
    catch (e) { say(e.message, true); $('enabled').checked = !on; }
  };

  /* Shows ------------------------------------------------------------------------------------------------------ */
  const mode = () => document.querySelector('[name=mode]:checked').value;
  function modeChanged() { $('program-fields').hidden = mode() !== 'program'; $('game-fields').hidden = mode() !== 'game'; $('add-show').textContent = mode() === 'game' ? 'Add game' : 'Add show'; }
  document.querySelectorAll('[name=mode]').forEach(r => { r.onchange = modeChanged; });
  let games = [];
  function gamePicker() {
    const g = games.find(g => String(g.game_id) === $('game').value);
    targetPicker($('game-target'), g?.suggested_target, $('league').value === 'mlb', g?.sunday_ticket_target, false, g?.prime_video_target, g?.espn_unlimited_target);
    $('game-note').textContent = g ? [g.broadcasts.length ? 'On ' + [...new Set(g.broadcasts.map(b => b.name))].join(', ') : 'No TV listing', g.note].filter(Boolean).join('. ') : '';
  }
  $('league').onchange = () => { games = []; $('game').replaceChildren(new Option('Load a date first', '')); gamePicker(); };
  $('load-games').onclick = async () => {
    const sel = $('game'); sel.replaceChildren(new Option('Loading…', ''));
    try {
      const r = await api('v1/sports/games?league=' + $('league').value + '&date=' + encodeURIComponent($('game-date').value));
      games = r.games || [];
      sel.replaceChildren(new Option(games.length ? 'Choose a game' : 'No games on this date', ''), ...games.map(g => new Option(hm(new Date(g.start_time)) + ' · ' + g.title + (g.channels?.length ? ' · ' + g.channels.join('/') : ''), g.game_id)));
      gamePicker();
    } catch (e) { sel.replaceChildren(new Option('Could not load games', '')); say(e.message, true); }
  };
  $('game').onchange = () => {
    gamePicker();
    const g = games.find(g => String(g.game_id) === $('game').value); if (!g) return;
    const s = new Date(g.start_time); $('show-start').value = fmt.local(s); $('show-end').value = fmt.local(new Date(s.getTime() + LEAGUE_HOURS[g.league] * 3600e3));
  };
  $('show-form').onsubmit = async e => {
    e.preventDefault(); $('add-show').disabled = true;
    try {
      const start = new Date($('show-start').value), end = new Date($('show-end').value);
      if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) throw Error('Choose a start and window end');
      const body = {mode: mode(), start: start.toISOString(), end: end.toISOString(), priority: $('show-priority').value};
      if (body.mode === 'game') {
        const g = games.find(g => String(g.game_id) === $('game').value); if (!g) throw Error('Choose a game');
        const target = $('game-target').value(); if (target) body.target = target;
        else if (!$('game-target').antenna()) body.target = {source_id: 'mlb', channel_id: String(g.game_id), date: g.official_date || $('game-date').value, antenna: false};
        Object.assign(body, {game: {league: g.league, game_pk: g.game_id, game_date: g.official_date || $('game-date').value}, backup: $('backup-target').value(), backup_title: $('backup-title').value.trim() || 'Backup program'});
        if ($('game-title').value.trim()) body.title = $('game-title').value.trim();
      } else Object.assign(body, {title: $('show-title').value.trim(), target: $('show-target').value()});
      await post('v1/programming/shows', body); await refresh();
      say(body.mode === 'game' ? 'Game scheduled with its backup program.' : 'Show scheduled.');
    } catch (err) { say(err.message, true); } finally { $('add-show').disabled = false; }
  };
  function showSource(s) { const league = s.game?.league || 'mlb'; return s.mode === 'game' ? league.toUpperCase() + ' · ' + routed(s.target) : targetLabel(s.target); }
  function renderShows() {
    const list = $('shows'); list.replaceChildren();
    const now = Date.now(), gone = data.game_gone_minutes || 20;
    const shows = data.settings.shows.filter(s => Date.parse(s.end) > now), removed = data.settings.removed || [];
    const checked = data.games_checked_at ? Date.parse(data.games_checked_at) : null;
    $('games-checked').textContent = 'Games follow the MLB Stats API and ESPN until they start. ' + (checked ? 'Checked at ' + hm(new Date(checked)) + '.' : 'Checked every ' + (data.game_check_minutes || 10) + ' minutes.');
    $('check-minutes').textContent = data.game_check_minutes || 10; $('gone-minutes').textContent = gone;
    if (!shows.length) list.append(h('li', {class: 'hint'}, 'No scheduled shows. The weekly grid runs as painted.'));
    let last = '';
    for (const s of shows) {
      const a = new Date(s.start), b = new Date(s.end);
      if (day(a) !== last) { last = day(a); list.append(h('li', {class: 'day'}, last)); }
      const body = h('div', h('strong', (s.mode === 'game' ? LEAGUE_ICON[s.game?.league || 'mlb'] : '') + s.title), h('small', showSource(s)));
      if (s.mode === 'game' && s.backup.source_id !== 'schedule') body.append(h('small', 'Then ' + s.backup_title + ' on ' + targetLabel(s.backup) + ' after the final, until ' + hm(b)));
      if (s.added_by === 'favorites') body.append(h('small', '★ A favorite\'s game · ', h('a', {href: 'crawl#teams'}, 'rank favorites')));
      if (s.update) body.append(h('small', {class: 'note'}, s.update.text + ' · ' + hm(new Date(s.update.at))));
      if (s.missing_since) { const since = Date.parse(s.missing_since); body.append(h('small', {class: 'note'}, 'Not on the ' + (s.game?.league || 'mlb').toUpperCase() + ' schedule since ' + hm(new Date(since)) + '; removed at ' + hm(new Date(since + gone * 6e4)) + ' if it stays off')); }
      const twins = shows.filter(o => o !== s && Date.parse(o.start) === a.getTime());
      if (twins.length) body.append(h('small', {class: 'note'}, 'Starts with ' + twins.map(o => o.title).join(', ') + ': remove one'));
      const priority = s.priority || 'normal';
      const prio = h('select', {class: 'prio ' + priority, 'aria-label': 'Priority of ' + s.title, title: 'Priority: a show that outranks what is on air cuts in at its start'},
        ...['low', 'normal', 'high'].map(p => h('option', {value: p}, p[0].toUpperCase() + p.slice(1))));
      prio.value = priority;
      prio.onchange = async () => {
        try { data = await post('v1/programming/shows/' + s.id, {priority: prio.value}); await adopt(true); say(s.title + ' is ' + prio.value + ' priority.'); }
        catch (e) { prio.value = priority; say(e.message, true); }
      };
      const del = h('button', {class: 'quiet sm', type: 'button', 'aria-label': 'Remove ' + s.title}, 'Remove');
      del.onclick = async () => {
        if (!await VV.confirm('Remove "' + s.title + '" from the schedule?', {title: 'Remove show', ok: 'Remove', danger: true})) return;
        try { data = await api('v1/programming/shows/' + s.id, undefined, {method: 'DELETE'}); await adopt(true); say('Show removed.'); } catch (e) { say(e.message, true); }
      };
      list.append(h('li', {data: {show: s.id}}, h('time', {dateTime: s.start}, hm(a) + '–' + hm(b)), body, prio, del));
    }
    if (removed.length) {
      list.append(h('li', {class: 'day'}, 'Removed by the sports feeds'));
      for (const r of removed) list.append(h('li', {class: 'gone'}, h('time', day(new Date(r.start))), h('div', h('strong', (LEAGUE_ICON[r.league] || '') + r.title), h('small', r.text + ' · removed ' + hm(new Date(r.at))))));
    }
  }
  $('follow-games').onclick = async () => {
    const button = $('follow-games'); button.disabled = true;
    try { const r = await post('v1/programming/follow-games', {}); data = r; await adopt(true); say(r.changes.length ? r.changes.map(c => c.title + ': ' + c.text).join(' · ') : 'Every scheduled game matches its feed.'); }
    catch (e) { say(e.message, true); } finally { button.disabled = false; }
  };

  /* Sports, and the tabs ------------------------------------------------------------------------------------ */
  OnAir.configure({refresh: () => refresh(), label: t => targetLabel(named(t))});
  let sportsList = null;
  function tab(name) {
    document.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== name; });
  }
  document.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => tab(b.dataset.tab); });
  function customizeGame(g) {
    tab('add');
    document.querySelector('[name=mode][value=game]').checked = true; modeChanged();
    $('league').value = g.league; $('game-date').value = g.game_date; games = [{...g, official_date: g.game_date}];
    $('game').replaceChildren(new Option((g.start_time_tbd ? 'TBD' : hm(new Date(g.start_time))) + ' · ' + g.title + (g.channels?.length ? ' · ' + g.channels.join('/') : ''), g.game_id));
    $('game').value = String(g.game_id); $('game').onchange();
    if (g.start_time_tbd) { $('show-start').value = ''; $('show-end').value = ''; }
    else $('show-end').value = fmt.local(new Date(Date.parse(g.start_time) + LEAGUE_HOURS[g.league] * 3600e3));
    $('show-form').scrollIntoView({behavior: 'smooth', block: 'start'}); $('game-target').querySelector('select')?.focus({preventScroll: true});
  }
  $('backup-target').addEventListener('change', () => { $('backup-title-label').hidden = $('backup-target').source?.() === 'schedule'; });

  /* Rundown and status -------------------------------------------------------------------------------------- */
  const SWATCH = {game: 'var(--warn)', recording: 'var(--rec)', manual: 'var(--pvw)', show: 'var(--touch)'};
  function renderRundown() {
    const list = $('rundown'); list.replaceChildren(); const now = Date.now();
    $('rundown-paused').textContent = playback?.paused ? 'Up next is paused: nothing changes on master until it resumes.' : '';
    const segments = playback ? playback.segments.filter(s => Date.parse(s.start) < now + 864e5) : data.timeline;
    $('rundown-title').textContent = playback ? 'As it will air · next 24 hours' : 'Next 24 hours';
    for (const s of segments) {
      const off = offAir(s), current = Date.parse(s.start) <= now && now < Date.parse(s.end);
      const sw = h('span', {class: 'swatch' + (off ? ' off' : ''), style: {background: s.color || SWATCH[s.kind] || (off ? '' : 'var(--touch)')}});
      list.append(h('li', {class: (off ? 'off ' : '') + (current ? 'current' : '')}, h('time', {dateTime: s.start}, hm(new Date(s.start)) + '–' + (s.estimated ? '~' : '') + hm(new Date(s.end))), sw,
        h('div', h('strong', (s.kind === 'game' ? LEAGUE_ICON[s.game?.league || 'mlb'] || '' : '') + airTitle(s)), h('small', airDetail(s)))));
    }
  }
  function renderStatus() {
    $('enabled').checked = data.settings.enabled;
    const [cur, next] = playback ? playback.segments : [data.on_now, data.timeline[1]];
    $('on-now').textContent = cur ? airTitle(cur) : '—'; $('on-now-detail').textContent = cur ? airDetail(cur) + ' · until ' + (cur.estimated ? '~' : '') + hm(new Date(cur.end)) : '';
    $('next').textContent = next ? airTitle(next) : '—'; $('next-detail').textContent = next ? hm(new Date(next.start)) + ' · ' + airDetail(next) : '';
    $('take-current').disabled = !data.settings.enabled;
    VV.fill($('queue-state'), h('span', {class: 'chip ' + (data.settings.enabled ? 'pvw' : '')}, data.settings.enabled ? 'Running' : 'Stopped · nothing queued'),
      queue?.paused ? h('span', {class: 'chip warn', title: queue.pause_reason || ''}, 'Up next paused') : null);
  }
  function renderAll() { $('zone').textContent = data.timezone; $('lookahead').textContent = data.lookahead_minutes; renderBlocks(); renderGrid(); renderShows(); renderRundown(); renderStatus(); sportsList?.render(); markDirty(); }
  async function adopt(keepDraft) {
    const kept = keepDraft && draft && dirty() ? {blocks: draft.blocks, grid: draft.grid} : null;
    for (const b of data.settings.blocks) b.target = await label(b.target);
    draft = structuredClone(data.settings); if (kept) Object.assign(draft, kept); renderAll();
  }
  async function refresh() {
    data = await api('v1/programming');
    [queue, playback] = await Promise.all([api('v1/queue').catch(() => null), api('v1/playback?until=' + encodeURIComponent(weekEnd().toISOString())).catch(() => null)]);
    await adopt(true);
  }
  $('take-current').onclick = async () => {
    try { const r = await post('v1/programming/take-current', {}); say(r.items.length ? 'Queued ' + (data.on_now?.title || 'the current block') + ' to release in two seconds.' : 'The current block is already in the queue.'); }
    catch (e) { say(e.message, true); }
  };
  async function load() {
    try {
      const s = await api('v1/sources'); sources = s.sources || []; VV.known.sources = sources;
      await refresh();
      const today = new Date(); $('game-date').value = today.getFullYear() + '-' + pad(today.getMonth() + 1) + '-' + pad(today.getDate());
      const start = new Date(Math.ceil(today.getTime() / 1800e3) * 1800e3); $('show-start').value = fmt.local(start); $('show-end').value = fmt.local(new Date(start.getTime() + 3600e3));
      targetPicker($('show-target')); targetPicker($('backup-target'), null, false, null, true); gamePicker(); modeChanged();
      if (!sportsList) { sportsList = OnAir.sports($('sports-list'), {scheduled: () => data?.settings.shows || [], customize: customizeGame}); sportsList.load(); }
    } catch (e) { say(e.message, true); }
  }
  setInterval(() => { if (data && !document.hidden && !painting && !$('block-dialog').open) refresh().catch(() => {}); }, 30000);
  window.addEventListener('beforeunload', e => { if (draft && dirty()) e.preventDefault(); });
  document.addEventListener('vv:auth', load);
  VV.commands.add({id: 'schedule:save', title: 'Save the schedule grid', group: 'Schedule', when: () => draft && dirty(), run: async () => { await save(); return 'Schedule saved.'; }},
    {id: 'schedule:follow', title: 'Check the sports feeds now', group: 'Schedule', run: () => $('follow-games').click()},
    {id: 'schedule:airs', title: 'Show or hide what will air on the grid', group: 'Schedule', run: () => { $('show-airs').click(); }});
  load();
})();
