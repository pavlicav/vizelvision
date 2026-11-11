// Schedule: the week as planned (the lineup's slots, shows and games on a date) beside what will
// really air, with sports slots, clashes and ideas for what to add. Rebuilt 2026-11-09: nothing
// is painted, every change is one deliberate step, and each can be undone.
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const COLORS = ['#3a6f8f', '#7a4f9a', '#2f7d5b', '#a0582f', '#8f3a4f', '#5a6f2f', '#2f5f9a', '#9a8a2f'];
  const ZOOMS = [.55, .8, 1.1, 1.6, 2.3], LENGTHS = [15, 30, 45, 60, 90, 120, 150, 180, 240];
  const LEAGUE_HOURS = OnAir.HOURS, ICON = OnAir.ICON, OFF = {source_id: 'off-air', channel_id: 'off-air'};
  const GAME_SOURCES = ['mlb', 'sunday-ticket', 'thursday-night-football', 'nhl', 'nwsl'];
  const narrow = () => window.matchMedia('(max-width: 760px)').matches;
  let data = null, playback = null, queue = null, sportsView = null, ideas = null, sources = [], folders = null;
  const channels = new Map(), listed = new Map();
  const view = {mode: VV.store.get('scheduleView', narrow() ? 'day' : 'week'), day: 0, zoom: VV.store.get('scheduleZoom', 2), overnight: VV.store.get('scheduleOvernight', false)};
  let ghosts = [], plan = [], dragging = false, hiddenIdeas = new Set(VV.store.get('scheduleHiddenIdeas', []));
  const say = (text, error) => toast(text, {error, ok: !error});
  const pad = n => String(n).padStart(2, '0');
  const hm = d => { d = new Date(d); return (d.getHours() % 12 || 12) + ':' + pad(d.getMinutes()) + (d.getHours() < 12 ? ' AM' : ' PM'); };
  const clock = m => { m = ((m % 1440) + 1440) % 1440; const hr = Math.floor(m / 60); return (hr % 12 || 12) + ':' + pad(m % 60) + (hr < 12 ? ' AM' : ' PM'); };
  const hhmm = m => pad(Math.floor(m / 60) % 24) + ':' + pad(m % 60);
  const minutesOf = text => { const [a, b] = text.split(':').map(Number); return a * 60 + b; };
  const mins = m => m < 60 ? m + ' min' : (m % 60 ? Math.floor(m / 60) + ' h ' + m % 60 + ' min' : m / 60 + ' h');
  const dayName = d => new Date(d).toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
  const spokenDays = on => { on = DAYS.filter(d => on.includes(d)); return on.length === 7 ? 'Every day' : on.join() === DAYS.slice(0, 5).join() ? 'Weekdays' : on.join() === 'sat,sun' ? 'Weekends' : on.map(d => NAMES[DAYS.indexOf(d)]).join(', '); };
  // The week is in the schedule's time zone: weekday (Mon 0), date and minute of the day there.
  function zoned(d) {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone: data?.timezone || undefined, weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23'}).formatToParts(d).map(x => [x.type, x.value]));
    return {day: NAMES.indexOf(p.weekday), date: p.year + '-' + pad(p.month) + '-' + pad(p.day), month: +p.month, dom: +p.day, minutes: (+p.hour % 24) * 60 + +p.minute};
  }
  // Seven days from today (from local noon, so a clock change never repeats or skips a date), and their end.
  function week() { const now = Date.now(), noon = now + (720 - zoned(new Date(now)).minutes) * 6e4; return DAYS.map((_, i) => zoned(new Date(noon + i * 864e5))); }
  function weekEnd() { const now = new Date(), p = zoned(now); return new Date(now.getTime() + (7 * 1440 - p.minutes) * 6e4); }
  // The moment a date and minute of the day are, in the schedule's zone.
  function instant(date, minute) {
    const [y, m, d] = date.split('-').map(Number), want = Date.UTC(y, m - 1, d, 0, minute);
    let t = want;
    for (let i = 0; i < 3; i++) { const z = zoned(new Date(t)), [zy, zm, zd] = z.date.split('-').map(Number); t -= Date.UTC(zy, zm - 1, zd, 0, z.minutes) - want; }
    return new Date(t);
  }

  /* Naming sources --------------------------------------------------------------------------------- */
  async function channelsFor(source) {
    if (!channels.has(source)) channels.set(source, api('v1/sources/' + encodeURIComponent(source) + '/programs').then(r => { const list = r.channels || []; listed.set(source, list); return list; }).catch(() => []));
    return channels.get(source);
  }
  let renderSoon = null;
  function channelName(t) {
    if (!t) return '';
    if (t.source_id === 'off-air') return 'OFF AIR · test card';
    if (t.source_id === 'schedule') return 'the schedule';
    if (t.source_id === 'library') return 'Library · ' + String(t.channel_id).split('/').pop().replace(/\.[a-z0-9]{2,4}$/i, '');
    if (GAME_SOURCES.includes(t.source_id)) return routed(t);
    const list = listed.get(t.source_id), c = list?.find(c => String(c.id) === String(t.channel_id));
    if (!list && !channels.has(t.source_id)) channelsFor(t.source_id).then(() => { clearTimeout(renderSoon); renderSoon = setTimeout(renderAll, 50); });
    const name = c ? (c.number ? c.number + ' ' : '') + c.name : t.label || t.channel_id;
    return (t.source_id === 'youtube-tv' ? 'YouTube TV ' : t.source_id === 'internet' ? 'Stream · ' : '') + name + (t.antenna === false ? ' · YouTube TV only' : '');
  }
  const routed = t => t?.source_id === 'mlb' ? 'automatic routing' + (t.antenna === false ? ' · YouTube TV only' : '') : t?.source_id === 'sunday-ticket' ? 'NFL Sunday Ticket' : t?.source_id === 'thursday-night-football' ? 'Prime Video' : t?.source_id === 'nhl' || t?.source_id === 'nwsl' ? 'ESPN Unlimited' : channelName(t);
  function targetPicker(host, initial, {off = true, none = false, auto = false, schedule = false, ticket = null, prime = null, espn = null} = {}) {
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
    cs.onchange = () => { showLate(); host.dispatchEvent(new Event('change')); };
    VV.networks().then(showLate);
    host.antenna = () => ll.hidden || late.value !== 'wait';
    host.replaceChildren(h('div', {class: 'fields'}, sl, cl, ll));
    if (none) ss.append(new Option('Nothing · skip that airing', 'none'));
    if (schedule) ss.append(new Option('Return to the schedule', 'schedule'));
    if (auto) ss.append(new Option('Automatic · MLB national channel or MLB.TV', 'auto'));
    if (ticket) ss.append(new Option('NFL Sunday Ticket · this game (read from the guide)', 'sunday-ticket'));
    if (prime) ss.append(new Option('Thursday Night Football · this game on Prime Video', 'thursday-night-football'));
    if (espn) ss.append(new Option(espn.source_id.toUpperCase() + ' on ESPN Unlimited · this game in YouTube TV', espn.source_id));
    for (const s of sources.filter(s => !GAME_SOURCES.includes(s.id) && s.id !== 'library' && s.configured)) ss.append(new Option(s.name, s.id));
    if (off) ss.append(new Option('OFF AIR · test card', 'off-air'));
    const fixed = ['off-air', 'auto', 'none', 'schedule', ...GAME_SOURCES];
    async function fillChannels(selected) {
      cs.replaceChildren(); cl.hidden = fixed.includes(ss.value); host.dispatchEvent(new Event('change'));
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
    ss.onchange = () => fillChannels();
    const has = id => [...ss.options].some(o => o.value === id);
    ss.value = initial && has(initial.source_id) ? initial.source_id : none ? 'none' : schedule ? 'schedule' : auto ? 'auto' : ss.options[0]?.value;
    fillChannels(initial?.channel_id);
    host.value = () => {
      const v = ss.value;
      if (v === 'auto' || v === 'none') return null;
      if (v === 'schedule') return {source_id: 'schedule', channel_id: 'schedule'};
      if (v === 'sunday-ticket') return {...ticket};
      if (v === 'thursday-night-football') return {...prime};
      if (espn && v === espn.source_id) return {...espn};
      if (v === 'off-air') return {...OFF};
      if (!cs.value) throw Error('Choose a channel');
      return {source_id: v, channel_id: cs.value, ...(v === 'youtube-tv' && !host.antenna() ? {antenna: false} : {})};
    };
  }

  /* Changes, each with its undo ---------------------------------------------------------------------- */
  function done(text, undo) {
    const node = toast(text, {ok: true, timeout: undo ? 12000 : undefined});
    if (!undo || !node) return;
    const b = h('button', {class: 'quiet xs', type: 'button', style: {marginLeft: '10px'}}, 'Undo');
    b.onclick = async () => { node.remove(); try { await undo(); say('Undone.'); } catch (e) { say(e.message, true); } };
    node.append(b);
  }
  // A slot or sports change answers with the whole schedule.
  function adopt(response) { if (response?.settings) { data = response; afterChange(); } return response; }
  async function afterChange() { ideas = null; renderAll(); await Promise.all([loadPlayback(), loadSports()]); renderAll(); if (tabOpen('ideas')) loadIdeas(); }
  const clean = slot => ({title: slot.title, color: slot.color, days: slot.days, start: slot.start, minutes: slot.minutes, priority: slot.priority, enabled: slot.enabled, skip: slot.skip, what: slot.what});
  const slotOf = id => data.settings.slots.find(s => s.id === id);
  async function addSlot(body, text) {
    const r = adopt(await api('v1/programming/slots', body)), id = r.changed.id;
    done(text || r.changed.title + ' is on the lineup: ' + spokenDays(r.changed.days) + ' at ' + clock(minutesOf(r.changed.start)) + '.', () => removeSlot(id, true));
    return r.changed;
  }
  async function updateSlot(slot, changes, text) {
    const before = clean(slot);
    adopt(await api('v1/programming/slots/' + slot.id, changes));
    done(text || slot.title + ' updated.', async () => { adopt(await api('v1/programming/slots/' + slot.id, before)); });
  }
  async function removeSlot(id, quiet) {
    const r = adopt(await api('v1/programming/slots/' + id, undefined, {method: 'DELETE'})), slot = r.removed_slot;
    if (!quiet) done(slot.title + ' is off the lineup.', async () => { adopt(await api('v1/programming/slots', {...clean(slot), id: slot.id})); });
  }
  async function skipAiring(item, skip) {
    adopt(await api('v1/programming/slots/' + item.slot + '/skip', {date: item.date, skip}));
    done(skip ? item.title + ' is skipped on ' + dayName(item.start) + '.' : item.title + ' is back on ' + dayName(item.start) + '.',
      async () => { adopt(await api('v1/programming/slots/' + item.slot + '/skip', {date: item.date, skip: !skip})); });
  }
  const showBody = s => ({mode: s.mode, title: s.title, start: s.start, end: s.end, priority: s.priority || 'normal', target: s.target,
    ...(s.mode === 'game' ? {game: {league: s.game.league, game_pk: s.game.game_pk, game_date: s.game.game_date}, backup: s.backup, backup_title: s.backup_title} : {})});
  async function removeShow(show) {
    data = await api('v1/programming/shows/' + show.id, undefined, {method: 'DELETE'}); await afterChange();
    const again = Date.parse(show.end) > Date.now() ? async () => { await api('v1/programming/shows', {...showBody(show), start: new Date(Math.max(Date.parse(show.start), Date.now() + 60e3)).toISOString()}); await refresh(); } : null;
    done(show.title + ' is off the schedule.', again);
  }
  async function setPriority(show, priority) {
    const before = show.priority || 'normal';
    data = await api('v1/programming/shows/' + show.id, {priority}); await afterChange();
    done(show.title + ' is ' + priority + ' priority.', async () => { data = await api('v1/programming/shows/' + show.id, {priority: before}); await afterChange(); });
  }
  async function addShow(body, text) {
    const show = await api('v1/programming/shows', body); await refresh();
    done(text || show.title + ' is on the schedule for ' + fmt.when(show.start) + '.', async () => { data = await api('v1/programming/shows/' + show.id, undefined, {method: 'DELETE'}); await afterChange(); });
  }

  /* The plan, and what becomes of each part ------------------------------------------------------------ */
  // A schedule key is "run_at|kind|ref|target": ref is the slot or show.
  function refOf(key) { const p = (key || '').split('|'); return p.length >= 4 && ['block', 'show', 'game'].includes(p[1]) && p[2] !== 'None' ? p[2] : null; }
  function buildPlan() {
    const now = Date.now(), from = Date.parse(data.airings_from), items = [];
    const spans = new Map(), dropped = new Map();
    for (const s of playback?.segments || []) { const ref = refOf(s.key); if (ref) (spans.get(ref) || spans.set(ref, []).get(ref)).push(s); }
    for (const d of playback?.dropped || []) { const ref = refOf(d.key); if (ref) (dropped.get(ref) || dropped.set(ref, []).get(ref)).push(d); }
    const horizon = playback ? Date.parse(playback.until) : 0;
    const onAt = t => (playback?.segments || []).find(s => Date.parse(s.start) <= t && t < Date.parse(s.end));
    function outcome(item, ref) {
      const a = Date.parse(item.start), b = Date.parse(item.end);
      if (item.skipped) return {state: 'skipped', text: 'Skipped this time'};
      if (item.type === 'slot' && !item.target) return {state: 'nothing', text: item.why || 'Nothing to air'};
      if (b <= now) return {state: 'gone', text: 'Already aired'};
      if (!data.settings.enabled) return {state: 'idle', text: 'The schedule is switched off'};
      if (!playback || a >= horizon) return {state: 'plan', text: ''};
      const mine = (spans.get(ref) || []).filter(s => Date.parse(s.end) > a - 6e4 && Date.parse(s.start) < Math.max(b, a + 6e4) + (item.type === 'game' ? 12 * 3600e3 : 6e4));
      if (!mine.length) {
        const why = (dropped.get(ref) || []).find(d => !d.due || Math.abs(Date.parse(d.due) - a) < 12 * 3600e3)?.why;
        const other = onAt(Math.max(a, now) + 6e4);
        return {state: 'wont', text: why || (other ? (other.title || 'Something else') + ' is on instead' : 'Something else has the time'), other};
      }
      const first = Date.parse(mine[0].start), last = Date.parse(mine[mine.length - 1].end), notes = [...new Set(mine.flatMap(s => s.notes || []))];
      const result = {state: 'airs', text: '', from: first, to: last, estimated: mine.some(s => s.estimated), notes};
      if (first > Math.max(a, now) + 2 * 6e4) { const other = onAt(Math.max(a, now) + 6e4); Object.assign(result, {state: 'late', other, text: 'Joins at ' + hm(first) + (other ? ', after ' + (other.title || 'what is on') : '')}); }
      const cut = notes.find(n => n.startsWith('Cut when'));
      if (cut) Object.assign(result, {state: result.state === 'late' ? 'late' : 'cut', text: [result.text, cut + ' (' + hm(last) + ')'].filter(Boolean).join('. ')});
      else if (item.type !== 'game' && last < b - 2 * 6e4 && last < horizon) Object.assign(result, {state: 'cut', text: [result.text, 'Ends early at ' + hm(last)].filter(Boolean).join('. ')});
      return result;
    }
    for (const a of data.airings) {
      if (!a.enabled) continue;
      const item = {...a, type: 'slot', id: a.slot + '|' + a.date};
      item.out = outcome(item, a.slot); items.push(item);
    }
    for (const s of data.settings.shows) {
      if (Date.parse(s.end) <= from) continue;
      const item = {type: s.mode === 'game' ? 'game' : 'show', id: s.id, show: s, title: s.title, start: s.start, end: s.end, target: s.target, priority: s.priority || 'normal'};
      item.out = outcome(item, s.id);
      // A game is on until its final: draw it to where the projection has it end.
      if (item.type === 'game' && item.out.to && item.out.to > Date.parse(s.start)) item.shown_end = new Date(item.out.to).toISOString();
      items.push(item);
    }
    for (const g of ghosts) items.push(...ghostItems(g));
    return items;
  }
  function ghostItems({idea, days}) {
    const body = idea.apply.body, dates = week();
    if (idea.group === 'soon') return [{type: 'ghost', id: idea.id, idea, title: idea.title, start: body.start, end: body.end, target: body.target, out: {state: 'ghost', text: 'Suggestion'}}];
    if (!body.days || !body.start) return [];
    return dates.filter(d => (days || body.days).includes(DAYS[d.day])).map(d => {
      const start = instant(d.date, minutesOf(body.start));
      return {type: 'ghost', id: idea.id + '|' + d.date, idea, days, title: idea.title, start: start.toISOString(), end: new Date(start.getTime() + body.minutes * 6e4).toISOString(),
        target: body.what?.target, out: {state: 'ghost', text: 'Suggestion'}};
    });
  }

  /* The week -------------------------------------------------------------------------------------------- */
  function where(item) {
    if (item.type === 'game') return (item.show.game?.league || 'mlb').toUpperCase() + ' · ' + routed(item.target);
    if (item.type === 'slot' && item.kind === 'library') return item.label ? 'Library · ' + item.label : 'Library';
    if (item.type === 'slot' && item.by === 'listings') return item.label || channelName(item.target);
    return item.target ? (item.label || channelName(item.target)) : '';
  }
  function lanes(items) {
    items.sort((x, y) => x.a - y.a || (y.b - y.a) - (x.b - x.a));
    let cluster = [], end = -1;
    // What will not air (or is only suggested) takes a narrower lane than what will.
    const weight = i => ['wont', 'skipped', 'gone'].includes(i.item.out.state) ? .45 : 1;
    const flush = () => {
      const n = Math.max(...cluster.map(i => i.lane)) + 1, widths = Array.from({length: n}, (_, lane) => Math.max(...cluster.filter(i => i.lane === lane).map(weight)));
      const total = widths.reduce((a, b) => a + b, 0);
      cluster.forEach(i => { i.left = widths.slice(0, i.lane).reduce((a, b) => a + b, 0) / total; i.width = widths[i.lane] / total; });
      cluster = [];
    };
    for (const it of items) {
      if (cluster.length && it.a >= end) { flush(); end = -1; }
      const used = new Set(cluster.filter(c => c.b > it.a).map(c => c.lane));
      let lane = 0; while (used.has(lane)) lane++;
      it.lane = lane; cluster.push(it); end = Math.max(end, it.b);
    }
    if (cluster.length) flush();
    return items;
  }
  function renderWeek() {
    const cal = $('cal'), ppm = ZOOMS[view.zoom], dates = week(), now = new Date(), here = zoned(now);
    plan = buildPlan();
    const one = view.mode === 'day', shown = one ? [dates[view.day]] : dates;
    // Slices of everything, by date.
    const slices = new Map(shown.map(d => [d.date, []])), ribbons = new Map(shown.map(d => [d.date, []]));
    const cut = (startISO, endISO, add) => {
      const a = zoned(new Date(startISO)), b = zoned(new Date(new Date(endISO).getTime() - 1));
      for (const d of shown) {
        if (d.date < a.date || d.date > b.date) continue;
        const from = d.date === a.date ? a.minutes : 0, to = d.date === b.date ? b.minutes + 1 : 1440;
        if (to > from) add(d.date, from, to, d.date === a.date);
      }
    };
    for (const item of plan) cut(item.start, item.shown_end || item.end, (date, a, b, first) => slices.get(date).push({item, a, b, first}));
    for (const s of playback?.segments || []) cut(s.start, s.end, (date, a, b) => ribbons.get(date).push({s, a, b}));
    // The hours shown: all of them overnight, else from six (or the first thing before it).
    let top = view.overnight ? 0 : 360;
    if (!view.overnight) for (const list of slices.values()) for (const x of list) if (x.item.out.state !== 'gone' && x.a < top && x.first) top = Math.floor(x.a / 60) * 60;
    const height = (1440 - top) * ppm;
    cal.style.setProperty('--ppm', ppm); cal.style.setProperty('--cols', shown.length); cal.classList.toggle('one', one);
    cal.replaceChildren(h('div', {class: 'corner'}));
    for (const d of shown) {
      const count = slices.get(d.date).filter(x => x.first && !['ghost', 'skipped'].includes(x.item.out.state)).length;
      const head = h('button', {type: 'button', title: one ? 'Back to the week' : 'This day alone'}, (d.date === here.date ? 'Today' : NAMES[d.day]) + ' ' + d.month + '/' + d.dom);
      head.onclick = () => { view.day = dates.findIndex(x => x.date === d.date); setMode(one ? 'week' : 'day'); };
      cal.append(h('div', {class: 'dayhead' + (d.date === here.date ? ' today' : '')}, head, h('small', count ? count + ' on' : 'nothing on')));
    }
    const gutter = h('div', {class: 'gutter', style: {height: height + 'px', position: 'sticky'}});
    for (let m = Math.ceil(top / 60) * 60 + 60; m < 1440; m += 60) gutter.append(h('span', {style: {top: (m - top) * ppm + 'px'}}, clock(m).replace(':00', '')));
    cal.append(gutter);
    for (const d of shown) {
      const col = h('div', {class: 'col' + (d.date === here.date ? ' today' : ''), style: {height: height + 'px'}, data: {date: d.date}});
      col.style.backgroundPosition = '0 ' + (-(top % 60) * ppm) + 'px';
      if (d.date === here.date && here.minutes > top) col.append(h('div', {class: 'past', style: {height: (here.minutes - top) * ppm + 'px'}}));
      const air = h('div', {class: 'air'});
      for (const {s, a, b} of ribbons.get(d.date)) {
        if (b <= top) continue;
        const off = s.kind === 'off_air' || s.target?.source_id === 'off-air';
        air.append(h('i', {class: off ? 'off_air' : s.kind, title: hm(s.start) + '–' + (s.estimated ? '~' : '') + hm(s.end) + ' · ' + (s.title || channelName(s.target)) + (s.notes?.length ? ' · ' + s.notes.join(' · ') : ''),
          style: {top: (Math.max(a, top) - top) * ppm + 'px', height: Math.max((b - Math.max(a, top)) * ppm - 1, 2) + 'px', background: !off && s.kind === 'block' && s.color ? s.color : null}}));
      }
      col.append(air);
      for (const x of lanes(slices.get(d.date).filter(x => x.b > top))) col.append(card(x, top, ppm));
      if (d.date === here.date && here.minutes >= top) col.append(h('div', {class: 'nowline', style: {top: (here.minutes - top) * ppm + 'px'}}));
      col.onclick = e => {
        if (e.target !== col && !e.target.classList.contains('past')) return;
        const minute = Math.min(1410, Math.floor((top + (e.clientY - col.getBoundingClientRect().top) / ppm) / 30) * 30);
        addMenu(e.clientX, e.clientY, {date: d.date, day: DAYS[d.day], minute});
      };
      cal.append(col);
    }
    $('view-week').setAttribute('aria-pressed', String(!one)); $('view-day').setAttribute('aria-pressed', String(one));
    $('day-nav').hidden = !one; $('overnight').checked = view.overnight;
    $('week-title').textContent = one ? (shown[0].date === here.date ? 'Today' : NAMES[shown[0].day]) + ' ' + shown[0].month + '/' + shown[0].dom : 'The week';
    renderDraftbar();
  }
  function card({item, a, b, first, left, width}, top, ppm) {
    const from = Math.max(a, top), state = item.out.state, slot = item.type === 'slot' ? slotOf(item.slot) : null;
    const tall = (b - from) * ppm >= 44, style = {top: (from - top) * ppm + 1 + 'px', height: Math.max((b - from) * ppm - 2, 15) + 'px',
      left: 'calc(10px + (100% - 12px) * ' + left + ')', width: 'calc((100% - 12px) * ' + width + ' - 2px)'};
    const classes = ['ev', item.type, tall ? 'tall' : '', ['wont', 'nothing', 'skipped', 'gone', 'ghost'].includes(state) ? state : ''].filter(Boolean).join(' ');
    const tags = [];
    if (item.type !== 'slot' && item.priority === 'high') tags.push(h('span', {class: 'tag hi'}, 'High'));
    if (item.type !== 'slot' && item.priority === 'low') tags.push(h('span', {class: 'tag'}, 'Low'));
    if (state === 'late') tags.push(h('span', {class: 'tag warn'}, 'Joins late'));
    if (state === 'cut') tags.push(h('span', {class: 'tag warn'}, 'Cut short'));
    if (state === 'wont') tags.push(h('span', {class: 'tag warn'}, "Won't air"));
    if (state === 'nothing') tags.push(h('span', {class: 'tag warn'}, 'Not listed'));
    if (item.listed?.new) tags.push(h('span', {class: 'tag'}, 'New'));
    const title = (item.type === 'game' ? ICON[item.show.game?.league || 'mlb'] || '' : state === 'ghost' ? '+ ' : '') + item.title;
    const time = first ? hm(item.start) + '–' + (item.out.estimated ? '~' : '') + hm(item.shown_end || item.end) : 'from ' + dayName(item.start);
    const node = h('button', {type: 'button', class: classes, style, title: title + ' · ' + hm(item.start) + '–' + hm(item.end) + (where(item) ? ' · ' + where(item) : '') + (item.out.text ? ' · ' + item.out.text : '')},
      h('strong', tags, title), h('small', [time, state === 'skipped' ? 'skipped' : where(item)].filter(Boolean).join(' · ')));
    if (item.color && item.type === 'slot') node.style.setProperty('--c', item.color);
    node.onclick = e => { e.stopPropagation(); if (node.dataset.dragged) { delete node.dataset.dragged; return; } openInfo(item); };
    if (slot && first && !['skipped', 'gone'].includes(state)) {
      const grip = h('span', {class: 'grip'});
      node.append(grip);
      node.addEventListener('pointerdown', e => drag(e, item, slot, node, e.target === grip ? 'size' : 'move', ppm));
    }
    return node;
  }
  // Dragging is for a mouse only: a finger scrolls, and taps open things.
  function drag(e, item, slot, node, mode, ppm) {
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    const y0 = e.clientY, base = minutesOf(slot.start), h0 = node.offsetHeight, tip = h('div', {class: 'dragtip'});
    let moved = false, delta = 0;
    const move = ev => {
      const dy = ev.clientY - y0;
      if (!moved && Math.abs(dy) < 5) return;
      if (!moved) { moved = dragging = true; node.classList.add('dragging'); document.body.append(tip); }
      delta = Math.round(dy / ppm / 5) * 5;
      if (mode === 'move') { delta = Math.max(-base, Math.min(1435 - base, delta)); node.style.transform = 'translateY(' + delta * ppm + 'px)'; tip.textContent = clock(base + delta) + ' – ' + clock(base + delta + slot.minutes); }
      else { delta = Math.max(5 - slot.minutes, Math.min(1440 - slot.minutes, delta)); node.style.height = h0 + delta * ppm + 'px'; tip.textContent = mins(slot.minutes + delta) + ' · ends ' + clock(base + slot.minutes + delta); }
      tip.style.left = ev.clientX + 14 + 'px'; tip.style.top = ev.clientY + 10 + 'px';
    };
    const up = async () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); tip.remove();
      if (!moved) return;
      node.dataset.dragged = '1'; dragging = false;
      if (!delta) { renderWeek(); return; }
      const all = slot.days.length > 1 ? ' on ' + spokenDays(slot.days).toLowerCase() : '';
      try {
        if (mode === 'move') await updateSlot(slot, {start: hhmm(base + delta)}, slot.title + ' now starts at ' + clock(base + delta) + all + '.');
        else await updateSlot(slot, {minutes: slot.minutes + delta}, slot.title + ' now runs ' + mins(slot.minutes + delta) + all + '.');
      } catch (err) { say(err.message, true); renderWeek(); }
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  }
  function setMode(mode) { view.mode = mode; VV.store.set('scheduleView', mode); renderWeek(); }
  $('view-week').onclick = () => setMode('week'); $('view-day').onclick = () => setMode('day');
  $('day-prev').onclick = () => { view.day = (view.day + 6) % 7; renderWeek(); }; $('day-next').onclick = () => { view.day = (view.day + 1) % 7; renderWeek(); };
  $('zoom-in').onclick = () => { view.zoom = Math.min(ZOOMS.length - 1, view.zoom + 1); VV.store.set('scheduleZoom', view.zoom); renderWeek(); };
  $('zoom-out').onclick = () => { view.zoom = Math.max(0, view.zoom - 1); VV.store.set('scheduleZoom', view.zoom); renderWeek(); };
  $('overnight').onchange = () => { view.overnight = $('overnight').checked; VV.store.set('scheduleOvernight', view.overnight); renderWeek(); };

  /* Adding: the menu, then one of the dialogs --------------------------------------------------------- */
  let menu = null;
  function closeMenu() { menu?.remove(); menu = null; }
  function addMenu(x, y, at) {
    closeMenu();
    const when = at ? NAMES[DAYS.indexOf(at.day)] + ' ' + clock(at.minute) : null;
    const option = (title, detail, run) => { const b = h('button', {type: 'button'}, h('span', h('strong', title), h('small', detail))); b.onclick = () => { closeMenu(); run(); }; return b; };
    menu = h('div', {class: 'addmenu', role: 'menu', style: {position: 'fixed'}}, h('span', {class: 'label'}, when ? 'Add at ' + when : 'Add to the schedule'),
      option('A programme', 'By name: the channel follows the listings', () => openSlot(null, {kind: 'program', ...at})),
      option('A channel', 'Whatever is on it then', () => openSlot(null, {kind: 'channel', ...at})),
      option('From the library', 'The next episode, the newest recording, or one at random', () => openSlot(null, {kind: 'library', ...at})),
      option('A sports slot', 'Monday Night Football and the like, every week', () => openSports(null, at ? {days: [at.day]} : null)),
      option('One game', 'Pick a game and its channel', () => openGame(at)));
    document.body.append(menu);
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + 'px'; menu.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + 'px';
    menu.querySelector('button').focus({preventScroll: true});
  }
  document.addEventListener('pointerdown', e => { if (menu && !menu.contains(e.target)) closeMenu(); }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
  $('cal-wrap').addEventListener('scroll', closeMenu, {passive: true});
  $('add').onclick = e => { const r = e.currentTarget.getBoundingClientRect(); addMenu(r.left, r.bottom + 6, null); };

  /* The slot dialog ----------------------------------------------------------------------------------- */
  const form = {editing: null, kind: 'program', days: new Set(), color: COLORS[0], repeat: 'weekly', picked: null, named: false};
  function chips(host, set, changed) {
    host.replaceChildren(...DAYS.map((d, i) => { const b = h('button', {type: 'button', 'aria-pressed': String(set.has(d))}, NAMES[i]); b.onclick = () => { set.has(d) ? set.delete(d) : set.add(d); b.setAttribute('aria-pressed', String(set.has(d))); changed?.(); }; return b; }));
  }
  function setKind(kind) {
    form.kind = kind;
    document.querySelectorAll('#slot-kinds button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.kind === kind)));
    document.querySelectorAll('[data-kind-panel]').forEach(p => { p.hidden = p.dataset.kindPanel !== kind; });
    const once = $('slot-repeat').querySelector('[data-repeat=once]');
    once.disabled = kind === 'library'; if (kind === 'library' && form.repeat === 'once') setRepeat('weekly');
    if (kind === 'library') loadFolders();
    slotChanged();
  }
  function setRepeat(repeat) {
    form.repeat = repeat;
    document.querySelectorAll('#slot-repeat button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.repeat === repeat)));
    $('weekly-fields').hidden = repeat !== 'weekly'; $('once-fields').hidden = repeat !== 'once';
    slotChanged();
  }
  function setMinutes(value) {
    const sel = $('slot-minutes'); sel.replaceChildren(...[...new Set([...LENGTHS, value])].sort((a, b) => a - b).map(m => new Option(mins(m), m)));
    sel.value = String(value);
  }
  function slotChanged() {
    const start = $('slot-start').value, minutes = +$('slot-minutes').value;
    $('slot-ends').value = start ? clock(minutesOf(start) + minutes) + (minutesOf(start) + minutes > 1440 ? ' (next day)' : '') : '';
    $('slot-save').textContent = form.editing ? 'Save' : form.repeat === 'once' ? 'Add this once' : 'Add to the lineup';
    // What it would overlap, as a warning (it is allowed: the later start has the time).
    const warn = $('slot-warning'); warn.hidden = true;
    if (!start || form.repeat !== 'weekly' || !data) return;
    const a = minutesOf(start), b = a + minutes;
    const over = data.settings.slots.filter(s => s.id !== form.editing && s.enabled && s.days.some(d => form.days.has(d)) && minutesOf(s.start) < b && a < minutesOf(s.start) + s.minutes);
    if (over.length) { warn.hidden = false; warn.textContent = 'Overlaps ' + over.map(s => s.title + ' (' + clock(minutesOf(s.start)) + ')').join(', ') + '. Of two slots, the higher priority has the time, then the one that starts later.'; }
  }
  async function loadFolders() {
    const sel = $('library-folder');
    if (!folders) { sel.replaceChildren(new Option('Loading…', '')); try { folders = (await api('v1/programming/library')).folders; } catch (e) { folders = []; say(e.message, true); } }
    const keyOf = f => [f.root, f.path || '', f.name || ''].join('|');
    sel.replaceChildren(...folders.map(f => new Option((f.whole ? 'All of ' + f.label : f.label + ' · ' + f.root_name) + ' · ' + f.files + ' files · about ' + f.minutes + ' min', keyOf(f))));
    if (!folders.length) sel.append(new Option('The library has no folders with files', ''));
    const what = form.editing ? slotOf(form.editing)?.what : form.picked?.what;
    if (what?.kind === 'library') sel.value = [what.root, what.path || '', what.name || ''].join('|');
    folderChanged(!what || what.kind !== 'library');
  }
  function folderChanged(defaults) {
    const f = folders?.find(f => [f.root, f.path || '', f.name || ''].join('|') === $('library-folder').value);
    $('library-breaks-label').hidden = !f?.breaks;
    if (!f) return;
    if (defaults) {
      $('library-order').value = f.order; $('library-breaks').value = f.breaks ? '120' : '0';
      if (!form.named) $('slot-title').value = f.label.slice(0, 48);
      if (!form.editing) setMinutes(Math.max(30, Math.ceil((f.minutes + (f.breaks ? 6 : 0)) / 30) * 30));
    }
    $('library-note').textContent = 'One file per airing, about ' + f.minutes + ' min' + (f.breaks ? ' plus its ad breaks' : '') + '. It plays to its end; the rest of the slot is the test card, and a file longer than its slot is cut by what starts next.';
    slotChanged();
  }
  $('library-folder').onchange = () => folderChanged(true);
  let searchTimer = null, searchSeq = 0;
  function searchProgrammes() {
    clearTimeout(searchTimer);
    const q = $('program-search').value.trim(), list = $('program-results');
    if (form.picked?.title !== q) form.picked = q ? {title: q, typed: true} : null;
    if (q.length < 2) { list.replaceChildren(); return; }
    searchTimer = setTimeout(async () => {
      const seq = ++searchSeq;
      let found = [];
      try { found = (await api('v1/programming/search?q=' + encodeURIComponent(q))).programmes; } catch { /* The listings are away: the name typed is used. */ }
      if (seq !== searchSeq) return;
      list.replaceChildren(...found.map(p => {
        const next = p.next, b = h('button', {type: 'button', role: 'option', 'aria-selected': 'false'}, h('strong', p.title),
          h('small', next ? 'Next: ' + fmt.when(next.start) + ' · ' + next.channel + (next.new ? ' · new' : '') + (p.airings > 1 ? ' · ' + p.airings + ' airings listed' : '') : 'Seen in the listings before · ' + p.channels.join(', ')));
        b.onclick = () => pickProgramme(p, b);
        return h('li', b);
      }));
      if (!found.length) list.replaceChildren(h('li', {class: 'hint tiny', style: {padding: '8px 10px'}}, 'Nothing by that name in the listings. It can still be added: it airs on the channel below until the listings have it.'));
    }, 220);
  }
  function pickProgramme(p, button) {
    form.picked = {title: p.title};
    $('program-search').value = p.title;
    document.querySelectorAll('#program-results [role=option]').forEach(b => b.setAttribute('aria-selected', String(b === button)));
    if (!form.named) $('slot-title').value = p.title.slice(0, 48);
    const next = p.next;
    if (next) {
      targetPicker($('usual-target'), next.target, {off: false, none: true});
      const z = zoned(new Date(next.start)), length = Math.round((Date.parse(next.end) - Date.parse(next.start)) / 6e4);
      if (!form.editing) {
        $('slot-start').value = hhmm(z.minutes); setMinutes(Math.max(5, length));
        if (form.repeat === 'once') $('slot-date').value = z.date;
        else if (!form.touchedDays) { form.days.clear(); form.days.add(DAYS[z.day]); chips($('slot-days'), form.days, daysTouched); }
      }
      $('program-note').textContent = 'Listed ' + fmt.when(next.start) + ' for ' + mins(length) + ' on ' + next.channel + '. The time is set to match; each airing follows the listings from there.';
    } else $('program-note').textContent = 'Not in the listings now. It airs on the channel below until they have it.';
    slotChanged();
  }
  const daysTouched = () => { form.touchedDays = true; slotChanged(); };
  $('program-search').oninput = searchProgrammes;
  $('slot-title').oninput = () => { form.named = !!$('slot-title').value.trim(); };
  $('slot-start').oninput = slotChanged; $('slot-minutes').onchange = slotChanged;
  document.querySelectorAll('#slot-kinds button').forEach(b => { b.onclick = () => setKind(b.dataset.kind); });
  document.querySelectorAll('#slot-repeat button').forEach(b => { b.onclick = () => setRepeat(b.dataset.repeat); });
  document.querySelectorAll('[data-days]').forEach(b => { b.onclick = () => { form.days = new Set(b.dataset.days.split(',')); form.touchedDays = true; chips($('slot-days'), form.days, daysTouched); slotChanged(); }; });
  function swatches() {
    $('slot-colors').replaceChildren(...COLORS.map(c => { const b = h('button', {type: 'button', 'aria-label': 'Colour ' + c, 'aria-pressed': String(c === form.color), style: {background: c}}); b.onclick = () => { form.color = c; swatches(); }; return b; }));
  }
  // slot: one to edit. given: {kind, day, minute, date} from a tap, or an idea's body {title, days, start, minutes, what}.
  function openSlot(slot, given = {}) {
    const what = slot?.what || given.what;
    Object.assign(form, {editing: slot?.id || null, picked: what ? {title: what.title, what} : null, named: !!(slot || given.title), touchedDays: !!(slot || given.days),
      days: new Set(slot?.days || given.days || [given.day || DAYS[zoned(new Date()).day]]), color: slot?.color || COLORS[(data?.settings.slots.length || 0) % COLORS.length]});
    $('slot-dialog-title').textContent = slot ? 'Edit ' + slot.title : 'Add to the lineup';
    $('slot-title').value = slot?.title || given.title || '';
    const start = slot?.start || given.start || hhmm(given.minute ?? Math.ceil((zoned(new Date()).minutes + 1) / 30) * 30 % 1440);
    $('slot-start').value = start; setMinutes(slot?.minutes || given.minutes || 30);
    $('slot-date').value = given.date || zoned(new Date()).date;
    $('slot-priority').value = slot?.priority || 'normal';
    $('program-search').value = what?.kind === 'program' ? what.title : ''; $('program-results').replaceChildren();
    $('program-follow').checked = what?.follow !== false;
    $('program-note').textContent = 'The channel follows the programme: each airing is looked up in the listings.';
    targetPicker($('usual-target'), what?.kind === 'program' ? what.target : null, {off: false, none: true});
    targetPicker($('channel-target'), what?.kind === 'channel' ? what.target : null);
    $('library-order').value = what?.order || 'next'; $('library-breaks').value = String(what?.ad_breaks || 0);
    $('slot-delete').hidden = !slot; $('slot-repeat').parentElement.hidden = !!slot;
    chips($('slot-days'), form.days, daysTouched); swatches();
    setRepeat('weekly'); setKind(what?.kind || given.kind || 'program');
    $('slot-dialog').showModal();
    if (form.kind === 'program' && !slot) $('program-search').focus();
  }
  function whatFromForm() {
    if (form.kind === 'channel') return {kind: 'channel', target: $('channel-target').value()};
    if (form.kind === 'library') {
      const f = folders?.find(f => [f.root, f.path || '', f.name || ''].join('|') === $('library-folder').value);
      if (!f) throw Error('Choose a folder');
      const breaks = +$('library-breaks').value;
      return {kind: 'library', root: f.root, order: $('library-order').value, ...(f.path ? {path: f.path} : {}), ...(f.name ? {name: f.name} : {}), ...(f.breaks && breaks ? {ad_breaks: breaks} : {})};
    }
    const title = (form.picked?.title || $('program-search').value).trim();
    if (!title) throw Error('Name the programme to look for');
    const usual = $('usual-target').value();
    return {kind: 'program', title, follow: $('program-follow').checked, ...(usual ? {target: usual} : {})};
  }
  $('slot-form').onsubmit = async e => {
    e.preventDefault(); $('slot-save').disabled = true;
    try {
      const what = whatFromForm(), title = $('slot-title').value.trim() || what.title;
      if (!title) throw Error('Give it a name');
      const start = $('slot-start').value, minutes = +$('slot-minutes').value;
      if (!start) throw Error('Choose a start time');
      if (form.repeat === 'once' && !form.editing) {
        const target = what.target;
        if (!target) throw Error('For a one-off, choose the channel it is on');
        const from = instant($('slot-date').value, minutesOf(start));
        await addShow({mode: 'program', title: title.slice(0, 72), target, start: from.toISOString(), end: new Date(from.getTime() + minutes * 6e4).toISOString(), priority: $('slot-priority').value});
      } else {
        if (!form.days.size) throw Error('Choose at least one day');
        const body = {title: title.slice(0, 48), color: form.color, days: DAYS.filter(d => form.days.has(d)), start, minutes, priority: $('slot-priority').value, what};
        if (form.editing) await updateSlot(slotOf(form.editing), body, title + ' saved.'); else await addSlot(body);
      }
      $('slot-dialog').close();
    } catch (err) { say(err.message, true); } finally { $('slot-save').disabled = false; }
  };
  $('slot-cancel').onclick = () => $('slot-dialog').close();
  $('slot-delete').onclick = async () => { try { await removeSlot(form.editing); $('slot-dialog').close(); } catch (e) { say(e.message, true); } };

  /* Sports slots ------------------------------------------------------------------------------------- */
  const sp = {editing: null, days: new Set(), preset: null};
  const radio = (name, value) => { if (value === undefined) return document.querySelector('[name=' + name + ']:checked').value; document.querySelectorAll('[name=' + name + ']').forEach(r => { r.checked = r.value === value; }); };
  const names = text => text.split(',').map(s => s.trim()).filter(Boolean);
  function sportsBody() {
    return {title: $('sp-title').value.trim(), league: $('sp-league').value, days: DAYS.filter(d => sp.days.has(d)), from: $('sp-from').value, to: $('sp-to').value,
      networks: names($('sp-networks').value), teams: names($('sp-teams').value), pick: radio('sp-pick'), priority: radio('sp-priority'), lead_minutes: +$('sp-lead').value, ...(sp.preset ? {preset: sp.preset} : {})};
  }
  const STATUS = {would: ['pvw', 'Airs'], scheduled: ['pvw', 'Scheduled'], shared: ['pvw', 'Scheduled'], passed: ['', 'Not the pick'], no_channel: ['warn', 'No channel'], removed: ['', 'Removed by hand'], error: ['warn', 'Could not schedule']};
  function gameRow(g) {
    const [tone, text] = STATUS[g.status] || ['', g.status];
    return h('li', h('time', {dateTime: g.start_time}, fmt.when(g.start_time)), h('div', {class: 'grow'}, h('strong', (ICON[g.league] || '') + g.title), h('small', (g.networks.join(', ') || 'No channel you get') + (g.error ? ' · ' + g.error : ''))), h('span', {class: 'chip ' + tone}, text));
  }
  let previewTimer = null, previewSeq = 0;
  function previewSports() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const list = $('sp-preview'), seq = ++previewSeq;
      if (!sp.days.size) { list.replaceChildren(h('li', {class: 'hint'}, 'Choose at least one day.')); return; }
      list.replaceChildren(h('li', {class: 'hint'}, 'Looking for games…'));
      try {
        const games = (await api('v1/programming/sports/preview', {...sportsBody(), title: $('sp-title').value.trim() || 'Sports'})).games;
        if (seq !== previewSeq) return;
        list.replaceChildren(...(games.length ? games.map(gameRow) : [h('li', {class: 'hint'}, 'No games match in the next 8 days. The slot still stands for when they do.')]));
      } catch (e) { if (seq === previewSeq) list.replaceChildren(h('li', {class: 'hint'}, e.message)); }
    }, 350);
  }
  function openSports(slot, given) {
    const s = slot || given || {};
    sp.editing = slot?.id || null; sp.preset = s.preset || null; sp.days = new Set(s.days || ['mon']);
    $('sports-dialog-title').textContent = slot ? 'Edit ' + slot.title : 'Sports slot';
    $('sp-title').value = s.title || ''; $('sp-league').value = s.league || 'nfl'; $('sp-from').value = s.from || '19:00'; $('sp-to').value = s.to || '23:30';
    $('sp-networks').value = (s.networks || []).join(', '); $('sp-teams').value = (s.teams || []).join(', '); $('sp-lead').value = String(s.lead_minutes || 0);
    radio('sp-pick', s.pick || 'all'); radio('sp-priority', s.priority || 'normal');
    chips($('sp-days'), sp.days, previewSports);
    $('sp-delete').hidden = !slot; $('sp-save').textContent = slot ? 'Save' : 'Add sports slot';
    $('sports-dialog').showModal(); previewSports();
  }
  for (const id of ['sp-league', 'sp-from', 'sp-to', 'sp-networks', 'sp-teams']) $(id).addEventListener('change', previewSports);
  document.querySelectorAll('[name=sp-pick]').forEach(r => r.addEventListener('change', previewSports));
  $('sp-cancel').onclick = () => $('sports-dialog').close();
  $('sports-form').onsubmit = async e => {
    e.preventDefault(); $('sp-save').disabled = true;
    try {
      const body = sportsBody();
      if (!body.days.length) throw Error('Choose at least one day');
      if (sp.editing) {
        const before = data.settings.sports.find(s => s.id === sp.editing);
        adopt(await api('v1/programming/sports/' + sp.editing, body));
        done(body.title + ' saved.', async () => { adopt(await api('v1/programming/sports/' + sp.editing, before)); });
      } else {
        const r = adopt(await api('v1/programming/sports', body)), id = r.changed.id;
        done(body.title + ' is a sports slot: its games go on by themselves.', async () => { adopt(await api('v1/programming/sports/' + id, undefined, {method: 'DELETE'})); });
      }
      $('sports-dialog').close(); settle();
    } catch (err) { say(err.message, true); } finally { $('sp-save').disabled = false; }
  };
  $('sp-delete').onclick = async () => {
    const slot = data.settings.sports.find(s => s.id === sp.editing);
    try {
      adopt(await api('v1/programming/sports/' + sp.editing, undefined, {method: 'DELETE'})); $('sports-dialog').close();
      done(slot.title + ' is gone. Its games that have not started come off the schedule.', async () => { adopt(await api('v1/programming/sports', slot)); settle(); }); settle();
    } catch (e) { say(e.message, true); }
  };
  // The planner works a moment after a change: its games arrive on the week by themselves.
  function settle() { setTimeout(() => refresh().catch(() => {}), 2500); setTimeout(() => refresh().catch(() => {}), 9000); }
  async function loadSports() { try { sportsView = await api('v1/programming/sports'); } catch { sportsView = null; } }
  function renderSports() {
    const host = $('sports-slots'); host.replaceChildren();
    const slots = data.settings.sports || [], found = sportsView?.games || [];
    if (slots.length) {
      const list = h('ul', {class: 'list rows', style: {border: '1px solid var(--line)', borderRadius: 'var(--r)', marginBottom: '14px'}});
      for (const s of slots) {
        const prio = h('select', {'aria-label': 'Priority of ' + s.title, style: {width: 'auto', height: '28px', fontSize: '13px'}}, ...['low', 'normal', 'high'].map(p => h('option', {value: p}, p[0].toUpperCase() + p.slice(1))));
        prio.value = s.priority;
        prio.onchange = async () => { try { adopt(await api('v1/programming/sports/' + s.id, {priority: prio.value})); done(s.title + ' is ' + prio.value + ' priority.', async () => { adopt(await api('v1/programming/sports/' + s.id, {priority: s.priority})); settle(); }); settle(); } catch (e) { say(e.message, true); } };
        const on = h('input', {type: 'checkbox', checked: s.enabled, 'aria-label': s.title + ' on'});
        on.onchange = async () => { try { adopt(await api('v1/programming/sports/' + s.id, {enabled: on.checked})); say(s.title + (on.checked ? ' is on.' : ' is off: its games that have not started come off.')); settle(); } catch (e) { say(e.message, true); } };
        const edit = h('button', {type: 'button', class: 'quiet sm'}, 'Edit'); edit.onclick = () => openSports(s);
        const games = found.filter(g => g.slot === s.id && ['scheduled', 'shared'].includes(g.status)), other = found.filter(g => g.slot === s.id && ['no_channel', 'error', 'removed'].includes(g.status));
        list.append(h('li', {class: s.enabled ? '' : 'off'}, h('div', {class: 'grow'}, h('strong', (ICON[s.league] || '') + s.title),
          h('small', spokenDays(s.days) + ' · games starting ' + clock(minutesOf(s.from)) + '–' + clock(minutesOf(s.to)) + (s.networks.length ? ' · on ' + s.networks.join(', ') : '') + (s.teams.length ? ' · ' + s.teams.join(', ') : '') + (s.pick === 'best' ? ' · the best one each day' : '')),
          games.length ? h('small', 'Next: ' + games.slice(0, 3).map(g => g.title + ' (' + fmt.when(g.start_time) + ')').join(' · ')) : s.enabled ? h('small', 'No games found in the next ' + (sportsView?.days || 8) + ' days.') : null,
          other.length ? h('small', {class: 'note'}, other.map(g => g.title + ': ' + (STATUS[g.status]?.[1] || g.status).toLowerCase()).join(' · ')) : null),
          prio, h('label', {class: 'switch'}, on), edit));
      }
      host.append(list);
    }
    const presets = sportsView?.presets || [];
    if (presets.length) host.append(h('div', {class: 'group-head'}, h('h3', slots.length ? 'More ready-made slots' : 'Ready-made slots')),
      h('div', {class: 'cards'}, presets.map(p => { const b = h('button', {type: 'button', class: 'sm primary'}, 'Set up'); b.onclick = () => openSports(null, p);
        return h('div', {class: 'card'}, h('h3', (ICON[p.league] || '') + p.title), h('p', p.blurb), h('div', {class: 'actions'}, b)); })));
    const own = h('button', {type: 'button', class: 'quiet sm'}, '+ A slot of your own'); own.onclick = () => openSports(null, null);
    host.append(h('div', {class: 'actions', style: {margin: '12px 0 4px'}}, own, sportsView?.checked_at ? h('span', {class: 'hint tiny'}, 'Games checked at ' + hm(sportsView.checked_at) + '.') : null));
  }

  /* One game (the form the sports list's ⋯ opens) --------------------------------------------------------- */
  let games = [];
  function gamePicker() {
    const g = games.find(g => String(g.game_id) === $('game').value);
    targetPicker($('game-target'), g?.suggested_target, {off: false, auto: $('league').value === 'mlb', ticket: g?.sunday_ticket_target, prime: g?.prime_video_target, espn: g?.espn_unlimited_target});
    $('game-note').textContent = g ? [g.broadcasts.length ? 'On ' + [...new Set(g.broadcasts.map(b => b.name))].join(', ') : 'No TV listing', g.note].filter(Boolean).join('. ') : '';
  }
  $('league').onchange = () => { games = []; $('game').replaceChildren(new Option('Load a date first', '')); gamePicker(); };
  $('load-games').onclick = async () => {
    const sel = $('game'); sel.replaceChildren(new Option('Loading…', ''));
    try {
      const r = await api('v1/sports/games?league=' + $('league').value + '&date=' + encodeURIComponent($('game-date').value));
      games = r.games || [];
      sel.replaceChildren(new Option(games.length ? 'Choose a game' : 'No games on this date', ''), ...games.map(g => new Option(hm(g.start_time) + ' · ' + g.title + (g.channels?.length ? ' · ' + g.channels.join('/') : ''), g.game_id)));
      gamePicker();
    } catch (e) { sel.replaceChildren(new Option('Could not load games', '')); say(e.message, true); }
  };
  $('game').onchange = () => {
    gamePicker();
    const g = games.find(g => String(g.game_id) === $('game').value); if (!g) return;
    const s = new Date(g.start_time); $('show-start').value = fmt.local(s); $('show-end').value = fmt.local(new Date(s.getTime() + LEAGUE_HOURS[g.league] * 3600e3));
  };
  $('backup-target').addEventListener('change', () => { $('backup-title-label').hidden = $('backup-target').source?.() === 'schedule'; });
  function openGame(at, g) {
    const today = zoned(new Date());
    $('game-date').value = g?.game_date || at?.date || today.date; $('game-title').value = ''; $('show-priority').value = 'normal';
    targetPicker($('backup-target'), null, {schedule: true});
    if (g) {
      $('league').value = g.league; games = [{...g, official_date: g.game_date}];
      $('game').replaceChildren(new Option((g.start_time_tbd ? 'TBD' : hm(g.start_time)) + ' · ' + g.title + (g.channels?.length ? ' · ' + g.channels.join('/') : ''), g.game_id));
      $('game').value = String(g.game_id); $('game').onchange();
      if (g.start_time_tbd) { $('show-start').value = ''; $('show-end').value = ''; }
    } else { games = []; $('game').replaceChildren(new Option('Load a date first', '')); gamePicker(); $('show-start').value = ''; $('show-end').value = ''; $('load-games').click(); }
    $('game-dialog').showModal();
  }
  $('game-cancel').onclick = () => $('game-dialog').close();
  $('show-form').onsubmit = async e => {
    e.preventDefault(); $('add-show').disabled = true;
    try {
      const start = new Date($('show-start').value), end = new Date($('show-end').value);
      if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) throw Error('Choose a start and window end');
      const g = games.find(g => String(g.game_id) === $('game').value); if (!g) throw Error('Choose a game');
      const body = {mode: 'game', start: start.toISOString(), end: end.toISOString(), priority: $('show-priority').value};
      const target = $('game-target').value(); if (target) body.target = target;
      else if (!$('game-target').antenna()) body.target = {source_id: 'mlb', channel_id: String(g.game_id), date: g.official_date || $('game-date').value, antenna: false};
      Object.assign(body, {game: {league: g.league, game_pk: g.game_id, game_date: g.official_date || $('game-date').value}, backup: $('backup-target').value(), backup_title: $('backup-title').value.trim() || 'Backup program'});
      if ($('game-title').value.trim()) body.title = $('game-title').value.trim();
      await addShow(body, 'Game scheduled.'); $('game-dialog').close();
    } catch (err) { say(err.message, true); } finally { $('add-show').disabled = false; }
  };

  /* What one thing on the week is, and what can be done with it ------------------------------------------- */
  const fact = (name, value) => value ? [h('dt', name), h('dd', value)] : [];
  function openInfo(item) {
    const body = $('info-body'), foot = $('info-foot'), out = item.out, close = () => $('info-dialog').close();
    const act = (label, run, cls = '') => { const b = h('button', {type: 'button', class: cls}, label); b.onclick = async () => { try { close(); await run(); } catch (e) { say(e.message, true); } }; return b; };
    const outcomeLine = out.state === 'airs' ? 'Airs ' + hm(out.from) + '–' + (out.estimated ? 'about ' : '') + hm(out.to) : out.text;
    const tone = ['wont', 'late', 'cut', 'nothing'].includes(out.state) ? 'note warn' : out.state === 'airs' ? 'note ok' : 'hint';
    $('info-title').textContent = (item.type === 'game' ? ICON[item.show.game?.league || 'mlb'] || '' : '') + item.title;
    foot.replaceChildren();
    if (item.type === 'ghost') {
      const idea = item.idea;
      body.replaceChildren(h('p', {class: 'hint'}, idea.why), h('dl', {class: 'facts'}, fact('When', idea.group === 'soon' ? fmt.full(item.start) + ' – ' + hm(item.end) : spokenDays(item.days || idea.days) + ' · ' + clock(minutesOf(idea.start)) + ' · ' + mins(idea.minutes)), fact('Detail', idea.detail)));
      foot.append(act('Not this one', () => { ghosts = ghosts.filter(g => g.idea.id !== idea.id); renderAll(); }, 'quiet'), ideaEditable(idea) ? act('Change it first', () => editIdea(idea, item.days)) : null, act('Add it', () => applyIdea(idea, item.days), 'primary'));
    } else if (item.type === 'slot') {
      const slot = slotOf(item.slot), what = slot.what;
      const source = item.by === 'listings' ? item.label + ' · from the listings' + (item.listed?.episode_title ? ' · “' + item.listed.episode_title + '”' : '') + (item.listed?.new ? ' · new' : '')
        : item.by === 'usual' ? (item.label || channelName(item.target)) + ' · its usual channel (' + (item.why || 'not listed').toLowerCase() + ')'
        : item.by === 'library' ? item.label + (item.length ? ' · ' + fmt.dur(item.length) : '') + (item.fits === false ? ' · longer than its slot' : '')
        : item.by === 'fixed' ? channelName(item.target) : item.by === 'skipped' ? '' : item.why;
      const rule = what.kind === 'program' ? 'Follows “' + what.title + '” through the listings' + (what.target ? '; usually ' + channelName(what.target) : '; skipped when not listed')
        : what.kind === 'library' ? 'One file from the library each time (' + ({next: 'the next in order', newest: 'the newest', shuffle: 'at random'})[what.order] + ')' : 'Always this channel';
      body.replaceChildren(h('p', {class: tone}, outcomeLine || 'On the plan.'),
        h('dl', {class: 'facts'}, fact('This airing', dayName(item.start) + ' · ' + hm(item.start) + '–' + hm(item.end)), fact('From', source), fact('The slot', spokenDays(slot.days) + ' · ' + clock(minutesOf(slot.start)) + ' · ' + mins(slot.minutes)), fact('How', rule)),
        out.state === 'wont' && out.other?.key && refOf(out.other.key) ? h('p', {class: 'hint'}, 'Shows and games on a date come before the lineup. To air this instead, remove or move “' + (out.other.title || 'the other one') + '”.') : null);
      const future = Date.parse(item.end) > Date.now();
      foot.append(act('Remove slot…', async () => { if (await VV.confirm('Take “' + slot.title + '” off the lineup on every day?', {title: 'Remove slot', ok: 'Remove', danger: true})) await removeSlot(slot.id); }, 'danger'),
        future ? act(item.skipped ? 'Put this one back' : 'Skip this one', () => skipAiring(item, !item.skipped), 'quiet') : null,
        act('Edit slot', () => openSlot(slot), 'primary'));
      foot.firstChild.style.marginRight = 'auto';
    } else {
      const show = item.show, game = item.type === 'game';
      const prio = h('div', {class: 'seg', role: 'group', 'aria-label': 'Priority'}, ...['low', 'normal', 'high'].map(p => { const b = h('button', {type: 'button', 'aria-pressed': String((show.priority || 'normal') === p)}, p); b.onclick = async () => { close(); try { await setPriority(show, p); } catch (e) { say(e.message, true); } }; return b; }));
      const slot = show.slot ? (data.settings.sports || []).find(s => s.id === show.slot) : null;
      body.replaceChildren(h('p', {class: tone}, outcomeLine || 'On the plan.'),
        h('dl', {class: 'facts'}, fact(game ? 'Window' : 'When', fmt.full(show.start) + ' – ' + hm(show.end)), fact('On', game ? (show.game.league || 'mlb').toUpperCase() + ' · ' + routed(show.target) : channelName(show.target)),
          game ? fact('Then', show.backup.source_id === 'schedule' ? 'Back to the schedule after the final' : show.backup_title + ' on ' + channelName(show.backup)) : [],
          fact('Added by', slot ? 'The sports slot ' + slot.title : show.added_by === 'favorites' ? 'A favorite team (Crawl › Favorites)' : show.added_by === 'slot' ? 'A sports slot' : ''),
          fact('Changed', show.update ? show.update.text + ' · ' + hm(show.update.at) : ''), fact('Feed', show.missing_since ? 'Not on its league’s schedule since ' + hm(show.missing_since) : '')),
        h('div', {class: 'field'}, h('span', 'Priority'), prio, h('p', {class: 'hint tiny'}, game ? 'High cuts in at its start, even into another game. Normal waits for what holds master and joins in progress. Low gives way to Normal.' : 'High cuts into a game on air at its start. Otherwise it waits for the game to end.')));
      foot.append(act('Remove', () => removeShow(show), 'danger'));
      foot.firstChild.style.marginRight = 'auto';
    }
    $('info-dialog').showModal();
  }
  $('info-close').onclick = () => $('info-dialog').close();
  $('info-dialog').addEventListener('click', e => { if (e.target === $('info-dialog')) $('info-dialog').close(); });

  /* Ideas ---------------------------------------------------------------------------------------------- */
  const tabOpen = name => document.querySelector('[data-tab=' + name + ']')?.getAttribute('aria-selected') === 'true';
  const ideaEditable = idea => ['strips', 'library', 'habits', 'sports'].includes(idea.group);
  const allIdeas = () => (ideas?.groups || []).flatMap(g => g.ideas);
  async function loadIdeas(fresh) {
    $('ideas-note').textContent = 'Looking through the listings, the library and the sports feeds…';
    try { ideas = await api('v1/programming/ideas' + (fresh ? '?fresh=1' : '')); } catch (e) { ideas = {groups: [], draft: [], error: e.message}; }
    ghosts = ghosts.filter(g => allIdeas().some(i => i.id === g.idea.id));
    renderIdeas(); renderWeek();
  }
  function editIdea(idea, days) {
    const body = idea.apply.body;
    if (idea.group === 'sports') openSports(null, body); else openSlot(null, {...body, days: days || body.days});
  }
  async function applyIdea(idea, days) {
    const {path, body} = idea.apply;
    ghosts = ghosts.filter(g => g.idea.id !== idea.id);
    if (idea.group === 'fixups') await updateSlot(slotOf(idea.slot), body, idea.apply.body.title ? 'Renamed to ' + body.title + ': it follows the listings now.' : idea.title + ' follows the listings now.');
    else if (idea.group === 'soon') await addShow(body);
    else if (idea.group === 'sports') { const r = adopt(await api(path, body)), id = r.changed.id; done(idea.title + ' is a sports slot: its games go on by themselves.', async () => { adopt(await api('v1/programming/sports/' + id, undefined, {method: 'DELETE'})); settle(); }); settle(); }
    else await addSlot({...body, days: days || body.days, color: COLORS[data.settings.slots.length % COLORS.length]});
  }
  function renderIdeas() {
    const host = $('ideas'); host.replaceChildren();
    if (!ideas) return;
    const groups = ideas.groups.map(g => ({...g, ideas: g.ideas.filter(i => !hiddenIdeas.has(i.id))})).filter(g => g.ideas.length);
    const count = groups.reduce((n, g) => n + g.ideas.length, 0), guide = ideas.guide || {};
    $('ideas-count').hidden = !count; $('ideas-count').textContent = count;
    $('ideas-note').textContent = ideas.error ? 'Could not look for ideas: ' + ideas.error
      : (guide.available ? 'From ' + guide.programmes + ' programmes on ' + guide.channels + ' channels listed until ' + fmt.when(guide.reaches) + ', what the listings showed since ' + (guide.atlas_since || 'today') + ', the library and the sports feeds.' : 'The listings are away: ideas come from the library and the sports feeds only.')
      + (hiddenIdeas.size ? ' ' + hiddenIdeas.size + ' hidden.' : '');
    $('draft').disabled = !ideas.draft?.length;
    for (const g of groups) {
      host.append(h('div', {class: 'group-head'}, h('h3', g.title), h('span', {class: 'hint tiny'}, g.blurb)));
      host.append(h('div', {class: 'cards'}, g.ideas.map(idea => {
        const shown = ghosts.some(x => x.idea.id === idea.id), canShow = idea.group === 'soon' || (idea.days && idea.start);
        const add = h('button', {type: 'button', class: 'primary sm'}, g.id === 'fixups' ? 'Do it' : 'Add');
        add.onclick = async () => { add.disabled = true; try { await applyIdea(idea); } catch (e) { say(e.message, true); add.disabled = false; } };
        const edit = ideaEditable(idea) ? h('button', {type: 'button', class: 'sm'}, 'Change…') : null; if (edit) edit.onclick = () => editIdea(idea);
        const peek = canShow ? h('button', {type: 'button', class: 'quiet sm', 'aria-pressed': String(shown)}, shown ? 'Hide on week' : 'Show on week') : null;
        if (peek) peek.onclick = () => { ghosts = shown ? ghosts.filter(x => x.idea.id !== idea.id) : [...ghosts, {idea}]; renderIdeas(); renderWeek(); if (!shown) $('week-panel').scrollIntoView({behavior: 'smooth', block: 'start'}); };
        const hide = h('button', {type: 'button', class: 'quiet sm', title: 'Do not suggest this again'}, 'Hide'); hide.onclick = () => { hiddenIdeas.add(idea.id); VV.store.set('scheduleHiddenIdeas', [...hiddenIdeas].slice(-300)); renderIdeas(); };
        return h('div', {class: 'card' + (shown ? ' on' : '')}, h('h3', idea.title), h('p', idea.why), idea.detail ? h('p', idea.detail) : null,
          idea.when ? h('span', {class: 'when'}, (g.id === 'soon' ? '' : 'Next: ') + fmt.when(idea.when) + (idea.count > 1 ? ' · ' + idea.count + ' games in the next week' : '')) : null,
          idea.free === false ? h('p', {class: 'note warn', style: {margin: 0}}, 'Overlaps the lineup at ' + clock(minutesOf(idea.start)) + ': change it first, or the later start has the time.') : null,
          h('div', {class: 'actions'}, add, edit, peek, hide));
      })));
    }
    if (!groups.length && !ideas.error) host.append(h('p', {class: 'hint'}, 'No ideas just now. The listings are noted every day, so regular programmes show up here within the week.'));
    if (hiddenIdeas.size) { const b = h('button', {type: 'button', class: 'quiet sm', style: {marginTop: '12px'}}, 'Show the ' + hiddenIdeas.size + ' hidden'); b.onclick = () => { hiddenIdeas = new Set(); VV.store.set('scheduleHiddenIdeas', []); renderIdeas(); }; host.append(b); }
  }
  $('ideas-refresh').onclick = () => loadIdeas(true);
  $('draft').onclick = () => {
    const byId = new Map(allIdeas().map(i => [i.id, i]));
    ghosts = (ideas?.draft || []).filter(d => byId.has(d.id) && !hiddenIdeas.has(d.id)).map(d => ({idea: byId.get(d.id), days: d.days}));
    if (!ghosts.length) { say('Nothing more fits beside the lineup just now.'); return; }
    renderIdeas(); renderWeek(); $('week-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  function renderDraftbar() {
    const bar = $('draftbar'); bar.hidden = !ghosts.length;
    if (!ghosts.length) return;
    const all = h('button', {type: 'button', class: 'primary sm'}, ghosts.length === 1 ? 'Add it' : 'Add all ' + ghosts.length);
    all.onclick = async () => {
      all.disabled = true; const adding = ghosts; ghosts = []; let added = 0;
      for (const g of adding) { try { await applyIdea(g.idea, g.days); added++; } catch (e) { say(g.idea.title + ': ' + e.message, true); } }
      say(added + ' added to the schedule. Each has its own Undo; the lineup tab lists them all.');
    };
    const clear = h('button', {type: 'button', class: 'quiet sm'}, 'Clear'); clear.onclick = () => { ghosts = []; renderIdeas(); renderWeek(); };
    bar.replaceChildren(h('span', {style: {flex: '1', minWidth: '200px'}}, ghosts.length === 1 ? 'One suggestion is shown on the week (dashed green). Tap it to add or drop it.' : ghosts.length + ' suggestions are shown on the week (dashed green). Tap one to add or drop it, or take them all.'), all, clear);
  }

  /* Clashes: where two things want the same time ------------------------------------------------------------ */
  function renderClashes() {
    const host = $('clashes'), now = Date.now(), seen = new Set(), rows = [];
    for (const item of plan) {
      if (!['game', 'show'].includes(item.type) || !['wont', 'late', 'cut'].includes(item.out.state) || Date.parse(item.end) < now || seen.has(item.id)) continue;
      seen.add(item.id);
      const show = item.show, other = item.out.other, rival = other?.key && refOf(other.key) ? data.settings.shows.find(s => s.id === refOf(other.key)) : null;
      const fixes = [];
      const button = (label, run) => { const b = h('button', {type: 'button', class: 'sm'}, label); b.onclick = async () => { b.disabled = true; try { await run(); } catch (e) { say(e.message, true); } }; fixes.push(b); };
      if (item.out.state === 'cut') {
        const cutter = plan.find(p => p.show && p.id !== item.id && item.out.text.includes(p.title) && (p.priority === 'high' || p.show.favorites));
        if (cutter?.priority === 'high') button('Let ' + show.title + ' finish', () => setPriority(cutter.show, 'normal'));
        else button('Keep ' + show.title + ' on', () => setPriority(show, 'high'));
      } else if ((show.priority || 'normal') !== 'high') button(item.type === 'game' ? 'Cut in at its start' : 'Give it the time', () => setPriority(show, 'high'));
      else if (rival && (rival.priority || 'normal') === 'high') button('Lower ' + rival.title, () => setPriority(rival, 'normal'));
      const open = h('button', {type: 'button', class: 'quiet sm'}, 'Details'); open.onclick = () => openInfo(item);
      rows.push(h('li', {class: 'conflict'}, h('time', {dateTime: item.start}, fmt.when(item.start)), h('div', {class: 'grow'}, h('strong', (item.type === 'game' ? ICON[show.game?.league || 'mlb'] || '' : '') + item.title),
        h('small', {class: 'note'}, item.out.text + '.'), rival ? h('small', 'Up against ' + rival.title + ' (' + (rival.priority || 'normal') + ' priority' + (rival.favorites ? ', a favorite' : '') + '). This one is ' + (show.priority || 'normal') + '.') : null), ...fixes, open));
    }
    const twins = data.settings.shows.filter(s => Date.parse(s.end) > now && data.settings.shows.some(o => o !== s && o.start === s.start));
    for (const s of twins) rows.push(h('li', {class: 'conflict'}, h('time', fmt.when(s.start)), h('div', {class: 'grow'}, h('strong', s.title), h('small', {class: 'note'}, 'Starts at the same moment as another show: remove one.'))));
    $('clash-count').hidden = !rows.length; $('clash-count').textContent = rows.length;
    host.replaceChildren(rows.length ? h('ul', {class: 'list rows', style: {border: '1px solid var(--line)', borderRadius: 'var(--r)'}}, rows)
      : h('p', {class: 'hint'}, 'No clashes: every show and game on the week airs from its start.'));
  }

  /* The lineup as a list, shows on a date, and the rundown ----------------------------------------------------- */
  function slotSource(s) {
    const w = s.what;
    return w.kind === 'program' ? 'Follows “' + w.title + '”' + (w.target ? ' · usually ' + channelName(w.target) : ' · skipped when not listed')
      : w.kind === 'library' ? 'Library · ' + (w.name || (w.path || '').replace(/\/$/, '') || w.root) + ' · ' + ({next: 'next in order', newest: 'the newest', shuffle: 'at random'})[w.order] + (w.ad_breaks ? ' · ad breaks' : '')
      : channelName(w.target);
  }
  function renderLineup() {
    const list = $('lineup'); list.replaceChildren();
    const slots = [...data.settings.slots].sort((a, b) => minutesOf(a.start) - minutesOf(b.start) || DAYS.indexOf(a.days[0]) - DAYS.indexOf(b.days[0]));
    if (!slots.length) list.append(h('li', {class: 'hint'}, 'The lineup is empty: everything is OFF AIR but shows and games on a date. Tap a time on the week, or see Ideas.'));
    for (const s of slots) {
      const on = h('input', {type: 'checkbox', checked: s.enabled, 'aria-label': s.title + ' on'});
      on.onchange = async () => { try { await updateSlot(s, {enabled: on.checked}, s.title + (on.checked ? ' is back on.' : ' is switched off.')); } catch (e) { say(e.message, true); on.checked = !on.checked; } };
      const edit = h('button', {type: 'button', class: 'quiet sm'}, 'Edit'); edit.onclick = () => openSlot(s);
      list.append(h('li', {class: s.enabled ? '' : 'off', data: {slot: s.id}}, h('span', {class: 'swatch', style: {background: s.color}}), h('time', clock(minutesOf(s.start)) + '–' + clock(minutesOf(s.start) + s.minutes)),
        h('div', {class: 'grow'}, h('strong', s.title), h('small', spokenDays(s.days) + ' · ' + slotSource(s) + (s.skip?.length ? ' · ' + s.skip.length + ' skipped' : ''))), h('label', {class: 'switch'}, on), edit));
    }
    const shows = $('shows'), now = Date.now(), gone = data.game_gone_minutes || 20; shows.replaceChildren();
    const upcoming = data.settings.shows.filter(s => Date.parse(s.end) > now), removed = data.settings.removed || [];
    $('games-checked').textContent = data.games_checked_at ? 'Games checked against their feeds at ' + hm(data.games_checked_at) + '.' : '';
    $('gone-minutes').textContent = gone;
    if (!upcoming.length) shows.append(h('li', {class: 'hint'}, 'Nothing on a date. Sports slots and favorites add games here by themselves.'));
    let last = '';
    for (const s of upcoming) {
      if (dayName(s.start) !== last) { last = dayName(s.start); shows.append(h('li', {class: 'day'}, last)); }
      const item = plan.find(p => p.id === s.id), open = h('button', {type: 'button', class: 'quiet sm'}, 'Details'); open.onclick = () => item && openInfo(item);
      const prio = h('select', {'aria-label': 'Priority of ' + s.title, style: {width: 'auto', height: '28px', fontSize: '13px'}}, ...['low', 'normal', 'high'].map(p => h('option', {value: p}, p[0].toUpperCase() + p.slice(1))));
      prio.value = s.priority || 'normal'; prio.onchange = async () => { try { await setPriority(s, prio.value); } catch (e) { say(e.message, true); } };
      const del = h('button', {type: 'button', class: 'quiet sm', 'aria-label': 'Remove ' + s.title}, 'Remove'); del.onclick = async () => { try { await removeShow(s); } catch (e) { say(e.message, true); } };
      shows.append(h('li', {data: {show: s.id}}, h('time', {dateTime: s.start}, hm(s.start) + '–' + hm(s.end)), h('div', {class: 'grow'}, h('strong', (s.mode === 'game' ? ICON[s.game?.league || 'mlb'] : '') + s.title),
        h('small', s.mode === 'game' ? (s.game.league || 'mlb').toUpperCase() + ' · ' + routed(s.target) : channelName(s.target)),
        s.added_by ? h('small', s.added_by === 'favorites' ? '★ A favorite’s game' : 'From the sports slot ' + ((data.settings.sports || []).find(x => x.id === s.slot)?.title || '')) : null,
        item && ['wont', 'late', 'cut'].includes(item.out.state) ? h('small', {class: 'note'}, item.out.text) : null,
        s.update ? h('small', {class: 'note'}, s.update.text + ' · ' + hm(s.update.at)) : null), prio, open, del));
    }
    if (removed.length) { shows.append(h('li', {class: 'day'}, 'Removed by the sports feeds')); for (const r of removed) shows.append(h('li', {class: 'off'}, h('time', dayName(r.start)), h('div', {class: 'grow'}, h('strong', (ICON[r.league] || '') + r.title), h('small', r.text + ' · removed ' + hm(r.at))))); }
  }
  $('follow-games').onclick = async () => {
    const button = $('follow-games'); button.disabled = true;
    try { const r = await api('v1/programming/follow-games', {}); data = r; await afterChange(); say(r.changes.length ? r.changes.map(c => c.title + ': ' + c.text).join(' · ') : 'Every scheduled game matches its feed.'); }
    catch (e) { say(e.message, true); } finally { button.disabled = false; }
  };
  const offAir = s => s.kind === 'off_air' || s.target?.source_id === 'off-air';
  const airTitle = s => s.title || channelName(s.target);
  function score(s) { const g = s.game; if (!g) return ''; if (queue?.hold?.game?.game_pk === g.game_pk && queue.hold.detail) return queue.hold.detail; return queue?.games?.[(g.league || 'mlb') + ':' + g.game_pk]?.summary || ''; }
  function airDetail(s) {
    const cut = (s.notes || []).some(n => n.startsWith('Cut when'));
    const parts = s.kind === 'game' ? [(s.game?.league || 'mlb').toUpperCase() + ' · ' + routed(s.target), score(s), cut ? '' : 'until its final' + (s.estimated ? ' (estimated)' : '')]
      : s.kind === 'recording' ? ['Recording from Up next'] : s.kind === 'manual' ? ['Queued in Up next · ' + channelName(s.target)] : offAir(s) ? ['Test card'] : s.kind === 'ident' ? ['Station ID']
      : [channelName(s.target) + (s.kind === 'show' ? ' · scheduled show' : '')];
    return [...parts, ...(s.notes || [])].filter(Boolean).join(' · ');
  }
  const SWATCH = {game: 'var(--warn)', recording: 'var(--rec)', manual: 'var(--pvw)', show: 'var(--touch)'};
  function renderRundown() {
    const list = $('rundown'); list.replaceChildren(); const now = Date.now();
    $('rundown-paused').textContent = playback?.paused ? 'Up next is paused: nothing changes on master until it resumes.' : '';
    for (const s of playback ? playback.segments.filter(s => Date.parse(s.start) < now + 864e5) : data.timeline) {
      const off = offAir(s), current = Date.parse(s.start) <= now && now < Date.parse(s.end);
      list.append(h('li', {class: (off ? 'off ' : '') + (current ? 'current' : '')}, h('span', {class: 'swatch', style: {background: s.color || SWATCH[s.kind] || (off ? 'var(--line-2)' : 'var(--touch)')}}),
        h('time', {dateTime: s.start}, hm(s.start) + '–' + (s.estimated ? '~' : '') + hm(s.end)), h('div', {class: 'grow'}, h('strong', (s.kind === 'game' ? ICON[s.game?.league || 'mlb'] || '' : '') + airTitle(s)), h('small', airDetail(s)))));
    }
  }
  function renderStatus() {
    $('enabled').checked = data.settings.enabled;
    const [cur, next] = playback ? playback.segments : [data.on_now, data.timeline[1]];
    $('on-now').textContent = cur ? airTitle(cur) : '—'; $('on-now-detail').textContent = cur ? airDetail(cur) + ' · until ' + (cur.estimated ? '~' : '') + hm(cur.end) : '';
    $('next').textContent = next ? airTitle(next) : '—'; $('next-detail').textContent = next ? hm(next.start) + ' · ' + airDetail(next) : '';
    $('take-current').disabled = !data.settings.enabled;
    VV.fill($('queue-state'), h('span', {class: 'chip ' + (data.settings.enabled ? 'pvw' : 'warn')}, data.settings.enabled ? 'Running' : 'Stopped · nothing queued'),
      queue?.paused ? h('span', {class: 'chip warn', title: queue.pause_reason || ''}, 'Up next paused') : null);
    $('lookahead').textContent = data.lookahead_minutes; $('zone-note').textContent = 'Times are ' + data.timezone + '.';
    $('guide-reach').textContent = data.guide?.reaches ? 'to ' + fmt.when(data.guide.reaches) : 'nowhere just now (they are away)';
  }
  function renderAll() { if (!data) return; renderStatus(); renderWeek(); renderClashes(); renderLineup(); renderRundown(); renderSports(); renderIdeas(); sportsList?.render(); }

  /* Tabs, loading, and keeping up ------------------------------------------------------------------------------ */
  let sportsList = null;
  function tab(name) {
    document.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== name; });
    VV.store.set('scheduleTab', name);
    if (name === 'ideas' && !ideas) loadIdeas();
    if (name === 'sports' && !sportsList) { sportsList = OnAir.sports($('sports-list'), {scheduled: () => data?.settings.shows || [], customize: g => openGame(null, g)}); sportsList.load(); }
  }
  document.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => tab(b.dataset.tab); });
  OnAir.configure({refresh: () => refresh(), label: t => channelName(t)});
  $('enabled').onchange = async () => {
    const on = $('enabled').checked;
    try { data = await api('v1/programming', {enabled: on}); await afterChange(); say(on ? 'Schedule running. Upcoming changes will be queued.' : 'Schedule stopped. Its waiting entries were withdrawn from Up next.'); }
    catch (e) { say(e.message, true); $('enabled').checked = !on; }
  };
  $('take-current').onclick = async () => {
    try { const r = await api('v1/programming/take-current', {}); say(r.items.length ? 'Queued ' + (data.on_now?.title || 'what is on now') + ' to release in two seconds.' : 'What is on now is already in Up next.'); }
    catch (e) { say(e.message, true); }
  };
  async function loadPlayback() { [queue, playback] = await Promise.all([api('v1/queue').catch(() => null), api('v1/playback?until=' + encodeURIComponent(weekEnd().toISOString())).catch(() => null)]); }
  async function refresh() { data = await api('v1/programming'); await Promise.all([loadPlayback(), loadSports()]); renderAll(); }
  async function load() {
    try {
      const s = await api('v1/sources'); sources = s.sources || []; VV.known.sources = sources;
      await refresh();
      tab(VV.store.get('scheduleTab', 'ideas'));
      // The week opens at now, less an hour.
      const wrap = $('cal-wrap'), line = wrap.querySelector('.nowline'); if (line) wrap.scrollTop = Math.max(0, line.offsetTop - 70);
    } catch (e) { say(e.message, true); }
  }
  const busy = () => dragging || menu || [...document.querySelectorAll('dialog')].some(d => d.open);
  setInterval(() => { if (data && !document.hidden && !busy()) refresh().catch(() => {}); }, 30000);
  setInterval(() => { if (data && !document.hidden && !busy()) renderWeek(); }, 60000);
  document.addEventListener('vv:auth', load);
  VV.commands.add({id: 'schedule:add', title: 'Add to the schedule', group: 'Schedule', run: () => $('add').click()},
    {id: 'schedule:follow', title: 'Check the sports feeds now', group: 'Schedule', run: () => $('follow-games').click()},
    {id: 'schedule:draft', title: 'Draft a week from the ideas', group: 'Schedule', when: () => !!ideas?.draft?.length, run: () => $('draft').click()},
    {id: 'schedule:day', title: 'Show one day, or the week', group: 'Schedule', run: () => setMode(view.mode === 'day' ? 'week' : 'day')});
  load();
})();
