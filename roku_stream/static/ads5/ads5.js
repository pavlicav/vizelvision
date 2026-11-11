/* Ads 5 · the page that runs the channel. Reads v1/status every second and v1/library every
   15 s; every change is a POST that the server answers at once (and Next up is drawn again). */
'use strict';

const $ = (s, root = document) => root.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const video = $('#video');
const KIND_COLOURS = ['#4fb3ff', '#34d07a', '#ff8b3d', '#ff5a8c', '#b495ff', '#5fd4d0', '#f2d45c', '#9ad04f', '#e86bd8', '#7aa2ff', '#ff6f61', '#c9a27a', '#8e99a3'];
const BY = {you: 'Queued by you', rotation: 'Rotation', clock: 'The format', 'tune-in': 'Tune-in ident', fill: 'Fill'};
const KIND_WORD = {ad: 'Ad', promo: 'Ident', id: 'Station ID'};
const OPTIONS = {
  ident_every: [[0, 'Off'], [1, '1'], [2, '2'], [3, '3'], [5, '5'], [10, '10'], [15, '15'], [30, '30']],
  station_id_every: [[0, 'Off'], [15, '15'], [30, '30'], [60, '60']],
  order: [['mix', 'Mix'], ['shuffle', 'Shuffle'], ['list', 'In list order']],
  longest_ad: [[0, 'Any'], [15, '15 s'], [30, '30 s'], [60, '1 min'], [120, '2 min']],
};
const LIMITS = [[null, 'No limit'], [[1, 15], 'Once / 15 min'], [[1, 30], 'Once / 30 min'], [[1, 60], 'Once an hour'],
  [[1, 180], 'Once / 3 h'], [[1, 360], 'Once / 6 h'], [[1, 1440], 'Once a day']];
const BEFORE = 30, AFTER = 210;   // the strip: seconds of the past and the future

let status = null, statusAt = 0, skew = 0, lib = null, libSig = '';
let tab = 'ads', kindFilter = null, query = '', sort = 'name', shown = 48;
let hls = null, watching = false;
const kindColour = {};

// ---------------------------------------------------------------- helpers
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {cache: 'no-store'} :
    {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || r.statusText);
  return j;
}
function toast(text, bad) {
  const t = $('#toast');
  t.textContent = text;
  t.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.className = 'toast', 2600);
}
const mmss = s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const clockAt = (t, secs) => new Date(t * 1000).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit', ...(secs ? {second: '2-digit'} : {})});
const serverNow = () => Date.now() / 1000 + skew;
function picture(item) {
  if (item.kind === 'ad') return `pic/${item.id}-1.jpg`;
  if (item.kind === 'id') return 'still/station.png';
  return `still/${item.id}.png`;
}
function colourOf(item) {
  if (item.kind === 'promo') return 'var(--ident)';
  if (item.kind === 'id') return 'var(--sid)';
  const ad = lib && lib.byId[item.id];
  return (ad && kindColour[ad.kind]) || '#8e99a3';
}
function kindName(key) {
  const k = lib && lib.kinds.find(k => k.key === key);
  return k ? k.name : 'Unsorted';
}

