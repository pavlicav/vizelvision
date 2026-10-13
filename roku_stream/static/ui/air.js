// On Air: what master is putting out, what is prepared next, Up next, and the station around it.
(() => {
  'use strict';
  const {h, api, fmt, toast, label, same, $} = VV;
  const id = name => document.getElementById(name);
  let master = {}, queue = null, sending = false, commandError = '';
  const card = TestCard.create('master');
  id('master-view').prepend(card);
  // On air but not watching: say so, rather than a black box.
  const dark = h('button', {id: 'dark', class: 'dark', type: 'button', hidden: true}, h('span', {class: 'lamp pgm'}), 'On air · ▶ Watch master');
  dark.onclick = () => watchMaster();
  id('master-view').append(dark);
  const upNext = UpNext.mount(id('queue-host'), {find: Find.box()});
  const strip = CrawlBar.screen({strip: true}); id('crawl-strip').append(strip);

  /* Names: the catalog and the library, so files and channels read well -------------------- */
  async function learn() {
    try {
      const catalog = await api('v1/sources');
      VV.known.sources = catalog.sources || [];
      for (const s of VV.known.sources.filter(s => s.configured && (s.id === 'library' || s.id === master.on_air?.source_id || s.id === master.prepared?.source_id)))
        VV.known.programs.set(s.id, await api('v1/sources/' + encodeURIComponent(s.id) + '/programs').catch(() => VV.known.programs.get(s.id)));
      render(); upNext.render();
    } catch {}
  }

  /* Master ------------------------------------------------------------------------------------------ */
  const STATES = {live: 'pgm', fallback: 'warn', reconnecting: 'warn', starting: 'warn', stopped: '', unavailable: 'warn', not_configured: ''};
  function render() {
    const m = master, connected = !['not_configured', 'unavailable', undefined].includes(m.state);
    const onAir = m.on_air;
    id('pgm-lamp').className = 'lamp ' + (onAir ? 'pgm' : connected ? '' : 'warn');
    id('pgm').classList.toggle('live', !!onAir);
    id('master-state').textContent = connected ? (m.publisher_ready ? m.state : m.state + ' · publisher not ready') : 'not connected';
    id('master-state').className = 'chip ' + (STATES[m.state] || '');
    VV.fill(id('bug'), onAir ? h('span', {class: 'chip solid pgm'}, 'PGM') : h('span', {class: 'chip'}, 'OFF AIR'),
      m.ident?.on_air ? h('span', {class: 'chip warn'}, 'Station ID') : null, waitChip(m), m.crawl?.on_air ? h('span', {class: 'chip touch'}, 'Crawl') : null,
      adMuteChip(m));
    const title = !connected ? 'Master not connected' : onAir ? (onAir.source_id === 'ident' ? 'Station ID' : label(onAir).replace(/^[^·]+ · /, '')) : 'Test card';
    id('pgm-title').textContent = title;
    const aired = onAir && queue?.items?.find(i => i.status === 'succeeded' && same(i.target, onAir));
    id('master-detail').textContent = !connected ? 'Browse sources and the schedule here; start the master worker to put things on air through Up next.'
      : !m.publisher_ready ? 'Waiting for the master publisher to become ready.'
      : onAir ? [label(onAir).split(' · ')[0], aired?.origin === 'programming' ? 'Schedule · ' + (aired.title || 'block') : aired?.program?.title, onAir.resolved_source?.label].filter(Boolean).join(' · ')
      : 'Nothing on master: viewers see the off-air card.' + (m.recovery ? ' Recovering ' + label(m.recovery.target) + '…' : '');
    const media = ['library', 'ident'].includes(onAir?.source_id) ? onAir.media : null;
    id('progress-wrap').hidden = !(media && media.duration_seconds);
    if (media?.duration_seconds) {
      id('master-progress').style.width = Math.min(100, 100 * (media.position_seconds || 0) / media.duration_seconds) + '%';
      id('pos').textContent = fmt.dur(media.position_seconds); id('dur').textContent = '−' + fmt.dur(media.duration_seconds - (media.position_seconds || 0)) + ' · ' + fmt.dur(media.duration_seconds);
    }
    const hold = queue?.hold;
    id('hold-row').hidden = !(connected && onAir && hold && same(onAir, hold.target));
    if (!id('hold-row').hidden) { id('hold-text').textContent = 'On air ' + UpNext.holdText(hold); id('hold-change-main').hidden = !!hold.ending; }
    card.hidden = !!onAir || monitorWanted;
    id('master-video').hidden = !monitorWanted;
    id('dark').hidden = !(onAir && !monitorWanted);
    id('watch-master').disabled = !m.preview_enabled || monitorWanted;
    id('prepared-label').textContent = m.recovery ? 'Recovering: ' + label(m.recovery.target) : m.prepared ? label(m.prepared) + (m.prepared.after_input_id ? ' · cued to follow the current file' : '')
      : m.operation?.state === 'pending' ? 'Working: ' + (m.operation.action === '_queue' ? 'queued prepare and take' : m.operation.action) + '…' : 'Nothing prepared';
    id('pvw-lamp').className = 'lamp ' + (m.prepared ? 'pvw' : m.recovery || m.operation?.state === 'pending' ? 'warn blink' : '');
    id('master-controls').hidden = !connected;
    id('cancel-prepare').disabled = (!m.prepared && !m.recovery && m.operation?.state !== 'pending') || sending;
    id('cancel-prepare').textContent = m.recovery ? 'Cancel recovery' : 'Cancel preparation';
    id('fallback').disabled = sending || !m.publisher_ready;
    const errors = [commandError, m.error, m.operation?.state === 'failed' ? m.operation.error : null, m.cleanup_warning, m.production_error].filter((v, i, a) => v && a.indexOf(v) === i);
    if (m.error && m.last_input_failure?.error === m.error) errors.push(label(m.last_input_failure.target));
    id('master-error').textContent = errors.join(' · ');
    adMuteRow(m);
    flow();
  }
  /* The wait fill: ads over the station ID's held end card while the next source gets ready,
     then "We now join..." before a game in progress (my_ads status: state fill). */
  function waitChip(m) {
    const fill = m.ident?.on_air && m.ident.fill, ads = m.my_ads;
    if (!fill) return null;
    const what = ads?.fill?.joined ? 'We now join…' : ads?.state === 'fill' && (ads.ad || ads.promo) ? 'Ad while the next program gets ready'
      : fill.state === 'finishing' ? 'Next program ready' : 'Next program getting ready';
    return h('span', {class: 'chip ' + (ads?.fill?.joined ? 'solid pvw' : 'touch'), title: 'The station ID holds its end card; ads fill the wait'}, what);
  }
  /* Ad mute: a tally while a break is muted (or would be, in shadow), and the two quick fixes. */
  function adMuteChip(m) {
    const a = m.admute, live = a?.on_air;
    if (!live || a.mode === 'off' || !['muted', 'held'].includes(live.state)) return null;
    return a.mode === 'on' ? h('span', {class: 'chip solid pgm'}, 'Ad muted') : h('span', {class: 'chip warn'}, 'AD · shadow');
  }
  function adMuteRow(m) {
    const a = m.admute, live = a?.on_air;
    id('admute-row').hidden = !(m.on_air && live && a.mode !== 'off');
    if (id('admute-row').hidden) return;
    const quiet = ['muted', 'held'].includes(live.state);
    const states = {listening: 'listening', paused: 'paused for this program', starting: 'starting'};
    id('admute-chip').className = 'chip ' + (quiet ? (a.mode === 'on' ? 'pgm' : 'warn') : a.connected && live.fresh ? 'pvw' : 'warn');
    id('admute-chip').textContent = a.mode === 'shadow' ? 'Ad mute · shadow' : 'Ad mute';
    id('admute-text').textContent = !a.connected || !live.fresh ? 'detector not answering: the sound is left alone'
      : quiet ? (a.mode === 'on' ? 'muted: ad break' : 'would mute: ad break') + (live.p_ad != null ? ' · ' + Math.round(100 * live.p_ad) + '%' : '')
      : states[live.state] || live.state;
    id('admute-show').disabled = id('admute-ad').disabled = sending;
    // What a fix applies to: the picture on master now, which the detector saw a delay ago.
    const delay = m.captions?.programme_delay?.seconds ?? 4;
    VV.adPicture(id('admute-shot'), m.on_air.id, Math.floor(Date.now() / 1000 - delay));
  }
  async function adMute(action) {
    if (id('admute-row').hidden) return;
    try { await api('v1/admute/override', {action}); toast(action === 'unmute' ? 'Sound back; marked as the programme.' : 'Muted; marked as an ad.', {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
    finally { VV.poke('v1/master'); }
  }
  id('admute-show').onclick = () => adMute('unmute');
  id('admute-ad').onclick = () => adMute('mute');
  VV.commands.add([
    {id: 'admute:unmute', title: "Ad mute: it's the show (unmute)", group: 'Ad mute', keys: 'u', when: () => !id('admute-row').hidden, run: () => adMute('unmute')},
    {id: 'admute:mute', title: "Ad mute: it's an ad (mute)", group: 'Ad mute', keys: 'a', when: () => !id('admute-row').hidden, run: () => adMute('mute')},
  ]);
  async function command(action) {
    if (sending) return;
    if (action === 'fallback' && !await VV.confirm('Cut master to the fallback test card now? What is on air stops; Up next carries on from there.', {title: 'Return to fallback', ok: 'Cut to fallback', danger: true})) return;
    sending = true; commandError = ''; render();
    try { await api('v1/master/' + action, {}); toast(action === 'fallback' ? 'Master is going to the fallback card.' : 'Preparation cancelled.', {ok: true}); }
    catch (e) { commandError = e.message; }
    finally { sending = false; VV.poke('v1/master'); VV.poke('v1/queue'); }
  }
  id('cancel-prepare').onclick = () => command('cancel');
  id('fallback').onclick = () => command('fallback');
  id('hold-change-main').onclick = () => OnAir.changeEnd({target: master.on_air || queue?.hold?.target, hold: queue?.hold, queue});
  let learnedFor = '';
  VV.watch('v1/master', 2000, (data, w) => {
    if (w.error) { master = {state: 'unavailable', error: w.error.message}; render(); return; }
    master = data; render();
    const key = [master.on_air?.source_id, master.prepared?.source_id].join('|');
    if (key !== learnedFor) { learnedFor = key; learn(); }
  });
  VV.watch('v1/queue', 2000, (data, w) => { if (!w.error) { queue = data; render(); } });
  VV.watch('v1/production', 30000, data => TestCard.set(data.cards));
  setInterval(learn, 120000);

  /* The monitor: master's own HLS output --------------------------------------------------------- */
  const video = id('master-video');
  let player = null, monitorWanted = false, generation = 0, retryTimer = null, lastTime = 0, lastAdvance = 0, problem = null;
  function stopMonitor() {
    monitorWanted = false; generation++; clearTimeout(retryTimer); retryTimer = null;
    if (player) { player.destroy(); player = null; }
    video.pause(); video.removeAttribute('src'); video.load();
    id('monitor-status').textContent = 'Monitor off'; id('stop-monitor').disabled = true; id('mute-master').hidden = true; render();
  }
  async function watchMaster(reconnect = false) {
    const resume = !reconnect || !video.paused;
    if (!reconnect) stopMonitor();
    monitorWanted = true; problem = null; const mine = ++generation;
    card.hidden = true; video.hidden = false; id('stop-monitor').disabled = false; id('watch-master').disabled = true; id('mute-master').hidden = false;
    id('monitor-status').textContent = reconnect ? 'Reconnecting…' : 'Loading…';
    try {
      const next = await VV.play(video, 'v1/master/media/index.m3u8', {backBufferLength: 10, maxBufferLength: 15, maxMaxBufferLength: 30});
      if (!monitorWanted || mine !== generation) { next.destroy(); return; }
      player = next;
      player.on?.(window.Hls?.Events.ERROR, (_e, data) => { if (data.fatal && monitorWanted && mine === generation) retry(); });
      player.on?.(window.Hls?.Events.MANIFEST_PARSED, () => { if (resume && monitorWanted && mine === generation) video.play().catch(() => { id('monitor-status').textContent = 'Press play'; }); });
      lastTime = video.currentTime; lastAdvance = Date.now();
    } catch (e) { if (monitorWanted && mine === generation) { problem = e.message; id('monitor-status').textContent = e.message; id('watch-master').disabled = false; } }
  }
  function retry() {
    if (!monitorWanted || retryTimer) return;
    id('monitor-status').textContent = 'Reconnecting…';
    retryTimer = setTimeout(() => { retryTimer = null; if (monitorWanted) watchMaster(true); }, 3000);
  }
  video.addEventListener('timeupdate', () => { if (monitorWanted && video.currentTime !== lastTime) { lastAdvance = Date.now(); lastTime = video.currentTime; } });
  video.addEventListener('error', () => { if (monitorWanted) retry(); });
  video.addEventListener('click', () => { if (video.paused) video.play().catch(() => {}); });
  setInterval(() => {
    if (!monitorWanted || retryTimer || problem) return;
    if (video.paused) { id('monitor-status').textContent = video.readyState === 0 ? 'Loading…' : 'Paused'; return; }
    const age = Date.now() - lastAdvance;
    id('monitor-status').textContent = age < 2000 && video.readyState >= 3 ? 'Watching · delayed by buffering' : 'Buffering…';
    if (age > 15000) retry();
  }, 1000);
  const muteIcon = () => id('mute-master').replaceChildren(VV.icon(video.muted ? VV.ICONS.mute : VV.ICONS.sound));
  id('mute-master').onclick = () => { video.muted = !video.muted; muteIcon(); id('mute-master').setAttribute('aria-label', video.muted ? 'Unmute the monitor' : 'Mute the monitor'); };
  muteIcon();
  id('watch-master').onclick = () => watchMaster();
  id('stop-monitor').onclick = stopMonitor;
  window.addEventListener('pagehide', stopMonitor);
  VV.commands.add({id: 'air:watch', title: 'Watch master', group: 'On Air', keys: 'w', run: () => monitorWanted ? stopMonitor() : watchMaster()},
    {id: 'air:fallback', title: 'Return master to the fallback card', group: 'On Air', run: () => command('fallback')});

  /* Tiles: the crawl, the next break, the schedule -------------------------------------------------- */
  let register = null;
  VV.watch('v1/crawl/alerts', 10000, (data, w) => { if (!w.error) { register = data; crawlTile(); } });
  function crawlTile() {
    const c = master.crawl;
    CrawlBar.draw(strip, c?.on_air ? {label: c.label, style: c.style, items: c.items || []} : null);
    const kind = c?.on_air ? c.kind : null;
    id('crawl-lamp').className = 'lamp ' + (kind === 'important' ? 'pgm' : kind ? 'touch' : '');
    id('crawl-state').textContent = kind === 'important' ? 'Important news is running' : kind === 'override' ? 'Override on the bar' : kind ? (c.label || 'Bulletin') + ' pop-up' : 'Bar off';
    const slot = register?.plan?.slots?.[0], counts = register?.counts;
    id('crawl-next').textContent = [register ? (register.context ? register.context.replace('_', '-') + ' · ' + register.mode : '') : '',
      slot ? 'next: ' + (slot.segment.replace('_', ' ')) + ' ' + fmt.rel(slot.at) : register?.ready ? 'nothing planned' : '',
      counts ? (register.items.filter(i => i.kind === 'alert').length + ' alerts listed') : ''].filter(Boolean).join(' · ');
  }
  VV.watch('v1/master', 2000, () => crawlTile());
  VV.watch('v1/continuity', 15000, (data, w) => {
    if (w.error) { id('break-who').textContent = '—'; id('break-what').textContent = w.error.message; return; }
    const n = data.next, on = data.settings?.enabled;
    id('break-lamp').className = 'lamp ' + (master.ident?.on_air ? 'pgm' : n ? 'pvw' : '');
    id('break-who').textContent = !on ? 'Plain station ID' : n ? n.name : 'Nothing cued';
    id('break-what').textContent = n ? 'About ' + fmt.when(n.break_at) + ' · after ' + n.just_played + (n.up_next ? ' · before ' + n.up_next : '') : on ? 'Worked out every 20 seconds; nothing is cued over the test card.' : 'Announcements are off.';
    const r = data.ready || {};
    id('break-id').textContent = [master.ident?.ready ? 'ID ready' : 'ID not ready', r.sports ? 'Sports ID ready' : null, r.key === false ? 'no Deepgram key' : null,
      master.last_station_id ? 'last ID ' + fmt.when(master.last_station_id.at) : null].filter(Boolean).join(' · ');
  });
  VV.watch('v1/playback', 30000, (data, w) => {
    if (w.error) return;
    const [cur, next] = data.segments || [];
    id('sched-lamp').className = 'lamp ' + (data.paused ? 'warn' : cur && cur.kind !== 'off_air' ? 'pvw' : '');
    id('sched-now').textContent = cur ? cur.title || label(cur.target) : '—';
    id('sched-now-detail').textContent = cur ? 'until ' + (cur.estimated ? '~' : '') + fmt.clock(cur.end) + (data.paused ? ' · Up next paused' : '') : '';
    id('sched-next').textContent = next ? fmt.clock(next.start) + ' · ' + (next.title || label(next.target)) : '—';
  });

  /* The machinery: the signal path, live ------------------------------------------------------------------ */
  function flow() {
    if (!VV.machinery.on) return;
    const svg = id('flow'), m = master, on = m.on_air, prep = m.prepared;
    const box = (x, y, w, hh, cls, title, lines) => `<g><rect class="box ${cls}" x="${x}" y="${y}" width="${w}" height="${hh}" rx="6"/>`
      + `<text class="title" x="${x + 10}" y="${y + 18}">${title}</text>` + lines.map((t, i) => `<text class="muted" x="${x + 10}" y="${y + 36 + i * 15}">${esc(t)}</text>`).join('') + '</g>';
    const esc = t => String(t ?? '').slice(0, 26).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
    const src = on ? label(on).split(' · ')[0] : 'none';
    svg.innerHTML = '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 10 5 0 10z" fill="#46515b"/></marker></defs>'
      + box(10, 20, 190, 86, on ? 'pgm' : '', 'SOURCES', ['TV-Thing · Roku · Library', 'on air: ' + src, prep ? 'prepared: ' + label(prep).split(' · ')[0] : 'nothing prepared'])
      + box(10, 124, 190, 86, prep ? 'pvw' : '', 'PREVIEW (PVW)', [prep ? label(prep).replace(/^[^·]+ · /, '') : 'empty', m.operation?.state === 'pending' ? 'working: ' + m.operation.action : 'op: ' + (m.operation?.action || '—') + ' ' + (m.operation?.state || ''), m.recovery ? 'recovering' : ''])
      + box(250, 60, 190, 110, on ? 'pgm' : 'warn', 'MASTER (PGM)', ['state: ' + (m.state || '—'), on ? label(on).replace(/^[^·]+ · /, '') : 'fallback card', 'video lag ' + (m.tracks?.video?.lag_seconds ?? '—') + ' s', 'audio lag ' + (m.tracks?.audio?.lag_seconds ?? '—') + ' s'])
      + box(500, 20, 160, 60, m.crawl?.on_air ? 'pvw' : '', 'CRAWL', [m.crawl?.on_air ? (m.crawl.kind + ' · ' + (m.crawl.label || '')) : 'bar off'])
      + box(500, 95, 160, 60, m.ident?.on_air ? 'pgm' : m.ident?.ready ? 'pvw' : 'warn', 'STATION ID', [m.ident?.on_air ? 'on air' + (m.ident.held ? ' · holding end card' : '') : m.ident?.ready ? 'ready · ' + m.ident.duration_seconds + ' s' : 'not ready'])
      + box(500, 170, 160, 50, '', 'CLOCK', ['station clock overlay'])
      + box(720, 60, 170, 110, m.publisher_ready ? 'pvw' : 'warn', 'PUBLISHER → VIEWERS', [m.publisher_ready ? 'publishing' : 'not ready', 'HLS · RTSP · Roku app', m.preview_enabled ? 'monitor available' : 'monitor off'])
      + `<path class="wire ${on ? 'on' : ''}" d="M200 63 C225 63 225 100 250 100" marker-end="url(#arrow)"/>`
      + `<path class="wire" d="M200 167 C225 167 225 135 250 135" marker-end="url(#arrow)"/>`
      + `<path class="wire" d="M500 50 C470 50 470 90 440 95"/><path class="wire" d="M500 125 L440 120"/><path class="wire" d="M500 195 C470 195 470 150 440 150"/>`
      + `<path class="wire ${on ? 'on' : ''}" d="M440 115 L720 115" marker-end="url(#arrow)"/>`;
    const meter = (name, t) => h('div', {class: 'panel inset', style: {padding: '10px 12px'}}, h('div', {class: 'label'}, name),
      h('div', {class: 'mono small'}, t ? 'lag ' + (t.lag_seconds ?? '—') + ' s · age ' + (t.age_seconds ?? '—') + ' s' : '—'),
      h('div', {class: 'mono tiny muted'}, t ? (t.buffers ?? 0).toLocaleString() + ' buffers' + (t.backwards ? ' · ' + t.backwards + ' backwards' : '') + (t.late_dropped ? ' · ' + t.late_dropped + ' late' : '') : ''));
    id('tracks').replaceChildren(meter('Master video', m.tracks?.video), meter('Master audio', m.tracks?.audio),
      meter('Input video', m.input_tracks?.on_air?.video), meter('Input audio', m.input_tracks?.on_air?.audio));
  }
  document.addEventListener('vv:machinery', flow);
})();
