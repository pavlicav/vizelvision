// Ads › My ads: the operator's own ads, aired over the breaks ad mute mutes (my_ads.py, ad_break.py).
// Upload, order, limits, the break card and the corner picture; what is on air now, Next up (skip,
// queue by hand: master's, ad_break.AdBreak.command) and what aired.
// Its ids start my- where the other tabs use the same name.
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const panel = $('panel-my-ads');
  let view = null, editing = null, drawn = '', drawnLimit = null, drawnPick = '', drawnNext = '';

  // Limits: at most count plays in any stretch of minutes.
  const LIMITS = [[null, 'No limit'], [{count: 1, minutes: 15}, 'Once every 15 minutes'], [{count: 1, minutes: 30}, 'Once every 30 minutes'],
    [{count: 1, minutes: 60}, 'Once an hour'], [{count: 2, minutes: 60}, 'Twice an hour'], [{count: 1, minutes: 120}, 'Once every 2 hours'],
    [{count: 1, minutes: 180}, 'Once every 3 hours'], [{count: 1, minutes: 360}, 'Once every 6 hours'], [{count: 1, minutes: 1440}, 'Once a day']];
  const limitKey = l => l ? l.count + '/' + l.minutes : 'none';
  const per = m => m % 1440 === 0 ? (m === 1440 ? 'a day' : m / 1440 + ' days') : m % 60 === 0 ? (m === 60 ? 'an hour' : m / 60 + ' hours') : m + ' minutes';
  const limitText = l => LIMITS.find(([v]) => limitKey(v) === limitKey(l))?.[1] || `${l.count === 1 ? 'Once' : l.count === 2 ? 'Twice' : l.count + ' times'} every ${per(l.minutes)}`;
  function limitSelect(current, change, label) {
    const options = LIMITS.map(([v, text]) => [limitKey(v), text]);
    if (!options.some(([k]) => k === limitKey(current))) options.push([limitKey(current), limitText(current)]);
    options.push(['custom', 'Custom…']);
    const select = h('select', {'aria-label': label}, options.map(([k, text]) => h('option', {value: k, selected: k === limitKey(current)}, text)));
    select.onchange = async () => {
      if (select.value !== 'custom') return change(select.value === 'none' ? null : LIMITS.find(([v]) => limitKey(v) === select.value)?.[0]
        || {count: +select.value.split('/')[0], minutes: +select.value.split('/')[1]});
      const limit = await customLimit(current);
      if (limit === undefined) { select.value = limitKey(current); return; }
      change(limit);
    };
    return select;
  }
  function customLimit(current) {
    return new Promise(resolve => {
      const count = h('input', {type: 'number', min: 1, max: 50, step: 1, value: current?.count || 1, 'aria-label': 'Times'});
      const minutes = h('input', {type: 'number', min: 5, max: 10080, step: 5, value: current?.minutes || 60, 'aria-label': 'Minutes'});
      const ok = h('button', {class: 'primary', type: 'submit'}, 'Set limit'), no = h('button', {class: 'quiet', type: 'button'}, 'Cancel');
      const form = h('form', {class: 'body stack tight'}, h('p', {class: 'small'}, 'At most this many plays in any stretch of this many minutes.'),
        h('div', {class: 'fields'}, h('label', {class: 'field'}, h('span', 'Times'), count), h('label', {class: 'field'}, h('span', 'In minutes (60 = an hour, 1440 = a day)'), minutes)));
      const dialog = h('dialog', {'aria-label': 'Custom limit'}, h('div', {class: 'head'}, h('h2', 'Custom limit')), form, h('div', {class: 'foot'}, no, ok));
      let answer;
      ok.onclick = e => { e.preventDefault(); form.requestSubmit(); };
      form.onsubmit = e => {
        e.preventDefault();
        const c = Math.round(+count.value), m = Math.round(+minutes.value);
        if (!(c >= 1 && c <= 50 && m >= 5 && m <= 10080)) { toast('Times is 1 to 50; minutes 5 to 10080 (a week).', {error: true}); return; }
        answer = {count: c, minutes: m}; dialog.close();
      };
      no.onclick = () => dialog.close();
      dialog.addEventListener('close', () => { dialog.remove(); resolve(answer); });
      document.body.append(dialog); dialog.showModal(); count.focus();
    });
  }

  // Files (pictures, the card, the ads themselves, the promos' stills) need the API key: fetched as blobs, once each.
  const blobs = new Map();
  function fetched(path) {
    if (!blobs.has(path)) blobs.set(path, api(path, undefined, {raw: true, timeout: 120000})
      .then(r => r.ok ? r.blob() : null).then(b => b && URL.createObjectURL(b)).catch(() => null));
    return blobs.get(path);
  }
  const blob = name => fetched('v1/my-ads/file/' + name);
  function showAt(img, path) {
    if (img.dataset.name === path) return;
    img.dataset.name = path;
    fetched(path).then(url => { if (img.dataset.name !== path) return; if (url) img.src = url; img.closest('.shot')?.classList.toggle('none', !url); });
  }
  const show = (img, name) => showAt(img, 'v1/my-ads/file/' + name);

  // Settings ------------------------------------------------------------------------------------
  async function save(changes, done) {
    try { view = await api('v1/my-ads', changes); render(); if (done) toast(done, {ok: true}); }
    catch (e) { toast(e.message, {error: true}); render(true); }
  }
  async function edit(ad, changes, done) {
    try { view = await api('v1/my-ads/ads/' + ad.id, changes); render(); if (done) toast(done, {ok: true}); }
    catch (e) { toast(e.message, {error: true}); render(true); }
  }
  async function move(ad, by) {
    const ids = view.ads.map(a => a.id), i = ids.indexOf(ad.id), j = i + by;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try { view = await api('v1/my-ads/order', {ids}); render(); } catch (e) { toast(e.message, {error: true}); }
  }
  async function remove(ad) {
    if (!await VV.confirm('Its file and pictures are deleted. Its past plays stay in the log.', {title: `Delete “${ad.name || 'this ad'}”?`, ok: 'Delete', danger: true})) return;
    try { view = await api('v1/my-ads/ads/' + ad.id, undefined, {method: 'DELETE'}); render(); toast('Deleted.', {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
  }
  function preview(ad) {
    const video = h('video', {controls: true, playsinline: true, preload: 'auto'});
    const close = h('button', {class: 'quiet', type: 'button'}, 'Close');
    const note = h('p', {class: 'tiny muted'}, 'Loading ' + (ad.bytes ? fmt.bytes(ad.bytes) : 'the file') + '…');
    const dialog = h('dialog', {class: 'preview', 'aria-label': 'Preview ' + (ad.name || 'ad')}, h('div', {class: 'head'}, h('h2', ad.name || 'Ad')),
      h('div', {class: 'body stack tight'}, video, note), h('div', {class: 'foot'}, close));
    close.onclick = () => dialog.close();
    dialog.addEventListener('close', () => { video.pause(); dialog.remove(); });
    document.body.append(dialog); dialog.showModal();
    blob(ad.id).then(url => {
      if (!url) { note.textContent = 'Could not load it.'; return; }
      video.src = url; video.play().catch(() => {});
      note.textContent = 'As uploaded: on air it is levelled' + (ad.gain_db ? ` (${ad.gain_db > 0 ? '+' : ''}${ad.gain_db} dB)` : '') + ' and fitted to 16:9.';
    });
  }

  // One ad -------------------------------------------------------------------------------------------
  function chips(ad, st) {
    const out = [];
    if (st?.state === 'ad' && st.ad?.id === ad.id) out.push(h('span', {class: 'chip solid pgm'}, 'On air'));
    else if (st?.cued === ad.id) out.push(h('span', {class: 'chip pvw', title: 'Decoded and ready: it starts the next break (or follows the ad on air)'}, 'Plays next'));
    if (!ad.present) out.push(h('span', {class: 'chip pgm', title: 'The file is gone from my-ads/'}, 'File missing'));
    if (!ad.enabled) out.push(h('span', {class: 'chip'}, 'Off'));
    else if (!ad.allowed && ad.again) out.push(h('span', {class: 'chip warn', title: limitText(ad.limit)}, 'Sits out until ' + fmt.when(ad.again)));
    const why = st?.left_out?.[ad.id];
    if (why) out.push(h('span', {class: 'chip pgm', title: why}, 'Would not play · retried in 10 min'));
    return out;
  }
  function heading(ad, st) {
    if (editing === ad.id) {
      const input = h('input', {type: 'text', value: ad.name, maxlength: 80, 'aria-label': 'Name', placeholder: 'e.g. Cousin Vinny\'s Pizza'});
      const form = h('form', null, input, h('button', {class: 'sm primary', type: 'submit'}, 'Save'),
        h('button', {class: 'sm quiet', type: 'button', onclick: () => { editing = null; render(true); }}, 'Cancel'));
      form.onsubmit = e => { e.preventDefault(); editing = null; edit(ad, {name: input.value}, 'Renamed.'); };
      queueMicrotask(() => { input.focus(); input.select(); });
      return h('div', {class: 'top'}, form);
    }
    return h('div', {class: 'top'}, h('h3', ad.name || h('i', {class: 'muted'}, 'Untitled')), ...chips(ad, st),
      h('div', {class: 'end'}, h('button', {class: 'xs quiet', type: 'button', onclick: () => { editing = ad.id; render(true); }}, 'Rename')));
  }
  function facts(ad) {
    const dot = () => h('span', {class: 'sep'}, '·');
    const p = ad.played || {};
    return h('div', {class: 'facts'}, h('span', {class: 'num'}, fmt.dur(ad.duration)), dot(),
      ad.width ? [h('span', null, ad.width + '×' + ad.height), dot()] : null,
      ad.converted ? [h('span', {title: 'Converted on upload, so master decodes it in real time beside a live programme'}, 'converted to 720p'), dot()] : null,
      h('span', {title: ad.lufs != null ? `Measured ${ad.lufs} LUFS; aired at the station's -20 LUFS` : ''},
        !ad.audio ? 'no sound' : ad.lufs == null ? 'silent' : 'levelled ' + (ad.gain_db >= 0 ? '+' : '') + ad.gain_db + ' dB'), dot(),
      h('span', null, p.last ? `played ${p.hour} in the last hour, ${p.day} today · last ${fmt.when(p.last)}` : 'not played yet'));
  }
  function row(ad, i, n, st) {
    const pics = h('button', {class: 'pics', type: 'button', title: 'Preview it', 'aria-label': 'Preview ' + (ad.name || 'ad'), onclick: () => preview(ad)},
      Array.from({length: 4}, (_, k) => {
        const img = h('img', {alt: ''}), box = h('div', {class: 'shot' + (k < ad.pics ? '' : ' none')}, img);
        if (k < ad.pics) show(img, `${ad.id}-${k}.jpg`);
        return box;
      }));
    const enabled = h('input', {type: 'checkbox', checked: ad.enabled});
    enabled.onchange = () => edit(ad, {enabled: enabled.checked}, enabled.checked ? 'On: it airs in breaks again.' : 'Off: it sits out.');
    const trim = h('select', {'aria-label': 'Volume'}, [-6, -3, 0, 3, 6].map(db => h('option', {value: db, selected: db === Math.round(ad.trim_db)},
      db === 0 ? 'As levelled' : (db > 0 ? '+' : '') + db + ' dB')));
    trim.onchange = () => edit(ad, {trim_db: +trim.value}, 'Volume set.');
    const airing = st?.state === 'ad' && st.ad?.id === ad.id;
    return h('li', {class: 'ad' + (airing ? ' airing' : st?.cued === ad.id ? ' next' : '') + (ad.enabled ? '' : ' off'), data: {id: ad.id}},
      h('div', {class: 'move'}, h('button', {class: 'icon sm quiet', type: 'button', title: 'Move up', 'aria-label': 'Move up', disabled: i === 0, onclick: () => move(ad, -1)}, VV.icon(VV.ICONS.up)),
        h('b', {class: 'num'}, String(i + 1)),
        h('button', {class: 'icon sm quiet', type: 'button', title: 'Move down', 'aria-label': 'Move down', disabled: i === n - 1, onclick: () => move(ad, 1)}, VV.icon(VV.ICONS.down))),
      h('div', {class: 'main'}, heading(ad, st), pics, facts(ad),
        h('div', {class: 'controls'}, h('label', {class: 'switch'}, enabled, h('span', 'Airs')),
          h('label', {class: 'field'}, h('span', 'Limit'), limitSelect(ad.limit, limit => edit(ad, {limit}, 'Limit: ' + (limit ? limitText(limit).toLowerCase() : 'none') + '.'), 'Limit')),
          ad.limit ? h('button', {class: 'xs' + (ad.enabled && !ad.allowed ? ' primary' : ''), type: 'button',
            title: 'Forget its plays so far: it may air now, and its limit counts again from its next play',
            onclick: () => edit(ad, {limits_from: 'now'}, 'Limit reset: it may air now.')}, 'Reset limit') : null,
          h('label', {class: 'field'}, h('span', 'Volume'), trim),
          h('span', {class: 'grow'}),
          h('button', {class: 'xs', type: 'button', onclick: () => preview(ad)}, VV.icon(VV.ICONS.play), 'Preview'),
          h('button', {class: 'xs', type: 'button', title: 'Next up: after anything else you queued, before the rotation (even if it is off or over its limit)',
            onclick: () => queueIt({kind: 'ad', id: ad.id, name: ad.name}, false)}, VV.icon(VV.ICONS.plus), 'Queue'),
          h('button', {class: 'xs danger', type: 'button', onclick: () => remove(ad)}, 'Delete'))));
  }

  // Next up -------------------------------------------------------------------------------------------
  // Master's queue for the breaks (ad_break.py): what you queued first, then the rotation's ads drawn
  // ahead, with the next promo where its timing puts it. A skipped ad is out of this round.
  async function command(body, done) {
    try {
      view = await api('v1/my-ads/next', body); render(true);
      if (done) toast(done, {ok: true});
      setTimeout(() => VV.poke('v1/my-ads'), 400);
    } catch (e) { toast(e.message, {error: true}); }
  }
  const queueIt = (item, first) => command({op: 'add', kind: item.kind, id: item.id, next: first},
    `${item.name || 'It'} ${first ? 'plays next' : 'is queued'}.`);
  const skip = row => command({op: 'skip', key: row.key}, row.kind === 'promo' && row.by === 'promos'
    ? `Skipped ${row.name}: another promo instead.` : `Skipped ${row.name || 'it'} this time round.`);
  function timing(row) {
    if (row.kind === 'promo' && row.opens)
      return row.due_at <= Date.now() / 1000 + 1 ? 'opens the next break' : 'opens the first break after ' + fmt.clock(row.due_at);
    return row.in == null ? null : row.in < 1 ? 'next' : 'in ' + fmt.dur(row.in);
  }
  function nextUp() {
    const st = view.status || {}, s = view.settings, rows = st.next, empty = $('nextup-empty');
    const byId = Object.fromEntries(view.ads.map(a => [a.id, a]));
    const stills = Object.fromEntries((view.promos?.list || []).map(p => [p.id, p.still]));
    const inBreak = ['ad', 'promo', 'card', 'pass'].includes(st.state);
    $('next-when').textContent = !rows ? '' : inBreak ? 'In this break if it lasts, then the next'
      : st.state === 'fill' ? 'While the next program gets ready' : 'For the next break';
    if (!rows) {
      VV.fill($('nextup'));
      drawnNext = '';
      empty.hidden = false;
      empty.textContent = st.error ? 'Master is unavailable, so Next up is unknown.' : 'Master has not shown Next up yet: it needs a restart for it.';
      return;
    }
    const every = view.promos?.every;
    $('promo-every').textContent = !view.promos?.enabled ? 'promos are off now' : every === 0 ? 'every break' : 'every ' + every + ' minutes';
    empty.hidden = rows.length > 0;
    empty.textContent = !s.enabled && !view.promos?.enabled ? 'My ads and promos are both off: breaks show the programme, muted.'
      : view.ads.length ? 'Nothing may play now: every ad is off or over its limit, so the break card.' : 'Nothing yet: upload ads below.';
    // Drawn again only when an entry changes (a click is never lost to a redraw); the times tick in place.
    const key = JSON.stringify([rows.map(r => ({...r, in: null})), rows.map(r => byId[r.id]?.pics), s.enabled, view.promos?.enabled]);
    if (key === drawnNext) {
      for (const row of rows) {
        const el = $('nextup').querySelector(`li[data-key="${row.key}"] .when`);
        if (el) el.textContent = timing(row) || '';
      }
      return;
    }
    drawnNext = key;
    VV.fill($('nextup'), ...rows.map((row, i) => {
      const ad = row.kind === 'ad' ? byId[row.id] : null, still = row.kind === 'promo' && stills[row.id];
      const img = h('img', {alt: ''}), shot = h('div', {class: 'shot thumb'}, img);
      if (ad?.pics) show(img, `${ad.id}-0.jpg`);
      else if (still) showAt(img, 'v1/promos/file/' + still);
      else shot.classList.add('none');
      const off = row.kind === 'ad' ? !s.enabled : !view.promos?.enabled;
      const when = timing(row), name = row.name || 'Untitled';
      return h('li', {class: [row.kind, row.by === 'you' ? 'mine' : '', row.cued ? 'cued' : '', off || row.left_out ? 'held' : ''].filter(Boolean).join(' '),
        data: {key: row.key}, title: row.cued ? 'Decoded and ready to go on' : null},
        h('span', {class: 'pos'}, String(i + 1)), shot,
        h('div', {class: 'what'}, h('b', {title: name}, name),
          h('span', {class: 'facts'}, row.kind === 'promo' ? h('span', {class: 'chip pvw'}, 'Station promo') : null,
            row.by === 'you' ? h('span', {class: 'chip touch'}, 'Queued by you') : null,
            h('span', {class: 'num'}, fmt.dur(row.duration)), h('span', {class: 'when'}, when || ''),
            row.left_out ? h('span', {class: 'chip pgm', title: row.left_out}, 'Would not play · retried in 10 min') : null,
            off ? h('span', {class: 'chip'}, row.kind === 'ad' ? 'My ads is off' : 'Promos are off') : null)),
        h('button', {class: 'xs quiet', type: 'button', 'aria-label': 'Skip ' + name,
          title: row.kind === 'promo' && row.by === 'promos' ? 'Another promo instead' : 'Not this time: it comes round again later',
          onclick: () => skip(row)}, VV.icon(VV.ICONS.x), 'Skip'));
    }));
  }
  // The picker: every promo and ad, by name. Drawn again only when what it lists changes.
  function queuePicker() {
    const select = $('queue-pick'), promos = view.promos?.list || [];
    const byName = (a, b) => (a.name || '').localeCompare(b.name || '', undefined, {sensitivity: 'base'});
    const options = [
      ['Station promos', [...promos].sort(byName).map(p => ['promo:' + p.id, `${p.name} · ${fmt.dur(p.duration)}${p.why ? ' · ' + p.why : ''}`, !!p.why])],
      ['My ads', [...view.ads].sort(byName).map(a => ['ad:' + a.id, `${a.name || 'Untitled'} · ${fmt.dur(a.duration)}`
        + (!a.present ? ' · file missing' : !a.enabled ? ' · off' : !a.allowed ? ' · over its limit' : ''), !a.present])]];
    const key = JSON.stringify(options);
    if (key === drawnPick) return;
    drawnPick = key;
    const value = select.value;
    VV.fill(select, h('option', {value: ''}, 'Choose an ad or a promo…'),
      ...options.filter(([, items]) => items.length).map(([label, items]) =>
        h('optgroup', {label}, items.map(([v, text, disabled]) => h('option', {value: v, disabled}, text)))));
    select.value = [...select.options].some(o => o.value === value && !o.disabled) ? value : '';
  }
  $('queue-add').onsubmit = e => {
    e.preventDefault();
    const [kind, id] = $('queue-pick').value.split(':');
    if (!id) { toast('Choose an ad or a promo first.', {error: true}); return; }
    const item = kind === 'ad' ? view.ads.find(a => a.id === id) : view.promos.list.find(p => p.id === id);
    queueIt({kind, id, name: item?.name}, e.submitter?.dataset.next === 'true');
  };
  $('skip-now').onclick = () => {
    const key = $('skip-now').dataset.key;
    if (key) command({op: 'skip', key}, 'Skipped: the next goes on.');
  };

  // The page ------------------------------------------------------------------------------------------
  const CORNERS ={'bottom-right': ['right', 'bottom'], 'bottom-left': ['left', 'bottom'], 'top-right': ['right', 'top'], 'top-left': ['left', 'top']};
  function corner(pip) {
    const box = $('corner'), f = {small: 5, medium: 4, large: 3}[pip.size], [x, y] = CORNERS[pip.corner];
    $('screen').classList.toggle('off', !pip.enabled);
    Object.assign(box.style, {width: 100 / f + '%', height: 100 / f + '%', left: '', right: '', top: '', bottom: ''});
    box.style[x] = '4.8%';
    box.style[y] = y === 'bottom' ? '14.5%' : pip.corner === 'top-left' ? '24.5%' : '14.5%';
  }
  function status() {
    const st = view.status || {}, s = view.settings, mode = view.admute_mode;
    const note = $('mode-note');
    note.hidden = !(s.enabled && mode !== 'on');
    if (!note.hidden) VV.fill(note, `Ad mute is ${mode === 'off' ? 'off' : 'in shadow'}: it mutes nothing, so your ads never air. `,
      h('a', {href: '#admute'}, 'Turn ad mute On'), '.');
    const big = $('my-status'), lamp = $('my-lamp'), chip = $('state-chip'), playing = st.promo || st.ad;
    const byId = Object.fromEntries(view.ads.map(a => [a.id, a]));
    $('my-error').textContent = st.error || (st.card?.error && s.enabled ? st.card.error : '') || '';
    let text = 'Off', detail = 'Muted breaks look as ad mute leaves them: the programme\'s picture, muted.', cls = '';
    const waiting = st.state === 'fill';  // the station ID holds its end card while the next source gets ready
    if (waiting && st.promo) {
      text = st.promo.name; cls = 'on';
      detail = 'A station promo, while the next program gets ready (over the station ID\'s end card).';
    } else if (waiting && st.ad) {
      text = st.ad.name || 'Untitled ad'; cls = 'on';
      detail = 'Your ad fills the wait while the next program gets ready; the station ID irises out after it.';
    } else if (waiting) {
      text = st.fill?.joined ? 'We now join…' : 'Station ID end card'; cls = st.fill?.joined ? 'on' : 'card';
      detail = st.fill?.joined ? 'The VizelVision Sports bumper: the game in progress is next.' : 'The next program is getting ready; an ad goes on once one is readied.';
    } else if (st.state === 'promo' && st.promo) {
      text = st.promo.name; cls = 'on';
      detail = 'A station promo opens this break (Presentation → Promos); your ads follow.';
    } else if (s.enabled && st.state === 'ad' && st.ad) {
      text = st.ad.name || 'Untitled ad'; cls = 'on';
      detail = 'Your ad is on air in place of the break, the programme in the corner.';
    } else if (s.enabled && st.state === 'card') {
      text = 'Break card'; cls = 'card';
      detail = (view.ads.some(a => a.enabled && a.allowed) ? 'Your next ad is being readied.' : 'None of your ads may play now (switched off, or over their limits).')
        + (st.card_since ? ' Since ' + fmt.clockSec(st.card_since) + '.' : '');
    } else if (s.enabled) {
      text = st.active ? 'Waiting for a break' : 'Standing by';
      detail = st.active ? 'The next break ad mute mutes gets your ads.' : 'Ad mute is not muting anything, so nothing is replaced.';
    }
    big.textContent = text; big.className = 'status-big ' + cls;
    $('my-status-detail').textContent = detail;
    lamp.className = 'lamp' + (cls ? ' pgm' : st.active ? ' pvw' : '');
    chip.textContent = st.state === 'promo' ? 'promo' : cls === 'on' ? 'my ad' : cls === 'card' ? 'card' : st.active ? 'armed' : 'idle';
    chip.className = 'chip' + (cls === 'on' ? ' solid pgm' : cls === 'card' ? ' warn' : st.active ? ' pvw' : '');
    $('now-panel').classList.toggle('live', !!cls);
    const progress = cls === 'on' && playing && playing.duration;
    $('progress').hidden = !progress;
    if (progress) {
      $('progress-bar').style.width = Math.min(100, 100 * (playing.position || 0) / playing.duration) + '%';
      $('progress-text').textContent = fmt.dur(playing.position || 0) + ' / ' + fmt.dur(playing.duration);
    }
    const cued = st.cued && byId[st.cued], first = st.next?.find(r => !r.left_out);
    $('next').textContent = first ? 'Plays next: ' + (first.name || 'untitled') + ' (' + fmt.dur(first.duration) + ')'
      : !s.enabled ? '' : cued ? 'Plays next: ' + (cued.name || 'untitled') + ' (' + fmt.dur(cued.duration) + ')'
      : view.ads.length ? 'Nothing cued: ' + (view.ads.some(a => a.enabled && a.allowed) ? 'readying the next…' : 'every ad is off or over its limit, so the break card.') : '';
    // Skip what is on air: the next goes on at once (not once the next program is ready: it plays out).
    const skippable = playing?.key && cls === 'on' && st.fill?.state !== 'finishing';
    $('skip-now').hidden = !skippable;
    if (skippable) {
      $('skip-now').dataset.key = playing.key;
      $('skip-now').lastChild.textContent = st.promo ? 'Skip this promo' : 'Skip this ad';
    }
    const onAir = !!view.on_air;
    $('my-unmute').disabled = $('my-mute').disabled = !onAir || mode !== 'on';
  }
  function recent() {
    const names = Object.fromEntries(view.ads.map(a => [a.id, a.name || 'Untitled']));
    const rows = view.recent.slice(0, 40).map(p => p.kind === 'card'
      ? h('tr', null, h('td', {class: 'when'}, fmt.when(p.at)), h('td', null, h('span', {class: 'chip warn'}, 'Break card')), h('td', {class: 'num'}, fmt.dur(p.seconds)), h('td'))
      : p.kind === 'join'
      ? h('tr', null, h('td', {class: 'when'}, fmt.when(p.at)), h('td', null, h('span', {class: 'chip pvw'}, 'We now join'), ' ', 'VizelVision Sports bumper'),
        h('td', {class: 'num aired'}, fmt.dur(p.seconds) + ' of ' + fmt.dur(p.length)), h('td', {class: 'small muted'}, 'before a game in progress'))
      : p.kind === 'promo'
      ? h('tr', null, h('td', {class: 'when'}, fmt.when(p.at)), h('td', null, h('span', {class: 'chip pvw'}, 'Station promo'), ' ', p.name || p.id),
        h('td', {class: 'num aired'}, fmt.dur(p.seconds) + ' of ' + fmt.dur(p.length)), h('td', {class: 'small muted'}, p.complete ? 'complete' : 'cut short'))
      : h('tr', null, h('td', {class: 'when'}, fmt.when(p.at)), h('td', null, names[p.id] ?? h('i', {class: 'muted'}, (p.name || 'an ad') + ' (deleted)')),
        h('td', {class: 'num aired'}, fmt.dur(p.seconds) + ' of ' + fmt.dur(p.length)),
        h('td', {class: 'small muted'}, p.error ? h('span', {class: 'chip pgm', title: p.error}, 'failed') : p.complete ? 'complete'
          : p.wait ? 'cut short: the next program was ready' : 'cut short: the programme came back', p.counted ? null : ' · didn\'t count',
          p.wait ? ' · while the next program got ready' : p.programme_break ? ' · in a show\'s ad break' : null)));
    VV.fill($('recent'), ...rows);
    $('recent-empty').hidden = rows.length > 0;
    $('card-today').textContent = view.card.seconds_today ? 'Break card in the last day: ' + fmt.dur(view.card.seconds_today) : '';
  }
  function render(force) {
    if (!view) return;
    const s = view.settings;
    for (const b of document.querySelectorAll('#enabled [data-enabled]')) b.setAttribute('aria-pressed', String(String(s.enabled) === b.dataset.enabled));
    for (const b of document.querySelectorAll('#order [data-order]')) b.setAttribute('aria-pressed', String(s.order === b.dataset.order));
    $('order-note').textContent = s.order === 'shuffle' ? 'Every ad once, in a random order, before any repeats.' : 'Top to bottom, then around again.';
    status(); recent(); nextUp(); queuePicker();
    const total = view.ads.reduce((t, a) => t + a.duration, 0);
    $('count-chip').textContent = view.ads.length ? `${view.ads.length} · ${fmt.dur(total)}` : 'none';
    $('my-empty').hidden = view.ads.length > 0;
    // The list is drawn again only when it changes (not while a name is being typed).
    const st = view.status || {};
    const key = JSON.stringify([view.ads, st.cued, st.state === 'ad' && st.ad?.id, st.left_out, editing]);
    if ((force || key !== drawn) && (editing == null || force)) {
      drawn = key;
      VV.fill($('my-list'), ...view.ads.map((ad, i) => row(ad, i, view.ads.length, st)));
    }
    if (limitKey(s.default_limit) !== drawnLimit && document.activeElement !== $('default-limit')) {
      drawnLimit = limitKey(s.default_limit);
      VV.fill($('default-limit').parentElement, h('span', 'Limit for new uploads'),
        Object.assign(limitSelect(s.default_limit, limit => save({default_limit: limit}, 'New uploads get: ' + (limit ? limitText(limit).toLowerCase() : 'no limit') + '.'), 'Limit for new uploads'), {id: 'default-limit'}));
    }
    const card = $('card-text');
    if (document.activeElement !== card && !card.dataset.dirty) card.value = s.card.text;
    show($('card-img'), view.card.file);
    $('card-station').hidden = !s.card.image;
    $('card-note').textContent = (s.card.image ? 'Your picture. ' : 'The station ID\'s end card. ')
      + 'Shown when none of your ads may play. Its sound is ad mute\'s break sound (silence or Cairo radio).';
    $('pip-on').checked = s.pip.enabled; $('pip-corner').value = s.pip.corner; $('pip-size').value = s.pip.size;
    $('pip-corner').disabled = $('pip-size').disabled = !s.pip.enabled;
    corner(s.pip);
    const l = view.limits;
    $('upload-limits').textContent = `up to ${fmt.mins(l.seconds)} and ${fmt.bytes(l.bytes)} each`;
  }

  // Uploads ------------------------------------------------------------------------------------------
  const queue = [];
  let uploading = false;
  function send(path, file, progress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', path + '?name=' + encodeURIComponent(file.name));
      if (VV.key) xhr.setRequestHeader('X-API-Key', VV.key);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.upload.onprogress = e => progress?.(e.loaded, e.total || file.size);
      xhr.upload.onload = () => progress?.(file.size, file.size, true);
      xhr.onload = () => {
        let data = null; try { data = JSON.parse(xhr.responseText); } catch {}
        if (xhr.status === 401) { VV.signin(); reject(Error('An API key is required')); }
        else if (xhr.status >= 200 && xhr.status < 300 && data) resolve(data);
        else reject(Error(data?.error?.message || 'HTTP ' + xhr.status));
      };
      xhr.onerror = () => reject(Error('The connection dropped during the upload'));
      xhr.send(file);
    });
  }
  function addFiles(files) {
    const l = view?.limits;
    for (const file of files) {
      const bar = h('i'), what = h('span', {class: 'what'}, 'Waiting…');
      const li = h('li', null, h('span', {class: 'name', title: file.name}, file.name), h('span', {class: 'bar'}, bar), what);
      $('uploads').prepend(li);
      const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
      const fail = text => { li.classList.add('failed'); bar.style.width = '100%'; what.textContent = text; };
      if (l && !l.video.includes(ext)) { fail('Not a video this takes (' + l.video.join(' ') + ')'); continue; }
      if (l && file.size > l.bytes) { fail('Over ' + fmt.bytes(l.bytes)); continue; }
      queue.push({file, li, bar, what, fail});
    }
    pump();
  }
  async function pump() {
    if (uploading) return;
    uploading = true;
    while (queue.length) {
      const {file, li, bar, what, fail} = queue.shift();
      try {
        const data = await send('v1/my-ads/upload', file, (sent, total, all) => {
          bar.style.width = (100 * sent / total).toFixed(1) + '%';
          what.textContent = all ? 'Checking, levelling, pictures…' : Math.floor(100 * sent / total) + '% · ' + fmt.bytes(sent);
        });
        view = data; render(true);
        const ad = data.ads.find(a => a.id === data.added);
        li.classList.add('done'); bar.style.width = '100%';
        what.textContent = 'Added · ' + fmt.dur(ad?.duration) + (ad?.limit ? ' · ' + limitText(ad.limit).toLowerCase() : '');
        setTimeout(() => li.remove(), 20000);
      } catch (e) { fail(e.message); }
    }
    uploading = false;
  }
  const drop = $('drop'), picker = $('files');
  drop.onclick = () => picker.click();
  drop.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); picker.click(); } };
  picker.onchange = () => { addFiles([...picker.files]); picker.value = ''; };
  for (const name of ['dragenter', 'dragover']) drop.addEventListener(name, e => { e.preventDefault(); drop.classList.add('over'); });
  for (const name of ['dragleave', 'dragend']) drop.addEventListener(name, () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); addFiles([...e.dataTransfer.files]); });
  // A file dropped anywhere else on the page would open it in the browser instead; on this tab it is uploaded.
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => { if (!drop.contains(e.target)) { e.preventDefault(); if (!panel.hidden && e.dataTransfer?.files?.length) addFiles([...e.dataTransfer.files]); } });

  // The card ------------------------------------------------------------------------------------------
  const PRESETS = ['STAY TUNED', 'WE\'LL BE RIGHT BACK', 'BACK IN A MOMENT', 'DON\'T TOUCH THAT DIAL'];
  VV.fill($('presets'), ...PRESETS.map(text => h('button', {class: 'xs', type: 'button', onclick: () => { $('card-text').value = text; $('card-text').dataset.dirty = '1'; }}, text)));
  $('card-text').oninput = () => { $('card-text').dataset.dirty = '1'; };
  $('card-form').onsubmit = async e => {
    e.preventDefault();
    $('card-save').disabled = true;
    await save({card: {text: $('card-text').value}}, 'The card is redrawn.');
    delete $('card-text').dataset.dirty;
    $('card-save').disabled = false;
  };
  $('card-upload').onclick = () => $('card-file').click();
  $('card-file').onchange = async () => {
    const file = $('card-file').files[0];
    $('card-file').value = '';
    if (!file) return;
    try { view = await send('v1/my-ads/card-image', file); render(true); toast('Your picture is the break card now.', {ok: true}); }
    catch (err) { toast(err.message, {error: true}); }
  };
  $('card-station').onclick = async () => {
    try { view = await api('v1/my-ads/card-image', undefined, {method: 'DELETE'}); render(true); toast('Back to the station card.', {ok: true}); }
    catch (err) { toast(err.message, {error: true}); }
  };

  // Settings controls -----------------------------------------------------------------------------------
  $('enabled').onclick = e => {
    const b = e.target.closest('[data-enabled]');
    if (b) save({enabled: b.dataset.enabled === 'true'}, b.dataset.enabled === 'true' ? 'Muted breaks get your ads.' : 'Off: muted breaks show the programme, muted.');
  };
  $('order').onclick = e => { const b = e.target.closest('[data-order]'); if (b) save({order: b.dataset.order}); };
  $('shuffle-list').onclick = async () => {
    try { view = await api('v1/my-ads/shuffle', {}); render(true); toast('The list is in a new order.', {ok: true}); } catch (err) { toast(err.message, {error: true}); }
  };
  $('pip-on').onchange = () => save({pip: {enabled: $('pip-on').checked}});
  $('pip-corner').onchange = () => save({pip: {corner: $('pip-corner').value}});
  $('pip-size').onchange = () => save({pip: {size: $('pip-size').value}});

  // The quick fixes act on ad mute (the same as its page and On Air's).
  async function override(action) {
    try {
      const result = await api('v1/admute/override', {action});
      if (result.override && !result.override.accepted) throw Error(result.override.reason || 'Not accepted');
      toast(action === 'unmute' ? 'Back to the programme.' : 'A break: your ads now.', {ok: true});
      setTimeout(() => VV.poke('v1/my-ads'), 400);
    } catch (e) { toast(e.message, {error: true}); }
  }
  $('my-unmute').onclick = () => override('unmute');
  $('my-mute').onclick = () => override('mute');
  VV.commands.add([
    {id: 'myads:unmute', title: "It's the show: end the break", group: 'My ads', keys: 'u', when: () => !panel.hidden && !$('my-unmute').disabled, run: () => override('unmute')},
    {id: 'myads:mute', title: "It's an ad: a break now", group: 'My ads', keys: 'a', when: () => !panel.hidden && !$('my-mute').disabled, run: () => override('mute')},
    {id: 'myads:upload', title: 'Upload ads', group: 'My ads', when: () => !panel.hidden, run: () => picker.click()},
  ]);

  // Polled while its tab is shown (ads.js).
  (window.AdsTabs ||= {})['my-ads'] = () => VV.watch('v1/my-ads', 2000, (data, w) => {
    if (w.error) { $('my-error').textContent = w.error.message; return; }
    view = data;
    render();
  });
})();
