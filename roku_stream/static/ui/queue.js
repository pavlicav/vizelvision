// Up next: the rundown. The only way on air; what is on master heads it, then what waits
// (Play now at the front, Add to queue at the back), then what the schedule brings.
//   UpNext.mount(host, {compact, find}) → {render}; find is an element (Find.box()) put under the head.
window.UpNext = (() => {
  'use strict';
  const {h, api, fmt, toast, label, same, icon, ICONS} = VV;
  const ICON = {nfl: '🏈 ', ncaaf: '🏈 ', mlb: '⚾ ', nba: '🏀 ', nhl: '🏒 ', wnba: '🏀 ', nwsl: '⚽ '};
  const PENDING = ['queued', 'running', 'blocked'];

  function holdText(hold) {
    if (hold.ending) return 'ending now';
    if (hold.game) return 'until ' + (hold.game.title || 'the game') + ' ends' + (hold.detail ? ' (' + hold.detail + ')' : '');
    return 'until ' + (hold.program ? hold.program.title + ' ends · ' : '') + fmt.clock(hold.until);
  }
  const showTarget = t => (t?.source_id === 'mlb' ? 'MLB · automatic routing' : t?.source_id === 'sunday-ticket' ? 'NFL Sunday Ticket'
    : t?.source_id === 'thursday-night-football' ? 'Thursday Night Football · Prime Video' : label(t)) + (t?.antenna === false ? ' · YouTube TV only' : '');
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
        h('strong', '+ Add to queue'), ' plays after everything ahead of it. Live shows in the schedule still start on time, and a game holds master until it is final; then a game already under way, recordings waiting here, or the schedule follows. Preparing a source takes extra time: check late entries before resuming.'));
    const panel = h('section', {class: 'panel queue' + (compact ? ' compact' : ''), id: 'queue-panel', 'aria-label': 'Up next'},
      h('div', {class: 'head'}, lamp, h('h2', 'Up next'), h('div', {class: 'end'}, change, clear, toggle)),
      find, h('div', {class: 'body', style: {paddingBottom: '6px'}}, state, error), items, help);
    host.replaceChildren(panel);
    let queue = null, master = {};

    async function act(path, body, method) {
      error.textContent = '';
      try { await api('v1/queue/' + path, body, {method}); VV.poke('v1/queue'); VV.poke('v1/master'); }
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
      const pending = q.items.filter(i => PENDING.includes(i.status));
      const history = q.items.filter(i => !PENDING.includes(i.status)).slice(0, compact ? 3 : 5);
      const focused = document.activeElement, focusEntry = focused?.closest('.queue-entry')?.dataset.id, focusAction = focused?.dataset.action;
      items.replaceChildren();
      const next = ['game', 'show'].includes(q.next_scheduled?.kind) ? null : q.next_scheduled, scheduled = q.scheduled_shows || [];
      const connected = !['not_configured', 'unavailable', undefined].includes(master.state), onAir = q.master_on_air ?? master.on_air;
      const playing = ['library', 'ident'].includes(onAir?.source_id) ? onAir.media : null;
      const upcoming = [next?.target?.source_id === 'off-air' ? null : next?.run_at, ...scheduled.map(s => s.start)].filter(Boolean).map(Date.parse).sort((a, b) => a - b)[0];
      if (connected) {
        const aired = onAir && q.items.find(i => i.status === 'succeeded' && same(i.target, onAir));
        const game = aired?.game, score = (q.hold?.game && same(onAir, q.hold.target) && q.hold.detail) || (game && q.games?.[(game.league || 'mlb') + ':' + game.game_pk]?.summary);
        const detail = !onAir ? (pending.length ? 'Test card until the next entry' : upcoming ? 'Nothing scheduled until ' + fmt.full(upcoming) : 'Nothing scheduled')
          : playing ? fmt.dur(playing.position_seconds) + ' / ' + fmt.dur(playing.duration_seconds)
          : (aired?.origin === 'programming' ? 'Schedule · ' + (aired.title || 'Programming block') : aired?.program?.title || game?.title || 'Live') + (score ? ' · ' + score : '');
        const body = [h('span', {class: 'label', style: {color: onAir ? 'var(--pgm)' : 'var(--muted)'}}, onAir ? 'On air now' : 'Off air'), h('strong', label(onAir)), h('small', detail)];
        if (playing?.duration_seconds) body.push(h('div', {class: 'meter pgm', style: {marginTop: '6px'}}, h('i', {style: {width: Math.min(100, 100 * (playing.position_seconds || 0) / playing.duration_seconds) + '%'}})));
        items.append(row(onAir ? 'queue-on-air live' : 'queue-on-air off', onAir ? h('span', {class: 'lamp pgm'}) : h('span', {class: 'lamp'}), body));
      }
      if (!pending.length) items.append(h('li', {class: 'q empty'}, h('div', {class: 'q-time'}), h('div', {class: 'q-body hint'},
        find ? 'Nothing waiting. Search above, or use ▶ Play now or + Add to queue beside a channel, game or recording.' : 'Nothing waiting. Use ▶ Play now or + Add to queue beside a channel, game or recording.')));
      const last = pending.at(-1)?.target || onAir, fileEnd = !pending.length && playing?.duration_seconds ? Date.now() + (playing.duration_seconds - (playing.position_seconds || 0)) * 1000 : null;
      const offAfter = connected && ['library', 'ident'].includes(last?.source_id) && (!upcoming || (fileEnd && upcoming > fileEnd));
      const showNext = () => {
        if (offAfter) items.append(row('queue-off-air off', 'THEN', [h('strong', 'OFF AIR · test card'),
          h('small', (last.source_id === 'ident' ? 'When the station ID ends' : 'When the ' + (pending.length ? 'last ' : '') + 'recording ends') + ' · nothing scheduled after it')]));
        if (next) {
          const off = next.target?.source_id === 'off-air';
          items.append(row('queue-entry queue-next sched', fmt.clock(next.run_at), [h('span', {class: 'label'}, 'Next scheduled'), h('strong', off ? 'OFF AIR · test card' : next.title),
            off ? null : h('small', label(next.target)),
            h('small', (next.skip_after ? 'until ' + fmt.clock(next.skip_after) + ' · ' : '') + (off ? 'Nothing scheduled then · joins Up next shortly before' : 'From the schedule · joins Up next shortly before it starts'))]));
        }
        if (!scheduled.length) return;
        items.append(h('li', {class: 'q divider'}, h('div'), h('div', {class: 'label'}, 'Scheduled games and shows')));
        for (const show of scheduled.slice(0, compact ? 3 : 6)) {
          const game = show.mode === 'game';
          items.append(row('queue-entry queue-next sched' + (game ? ' game' : ''), fmt.clock(show.start), [h('strong', (game ? ICON[show.game?.league] || '' : '') + show.title),
            h('small', showTarget(show.target) + ' · ' + (sameDayText(show.start)) + fmt.clock(show.start) + '–' + fmt.clock(show.end)),
            h('small', game ? 'Holds master until final' + (show.backup?.source_id === 'schedule' ? '' : ' · then ' + show.backup_title + ' · ' + label(show.backup)) : 'Scheduled show · overrides the grid')],
            null, {show: show.id}));
        }
        if (scheduled.length > (compact ? 3 : 6)) items.append(h('li', {class: 'q divider'}, h('div'), h('a', {class: 'tiny', href: 'schedule'}, (scheduled.length - (compact ? 3 : 6)) + ' more on the Schedule →')));
      };
      if (pending.length || history.length) items.append(h('li', {class: 'q divider'}, h('div'), h('div', {class: 'label'}, pending.length ? 'Waiting' : 'Earlier')));
      for (const item of [...pending, ...history]) {
        if (item === history[0]) { showNext(); items.append(h('li', {class: 'q divider'}, h('div'), h('div', {class: 'label'}, 'Earlier'))); }
        const media = item.target?.source_id === 'library' ? VV.libraryItem(item.target.channel_id) : null;
        const kind = media ? 'Recording · ' + (media.duration ? fmt.dur(media.duration) : 'length unknown') : item.origin === 'programming' ? 'Schedule · ' + (item.title || 'Programming block')
          : item.origin === 'manual_end' ? 'After the manual take ends · the schedule is off' : item.tune_anyway ? 'Channel only · program requirement waived' : item.program?.title || 'Live channel';
        const end = item.hold_end, until = end?.game ? ' · until ' + (end.game.title || 'the game') + ' is final' : end?.until ? ' · until ' + fmt.clock(end.until) : '';
        const due = (item.run_at ? fmt.when(item.run_at) : item.release_type === 'after_current' ? 'After what is ahead of it' : 'After ' + (item.after_game_title || 'game')) + until;
        const missed = item.program?.end && item.program.end < Date.now() / 1000 && !item.tune_anyway;
        const late = item.program?.start < Date.now() / 1000 && !missed;
        const why = item.error?.message || (PENDING.includes(item.status) || ['gave_way', 'superseded'].includes(item.gate_status) ? item.gate_detail : null);
        const status = h('span', {class: 'chip ' + ({queued: 'touch', running: 'pgm', blocked: 'warn', failed: 'pgm', succeeded: 'pvw'}[item.status] || '')}, item.status);
        const actions = [];
        const action = (text, verb, body = {}, cls = '') => {
          const b = h('button', {type: 'button', class: 'xs ' + cls, 'aria-label': text + ' ' + (item.program?.title || item.channel), data: {action: verb + (body.direction || '')}}, text);
          b.onclick = () => act(item.id + '/' + verb, body); actions.push(b);
        };
        const remove = () => { const b = h('button', {type: 'button', class: 'xs danger', 'aria-label': 'Remove ' + (item.program?.title || item.channel), data: {action: 'remove'}}, 'Remove');
          b.onclick = () => act(item.id, undefined, 'DELETE'); actions.push(b); };
        if (item.status === 'queued') { action('Move up', 'move', {direction: 'up'}); action('Move down', 'move', {direction: 'down'}); remove(); }
        if (item.status === 'blocked') { action('Retry', 'retry'); if (item.program) action('Tune channel anyway', 'tune-anyway'); remove(); }
        const time = item.run_at ? fmt.clock(item.run_at) : item.release_type === 'after_current' ? 'NEXT' : 'AFTER';
        items.append(row('queue-entry ' + item.status + (media ? ' rec' : '') + (PENDING.includes(item.status) ? '' : ' past'), time,
          [h('strong', label(item.target)), h('small', kind), h('small', due + (item.release_type === 'scheduled_end' ? ' · scheduled end estimate' : '') + (item.kind === 'game' && item.status === 'queued' ? ' · holds master until final' : '')),
            h('div', {class: 'row', style: {gap: '6px', marginTop: '4px'}}, status, missed ? h('span', {class: 'chip warn'}, 'missed') : late && item.status === 'queued' ? h('span', {class: 'chip warn'}, 'joins live') : null,
              why ? h('small', {class: 'muted'}, why) : null),
            item.result?.on_air?.resolved_source?.label ? h('small', 'Taken via ' + item.result.on_air.resolved_source.label) : null,
            PENDING.includes(item.status) ? antennaNote(item) : antennaTaken(item)],
          actions.length ? actions : null, {id: item.id}));
      }
      if (!history.length) showNext();
      if (focusEntry && focusAction) [...items.children].find(e => e.dataset.id === focusEntry)?.querySelector('[data-action="' + focusAction + '"]')?.focus({preventScroll: true});
    }
    const sameDayText = iso => new Date(iso).toDateString() === new Date().toDateString() ? '' : fmt.day(iso) + ' ';
    VV.networks().then(render);
    VV.watch('v1/queue', 2000, (data, w) => { if (w.error) { if (w.error.status !== 401) error.textContent = w.error.message; return; } error.textContent = ''; queue = data; render(); });
    VV.watch('v1/master', 2000, (data, w) => { if (!w.error) { master = data; render(); } });
    return {render, get queue() { return queue; }};
  }
  return {mount, holdText};
})();
