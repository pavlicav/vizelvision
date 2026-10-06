// Sources: every channel, game and recording, with the three ways on air beside each.
(() => {
  'use strict';
  const {h, api, fmt, toast, label, same, ROKU} = VV;
  const id = name => document.getElementById(name);
  const state = {sources: [], programs: VV.known.programs, filter: VV.store.get('sourcesFilter', 'all'), query: '', busy: false, master: {}, queue: null};
  const isRoku = sid => ROKU.includes(sid);
  const matchesSource = sid => state.filter === 'all' || state.filter === sid || (state.filter === 'roku' && isRoku(sid));
  UpNext.mount(id('queue-host'), {compact: true});
  OnAir.configure({refresh: async () => {}});

  // What a row puts on air: OnAir names channels, games, programs and recordings alike.
  const {guideItem, recordingItem} = OnAir;

  function sourceGroups() {
    const groups = state.sources.filter(s => !isRoku(s.id)), roku = state.sources.filter(s => isRoku(s.id));
    if (roku.length) groups.push({id: 'roku', name: 'Roku', configured: roku.some(s => s.configured), availability: roku.filter(s => s.configured).map(s => s.name).join(' · ')});
    return groups;
  }
  function selectedTarget(group, select) {
    if (group.id === 'roku') { try { return JSON.parse(select.value); } catch { return null; } }
    return {source_id: group.id, channel_id: select.value};
  }
  function cardItem(group, select) {
    const target = selectedTarget(group, select); if (!target) return null;
    const source = state.sources.find(s => s.id === target.source_id), data = state.programs.get(target.source_id);
    const channel = data?.channels?.find(c => String(c.id) === String(target.channel_id));
    return source && channel ? guideItem(source, channel, data) : null;
  }

  /* The source list ------------------------------------------------------------------------------------- */
  function renderNav() {
    const nav = id('sources'); nav.replaceChildren();
    for (const s of [{id: 'all', name: 'All sources', availability: 'Everything'}, ...sourceGroups(), {id: 'sports', name: 'Sports', availability: 'Games by league'}]) {
      const b = h('button', {type: 'button', 'aria-pressed': String(s.id === state.filter), data: {source: s.id}}, h('strong', s.name), h('small', s.configured === false ? 'Not configured' : s.availability || ''));
      b.onclick = () => { state.filter = s.id; VV.store.set('sourcesFilter', s.id); renderNav(); renderGuide(); renderCards(); };
      nav.append(b);
    }
  }

  /* Source cards: a channel picker and a live preview per source ------------------------------------------- */
  const cards = new Map();
  function stopInput(card) {
    card.generation++; if (card.player) { card.player.destroy(); card.player = null; }
    card.video.pause(); card.video.removeAttribute('src'); card.video.load(); card.key = null; card.started = 0;
  }
  async function startInput(card, target) {
    stopInput(card); card.key = target.id; const mine = card.generation;
    card.status.textContent = 'Loading source preview…';
    try {
      const player = await VV.play(card.video, 'v1/inputs/' + encodeURIComponent(target.id) + '/media/index.m3u8',
        {backBufferLength: 0, maxBufferLength: 4, maxMaxBufferLength: 8, liveSyncDurationCount: 1});
      if (card.generation !== mine) { player.destroy(); return; }
      card.player = player;
      player.on?.(window.Hls?.Events.ERROR, (_e, data) => { if (data.fatal && card.generation === mine) { stopInput(card); card.failed = target.id; card.status.textContent = 'Preview unavailable · retry'; renderCards(); } });
      player.on?.(window.Hls?.Events.MANIFEST_PARSED, () => { if (card.generation === mine) card.video.play().catch(() => { card.status.textContent = 'Press play to preview'; }); });
    } catch (e) { if (card.generation === mine) { card.status.textContent = e.message; card.failed = target.id; } }
  }
  function renderCards() {
    const sports = state.filter === 'sports';
    id('source-cards').hidden = sports;
    for (const group of sourceGroups().filter(s => s.configured && s.id !== 'library')) {
      const roku = group.id === 'roku';
      let card = cards.get(group.id);
      if (!card) {
        const select = h('select', {'aria-label': roku ? 'Roku channel or game' : group.name + ' channel'});
        const play = h('button', {class: 'take sm', type: 'button', 'aria-label': 'Play the selected ' + group.name + ' channel now'}, '▶ Play now');
        const queue = h('button', {class: 'sm', type: 'button', 'aria-label': 'Add the selected ' + group.name + ' channel to the queue'}, '+ Add to queue');
        const retry = h('button', {class: 'sm quiet', type: 'button'}, 'Retry preview');
        const status = h('small', {class: 'tiny muted', role: 'status'}, 'Preview idle');
        const video = h('video', {controls: true, muted: true, playsInline: true, hidden: true, 'aria-label': group.name + ' source preview'});
        const lamp = h('span', {class: 'lamp'}), note = h('p', {class: 'small muted'});
        const offAir = TestCard.create(roku ? 'roku' : group.id);
        const known = roku ? h('p', {class: 'tiny muted'}) : null;
        const root = h('article', {class: 'panel input-card', data: {source: group.id}},
          h('div', {class: 'head'}, lamp, h('h2', group.name)),
          h('div', {class: 'body stack tight'}, select, h('div', {class: 'screen'}, offAir, video), status, note, known, h('div', {class: 'actions'}, play, queue, retry)));
        card = {root, select, play, queue, retry, video, status, offAir, lamp, note, known, generation: 0, key: null, failed: null, signature: null, started: 0};
        cards.set(group.id, card); id('source-cards').append(root);
        play.onclick = () => { const item = cardItem(group, select); if (item) OnAir.open(item, {action: 'now'}); };
        queue.onclick = async () => { const item = cardItem(group, select); if (!item) return; queue.disabled = true; try { await OnAir.add(item); } catch (e) { toast(e.message, {error: true}); } finally { queue.disabled = false; } };
        select.onchange = () => renderCards();
        retry.onclick = () => { card.failed = null; stopInput(card); renderCards(); };
        video.addEventListener('timeupdate', () => { card.started = Date.now(); status.textContent = 'Previewing · ' + (video.muted ? 'muted' : 'listening'); });
        video.addEventListener('volumechange', () => { if (!video.muted) document.querySelectorAll('video').forEach(v => { if (v !== video) v.muted = true; }); });
      }
      const providers = roku ? state.sources.filter(s => isRoku(s.id) && s.configured) : [group];
      const choices = providers.flatMap(provider => {
        const data = state.programs.get(provider.id);
        return (data?.channels || []).map(c => ({label: (c.number ? c.number + ' · ' : '') + c.name, provider: provider.name,
          target: {source_id: provider.id, channel_id: String(c.id), ...(['mlb', 'sunday-ticket', 'thursday-night-football'].includes(provider.id) && data.date ? {date: data.date} : {})}}));
      });
      const signature = JSON.stringify(choices);
      if (signature !== card.signature) {
        const old = card.select.value; card.select.replaceChildren(); let optgroup;
        for (const choice of choices) {
          if (roku && optgroup?.label !== choice.provider) { optgroup = h('optgroup'); optgroup.label = choice.provider; card.select.append(optgroup); }
          const option = new Option(choice.label, roku ? JSON.stringify(choice.target) : choice.target.channel_id);
          (roku ? optgroup : card.select).append(option);
        }
        if ([...card.select.options].some(o => o.value === old)) card.select.value = old;
        else if (roku) { const current = state.master.roku_last_prepared?.target || state.master.prepared || state.master.on_air; const match = choices.find(c => same(c.target, current)); if (match) card.select.value = JSON.stringify(match.target); }
        card.signature = signature;
      }
      const belongs = target => roku ? isRoku(target?.source_id) : target?.source_id === group.id;
      const prepared = belongs(state.master.prepared) ? state.master.prepared : null;
      const onAir = belongs(state.master.on_air) ? state.master.on_air : null;
      const target = prepared || onAir;
      card.root.hidden = !matchesSource(group.id) || state.filter === 'sports';
      card.queue.hidden = card.play.hidden = !state.queue?.master_queue; card.queue.disabled = card.play.disabled = !choices.length;
      card.root.dataset.live = String(!!onAir);
      card.lamp.className = 'lamp ' + (onAir ? 'pgm' : prepared ? 'pvw' : '');
      card.note.textContent = target ? (prepared ? 'Prepared for Up next · ' : 'On master · ') + label(target)
        : state.master.operation?.state === 'pending' && belongs(state.master.operation.target) ? 'Preparing for Up next…'
        : roku ? 'One Roku: ' + providers.map(p => p.name).join(', ') + ' share this preview.' : 'Choose a channel, then play it now or add it to the queue.';
      if (roku) {
        const known = state.master.roku_last_prepared, selected = selectedTarget(group, card.select);
        const recent = known?.reusable && Date.now() / 1000 - known.prepared_at >= 0 && Date.now() / 1000 - known.prepared_at <= known.max_age_seconds;
        card.known.textContent = known ? 'Last known: ' + label(known.target) + ' · verified ' + fmt.when(known.prepared_at) + (!recent ? ' · ' + (known.reason || 'expired') : same(selected, known.target) ? ' · queuing it reuses this without navigating' : '') : 'No verified Roku state yet.';
      }
      if (!target || card.root.hidden) { if (card.key) stopInput(card); card.video.hidden = true; card.status.textContent = target ? 'Preview hidden' : 'Preview idle · shows while Up next prepares it or it is on master'; }
      else { card.video.hidden = false; if (card.key !== target.id && card.failed !== target.id) startInput(card, target); }
      card.offAir.hidden = !!target;
      card.retry.hidden = !target || card.failed !== target.id;
    }
    renderRoku();
  }
  setInterval(() => { for (const card of cards.values()) if (card.key && card.started && Date.now() - card.started > 3000) card.status.textContent = card.video.paused ? 'Preview paused' : 'Preview buffering…'; }, 1000);
  window.addEventListener('pagehide', () => { for (const c of cards.values()) stopInput(c); if (rokuTimer) clearInterval(rokuTimer); });

  /* Roku: TV Thing's Roku lane since 2026-10-06 -------------------------------------------------------------- */
  // The Roku's live picture (menus and all), its remote and its calibration are on TV Thing; this panel
  // says what the Roku is doing for master control and links there.
  let rokuPanel = null, rokuTimer = null;
  const tvThing = path => location.protocol + '//' + location.hostname + '/tv/' + path;
  function buildRoku() {
    const status = h('p', {class: 'small muted', id: 'roku-live-detail', role: 'status'}, 'Asking TV Thing…');
    const stop = h('button', {class: 'sm danger', type: 'button', id: 'stop-roku', hidden: true}, 'Stop');
    rokuPanel = h('section', {class: 'panel', id: 'roku-live', 'aria-label': 'The Roku in TV Thing'},
      h('div', {class: 'head'}, h('span', {class: 'lamp', id: 'roku-lamp'}), h('h2', 'Roku · TV Thing'),
        h('div', {class: 'end'}, stop, h('a', {class: 'btn sm', href: tvThing('#roku'), target: '_blank', rel: 'noopener'}, 'Watch and drive it →'))),
      h('div', {class: 'body stack tight'}, status,
        h('p', {class: 'tiny muted'}, 'TV Thing shows the Roku live, menus and all, with a remote and its own lock; its calibration is on ',
          h('a', {href: tvThing('roku.html'), target: '_blank', rel: 'noopener'}, 'TV Thing’s Roku page'), '.')));
    id('roku-host').append(rokuPanel);
    stop.onclick = async () => { try { await api('v1/operation/cancel', {}); loadRoku(); } catch (e) { status.textContent = e.message; } };
  }
  async function loadRoku() {
    try {
      const op = await api('v1/operation');
      const who = op.lock ? ' · held by ' + op.lock.owner : '';
      id('roku-live-detail').textContent = (op.active ? 'Navigating: ' + (op.message || op.phase) : op.selection?.manual ? 'Manual Roku (someone is using the remote)'
        : op.selection ? 'Showing ' + label({source_id: op.selection.source_id, channel_id: op.selection.channel_id}) : op.message || 'Roku idle') + who;
      id('roku-lamp').className = 'lamp ' + (op.active ? 'warn blink' : op.selection && !op.selection.manual ? 'pvw' : '');
      id('stop-roku').hidden = !op.active;
    } catch (e) { id('roku-live-detail').textContent = e.message; }
  }
  function renderRoku() {
    const configured = state.sources.some(s => isRoku(s.id) && s.configured);
    if (configured && !rokuPanel) buildRoku();
    if (!rokuPanel) return;
    const visible = state.sources.some(s => isRoku(s.id) && s.configured && matchesSource(s.id)) && state.filter !== 'sports' && state.filter !== 'all';
    const pending = state.master.operation?.state === 'pending' ? state.master.operation.target : null;
    const selecting = pending && isRoku(pending.source_id);
    rokuPanel.hidden = !(visible || selecting);
    if (!rokuPanel.hidden && !rokuTimer) { loadRoku(); rokuTimer = setInterval(() => { if (!document.hidden) loadRoku(); }, 3000); }
    else if (rokuPanel.hidden && rokuTimer) { clearInterval(rokuTimer); rokuTimer = null; }
  }

  /* The guide ------------------------------------------------------------------------------------------- */
  let sportsView = null;
  const PREVIEW_ROWS = 8, expanded = new Set();
  function programCell(program, title, source, channel, data) {
    const cell = h('div', {class: 'prog'}, h('span', {class: 'label'}, title));
    if (!program) { cell.append(h('small', 'Listings unavailable')); return cell; }
    cell.append(h('strong', program.title), h('small', fmt.when(program.start) + (program.end ? ' – ' + fmt.clock(program.end) : '')));
    if (program.status) cell.append(h('small', program.status));
    if (program.preferred_source) cell.append(h('small', 'Suggested source: ' + (program.preferred_source.label || program.preferred_source.provider)));
    if (program.end && program.start <= Date.now() / 1000 && program.end > Date.now() / 1000)
      cell.append(h('div', {class: 'meter'}, h('i', {style: {width: 100 * (Date.now() / 1000 - program.start) / (program.end - program.start) + '%'}})));
    if (state.queue?.master_queue && source && program.id && !channel.game && program.start > Date.now() / 1000) cell.append(OnAir.buttons(guideItem(source, channel, data, program)));
    return cell;
  }
  function renderGuide() {
    const sports = state.filter === 'sports';
    id('sports-view').hidden = !sports; id('search').hidden = sports;
    if (sports) {
      id('heading').textContent = 'Sports'; id('guide').replaceChildren();
      if (!sportsView && state.queue) { sportsView = OnAir.sports(id('sports-view')); sportsView.load(); }
      return;
    }
    id('heading').textContent = state.filter === 'all' ? 'All sources' : sourceGroups().find(s => s.id === state.filter)?.name || 'Sources';
    const guide = id('guide'); guide.replaceChildren();
    for (const source of state.sources.filter(s => matchesSource(s.id))) {
      const data = state.programs.get(source.id);
      const head = h('div', {class: 'head guide-head'}, h('h2', source.name));
      const body = h('div', {class: 'body flush'});
      const section = h('section', {class: 'panel source', data: {source: source.id}}, head, body);
      guide.append(section);
      if (source.selection) head.append(h('small', {class: 'muted'}, 'Tuner: ' + (source.selection.name || source.selection.number || 'unknown')));
      if (!source.configured) { body.append(h('p', {class: 'hint', style: {padding: '14px 16px'}}, 'Not configured.')); continue; }
      if (!data) { body.append(h('p', {class: 'hint', style: {padding: '14px 16px'}}, 'Loading listings…')); continue; }
      if (source.id === 'library') { renderLibrary(head, body, data); continue; }
      const warnings = [data.error, data.stale ? 'Showing cached listings: the source could not be refreshed.' : null, ...(data.warnings || [])].filter(Boolean);
      if (warnings.length) body.append(h('div', {style: {padding: '10px 16px'}}, warnings.map(w => h('p', {class: 'note warn small'}, w))));
      if (data.guide?.generated_at) head.append(h('small', {class: 'muted'}, 'Guide ' + fmt.when(data.guide.generated_at) + (Number.isFinite(data.guide.coverage_hours) ? ' · ' + data.guide.coverage_hours.toFixed(1) + ' h ahead' : '')));
      const all = (data.channels || []).filter(c => [c.name, c.number, c.now?.title, c.game?.title, ...(c.upcoming || []).map(p => p.title)].filter(Boolean).join(' ').toLowerCase().includes(state.query));
      head.append(h('span', {class: 'chip ghost', style: {marginLeft: 'auto'}}, all.length + ' ' + (all.length === 1 ? 'channel' : 'channels')));
      // In All sources, each source shows its first channels; searching or choosing the source shows every one.
      const short = state.filter === 'all' && !state.query && !expanded.has(source.id) && all.length > PREVIEW_ROWS;
      const rows = short ? all.slice(0, PREVIEW_ROWS) : all;
      if (!rows.length && !data.error) body.append(h('p', {class: 'hint', style: {padding: '14px 16px'}}, state.query ? 'No matching listings.' : 'No channels or games listed.'));
      for (const channel of rows) {
        const live = same(state.master.on_air, {source_id: source.id, channel_id: String(channel.id), date: state.master.on_air?.date});
        const name = h('div', {class: 'ch stack tight', style: {gap: '6px'}}, h('div', live ? h('span', {class: 'chip solid pgm', style: {marginBottom: '4px'}}, 'On air') : null,
          h('strong', channel.number || channel.name), channel.number ? h('small', channel.name) : null),
          state.queue?.master_queue ? OnAir.buttons(guideItem(source, channel, data), {compact: true}) : null);
        const now = programCell(channel.now || ((channel.game && !channel.upcoming.length) ? channel.game : null), channel.game && !channel.now ? 'Game status' : 'Now', source, channel, data);
        const upcoming = programCell(channel.upcoming[0], 'Next', source, channel, data);
        if (channel.upcoming.length > 1) {
          const list = h('ul');
          for (const p of channel.upcoming.slice(1)) list.append(h('li', h('span', fmt.when(p.start) + ' · ' + p.title),
            state.queue?.master_queue && p.id && !channel.game ? OnAir.buttons(guideItem(source, channel, data, p)) : null));
          upcoming.append(h('details', h('summary', 'Later · ' + (channel.upcoming.length - 1) + ' programs'), list));
        }
        body.append(h('div', {class: 'grow-row row-channel', data: {channel: channel.id}}, name, now, upcoming));
      }
      if (short) {
        const more = h('button', {class: 'sm quiet', type: 'button'}, 'Show all ' + all.length + ' channels');
        more.onclick = () => { expanded.add(source.id); renderGuide(); };
        body.append(h('div', {style: {padding: '10px 16px', borderTop: '1px solid var(--line)'}}, more));
      }
    }
  }
  const naturally = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
  function libraryGroups(data) {
    const groups = new Map();
    for (const item of data.items || []) { if (!groups.has(item.collection)) groups.set(item.collection, []); groups.get(item.collection).push(item); }
    // Recordings newest first; other folders in episode order.
    for (const items of groups.values()) items.sort((a, b) => a.aired && b.aired ? b.aired - a.aired || naturally.compare(a.path, b.path) : naturally.compare(a.path, b.path));
    return [...groups].sort((a, b) => naturally.compare(a[0], b[0]));
  }
  const playOrder = items => [...items].sort((a, b) => a.aired && b.aired ? a.aired - b.aired || naturally.compare(a.path, b.path) : naturally.compare(a.path, b.path));
  function renderLibrary(head, body, data) {
    if (data.roots) head.append(h('small', {class: 'muted'}, data.roots.map(r => r.name + ' · ' + (r.available ? r.count + ' files' : r.error || 'unavailable')).join(' · ')));
    const problems = [data.error, ...(data.roots || []).filter(r => r.error).map(r => r.name + ': ' + r.error)].filter(Boolean);
    if (problems.length) body.append(h('div', {style: {padding: '10px 16px'}}, problems.map(p => h('p', {class: 'note warn small'}, p))));
    const matches = item => [item.title, item.collection, item.channel, item.path].filter(Boolean).join(' ').toLowerCase().includes(state.query);
    const groups = libraryGroups(data).map(([name, items]) => [name, items.filter(matches)]).filter(([, items]) => items.length);
    if (!groups.length) body.append(h('p', {class: 'hint', style: {padding: '14px 16px'}}, state.query ? 'No matching files.' : 'No finished files in the library yet. Recordings appear here once TV-Thing finishes them.'));
    for (const [name, items] of groups) {
      const title = h('div', {class: 'collection'}, h('h3', name), h('small', {class: 'muted'}, items.length + (items.length === 1 ? ' file' : ' files')));
      if (state.queue?.master_queue && items.length > 1) {
        const all = h('button', {class: 'sm', type: 'button', 'aria-label': 'Add all of ' + name + ' to the queue in order'}, '+ Add all to queue');
        all.onclick = () => queueAll(playOrder(items.filter(i => i.playable !== false)), all); title.append(all);
      }
      body.append(title);
      for (const item of items) {
        const target = {source_id: 'library', channel_id: item.id};
        const onAir = same(state.master.on_air, target), prepared = same(state.master.prepared, target);
        const info = h('div', h('strong', item.title), h('small', [item.channel, item.aired ? fmt.full(item.aired) : null, item.variant ? '(' + item.variant + ')' : null].filter(Boolean).join(' · ') || item.path),
          onAir ? h('small', {style: {color: 'var(--pgm)'}}, 'On master · ' + fmt.dur(state.master.on_air.media?.position_seconds) + ' / ' + fmt.dur(state.master.on_air.media?.duration_seconds))
            : prepared ? h('small', {style: {color: 'var(--pvw)'}}, state.master.prepared.after_input_id ? 'Cued · plays when the current file ends' : 'Cued at its start for Up next') : null);
        const meta = h('div', h('small', {class: 'mono'}, item.probe === 'pending' ? 'Checking file…' : item.duration ? fmt.dur(item.duration) : 'Length unknown'),
          h('small', {class: 'mono'}, (item.bytes / 1e9).toFixed(item.bytes >= 1e10 ? 0 : 1) + ' GB' + (item.video?.height ? ' · ' + item.video.height + 'p' : '')),
          item.playable === false ? h('small', {style: {color: 'var(--warn)'}}, 'Cannot play: ' + (item.reason || 'unsupported')) : null);
        const actions = state.queue?.master_queue && item.playable !== false ? OnAir.buttons(recordingItem(item)) : h('div');
        body.append(h('div', {class: 'media media-row', data: {live: String(onAir), id: item.id}}, info, meta, actions));
      }
    }
  }
  async function queueAll(items, button) {
    button.disabled = true;
    try { for (const item of items) await api('v1/queue', {target: {source_id: 'library', channel_id: item.id}, release_type: 'after_current'}); toast('Added ' + items.length + ' recordings to the end of Up next, in order.', {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
    finally { button.disabled = false; VV.poke('v1/queue'); }
  }

  /* Loading ----------------------------------------------------------------------------------------------- */
  async function refresh() {
    if (state.busy) return; state.busy = true; id('refresh').disabled = true; id('status').textContent = 'Refreshing listings…';
    try {
      const catalog = await api('v1/sources');
      state.sources = catalog.sources.filter(s => s.id !== 'tv-thing-analog'); VV.known.sources = state.sources;
      state.master = catalog.master || state.master;
      renderNav(); renderGuide(); renderCards();
      const results = await Promise.allSettled(state.sources.filter(s => s.configured).map(async source => {
        try { state.programs.set(source.id, await api('v1/sources/' + encodeURIComponent(source.id) + '/programs')); }
        catch (e) { const previous = state.programs.get(source.id); state.programs.set(source.id, {...previous, stale: !!previous, error: e.message}); throw e; }
        finally { renderGuide(); renderCards(); }
      }));
      const failed = results.filter(r => r.status === 'rejected').length;
      id('status').textContent = failed ? failed + ' source(s) could not be refreshed; the rest are current.' : catalog.warnings?.length ? catalog.warnings.join(' · ') : 'Listings updated ' + fmt.clock(new Date()) + ' · times in your time zone';
    } catch (e) { id('status').textContent = 'Could not refresh sources: ' + e.message; }
    finally { state.busy = false; id('refresh').disabled = false; }
  }
  id('search').oninput = e => { state.query = e.target.value.toLowerCase().trim(); renderGuide(); };
  id('refresh').onclick = refresh;
  VV.watch('v1/master', 2000, (data, w) => { if (!w.error) { state.master = data; renderCards(); } });
  let lastQueue = '';
  VV.watch('v1/queue', 2000, (data, w) => {
    if (w.error) return;
    const first = !state.queue; state.queue = data;
    const signature = String(data.master_queue);
    if (first || signature !== lastQueue) { lastQueue = signature; renderGuide(); renderCards(); }
  });
  VV.watch('v1/production', 30000, data => TestCard.set(data.cards));
  // Recording progress and new files: the library listing every 15 s while it is shown.
  setInterval(async () => {
    if (document.hidden || state.busy || !['all', 'library'].includes(state.filter) || !state.sources.some(s => s.id === 'library' && s.configured)) return;
    try { state.programs.set('library', await api('v1/sources/library/programs')); renderGuide(); } catch {}
  }, 15000);
  setInterval(() => { if (!document.hidden) refresh(); }, 120000);
  document.addEventListener('vv:auth', refresh);
  VV.commands.add({id: 'sources:refresh', title: 'Refresh listings', group: 'Sources', keys: 'r', run: refresh},
    ...['all', 'library', 'roku', 'sports'].map(f => ({id: 'sources:filter:' + f, title: 'Show ' + ({all: 'all sources', library: 'the Media Library', roku: 'Roku sources', sports: 'Sports'}[f]), group: 'Sources',
      run: () => { state.filter = f; VV.store.set('sourcesFilter', f); renderNav(); renderGuide(); renderCards(); }})));
  refresh();
})();
