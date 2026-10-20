// Sources: every channel, game and recording, with the three ways on air beside each.
(() => {
  'use strict';
  const {h, api, fmt, toast, label, same, ROKU, icon, ICONS} = VV;
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
  /* Ad breaks for a show (a folder set up for them: Jellyfin's, never TV-Thing's recordings) ---------- */
  // "+ Add ads" on a row opens its strip: how long each break runs (15 s steps up to 3 min) and
  // the scan that finds the breaks (only when asked; what it found is kept). Play and Queue
  // then ask for ad breaks, once the scan found some.
  const BREAK = {least: 15, most: 180, step: 15};
  const ads = new Map();   // item ID -> seconds of ads at each break, while Add ads is on for it
  const SCANNING = ['scanning', 'waiting'];
  function showItem(file) {
    const item = recordingItem(file);
    Object.defineProperty(item, 'target', {enumerable: true, get() {
      const found = file.ad_breaks, seconds = ads.get(file.id);
      return {source_id: 'library', channel_id: file.id, ...(seconds && found?.state === 'ok' ? {ad_breaks: seconds} : {})};
    }});
    if (file.ad_breaks?.state === 'ok') item.ad_count = file.ad_breaks.at.length;
    return item;
  }
  function adsButton(file) {
    const on = ads.has(file.id);
    const b = h('button', {type: 'button', class: 'sm' + (on ? ' primary' : ''), 'aria-pressed': String(on), 'aria-label': (on ? 'Remove ads from ' : 'Add ads to ') + file.title},
      on ? '✓ Ads' : '+ Add ads');
    b.onclick = () => {
      if (on) ads.delete(file.id); else ads.set(file.id, VV.store.get('adBreakSeconds', 60));
      renderGuide();
    };
    return b;
  }
  function breakFinding(found) {
    const n = found.at.length;
    return {ok: n + (n === 1 ? ' ad break' : ' ad breaks') + ' · at ' + found.at.map(t => fmt.dur(t)).join(', '),
      none: 'No ad breaks found in this file: it plays straight through.',
      failed: 'The scan failed' + (found.reason ? ': ' + found.reason : '') + '.',
      scanning: 'Scanning for ad breaks… about half a minute.', waiting: 'Waiting to scan…',
      not_scanned: 'Not scanned yet: the scan finds where the show fades to black for its breaks.'}[found.state] || found.state;
  }
  function adsStrip(file) {
    const seconds = ads.get(file.id), found = file.ad_breaks;
    const shown = h('strong', {class: 'mono'}, fmt.dur(seconds));
    const length = h('input', {type: 'range', min: BREAK.least, max: BREAK.most, step: BREAK.step, value: seconds,
      'aria-label': 'How long each ad break runs', style: {width: '160px'}});
    length.oninput = () => { const v = Number(length.value); ads.set(file.id, v); VV.store.set('adBreakSeconds', v); shown.textContent = fmt.dur(v); };
    const scanning = SCANNING.includes(found.state);
    const scan = h('button', {type: 'button', class: 'sm' + (found.state === 'not_scanned' ? ' primary' : ' quiet'), disabled: scanning},
      found.state === 'not_scanned' ? 'Scan for ad breaks' : scanning ? 'Scanning…' : 'Scan again');
    scan.onclick = async () => {
      scan.disabled = true;
      try { replaceItem(await api('v1/sources/library/scan', {channel_id: file.id})); renderGuide(); watchScans(); }
      catch (e) { toast(e.message, {error: true}); scan.disabled = false; }
    };
    const finding = h('small', {class: found.state === 'failed' ? 'warn' : '', role: 'status'}, breakFinding(found),
      found.state !== 'ok' && !scanning ? ' Until it has breaks, Play and Queue put it on without ads.' : '');
    return h('div', {class: 'media-ads'},
      h('label', {class: 'ads-length'}, h('span', {class: 'label'}, 'Each break'), length, shown),
      h('div', {class: 'ads-scan'}, scan, finding));
  }
  function replaceItem(item) {
    const data = state.programs.get('library');
    if (data?.items) data.items = data.items.map(i => i.id === item.id ? item : i);
  }
  // While a scan runs, the listing every 3 s (else every 15 s, below).
  let scanTimer = null;
  function watchScans() {
    if (scanTimer) return;
    scanTimer = setInterval(async () => {
      try {
        const data = await api('v1/sources/library/programs');
        state.programs.set('library', data); renderGuide();
        if (!(data.items || []).some(i => SCANNING.includes(i.ad_breaks?.state))) { clearInterval(scanTimer); scanTimer = null; }
      } catch {}
    }, 3000);
  }

  const playOrder = items => [...items].sort((a, b) => a.aired && b.aired ? a.aired - b.aired || naturally.compare(a.path, b.path) : naturally.compare(a.path, b.path));
  function renderLibrary(head, body, data) {
    if (data.roots) head.append(h('small', {class: 'muted'}, data.roots.map(r => r.name + ' · ' + (r.available ? r.count + ' files' : r.error || 'unavailable')).join(' · ')));
    const problems = [data.error, ...(data.roots || []).filter(r => r.error).map(r => r.name + ': ' + r.error)].filter(Boolean);
    if (problems.length) body.append(h('div', {style: {padding: '10px 16px'}}, problems.map(p => h('p', {class: 'note warn small'}, p))));
    const matches = item => [item.title, item.collection, item.channel, item.path].filter(Boolean).join(' ').toLowerCase().includes(state.query);
    const visible = (data.items || []).filter(matches);
    if (!visible.length) body.append(h('p', {class: 'hint', style: {padding: '14px 16px'}}, state.query ? 'No matching files.' : 'No finished files in the library yet. Recordings appear here once TV-Thing finishes them.'));
    // TV-Thing's recordings (and other plain folders): each folder closed until opened, newest
    // first, a programme recorded more than once (every Jeopardy!) folded together inside it.
    for (const [name, items] of libraryGroups({items: visible.filter(i => !i.ad_breaks)})) {
      const folderKey = 'folder:' + name;
      const open = folded(folderKey, items);
      body.append(foldTitle('collection', folderKey, open, h('h3', name), items.length + (items.length === 1 ? ' file' : ' files'), items, name));
      if (!open) continue;
      const titles = byTitle(items);
      for (const [title, airings] of titles) {
        if (airings.length === 1 || titles.length === 1) { for (const item of airings) mediaRow(body, item); continue; }
        const titleKey = 'title:' + name + '/' + title;
        const titleOpen = folded(titleKey, airings);
        body.append(foldTitle('collection season-title', titleKey, titleOpen, h('h4', title),
          airings.length + ' recordings', airings, title));
        if (titleOpen) for (const item of airings) mediaRow(body, item, true);
      }
    }
    // Shows (a folder with ad breaks: Jellyfin's): each show, then each season, closed until opened.
    for (const [show, seasons] of showTree(visible.filter(i => i.ad_breaks))) {
      const episodes = [...seasons.values()].flat();
      const showKey = 'show:' + show;
      const open = folded(showKey, episodes);
      const named = [...seasons.keys()].filter(Boolean).length;
      body.append(foldTitle('collection show-title', showKey, open, h('h3', show),
        [named ? named + (named === 1 ? ' season' : ' seasons') : null, episodes.length + (episodes.length === 1 ? ' episode' : ' episodes')].filter(Boolean).join(' · '), episodes));
      if (!open) continue;
      for (const [season, items] of seasons) {
        if (!season) { for (const item of items) mediaRow(body, item, true); continue; }
        const seasonKey = 'season:' + show + '/' + season;
        const seasonOpen = folded(seasonKey, items);
        body.append(foldTitle('collection season-title', seasonKey, seasonOpen, h('h4', season),
          items.length + (items.length === 1 ? ' episode' : ' episodes'), items, show + ' ' + season));
        if (seasonOpen) for (const item of items) mediaRow(body, item, true);
      }
    }
  }
  // A folder's recordings by programme title, in the folder's order (newest first): a programme
  // sits where its latest recording would.
  function byTitle(items) {
    const titles = new Map();
    for (const item of items) { const key = item.title || item.path; if (!titles.has(key)) titles.set(key, []); titles.get(key).push(item); }
    return [...titles];
  }
  // Shows by folder: show -> season (null: episodes right in the show's folder) -> episodes, in order.
  function showTree(items) {
    const shows = new Map();
    for (const item of items) {
      const parts = item.path.split('/');
      const show = parts.length > 1 ? parts[0] : 'Shows', season = parts.length > 2 ? parts.slice(1, -1).join('/') : null;
      if (!shows.has(show)) shows.set(show, new Map());
      const seasons = shows.get(show);
      if (!seasons.has(season)) seasons.set(season, []);
      seasons.get(season).push(item);
    }
    const order = (a, b) => a == null ? -1 : b == null ? 1 : naturally.compare(a, b);
    return [...shows].sort((a, b) => naturally.compare(a[0], b[0])).map(([show, seasons]) =>
      [show, new Map([...seasons].sort((a, b) => order(a[0], b[0])).map(([season, list]) => [season, playOrder(list)]))]);
  }
  // Which shows and seasons are open, as opened or closed by hand: remembered in this browser.
  // Otherwise closed, except the one with an episode on air, cued or with its ads strip open.
  // A search opens everything it finds.
  const folds = VV.store.get('libraryFolds', {});
  function folded(key, items) {
    if (state.query) return true;
    if (key in folds) return folds[key];
    const shown = it => same(state.master.on_air, {source_id: 'library', channel_id: it.id})
      || same(state.master.prepared, {source_id: 'library', channel_id: it.id}) || ads.has(it.id);
    return items.some(shown);
  }
  function foldTitle(cls, key, open, heading, count, items, name) {
    const toggle = h('button', {type: 'button', class: 'fold', 'aria-expanded': String(open)}, icon(ICONS.down), heading,
      h('small', {class: 'muted'}, count));
    toggle.onclick = () => {
      if (state.query) return;   // a search shows all it finds
      folds[key] = !open;
      VV.store.set('libraryFolds', folds);
      renderGuide();
    };
    const live = items.some(it => same(state.master.on_air, {source_id: 'library', channel_id: it.id}));
    return collectionTitle(cls, toggle, null, name, name ? items : [], live ? h('span', {class: 'chip solid pgm'}, 'On air') : null);
  }
  function collectionTitle(cls, heading, count, name, items, extra) {
    const title = h('div', {class: cls}, heading, count ? h('small', {class: 'muted'}, count) : null, extra || null);
    if (state.queue?.master_queue && items.length > 1) {
      const all = h('button', {class: 'sm', type: 'button', 'aria-label': 'Add all of ' + name + ' to the queue in order'}, '+ Add all to queue');
      all.onclick = () => queueAll(playOrder(items.filter(i => i.playable !== false)), all); title.append(all);
    }
    return title;
  }
  function mediaRow(body, item, nested = false) {
    const target = {source_id: 'library', channel_id: item.id};
    const onAir = same(state.master.on_air, target), prepared = same(state.master.prepared, target);
    const info = h('div', h('strong', item.title), h('small', [item.channel, item.aired ? fmt.full(item.aired) : null, item.variant ? '(' + item.variant + ')' : null].filter(Boolean).join(' · ') || (nested ? item.path.split('/').pop() : item.path)),
      onAir ? h('small', {style: {color: 'var(--pgm)'}}, 'On master · ' + fmt.dur(state.master.on_air.media?.position_seconds) + ' / ' + fmt.dur(state.master.on_air.media?.duration_seconds))
        : prepared ? h('small', {style: {color: 'var(--pvw)'}}, state.master.prepared.after_input_id ? 'Cued · plays when the current file ends' : 'Cued at its start for Up next') : null);
    const meta = h('div', h('small', {class: 'mono'}, item.probe === 'pending' ? 'Checking file…' : item.duration ? fmt.dur(item.duration) : 'Length unknown'),
      h('small', {class: 'mono'}, (item.bytes / 1e9).toFixed(item.bytes >= 1e10 ? 0 : 1) + ' GB' + (item.video?.height ? ' · ' + item.video.height + 'p' : '')),
      item.playable === false ? h('small', {style: {color: 'var(--warn)'}}, 'Cannot play: ' + (item.reason || 'unsupported')) : null);
    const show = item.ad_breaks && item.playable !== false;
    const actions = state.queue?.master_queue && item.playable !== false ? OnAir.buttons(show ? showItem(item) : recordingItem(item)) : h('div');
    if (show && state.queue?.master_queue) actions.append(adsButton(item));
    const breaks = state.master.on_air && onAir ? state.master.on_air.break_plan : null;
    if (breaks) info.append(h('small', {style: {color: 'var(--pgm)'}}, breaks.state === 'held' ? 'In an ad break'
      : 'Ad breaks · ' + breaks.aired + ' of ' + breaks.count + ' done' + (breaks.next_at != null ? ' · next at ' + fmt.dur(breaks.next_at) : '')));
    body.append(h('div', {class: 'media media-row' + (nested ? ' nested' : ''), data: {live: String(onAir), id: item.id}}, info, meta, actions));
    if (show && ads.has(item.id)) body.append(adsStrip(item));
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
