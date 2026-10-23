// Up next: the rundown. The only way on air; what is on master heads it, then what will
// actually air (GET /v1/playback: Up next and the schedule played forward under the queue's
// rules), then what the estimates leave out (Won't air), then what already happened.
//   UpNext.mount(host, {compact, find}) → {render}; find is an element (Find.box()) put under the head.
window.UpNext = (() => {
  'use strict';
  const {h, api, fmt, toast, label, same, icon, ICONS} = VV;
  const ICON = {nfl: '🏈 ', ncaaf: '🏈 ', mlb: '⚾ ', nba: '🏀 ', nhl: '🏒 ', wnba: '🏀 ', nwsl: '⚽ '};
  const PENDING = ['queued', 'running', 'blocked'];

  function holdText(hold) {
    if (hold.ending) return 'ending now';
    if (hold.cut) return 'until ' + (hold.cut.title || 'a higher-priority show') + ' cuts in at ' + fmt.clock(hold.until) + (hold.detail ? ' (' + hold.detail + ')' : '');
    if (hold.game) return 'until ' + (hold.game.title || 'the game') + ' ends' + (hold.detail ? ' (' + hold.detail + ')' : '');
    return 'until ' + (hold.program ? hold.program.title + ' ends · ' : '') + fmt.clock(hold.until);
  }
  const showTarget = t => (t?.source_id === 'mlb' ? 'MLB · automatic routing' : t?.source_id === 'sunday-ticket' ? 'NFL Sunday Ticket'
    : t?.source_id === 'thursday-night-football' ? 'Thursday Night Football · Prime Video'
    : t?.source_id === 'nhl' ? 'NHL on ESPN Unlimited · YouTube TV' : label(t)) + (t?.antenna === false ? ' · YouTube TV only' : '');
  // A network on YouTube TV waiting in Up next: the antenna takes over if YouTube TV is late.
  function antennaNote(item) {
    const n = VV.networkOf(item.target);
    if (!n || item.target.source_id !== 'youtube-tv') return null;
    return h('small', {class: 'muted'}, item.target.antenna === false ? 'YouTube TV only · waits for the Roku'
      : 'Antenna backup · ' + n.antenna.number + ' ' + n.antenna.name + ' if YouTube TV is not ready in time');
  }
  // A warm-up: what follows a program about to end, prepared on the Roku while it finishes.
  // Entries say so on their own row; this covers the schedule's block, which has none yet.
  function warmText(q) {
    const w = q.warm;
    if (!w || w.state === 'stopped' || q.items.some(i => PENDING.includes(i.status) && same(i.target, w.target))) return '';
    const name = w.title || showTarget(w.target);
    return w.state === 'ready' ? ' ' + name + ' is ready on the Roku for when ' + w.ends + ' ends.'
      : w.state === 'failed' ? ' Could not prepare ' + name + ' early (' + w.error + '); it is prepared when it goes on.'
      : ' Preparing ' + name + ' on the Roku while ' + w.ends + ' finishes.';
  }
  // Back to YouTube TV: a program on air from the antenna in its place, prepared on the Roku
  // beside it (the antenna stays on air until the cut).
  function upgradeText(q) {
    const u = q.upgrade;
    if (!u || u.state === 'stopped' || u.state === 'switched') return '';
    const name = label(u.target);
    return u.state === 'failed' ? ' Could not get ' + name + ' ready (' + u.error + '); staying on the antenna'
        + (u.retry ? ', trying again in 2 minutes.' : '.')
      : u.state === 'switching' ? ' Switching back to ' + name + '.'
      : ' Preparing ' + name + ' on the Roku; it replaces the antenna once ready.';
  }
  function antennaTaken(item) {
    const a = item.result?.antenna;
    return a ? h('small', 'From the antenna · ' + a.number + ' ' + a.name + ' (' + a.reason + ')') : null;
  }

  function mount(host, {compact = false, find = null} = {}) {
    const state = h('p', {id: 'queue-state', class: 'hint'});
    const toggle = h('button', {id: 'queue-toggle', type: 'button', class: 'sm'}, 'Resume');
    const change = h('button', {id: 'hold-change', type: 'button', class: 'sm', hidden: true}, icon(ICONS.clock), 'Change end time');
    const clear = h('button', {id: 'queue-clear', type: 'button', class: 'sm danger', hidden: true}, 'Clear');
    const lamp = h('span', {class: 'lamp'});
    const items = h('ol', {id: 'queue-items', class: 'rundown'});
    const error = h('p', {id: 'queue-error', class: 'note bad', role: 'status'});
    const help = h('details', {class: 'more', style: {margin: '0 16px 14px'}}, h('summary', 'How Up next works'),
      h('p', {class: 'hint', style: {marginTop: '8px'}}, 'Up next is the only way on air. ', h('strong', '▶ Play now'), ' goes to the front and cuts in once the source is ready. ',
        h('strong', '+ Add to queue'), ' plays after everything ahead of it. Live shows in the schedule still start on time, and a game holds master until it is final; then a game already under way, recordings waiting here, or the schedule follows. Preparing a source takes extra time: check late entries before resuming.'),
      h('p', {class: 'hint'}, 'The rundown is what will actually air: Up next and the schedule played forward under those rules, as on the Schedule page. Game ends are estimates; ',
        h('strong', 'Won’t air'), ' lists what the estimates leave out.'));
    const panel = h('section', {class: 'panel queue' + (compact ? ' compact' : ''), id: 'queue-panel', 'aria-label': 'Up next'},
      h('div', {class: 'head'}, lamp, h('h2', 'Up next'), h('div', {class: 'end'}, change, clear, toggle)),
      find, h('div', {class: 'body', style: {paddingBottom: '6px'}}, state, error), items, help);
    host.replaceChildren(panel);
    let queue = null, master = {}, playback = null, waiting = '';
    let wontOpen = false;  // The "Won't air" list stays open across renders once opened.

    async function act(path, body, method) {
      error.textContent = '';
      try { await api('v1/queue/' + path, body, {method}); VV.poke('v1/queue'); VV.poke('v1/master'); VV.poke('v1/playback'); }
      catch (e) { error.textContent = e.message; }
    }
    toggle.onclick = () => act(queue.paused ? 'resume' : 'pause', {});
    clear.onclick = async () => {
      const count = added().length;
      if (await VV.confirm('Remove the ' + count + ' ' + (count === 1 ? 'entry' : 'entries') + ' you added to Up next? Scheduled programs stay.', {title: 'Clear Up next', ok: 'Clear', danger: true}))
        act('clear', {});
    };
    change.onclick = () => OnAir.changeEnd({target: master.on_air || queue?.hold?.target, hold: queue?.hold, queue});
    const added = () => (queue?.items || []).filter(i => ['queued', 'blocked'].includes(i.status) && !['programming', 'manual_end'].includes(i.origin));

    function row(cls, time, body, actions, data) {
      return h('li', {class: 'q ' + cls, data}, h('div', {class: 'q-time mono'}, time), h('div', {class: 'q-body'}, body), actions ? h('div', {class: 'q-actions actions'}, actions) : null);
    }
    const divider = text => h('li', {class: 'q divider'}, h('div'), typeof text === 'string' ? h('div', {class: 'label'}, text) : text);
    // An entry's buttons: move and remove while it waits, retry (or tune anyway) once blocked.
    function entryActions(item) {
      const actions = [];
      const action = (text, verb, body = {}, cls = '') => {
        const b = h('button', {type: 'button', class: 'xs ' + cls, 'aria-label': text + ' ' + (item.title || item.program?.title || item.channel || label(item.target)), data: {action: verb + (body.direction || '')}}, text);
        b.onclick = () => act(item.id + '/' + verb, body); actions.push(b);
      };
      const remove = () => { const b = h('button', {type: 'button', class: 'xs danger', 'aria-label': 'Remove ' + (item.title || item.program?.title || item.channel || label(item.target)), data: {action: 'remove'}}, 'Remove');
        b.onclick = () => act(item.id, undefined, 'DELETE'); actions.push(b); };
      if (item.status === 'queued') { action('Move up', 'move', {direction: 'up'}); action('Move down', 'move', {direction: 'down'}); remove(); }
      if (item.status === 'blocked') { action('Retry', 'retry'); if (item.program) action('Tune channel anyway', 'tune-anyway'); remove(); }
      return actions.length ? actions : null;
    }
    // Why an entry was skipped; a blocked entry passed over keeps its failure in that line.
    const why = item => ['gave_way', 'superseded', 'cut', 'passed', 'over'].includes(item.gate_status) ? item.gate_detail
      : item.error?.message || (PENDING.includes(item.status) ? item.gate_detail : null);
    const statusChip = item => h('span', {class: 'chip ' + ({queued: 'touch', running: 'pgm', blocked: 'warn', failed: 'pgm', succeeded: 'pvw'}[item.status] || '')}, item.status);

    // An Up next entry as the queue holds it: what is going on now, what the projection has
    // not placed yet, and what already happened.
    function entryRow(item) {
      const media = item.target?.source_id === 'library' ? VV.libraryItem(item.target.channel_id) : null;
      const kind = media ? 'Recording · ' + (media.duration ? fmt.dur(media.duration) : 'length unknown') + adBreaks(item.target) : item.origin === 'programming' ? 'Schedule · ' + (item.title || 'Programming block')
        : item.origin === 'manual_end' ? 'After the manual take ends · the schedule is off' : item.tune_anyway ? 'Channel only · program requirement waived' : item.program?.title || 'Live channel';
      const end = item.hold_end, until = end?.game ? ' · until ' + (end.game.title || 'the game') + ' is final' : end?.until ? ' · until ' + fmt.clock(end.until) : '';
      const due = (item.run_at ? fmt.when(item.run_at) : item.release_type === 'after_current' ? 'After what is ahead of it' : 'After ' + (item.after_game_title || 'game')) + until;
      const missed = item.program?.end && item.program.end < Date.now() / 1000 && !item.tune_anyway;
      const late = item.program?.start < Date.now() / 1000 && !missed;
      const reason = why(item);
      const time = item.status === 'running' ? 'NOW' : item.run_at ? fmt.clock(item.run_at) : item.release_type === 'after_current' ? 'NEXT' : 'AFTER';
      return row('queue-entry ' + item.status + (media ? ' rec' : '') + (PENDING.includes(item.status) ? '' : ' past'), time,
        [h('strong', label(item.target)), h('small', kind), h('small', due + (item.release_type === 'scheduled_end' ? ' · scheduled end estimate' : '') + (item.kind === 'game' && item.status === 'queued' ? ' · holds master until final' : '')),
          h('div', {class: 'row', style: {gap: '6px', marginTop: '4px'}}, statusChip(item), missed ? h('span', {class: 'chip warn'}, 'missed') : late && item.status === 'queued' ? h('span', {class: 'chip warn'}, 'joins live') : null,
            reason ? h('small', {class: 'muted'}, reason) : null),
          item.result?.on_air?.resolved_source?.label ? h('small', 'Taken via ' + item.result.on_air.resolved_source.label) : null,
          PENDING.includes(item.status) ? antennaNote(item) : antennaTaken(item)],
        entryActions(item), {id: item.id});
    }

    /* The projection: what will air, in order --------------------------------------------- */
    const offAir = s => s.kind === 'off_air' || s.target?.source_id === 'off-air';
    const score = game => game && queue?.games?.[(game.league || 'mlb') + ':' + game.game_pk]?.summary;
    // Back-to-back OFF AIR (the schedule's own, then a gap) reads as one sign-off.
    function merged(segments) {
      const out = [];
      for (const s of segments) {
        const last = out.at(-1);
        if (last && offAir(last) && offAir(s) && last !== segments[0]) out[out.length - 1] = {...last, end: s.end};
        else out.push(s);
      }
      return out;
    }
    const approx = s => !!s && (s.estimated || (s.notes || []).includes('Length unknown'));
    // A show queued with ad breaks: My ads at each of its act breaks, about this long each.
    const adBreaks = target => target?.ad_breaks ? ' · ad breaks of ' + fmt.dur(target.ad_breaks) : '';
    function where(s) {
      if (s.kind === 'recording') {
        const media = s.target?.source_id === 'library' ? VV.libraryItem(s.target.channel_id) : null;
        return 'Recording · ' + (media?.duration ? fmt.dur(media.duration) : 'length unknown') + adBreaks(s.target);
      }
      return showTarget(s.target) + (s.kind === 'game' && score(s.game) ? ' · ' + score(s.game) : '');
    }
    function segmentRow(s, item, before) {
      const game = s.kind === 'game', guess = approx(before) ? '~' : '';
      const from = s.item ? (item?.origin === 'programming' ? 'Schedule · in Up next' : 'Up next') : s.source === 'recording' ? 'Up next' : 'Schedule';
      const cut = (s.notes || []).some(n => n.startsWith('Cut when'));
      const span = game && !cut ? 'until its final' + (s.estimated ? ', about ' + fmt.clock(s.end) : '')
        : fmt.clock(s.start) + '–' + (s.estimated || approx(s) ? '~' : '') + fmt.clock(s.end);
      // OFF AIR giving way is the projection's bookkeeping, not news on this page.
      const notes = (s.notes || []).filter(n => n !== 'Length unknown' && n !== 'Joins in progress' && !/OFF AIR/.test(n));
      const live = (s.notes || []).includes('Joins in progress');
      const chips = [item && item.status !== 'queued' ? statusChip(item) : null, live ? h('span', {class: 'chip warn'}, 'joins in progress') : null,
        item && item.status === 'blocked' && why(item) ? h('small', {class: 'muted'}, why(item)) : null].filter(Boolean);
      const name = (game ? ICON[s.game?.league || 'mlb'] || '' : '') + (s.title || label(s.target));
      return row('queue-entry proj ' + (item ? item.status : 'sched') + (game ? ' game' : '') + (s.kind === 'recording' ? ' rec' : ''), guess + fmt.clock(s.start),
        [h('strong', name), h('small', where(s)), h('small', [span, from, ...notes].join(' · ')),
          chips.length ? h('div', {class: 'row', style: {gap: '6px', marginTop: '4px'}}, chips) : null,
          item ? antennaNote(item) : null],
        item ? entryActions(item) : null, item ? {id: item.id} : null);
    }
    function offRow(s, before, last) {
      return row('queue-entry proj off', (approx(before) ? '~' : '') + fmt.clock(s.start), [h('strong', 'OFF AIR · test card'),
        h('small', last ? 'Nothing scheduled after it' : 'Until ' + fmt.when(s.end))]);
    }
    // What the estimates leave out: entries whose slot ends before what holds master does, OFF
    // AIR giving way, an entry outranked. OFF AIR itself is not listed: it never needs a hand.
    function wontRow(list) {
      const names = [...new Set(list.map(d => d.title || label(d.target)))];
      const details = h('details', {class: 'wont', open: wontOpen}, h('summary', h('strong', 'Won’t air · ' + list.length), ' ',
        h('small', {class: 'muted'}, names.slice(0, 3).join(', ') + (names.length > 3 ? '…' : ''))),
        h('ul', {class: 'wont-list'}, list.map(d => {
          const item = d.item ? queue.items.find(i => i.id === d.item) : null;
          return h('li', {data: item ? {id: item.id} : null}, h('span', {class: 'mono muted'}, d.due ? fmt.when(d.due) : '—'),
            h('span', h('strong', d.title || label(d.target)), h('small', {class: 'muted'}, d.why)), item ? h('span', {class: 'actions'}, entryActions(item)) : h('span'));
        })));
      details.ontoggle = () => { wontOpen = details.open; };
      return h('li', {class: 'q wont-row'}, h('div', {class: 'q-time mono'}, '—'), h('div', {class: 'q-body'}, details));
    }

    function render() {
      const q = queue;
      if (!q) return;
      if (!q.master_queue) { panel.hidden = true; return; }
      panel.hidden = false;
      const then = q.schedule_enabled ? 'the schedule' : 'OFF AIR';
      state.textContent = q.hold ? 'On air ' + holdText(q.hold) + ' · then ' + (q.hold.game ? 'a game under way, Up next recordings or ' : '') + then + (q.hold.ending ? '' : '. Up next waits until then.')
        : q.paused ? 'Paused · ' + (q.pause_reason || 'Ready when you are') : 'Running: Play now goes first; Add to queue plays after what is ahead of it.';
      state.textContent += warmText(q) + upgradeText(q);
      lamp.className = 'lamp ' + (q.paused && !q.hold ? 'warn' : q.hold ? 'pgm' : 'pvw');
      toggle.replaceChildren(q.hold ? (q.schedule_enabled ? 'Return to schedule now' : 'End now · OFF AIR') : q.paused ? 'Resume queue' : 'Pause queue');
      toggle.className = 'sm ' + (q.paused && !q.hold ? 'primary' : '');
      toggle.disabled = !!q.hold?.ending;
      const liveOn = master.on_air && !['library', 'ident'].includes(master.on_air.source_id);
      change.hidden = q.hold ? !!q.hold.ending : !liveOn;
      change.lastChild.textContent = q.hold ? 'Change end time' : 'Set end time';
      const extra = added();
      clear.hidden = !extra.length; clear.textContent = 'Clear (' + extra.length + ')';
      const byId = new Map(q.items.map(i => [i.id, i]));
      const pending = q.items.filter(i => PENDING.includes(i.status));
      const history = q.items.filter(i => !PENDING.includes(i.status)).slice(0, 3);
      const focused = document.activeElement, focusEntry = focused?.closest('[data-id]')?.dataset.id, focusAction = focused?.dataset.action;
      items.replaceChildren();
      const connected = !['not_configured', 'unavailable', undefined].includes(master.state), onAir = q.master_on_air ?? master.on_air;
      const playing = ['library', 'ident'].includes(onAir?.source_id) ? onAir.media : null;
      const segments = merged(playback?.segments || []), current = segments[0];
      // The first segment is what is on now, and says how it ends; unless an entry due now
      // already replaces it (the projection then starts with that entry).
      const nowSeg = current && (onAir ? same(onAir, current.target) : offAir(current)) ? current : null;
      if (connected) {
        const aired = onAir && q.items.find(i => i.status === 'succeeded' && same(i.target, onAir));
        const game = aired?.game, live = (q.hold?.game && same(onAir, q.hold.target) && q.hold.detail) || score(game);
        const next = segments.slice(1).find(s => !offAir(s));
        const ends = nowSeg && playback && nowSeg.end < playback.until ? (nowSeg.estimated ? 'until about ' : 'until ') + fmt.when(nowSeg.end) : '';
        const detail = !onAir ? (next ? 'Test card until ' + (next.title || label(next.target)) + ' at ' + fmt.when(next.start) : 'Nothing scheduled')
          : playing ? fmt.dur(playing.position_seconds) + ' / ' + fmt.dur(playing.duration_seconds)
          : [(aired?.origin === 'programming' ? 'Schedule · ' + (aired.title || 'Programming block') : aired?.program?.title || game?.title || 'Live'), live, ends].filter(Boolean).join(' · ');
        const body = [h('span', {class: 'label', style: {color: onAir ? 'var(--pgm)' : 'var(--muted)'}}, onAir ? 'On air now' : 'Off air'), h('strong', label(onAir)), h('small', detail)];
        if (playing?.duration_seconds) body.push(h('div', {class: 'meter pgm', style: {marginTop: '6px'}}, h('i', {style: {width: Math.min(100, 100 * (playing.position_seconds || 0) / playing.duration_seconds) + '%'}})));
        items.append(row(onAir ? 'queue-on-air live' : 'queue-on-air off', onAir ? h('span', {class: 'lamp pgm'}) : h('span', {class: 'lamp'}), body));
      }
      // Going on now: an entry being prepared and taken.
      for (const item of pending.filter(i => i.status === 'running')) items.append(entryRow(item));
      // Then what will air. Every entry the projection places is accounted for, shown or not.
      const placed = new Set(segments.map(s => s.item).filter(Boolean));
      const limit = compact ? 3 : 8;
      let shown = 0, more = 0, before = nowSeg, day = new Date().toDateString();
      const rest = segments.slice(nowSeg ? 1 : 0);
      rest.forEach((s, index) => {
        const item = s.item ? byId.get(s.item) : null;
        if (item && !PENDING.includes(item.status)) return;  // Aired since the projection was made.
        if (item?.status === 'running') return;
        if (shown >= limit) { if (!offAir(s)) more++; return; }
        const date = new Date(s.start).toDateString();
        if (date !== day) { day = date; items.append(divider(fmt.day(s.start))); }
        items.append(offAir(s) ? offRow(s, before, index === rest.length - 1) : segmentRow(s, item, before));
        if (!offAir(s)) shown++;
        before = s;
      });
      if (!rest.length && !pending.length) items.append(h('li', {class: 'q empty'}, h('div', {class: 'q-time'}), h('div', {class: 'q-body hint'},
        find ? 'Nothing waiting. Search above, or use ▶ Play now or + Add to queue beside a channel, game or recording.' : 'Nothing waiting. Use ▶ Play now or + Add to queue beside a channel, game or recording.')));
      if (more) items.append(divider(h('a', {class: 'tiny', href: 'schedule'}, more + ' more in the next day on the Schedule →')));
      // Waiting entries the projection has not placed: just added (it catches up in seconds),
      // or due after its horizon.
      const dropped = (playback?.dropped || []).filter(d => !offAir(d) && (!d.item || PENDING.includes(byId.get(d.item)?.status)));
      const left = new Set(dropped.map(d => d.item).filter(Boolean));
      const unplaced = pending.filter(i => i.status !== 'running' && !placed.has(i.id) && !left.has(i.id) && !(i.target?.source_id === 'off-air' && playback));
      if (unplaced.length) {
        items.append(divider(playback ? 'Also waiting' : 'Waiting'));
        unplaced.forEach(item => items.append(entryRow(item)));
      }
      if (dropped.length) items.append(wontRow(dropped));
      // Scheduled games and shows after the projection's day.
      const horizon = playback ? Date.parse(playback.until) : Infinity;
      const later = (q.scheduled_shows || []).filter(s => Date.parse(s.start) >= horizon).slice(0, compact ? 2 : 4);
      if (later.length) {
        items.append(divider('Later'));
        for (const show of later) {
          const game = show.mode === 'game';
          items.append(row('queue-entry queue-next sched' + (game ? ' game' : ''), fmt.clock(show.start), [h('strong', (game ? ICON[show.game?.league] || '' : '') + show.title),
            h('small', showTarget(show.target) + ' · ' + sameDayText(show.start) + fmt.clock(show.start) + '–' + fmt.clock(show.end)),
            h('small', game ? 'Holds master until final' + (show.backup?.source_id === 'schedule' ? '' : ' · then ' + show.backup_title + ' · ' + label(show.backup)) : 'Scheduled show · overrides the grid')],
            null, {show: show.id}));
        }
      }
      if (history.length) {
        items.append(divider('Earlier'));
        history.forEach(item => items.append(entryRow(item)));
      }
      if (focusEntry && focusAction) [...items.querySelectorAll('[data-id]')].find(e => e.dataset.id === focusEntry)?.querySelector('[data-action="' + focusAction + '"]')?.focus({preventScroll: true});
    }
    const sameDayText = iso => new Date(iso).toDateString() === new Date().toDateString() ? '' : fmt.day(iso) + ' ';
    VV.networks().then(render);
    VV.watch('v1/queue', 2000, (data, w) => {
      if (w.error) { if (w.error.status !== 401) error.textContent = w.error.message; return; }
      error.textContent = ''; queue = data;
      // What waits changed (added, removed, taken): the projection is worked out again now.
      const key = data.items.filter(i => PENDING.includes(i.status)).map(i => i.id + i.status).join() + '|' + JSON.stringify(data.hold?.id || null);
      if (waiting && key !== waiting) VV.poke('v1/playback');
      waiting = key; render();
    });
    // A server from before the projection named its entries (no `dropped`) lists Up next as it holds it.
    VV.watch('v1/playback', 10000, (data, w) => { if (!w.error) { playback = Array.isArray(data?.dropped) ? data : null; render(); } });
    VV.watch('v1/master', 2000, (data, w) => { if (!w.error) { master = data; render(); } });
    return {render, get queue() { return queue; }};
  }
  return {mount, holdText};
})();
