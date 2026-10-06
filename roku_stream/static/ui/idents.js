// Ads › Idents: the station's ID card, and every ident it airs. The station ID and the Sports ID
// (ident/build.py, served at /v1/idents/), the promos and legal ID in ad breaks (promos.js), what
// is on air or cued for the next break, and what aired. Its ids start idt-.
(() => {
  'use strict';
  const {h, fmt, label} = VV;
  const $ = id => document.getElementById(id);
  const {blob, preview: previewPromo} = window.PromosPanel;
  let master = null, continuity = null, promos = null, drawn = '', sound = null;

  // The two IDs. A cued ID file named sports-… is the sports break (roku_stream/ident.py).
  const IDS = [
    {id: 'station-id', what: 'station', name: 'Station ID', length: 30, voice: 'DJ Low Tide',
      where: 'Between programmes. It holds its “Stay tuned” end card while the next programme gets ready; the announcer on duty speaks over it.'},
    {id: 'sports-id', what: 'sports', name: 'VizelVision Sports', length: 30, voice: 'Jupiter',
      where: 'Before every game, after the announcer says what is next: “The following is a presentation of VizelVision Sports.”'},
  ];
  const isSports = file => typeof file === 'string' && file.startsWith('sports-');

  /* The ID card ----------------------------------------------------------------------------------------- */
  function hear(file, button) {
    const again = sound?.button === button;
    stopSound();
    if (again) return;
    const audio = new Audio(`static/sonic/${file}.mp3`);
    sound = {audio, button, text: button.textContent};
    button.textContent = '■ Stop';
    audio.onended = stopSound;
    audio.play().catch(stopSound);
  }
  function stopSound() {
    if (!sound) return;
    sound.audio.pause(); sound.button.textContent = sound.text; sound = null;
  }
  function renderCard() {
    const c = continuity, p = promos?.settings;
    const onDuty = c?.settings?.announcers?.find(a => a.id === c.on_duty_now);
    const open = h('button', {type: 'button', class: 'xs', title: 'The logo, open: C E G A'}, '▶ Open');
    const closed = h('button', {type: 'button', class: 'xs', title: 'The logo, closed: D F♯ A D'}, '▶ Closed');
    open.onclick = () => hear('logo-open', open); closed.onclick = () => hear('logo-closed', closed);
    const rows = [
      ['Legal ID', h('span', {class: 'row', style: 'gap:6px'}, '“This is VizelVision 19, Cable 70.”', h('span', {class: 'chip'}, 'Jupiter'))],
      ['Sonic logo', h('span', {class: 'row', style: 'gap:6px'}, 'Viz-el-Vi-sion: C E G A, then D F♯ A D', open, closed)],
      ['Voices', 'DJ Low Tide (station ID) · Jupiter (Sports ID, legal ID)'],
      ['Announcer', !c ? '—' : !c.settings?.enabled ? 'Off: the plain ID plays' : (onDuty ? onDuty.name + ' is on duty' : 'On')],
      ['Promos', !p ? '—' : p.enabled ? `On · at least one every ${p.every} min, as breaks allow` : 'Off'],
      ['Loudness', '−20 LUFS, like the programmes around it'],
    ];
    VV.fill($('idt-card'), ...rows.flatMap(([k, v]) => [h('dt', null, k), h('dd', null, v)]));
  }

  /* On air, and the next break -------------------------------------------------------------------------- */
  function renderAir() {
    const m = master || {}, id = m.ident || {}, promo = m.my_ads?.promo, next = continuity?.next;
    const onAir = !!(id.on_air || promo);
    $('idt-status').textContent = id.on_air ? (isSports(id.file) ? 'Sports break' : 'Station ID') + (id.held ? ' · holding' : '')
      : promo ? promo.name : 'No ident on air';
    $('idt-status').className = 'status-big' + (onAir ? ' on' : '');
    $('idt-detail').textContent = id.on_air ? (id.held ? 'Holding its end card while the next programme gets ready.' : 'On master now.')
      : promo ? `${fmt.dur(promo.position || 0)} of ${fmt.dur(promo.duration)}, in an ad break.`
      : m.on_air ? 'On air: ' + label(m.on_air) + '.' : master ? 'Master is on the off-air card.' : '';
    $('idt-lamp').className = 'lamp ' + (onAir ? 'pgm' : id.ready ? 'pvw' : 'warn');
    $('idt-chip').textContent = !master ? '—' : id.ready ? 'ID ready' : id.enabled === false ? 'ID off' : 'ID not ready';

    const rows = [];
    if (continuity) {
      rows.push(['Next break', next?.break_at ? `${fmt.when(next.break_at)} (${fmt.rel(next.break_at)})` : 'None cued yet']);
      rows.push(['It plays', next ? (next.kind === 'sports' ? next.name : 'Station ID, announced by ' + next.name)
        : continuity.settings?.enabled ? 'The station ID' : 'The plain station ID (announcer off)']);
      const between = next ? [next.just_played, next.up_next].filter(Boolean).join(' → ') : '';
      if (between) rows.push(['Between', between]);
    }
    if (promos) {
      const s = promos.settings, w = promos.master?.promos || {}, cued = promos.promos.find(x => x.id === w.cued);
      rows.push(['Next promo', !s.enabled ? 'Promos are off'
        : (cued ? cued.name : 'Nothing cued yet') + (promos.due ? ', opening the next break' : promos.next_due ? `, at the first break after ${fmt.clock(promos.next_due)}` : '')
          + (w.active === false ? ' (only while ad mute is On)' : '')]);
    }
    if (id.error) rows.push(['Problem', id.error]);
    VV.fill($('idt-next'), ...rows.flatMap(([k, v]) => [h('dt', null, k), h('dd', null, v)]));
    const lines = next?.lines || [];
    VV.fill($('idt-lines'), ...lines.map(line => h('li', null, line)));
    $('idt-lines').hidden = !lines.length;
  }

  /* What aired: IDs and announced breaks (continuity, master), promos (their plays) ---------------------------- */
  function aired() {
    const rows = [];
    for (const r of continuity?.recent || []) {
      if (!r.aired_at) continue;
      rows.push({at: r.aired_at, what: r.kind === 'sports' ? 'sports' : 'station', file: r.file, title: r.kind === 'sports' ? 'Sports break' : 'Station ID',
        detail: r.name + ([r.just_played, r.up_next].some(Boolean) ? ': ' + [r.just_played, r.up_next].filter(Boolean).join(' → ') : '')});
    }
    const last = master?.last_station_id;
    if (last?.at && !rows.some(r => r.file === last.file && Math.abs(r.at - last.at) < 5))
      rows.push({at: last.at, what: isSports(last.file) ? 'sports' : 'station', file: last.file, title: isSports(last.file) ? 'Sports break' : 'Station ID',
        detail: last.after ? 'After ' + label(last.after) : ''});
    const names = Object.fromEntries((promos?.promos || []).map(p => [p.id, p.name]));
    for (const r of promos?.recent || [])
      rows.push({at: r.at, what: r.id, title: names[r.id] || r.name || r.id, promo: true, error: r.error,
        detail: `${fmt.dur(r.seconds)} of ${fmt.dur(r.length)} · ` + (r.error ? 'failed' : r.complete ? 'complete' : 'cut short' + (r.counted ? '' : ", didn't count"))});
    return rows.sort((a, b) => b.at - a.at);
  }

  /* The idents ------------------------------------------------------------------------------------------------- */
  function still(path, name, length, play) {
    const img = h('img', {alt: name + ': a still', hidden: true});
    const none = h('span', {class: 'none'}, name);
    blob(path, false).then(url => { if (url) { img.src = url; img.hidden = false; none.hidden = true; } });
    return h('button', {class: 'still', type: 'button', title: 'Play ' + name, 'aria-label': 'Play ' + name, onclick: play},
      none, img, h('span', {class: 'play'}, '▶ ' + fmt.dur(length)));
  }
  function playId(ident) {
    const video = h('video', {controls: true, playsinline: true, preload: 'auto'});
    const note = h('p', {class: 'tiny muted'}, 'Loading…');
    const close = h('button', {class: 'quiet', type: 'button'}, 'Close');
    const dialog = h('dialog', {class: 'preview ident-preview', 'aria-label': 'Play ' + ident.name}, h('div', {class: 'head'}, h('h2', null, ident.name)),
      h('div', {class: 'body stack tight'}, video, note), h('div', {class: 'foot'}, close));
    close.onclick = () => dialog.close();
    dialog.addEventListener('close', () => { video.pause(); dialog.remove(); });
    document.body.append(dialog); dialog.showModal();
    blob(`v1/idents/${ident.id}.mp4`, false).then(url => {
      if (!url) { note.textContent = 'Could not load it.'; return; }
      note.textContent = ident.id === 'station-id' ? 'As it airs without an announcer: DJ Low Tide over the jingle.' : 'As it airs, after the announcer.';
      video.src = url; video.play().catch(() => {});
    });
  }
  function idCard(ident, rows) {
    const id = master?.ident || {}, next = continuity?.next;
    const onAir = id.on_air && (ident.what === 'sports') === isSports(id.file);
    const cued = !onAir && (ident.what === 'sports' ? next?.kind === 'sports' : !!next && next.kind !== 'sports');
    const ready = ident.what === 'sports' ? continuity?.ready?.sports : continuity?.ready?.id ?? id.ready;
    const last = rows.find(r => r.what === ident.what);
    return h('article', {class: 'ident' + (onAir ? ' onair' : cued ? ' cued' : '')},
      still(`v1/idents/${ident.id}.png`, ident.name, ident.length, () => playId(ident)),
      h('div', {class: 'text'},
        h('h3', null, ident.name, h('span', {class: 'chip'}, 'ID'),
          onAir ? h('span', {class: 'chip solid pgm'}, 'on air') : cued ? h('span', {class: 'chip pvw'}, 'next break') : null,
          ready === false ? h('span', {class: 'chip warn'}, 'not built') : null),
        h('p', {class: 'small muted'}, ident.where),
        h('p', {class: 'tiny muted'}, `${ident.length} s · voiced by ${ident.voice}` + (last ? ` · last ${fmt.rel(last.at)}` : ''))));
  }
  function promoCard(promo) {
    const w = promos.master || {}, onAir = w.promo?.id === promo.id, cued = !onAir && w.promos?.cued === promo.id;
    return h('article', {class: 'ident' + (promo.enabled ? '' : ' off') + (onAir ? ' onair' : cued ? ' cued' : '')},
      still(`v1/promos/still/${promo.id}.png`, promo.name, promo.duration, () => previewPromo(promo, promos.values)),
      h('div', {class: 'text'},
        h('h3', null, promo.name, h('span', {class: 'chip'}, promo.kind === 'ident' ? 'ident' : 'promo'),
          onAir ? h('span', {class: 'chip solid pgm'}, 'on air') : cued ? h('span', {class: 'chip pvw'}, 'cued') : null,
          promo.enabled ? null : h('span', {class: 'chip'}, 'off')),
        h('p', {class: 'small muted'}, promo.description),
        !promo.present ? h('p', {class: 'small why'}, 'Not built yet') : promo.enabled && promo.why ? h('p', {class: 'small why'}, 'Sits out now: ' + promo.why) : null,
        h('p', {class: 'tiny muted'}, `${fmt.dur(promo.duration)} · in ad breaks · today ${promo.played.day}` + (promo.played.last ? ` · last ${fmt.rel(promo.played.last)}` : ''))));
  }

  function render() {
    renderCard(); renderAir();
    const rows = aired();
    const w = promos?.master || {}, id = master?.ident || {};
    const key = JSON.stringify([id.on_air, id.file, continuity?.next?.kind, !!continuity?.next, continuity?.ready, rows.slice(0, 40).map(r => [r.what, r.at]),
      (promos?.promos || []).map(p => [p.id, p.enabled, p.present, p.why, p.played, p.built_at]), w.promo?.id, w.promos?.cued, Math.floor(Date.now() / 60000)]);
    if (key !== drawn) {
      drawn = key;
      const list = (promos?.promos || []).slice().sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
      VV.fill($('idt-grid'), ...IDS.map(ident => idCard(ident, rows)), ...list.map(promoCard));
      $('idt-count').textContent = IDS.length + list.length + ' idents';
      VV.fill($('idt-recent'), ...rows.slice(0, 30).map(r => h('tr', null, h('td', {class: 'when'}, fmt.when(r.at)),
        h('td', null, r.title, ' ', h('span', {class: 'chip' + (r.promo ? '' : ' touch')}, r.promo ? 'promo' : 'ID')),
        h('td', {class: 'small muted'}, r.error ? h('span', {class: 'chip pgm', title: r.error}, r.detail) : r.detail))));
      $('idt-recent-empty').hidden = rows.length > 0;
    }
  }

  (window.AdsTabs ||= {}).idents = () => {
    // The ID card's face: the legal ID's picture.
    if (!$('idt-face').src) blob('v1/promos/file/legal.png', false).then(url => { if (url) $('idt-face').src = url; });
    const stops = [
      VV.watch('v1/master', 3000, (data, w) => { $('idt-error').textContent = w.error ? 'Master: ' + (w.error.message || w.error) : ''; if (!w.error) { master = data; render(); } }),
      VV.watch('v1/continuity', 15000, (data, w) => { if (!w.error) { continuity = data; render(); } }),
      VV.watch('v1/promos', 5000, (data, w) => { if (!w.error) { promos = data; render(); } }),
    ];
    return () => { stops.forEach(stop => stop()); stopSound(); };
  };
})();
