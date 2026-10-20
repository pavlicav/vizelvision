// Crawl: the register of everything the crawl can air (GET /v1/crawl/alerts), what is on the
// bar, the plan, and every control of the rotation (GET/POST /v1/crawl…).
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const q = name => document.querySelector(`[data-id="${name}"]`);
  const MODE_NAMES = {always: 'Always on', popups: 'Pop-ups', quiet: 'Important only'};
  const CONTEXT_NAMES = {program: 'Programs', game: 'Live games', off_air: 'Off-air card', ident: 'Station ID'};
  const LEAGUES = {mlb: 'MLB', nfl: 'NFL', ncaaf: 'College Football', nba: 'NBA', nhl: 'NHL', wnba: 'WNBA', nwsl: 'NWSL'};
  const PLAYOFFS = {mlb: 'All playoffs, through the World Series', ncaaf: 'All bowls and playoffs'};
  // A favorite's game, by what the planner did with it (favorites.py).
  const FAV_STATUS = {scheduled: ['pvw', 'On the Schedule'], by_hand: ['pvw', 'Scheduled by hand'], off: ['', 'Would go on air'],
    removed: ['', 'Removed from the Schedule'], tbd: ['', 'Time to be announced'], no_channel: ['warn', 'No channel'], error: ['warn', 'Could not schedule']};
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const DURATIONS = [[30, '30 minutes'], [60, '1 hour'], [120, '2 hours'], [240, '4 hours'], [720, '12 hours'], [0, 'Until cleared']];
  const STATUS = {on_air: ['pgm', 'On air'], looping: ['pgm', 'Looping'], next: ['touch', 'Next'], held: ['', 'Held'], muted: ['', 'Muted'], duplicate: ['', 'Duplicate']};
  const view = {scope: VV.store.get('crawlScope', 'alert'), status: '', source: '', query: '', tab: VV.store.get('crawlTab', 'manual')};
  const expanded = new Set();
  const dirty = {rules: false, segments: false, messages: false, transit: false, important: false, override: false};
  let data = null, reg = null, busy = false, busRoutes = null, routes = [], messages = [], favs = null;
  const teams = {};

  /* Fetching and acting ------------------------------------------------------------------------------------- */
  async function load() {
    const [crawl, register] = await Promise.all([api('v1/crawl'), api('v1/crawl/alerts').catch(e => ({ready: false, error: e.message, items: [], plan: {}}))]);
    data = crawl; reg = register; render();
  }
  async function act(work, message) {
    if (busy) return;
    busy = true;
    try { const result = await work(); if (result?.settings) data = result; if (message) toast(message, {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
    finally { busy = false; await load().catch(() => {}); }
  }
  const mark = part => { dirty[part] = true; const hint = q(part + '-dirty'); if (hint) hint.textContent = 'Unsaved changes.'; };
  const clean = part => { dirty[part] = false; const hint = q(part + '-dirty'); if (hint) hint.textContent = ''; };
  const editing = panel => document.querySelector(`[data-panel="${panel}"]`)?.contains(document.activeElement);

  /* The bar now, and the layers ---------------------------------------------------------------------------- */
  const screen = CrawlBar.screen({strip: true}); $('screen').append(screen);
  const draftScreen = CrawlBar.screen({strip: true, label: 'Preview of the override'}); $('draft').append(h('span', {class: 'label'}, 'Preview'), draftScreen);
  function renderTop() {
    const status = data.status, rot = data.rotation || {}, state = $('state');
    const chips = [];
    if (data.master_error) chips.push(h('span', {class: 'chip warn'}, 'Master unavailable'));
    else if (!status) chips.push(h('span', {class: 'chip'}, 'Waiting for master'));
    else {
      if (rot.context) chips.push(h('span', {class: 'chip'}, (CONTEXT_NAMES[rot.context] || rot.context) + ' · ' + (MODE_NAMES[rot.mode] || rot.mode)));
      if (rot.mode === 'popups' && rot.next_round) chips.push(h('span', {class: 'chip', title: 'Everything due airs together then; new items pop up at once'}, rot.next_round * 1000 > Date.now() ? 'Next round ≈ ' + fmt.clock(rot.next_round) : 'Round due'));
      if (rot.position === 'top') chips.push(h('span', {class: 'chip touch', title: 'Clear of the score bug along the bottom'}, 'Bar at the top' + (rot.league ? ' · ' + (LEAGUES[rot.league] || rot.league) : '')));
      for (const name of ['eas', 'nws']) if (status[name]?.error) chips.push(h('span', {class: 'chip warn', title: status[name].error}, (name === 'eas' ? 'EAS decoder' : 'NWS') + ' unreachable'));
      if (rot.error) chips.push(h('span', {class: 'chip warn', title: rot.error}, 'Rotation paused'));
      if (status.error) chips.push(h('span', {class: 'chip warn', title: status.error}, 'Crawl error'));
    }
    VV.fill(state, chips);
    const kind = status?.on_air ? status.kind : null;
    $('bar-lamp').className = 'lamp ' + (kind === 'important' ? 'pgm' : kind ? 'touch' : '');
    CrawlBar.draw(screen, status?.on_air ? {label: status.label, flag: status.flag, style: status.style, position: status.position, items: status.items || []} : null);
    const where = status?.position === 'top' ? ' Along the top, clear of the score bug.' : '';
    $('bar-note').textContent = (kind === 'important' ? 'Important news: runs continuously over everything until it ends.' : kind === 'override' ? 'The override holds the bar until it is cleared or ends.'
      : kind === 'bulletin' ? (status.flag ? 'New items, on their own; the bar slides away after one pass.' : status.label === 'UPDATE' ? 'The update round: everything due, together, one pass.' : 'A pop-up running its pass; the bar slides away when it ends.')
      : 'The bar is off. A mimic of master\'s bar: same colours and wording, 120 px a second at 720p.') + where;
    const s = data.settings, active = layer => s[layer].text && (!s[layer].until || Date.parse(s[layer].until) > Date.now());
    const layerRow = (n, name, on, detail, cls) => h('li', {class: (on ? 'on ' : '') + (cls || '')}, h('span', {class: 'n'}, n), h('div', h('strong', name), h('small', detail)), h('span', {class: 'lamp ' + (on ? (cls === 'important' ? 'pgm' : 'touch') : '')}));
    const severe = (status?.alerts || []).filter(a => a.important && !a.dismissed && !a.duplicate).length;
    VV.fill($('layers'),
      layerRow('1', 'Important', kind === 'important', severe ? severe + ' severe alert' + (severe > 1 ? 's' : '') + (active('important') ? ' + your message' : '') : active('important') ? 'Your message, ' + (s.important.until ? 'until ' + fmt.when(s.important.until) : 'until cleared') : 'Severe alerts and the important message', 'important'),
      layerRow('2', 'Override', kind === 'override', active('override') ? (kind === 'override' ? 'On the bar ' : 'Set, waiting ') + (s.override.until ? 'until ' + fmt.when(s.override.until) : 'until cleared') : 'Your message, holding the bar'),
      layerRow('3', 'Rotation', kind === 'bulletin', kind === 'bulletin' ? (status.flag ? 'New: ' + (status.label || 'items') : status.label === 'UPDATE' ? 'The update round' : (status.label || 'A segment') + ' pop-up') : rot.mode === 'quiet' ? 'Quiet in this context' : (MODE_NAMES[rot.mode] || '—') + (reg?.plan?.slots?.[0] ? ' · next ' + segName(reg.plan.slots[0].segment) + ' ' + fmt.rel(reg.plan.slots[0].at) : '')));
  }
  const segName = seg => seg === 'round' ? 'Update round' : data?.segments?.[seg]?.name || seg;
  // A slot or history entry, in words: a round names what it carries.
  const slotName = s => s.segment === 'round' ? 'Update round' + ((s.segments || []).length ? ': ' + s.segments.map(segName).join(', ') : '') : segName(s.segment) + (s.new ? ' · new' : '');
  // The next planned pop-ups (and loops), in plain words.
  function renderComing() {
    const plan = reg?.plan || {}, byId = new Map((reg?.items || []).map(i => [i.id, i]));
    const entries = [...(plan.slots || []).map(s => ({at: s.at, what: s.segment === 'round' ? slotName(s) : segName(s.segment) + (s.new ? ' · new items' : ''), ids: s.ids, context: s.context})),
      ...(plan.loops || []).map(l => ({at: l.start, what: 'Loop over the ' + (CONTEXT_NAMES[l.context] || l.context).toLowerCase(), ids: l.ids, context: l.context}))].sort((a, b) => a.at - b.at).slice(0, 4);
    VV.fill($('coming'), entries.length ? entries.map(e => h('li', h('span', {class: 't'}, '≈ ' + fmt.clock(e.at), h('small', {class: 'muted', style: {display: 'block', fontSize: '11px', marginTop: '3px'}}, fmt.rel(e.at))),
      h('span', {class: 'small'}, h('strong', e.what), h('span', {class: 'muted'}, ' · ' + e.ids.map(i => byId.get(i)).filter(Boolean).map(i => i.tag || i.heading || i.source_name).filter((v, i, a) => a.indexOf(v) === i).slice(0, 4).join(', '))),
      h('span', {class: 'tiny muted'}, e.ids.length + (e.ids.length === 1 ? ' item' : ' items'))))
      : h('li', {class: 'hint', style: {display: 'block'}}, reg?.ready ? 'Nothing planned in the next three hours' + (reg.higher ? ': a higher layer holds the bar.' : '.') : 'Waiting for the rotation…'));
  }

  /* The register ------------------------------------------------------------------------------------------------ */
  const sources = new Map();
  function visible(item) {
    if (view.scope === 'alert' && item.kind !== 'alert') return false;
    if (view.status === 'live' && !['on_air', 'looping'].includes(item.status)) return false;
    if (view.status && view.status !== 'live' && item.status !== view.status && !(view.status === 'muted' && item.status === 'duplicate')) return false;
    if (view.source && item.source !== view.source) return false;
    if (view.query && ![item.tag, item.heading, item.text, item.source_name, item.segment_name, item.id, item.why].join(' ').toLowerCase().includes(view.query)) return false;
    return true;
  }
  function statusCell(item) {
    const [lamp, word] = STATUS[item.status] || ['', item.status];
    const name = item.status === 'looping' && item.layer === 'rotation' ? 'In loop' : word;
    return h('span', {class: 'st'}, h('span', {class: 'lamp ' + lamp + (item.new ? ' blink' : '')}), name, item.new ? h('span', {class: 'chip touch', style: {height: '18px'}}, 'New') : null);
  }
  function airingCell(item) {
    if (item.airing === 'first') return h('span', {class: 'airing first', title: item.air_count ? 'Its first airing is on now' : 'Not aired yet'}, 'FIRST');
    const before = item.air_count - (['on_air', 'looping'].includes(item.status) ? 1 : 0);
    return h('span', {class: 'airing repeat', title: 'Aired ' + item.air_count + ' time' + (item.air_count === 1 ? '' : 's') + ' so far'}, 'REPEAT', h('small', {class: 'muted', style: {display: 'block', fontWeight: 400, marginTop: '3px'}}, 'aired ' + before + '×'));
  }
  function nextCell(item) {
    if (item.status === 'on_air') return h('div', {class: 'when', style: {color: 'var(--pgm)'}}, 'Now');
    if (item.status === 'looping') return h('div', {class: 'when'}, 'Continuous', h('small', item.expires ? 'until ' + fmt.when(item.expires) : 'until it ends'));
    if (item.next_at) return h('div', {class: 'when'}, '≈ ' + fmt.clock(item.next_at), h('small', fmt.rel(item.next_at) + (item.next_how === 'new' ? ' · at once' : item.next_how === 'loop' ? ' · loop' : item.next_how === 'round' ? ' · round' : '')));
    return h('div', {class: 'when muted'}, '—');
  }
  function itemText(item) {
    return h('div', {class: 'what'}, h('div', {class: 'txt'}, item.tag ? h('span', {class: 'tagbox'}, item.tag) : null, item.heading ? h('b', item.heading) : null, item.text || h('i', {class: 'muted'}, 'no text')),
      item.expires && item.kind === 'alert' ? h('small', {class: 'tiny muted'}, 'until ' + fmt.when(item.expires)) : null);
  }
  function actions(item) {
    const box = h('div', {class: 'actions', style: {justifyContent: 'flex-end', flexWrap: 'nowrap'}});
    const manual = item.source === 'manual', layered = item.layer !== 'rotation';
    const button = (text, title, run, cls = '') => { const b = h('button', {type: 'button', class: 'xs ' + cls, title, 'aria-label': text + ': ' + (item.heading || item.text).slice(0, 60)}, text); b.onclick = e => { e.stopPropagation(); run(); }; box.append(b); return b; };
    if (!manual && !layered && !['muted', 'duplicate'].includes(item.status)) {
      const air = button('Air now', 'Pop this item up now, whatever the rules', () => act(() => api('v1/crawl/alerts/' + encodeURIComponent(item.id), {action: 'air'}), 'It pops up within a few seconds.'));
      air.disabled = !!reg?.higher || item.status === 'on_air';
    }
    if (!manual) {
      const muted = item.status === 'muted' || item.muted;
      button(muted ? 'Unmute' : 'Mute', muted ? 'Put it back in the crawl' : 'Take it out of the crawl' + (['eas', 'nws'].includes(item.source) ? ' (dismissed in crawl.json; the worker honours it)' : ''),
        () => act(() => api('v1/crawl/alerts/' + encodeURIComponent(item.id), {action: muted ? 'unmute' : 'mute'}), muted ? 'Back in the crawl.' : 'Muted: it no longer airs.'), muted ? '' : 'quiet');
      if (item.status !== 'muted') button('Hold', 'Put it in the override slot: it holds the bar', () => hold(item), 'quiet');
    } else box.append(h('a', {class: 'btn xs quiet', href: '#manual', onclick: e => { e.stopPropagation(); tab('manual'); }}, 'Edit'));
    return box;
  }
  function detail(item) {
    const kv = [['ID', h('code', item.id)], ['Source', item.source_name + ' · ' + item.segment_name + ' segment'], ['Layer', {important: 'Important (worker, continuous)', override: 'Override (worker)', rotation: 'Rotation (desk)'}[item.layer]],
      ['Status', item.why], item.severity ? ['Severity', item.severity] : null, item.event ? ['Event', item.event] : null, item.areas ? ['Areas', item.areas] : null, item.by ? ['From', item.by] : null,
      item.issued ? ['Issued', fmt.full(item.issued)] : null, item.expires ? ['Ends', fmt.full(item.expires)] : null, ['First seen', item.first_seen ? fmt.full(item.first_seen) : '—'],
      ['First aired', item.first_aired ? fmt.full(item.first_aired) : 'Not yet'], ['Airings', String(item.air_count)]].filter(Boolean);
    const airings = (item.airings || []).slice().reverse();
    return h('div', {class: 'cols-2', style: {gap: '18px'}},
      h('div', {class: 'stack tight'}, h('p', {style: {fontSize: '15px'}}, item.tag ? h('span', {class: 'tagbox'}, item.tag) : null, item.heading ? h('b', item.heading + ' ') : null, item.text),
        h('dl', {class: 'kv'}, kv.map(([k, v]) => [h('dt', k), h('dd', v)]))),
      h('div', {class: 'stack tight'}, h('span', {class: 'label'}, 'Airings'), airings.length ? h('table', {class: 'data'}, h('thead', h('tr', ['Started', 'Ended', 'How', 'Where', 'Layer'].map(t => h('th', t)))),
        h('tbody', airings.map(a => h('tr', h('td', {class: 'mono small'}, fmt.when(a.at)), h('td', {class: 'mono small'}, a.ended ? fmt.clock(a.ended) : 'on air'), h('td', {class: 'small'}, (a.how || '—') + (a.forced ? ' · aired by hand' : '') + (a.new ? ' · new' : '')),
          h('td', {class: 'small'}, CONTEXT_NAMES[a.context] || a.context || '—'), h('td', {class: 'small'}, a.layer))))) : h('p', {class: 'hint'}, 'Not aired since the ledger started keeping track.')));
  }
  function renderRegister() {
    const body = $('reg-body');
    if (!reg?.ready) {
      body.replaceChildren(); $('reg-empty').hidden = false;
      $('reg-empty').textContent = reg?.error ? 'The register is not available: ' + reg.error : 'Waiting for the rotation’s first look…';
      return;
    }
    const items = reg.items || [];
    $('n-alert').textContent = items.filter(i => i.kind === 'alert').length; $('n-all').textContent = items.length;
    for (const i of items) sources.set(i.source, i.source_name);
    const select = $('source-filter'), chosen = select.value;
    if (select.options.length - 1 !== sources.size) { select.replaceChildren(new Option('Every source', ''), ...[...sources].sort((a, b) => a[1].localeCompare(b[1])).map(([v, n]) => new Option(n, v))); select.value = chosen; }
    const shown = items.filter(visible);
    $('reg-lamp').className = 'lamp ' + (items.some(i => i.layer === 'important' && i.status === 'looping') ? 'pgm' : items.some(i => i.status === 'on_air') ? 'touch' : '');
    $('reg-updated').textContent = 'as of ' + fmt.clockSec(reg.now) + ' · ' + (reg.counts.next || 0) + ' planned · ' + (reg.counts.held || 0) + ' held';
    const rows = [];
    let lastKind = null;
    for (const item of shown) {
      if (view.scope === 'all' && item.kind !== lastKind) { lastKind = item.kind; rows.push(h('tr', {class: 'kind-sep'}, h('td', {colspan: 8}, item.kind === 'alert' ? 'Alerts' : 'Everything else: scores, weather, coming up, Cairo, messages'))); }
      const open = expanded.has(item.id);
      const tr = h('tr', {class: 'item' + (['muted', 'duplicate'].includes(item.status) ? ' muted' : ''), 'aria-expanded': String(open), tabindex: '0', data: {id: item.id, status: item.status}},
        h('td', {class: 'c-status'}, statusCell(item)),
        h('td', h('span', {class: 'badge s-' + item.source}, item.source_name)),
        h('td', {class: 'c-what'}, itemText(item)),
        h('td', airingCell(item)),
        h('td', h('div', {class: 'when'}, item.last_aired ? fmt.when(item.last_aired) : '—', item.last_aired ? h('small', fmt.rel(item.last_aired)) : null)),
        h('td', nextCell(item)),
        h('td', h('div', {class: 'why'}, item.why)),
        h('td', {class: 'acts'}, actions(item)));
      const toggle = () => { expanded.has(item.id) ? expanded.delete(item.id) : expanded.add(item.id); renderRegister(); };
      tr.onclick = toggle; tr.onkeydown = e => { if (e.key === 'Enter' && e.target === tr) toggle(); };
      rows.push(tr);
      if (open) rows.push(h('tr', {class: 'detail'}, h('td', {colspan: 8}, detail(item))));
    }
    const focused = document.activeElement?.closest?.('tr.item')?.dataset.id;
    body.replaceChildren(...rows);
    if (focused) body.querySelector(`tr.item[data-id="${CSS.escape(focused)}"]`)?.focus({preventScroll: true});
    $('reg-empty').hidden = !!shown.length;
    $('reg-empty').textContent = items.length ? 'Nothing matches these filters.' : 'The crawl has nothing to say right now: no alerts, and no segment lists anything.';
    const gone = reg.gone || [];
    $('gone-box').hidden = !gone.length;
    VV.fill($('gone'), gone.map(g => h('li', h('div', {class: 'row', style: {gap: '8px'}}, h('span', {class: 'badge'}, g.source), h('span', {class: 'small grow clip'}, (g.tag ? g.tag + ' · ' : '') + (g.heading ? g.heading + ' ' : '') + g.text),
      h('span', {class: 'tiny muted mono'}, 'aired ' + g.air_count + '× · last listed ' + fmt.when(g.last_listed))))));
  }
  document.querySelectorAll('[data-scope]').forEach(b => { b.onclick = () => { view.scope = b.dataset.scope; VV.store.set('crawlScope', view.scope); document.querySelectorAll('[data-scope]').forEach(x => x.setAttribute('aria-selected', String(x === b))); renderRegister(); }; });
  document.querySelectorAll('[data-scope]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.scope === view.scope)));
  document.querySelectorAll('[data-status]').forEach(b => { b.onclick = () => { view.status = b.dataset.status; document.querySelectorAll('[data-status]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); renderRegister(); }; });
  $('source-filter').onchange = e => { view.source = e.target.value; renderRegister(); };
  $('reg-search').oninput = e => { view.query = e.target.value.trim().toLowerCase(); renderRegister(); };

  // Hold: the item goes into the override slot, for as long as you choose.
  function hold(item) {
    const minutes = h('select', DURATIONS.map(([m, t]) => new Option(t, String(m))));
    minutes.value = '30';
    const text = h('textarea', {maxLength: 500, rows: 3}, ((item.heading ? item.heading + ': ' : '') + item.text).slice(0, 500));
    const go = h('button', {class: 'primary', type: 'button'}, 'Hold on the bar'), cancel = h('button', {class: 'quiet', type: 'button'}, 'Cancel');
    const dialog = h('dialog', {'aria-label': 'Hold an item on the bar'}, h('div', {class: 'head'}, h('h2', 'Hold on the bar')),
      h('div', {class: 'body'}, h('p', {class: 'hint'}, 'Puts this in the override slot: it takes the bar now and holds it, ahead of the rotation (only important news comes first). It replaces any override that is set.'),
        h('label', {class: 'field'}, h('span', 'Text'), text), h('label', {class: 'field'}, h('span', 'For'), minutes)), h('div', {class: 'foot'}, cancel, go));
    cancel.onclick = () => dialog.close(); dialog.addEventListener('close', () => dialog.remove());
    go.onclick = () => { dialog.close(); act(() => api('v1/crawl/override', {text: text.value.trim(), label: (item.tag || data.segments[item.segment]?.label || '').slice(0, 24), minutes: Number(minutes.value) || null, style: item.kind === 'alert' && item.source !== 'alertdc' ? 'urgent' : 'station'}), 'Held on the bar.'); };
    document.body.append(dialog); dialog.showModal();
  }

  /* The plan, drawn ---------------------------------------------------------------------------------------------- */
  function renderTimeline() {
    if (!VV.machinery.on || !reg?.plan?.until) return;
    const svg = $('timeline'), plan = reg.plan, now = reg.now, end = plan.until, W = 1200, L = 10, R = 1190, X = t => L + (R - L) * (t - now) / (end - now);
    const gap = data.settings.rules.gap_minutes * 60;
    $('r-round').textContent = data.settings.rules.round_minutes; $('r-gap').textContent = data.settings.rules.gap_minutes;
    $('plan-note').textContent = plan.slots.length + ' pop-ups planned' + (plan.higher_until ? ' · a higher layer holds the bar' : '');
    const esc = t => String(t).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
    const tone = {program: '#4fb3ff', game: '#ffb340', off_air: '#8e99a3', ident: '#b495ff'};
    let out = '<defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="4" height="8" fill="#ffffff10"/></pattern></defs>';
    for (const s of plan.spans) {
      const x = X(s.start), w = Math.max(1, X(s.end) - x), c = tone[s.context] || '#8e99a3';
      out += `<rect x="${x}" y="20" width="${w}" height="26" fill="${c}22" stroke="${c}66"/>`
        + (w > 70 ? `<text x="${x + 6}" y="37" fill="${c}">${esc((CONTEXT_NAMES[s.context] || s.context).toUpperCase() + ' · ' + (MODE_NAMES[s.mode] || s.mode).toUpperCase())}</text>` : '');
      if (s.mode === 'quiet') out += `<rect x="${x}" y="58" width="${w}" height="92" fill="url(#hatch)"/>`;
    }
    for (const loop of plan.loops || []) { const x = X(loop.start), w = Math.max(2, X(loop.end) - x); out += `<rect x="${x}" y="60" width="${w}" height="88" fill="#34d07a14" stroke="#34d07a55" stroke-dasharray="4 3"/><text x="${x + 6}" y="76" fill="#34d07a">LOOP · ${loop.ids.length} items</text>`; }
    if (plan.higher_until) out += `<rect x="${L}" y="58" width="${X(plan.higher_until) - L}" height="92" fill="#ff443818" stroke="#ff443866"/><text x="${L + 6}" y="74" fill="#ff8f86">HIGHER LAYER HOLDS THE BAR</text>`;
    plan.slots.forEach((slot, i) => {
      const x = X(slot.at), w = Math.max(3, X(slot.at + slot.duration) - x), y = 92 + (i % 3) * 18;
      if (gap) out += `<rect x="${x + w}" y="60" width="${Math.max(0, X(slot.at + slot.duration + gap) - x - w)}" height="88" fill="#ffb3400d"/>`;
      out += `<rect x="${x}" y="${y}" width="${w}" height="14" rx="2" fill="${slot.new ? '#4fb3ff' : '#c3cbd1'}"/><text x="${x + w + 4}" y="${y + 11}" fill="#c3cbd1">${esc(slot.segment === 'round' ? 'Round · ' + (slot.segments || []).length : segName(slot.segment) + (slot.new ? ' · new' : ''))}</text>`;
    });
    for (let t = Math.ceil(now / 1800) * 1800; t < end; t += 1800) out += `<line x1="${X(t)}" x2="${X(t)}" y1="150" y2="160" stroke="#46515b"/><text x="${X(t) - 16}" y="176" class="muted">${esc(fmt.clock(t))}</text>`;
    out += `<line x1="${L}" x2="${R}" y1="150" y2="150" stroke="#2f373f"/><line x1="${L}" x2="${L}" y1="14" y2="160" stroke="#ff4438" stroke-width="2"/><text x="${L + 4}" y="12" fill="#ff8f86">NOW</text>`;
    out += `<text x="${L}" y="200" class="muted">${esc('Shaded after each pop-up: the ' + data.settings.rules.gap_minutes + ' min gap. Hatched: no pop-ups in that context.')}</text>`;
    svg.setAttribute('viewBox', `0 0 ${W} 210`); svg.innerHTML = out;
  }
  document.addEventListener('vv:machinery', renderTimeline);

  /* Messages on the bar: important and override -------------------------------------------------------------------- */
  const draftOverride = () => { const text = q('override-text').value.trim().replace(/\s+/g, ' '); return text ? {label: q('override-label').value.trim().toUpperCase(), style: q('override-style').value, items: [{tag: '', heading: '', text}]} : null; };
  for (const name of ['important', 'override']) {
    const select = q(name + '-minutes');
    DURATIONS.forEach(([m, t]) => select.append(new Option(t, String(m))));
    select.value = name === 'important' ? '60' : '0';
    [name + '-text', name + '-label'].concat(name === 'override' ? ['override-style'] : []).forEach(n => q(n).addEventListener('input', () => { dirty[name] = true; if (name === 'override') CrawlBar.draw(draftScreen, draftOverride()); }));
    q(name + '-go').onclick = async () => {
      const text = q(name + '-text').value.trim();
      if (!text) { toast('Type the ' + (name === 'important' ? 'important message' : 'override') + ' first.', {error: true}); return; }
      if (name === 'important' && !await VV.confirm('Put this on the bar in red, over everything, until it ends or is cleared?', {title: 'Important message', ok: 'Put on air', danger: true, detail: text})) return;
      dirty[name] = false;
      act(() => api('v1/crawl/' + name, {text, label: q(name + '-label').value.trim(), minutes: Number(q(name + '-minutes').value) || null, ...(name === 'override' ? {style: q('override-style').value} : {})}),
        (name === 'important' ? 'Important message' : 'Override') + ' goes on air within a second.');
    };
    q(name + '-clear').onclick = () => { dirty[name] = false; act(() => api('v1/crawl/' + name, {text: '', minutes: null}), (name === 'important' ? 'Important message' : 'Override') + ' cleared.'); };
  }
  function renderManual() {
    for (const name of ['important', 'override']) {
      const layer = data.settings[name], live = layer.text && (!layer.until || Date.parse(layer.until) > Date.now());
      $(name + '-state').textContent = live ? 'On · ' + (layer.until ? 'until ' + fmt.when(layer.until) : 'until cleared') : 'Off';
      $(name + '-lamp').className = 'lamp ' + (live ? (name === 'important' ? 'pgm' : 'touch') : '');
      if (!dirty[name] && !editing('manual')) {
        q(name + '-text').value = live ? layer.text : ''; q(name + '-label').value = layer.label;
        if (name === 'override') q('override-style').value = layer.style;
      }
    }
    CrawlBar.draw(draftScreen, draftOverride());
  }

  /* Rules ----------------------------------------------------------------------------------------------------------- */
  function renderRules() {
    if (dirty.rules || editing('rules')) return;
    const rules = data.settings.rules;
    VV.fill(q('rules'), Object.entries(data.contexts).map(([context, name]) => {
      const select = h('select', {data: {context}}, data.modes.map(mode => new Option(MODE_NAMES[mode] || mode, mode)));
      select.value = rules[context]; select.onchange = () => mark('rules');
      return h('label', {class: 'field'}, h('span', name), select);
    }));
    q('round').value = rules.round_minutes; q('gap').value = rules.gap_minutes;
    VV.fill(q('top-leagues'), Object.entries(LEAGUES).map(([league, name]) => {
      const box = h('input', {type: 'checkbox', checked: rules.top_leagues.includes(league), data: {league}});
      box.onchange = () => mark('rules');
      return h('label', {class: 'check'}, box, h('span', name));
    }));
  }
  q('round').oninput = q('gap').oninput = () => mark('rules');
  q('save-rules').onclick = () => {
    const rules = {round_minutes: Number(q('round').value), gap_minutes: Number(q('gap').value),
      top_leagues: [...document.querySelectorAll('[data-id="top-leagues"] [data-league]')].filter(b => b.checked).map(b => b.dataset.league)};
    document.querySelectorAll('[data-context]').forEach(s => { rules[s.dataset.context] = s.value; });
    clean('rules'); act(() => api('v1/crawl', {rules}), 'Rules saved.');
  };

  /* Segments -------------------------------------------------------------------------------------------------------- */
  function renderSegments() {
    if (dirty.segments || editing('segments')) return;
    const box = q('segments'); box.replaceChildren();
    for (const [seg, meta] of Object.entries(data.segments)) {
      const options = data.settings.segments[seg], live = data.rotation?.segments?.[seg] || {}, extra = data.feeds?.segments?.[seg];
      const check = (text, set, cls = 'check') => { const input = h('input', {type: 'checkbox'}); set(input); if (input.dataset.field !== 'enabled') input.addEventListener('input', () => mark('segments')); return h('label', {class: cls}, input, h('span', text)); };
      const run = h('button', {type: 'button', class: 'xs quiet', 'aria-label': 'Run ' + meta.name + ' now'}, 'Run now');
      run.onclick = () => act(() => api('v1/crawl/run', {segment: seg}), meta.name + ' runs within a few seconds.');
      const every = h('input', {type: 'number', min: 2, max: 240, value: options.every, style: {width: '80px'}, data: {segment: seg, field: 'every'}});
      every.oninput = () => mark('segments');
      const feed = live.feed, notes = [];
      if (feed?.error) notes.push('Feed error: ' + feed.error); else if (feed?.fetched_at) notes.push('Fetched ' + fmt.when(feed.fetched_at)); else if (feed) notes.push(feed.running ? 'Loading…' : 'Not fetching (off)');
      if (live.last_aired) notes.push('last pop-up ' + fmt.when(live.last_aired));
      if (live.next_planned) notes.push('next ' + fmt.rel(live.next_planned));
      if (data.rotation?.new?.[seg]) notes.push(data.rotation.new[seg] + ' new, waiting');
      if (seg === 'cairo') notes.push('off-air card only, while Cairo Radio is the off-air audio');
      if (seg === 'scores' && favs && !favs.favorites.length) notes.push('choose favorites');
      if (seg === 'messages' && !data.settings.messages.length) notes.push('add station messages');
      if (seg === 'election') {
        const shown = feed?.elections || [];
        if (!shown.length) notes.push('no election tonight (definitions in roku_stream/elections/)');
        for (const e of shown) notes.push(e.name + ': ' + e.sources.map(s => s.name + (s.official ? ' (official)' : '') + ' ' +
          (s.error ? 'unreachable: ' + s.error : !s.at ? 'from 5 min before polls close' : s.contests ? s.contests + ' with results' : (s.note || 'no results yet'))).join(', '));
      }
      const card = h('article', {class: 'seg-card' + (options.enabled ? '' : ' off'), data: {segment: seg}},
        h('div', {class: 'row between'}, check(h('strong', meta.name), n => {
          n.checked = options.enabled; n.dataset.segment = seg; n.dataset.field = 'enabled';
          n.onchange = async () => {
            if (busy) { n.checked = data.settings.segments[seg].enabled; return; }
            const enabled = n.checked;
            n.disabled = true;
            await act(() => api('v1/crawl', {segments: {[seg]: {enabled}}}), meta.name + (enabled ? ' turned on.' : ' turned off until you turn it back on.'));
            n.checked = data.settings.segments[seg].enabled;
            card.classList.toggle('off', !n.checked);
            n.disabled = false;
          };
        }, 'switch'), h('span', {class: 'badge'}, meta.label), run),
        h('div', {class: 'row'}, extra ? check('Repeat every', n => { n.checked = extra.repeat; n.dataset.feed = seg; n.dataset.option = 'repeat'; }) : h('span', 'Every'), every, h('span', {class: 'small muted'}, 'min'),
          check('only when it changes', n => { n.checked = options.changed_only; n.dataset.segment = seg; n.dataset.field = 'changed_only'; })),
        extra ? check('New items pop up at once (once each)', n => { n.checked = extra.new_now; n.dataset.feed = seg; n.dataset.option = 'new_now'; }) : null,
        extra ? h('div', {class: 'days'}, h('span', {class: 'tiny muted'}, 'Airs during'), Object.entries(data.contexts).map(([context, name]) => check(name, n => { n.checked = extra.contexts.includes(context); n.dataset.feed = seg; n.dataset.airs = context; }))) : null,
        h('p', {class: 'tiny muted'}, notes.join(' · ')),
        h('ul', (live.preview || []).length ? live.preview.map(item => h('li', item.tag ? h('span', {class: 'tagbox', style: {fontSize: '10px'}}, item.tag) : null, item.heading ? h('strong', item.heading + ' ') : null, item.text)) : h('li', {class: 'muted'}, 'Nothing to say right now.')));
      box.append(card);
    }
  }
  q('save-segments').onclick = () => {
    const segments = {}, feedSegments = {};
    document.querySelectorAll('[data-panel=segments] [data-segment][data-field]:not([data-field=enabled])').forEach(n => { (segments[n.dataset.segment] ||= {})[n.dataset.field] = n.type === 'checkbox' ? n.checked : Number(n.value); });
    document.querySelectorAll('[data-panel=segments] [data-feed]').forEach(n => {
      const options = feedSegments[n.dataset.feed] ||= {contexts: []};
      if (n.dataset.option) options[n.dataset.option] = n.checked; else if (n.checked) options.contexts.push(n.dataset.airs);
    });
    const nowhere = Object.entries(feedSegments).find(([, o]) => !o.contexts.length);
    if (nowhere) { toast(data.segments[nowhere[0]].name + ' needs somewhere to air; turn the segment off instead.', {error: true}); return; }
    act(async () => {
      let result = await api('v1/crawl', {segments});
      if (Object.keys(feedSegments).length) result = await api('v1/crawl/feeds', {segments: feedSegments});
      clean('segments');
      return result;
    }, 'Segments saved.');
  };

  /* Sources: alerts, Metro and bus, the weather location ---------------------------------------------------------- */
  function renderFeeds() {
    const s = data.settings, st = data.status || {};
    q('eas').checked = s.eas; q('eas-transcript').checked = s.eas_transcript; q('eas-tests').checked = s.eas_tests; q('nws').checked = s.nws;
    q('areas').textContent = data.areas.map(a => a.name ? `${a.name} (${a.code})` : a.code).join(', ') || 'no areas';
    q('eas-source').textContent = data.eas_url || 'not configured';
    q('zones').textContent = data.nws_zones.join(', ') || 'none configured';
    q('eas-health').textContent = st.eas ? (st.eas.error ? 'unreachable: ' + st.eas.error : 'checked ' + fmt.rel(st.eas.checked_at)) : 'no status';
    q('nws-health').textContent = st.nws ? (st.nws.error ? 'unreachable: ' + st.nws.error : 'checked ' + fmt.rel(st.nws.checked_at)) : 'no status';
    if (!data.feeds) return;
    const weather = data.feeds.weather, feed = data.rotation?.segments?.weather?.feed;
    q('zip-state').textContent = weather.zip ? `${weather.zip} · ${weather.place}: the forecast is for this ZIP` + (feed?.station ? `, “now” from ${feed.station}, the nearest station reporting.` : '.') : 'No ZIP: the forecast and “now” are for the configured station.';
    if (document.activeElement !== q('zip')) q('zip').value = weather.zip;
    if (dirty.transit) return;
    q('rail').checked = data.feeds.transit.rail; q('bus').checked = data.feeds.transit.bus;
    routes = [...data.feeds.transit.routes]; drawRoutes();
  }
  for (const [name, field] of [['eas', 'eas'], ['eas-transcript', 'eas_transcript'], ['eas-tests', 'eas_tests'], ['nws', 'nws']])
    q(name).onchange = () => act(() => api('v1/crawl', {[field]: q(name).checked}), 'Alert settings saved.');
  const routeName = rid => busRoutes?.find(r => r.id === rid)?.name;
  function drawRoutes() {
    VV.fill(q('routes'), routes.length ? routes.map(rid => { const b = h('button', {type: 'button', title: routeName(rid) || '', 'aria-label': 'Stop showing route ' + rid}, rid + ' ✕'); b.onclick = () => { routes = routes.filter(r => r !== rid); mark('transit'); drawRoutes(); }; return b; }) : h('span', {class: 'chip'}, 'Every route'));
    const filter = q('route-filter').value.trim().toLowerCase(), list = q('route-list'); list.replaceChildren();
    if (!filter) return;
    if (!busRoutes) { list.append(h('p', {class: 'hint'}, 'Loading routes…')); return; }
    const found = busRoutes.filter(r => (r.id + ' ' + r.name).toLowerCase().includes(filter)).slice(0, 40);
    if (!found.length) list.append(h('p', {class: 'hint'}, 'No WMATA route matches.'));
    for (const r of found) {
      const check = h('input', {type: 'checkbox', checked: routes.includes(r.id)});
      check.onchange = () => { routes = check.checked ? [...routes, r.id] : routes.filter(x => x !== r.id); mark('transit'); drawRoutes(); };
      list.append(h('label', {class: 'check'}, check, h('span', r.id + ' · ' + r.name.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()))));
    }
  }
  q('route-filter').oninput = async () => { drawRoutes(); if (!busRoutes) { try { busRoutes = (await api('v1/crawl/bus-routes')).routes; } catch (e) { busRoutes = []; toast(e.message, {error: true}); } drawRoutes(); } };
  q('rail').onchange = q('bus').onchange = () => mark('transit');
  q('save-transit').onclick = () => { clean('transit'); act(() => api('v1/crawl/feeds', {transit: {rail: q('rail').checked, bus: q('bus').checked, routes}}), 'Metro and bus options saved.'); };
  q('save-zip').onclick = () => { const zip = q('zip').value.trim(); if (!/^\d{5}$/.test(zip)) { toast('Type a five-digit ZIP code.', {error: true}); return; } act(() => api('v1/crawl/feeds', {weather: {zip}}), 'Weather location saved; the forecast updates within a few seconds.'); };
  q('clear-zip').onclick = () => act(() => api('v1/crawl/feeds', {weather: {zip: ''}}), 'Weather is back to the configured station.');

  /* Favorites ------------------------------------------------------------------------------------------------------------ */
  // Teams and whole playoffs, best first (GET/POST /v1/favorites): the Scores segment's games,
  // and with on air on, games the Schedule gets.
  q('league').append(...Object.entries(LEAGUES).map(([v, n]) => new Option(n, v)));
  async function loadTeams(league) { if (!teams[league]) teams[league] = (await api('v1/sports/teams?league=' + league)).teams; return teams[league]; }
  function favName(fid) {
    const [league, team] = fid.split(':');
    if (team === 'playoffs') return (LEAGUES[league] || league) + ' · ' + (PLAYOFFS[league] || 'All playoffs');
    const found = (teams[league] || []).find(t => t.id === team);
    return (LEAGUES[league] || league) + ' · ' + (found ? found.name : '#' + team);
  }
  async function loadFavorites() { favs = await api('v1/favorites'); renderFavorites(); }
  async function saveFavorites(changes, message) {
    try { favs = await api('v1/favorites', changes); toast(message, {ok: true}); }
    catch (e) { toast(e.message, {error: true}); }
    renderFavorites();
    // The planner reschedules within a moment.
    setTimeout(() => loadFavorites().catch(() => {}), 1500);
  }
  function favGame(g) {
    const [cls, text] = FAV_STATUS[g.status] || ['', g.status];
    const start = g.start || g.start_time, where = g.target ? VV.label(g.target) : null;
    const why = g.status === 'no_channel' ? (g.networks.length ? 'On ' + g.networks.join(', ') + ': not a channel VizelVision gets' : 'No TV listing')
      : g.status === 'removed' ? 'Taken off the Schedule; schedule it by hand to air it' : g.status === 'error' ? g.error : null;
    return h('li', h('span', {class: 't'}, g.tbd ? 'TBD' : fmt.when(start)),
      h('div', h('strong', g.title), h('small', '★ ' + g.rank + ' · ' + favName(g.favorite) + (where ? ' · ' + where : '')), why ? h('small', why) : null),
      h('span', {class: 'chip ' + cls}, text));
  }
  async function renderFavorites() {
    if (!favs) return;
    const list = favs.favorites;
    await Promise.all([...new Set(list.map(t => t.split(':')[0]))].map(l => loadTeams(l).catch(() => [])));
    q('fav-air').checked = favs.air;
    const save = (next, message) => saveFavorites({favorites: next}, message);
    const move = (index, by) => { const next = [...list]; [next[index], next[index + by]] = [next[index + by], next[index]]; save(next, favName(list[index]) + ' is now number ' + (index + by + 1) + '.'); };
    VV.fill(q('followed'), list.length ? list.map((fid, index) => {
      const up = h('button', {type: 'button', class: 'xs quiet', 'aria-label': 'Move ' + favName(fid) + ' up', disabled: index === 0}, '▲'); up.onclick = () => move(index, -1);
      const down = h('button', {type: 'button', class: 'xs quiet', 'aria-label': 'Move ' + favName(fid) + ' down', disabled: index === list.length - 1}, '▼'); down.onclick = () => move(index, 1);
      const remove = h('button', {type: 'button', class: 'xs quiet', 'aria-label': 'Remove ' + favName(fid)}, '✕'); remove.onclick = () => save(list.filter(t => t !== fid), favName(fid) + ' is no longer a favorite.');
      return h('li', h('span', {class: 'n'}, String(index + 1)), h('span', favName(fid)), h('span', {class: 'acts'}, up, down, remove));
    }) : h('li', {class: 'hint'}, 'No favorites yet. Add them below.'));
    q('fav-games-title').textContent = 'Their games, next ' + (favs.days || 7) + ' days';
    const games = favs.games || [], errors = Object.entries(favs.errors || {});
    VV.fill(q('fav-games'), games.length ? games.map(favGame) : h('li', {class: 'hint'}, list.length ? (favs.checked_at ? 'No games for your favorites in the next ' + (favs.days || 7) + ' days.' : 'Looking for their games…') : 'Add favorites to see their games.'));
    q('fav-checked').textContent = [favs.checked_at ? 'Checked ' + fmt.when(favs.checked_at) + ', every ' + (favs.check_minutes || 10) + ' minutes.' : '',
      ...errors.map(([league, e]) => (LEAGUES[league] || league) + ': ' + e)].filter(Boolean).join(' ');
    if (view.tab !== 'teams') return;
    const league = q('league').value; let teamList;
    try { teamList = await loadTeams(league); } catch (e) { q('teams').replaceChildren(h('p', {class: 'hint'}, 'Could not load teams: ' + e.message)); return; }
    if (q('league').value !== league) return;  // Another league was chosen meanwhile: its render fills it.
    const filter = q('team-filter').value.trim().toLowerCase();
    const option = (fid, text, cls) => {
      const check = h('input', {type: 'checkbox', checked: list.includes(fid)});
      check.onchange = () => save(check.checked ? [...list, fid] : list.filter(t => t !== fid), check.checked ? favName(fid) + ' is favorite number ' + (list.length + 1) + '.' : favName(fid) + ' is no longer a favorite.');
      return h('label', {class: 'check' + (cls ? ' ' + cls : '')}, check, h('span', text));
    };
    const playoffs = league + ':playoffs', playoffName = PLAYOFFS[league] || 'All playoffs';
    VV.fill(q('teams'), [
      ...(!filter || playoffName.toLowerCase().includes(filter) || 'playoffs postseason'.includes(filter) ? [option(playoffs, playoffName, 'playoffs')] : []),
      ...teamList.filter(t => !filter || (t.name + ' ' + t.abbreviation).toLowerCase().includes(filter)).map(team => option(league + ':' + team.id, team.name))]);
  }
  q('fav-air').onchange = () => saveFavorites({air: q('fav-air').checked}, q('fav-air').checked ? 'Favorites go on air whenever they are on.' : 'Favorites stay off the air; their games scheduled for later are taken off the Schedule.');
  q('league').onchange = renderFavorites; q('team-filter').oninput = renderFavorites;

  /* Station messages ------------------------------------------------------------------------------------------------ */
  function renderMessages() {
    if (dirty.messages || editing('messages')) return;
    q('cycle').checked = data.settings.cycle_messages;
    messages = data.settings.messages.map(m => ({...m, days: [...m.days]}));
    drawMessages();
  }
  function drawMessages() {
    const list = q('messages'); list.replaceChildren();
    if (!messages.length) list.append(h('p', {class: 'hint'}, 'No station messages yet.'));
    messages.forEach((m, index) => {
      const field = (labelText, type, prop, attrs = {}) => {
        const input = h(type === 'textarea' ? 'textarea' : 'input', {...(type === 'textarea' ? {} : {type}), ...attrs}); input.value = m[prop] || '';
        input.oninput = () => { m[prop] = input.value; mark('messages'); };
        return h('label', {class: 'field'}, h('span', labelText), input);
      };
      const on = h('input', {type: 'checkbox', checked: m.enabled});
      const card = h('div', {class: 'msg' + (m.enabled ? '' : ' off')});
      on.onchange = () => { m.enabled = on.checked; card.className = 'msg' + (m.enabled ? '' : ' off'); mark('messages'); };
      const remove = h('button', {class: 'xs danger', type: 'button'}, 'Remove'); remove.onclick = () => { messages.splice(index, 1); mark('messages'); drawMessages(); };
      card.append(h('div', {class: 'row between'}, h('label', {class: 'switch'}, on, h('span', m.id ? h('code', {class: 'tiny muted'}, 'msg:' + m.id) : 'New message')), remove),
        field('Message', 'textarea', 'text', {maxLength: 300, rows: 2}),
        h('div', {class: 'fields'}, field('Tag', 'text', 'tag', {maxLength: 20, placeholder: 'e.g. TONIGHT'}), field('From', 'time', 'start'), field('Until', 'time', 'end'), field('First day', 'date', 'from'), field('Last day', 'date', 'until')),
        h('div', {class: 'days'}, DAYS.map((name, day) => { const box = h('input', {type: 'checkbox', checked: m.days.includes(day)}); box.onchange = () => { m.days = box.checked ? [...new Set([...m.days, day])].sort() : m.days.filter(d => d !== day); mark('messages'); }; return h('label', {class: 'check'}, box, h('span', name)); })));
      list.append(card);
    });
  }
  q('add-message').onclick = () => { messages.push({text: '', tag: '', enabled: true, days: [0, 1, 2, 3, 4, 5, 6], start: '', end: '', from: '', until: ''}); mark('messages'); drawMessages(); [...q('messages').querySelectorAll('textarea')].at(-1)?.focus(); };
  q('cycle').onchange = () => mark('messages');
  q('save-messages').onclick = () => {
    const list = messages.filter(m => m.text.trim()).map(m => ({...m, text: m.text.trim().replace(/\s+/g, ' ')}));
    clean('messages'); act(() => api('v1/crawl', {messages: list, cycle_messages: q('cycle').checked}), 'Messages saved.');
  };

  /* History ---------------------------------------------------------------------------------------------------------- */
  function renderHistory() {
    const rows = data.rotation?.history || [], box = q('history');
    if (!rows.length) { box.replaceChildren(h('p', {class: 'hint'}, 'Nothing has aired since the web service started. Per-item airings are in each item\'s details above.')); return; }
    box.replaceChildren(h('table', {class: 'data'}, h('thead', h('tr', ['Started', 'Segment', 'During', 'Ended', 'Items', 'Text'].map(t => h('th', t)))),
      h('tbody', rows.map(r => h('tr', h('td', {class: 'mono small nowrap'}, fmt.when(r.started)), h('td', (r.segment === 'round' ? slotName(r) : data.segments[r.segment]?.name || (r.loop ? 'Loop' : r.segment)) + (r.forced ? ' (by hand)' : '') + (r.new ? ' (new)' : '')),
        h('td', CONTEXT_NAMES[r.context] || r.context), h('td', {class: 'small'}, r.ended ? (r.how || 'ended') + ' ' + fmt.clock(r.ended) : h('span', {style: {color: 'var(--pgm)'}}, 'on air')),
        h('td', {class: 'mono small'}, String((r.ids || []).length || '—')), h('td', {class: 'small'}, r.text))))));
  }

  /* Tabs and the frame ----------------------------------------------------------------------------------------------- */
  function tab(name) {
    view.tab = name; VV.store.set('crawlTab', name);
    document.querySelectorAll('#tabs [data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== name; });
    if (name === 'teams') renderFavorites();
  }
  document.querySelectorAll('#tabs [data-tab]').forEach(b => { b.onclick = () => tab(b.dataset.tab); });
  tab(location.hash.slice(1) && document.querySelector(`[data-tab="${location.hash.slice(1)}"]`) ? location.hash.slice(1) : view.tab);
  function render() {
    if (!data) return;
    renderTop(); renderRegister(); renderTimeline(); renderComing(); renderManual(); renderRules(); renderSegments(); renderFeeds(); renderMessages(); renderHistory();
  }
  VV.watch('v1/crawl', 5000, (result, w) => { if (w.error) return; if (busy) return; data = result; render(); });
  VV.watch('v1/favorites', 15000, (result, w) => { if (w.error) return; favs = result; renderFavorites(); });
  VV.watch('v1/crawl/alerts', 5000, (result, w) => { if (w.error) { reg = {ready: false, error: w.error.message, items: [], plan: {}}; } else reg = result; if (data && !busy) { renderTop(); renderRegister(); renderTimeline(); renderComing(); } });
  window.addEventListener('beforeunload', e => { if (Object.values(dirty).some(Boolean)) e.preventDefault(); });
  VV.commands.add(
    {id: 'crawl:alerts', title: 'Show alerts only', group: 'Crawl', run: () => document.querySelector('[data-scope=alert]').click()},
    {id: 'crawl:all', title: 'Show everything the crawl lists', group: 'Crawl', run: () => document.querySelector('[data-scope=all]').click()},
    {id: 'crawl:override-clear', title: 'Clear the override', group: 'Crawl', when: () => !!data?.settings.override.text, run: () => q('override-clear').click()},
    {id: 'crawl:important-clear', title: 'Clear the important message', group: 'Crawl', when: () => !!data?.settings.important.text, run: () => q('important-clear').click()});
  document.addEventListener('vv:auth', () => load().catch(() => {}));
  load().then(() => {
    for (const seg of Object.keys(data.segments)) VV.commands.add({id: 'crawl:run:' + seg, title: 'Run ' + data.segments[seg].name + ' now', group: 'Crawl', run: () => act(() => api('v1/crawl/run', {segment: seg}), data.segments[seg].name + ' runs within a few seconds.')});
  }).catch(e => toast(e.message, {error: true}));
})();
