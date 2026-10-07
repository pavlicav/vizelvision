// Ads › Ad mute: the mode, the quick fixes, recent breaks to mark, settings, and the last hour.
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const panel = $('panel-admute');
  let view = null, dirty = false, busy = false;

  const STATES = {
    listening: ['Listening', ''], muted: ['Muted · ad break', 'muted-now'],
    held: ['Muted by you', 'muted-now'], paused: ['Paused for this program', ''], starting: ['Starting', ''],
  };
  const time = s => s ? new Date(s * 1000).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit', second: '2-digit'}) : '—';
  const sens = v => v < .25 ? 'cautious' : v > .75 ? 'eager' : v < .45 ? 'careful' : v > .55 ? 'keen' : 'balanced';
  const ENDS = {show: 'programme back', retracted: 'retracted (not sure)', capped: 'longest mute reached', gated: 'play resumed (MLB feed)',
    override: 'you unmuted', ended: 'source changed', paused: 'paused'};

  function input() {
    const d = view?.detector, key = view?.on_air?.id;
    return d?.inputs?.find(i => i.input === key) || null;
  }

  // Pictures. The detector keeps one a second for three hours, named by the second it saw
  // it; that airs `delay` seconds later (the shared programme delay). Times on this page
  // are air times, as the clock on screen shows them.
  const delay = () => +view?.delay || 0;
  const air = t => t + delay();
  const picture = VV.adPicture;
  const shotBox = (key, sec, stamp) => {
    const box = h('div', {class: 'shot'}, h('img', {alt: stamp ? 'Picture at ' + stamp : ''}), stamp ? h('span', {class: 'stamp'}, stamp) : null);
    picture(box, key, sec);
    return box;
  };
  // The detector's call for a second: [P(ad), muted] from the last hour's timeline.
  function caller(live) {
    const calls = new Map((live?.timeline || []).map(([t, p, m]) => [Math.round(t), [p, m]]));
    return sec => calls.get(Math.round(sec)) || calls.get(Math.round(sec) - 1) || calls.get(Math.round(sec) + 1) || null;
  }
  const barClass = c => 'call-bar' + (!c ? '' : c[1] ? ' ad' : c[0] >= .5 ? ' maybe' : '');
  const callText = c => !c ? '' : c[1] ? (view.settings.mode === 'on' ? 'muted' : 'would mute') : c[0] >= .5 ? 'ad?' : '';

  function render() {
    if (!view) return;
    const s = view.settings, w = view.worker || {}, d = view.detector, live = input();
    document.querySelectorAll('#mode [data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === s.mode)));
    detectorChoice(s, d);
    const mode = s.mode;
    const detectorUp = d && !view.detector_stale;
    $('detector-chip').textContent = !detectorUp ? 'detector offline' : w.connected ? 'detector linked' : 'detector up · master not linked';
    $('detector-chip').className = 'chip ' + (detectorUp && w.connected ? 'pvw' : 'warn');
    let status = 'Nothing analysed on air', cls = '', detail = '';
    if (mode === 'off') { status = 'Off'; detail = 'Nothing is analysed. Switch to Shadow to try it without touching the sound.'; }
    else if (!view.on_air) detail = 'Master is on the test card.';
    else if (!live) detail = 'The source on air is not analysed (it was prepared before ad mute was on, or its kind is switched off).';
    else {
      const [text, c] = STATES[live.state] || [live.state, ''];
      status = mode === 'shadow' && live.muted ? 'Would mute · ad break' : text;
      cls = mode === 'shadow' && live.muted ? 'shadow-now' : c;
      detail = [live.behind > 1.5 ? `⚠ detection ${live.behind.toFixed(1)} s behind: mutes land late or not at all` : null,
        live.title, live.detector === 'new' ? 'new detector' : null, live.known_now ? 'a known ad is playing' : null, live.game ? 'MLB feed ' + (live.gate || 'quiet') : null,
        'analysed ' + fmt.dur(live.analysed_seconds), live.lookahead + ' s lookahead'].filter(Boolean).join(' · ');
    }
    $('status').textContent = status; $('status').className = 'status-big ' + cls;
    $('status-detail').textContent = detail;
    const why = live?.why;
    $('why').hidden = !why;
    if (why) $('why').textContent = 'Why: ' + why.filter(Boolean).join(' — ');
    const heard = live?.heard;
    $('heard').hidden = !heard;
    if (heard) $('heard').textContent = 'Hears: “' + heard[1] + '”';
    overlays(live);
    $('lamp').className = 'lamp ' + (live?.muted ? (mode === 'on' ? 'pgm' : 'warn') : live ? 'pvw' : '');
    const p = live?.p_ad;
    $('p-meter').style.width = (p == null ? 0 : Math.round(100 * p)) + '%';
    $('p-text').textContent = p == null ? 'P(ad) —' : 'P(ad) ' + Math.round(100 * p) + '%';
    const canFix = !!live && mode !== 'off' && !busy;
    $('unmute').disabled = $('mute').disabled = !canFix;
    $('unmute').textContent = mode === 'shadow' ? "It's the show" : "It's the show · unmute";
    $('mute').textContent = mode === 'shadow' ? "It's an ad" : "It's an ad · mute";
    const paused = s.paused_until && s.paused_until * 1000 > Date.now();
    $('pause').hidden = paused; $('resume').hidden = !paused; $('pause').disabled = !view.on_air || mode === 'off';
    $('error').textContent = [w.error, !detectorUp && mode !== 'off' ? 'The detector (vizelvision-admute) is not running: nothing is muted.' : null].filter(Boolean).join(' · ');
    pictures(live);
    spans(live);
    knownPanel(d, live, s);
    timeline(live);
    const sp = d?.speech, words = s.speech === false ? 'not listening' : !sp ? null : !sp.usable ? 'Whisper unavailable'
      : 'Whisper ' + sp.model + (sp.load != null ? ' · busy ' + Math.round(100 * sp.load) + '%' : '')
        + (sp.lag != null ? ' · words up to ' + sp.lag + ' s late' : '') + (sp.dropped ? ' · ' + sp.dropped + ' windows dropped' : '');
    const fp = d?.prints, known = s.known_ads === false ? 'not fingerprinting' : !fp ? null
      : fp.ads + ' known ads' + (fp.ad_candidates > fp.ads ? ' (' + (fp.ad_candidates - fp.ads) + ' heard once)' : '') + ' · ' + fp.show + ' show sounds';
    $('model').textContent = [d?.model?.trained_on ? 'model: ' + d.model.trained_on.length + ' recordings' : null, words, known].filter(Boolean).join(' · ');
    $('model').title = sp?.error || '';
    if (!dirty) fill(s);
  }

  // The graphics it knows on this input: which are up now, which count (admute/overlays.py).
  function overlays(live) {
    const list = live?.overlays || [];
    const el = $('overlays');
    el.hidden = !list.length;
    if (!list.length) return;
    const up = list.filter(o => o.up && o.state === 'counts').map(o => o.name);
    const checking = list.filter(o => o.state === 'checking').map(o => o.name);
    const ignored = list.filter(o => o.state === 'ignored').map(o => o.name + (o.why ? ' (' + o.why + ')' : ''));
    el.textContent = [up.length ? 'On screen: ' + up.join(', ') : 'No known graphics on screen',
      checking.length ? 'checking ' + checking.join(', ') : null,
      ignored.length ? 'not counted: ' + ignored.join(', ') : null].filter(Boolean).join(' · ');
  }

  // What is on master now, and the half-minute before it (the operator's player is behind).
  function pictures(live) {
    $('now').hidden = !live;
    if (!live) { VV.fill($('strip')); return; }
    const now = Math.floor(Date.now() / 1000 - delay()), call = caller(live), c = call(now);
    picture($('now-shot'), live.input, now);
    $('now-stamp').textContent = time(air(now));
    $('now-call').textContent = callText(c); $('now-call').className = 'call' + (c?.[1] ? ' ad' : '');
    $('now-call').hidden = !callText(c);
    const strip = $('strip'), base = Math.floor(now / 3) * 3;
    if (strip.dataset.base === String(base) && strip.dataset.key === live.input) {
      strip.querySelectorAll('.frame').forEach(f => { f.querySelector('.call-bar').className = barClass(call(+f.dataset.sec)); });
      return;
    }
    strip.dataset.base = base; strip.dataset.key = live.input;
    const frames = [];
    for (let i = 9; i >= 0; i--) {
      const sec = base - 3 * i, ago = now - sec;
      frames.push(h('button', {class: 'frame', type: 'button', 'data-sec': sec, title: time(air(sec)) + ' · click to see it larger',
        onclick: () => sheet(live, {start: sec - 6, end: sec + 6, title: 'Around ' + time(air(sec))})},
        shotBox(live.input, sec), h('span', {class: barClass(call(sec))}), h('span', {class: 't'}, ago ? '−' + ago + ' s' : 'now')));
    }
    VV.fill(strip, ...frames);
  }

  // A break's pictures, every few seconds from just before it to just after, to judge it by.
  function sheet(live, {start, end, title, span}) {
    const len = end - start, step = Math.max(2, Math.ceil(len / 15)), call = caller(live), cells = [];
    for (let sec = Math.round(start); sec <= end; sec += step) {
      const c = call(sec), cell = h('div', {class: 'stack tight'}, shotBox(live.input, sec, time(air(sec))),
        h('span', {class: barClass(c)}), h('span', {class: 'tiny muted'}, callText(c) || ' '));
      cells.push(cell);
    }
    const close = h('button', {class: 'sm', type: 'button'}, 'Close');
    const marks = span ? [h('button', {class: 'sm', type: 'button', onclick: () => { markSpan(span, 'ad', live); dialog.close(); }}, 'Ad ✓'),
      h('button', {class: 'sm', type: 'button', onclick: () => { markSpan(span, 'show', live); dialog.close(); }}, 'Was the show')] : [];
    const dialog = h('dialog', {class: 'break', 'aria-label': title}, h('div', {class: 'head'}, h('h2', title)),
      h('div', {class: 'body stack'}, h('div', {class: 'sheet'}, ...cells),
        h('p', {class: 'tiny muted'}, 'Times are as the clock on screen showed them. Under each picture: red, muted (or would mute); amber, the detector leaned ad.'),
        h('div', {class: 'actions'}, ...marks, close)));
    close.onclick = () => dialog.close();
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog); dialog.showModal();
  }

  function spans(live) {
    const marks = new Map((view.labels || []).filter(l => l.span_id).map(l => [l.span_id, l.label]));
    const rows = (live?.spans || []).slice().reverse().map(sp => {
      const mark = marks.get(sp.id);
      const end = sp.end || Date.now() / 1000 - delay(), len = end - sp.start;
      const btn = (label, text) => h('button', {class: 'xs' + (mark === label ? ' primary' : ''), type: 'button',
        onclick: () => markSpan(sp, label, live)}, text);
      const title = 'Break at ' + time(air(sp.start));
      const edges = h('button', {class: 'frame', type: 'button', title: 'Before it, its start, and after it: click for the whole break',
        onclick: () => sheet(live, {start: sp.start - 6, end: end + 6, title, span: sp})},
        h('div', {class: 'edges'}, shotBox(live.input, sp.start - 3), shotBox(live.input, sp.start + 2),
          sp.end ? shotBox(live.input, sp.end + 3) : h('div', {class: 'shot none'})));
      return h('tr', null, h('td', {class: 'when'}, time(air(sp.start))), h('td', null, edges), h('td', null, fmt.dur(len)),
        h('td', null, sp.start_reason === 'override' ? 'you' : (sp.confirmed ? 'AD' : 'AD?') + ' · ' + Math.round(100 * sp.peak) + '%',
          sp.known >= KNOWN ? [' ', h('span', {class: 'tag known', title: 'Its sound matched an ad heard before'}, 'known ad')] : null,
          sp.why ? h('div', {class: 'tiny muted'}, sp.why.filter(Boolean).join(' — ')) : null),
        h('td', {class: 'small'}, sp.end ? ENDS[sp.end_reason] || sp.end_reason : 'now'),
        h('td', {class: 'nowrap'}, btn('ad', 'Ad ✓'), ' ', btn('show', 'Was the show')));
    });
    VV.fill($('spans'), ...rows);
    $('spans-empty').hidden = rows.length > 0;
  }

  function timeline(live) {
    const c = $('timeline'), g = c.getContext('2d');
    const W = c.width = c.clientWidth * devicePixelRatio || 900, H = c.height = 120 * devicePixelRatio;
    g.clearRect(0, 0, W, H);
    const now = Date.now() / 1000, from = now - 3600, x = t => (t - from) / 3600 * W;
    const css = getComputedStyle(document.documentElement), col = n => css.getPropertyValue(n).trim() || '#888';
    if (!live) return;
    g.fillStyle = col('--pgm') + '55';
    for (const sp of live.spans || []) g.fillRect(x(sp.start), 0, Math.max(1, x(sp.end || now) - x(sp.start)), H);
    g.fillStyle = col('--ink');
    for (const [t, kind] of live.seams || []) if (kind === 'black') g.fillRect(x(t), H * .82, Math.max(1, devicePixelRatio), H * .18);
    g.strokeStyle = col('--warn'); g.lineWidth = 1.5 * devicePixelRatio; g.beginPath();
    let first = true;
    for (const [t, p] of live.timeline || []) { const px = x(t), py = H - 4 - p * (H - 8); if (first) { g.moveTo(px, py); first = false; } else g.lineTo(px, py); }
    g.stroke();
  }

  // Known ads: what the fingerprint database holds, and what it learnt or forgot lately.
  const KNOWN = 0.18;   // the detector's own "clearly a known ad" (detector.KNOWN_CLEAR)
  const ago = t => time(t);
  function knownPanel(d, live, s) {
    const fp = d?.prints;
    $('known-chip').textContent = s.known_ads === false ? 'off' : fp ? fp.ads + ' known' : '—';
    $('known-chip').className = 'chip' + (s.known_ads === false ? ' warn' : fp ? ' pvw' : '');
    $('known-summary').textContent = s.known_ads === false ? 'Off: the sound is not fingerprinted, and nothing is learnt.'
      : !fp ? 'The detector has not reported its database yet.'
      : `${fp.ads} known ads, ${fp.seeded} of them from recordings and games, plus ${fp.ad_candidates - fp.ads} heard once (they count when heard again) `
        + `and ${fp.show} show sounds that are never ads.`;
    const g = live?.game_learning;
    $('game-learning').hidden = !g || s.learn_games === false || s.known_ads === false;
    if (g) $('game-learning').textContent = `Learning this game's breaks from MLB's play-by-play: ${g.breaks} so far (${g.new} new ads)`
      + (g.lag != null ? ` · the broadcast runs ${g.lag} s behind the feed` : '') + '.';
    const forget = (ids, label) => h('button', {class: 'xs', type: 'button', title: 'Forget it: it will only be learnt again from new breaks',
      onclick: () => forgetClips(ids)}, label || 'Forget');
    const items = (d?.prints_log || []).slice().reverse().map(e => {
      let what, ids = null;
      if (e.what === 'break') {
        what = `A break in ${e.src || 'the programme'} (${fmt.dur(e.dur)}): ${e.spots} ${e.spots === 1 ? 'spot' : 'spots'} kept, `
          + (e.known ? `${e.known} of them now known ads (aired before).` : 'each counts once it airs again.');
        ids = e.clips || (e.clip ? [e.clip] : null);
      } else if (e.what === 'game') {
        what = `${e.src}: ${e.breaks} breaks learnt from MLB's play-by-play, ${e.new} of them new.`;
        ids = e.clips;
      } else if (e.what === 'seed') what = `Recordings (${e.src}): ${e.new} new ads.`;
      else if (e.what === 'forgot') what = `Forgot ${e.clips.length === 1 ? 'an ad' : e.clips.length + ' ads'}: ${e.why}.`;
      else what = e.what;
      return h('li', null, h('span', {class: 'when'}, ago(e.t)), h('span', {class: 'what'}, what), ids?.length ? forget(ids) : null);
    });
    VV.fill($('known-log'), ...items);
    $('known-log-empty').hidden = items.length > 0;
  }
  async function forgetClips(ids) {
    try {
      view = await api('v1/admute/forget', {clips: ids});
      toast(ids.length === 1 ? 'Forgotten. It is learnt again only from new breaks.' : `${ids.length} forgotten.`, {ok: true});
      setTimeout(loadKnown, 1500);
    } catch (e) { toast(e.message, {error: true}); }
    render();
  }
  async function loadKnown() {
    if (!$('known-all').open) return;
    try {
      const k = await api('v1/admute/known');
      const rows = k.clips.map(c => h('tr', null,
        h('td', null, c.kind === 'show' ? h('span', {class: 'tag'}, 'show sound') : c.known ? h('span', {class: 'tag known'}, 'ad') : h('span', {class: 'tag'}, 'heard once')),
        h('td', {class: 'small'}, c.src || (c.seed || '').replace(/^extra.*/, 'recordings') || '—'),
        h('td', null, c.dur ? fmt.dur(c.dur) : '—'), h('td', null, c.seed && c.breaks < 2 ? (c.seed.startsWith('game-') ? 'a game' : 'a recording') : c.breaks + (c.breaks === 1 ? ' break' : ' breaks')),
        h('td', {class: 'when'}, c.last ? new Date(c.last * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : '—'),
        h('td', null, h('button', {class: 'xs', type: 'button', onclick: () => forgetClips([c.id])}, 'Forget'))));
      VV.fill($('known-table'), ...rows);
      $('known-table-note').textContent = k.clips.length ? `${k.clips.length} clips, most recently heard first.` : 'Nothing known yet.';
    } catch (e) { $('known-table-note').textContent = e.message; }
  }

  // Training recordings: what TV-Thing records for training, and what became of it.
  const REC = {scheduled: 'scheduled', recording: 'recording now', recorded: 'recorded · waiting to be learnt',
    processing: 'learning from it…', cancelled: 'cancelled', gone: 'gone from TV-Thing'};
  const at = t => t ? new Date(t * 1000).toLocaleString([], {weekday: 'short', hour: 'numeric', minute: '2-digit'}) : '—';
  function recordings(data) {
    const recs = data?.recordings || [];
    const status = r => r.status === 'processed'
      ? 'learnt' + (r.steps?.known_ads != null ? ` · ${r.steps.known_ads} breaks fingerprinted` : '') + (r.steps?.training_labels ? ' · training labels saved' : '') + ' · in the library'
      : r.status === 'failed' ? 'failed: ' + (r.error || 'see the log') : (REC[r.status] || r.status) + (r.adopted ? ' (your timer)' : '');
    VV.fill($('rec-table'), ...recs.map(r => h('tr', null,
      h('td', null, r.game_title || r.title, r.note ? h('div', {class: 'tiny muted'}, r.note) : null),
      h('td', {class: 'small nowrap'}, r.channel || '—'), h('td', {class: 'when'}, at(r.start)), h('td', {class: 'small'}, status(r)),
      h('td', null, ['scheduled', 'recording'].includes(r.status)
        ? h('button', {class: 'xs', type: 'button', title: r.adopted ? 'Stop learning from it (your TV-Thing timer stays)' : 'Cancel the TV-Thing timer',
            onclick: () => cancelRecording(r)}, 'Cancel') : null))));
    $('rec-empty').hidden = recs.length > 0;
    const busy = recs.filter(r => ['scheduled', 'recording', 'recorded', 'processing'].includes(r.status)).length;
    $('rec-chip').textContent = view?.settings?.record_games === false ? 'off' : busy ? busy + ' planned' : 'idle';
    $('rec-chip').className = 'chip' + (view?.settings?.record_games === false ? ' warn' : busy ? ' pvw' : '');
    VV.fill($('rec-skipped'), ...(data?.skipped || []).map(s => h('li', null, h('span', {class: 'when'}, at(s.start)),
      h('span', {class: 'what'}, `${s.title}: ${s.why}`))));
    $('rec-error').hidden = !data?.error;
    $('rec-error').textContent = data?.error ? 'Planning failed: ' + data.error : '';
  }
  async function cancelRecording(r) {
    if (!await VV.confirm(r.adopted ? 'Your TV-Thing timer stays; this game just will not be learnt from.' : 'The TV-Thing timer is cancelled.',
      {title: `Cancel recording ${r.game_title || r.title}?`, ok: 'Cancel recording', danger: !r.adopted})) return;
    try { recordings(await api('v1/admute/recordings/cancel', {game: r.game})); toast('Cancelled.', {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
  }

  // Classic or new detector: saved at once, like the mode. What runs is the sidecar's call:
  // the new one needs its model and CLIP, and falls back to classic (saying why) without them.
  function detectorChoice(s, d) {
    const known = 'detector' in s, run = d?.detector;
    document.querySelectorAll('#detector [data-detector]').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.detector === (s.detector || 'classic')));
      b.disabled = !known || busy;
    });
    const ms = run?.clip_ms != null ? ` (${run.clip_ms} ms a frame here)` : '';
    $('detector-note').textContent = !known ? 'This web app predates the detector choice.'
      : s.detector === 'new' && run && run.running !== 'new' ? `The new detector cannot run: ${run.error || 'not ready'}. The classic one is running.`
      : s.detector === 'new' && d && !run ? 'The detector sidecar predates the new detector: restart vizelvision-admute to use it.'
      : s.detector === 'new' ? `New: the classic evidence plus a CLIP picture score${ms}, which knows ads it has never seen, and its own weights for the first minutes after a source starts. Uses the known-ads database like classic.`
      : 'Classic: the detector as it has been. New adds a picture score that knows ads it has never seen and settles faster after a source starts; switching starts each input over.';
  }

  function fill(s) {
    $('src-tv').checked = s.sources.tv_thing; $('src-roku').checked = s.sources.roku; $('gate').checked = s.sports_gate;
    $('exceptions').value = s.exceptions.join('\n'); $('sensitivity').value = s.sensitivity; $('max-mute').value = s.max_mute;
    $('lookahead').value = s.lookahead; $('sound').value = s.sound; $('radio-db').value = s.radio_db; $('badge').value = s.badge;
    $('learn').checked = s.learn; $('speech').checked = s.speech !== false; $('speech').disabled = !('speech' in s);
    $('speech-model-row').hidden = !('speech_model' in s); $('speech-model').value = s.speech_model || 'base.en';
    $('known-ads').checked = s.known_ads !== false; $('known-ads').disabled = !('known_ads' in s);
    for (const [id, key] of [['learn-ads', 'learn_ads'], ['learn-games', 'learn_games']]) { $(id).checked = s[key] !== false; $(id).disabled = !(key in s); }
    $('diagnostic').checked = s.diagnostic === true; $('diagnostic').disabled = !('diagnostic' in s);
    $('record-games').checked = s.record_games !== false; $('record-games').disabled = !('record_games' in s);
    labels();
  }
  function labels() {
    $('sens-text').textContent = sens(+$('sensitivity').value);
    $('radio-db-text').textContent = (+$('radio-db').value > 0 ? '+' : '') + $('radio-db').value + ' dB';
    $('radio-level-row').hidden = $('sound').value !== 'radio';
  }
  function values() {
    return {sources: {tv_thing: $('src-tv').checked, roku: $('src-roku').checked}, sports_gate: $('gate').checked,
      exceptions: $('exceptions').value.split('\n').map(x => x.trim()).filter(Boolean), sensitivity: +$('sensitivity').value,
      max_mute: +$('max-mute').value, lookahead: +$('lookahead').value, sound: $('sound').value, radio_db: +$('radio-db').value,
      badge: $('badge').value, learn: $('learn').checked,
      // (A web app older than the Whisper switch rejects the key.)
      ...('speech' in (view?.settings || {}) ? {speech: $('speech').checked} : {}),
      ...('speech_model' in (view?.settings || {}) ? {speech_model: $('speech-model').value} : {}),
      ...('known_ads' in (view?.settings || {}) ? {known_ads: $('known-ads').checked} : {}),
      ...('learn_ads' in (view?.settings || {}) ? {learn_ads: $('learn-ads').checked} : {}),
      ...('learn_games' in (view?.settings || {}) ? {learn_games: $('learn-games').checked} : {}),
      ...('diagnostic' in (view?.settings || {}) ? {diagnostic: $('diagnostic').checked} : {}),
      ...('record_games' in (view?.settings || {}) ? {record_games: $('record-games').checked} : {})};
  }

  async function post(path, body, ok) {
    busy = true; render();
    try { view = await api(path, body); if (ok) toast(ok, {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
    finally { busy = false; render(); }
  }
  async function override(action) {
    busy = true; render();
    try {
      view = await api('v1/admute/override', {action});
      toast(action === 'unmute' ? 'Sound back; marked as the programme.' : 'Muted; marked as an ad.', {ok: true});
    } catch (e) { toast(e.message, {error: true}); }
    finally { busy = false; render(); }
  }
  function markSpan(sp, label, live) {
    post('v1/admute/label', {span_id: sp.id, label, start: sp.start, end: sp.end || Date.now() / 1000, title: live?.title || null},
      label === 'show' ? 'Marked as the programme. Thanks: it learns from this.' : 'Marked as a real ad.');
  }

  $('mode').onclick = async e => {
    const mode = e.target.closest('[data-mode]')?.dataset.mode;
    if (!mode || mode === view?.settings.mode) return;
    if (mode === 'on' && !await VV.confirm('Breaks it finds will go quiet on air. The two big buttons (or u / a) fix a mistake at once.',
      {title: 'Turn ad mute on', ok: 'Turn on'})) return;
    post('v1/admute', {mode}, {off: 'Ad mute is off.', shadow: 'Shadow: the AD badge shows what it would mute.', on: 'Ad mute is on.'}[mode]);
  };
  $('detector').onclick = e => {
    const detector = e.target.closest('[data-detector]')?.dataset.detector;
    if (!detector || detector === (view?.settings.detector || 'classic')) return;
    post('v1/admute', {detector}, detector === 'new' ? 'New detector: each input starts over.' : 'Classic detector: each input starts over.');
  };
  $('unmute').onclick = () => override('unmute');
  $('mute').onclick = () => override('mute');
  $('pause').onclick = () => post('v1/admute/pause', {hours: 6}, 'Paused until this source leaves the air.');
  $('resume').onclick = () => post('v1/admute/pause', {resume: true}, 'Ad mute resumed.');
  $('settings').addEventListener('input', () => { dirty = true; labels(); });
  $('settings').onsubmit = async e => {
    e.preventDefault(); $('save').disabled = true;
    try { view = await api('v1/admute', values()); dirty = false; toast('Saved.', {ok: true}); render(); }
    catch (err) { toast(err.message, {error: true}); } finally { $('save').disabled = false; }
  };
  $('missed').onsubmit = e => {
    e.preventDefault();
    // Clock times from the screen; the detector saw them `delay` seconds earlier.
    const at = v => { const [hh, mm, ss] = v.split(':').map(Number); const d = new Date(); d.setHours(hh, mm, ss || 0, 0); return d.getTime() / 1000 - delay(); };
    const start = at($('missed-from').value), end = at($('missed-to').value);
    if (!(end > start)) { toast('The end must come after the start.', {error: true}); return; }
    post('v1/admute/label', {span_id: 'missed-' + Math.round(start), label: 'ad', start, end, title: input()?.title || null},
      'Recorded as a missed break.');
  };
  VV.commands.add([
    {id: 'admute:unmute', title: "Ad mute: it's the show (unmute)", group: 'Ad mute', keys: 'u', when: () => !panel.hidden && !$('unmute').disabled, run: () => override('unmute')},
    {id: 'admute:mute', title: "Ad mute: it's an ad (mute)", group: 'Ad mute', keys: 'a', when: () => !panel.hidden && !$('mute').disabled, run: () => override('mute')},
  ]);
  addEventListener('resize', () => render());
  $('known-all').addEventListener('toggle', loadKnown);
  // Polled while its tab is shown (ads.js).
  (window.AdsTabs ||= {}).admute = () => {
    const stops = [VV.watch('v1/admute', 2000, (data, w) => { if (!w.error) { view = data; render(); } else $('error').textContent = w.error.message; }),
      VV.watch('v1/admute/recordings', 30000, (data, w) => { if (!w.error) recordings(data); })];
    return () => stops.forEach(stop => stop());
  };
})();
