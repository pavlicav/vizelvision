// Ads › Mix: every knob of how My ads chooses what airs next (ad_mix.py): each kind's share and how fast
// it wears, how "seen a lot" holds ads back, the rest after a play, new uploads, the balance, and each
// ad's own boost and wear. The page works out each ad's chance itself as the faders move (chance(),
// as ad_mix.chance does), replays the days ahead with the draft (POST v1/my-ads/mix/preview), and
// changes nothing on air until Save. Its ids start mx-.
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const panel = $('panel-mix');
  const SVG = 'http://www.w3.org/2000/svg';
  const DAY = 86400;
  const SHOWN = 60;                      // ads listed before "Show all"

  let view = null;                       // GET v1/my-ads/mix
  let saved = null, draft = null;        // {tuning, kinds: {key: {weight, wear}}, overrides: {id: {boost, wear}}}
  let shape = '';                        // the kinds and ads the page was built for: a change builds it again
  let preview = null, previewFor = '', previewSeq = 0, previewTimer = null;
  let days = VV.store.get('mixDays', 3);
  let all = false;                       // every ad listed, not the first SHOWN
  const faders = [];                     // {node, get, set, saved}: lit once they differ from what is saved
  const rows = new Map();                // ad id -> its row's parts
  const pictures = new Map();

  /* The chance (ad_mix.chance, step for step) ------------------------------------------------------ */
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const seenOf = (plays, now, halfLife) => { let s = 0; const k = halfLife * DAY; for (const t of plays) s += 0.5 ** (Math.max(0, now - t) / k); return s; };
  const wornOf = (seen, t) => t.floor + (1 - t.floor) * (t.curve > 0 ? 1 / (1 + seen / t.familiar) ** t.curve : 1);
  const restOf = (hours, t) => hours == null || t.rest_hours <= 0 ? 1 : Math.min(1, Math.max(0, hours) / t.rest_hours) ** 2;
  const newOf = (added, now, t) => t.new_days > 0 && added && now - added < t.new_days * DAY ? t.new_boost : 1;
  const own = (id, d = draft) => d.overrides[id] || {boost: 1, wear: 1};
  const kindWear = (key, d = draft) => d.kinds[key]?.wear ?? 1;
  const seenCache = new Map();
  function seenLately(ad, now, halfLife) {
    const hit = seenCache.get(ad.id);
    if (hit && hit.hl === halfLife && Math.abs(hit.now - now) < 30) return hit.value;
    const value = seenOf(ad.plays, now, halfLife);
    seenCache.set(ad.id, {hl: halfLife, now, value});
    return value;
  }
  // An ad's chance, as a share of a new ad's, with its parts: worn (from seen × wear), rest, new, boost.
  function chance(ad, now = Date.now() / 1000, d = draft) {
    const t = d.tuning, mine = own(ad.id, d);
    const seen = seenLately(ad, now, t.half_life_days), wear = kindWear(ad.kind, d) * mine.wear;
    const last = ad.plays.length ? ad.plays[ad.plays.length - 1] : null;
    const hours = last == null ? null : (now - last) / 3600;
    const worn = wornOf(seen * wear, t), rest = restOf(hours, t), fresh = newOf(ad.added, now, t);
    return {seen, wear, effective: seen * wear, worn, rest, hours, fresh, boost: mine.boost,
      value: Math.max(worn * rest * fresh * mine.boost, 1e-6)};
  }

  /* Words for numbers --------------------------------------------------------------------------- */
  const pct = (v, small) => v >= .995 && v <= 1.005 ? '100%' : v > 0 && v < .01 ? (small ? '<1%' : '<1%') : Math.round(v * 100) + '%';
  const num = (v, places = 1) => (+v.toFixed(places)).toLocaleString();
  const daysText = v => v === 0 ? 'Off' : v === 1 ? '1 day' : v % 7 === 0 && v >= 14 ? v / 7 + ' weeks' : num(v) + ' days';
  const hoursText = v => v === 0 ? 'Off' : v < 48 ? num(v) + ' h' : num(v / 24) + ' days';
  const wearWords = v => v === 0 ? 'Never' : v < .45 ? 'Slowly' : v < .85 ? 'Slower' : v <= 1.15 ? 'Normally' : v <= 2 ? 'Faster' : 'Fast';
  const times = v => '×' + +v.toFixed(2);
  const holdWords = v => v === 0 ? 'Off' : v <= .75 ? 'Gently' : v <= 1.5 ? 'Moderately' : v <= 2.5 ? 'Firmly' : 'Hard';
  const againWords = v => v === 0 ? 'Often' : v <= .5 ? 'Sometimes' : v <= 1.5 ? 'Rarely' : 'Almost never';
  const until = hours => hours < 1 ? Math.max(1, Math.round(hours * 60)) + ' min' : hours < 48 ? Math.round(hours) + ' h' : Math.round(hours / 24) + ' days';
  const plural = (n, one, many = one + 's') => n.toLocaleString() + ' ' + (n === 1 ? one : many);

  /* Faders ---------------------------------------------------------------------------------------- */
  // A slider with its reading. Its travel maps onto the value linearly, or by 'log' (each step a like
  // ratio: 1 to 2 as far as 30 to 60), or 'log0' (the far left is 0, then log). The notch is the
  // default; a double-click goes back to it. text(v): its reading, or [reading, small print]; hint: a
  // line under it, or hint(v) to say what the setting does as it moves.
  let faderCount = 0;
  function fader({label, min, max, step, scale = 'lin', def, value, text, hint, compact, saved: was, onInput}) {
    const id = 'mx-f' + (++faderCount);
    const lo0 = scale === 'log0' ? Math.max(step, min || step) : min;
    const toPos = v => scale === 'lin' ? (v - min) / (max - min)
      : scale === 'log' ? Math.log(v / min) / Math.log(max / min)
      : v <= 0 ? 0 : .03 + .97 * Math.log(Math.max(v, lo0) / lo0) / Math.log(max / lo0);
    const fromPos = p => scale === 'lin' ? min + p * (max - min)
      : scale === 'log' ? min * (max / min) ** p
      : p < .015 ? 0 : lo0 * (max / lo0) ** clamp((p - .03) / .97, 0, 1);
    const snap = v => clamp(Math.round(v / step) * step, min, max);
    const input = h('input', {type: 'range', id, min: 0, max: 1000, step: 1, 'aria-label': label});
    const out = h('output', {for: id});
    const node = h('div', {class: 'fader' + (compact ? ' compact' : '')},
      h('div', {class: 'top'}, h('label', {for: id}, label), out),
      h('div', {class: 'rail'}, def != null ? h('i', {class: 'notch', title: 'Default'}) : null, input));
    const note = hint ? node.appendChild(h('p')) : null;
    if (def != null) node.style.setProperty('--d', clamp(toPos(def), 0, 1).toFixed(4));
    let current = value;
    function show(v) {
      current = v;
      const p = clamp(toPos(v), 0, 1);
      input.value = Math.round(p * 1000);
      node.style.setProperty('--p', p.toFixed(4));
      const said = text(v), [main, small] = Array.isArray(said) ? said : [said];
      VV.fill(out, main, small ? h('small', null, small) : null);
      node.classList.toggle('default', def != null && Math.abs(v - def) < 1e-9);
      if (note) note.textContent = typeof hint === 'function' ? hint(v) : hint;
      input.setAttribute('aria-valuetext', small ? main + ', ' + small : main);
    }
    input.addEventListener('input', () => { const v = +snap(fromPos(+input.value / 1000)).toFixed(4); show(v); onInput(v); });
    input.addEventListener('dblclick', () => { if (def != null && current !== def) { show(def); onInput(def); } });
    show(value);
    const f = {node, input, get: () => current, set: show, saved: was, off: on => { node.classList.toggle('off', on); input.disabled = on; }};
    faders.push(f);
    return f;
  }
  // Lights each fader that differs from what is saved (its `saved` says what that is).
  function markFaders() {
    for (const f of faders) if (f.saved && f.node.isConnected) f.node.classList.toggle('changed', Math.abs(f.get() - f.saved()) > 1e-9);
  }

  /* The draft ------------------------------------------------------------------------------------- */
  const fromMix = mix => ({tuning: {...mix.tuning}, overrides: structuredClone(mix.overrides),
    kinds: Object.fromEntries(mix.categories.map(c => [c.key, {weight: c.weight, wear: c.wear}]))});
  const defaults = () => ({tuning: Object.fromEntries(Object.entries(view.ranges.tuning).map(([k, [d]]) => [k, d])), overrides: {},
    kinds: Object.fromEntries(view.mix.categories.map(c => [c.key, {weight: 1, wear: 1}]))});
  const kindName = key => key === 'unsorted' ? 'Unsorted' : view.mix.categories.find(c => c.key === key)?.name || key;
  const adById = id => view.ads.find(a => a.id === id);
  const LABELS = {half_life_days: 'Fades by half in', familiar: 'Feels familiar after', curve: 'Hold back worn ads', floor: 'Never below',
    rest_hours: 'Rest after airing', new_days: 'New for', new_boost: 'New ads\' boost', window: 'Balance over', again: 'Same kind twice running',
    tired: 'A kind steps aside under', unsorted: 'Unsorted share'};
  // What differs from what is saved, in words.
  function changes() {
    const out = [];
    for (const [k, v] of Object.entries(draft.tuning)) if (Math.abs(v - saved.tuning[k]) > 1e-9) out.push(LABELS[k] || k);
    for (const [k, v] of Object.entries(draft.kinds)) {
      if (Math.abs(v.weight - saved.kinds[k].weight) > 1e-9) out.push(kindName(k) + ' share');
      if (Math.abs(v.wear - saved.kinds[k].wear) > 1e-9) out.push(kindName(k) + ' wear');
    }
    const ids = new Set([...Object.keys(draft.overrides), ...Object.keys(saved.overrides)]);
    for (const id of ids) {
      const a = own(id, draft), b = own(id, saved);
      if (a.boost !== b.boost || a.wear !== b.wear) out.push(adById(id)?.name || 'an ad');
    }
    return out;
  }
  const dirty = () => !!draft && !!saved && changes().length > 0;
  // What the server takes: the draft, with null for an ad's own settings it no longer has.
  function payload() {
    const overrides = {...draft.overrides};
    for (const id of Object.keys(saved.overrides)) if (!(id in overrides)) overrides[id] = null;
    return {tuning: draft.tuning, kinds: draft.kinds, overrides};
  }
  function setOwn(id, change) {
    const next = {...own(id), ...change};
    if (next.boost === 1 && next.wear === 1) delete draft.overrides[id]; else draft.overrides[id] = next;
    changed();
  }

  /* Drawing -------------------------------------------------------------------------------------- */
  const el = (tag, attrs = {}, ...kids) => {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
    for (const kid of kids) if (kid != null) node.append(kid);
    return node;
  };
  // Charts are drawn at the width they show at, so their lettering is always the page's size.
  const width = (box, fallback) => Math.round(box.clientWidth) || fallback;
  const niceMax = v => { for (const m of [10, 20, 30, 40, 60, 80, 100, 150, 200, 300, 400, 600]) if (v <= m) return m; return Math.ceil(v / 100) * 100; };
  const state = v => v >= .5 ? 'fresh' : v < .1 ? 'worn' : 'mid';

  // Seen a lot: chance (worn part) against plays seen lately; every ad a dot; the saved curve dashed when it differs.
  function wornChart(stats) {
    const t = draft.tuning, W = width($('mx-worn-chart'), 460), H = Math.round(clamp(W * .5, 190, 260)), L = 40, R = 12, T = 26, B = 34;
    const xMax = niceMax(Math.max(20, ...stats.map(s => s.c.effective)) * 1.04);
    const x = v => L + (W - L - R) * Math.min(v, xMax) / xMax, y = v => T + (H - T - B) * (1 - Math.min(v, 1));
    const curve = tuning => { let d = ''; for (let i = 0; i <= 160; i++) { const s = xMax * i / 160; d += (i ? 'L' : 'M') + x(s).toFixed(1) + ' ' + y(wornOf(s, tuning)).toFixed(1); } return d; };
    const svg = el('svg', {class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Chance against how much an ad has been seen lately'});
    for (const v of [0, .25, .5, .75, 1]) svg.append(el('line', {class: 'grid', x1: L, x2: W - R, y1: y(v), y2: y(v)}), el('text', {x: L - 8, y: y(v) + 3.5, 'text-anchor': 'end'}, pct(v)));
    const step = xMax / 5;
    for (let v = 0; v <= xMax + 1e-9; v += step) svg.append(el('text', {x: x(v), y: H - B + 16, 'text-anchor': 'middle'}, num(v)));
    svg.append(el('line', {class: 'axis', x1: L, x2: W - R, y1: y(0), y2: y(0)}),
      el('text', {class: 'title', x: W - R, y: H - 4, 'text-anchor': 'end'}, 'plays seen lately, fading →'),
      el('text', {class: 'title', x: L - 34, y: 12}, 'chance, against a new ad'));
    const path = curve(t);
    svg.append(el('path', {class: 'area', d: path + `L${x(xMax)} ${y(0)}L${x(0)} ${y(0)}Z`}));
    const was = saved.tuning;
    if (['familiar', 'curve', 'floor'].some(k => Math.abs(was[k] - t[k]) > 1e-9)) svg.append(el('path', {class: 'was', d: curve(was)}, el('title', {}, 'As saved')));
    svg.append(el('path', {class: 'curve', d: path}));
    // Dots: a little scatter across the line, so a crowd at one spot still reads as many.
    for (const s of stats) {
      const jitter = ((parseInt(s.ad.id.slice(-4), 16) % 13) - 6) * .9;
      const kept = s.c.wear === 0;
      svg.append(el('circle', {class: 'bead ' + (kept ? 'kept' : state(s.c.worn)), cx: x(s.c.effective).toFixed(1), cy: (y(s.c.worn) + jitter).toFixed(1), r: kept ? 4.2 : 3.4},
        el('title', {}, `${s.ad.name}: seen ${num(s.c.seen)} lately${s.c.wear !== 1 ? ` (×${num(s.c.wear)} wear)` : ''}, ${pct(s.c.worn)} of a new ad's chance`)));
    }
    const unseen = stats.filter(s => s.c.effective < .5).length;
    if (unseen) svg.append(el('text', {class: 'tag', x: x(0) + 10, y: y(1) + 14}, `${unseen} barely seen`));
    return svg;
  }
  // After it airs: chance (rest part) against hours since; the ads resting now as dots.
  function restChart(stats, now) {
    const t = draft.tuning, W = width($('mx-rest-chart'), 400), H = 146, L = 40, R = 12, T = 12, B = 32;
    const span = Math.max(12, t.rest_hours * 1.5 || 12), x = v => L + (W - L - R) * Math.min(v, span) / span, y = v => T + (H - T - B) * (1 - v);
    const svg = el('svg', {class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Chance against hours since an ad aired'});
    for (const v of [0, .5, 1]) svg.append(el('line', {class: 'grid', x1: L, x2: W - R, y1: y(v), y2: y(v)}), el('text', {x: L - 8, y: y(v) + 3.5, 'text-anchor': 'end'}, pct(v)));
    const ticks = span <= 24 ? 6 : span <= 72 ? 12 : 24;
    for (let v = 0; v <= span + 1e-9; v += ticks) svg.append(el('text', {x: x(v), y: H - B + 16, 'text-anchor': 'middle'}, v < 48 ? v + ' h' : num(v / 24) + ' d'));
    svg.append(el('line', {class: 'axis', x1: L, x2: W - R, y1: y(0), y2: y(0)}),
      el('text', {class: 'title', x: W - R, y: H - 3, 'text-anchor': 'end'}, 'since it aired →'));
    let d = '';
    for (let i = 0; i <= 120; i++) { const hrs = span * i / 120; d += (i ? 'L' : 'M') + x(hrs).toFixed(1) + ' ' + y(restOf(hrs, t)).toFixed(1); }
    svg.append(el('path', {class: 'area', d: d + `L${x(span)} ${y(0)}L${x(0)} ${y(0)}Z`}), el('path', {class: 'curve', d}));
    for (const s of stats) {
      if (s.c.hours == null || s.c.hours > span) continue;
      svg.append(el('circle', {class: 'bead ' + state(s.c.rest), cx: x(s.c.hours).toFixed(1), cy: y(s.c.rest).toFixed(1), r: 3.4},
        el('title', {}, `${s.ad.name}: aired ${fmt.mins(s.c.hours * 3600)} ago, ${pct(s.c.rest)} back`)));
    }
    return svg;
  }

  /* Building the page ----------------------------------------------------------------------------- */
  function build() {
    faders.length = 0;
    rows.clear();
    buildKinds(); buildKnobs(); buildAds();
    for (const b of document.querySelectorAll('#mx-days [data-days]')) b.setAttribute('aria-pressed', String(+b.dataset.days === days));
  }

  const shares = () => {
    const present = new Set(view.ads.map(a => a.kind));
    const w = Object.fromEntries([...Object.entries(draft.kinds).map(([k, v]) => [k, v.weight]), ['unsorted', draft.tuning.unsorted]].filter(([k]) => present.has(k)));
    const total = Object.values(w).reduce((a, b) => a + b, 0);
    return Object.fromEntries(Object.entries(w).map(([k, v]) => [k, total ? v / total : 0]));
  };
  // Each kind's share if every ad came round alike (about what the plain shuffle gives it).
  const byCount = () => {
    const sizes = {};
    for (const a of view.ads) if (a.enabled) sizes[a.kind] = (sizes[a.kind] || 0) + 1;
    const total = Object.values(sizes).reduce((a, b) => a + b, 0);
    return Object.fromEntries(Object.entries(sizes).map(([k, n]) => [k, total ? n / total : 0]));
  };
  function buildKinds() {
    const sizes = {};
    for (const a of view.ads) sizes[a.kind] = (sizes[a.kind] || 0) + 1;
    const day = Object.fromEntries([...view.summary.categories.map(c => [c.key, c.day]), ['unsorted', view.summary.unsorted.day]]);
    const aired = view.summary.aired_day;
    const list = [...view.mix.categories.map(c => ({key: c.key, name: c.name, about: c.about})),
      ...(sizes.unsorted ? [{key: 'unsorted', name: 'Unsorted', about: 'Ads with no kind yet: choose one for each on the My ads tab.'}] : [])];
    const items = list.map(c => {
      const unsorted = c.key === 'unsorted';
      const share = fader({label: 'Share of plays', min: 0, max: 5, step: .05, def: 1, compact: true,
        value: unsorted ? draft.tuning.unsorted : draft.kinds[c.key].weight,
        saved: () => unsorted ? saved.tuning.unsorted : saved.kinds[c.key].weight,
        text: v => v === 0 ? ['Off', `by count ${pct(byCount()[c.key] || 0)}`]
          : [pct(shares()[c.key] ?? 0), [v === 1 ? null : times(v), `by count ${pct(byCount()[c.key] || 0)}`].filter(Boolean).join(' · ')],
        onInput: v => { if (unsorted) draft.tuning.unsorted = v; else draft.kinds[c.key].weight = v; changed(); }});
      const wear = unsorted ? null : fader({label: 'Wears out', min: 0, max: 3, step: .05, def: 1, compact: true, value: draft.kinds[c.key].wear,
        saved: () => saved.kinds[c.key].wear, text: v => [wearWords(v), v === 0 || v === 1 ? '' : times(v)],
        onInput: v => { draft.kinds[c.key].wear = v; changed(); }});
      const due = h('b', {class: 'due'}), bar = h('i'), said = h('span');
      const counted = h('i', {class: 'notch count', title: `Here, with the other kinds as they are, ${c.name} gets its share by ad count`});
      share.node.querySelector('.rail').prepend(counted);
      const got = aired ? (day[c.key] || 0) / aired : 0;
      const li = h('li', {class: sizes[c.key] ? '' : 'none', data: {kind: c.key}},
        h('div', {class: 'who'}, h('b', null, c.name), ' ', h('small', null, plural(sizes[c.key] || 0, 'ad')), c.about ? h('p', {title: c.about}, c.about) : null),
        share.node, wear ? wear.node : h('span', {class: 'tiny muted'}, 'Wears as tuned'),
        h('div', {class: 'day', title: 'The last day\'s plays, the mark where its share is now'}, h('div', {class: 'meter pvw'}, bar, due), said));
      return {key: c.key, share, due, bar, said, got, li, counted};
    });
    VV.fill($('mx-kinds'), h('li', {class: 'cols', 'aria-hidden': 'true'}, h('span', null, 'Kind'), h('span', null, 'Share of plays', h('small', null, h('i'), 'by ad count')), h('span', null, 'Wears out'), h('span', null, 'Last day')),
      ...items.map(i => i.li));
    buildKinds.items = items;
  }
  function refreshKinds() {
    const s = shares(), n = byCount();
    const weight = key => key === 'unsorted' ? draft.tuning.unsorted : draft.kinds[key].weight;
    const top = Math.max(.05, ...buildKinds.items.map(i => Math.max(i.got, s[i.key] || 0))) * 1.08;
    for (const i of buildKinds.items) {
      i.share.set(i.share.get());
      const due = s[i.key] || 0;
      i.bar.style.width = (100 * i.got / top).toFixed(1) + '%';
      i.due.style.left = (100 * due / top).toFixed(1) + '%';
      i.due.hidden = !due;
      i.said.textContent = `${pct(i.got)} · due ${pct(due)}`;
      // The weight that gives it its share by count, the others as they are: p = w / (w + others).
      const p = n[i.key] || 0, others = buildKinds.items.reduce((t, j) => t + (j.key === i.key || !(j.key in n) ? 0 : weight(j.key)), 0);
      const at = p >= 1 ? 5 : p * others / (1 - p);
      i.counted.hidden = !p || at > 5;
      i.counted.style.left = `calc(7px + (100% - 14px) * ${(Math.min(at, 5) / 5).toFixed(4)})`;
    }
    $('mx-kinds-sum').textContent = `${plural(Object.keys(s).length, 'kind')} · ${plural(view.ads.length, 'ad')} · ${plural(view.summary.aired_day, 'play')} in the last day`;
  }

  function knob(key, opts) {
    const [def, lo, hi] = view.ranges.tuning[key];
    return fader({label: LABELS[key], min: lo, max: hi, def, value: draft.tuning[key], saved: () => saved.tuning[key],
      onInput: v => { draft.tuning[key] = v; changed(); }, ...opts});
  }
  function buildKnobs() {
    const per = view.pace.per_break;
    const t = () => draft.tuning;
    const familiar = knob('familiar', {step: .5, scale: 'log', text: v => plural(v, 'play'),
      hint: v => `An ad seen ${plural(v, 'play')} lately has ${pct(wornOf(v, t()))} of a new one's chance.`});
    const curve = knob('curve', {step: .05, text: v => [holdWords(v), v ? num(v, 2) : 'nothing wears out'],
      hint: v => v === 0 ? 'Seeing an ad a lot never lowers its chance.'
        : `How steeply it falls from there: seen twice as much, ${pct(wornOf(2 * t().familiar, t()))}; four times, ${pct(wornOf(4 * t().familiar, t()))}.`});
    const floor = knob('floor', {step: .01, text: v => v === 0 ? 'None' : pct(v), hint: 'However worn, an ad keeps at least this much of a new ad\'s chance.'});
    const fade = knob('half_life_days', {step: 1, scale: 'log', text: daysText,
      hint: v => `A play from ${daysText(v)} ago counts half as much as one today; from ${daysText(2 * v)} ago, a quarter.`});
    VV.fill($('mx-worn-knobs'), familiar.node, curve.node, floor.node, fade.node);
    Object.assign(knobs, {familiar, curve});
    const rest = knob('rest_hours', {step: 1, scale: 'log0', text: hoursText, hint: 'Full chance again this long after a play; a quarter of it halfway there.'});
    VV.fill($('mx-rest-knobs'), rest.node);
    const newDays = knob('new_days', {step: 1, text: daysText, hint: 'Counted from the upload.'});
    const newBoost = knob('new_boost', {step: .1, text: times, hint: 'Their chance, times this.'});
    knobs.newBoost = newBoost;
    VV.fill($('mx-new-knobs'), newDays.node, newBoost.node);
    const window = knob('window', {step: 1, scale: 'log', text: v => [plural(v, 'ad'), `about ${plural(Math.max(1, Math.round(v / per)), 'break')}`],
      hint: 'How far back each kind\'s plays are counted against its share. Shorter evens things out within a break or two; longer, over the evening.'});
    const again = knob('again', {step: .05, text: v => [againWords(v), v ? num(v, 2) : ''],
      hint: 'How far behind its share the kind that just aired must be to go again straight away.'});
    const tired = knob('tired', {step: .01, text: v => v === 0 ? ['Never', 'kinds always take their turn'] : pct(v),
      hint: 'A kind whose best ad has under this much of the best chance of all sits a turn out, so a small or worn kind never repeats its few ads.'});
    VV.fill($('mx-balance-knobs'), window.node, again.node, tired.node);
  }
  const knobs = {};

  function buildAds() {
    const kinds = [...view.mix.categories.map(c => [c.key, c.name]), ...(view.ads.some(a => a.kind === 'unsorted') ? [['unsorted', 'Unsorted']] : [])];
    const select = $('mx-kind'), value = select.value;
    VV.fill(select, h('option', {value: ''}, 'Every kind'), ...kinds.map(([k, name]) => h('option', {value: k}, name)));
    select.value = kinds.some(([k]) => k === value) ? value : '';
    listAds();
  }
  // The rows shown: found, of the kind chosen, in the order chosen. Built again only when those change.
  function listAds() {
    const q = $('mx-q').value.trim().toLowerCase(), kind = $('mx-kind').value, mine = $('mx-own').checked, sort = $('mx-sort').value;
    const now = Date.now() / 1000;
    let list = view.ads.filter(a => (!q || a.name.toLowerCase().includes(q)) && (!kind || a.kind === kind) && (!mine || draft.overrides[a.id]));
    const c = new Map(list.map(a => [a.id, chance(a, now)]));
    const by = {seen: (a, b) => c.get(b.id).seen - c.get(a.id).seen, low: (a, b) => c.get(a.id).value - c.get(b.id).value,
      high: (a, b) => c.get(b.id).value - c.get(a.id).value, plays: (a, b) => b.plays.length - a.plays.length,
      new: (a, b) => (b.added || 0) - (a.added || 0), name: (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'})}[sort];
    list.sort((a, b) => by(a, b) || a.name.localeCompare(b.name));
    const total = list.length;
    if (!all) list = list.slice(0, SHOWN);
    const shown = new Set(list.map(a => a.id));
    for (const [id, row] of rows) {
      if (shown.has(id)) continue;
      for (const f of row.faders) { const i = faders.indexOf(f); if (i >= 0) faders.splice(i, 1); }
      rows.delete(id);
    }
    VV.fill($('mx-ads'), ...list.map(a => (rows.get(a.id) || adRow(a)).li));
    $('mx-more').hidden = all || total <= SHOWN;
    $('mx-more-btn').textContent = `Show all ${total}`;
    $('mx-ads-empty').hidden = total > 0;
    $('mx-ads-count').textContent = total === view.ads.length ? plural(total, 'ad') : `${total} of ${view.ads.length}`;
    refreshAds();
  }
  function adRow(ad) {
    const shot = h('div', {class: 'shot' + (ad.pics ? '' : ' none')}, h('img', {alt: ''}));
    if (ad.pics) picture(shot.firstChild, `${ad.id}-${Math.min(1, ad.pics - 1)}.jpg`);
    const meta = h('small');
    const bar = h('i'), meter = h('div', {class: 'meter'}, bar), said = h('span'), why = h('small', {class: 'why'});
    const boost = fader({label: 'Boost', min: 0, max: 5, step: .1, def: 1, compact: true, value: own(ad.id).boost,
      saved: () => own(ad.id, saved).boost, text: v => v === 0 ? ['Left out', 'of the mix'] : times(v),
      onInput: v => setOwn(ad.id, {boost: v})});
    const wear = fader({label: 'Wears out', min: 0, max: 3, step: .05, def: 1, compact: true, value: own(ad.id).wear,
      saved: () => own(ad.id, saved).wear, text: v => [wearWords(v), v === 0 || v === 1 ? '' : times(v)],
      onInput: v => setOwn(ad.id, {wear: v})});
    const keep = h('button', {type: 'button', class: 'xs', 'aria-pressed': 'false', title: 'Never wears out: however often you see it, it keeps a new ad\'s chance (it still rests after airing)',
      onclick: () => { setOwn(ad.id, {wear: own(ad.id).wear === 0 ? 1 : 0}); }}, 'Keep fresh');
    const reset = h('button', {type: 'button', class: 'xs quiet', title: 'Back to its kind\'s settings', onclick: () => setOwn(ad.id, {boost: 1, wear: 1})}, 'Reset');
    const li = h('li', {data: {id: ad.id}, class: ad.enabled ? '' : 'off'},
      shot, h('div', {class: 'who'}, h('b', null, ad.name || 'Untitled'), h('span', {class: 'kind'}, kindName(ad.kind)), meta),
      h('div', {class: 'chance'}, said, meter, why), boost.node, wear.node, h('div', {class: 'acts'}, keep, reset));
    const row = {li, meta, bar, meter, said, why, boost, wear, keep, reset, faders: [boost, wear]};
    rows.set(ad.id, row);
    return row;
  }
  function refreshAds() {
    const now = Date.now() / 1000, counts = preview?.mix?.ads || {};
    for (const [id, r] of rows) {
      const ad = adById(id);
      if (!ad) continue;
      const c = chance(ad, now), mine = own(id);
      r.bar.style.width = (100 * Math.min(1, c.value)).toFixed(1) + '%';
      r.meter.className = 'meter ' + (c.value >= .5 ? 'fresh' : c.value < .1 ? 'worn' : '');
      const parts = [`seen ${num(c.seen)} lately${c.wear !== 1 ? ` ×${num(c.wear)}` : ''}: ${pct(c.worn)}`];
      if (c.rest < 1) parts.push(`aired ${fmt.mins(c.hours * 3600)} ago: ${pct(c.rest)} back`);
      if (c.fresh !== 1) parts.push(`new: ${times(c.fresh)}`);
      if (c.boost !== 1) parts.push(`its chance ${times(c.boost)}`);
      VV.fill(r.said, pct(c.value), h('small', null, 'of a new ad\'s'));
      // Why, in a few words: what holds it back or lifts it.
      const t = draft.tuning, why = [];
      if (c.boost === 0) why.push('left out of the mix');
      else {
        if (c.wear === 0) why.push('kept fresh');
        else if (c.worn < .1) why.push('seen a lot');
        if (c.rest < 1) why.push('resting, full in ' + until(t.rest_hours - c.hours));
        if (c.fresh > 1) why.push('new');
        if (c.boost > 1) why.push('boosted');
      }
      r.why.textContent = why.join(' · ');
      r.said.parentElement.title = parts.join(' · ');
      const last = ad.plays.length ? ad.plays[ad.plays.length - 1] : null;
      const ahead = preview ? ` · next ${plural(preview.days, 'day')}: ${counts[id] || 0}` : '';
      r.meta.textContent = `${ad.plays.length ? `${plural(ad.plays.length, 'play')} · last ${fmt.when(last)}` : 'never aired'}${ahead}${ad.enabled ? '' : ' · switched off'}`;
      if (Math.abs(r.boost.get() - mine.boost) > 1e-9) r.boost.set(mine.boost);
      if (Math.abs(r.wear.get() - mine.wear) > 1e-9) r.wear.set(mine.wear);
      r.keep.setAttribute('aria-pressed', String(mine.wear === 0));
      r.reset.hidden = mine.boost === 1 && mine.wear === 1;
      r.li.classList.toggle('own', !!draft.overrides[id]);
      r.li.dataset.chance = c.value;
    }
  }
  function picture(img, name) {
    const path = 'v1/my-ads/file/' + name;
    const load = () => {
      if (!pictures.has(path)) pictures.set(path, api(path, undefined, {raw: true, timeout: 60000})
        .then(r => r.ok ? r.blob() : null).then(b => b && URL.createObjectURL(b)).catch(() => null));
      pictures.get(path).then(url => { if (url) img.src = url; else img.parentElement.classList.add('none'); });
    };
    if (!('IntersectionObserver' in window)) return load();
    const watch = new IntersectionObserver(seen => { if (seen.some(e => e.isIntersecting)) { watch.disconnect(); load(); } }, {rootMargin: '300px'});
    watch.observe(img.parentElement);
  }

  /* Refreshing ---------------------------------------------------------------------------------- */
  let frame = 0;
  function changed() {
    if (!draft) return;
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; refresh(); });
    schedulePreview();
  }
  function refresh() {
    if (!view || !draft) return;
    const now = Date.now() / 1000;
    const stats = view.ads.filter(a => a.enabled).map(ad => ({ad, c: chance(ad, now)}));
    refreshKinds();
    // Seen a lot: its knobs say what they do, the chart, its legend and the most held back.
    for (const k of [knobs.familiar, knobs.curve]) k.set(k.get());
    VV.fill($('mx-worn-chart'), wornChart(stats));
    const count = st => stats.filter(s => s.c.wear !== 0 && state(s.c.worn) === st).length, kept = stats.filter(s => s.c.wear === 0).length;
    const fresh = count('fresh'), mid = count('mid'), worn = count('worn');
    VV.fill($('mx-worn-legend'), h('span', null, h('i', {class: 'fresh'}), h('b', null, fresh), ' fresh (over half a new ad\'s chance)'),
      h('span', null, h('i', {class: 'mid'}), h('b', null, mid), ' in between'),
      h('span', null, h('i', {class: 'worn'}), h('b', null, worn), ' held back (under a tenth)'),
      kept ? h('span', null, h('i', {class: 'kept'}), h('b', null, kept), ' kept fresh') : null);
    $('mx-worn-chip').textContent = draft.tuning.curve === 0 ? 'off' : `${worn} held back`;
    $('mx-worn-chip').className = 'chip' + (draft.tuning.curve === 0 ? '' : worn ? ' warn' : ' pvw');
    const held = stats.filter(s => s.c.wear !== 0).sort((a, b) => a.c.worn - b.c.worn).slice(0, 8);
    VV.fill($('mx-held'), ...held.map(s => h('li', null, h('span', null, s.ad.name), h('span', {class: 'n'}, `seen ${num(s.c.seen)} · ${pct(s.c.worn)}`),
      h('button', {type: 'button', class: 'xs', title: 'Never wears out: it keeps a new ad\'s chance', onclick: () => setOwn(s.ad.id, {wear: 0})}, 'Keep fresh'))));
    $('mx-held-box').hidden = !held.length || draft.tuning.curve === 0;
    // After it airs.
    VV.fill($('mx-rest-chart'), restChart(stats, now));
    const t = draft.tuning, resting = stats.filter(s => s.c.rest < 1).length;
    $('mx-rest-chip').textContent = t.rest_hours === 0 ? 'off' : `${resting} resting`;
    $('mx-rest-chip').className = 'chip';
    VV.fill($('mx-rest-say'), t.rest_hours === 0 ? 'Off: an ad may come round again as soon as its limit lets it.'
      : ['An ad that aired ', h('b', null, hoursText(Math.max(1, Math.round(t.rest_hours / 4)))), ' ago has ', h('b', null, pct(restOf(Math.max(1, Math.round(t.rest_hours / 4)), t))),
        ' of its chance; one from ', h('b', null, hoursText(Math.round(t.rest_hours / 2))), ' ago, ', h('b', null, pct(restOf(Math.round(t.rest_hours / 2), t))), '.']);
    // New uploads.
    const recent = t.new_days ? view.ads.filter(a => a.added && now - a.added < t.new_days * DAY).length : 0;
    knobs.newBoost.off(t.new_days === 0);
    VV.fill($('mx-new-say'), t.new_days === 0 ? 'Off: new uploads take their turn like any other ad (and they are fresh, never seen).'
      : [h('b', null, plural(recent, 'ad')), ` uploaded in the last ${daysText(t.new_days)} ${recent === 1 ? 'gets' : 'get'} `, h('b', null, times(t.new_boost)), ' their chance.']);
    refreshAds();
    markFaders();
    // Unsaved changes.
    const list = changes();
    $('mx-savebar').hidden = !list.length;
    panel.classList.toggle('dirty', list.length > 0);
    $('mx-dirty').textContent = list.length ? `${plural(list.length, 'change')} not saved yet` : '';
    $('mx-dirty-list').textContent = list.slice(0, 6).join(' · ') + (list.length > 6 ? ` · and ${list.length - 6} more` : '');
    status();
  }
  function status() {
    const on = !!view.mix.enabled && view.order === 'shuffle';
    for (const b of document.querySelectorAll('#mx-on [data-on]')) b.setAttribute('aria-pressed', String(String(on) === b.dataset.on));
    const note = $('mx-note');
    note.hidden = on;
    note.textContent = view.order === 'list' ? 'My ads plays in list order now, so the mix waits. Choose Mix (here or on the My ads tab) to use it.'
      : 'The mix is off: My ads plays the plain shuffle. You can still tune it and preview it; choose Mix to put it on air.';
  }

  /* The preview ------------------------------------------------------------------------------------- */
  function schedulePreview(now) {
    clearTimeout(previewTimer);
    const key = JSON.stringify([payload(), days]);
    if (key === previewFor && preview) return;
    $('mx-pv').classList.add('busy');
    $('mx-pv-lamp').className = 'lamp warn';
    previewTimer = setTimeout(() => runPreview(key), now ? 0 : 450);
  }
  async function runPreview(key) {
    const seq = ++previewSeq;
    try {
      const result = await api('v1/my-ads/mix/preview', {...payload(), days}, {timeout: 60000});
      if (seq !== previewSeq) return;
      preview = result; previewFor = key;
      $('mx-error').hidden = true;
      renderPreview();
      refreshAds();
    } catch (e) {
      if (seq !== previewSeq) return;
      $('mx-pv').classList.remove('busy');
      $('mx-pv-lamp').className = 'lamp pgm';
      $('mx-error').hidden = false;
      $('mx-error').textContent = 'The preview could not be worked out: ' + e.message;
    }
  }
  function renderPreview() {
    const p = preview, m = p.mix, s = p.shuffle, d = p.days;
    $('mx-pv').classList.remove('busy');
    $('mx-pv-lamp').className = 'lamp pvw';
    const due = shares();
    const kinds = [...view.mix.categories.map(c => c.key), 'unsorted'].filter(k => k in due || k in m.kinds);
    const top = Math.max(.05, ...kinds.map(k => Math.max(m.kinds[k] || 0, s.kinds[k] || 0, due[k] || 0))) * 1.08;
    const w = v => (100 * v / top).toFixed(1) + '%';
    const better = (a, b, lower) => a === b ? '' : (lower ? a < b : a > b) ? 'better' : 'worse';
    const stat = (label, value, cls, note) => h('div', {class: 'stat'}, h('span', {class: 'label'}, label), h('b', {class: cls}, value), h('span', null, note));
    const names = Object.fromEntries(view.ads.map(a => [a.id, a]));
    const worn = p.worn.slice(0, 6).filter(id => names[id]);
    const most = Object.entries(m.ads).sort((a, b) => b[1] - a[1]).slice(0, 5).filter(([id]) => names[id]);
    VV.fill($('mx-pv'),
      h('p', {class: 'hint'}, `A replay of the next ${plural(d, 'day')} at your breaks' usual pace (about ${Math.round(p.breaks_a_day)} breaks a day, ${p.per_break} ads each): ${dirty() ? 'with your changes' : 'as saved'}, beside the plain shuffle.`),
      h('div', null, h('h3', null, 'Each kind\'s plays'),
        h('div', {class: 'pv-legend'}, h('span', null, h('i', {class: 'k-mix'}), 'the mix'), h('span', null, h('i', {class: 'k-due'}), 'its share'), h('span', null, h('i', {class: 'k-shuffle'}), 'the shuffle')),
        h('ul', {class: 'pv-kinds', style: {marginTop: '10px'}}, kinds.map(k => {
          const got = m.kinds[k] || 0, was = s.kinds[k] || 0, share = due[k] || 0;
          return h('li', null, h('span', null, kindName(k)), h('span', {class: 'pct'}, pct(got), h('small', null, pct(was))),
            h('div', {class: 'bars'}, h('div', {class: 'meter'}, h('i', {style: {width: w(got)}}), share ? h('b', {class: 'due', style: {left: w(share)}}) : null),
              h('div', {class: 'shuffle'}, h('i', {style: {width: w(was)}}))));
        }))),
      h('div', {class: 'stats'},
        stat('30 most seen', pct(m.worn_share), better(m.worn_share, s.worn_share, true), `of plays · shuffle ${pct(s.worn_share)}`),
        stat('Different ads', m.distinct, '', `shuffle ${s.distinct} of ${view.ads.length}`),
        stat('Wait to repeat', m.gap_hours == null ? '—' : Math.round(m.gap_hours) + ' h', '', `shuffle ${s.gap_hours == null ? '—' : Math.round(s.gap_hours) + ' h'}`),
        stat('Most of one ad', m.most_in_a_day + '×', better(m.most_in_a_day, s.most_in_a_day, true), `a day · shuffle ${s.most_in_a_day}×`)),
      worn.length ? h('div', null, h('h3', null, 'Your most seen ads'),
        h('table', {class: 'mini'}, h('thead', null, h('tr', null, h('th', null, 'Ad'), h('th', null, 'In all'), h('th', null, 'Mix'), h('th', null, 'Shuffle'))),
          h('tbody', null, worn.map(id => h('tr', null, h('td', null, names[id].name), h('td', {class: 'dim'}, names[id].plays.length), h('td', null, m.ads[id] || 0), h('td', {class: 'dim'}, s.ads[id] || 0)))))) : null,
      most.length ? h('div', null, h('h3', null, `Airs most, the next ${plural(d, 'day')}`),
        h('table', {class: 'mini'}, h('tbody', null, most.map(([id, n]) => h('tr', null, h('td', null, names[id].name, h('span', {class: 'tiny muted'}, ' · ' + kindName(names[id].kind))), h('td', null, n + '×')))))) : null);
  }

  /* Saving ------------------------------------------------------------------------------------------- */
  async function save() {
    if (!dirty()) return;
    const button = $('mx-save');
    button.disabled = true;
    try {
      take(await api('v1/my-ads/mix?view=mix', payload()), true);
      toast('Saved. Next up draws again with the new mix.', {ok: true});
    } catch (e) { toast(e.message, {error: true}); }
    finally { button.disabled = false; }
  }
  function discard() {
    draft = structuredClone(saved);
    resetFaders();
  }
  function resetFaders() {
    build(); refresh(); schedulePreview(true);
  }
  // A view from the server: what is saved; the draft follows it unless it has changes of its own.
  function take(data, fresh) {
    const keep = draft && !fresh && dirty();
    const before = saved && JSON.stringify(saved);
    view = data;
    seenCache.clear();
    saved = fromMix(data.mix);
    if (!keep) draft = structuredClone(saved);
    // Built again when the kinds or the ads change, or what is saved does (here, or from another browser).
    const next = JSON.stringify([data.mix.categories.map(c => c.key), data.ads.map(a => [a.id, a.kind, a.name, a.enabled])]);
    if (next !== shape || (!keep && before !== JSON.stringify(saved))) { shape = next; build(); }
    refresh();
    schedulePreview(true);
  }

  /* Controls ---------------------------------------------------------------------------------------- */
  $('mx-save').onclick = save;
  $('mx-discard').onclick = discard;
  $('mx-defaults').onclick = () => { if (!view) return; draft = defaults(); resetFaders(); toast('Everything back to the defaults: save to keep it, or discard.', {ok: true}); };
  $('mx-count').onclick = () => {
    if (!view) return;
    const n = byCount(), kinds = Object.keys(n), mean = 1 / Math.max(1, kinds.length);
    const w = key => +clamp(Math.round((n[key] || 0) / mean / .05) * .05, .05, 5).toFixed(2);
    for (const k of Object.keys(draft.kinds)) if (k in n) draft.kinds[k].weight = w(k);
    if ('unsorted' in n) draft.tuning.unsorted = w('unsorted');
    resetFaders();
  };
  $('mx-even').onclick = () => { if (!view) return; for (const k of Object.keys(draft.kinds)) draft.kinds[k].weight = 1; draft.tuning.unsorted = 1; resetFaders(); };
  $('mx-on').onclick = async e => {
    const b = e.target.closest('[data-on]');
    if (!b || !view) return;
    const on = b.dataset.on === 'true';
    try {
      if (on && view.order !== 'shuffle') await api('v1/my-ads', {order: 'shuffle'});
      const data = await api('v1/my-ads/mix?view=mix', {enabled: on});
      take(data, false);
      toast(on ? 'Mix on: kinds in balance, the ads seen most rested.' : 'Mix off: the plain shuffle.', {ok: true});
    } catch (err) { toast(err.message, {error: true}); }
  };
  $('mx-days').onclick = e => {
    const b = e.target.closest('[data-days]');
    if (!b) return;
    days = +b.dataset.days; VV.store.set('mixDays', days);
    for (const x of document.querySelectorAll('#mx-days [data-days]')) x.setAttribute('aria-pressed', String(x === b));
    schedulePreview(true);
  };
  for (const id of ['mx-kind', 'mx-sort', 'mx-own']) $(id).onchange = () => { all = false; listAds(); };
  let typing = 0;
  $('mx-q').oninput = () => { clearTimeout(typing); typing = setTimeout(() => { all = false; listAds(); }, 150); };
  $('mx-more-btn').onclick = () => { all = true; listAds(); };
  document.addEventListener('keydown', e => {
    if (!panel.hidden && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
  });
  addEventListener('beforeunload', e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
  VV.commands.add([
    {id: 'mix:save', title: 'Save the mix', group: 'Mix', when: () => !panel.hidden && dirty(), run: save},
    {id: 'mix:discard', title: 'Discard changes to the mix', group: 'Mix', when: () => !panel.hidden && dirty(), run: discard},
  ]);

  if ('ResizeObserver' in window) {
    let wide = 0;
    new ResizeObserver(() => { const w = $('mx-worn-chart').clientWidth; if (w && w !== wide) { wide = w; changed(); } }).observe($('mx-worn-chart'));
  }

  // Polled while its tab is shown (ads.js): the plays move on, so the chances do.
  (window.AdsTabs ||= {}).mix = () => VV.watch('v1/my-ads/mix', 60000, (data, w) => {
    if (w.error) { $('mx-error').hidden = false; $('mx-error').textContent = w.error.message; return; }
    $('mx-error').hidden = true;
    take(data, false);
  });
})();