// ---------------------------------------------------------------- the player
function watch() {
  watching = true;
  $('#veil').hidden = true;
  if (window.Hls && Hls.isSupported()) {
    if (hls) hls.destroy();
    hls = new Hls({liveSyncDurationCount: 2, liveMaxLatencyDurationCount: 6, maxLiveSyncPlaybackRate: 1.2, backBufferLength: 30});
    hls.loadSource('index.m3u8');
    hls.attachMedia(video);
    hls.on(Hls.Events.ERROR, (_, d) => {
      if (!d.fatal) return;
      showVeil(status && status.problem ? status.problem : 'The stream stopped. Trying again…');
      setTimeout(() => { if (watching) watch(); }, 4000);
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = 'index.m3u8';
  }
  video.play().catch(() => showVeil('Press Watch to start the channel.'));
}
function showVeil(text) {
  $('#veil-text').textContent = text;
  $('#veil').hidden = false;
}
function stopWatching() {
  watching = false;
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute('src');
  video.load();
}
$('#watch').onclick = () => { video.muted = false; soundIcon(); watch(); };
function soundIcon() {
  $('#sound-x').toggleAttribute('hidden', !video.muted);
  $('#sound-w').toggleAttribute('hidden', video.muted);
}
$('#sound').onclick = () => { video.muted = !video.muted; soundIcon(); if (!watching) watch(); };
video.addEventListener('playing', () => { $('#veil').hidden = true; });
// A hidden tab stops watching, so the channel rests (and counts no plays) when nobody looks.
document.addEventListener('visibilitychange', () => {
  if (document.hidden && watching) { stopWatching(); watching = 'paused'; }
  else if (!document.hidden && watching === 'paused') watch();
});

// What the screen shows now, on the server's clock: the player's position (its playlist's
// dates), or a few seconds behind the live edge when nothing plays here.
function screenTime() {
  if (hls && hls.playingDate && !video.paused) return hls.playingDate.getTime() / 1000;
  return serverNow() - 6;
}
function timeline() {
  if (!status) return [];
  const seen = new Set(), items = [];
  for (const h of status.history) { seen.add(h.key); items.push({...h}); }
  if (status.on_air && !seen.has(status.on_air.key)) items.push({...status.on_air});
  for (const n of status.next) items.push({...n, start: n.at, end: n.at + n.seconds, upcoming: true});
  return items;
}

// ---------------------------------------------------------------- status
async function poll() {
  try {
    const t0 = Date.now() / 1000;
    status = await api('v1/status');
    statusAt = Date.now() / 1000;
    skew = status.now - (t0 + statusAt) / 2;
    renderStatus();
  } catch (e) {
    $('#tally').className = 'tally wait';
    $('#tally-text').textContent = 'No answer';
  }
}
function renderStatus() {
  const tally = $('#tally');
  if (status.running) { tally.className = 'tally on'; $('#tally-text').textContent = 'On air'; }
  else if (status.problem) { tally.className = 'tally wait'; $('#tally-text').textContent = 'Getting ready'; }
  else { tally.className = 'tally'; $('#tally-text').textContent = 'Standby'; }
  renderNext();
  frame();
}
function itemAt(items, t) {
  return items.find(i => i.start <= t && t < i.end) || items.filter(i => i.start <= t).pop() || null;
}
function frame() {
  if (!status) return;
  const t = screenTime(), items = timeline();
  const cur = itemAt(items, t);
  if (cur) {
    $('#oa-name').textContent = cur.name;
    const chip = $('#oa-kind');
    chip.className = 'chip' + (cur.kind === 'promo' ? ' k-ident' : cur.kind === 'id' ? ' k-id' : '');
    chip.innerHTML = cur.kind === 'ad' ? `<i class="dot" style="background:${colourOf(cur)}"></i>${esc(kindName(lib && lib.byId[cur.id] && lib.byId[cur.id].kind))}` : esc(KIND_WORD[cur.kind]);
    const len = Math.max(0.1, cur.end - cur.start), at = Math.min(len, Math.max(0, t - cur.start));
    $('#oa-bar').style.width = (100 * at / len).toFixed(2) + '%';
    $('#oa-at').textContent = mmss(at);
    $('#oa-left').textContent = '−' + mmss(len - at);
    const ad = cur.kind === 'ad' && lib && lib.byId[cur.id];
    $('#oa-meta').textContent = [BY[cur.by] || cur.by, mmss(len), ad ? `${ad.plays_all} plays here` : ''].filter(Boolean).join(' · ');
    $('#oa-note').textContent = status.on_air && status.on_air.skipping ? 'Skipping…' : '';
  } else {
    $('#oa-name').textContent = status.running ? 'Starting…' : 'Standby';
    $('#oa-meta').textContent = status.running ? '' : 'The channel airs while someone watches.';
    $('#oa-bar').style.width = '0';
    $('#oa-at').textContent = $('#oa-left').textContent = '';
  }
  // Coming up: the next three after what is on screen.
  const after = items.filter(i => i.start >= (cur ? cur.end - 0.01 : t)).slice(0, 3);
  $('#soon').innerHTML = after.map(i => `<li><span class="when num">${i.start - t > 0 ? 'in ' + mmss(i.start - t) : 'now'}</span>
    <span class="nm">${esc(i.name)}</span><span class="chip" style="border-color:${colourOf(i)}">${esc(KIND_WORD[i.kind])}</span></li>`).join('')
    || '<li class="muted">Nothing drawn yet</li>';
  strip(items, t, cur);
  document.querySelectorAll('.card.onair').forEach(c => c.classList.remove('onair'));
  if (cur) { const c = document.querySelector(`.card[data-key="${cur.kind}:${cur.id}"]`); if (c) c.classList.add('onair'); }
}

// ---------------------------------------------------------------- the strip
function strip(items, t, cur) {
  const tape = $('#tape'), span = BEFORE + AFTER, x = s => (100 * (s - (t - BEFORE)) / span);
  const html = [];
  for (const i of items) {
    if (i.end < t - BEFORE || i.start > t + AFTER) continue;
    const left = Math.max(0, x(i.start)), right = Math.min(100, x(i.end));
    const cls = i.kind === 'ad' ? 'ad' : i.kind === 'promo' ? 'ident' : 'id';
    const past = i.end <= t ? ' past' : '', wait = i.upcoming && i.ready && i.ready !== 'ready' ? ' wait' : '';
    const bg = i.kind === 'ad' ? `background:${colourOf(i)};` : '';
    html.push(`<div class="blk ${cls}${past}${wait}" style="left:${left}%;width:${Math.max(0.2, right - left)}%;${bg}" title="${esc(i.name)} · ${mmss(i.seconds || i.end - i.start)}"><span>${esc(i.name)}</span></div>`);
  }
  tape.innerHTML = html.join('') + `<div class="playhead" style="left:${x(t)}%"></div>`;
  const ticks = [];
  for (let m = Math.ceil((t - BEFORE) / 60) * 60; m <= t + AFTER; m += 60) ticks.push(`<span style="left:${x(m)}%">${clockAt(m)}</span>`);
  $('#ticks').innerHTML = ticks.join('');
  const idents = items.filter(i => i.upcoming && i.kind !== 'ad');
  $('#strip-note').textContent = idents.length ? `next ident in ${mmss(idents[0].start - t)}` : '';
}

// ---------------------------------------------------------------- Next up
function renderNext() {
  const t = screenTime();
  const list = $('#next');
  list.innerHTML = status.next.map((n, idx) => `<li class="${n.by === 'you' ? 'mine' : ''}">
      <div class="thumb ${n.kind !== 'ad' ? 'ident' : ''}" style="background-image:url('${picture(n)}')"></div>
      <span class="when num">${n.at - t > 0 ? mmss(n.at - t) : 'now'}</span>
      <div class="nm"><b>${esc(n.name)}</b><small>${esc(KIND_WORD[n.kind])} · ${mmss(n.seconds)} · ${esc(BY[n.by] || n.by)}${n.ready && n.ready !== 'ready' ? ` · <span class="state">${esc(n.ready === 'live' ? 'drawn just before' : n.ready)}</span>` : ''}</small></div>
      <div class="acts">
        <button class="icon" data-move="${n.key}" data-by="-1" title="Earlier" ${idx === 0 ? 'disabled' : ''}>↑</button>
        <button class="icon" data-move="${n.key}" data-by="1" title="Later">↓</button>
        <button class="icon" data-skip="${n.key}" title="Take out of Next up">✕</button>
      </div></li>`).join('') || '<li class="muted">Nothing drawn: switch some ads on.</li>';
}
$('#next').addEventListener('click', async e => {
  const b = e.target.closest('button');
  if (!b) return;
  try {
    if (b.dataset.skip) { const r = await api('v1/next', {op: 'skip', key: b.dataset.skip}); status = r.status; }
    if (b.dataset.move) { const r = await api('v1/next', {op: 'move', key: b.dataset.move, by: +b.dataset.by}); status = r.status; }
    renderStatus();
  } catch (err) { toast(err.message, true); }
});
$('#redraw').onclick = async () => { try { status = (await api('v1/next', {op: 'redraw'})).status; renderStatus(); toast('Next up drawn again'); } catch (e) { toast(e.message, true); } };
$('#skip-on-air').onclick = async () => {
  try { status = (await api('v1/next', {op: 'skip', key: 'on-air'})).status; renderStatus(); toast('Cut to what is next: it reaches the screen in a few seconds'); }
  catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- the format
function segmented(name, value) {
  const el = $('#' + name), opts = OPTIONS[name].slice();
  if (!opts.some(([v]) => v === value)) opts.push([value, String(value)]);
  if (name === 'longest_ad') opts.sort((a, b) => (a[0] || 1e9) - (b[0] || 1e9));
  else if (typeof value === 'number') opts.sort((a, b) => a[0] - b[0]);
  el.innerHTML = opts.map(([v, label]) => `<button type="button" data-v="${v}" aria-pressed="${v === value}">${label}</button>`).join('')
    + (el.dataset.unit ? `<span class="tiny dim" style="align-self:center;margin-left:4px">${el.dataset.unit}</span>` : '');
}
for (const name of Object.keys(OPTIONS)) {
  $('#' + name).addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    const v = name === 'order' ? b.dataset.v : +b.dataset.v;
    save({[name]: v}, describeChange(name, v));
  });
}
function describeChange(name, v) {
  if (name === 'ident_every') return v ? `An ident every ${v} minute${v === 1 ? '' : 's'}` : 'No idents between ads';
  if (name === 'station_id_every') return v ? `The station ID every ${v} minutes` : 'No station ID';
  if (name === 'order') return {mix: 'The mix picks', shuffle: 'Shuffled', list: 'In list order'}[v];
  if (name === 'longest_ad') return v ? `Ads up to ${v < 60 ? v + ' s' : v / 60 + ' min'}` : 'Ads of any length';
  return 'Saved';
}
for (const name of ['idents', 'open_with_ident', 'limits', 'always_on']) {
  $('#' + name).addEventListener('change', e => save({[name]: e.target.checked}, 'Saved'));
}
$('#reset-limits').onclick = () => save({limits_from: 'now'}, 'Every ad may air again');
async function save(changes, message) {
  try {
    await api('v1/settings', changes);
    toast(message + ' · Next up drawn again');
    await Promise.all([poll(), loadLibrary(true)]);
  } catch (e) { toast(e.message, true); loadLibrary(true); }
}
function renderFormat() {
  const s = lib.settings;
  for (const name of Object.keys(OPTIONS)) segmented(name, s[name]);
  for (const name of ['idents', 'open_with_ident', 'limits', 'always_on']) $('#' + name).checked = !!s[name];
  const out = lib.ads.filter(a => a.enabled && !a.allowed && !a.too_long).length;
  $('#reset-limits').classList.toggle('lit', out > 0 && s.limits);
  $('#limits-note').textContent = !s.limits ? 'Limits are off: the mix spaces ads out.'
    : out ? `${out} ad${out === 1 ? '' : 's'} sitting out over the limit` : 'No ad is over its limit';
  wheel(s);
  $('#forked').textContent = s.forked_at ? `Forked from VizelVision ${new Date(s.forked_at * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})}.` : '';
}
function arc(cx, cy, r, a0, a1) {
  const p = a => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
function wheel(s) {
  const T = 2 * Math.PI, svg = $('#wheel'), parts = [];
  parts.push(`<circle cx="100" cy="100" r="78" fill="none" stroke="#2b333b" stroke-width="16"/>`);
  for (let m = 0; m < 60; m += 5) {
    const a = m / 60 * T;
    parts.push(`<line x1="${100 + 90 * Math.sin(a)}" y1="${100 - 90 * Math.cos(a)}" x2="${100 + 95 * Math.sin(a)}" y2="${100 - 95 * Math.cos(a)}" stroke="#46515b" stroke-width="${m % 15 ? 1 : 2}"/>`);
  }
  let idents = 0, ids = 0;
  if (s.idents && s.ident_every) for (let m = s.ident_every; m < 60.01; m += s.ident_every) {
    if (s.station_id_every && Math.abs(m % s.station_id_every) < 1e-6) continue;
    const a = (m % 60) / 60 * T; idents++;
    parts.push(`<path d="${arc(100, 100, 78, a - 0.045, a + 0.045)}" stroke="#f4e7c6" stroke-width="16" fill="none"/>`);
  }
  if (s.station_id_every) for (let m = 0; m < 60; m += s.station_id_every) {
    const a = m / 60 * T; ids++;
    parts.push(`<path d="${arc(100, 100, 78, a - 0.08, a + 0.08)}" stroke="#ff4438" stroke-width="16" fill="none"/>`);
  }
  const now = new Date(), hand = (now.getMinutes() + now.getSeconds() / 60) / 60 * T;
  parts.push(`<line x1="100" y1="100" x2="${100 + 62 * Math.sin(hand)}" y2="${100 - 62 * Math.cos(hand)}" stroke="#ffb340" stroke-width="3" stroke-linecap="round"/><circle cx="100" cy="100" r="5" fill="#ffb340"/>`);
  svg.innerHTML = parts.join('');
  $('.wheel-legend').innerHTML = `<span><i class="sw ad"></i>Ads</span><span><i class="sw ident"></i>${idents} ident${idents === 1 ? '' : 's'} an hour</span><span><i class="sw sid"></i>${ids} station ID${ids === 1 ? '' : 's'} an hour</span>`;
}

// ---------------------------------------------------------------- the mix
let mixTimer = null;
function renderMixer() {
  const el = $('#faders');
  el.innerHTML = lib.kinds.map(k => `<div class="fader" style="--k:${kindColour[k.key]}" title="${esc(k.about)}">
      <span class="val num">${(+k.weight).toFixed(2).replace(/\.?0+$/, '') || '0'}</span>
      <input type="range" min="0" max="10" step="0.25" value="${k.weight}" data-kind="${k.key}" aria-label="${esc(k.name)}'s share">
      <i class="cap"></i><span class="nm">${esc(k.name)}</span><span class="day">${k.day} · ${k.ads} ads</span></div>`).join('');
  const total = lib.kinds.reduce((n, k) => n + k.day, 0);
  $('#mix-note').textContent = total ? `${total} ads in the last day` : '';
}
$('#faders').addEventListener('input', e => {
  const r = e.target.closest('input[type=range]');
  if (!r) return;
  r.parentElement.querySelector('.val').textContent = (+r.value).toFixed(2).replace(/\.?0+$/, '') || '0';
  clearTimeout(mixTimer);
  mixTimer = setTimeout(async () => {
    try { await api('v1/mix', {kinds: {[r.dataset.kind]: {weight: +r.value}}}); toast(`${kindName(r.dataset.kind)}: share ${r.value}`); poll(); }
    catch (err) { toast(err.message, true); }
  }, 450);
});

// ---------------------------------------------------------------- the library
async function loadLibrary(force) {
  try {
    const data = await api('v1/library');
    data.byId = Object.fromEntries(data.ads.map(a => [a.id, a]));
    data.kinds.forEach((k, i) => { kindColour[k.key] = k.key === 'unsorted' ? '#8e99a3' : KIND_COLOURS[i % KIND_COLOURS.length]; });
    lib = data;
    renderFormat();
    renderPrep();
    const sig = JSON.stringify([data.ads, data.promos, data.kinds, data.station_id, data.recent.slice(0, 5)]);
    if (force || sig !== libSig) {
      libSig = sig;
      if (!document.activeElement || !document.activeElement.matches('#faders input')) renderMixer();
      renderKinds();
      renderCards();
    }
  } catch (e) { /* the next poll tries again */ }
}
function renderKinds() {
  $('#kind-filter').hidden = tab !== 'ads';
  $('#kind-filter').innerHTML = `<button data-kind="" aria-pressed="${!kindFilter}" style="--k:#e7ebee"><i></i>All kinds</button>` +
    lib.kinds.map(k => `<button data-kind="${k.key}" aria-pressed="${kindFilter === k.key}" style="--k:${kindColour[k.key]}"><i></i>${esc(k.name)} <span class="count">${k.ads}</span></button>`).join('');
  $('#n-ads').textContent = lib.ads.length;
  $('#n-idents').textContent = lib.promos.length + 1;
}
$('#kind-filter').addEventListener('click', e => {
  const b = e.target.closest('button');
  if (!b) return;
  kindFilter = b.dataset.kind || null;
  shown = 48;
  renderKinds(); renderCards();
});
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  tab = b.dataset.tab;
  document.querySelectorAll('.tab').forEach(x => x.setAttribute('aria-selected', String(x === b)));
  renderKinds(); renderCards();
});
$('#search').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); shown = 48; renderCards(); });
$('#more').onclick = () => { shown += 96; renderCards(); };
$('#sort').addEventListener('change', e => { sort = e.target.value; renderCards(); });

