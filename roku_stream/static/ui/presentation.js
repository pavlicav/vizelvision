// Presentation: the off-air card and its audio, the station clock, continuity, the station ID.
(() => {
  'use strict';
  const {h, api, fmt, toast, label} = VV;
  const $ = id => document.getElementById(id);
  const kinds = ['master', 'tv-thing', 'roku'];
  let data = null, context = null, oscillator = null, continuity = null;

  /* The off-air card ------------------------------------------------------------------------------------------ */
  function values() {
    return {captions: Object.fromEntries(kinds.map(kind => [kind, $(kind + '-caption').value])), details: [...document.querySelectorAll('[name=detail]:checked')].map(node => node.value),
      note: $('note').value, audio: $('audio').value, clock: {enabled: $('clock-enabled').checked, seconds: $('clock-seconds').checked}};
  }
  function tick() {
    const clock = document.querySelector('.tv-clock'); if (!clock || !data) return;
    const c = values().clock, d = new Date(), p = n => String(n).padStart(2, '0');
    clock.hidden = !c.enabled; $('clock-seconds').disabled = !c.enabled;
    clock.textContent = d.getHours() + ':' + p(d.getMinutes()) + (c.seconds ? ':' + p(d.getSeconds()) : '');
  }
  setInterval(tick, 1000);
  function preview() {
    const v = values();
    for (const kind of kinds) {
      const lines = v.details.flatMap(detail => {
        if (detail === 'now_playing') return kind === 'master' && v.audio === 'radio' ? ['(CAIRO RADIO) SHOW', '(ARTIST — TITLE FROM CAIRO RADIO)'] : [];
        if (detail === 'audio') return {tone: '1 kHz SINE · −20 dBFS PEAK · 48 kHz STEREO', silence: 'OFF-AIR AUDIO · SILENCE', radio: 'OFF-AIR AUDIO · CAIRO RADIO'}[v.audio];
        return detail === 'route' ? {master: 'VIZELVISION · MASTER OUTPUT', 'tv-thing': 'TV-THING · SOURCE', roku: 'ROKU · SOURCE'}[kind] : data.format_line;
      });
      if (v.note) lines.push(v.note);
      TestCard.update(document.querySelector('[data-card="' + kind + '"]'), {caption: v.captions[kind], lines});
    }
    tick();
    $('audition').disabled = v.audio !== 'tone';
    if (v.audio !== 'tone') stopTone();
  }
  function fill(settings) {
    for (const kind of kinds) $(kind + '-caption').value = settings.captions[kind];
    $('note').value = settings.note; $('audio').value = settings.audio; $('clock-enabled').checked = settings.clock.enabled; $('clock-seconds').checked = settings.clock.seconds;
    document.querySelectorAll('[name=detail]').forEach(node => { node.checked = settings.details.includes(node.value); });
    preview();
  }
  async function load() {
    try {
      data = await api('v1/production');
      VV.fill($('detail-options'), Object.entries(data.detail_options).map(([value, text]) => h('label', {class: 'check'}, h('input', {type: 'checkbox', name: 'detail', value}), h('span', text))));
      if (!document.querySelector('.test-card')) for (const kind of kinds) {
        const card = TestCard.create(kind), title = {master: 'Master output', 'tv-thing': 'TV-Thing sources', roku: 'Roku sources'}[kind];
        $('previews').append(h('div', {class: 'stack tight'}, h('span', {class: 'label'}, title),
          kind === 'master' ? h('div', {class: 'card-wrap'}, card, h('div', {class: 'tv-clock', hidden: true, 'aria-hidden': 'true'})) : card));
      }
      fill(data.settings);
    } catch (e) { toast(e.message, {error: true}); }
  }
  $('settings').addEventListener('input', preview);
  $('settings').onsubmit = async event => {
    event.preventDefault(); $('save').disabled = true;
    try { const result = await api('v1/production', values()); data.settings = result.settings; toast('Saved. The off-air presentation updates by itself.', {ok: true}); }
    catch (e) { toast(e.message, {error: true}); } finally { $('save').disabled = false; }
  };
  $('reset').onclick = () => {
    fill({captions: {master: 'VIZELVISION MASTER OFF-AIR', 'tv-thing': 'TV-THING OFF', roku: 'ROKU OFF'}, details: ['format', 'audio', 'now_playing', 'route'], note: 'NO PROGRAM LIVE', audio: 'tone', clock: {enabled: false, seconds: false}});
    toast('Defaults previewed. Save to apply.');
  };
  function stopTone() { if (oscillator) { oscillator.stop(); oscillator = null; } if (context) { context.close(); context = null; } $('audition').textContent = '▶ Listen to test tone'; }
  $('audition').onclick = async () => {
    if (oscillator) { stopTone(); return; }
    try {
      context = new AudioContext(); await context.resume();
      const gain = context.createGain(); gain.gain.value = .1;
      oscillator = context.createOscillator(); oscillator.type = 'sine'; oscillator.frequency.value = 1000;
      oscillator.connect(gain); gain.connect(context.destination); oscillator.start();
      $('audition').textContent = '■ Stop test tone';
    } catch (e) { stopTone(); toast(e.message, {error: true}); }
  };
  window.addEventListener('pagehide', stopTone);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopTone(); });

  /* Live captions -------------------------------------------------------------------------------------------------- */
  let captionData = null, captionBusy = false, captionDirty = false;
  function captionState(value) {
    const status = value.status || {}, enabled = value.settings.enabled;
    const error = value.master_error || status.error;
    const states = {off: 'Off', waiting_for_audio: 'Waiting for audio', loading: 'Loading Whisper…',
      transcribing: 'Transcribing…', listening: 'Listening', error: 'Captions unavailable'};
    $('caption-status').textContent = error ? 'Captions unavailable' : status.enabled !== enabled ?
      (enabled ? 'Starting captions…' : 'Stopping captions…') : states[status.state] || 'Waiting for master';
    $('caption-error').textContent = error || '';
    const delay = status.programme_delay?.seconds;
    $('caption-timing').textContent = error ? '' : delay !== undefined ?
      `Shared programme delay: ${delay} s · captions follow audio timestamps` +
      (status.late_cues ? ` · ${status.late_cues} late cues` : '') : '';
    $('caption-preview').textContent = error ? '' : enabled ? status.text || 'No speech transcribed yet.' : 'Captions are off.';
    $('caption-lamp').className = 'lamp ' + (error ? 'warn' : enabled && status.enabled ? 'pvw' : '');
  }
  function captionFill(value) {
    captionData = value;
    $('captions-enabled').checked = value.settings.enabled;
    if (!captionDirty) {
      $('caption-model').replaceChildren(...value.models.map(model => new Option(model, model)));
      $('caption-language').replaceChildren(...Object.entries(value.languages).map(([code, name]) => new Option(name, code)));
      $('caption-model').value = value.settings.model;
      $('caption-language').value = value.settings.language;
    }
    for (const id of ['captions-enabled', 'caption-model', 'caption-language', 'caption-save']) $(id).disabled = captionBusy;
    captionState(value);
  }
  async function saveCaptions(changes) {
    captionBusy = true;
    for (const id of ['captions-enabled', 'caption-model', 'caption-language', 'caption-save']) $(id).disabled = true;
    try {
      const result = await api('v1/captions', changes);
      if ('model' in changes) captionDirty = false;
      captionFill(result);
      toast('Caption settings saved.', {ok: true});
    } catch (e) {
      $('captions-enabled').checked = captionData.settings.enabled;
      toast(e.message, {error: true});
    } finally {
      captionBusy = false;
      for (const id of ['captions-enabled', 'caption-model', 'caption-language', 'caption-save']) $(id).disabled = false;
    }
  }
  $('captions-enabled').onchange = () => saveCaptions({enabled: $('captions-enabled').checked});
  $('caption-settings').oninput = () => { captionDirty = true; };
  $('caption-settings').onsubmit = event => {
    event.preventDefault();
    saveCaptions({model: $('caption-model').value, language: $('caption-language').value});
  };
  VV.watch('v1/captions', 2000, (value, watcher) => {
    if (captionBusy) return;
    if (watcher.error) {
      $('caption-status').textContent = 'Caption status unavailable';
      $('caption-error').textContent = watcher.error.message || String(watcher.error);
      $('caption-preview').textContent = '';
      return;
    }
    captionFill(value);
  });

  /* The station ID ------------------------------------------------------------------------------------------------- */
  let ready = {};
  function renderIdent(master) {
    const id = master.ident || {}, last = master.last_station_id;
    $('id-lamp').className = 'lamp ' + (id.on_air ? 'pgm' : id.ready ? 'pvw' : 'warn');
    const kv = (box, rows) => VV.fill(box, rows.filter(Boolean).map(([k, v]) => [h('dt', k), h('dd', v)]));
    kv($('ident'), [['State', id.on_air ? (id.held ? 'On air · holding its end card' : 'On air') : id.ready ? 'Ready' : 'Not ready'], ['Enabled', id.enabled ? 'Yes' : 'No'],
      ['Length', id.duration_seconds ? id.duration_seconds + ' s' : '—'], ['File', h('code', id.file || '—')], id.error ? ['Error', id.error] : null,
      ['Sports ID', ready.sports === undefined ? '—' : ready.sports ? 'Ready' : 'Not ready'], ['Announcer mix', ready.music ? 'Music bed ready' : 'No music bed']]);
    kv($('last-id'), last ? [['When', fmt.full(last.at) + ' (' + fmt.rel(last.at) + ')'], ['After', label(last.after)], ['Which', /^sports-/.test(last.file || '') ? 'Sports ID' : 'Station ID'], ['File', h('code', last.file || '—')]]
      : [['When', 'No ID since master started']]);
  }

  /* Tabs ------------------------------------------------------------------------------------------------------------- */
  const tabs = [...document.querySelectorAll('[role=tab]')];
  function show(name, focus) {
    const tab = tabs.find(t => t.dataset.tab === name) || tabs[0];
    for (const t of tabs) { const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; $('panel-' + t.dataset.tab).hidden = !on; }
    if (tab.dataset.tab === 'continuity') { continuity ||= ContinuityPanel.mount($('continuity-panel')); continuity.refresh().catch(e => toast(e.message, {error: true})); }
    if (focus) tab.focus();
    if (location.hash !== '#' + tab.dataset.tab) history.replaceState(null, '', '#' + tab.dataset.tab);
  }
  tabs.forEach((t, i) => {
    t.onclick = () => show(t.dataset.tab);
    t.onkeydown = e => { const step = {ArrowRight: 1, ArrowLeft: -1}[e.key]; if (step) { e.preventDefault(); show(tabs[(i + step + tabs.length) % tabs.length].dataset.tab, true); } };
  });
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  show(location.hash.slice(1) || 'offair');
  VV.watch('v1/master', 5000, (m, w) => { if (!w.error) renderIdent(m); });
  VV.watch('v1/continuity', 30000, (c, w) => { if (!w.error) ready = c.ready || {}; });
  document.addEventListener('vv:auth', load);
  VV.commands.add(['offair', 'captions', 'continuity', 'ident', 'sonic'].map(t => ({id: 'presentation:' + t, title: 'Presentation: ' + {offair: 'off-air card', captions: 'live captions', continuity: 'continuity', ident: 'station ID', sonic: 'sonic identity'}[t], group: 'Presentation', run: () => show(t)})),
    {id: 'presentation:tone', title: 'Play or stop the test tone', group: 'Presentation', run: () => $('audition').click()});
  load();
})();
