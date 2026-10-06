// Engineering: health of every part, the viewer monitor, the Roku capture, the system map,
// an API explorer, and this browser's interface settings.
(() => {
  'use strict';
  const {h, api, fmt, toast, label} = VV;
  const $ = id => document.getElementById(id);
  const S = {};  // latest of each endpoint
  const tab = VV.store.get('engTab', 'health');

  /* Tabs -------------------------------------------------------------------------------------------------------- */
  const tabs = [...document.querySelectorAll('[role=tab]')];
  const stops = [];
  function show(name) {
    const t = tabs.find(x => x.dataset.tab === name) || tabs[0];
    tabs.forEach(x => x.setAttribute('aria-selected', String(x === t)));
    document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== t.dataset.tab; });
    VV.store.set('engTab', t.dataset.tab);
    if (location.hash !== '#' + t.dataset.tab) history.replaceState(null, '', '#' + t.dataset.tab);
    stops.splice(0).forEach(stop => stop());
    ({health: startHealth, monitor: startMonitor, roku: startRoku, how: startMap, api: startApi, interface: startInterface}[t.dataset.tab] || (() => {}))();
  }
  tabs.forEach(t => { t.onclick = () => show(t.dataset.tab); });

  /* Health ------------------------------------------------------------------------------------------------------- */
  const tile = (title, lamp, rows, extra) => h('section', {class: 'panel'}, h('div', {class: 'head'}, h('span', {class: 'lamp ' + lamp}), h('h2', title)),
    h('div', {class: 'body stack tight'}, h('dl', {class: 'kv'}, rows.filter(Boolean).map(([k, v]) => [h('dt', k), h('dd', v ?? '—')])), extra || null));
  const ago = t => t ? fmt.rel(t) : '—';
  const bad = text => h('span', {style: {color: 'var(--warn)'}}, text);
  function renderHealth() {
    const m = S.master || {}, q = S.queue, p = S.programming, c = S.crawl, k = S.continuity, src = S.sources, mon = S.monitor;
    const tiles = [];
    const live = m.state === 'live';
    tiles.push(tile('Master worker', live ? 'pvw' : m.state ? 'warn' : '', [
      ['State', m.state], ['Publisher', m.publisher_ready ? 'ready' : bad('not ready')], ['On air', m.on_air ? label(m.on_air) : 'test card'],
      ['Prepared', m.prepared ? label(m.prepared) : '—'], ['Operation', m.operation ? m.operation.action + ' · ' + m.operation.state : '—'],
      m.recovery ? ['Recovery', bad(label(m.recovery.target))] : null, m.error ? ['Error', bad(m.error)] : null, m.cleanup_warning ? ['Cleanup', bad(m.cleanup_warning)] : null,
      m.production_error ? ['Production', bad(m.production_error)] : null,
      m.last_input_failure ? ['Last input failure', fmt.when(m.last_input_failure.at) + ' · ' + label(m.last_input_failure.target) + ': ' + m.last_input_failure.error] : null]));
    const track = t => t ? 'lag ' + t.lag_seconds + ' s · age ' + t.age_seconds + ' s' + (t.backwards ? ' · ' + t.backwards + ' backwards' : '') : '—';
    const lag = Math.max(m.tracks?.video?.lag_seconds || 0, m.tracks?.audio?.lag_seconds || 0);
    tiles.push(tile('Output tracks', lag > 2 ? 'warn' : m.tracks ? 'pvw' : '', [['Video', track(m.tracks?.video)], ['Audio', track(m.tracks?.audio)],
      ['Input video', m.input_tracks?.on_air?.video ? 'age ' + m.input_tracks.on_air.video.age_seconds + ' s · ' + (m.input_tracks.on_air.video.late_dropped || 0) + ' late dropped' : '—'],
      ['Input audio', m.input_tracks?.on_air?.audio ? 'age ' + m.input_tracks.on_air.audio.age_seconds + ' s · max gap ' + m.input_tracks.on_air.audio.max_packet_gap_seconds + ' s' : '—'],
      ['Monitor', m.preview_enabled ? 'HLS available' : 'off']]));
    if (q) {
      const waiting = q.items.filter(i => ['queued', 'blocked'].includes(i.status));
      tiles.push(tile('Up next', q.paused && !q.hold ? 'warn' : 'pvw', [['State', q.hold ? 'holding ' + (q.hold.game?.title || label(q.hold.target)) : q.paused ? bad('paused · ' + (q.pause_reason || '')) : 'running'],
        ['Waiting', waiting.length + ' (' + waiting.filter(i => i.status === 'blocked').length + ' blocked)'], ['Next scheduled', q.next_scheduled ? fmt.when(q.next_scheduled.run_at) + ' · ' + (q.next_scheduled.title || '') : '—'],
        ['Master queue', q.master_queue ? 'on' : 'off'], ['Schedule', q.schedule_enabled ? 'feeding Up next' : 'off']]));
    }
    if (p) tiles.push(tile('Schedule', p.settings.enabled ? 'pvw' : '', [['Automation', p.settings.enabled ? 'running' : 'stopped'], ['On now', p.on_now?.title], ['Last sync', ago(p.last_sync)],
      ['Games checked', ago(p.games_checked_at) + ' · every ' + p.game_check_minutes + ' min'], ['Lookahead', p.lookahead_minutes + ' min'], ['Time zone', p.timezone]]));
    if (c) {
      const st = c.status || {}, rot = c.rotation || {};
      const feeds = h('table', {class: 'feeds'}, Object.entries(rot.segments || {}).map(([seg, s]) => h('tr', h('td', c.segments[seg]?.name || seg),
        h('td', {class: 'mono tiny', style: {textAlign: 'right'}}, !c.settings.segments[seg].enabled ? 'off' : s.feed?.error ? bad('error') : s.feed ? (s.feed.fetched_at ? ago(s.feed.fetched_at) : 'loading') : 'local'))));
      tiles.push(tile('Crawl', rot.error || st.error ? 'warn' : st.on_air ? 'touch' : 'pvw', [['Bar', st.on_air ? st.kind + ' · ' + (st.label || '') : 'off'], ['Rotation', rot.error ? bad(rot.error) : (rot.context || '—') + ' · ' + (rot.mode || '—')],
        ['EAS decoder', st.eas ? (st.eas.error ? bad(st.eas.error) : 'checked ' + ago(st.eas.checked_at)) : 'not configured'], ['NWS', st.nws ? (st.nws.error ? bad(st.nws.error) : 'checked ' + ago(st.nws.checked_at)) : 'not configured'],
        ['Alerts', (st.alerts || []).length + ' active'], c.master_error ? ['Master', bad(c.master_error)] : null], feeds));
    }
    if (k) tiles.push(tile('Continuity', k.error ? 'warn' : k.settings.enabled ? 'pvw' : '', [['Announcements', k.settings.enabled ? 'on' : 'off'], ['On duty', k.on_duty_now],
      ['Deepgram', k.ready.key ? 'key found' : bad('no key')], ['Music bed', k.ready.music ? 'ready' : bad('missing')], ['Station ID', k.ready.id ? 'ready' : bad('missing')], ['Sports ID', k.ready.sports ? 'ready' : bad('missing')],
      ['Next break', k.next ? fmt.when(k.next.break_at) + ' · ' + k.next.name : '—'], k.error ? ['Error', bad(k.error)] : null]));
    tiles.push(tile('Station ID', m.ident?.ready ? 'pvw' : 'warn', [['State', m.ident ? (m.ident.on_air ? 'on air' : m.ident.ready ? 'ready' : 'not ready') : '—'], ['Length', m.ident?.duration_seconds ? m.ident.duration_seconds + ' s' : '—'],
      ['Last aired', m.last_station_id ? fmt.when(m.last_station_id.at) + (/^sports-/.test(m.last_station_id.file) ? ' · Sports ID' : '') : '—'], m.ident?.error ? ['Error', bad(m.ident.error)] : null]));
    if (src) tiles.push(tile('Sources', src.warnings?.length ? 'warn' : 'pvw', src.sources.map(s => [s.name, !s.configured ? 'not configured' : (s.availability || '—') + (s.stale ? ' · stale' : '') + (s.count != null ? ' · ' + s.count : '')]),
      src.warnings?.length ? h('p', {class: 'note warn tiny'}, src.warnings.join(' · ')) : null));
    const rk = m.roku_last_prepared;
    tiles.push(tile('Roku', m.roku_enabled ? (rk?.reusable ? 'pvw' : '') : '', [['Enabled', m.roku_enabled ? 'yes' : 'no'], ['Last verified', rk ? label(rk.target) + ' · ' + ago(rk.prepared_at) : '—'],
      rk ? ['Reusable', rk.reusable ? 'yes, for ' + fmt.mins(rk.max_age_seconds - rk.age_seconds) : rk.reason] : null, ['Where', 'TV Thing’s Roku lane']]));
    if (mon) { const last = mon.last_check; tiles.push(tile('Viewer monitor', last?.status === 'healthy' ? 'pvw' : last ? 'warn' : '', [['Checks', mon.settings.enabled ? 'every ' + mon.settings.interval_hours + ' h' : 'off'],
      ['Last', last ? last.status + ' · ' + ago(last.finished_at) : 'none'], ['Message', last?.message], ['Next', mon.settings.enabled ? fmt.when(mon.next_check_at) : '—']])); }
    const lib = src?.sources.find(s => s.id === 'library');
    VV.fill($('health'), tiles);
    $('health-note').textContent = 'Updated ' + fmt.clockSec(new Date()) + (lib ? '' : '');
  }
  function startHealth() {
    const subs = [['v1/master', 5000, 'master'], ['v1/queue', 5000, 'queue'], ['v1/programming', 60000, 'programming'], ['v1/crawl', 15000, 'crawl'], ['v1/continuity', 30000, 'continuity'],
      ['v1/sources', 60000, 'sources'], ['v1/production/monitor', 30000, 'monitor']];
    for (const [path, ms, name] of subs) stops.push(VV.watch(path, ms, (data, w) => { if (!w.error) { S[name] = data; renderHealth(); } }));
  }

  /* The viewer monitor ----------------------------------------------------------------------------------------------- */
  let monitorBusy = false, filled = false;
  const buttons = () => ['monitor-save', 'monitor-check', 'monitor-launch'].forEach(id => { $(id).disabled = monitorBusy || !!S.monitor?.running || !!S.monitor?.pending; });
  function renderMonitor(result, fill = false) {
    S.monitor = result;
    if (fill || !filled) { filled = true; const s = result.settings; $('monitor-enabled').checked = s.enabled; $('monitor-ip').value = s.roku_ip; $('monitor-channel').value = s.cable_channel; $('monitor-app').value = s.app_id; $('monitor-hours').value = s.interval_hours; }
    const last = result.last_check, busy = result.running || result.pending;
    $('monitor-lamp').className = 'lamp ' + (busy ? 'warn blink' : last?.status === 'healthy' ? 'pvw' : last ? 'warn' : '');
    $('monitor-message').textContent = result.storage_error || (busy ? 'Check in progress…' : last ? last.status.toUpperCase() + ' · ' + last.message : 'No checks yet.');
    $('monitor-timing').textContent = 'Last: ' + (last?.finished_at ? fmt.full(last.finished_at) : '—') + ' · Next: ' + (result.settings.enabled ? fmt.full(result.next_check_at) : 'periodic checks off');
    const image = last?.cable?.image_base64;
    $('monitor-image').hidden = !image; if (image) $('monitor-image').src = 'data:image/png;base64,' + image; else $('monitor-image').removeAttribute('src');
    const diagnostic = JSON.parse(JSON.stringify(result)); if (diagnostic.last_check?.cable) delete diagnostic.last_check.cable.image_base64;
    VV.fill($('monitor-diagnostics'), VV.json(diagnostic));
    buttons();
  }
  function startMonitor() { stops.push(VV.watch('v1/production/monitor', 5000, (data, w) => { if (w.error) $('monitor-message').textContent = w.error.message; else renderMonitor(data); })); }
  $('monitor-settings').onsubmit = async e => {
    e.preventDefault(); monitorBusy = true; buttons();
    try { renderMonitor(await api('v1/production/monitor', {enabled: $('monitor-enabled').checked, roku_ip: $('monitor-ip').value.trim(), cable_channel: Number($('monitor-channel').value), app_id: $('monitor-app').value.trim(), interval_hours: Number($('monitor-hours').value)}), true); toast('Monitor settings saved.', {ok: true}); }
    catch (err) { toast(err.message, {error: true}); } finally { monitorBusy = false; buttons(); }
  };
  $('monitor-check').onclick = async () => { monitorBusy = true; buttons(); try { renderMonitor(await api('v1/production/monitor/check', {})); } catch (e) { toast(e.message, {error: true}); } finally { monitorBusy = false; buttons(); } };
  $('monitor-launch').onclick = async () => {
    monitorBusy = true; buttons(); $('monitor-launch-message').textContent = 'Launching VizelVision…';
    try { const r = await api('v1/production/monitor/launch', {}, {timeout: 30000}); $('monitor-launch-message').textContent = 'Launch sent to ' + r.roku_ip + ' · active app: ' + (r.active_app?.name || r.active_app?.id || 'unknown'); }
    catch (e) { $('monitor-launch-message').textContent = e.message; } finally { monitorBusy = false; buttons(); }
  };

  /* The source Roku: TV Thing's Roku lane ------------------------------------------------------------------------------- */
  const tvThing = path => location.protocol + '//' + location.hostname + '/tv/' + path;
  $('tv-roku-page').href = tvThing('roku.html');
  $('tv-roku-watch').href = tvThing('#roku');
  async function loadRoku() {
    try {
      const {lane, lock, last_prepared: known} = await api('v1/roku/status');
      const roku = lane.roku || {}, selection = lane.selection, op = roku.operation, player = roku.player?.data || {};
      S.roku = {lane, lock};
      $('roku-lamp').className = 'lamp ' + (op?.active ? 'warn blink' : selection && !selection.manual ? 'pvw' : lane.stream?.active ? '' : 'warn');
      VV.fill($('roku-kv'), [['Showing', selection ? (selection.manual ? 'Manual Roku' : selection.name || label(selection)) : 'unverified'],
        ['Verified', known ? ago(known.prepared_at) + (known.reusable ? ' · reusable' : ' · checked again first') : '—'],
        ['Navigation', op ? op.state + (op.message ? ' · ' + op.message : '') : 'none yet'], ['Lock', lock ? lock.owner + ' · ' + fmt.mins(lock.seconds_remaining) : 'free'],
        ['Active app', player.app?.name || roku.player?.error || '—'], ['Capture', lane.stream?.active ? lane.stream.state : bad('stopped')]]
        .map(([k, v]) => [h('dt', k), h('dd', v)]));
      VV.fill($('calibration-kv'), [['Feed', 'H.264 copy from the HD PVR · stream/roku.m3u8'], ['Generation', h('code', lane.stream?.generation || '—')]]
        .map(([k, v]) => [h('dt', k), h('dd', v ?? '—')]));
      $('roku-stop').disabled = !op?.active;
      $('roku-status').textContent = 'Checked ' + fmt.clockSec(new Date());
    } catch (e) { $('roku-status').textContent = e.message; }
  }
  function startRoku() { loadRoku(); const timer = setInterval(() => { if (!document.hidden) loadRoku(); }, 5000); stops.push(() => clearInterval(timer)); }
  $('roku-refresh').onclick = loadRoku;
  $('roku-stop').onclick = async () => { if (!await VV.confirm('Stop the Roku navigation that is running?', {title: 'Stop the Roku', ok: 'Stop', danger: true})) return; try { await api('v1/operation/cancel', {}); loadRoku(); } catch (e) { toast(e.message, {error: true}); } };

  /* The system map ------------------------------------------------------------------------------------------------------ */
  function startMap() {
    const draw = () => {
      const m = S.master || {}, c = S.crawl?.status || {}, segs = S.crawl?.rotation?.segments || {}, k = S.continuity;
      const tone = ok => ok === undefined ? '#46515b' : ok ? '#34d07a' : '#ffb340';
      const box = (x, y, w, hh, title, lines, ok, cls = 'proc') => `<g><rect class="${cls}" x="${x}" y="${y}" width="${w}" height="${hh}" rx="6"/><circle cx="${x + w - 12}" cy="${y + 13}" r="4" fill="${tone(ok)}"/>`
        + `<text class="t" x="${x + 10}" y="${y + 18}">${title}</text>` + lines.map((t, i) => `<text class="muted" x="${x + 10}" y="${y + 35 + i * 14}">${t}</text>`).join('') + '</g>';
      const feed = s => segs[s]?.feed ? !segs[s].feed.error : undefined;
      // Who talks to whom: [title, lines, healthy?, into web, into master].
      const ext = [['TV-Thing', ['OTA tuners · HLS'], S.sources?.sources?.some(s => s.id === 'tv-thing-digital' && s.availability === 'available'), true, true],
        ['Source Roku (TV-Thing)', ['Roku lane · HD PVR copy'], S.rokuStatus ? !!S.rokuStatus.lane?.stream?.active : undefined, true, true],
        ['Media library', ['/mnt/sda1/media'], S.sources?.sources?.some(s => s.id === 'library' && s.configured), true, true],
        ['EAS decoder :8090', ['SAME + transcripts'], c.eas ? !c.eas.error : undefined, false, true],
        ['NWS · WMATA · AlertDC', ['alerts, Metro, DC'], [feed('transit'), feed('dc_alerts'), c.nws ? !c.nws.error : undefined].every(v => v !== false), true, true],
        ['ESPN · MLB Stats', ['scores, games, schedules'], feed('scores'), true, false],
        ['Cairo Radio', ['off-air audio, roster'], feed('cairo'), true, true], ['Deepgram', ['Aura voices'], k ? !!k.ready.key : undefined, true, false]];
      let out = '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 10 5 0 10z" fill="#46515b"/></marker></defs>';
      let intoWeb = 0, intoMaster = 0;
      ext.forEach(([t, l, ok, web, master], i) => {
        const y = 32 + i * 51;
        out += box(10, 10 + i * 51, 210, 44, t, l, ok, 'ext');
        if (web) { const ty = 40 + (intoWeb++) * 20; out += `<path class="wire" d="M220 ${y} C262 ${y} 258 ${ty} 300 ${ty}" marker-end="url(#ar)"/>`; }
        if (master) { const ty = 245 + (intoMaster++) * 22; out += `<path class="wire" d="M220 ${y} C262 ${y} 258 ${ty} 300 ${ty}" marker-end="url(#ar)" stroke-dasharray="${web ? '3 3' : ''}"/>`; }
      });
      out += box(300, 20, 330, 175, 'vizelvision-web  :6970', ['API + these pages (stdlib HTTP)', 'Up next (source_queue) · coordinator', 'Programming + follow-games · projector', 'Continuity (announcer renders)', 'Crawl desk · ledger · feeds', 'Roku capture + navigation (ECP)', 'Production monitor (viewer Roku)'], true);
      out += box(300, 225, 330, 150, 'vizelvision-master', ['GStreamer master worker (NVENC)', 'inputs: TV-Thing · Roku · files · ID', 'crawl layers 1–2 · EAS + NWS pollers', 'clock · off-air card · Cairo audio', 'state: ' + (m.state || '—')], m.state === 'live');
      out += `<path class="wire" d="M465 195 L465 225" marker-end="url(#ar)"/><text class="muted" x="475" y="214">unix socket · master.sock</text>`;
      out += box(700, 225, 180, 80, 'mediamtx', ['RTSP :18554/master', 'HLS for monitors'], m.publisher_ready);
      out += `<path class="wire" d="M630 265 L700 265" marker-end="url(#ar)"/>`;
      out += box(930, 150, 160, 60, 'Viewers', ['VizelVision Roku app'], S.monitor?.last_check?.status === 'healthy');
      out += box(930, 230, 160, 60, 'Browsers', ['monitor · previews'], undefined);
      out += box(930, 310, 160, 60, 'Apache', ['/vizelvision/ → :6970'], undefined);
      out += `<path class="wire" d="M880 255 C905 255 905 180 930 180" marker-end="url(#ar)"/><path class="wire" d="M880 265 L930 260" marker-end="url(#ar)"/><path class="wire" d="M630 60 L905 60 L905 340 L930 340"/>`;
      out += `<text class="muted" x="300" y="402">Lamps are live: green working, amber trouble, grey unknown. Dashed: also read by master.</text>`;
      out += `<text class="muted" x="300" y="418">Restart web: Up next pauses and a Roku feed drops. Restart master: what is on air drops.</text>`;
      $('map').innerHTML = out;
    };
    for (const [path, ms, name] of [['v1/master', 5000, 'master'], ['v1/crawl', 15000, 'crawl'], ['v1/continuity', 30000, 'continuity'], ['v1/sources', 60000, 'sources'], ['v1/roku/status', 30000, 'rokuStatus'], ['v1/production/monitor', 60000, 'monitor']])
      stops.push(VV.watch(path, ms, (data, w) => { if (!w.error) { S[name] = data; draw(); } }));
    draw();
  }
  document.querySelectorAll('[data-machinery]').forEach(a => a.addEventListener('click', () => VV.store.set('machinery', true)));

  /* The API explorer -------------------------------------------------------------------------------------------------------- */
  const today = new Date().toISOString().slice(0, 10);
  const ENDPOINTS = {
    'Master and Up next': [['GET', 'v1/master', 'what master is doing'], ['GET', 'v1/queue', 'Up next, holds, scheduled shows'], ['GET', 'v1/playback', 'what will air, next 24 h'],
      ['GET', 'v1/master/end-options?source_id=youtube-tv&channel_id=NBC', 'how a take could end'], ['POST', 'v1/queue/pause', 'pause Up next', '{}'], ['POST', 'v1/queue/resume', 'resume Up next', '{}']],
    'Schedule': [['GET', 'v1/programming', 'grid, blocks, shows, timeline'], ['POST', 'v1/programming/follow-games', 'check the sports feeds now', '{}'], ['POST', 'v1/programming/take-current', 'queue the current block', '{}']],
    'Sources': [['GET', 'v1/sources', 'the catalog'], ['GET', 'v1/sources/tv-thing-digital/programs', 'TV-Thing guide'], ['GET', 'v1/sources/library/programs', 'the media library'], ['GET', 'v1/sources/youtube-tv/programs', 'YouTube TV channels'], ['GET', 'v1/channels', 'YouTube TV channels (from TV Thing)']],
    'Sports': [['GET', 'v1/sports/upcoming?league=mlb&days=3', 'MLB, next 3 days'], ['GET', 'v1/sports/week?league=nfl', 'this NFL week'], ['GET', 'v1/sports/games?league=nhl&date=' + today, 'NHL today'], ['GET', 'v1/sports/teams?league=nwsl', 'NWSL teams'], ['GET', 'v1/baseball/games', 'legacy MLB catalog']],
    'Crawl': [['GET', 'v1/crawl', 'settings, worker status, rotation'], ['GET', 'v1/crawl/alerts', 'the register and the plan'], ['GET', 'v1/crawl/bus-routes', 'WMATA bus routes'], ['POST', 'v1/crawl/run', 'run a segment now', '{"segment": "scores"}']],
    'Presentation': [['GET', 'v1/production', 'off-air card settings'], ['GET', 'v1/continuity', 'announcers, roster, next break'], ['GET', 'v1/production/monitor', 'the viewer monitor']],
    'Roku (TV Thing)': [['GET', 'v1/roku/status', 'the source Roku, from TV Thing'], ['GET', 'v1/operation', 'its navigation'], ['POST', 'v1/operation/cancel', 'stop its navigation', '{}']],
    'Legacy and service': [['GET', 'health', 'web service health'], ['GET', 'v1/jobs', 'legacy scheduler jobs']],
  };
  let built = false;
  function startApi() {
    if (built) return; built = true;
    const box = $('endpoints');
    for (const [group, list] of Object.entries(ENDPOINTS)) {
      box.append(h('h3', group));
      for (const [method, path, what, body] of list) {
        const b = h('button', {type: 'button'}, h('span', h('b', {style: {color: method === 'GET' ? 'var(--pvw)' : 'var(--warn)'}}, method), ' ' + path), h('small', what));
        b.onclick = () => { $('api-method').value = method; $('api-path').value = path; $('api-body').value = body || '{}'; methodChanged(); if (method === 'GET') send(); };
        box.append(b);
      }
    }
  }
  function methodChanged() { const get = $('api-method').value === 'GET'; $('api-body-field').hidden = get || $('api-method').value === 'DELETE'; $('api-warn').hidden = get; }
  $('api-method').onchange = methodChanged;
  async function send() {
    const method = $('api-method').value, path = $('api-path').value.trim().replace(/^\/+/, '');
    let body;
    if (method !== 'GET') {
      if (method === 'POST') { try { body = JSON.parse($('api-body').value || '{}'); } catch { toast('The body is not valid JSON.', {error: true}); return; } }
      if (!await VV.confirm(method + ' ' + path, {title: 'Change the station?', ok: 'Send', danger: true, detail: 'This request can change what is on air or saved settings.'})) return;
    }
    const started = performance.now();
    $('api-meta').textContent = 'Sending…';
    try {
      const response = await api(path, body, {method, raw: true, timeout: 60000});
      const text = await response.text(), took = Math.round(performance.now() - started);
      let value; try { value = JSON.parse(text); } catch { value = null; }
      $('api-meta').textContent = response.status + ' · ' + took + ' ms · ' + fmt.bytes(text.length);
      VV.fill($('api-out'), value === null ? h('pre', {class: 'json'}, text.slice(0, 20000)) : VV.json(value));
    } catch (e) { $('api-meta').textContent = 'failed'; VV.fill($('api-out'), h('p', {class: 'note bad'}, e.message)); }
  }
  $('api-send').onclick = send;
  $('api-path').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

  /* Interface -------------------------------------------------------------------------------------------------------------------- */
  function startInterface() {
    $('pref-machinery').checked = VV.machinery.on; $('pref-palette').checked = VV.store.get('palette', true); $('pref-seconds').checked = VV.store.get('clockSeconds', true);
    $('key-state').textContent = VV.key ? 'An API key is saved in this browser.' : 'No API key saved (this server may not need one).';
    const draw = () => {
      const rows = [...VV.watchers.values()].map(w => h('tr', h('td', {class: 'mono small'}, w.path), h('td', {class: 'mono small'}, Math.min(...[...w.subs].map(s => s.ms)) / 1000 + ' s'),
        h('td', {class: 'small'}, w.subs.size), h('td', {class: 'mono small'}, w.at ? fmt.rel(w.at) : '—'), h('td', {class: 'mono small'}, Math.round(w.took) + ' ms'), h('td', {class: 'small'}, w.error ? h('span', {style: {color: 'var(--warn)'}}, w.error.message) : 'ok')));
      VV.fill($('watchers'), h('thead', h('tr', ['Endpoint', 'Every', 'Users', 'Last', 'Took', 'Status'].map(t => h('th', t)))), h('tbody', rows));
    };
    draw(); const timer = setInterval(draw, 1000); stops.push(() => clearInterval(timer));
  }
  $('pref-machinery').onchange = e => VV.machinery.set(e.target.checked);
  $('pref-palette').onchange = e => { VV.store.set('palette', e.target.checked); toast(e.target.checked ? 'Command palette on (Ctrl/⌘-K).' : 'Command palette off.'); };
  $('pref-seconds').onchange = e => VV.store.set('clockSeconds', e.target.checked);
  $('show-keys').onclick = () => VV.shortcuts();
  $('forget-key').onclick = () => { VV.setKey(''); $('key-state').textContent = 'API key forgotten.'; };

  VV.commands.add(tabs.map(t => ({id: 'eng:' + t.dataset.tab, title: 'Engineering: ' + t.textContent.toLowerCase(), group: 'Engineering', run: () => show(t.dataset.tab)})));
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  show(location.hash.slice(1) || tab);
})();