function limitValue(limit) {
  if (!limit) return 'null';
  return JSON.stringify([limit.count, limit.minutes]);
}
function limitSelect(a) {
  const current = limitValue(a.limit);
  const opts = LIMITS.map(([v, label]) => [v === null ? 'null' : JSON.stringify(v), label]);
  if (!opts.some(([v]) => v === current)) opts.push([current, `${a.limit.count} / ${a.limit.minutes} min`]);
  return `<select data-limit="${a.id}" aria-label="Limit">${opts.map(([v, l]) => `<option value='${v}' ${v === current ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
}
function whyOut(a) {
  if (!a.enabled) return 'Switched off on Ads 5';
  if (a.too_long) return 'Longer than the longest ad allowed';
  if (!a.allowed && a.again) return `Over its limit · may air again at ${clockAt(a.again)}`;
  if (!a.allowed) return 'Over its limit';
  return '';
}
function clipTag(state) {
  if (state === 'ready') return '';
  const word = {working: 'encoding', queued: 'waiting to encode', new: 'not encoded', failed: 'could not encode', missing: 'file missing', live: 'live text'}[state] || state;
  return `<span class="tag ${state === 'live' ? 'live' : 'wait'}">${esc(word)}</span>`;
}
function renderCards() {
  const cards = $('#cards');
  let html = '';
  if (tab === 'ads') {
    let ads = lib.ads.filter(a => (!kindFilter || a.kind === kindFilter) && (!query || a.name.toLowerCase().includes(query)));
    const by = {name: (a, b) => a.name.localeCompare(b.name), chance: (a, b) => (b.allowed - a.allowed) || b.chance - a.chance,
      plays: (a, b) => b.plays_all - a.plays_all, recent: (a, b) => (b.last || 0) - (a.last || 0), length: (a, b) => b.duration - a.duration}[sort];
    ads.sort(by);
    const more = ads.length - shown;
    ads = ads.slice(0, shown);
    $('#more').hidden = more <= 0;
    $('#more').textContent = `Show ${Math.min(more, 96)} more of ${more}`;
    html = ads.map(a => {
      const why = whyOut(a);
      return `<article class="card ${a.enabled ? '' : 'off'}" data-key="ad:${a.id}" style="--k:${kindColour[a.kind]}">
        <div class="pic"><img loading="lazy" alt="" src="pic/${a.id}-${a.pics > 1 ? 1 : 0}.jpg" style="width:100%;height:100%;object-fit:cover;display:block" onerror="this.remove()">
          <i class="kd"></i>${clipTag(a.clip)}<span class="dur">${mmss(a.duration)}</span></div>
        <div class="body"><b>${esc(a.name)}</b>
          <div class="stats"><span>${esc(kindName(a.kind))}</span><span>today ${a.plays_day}</span><span>all ${a.plays_all}</span>${a.boost !== 1 ? `<span>boost ×${a.boost}</span>` : ''}</div>
          ${why ? `<div class="why">${esc(why)}</div>` : ''}
          <div class="ctl"><label class="tog"><input type="checkbox" data-enable="${a.id}" ${a.enabled ? 'checked' : ''}><span></span></label>
            ${limitSelect(a)}
            <button class="btn small" data-queue="ad:${a.id}" data-next="1" title="Play it next">Next</button>
            <button class="btn small ghost" data-queue="ad:${a.id}" title="Add to the queue">Queue</button>
            ${a.limit && !a.allowed && a.enabled ? `<button class="btn small ghost lit" data-reset="${a.id}">Reset limit</button>` : ''}</div>
        </div></article>`;
    }).join('');
  } else if (tab === 'idents') {
    $('#more').hidden = true;
    const sid = {id: 'station', name: 'Station ID', kind: 'id', duration: 30, description: 'The 30-second station ID, every ' +
      (lib.settings.station_id_every ? lib.settings.station_id_every + ' minutes' : '— switched off') + '.', enabled: !!lib.settings.station_id_every,
      clip: lib.station_id.clip, plays_all: lib.station_id.plays_all};
    const items = [sid, ...lib.promos].filter(p => !query || p.name.toLowerCase().includes(query) || (p.description || '').toLowerCase().includes(query));
    if (sort === 'plays') items.sort((a, b) => b.plays_all - a.plays_all);
    else if (sort === 'name') items.sort((a, b) => (a.kind === 'id' ? -1 : b.kind === 'id' ? 1 : a.name.localeCompare(b.name)));
    html = items.map(p => {
      const isId = p.kind === 'id', key = isId ? 'id:station' : `promo:${p.id}`;
      return `<article class="card ${p.enabled ? '' : 'off'}" data-key="${key}" style="--k:${isId ? 'var(--sid)' : 'var(--ident)'}">
        <div class="pic"><img loading="lazy" alt="" src="still/${p.id}.png" style="width:100%;height:100%;object-fit:cover;display:block" onerror="this.remove()">
          <i class="kd"></i>${clipTag(p.clip)}<span class="dur">${mmss(p.duration)}</span></div>
        <div class="body"><b>${esc(p.name)}</b>
          <div class="stats"><span>${isId ? 'station ID' : esc(p.kind)}</span><span>all ${p.plays_all}</span></div>
          ${p.description ? `<p class="tiny muted">${esc(p.description.length > 140 ? p.description.slice(0, 138) + '…' : p.description)}</p>` : ''}
          ${p.why && p.enabled ? `<div class="why">${esc(p.why)}</div>` : ''}
          <div class="ctl">${isId ? '' : `<label class="tog"><input type="checkbox" data-promo="${p.id}" ${p.enabled ? 'checked' : ''}><span></span></label>`}
            <button class="btn small" data-queue="${isId ? 'id:station' : 'promo:' + p.id}" data-next="1">Next</button>
            <button class="btn small ghost" data-queue="${isId ? 'id:station' : 'promo:' + p.id}">Queue</button></div>
        </div></article>`;
    }).join('');
  } else {
    $('#more').hidden = true;
    html = `<div class="hist">${lib.recent.filter(r => !query || (r.name || '').toLowerCase().includes(query)).map(r => `<div class="h">
        <span class="t">${clockAt(r.at, true)}</span>
        <div class="thumb ${r.kind !== 'ad' ? 'ident' : ''}" style="background-image:url('${picture(r)}')"></div>
        <div class="nm"><b>${esc(r.name || r.id)}</b><small>${esc(KIND_WORD[r.kind] || r.kind)} · ${mmss(r.seconds)} of ${mmss(r.length)}${r.skipped ? ' · skipped' : r.complete ? '' : ' · cut short'}</small></div>
        <span class="chip" style="border-color:${colourOf(r)}">${esc(BY[r.by] || r.by || '')}</span></div>`).join('') || '<p class="muted">Nothing has aired on Ads 5 yet.</p>'}</div>`;
  }
  cards.style.display = tab === 'history' ? 'block' : '';
  cards.innerHTML = html;
  $('#empty').hidden = !!html;
  frame();
}
$('#cards').addEventListener('change', async e => {
  const el = e.target;
  try {
    if (el.dataset.enable) { await api(`v1/ads/${el.dataset.enable}`, {enabled: el.checked}); toast(el.checked ? 'On for Ads 5' : 'Off for Ads 5'); }
    if (el.dataset.promo) { await api(`v1/promos/${el.dataset.promo}`, {enabled: el.checked}); toast(el.checked ? 'Ident on' : 'Ident off'); }
    if (el.dataset.limit) {
      const v = JSON.parse(el.value);
      await api(`v1/ads/${el.dataset.limit}`, {limit: v && {count: v[0], minutes: v[1]}});
      toast('Limit saved');
    }
    loadLibrary(true); poll();
  } catch (err) { toast(err.message, true); loadLibrary(true); }
});
$('#cards').addEventListener('click', async e => {
  const b = e.target.closest('button');
  if (!b) return;
  try {
    if (b.dataset.queue) {
      const [kind, id] = b.dataset.queue.split(':');
      const r = await api('v1/next', {op: 'add', kind, id, next: !!b.dataset.next});
      status = r.status; renderStatus();
      toast(`${r.entry.name}: ${b.dataset.next ? 'plays next' : 'queued'}`);
    }
    if (b.dataset.reset) { await api(`v1/ads/${b.dataset.reset}`, {limits_from: 'now'}); toast('It may air again'); loadLibrary(true); }
  } catch (err) { toast(err.message, true); }
});

function renderPrep() {
  const c = lib.clips;
  $('#prep-text').textContent = `${c.ready} of ${c.total}${c.failed ? ` · ${c.failed} failed` : ''}`;
  $('#prep-bar').style.width = (100 * c.ready / Math.max(1, c.total)).toFixed(1) + '%';
  $('#prep-working').textContent = c.working.length ? 'Encoding ' + c.working.map(w => w.name).join(', ') + (c.queued ? ` · ${c.queued} waiting` : '') : (c.ready >= c.total ? 'The whole library is ready.' : '');
}

$('#fork').onclick = () => $('#confirm').showModal();
$('#confirm').addEventListener('close', async () => {
  if ($('#confirm').returnValue !== 'ok') return;
  try { await api('v1/fork', {}); toast("VizelVision's settings copied to Ads 5"); loadLibrary(true); poll(); }
  catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- start
setInterval(() => { $('#clock').textContent = new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit', second: '2-digit'}); }, 1000);
setInterval(poll, 1000);
setInterval(frame, 250);
setInterval(() => loadLibrary(false), 15000);
setInterval(() => lib && wheel(lib.settings), 30000);
loadLibrary(true).then(poll);
watch();
