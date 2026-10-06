// VizelVision · the core every page loads first.
//
//   VV.api(path, body?, {method, timeout})   one fetch: the API key, JSON, errors as Error(message)
//   VV.watch(path, ms, cb)                   a shared poller: pages and the top bar asking for the
//                                            same path share one request; paused while the tab is hidden
//   VV.h(tag, props, ...children)            builds DOM
//   VV.fmt.*                                 times, durations, sizes
//   VV.toast(text, {error})  VV.confirm(text, {ok, danger})
//   VV.label(target)                         names a source target (channel, file, station ID)
//   VV.networks()  VV.networkOf(target)      NBC, FOX, ABC, CBS and The CW: on YouTube TV and the antenna
//   VV.commands.add({...})                   the command palette (Ctrl/⌘-K) and keyboard shortcuts
//   VV.machinery                             the how-it-works diagrams: hidden until switched on
//
// A page marks its area with <header class="topbar" data-page="air"> and loads this script
// right after it. The API key lives in localStorage, so one sign-in covers every page.
window.VV = (() => {
  'use strict';
  const PAGES = [['air', 'On Air'], ['sources', 'Sources'], ['schedule', 'Schedule'], ['crawl', 'Crawl'],
    ['presentation', 'Presentation'], ['ads', 'Ads'], ['engineering', 'Engineering']];
  const store = {
    get(name, fallback) { try { const v = localStorage.getItem('vv.' + name); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(name, value) { try { localStorage.setItem('vv.' + name, JSON.stringify(value)); } catch {} },
  };

  /* DOM ------------------------------------------------------------------------ */
  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    if (props != null && (typeof props !== 'object' || props instanceof Node || Array.isArray(props))) { children.unshift(props); props = null; }
    for (const [key, value] of Object.entries(props || {})) {
      if (value == null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
      else if (key === 'data') Object.assign(node.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (key in node && !['list', 'form', 'type', 'role'].includes(key) && typeof value !== 'string') node[key] = value;
      else if (key === 'value' || key === 'checked' || key === 'disabled' || key === 'hidden' || key === 'selected') node[key] = value;
      else node.setAttribute(key, value === true ? '' : value);
    }
    append(node, children);
    return node;
  }
  function append(node, children) {
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  // replaceChildren, but nulls and falses are left out (the DOM would print them).
  const fill = (node, ...children) => { node.replaceChildren(); return append(node, children); };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const icon = (paths, size = 16) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', size); svg.setAttribute('height', size); svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = paths; return svg;
  };
  const ICONS = {
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    play: '<path d="M7 5v14l11-7z" fill="currentColor" stroke="none"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
    up: '<path d="m6 15 6-6 6 6"/>', down: '<path d="m6 9 6 6 6-6"/>', more: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    mute: '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>', sound: '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
    pin: '<path d="M12 17v5M5 17h14l-2-4V5H7v8z"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.1"/>',
    pause: '<path d="M8 5v14M16 5v14"/>', keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  };

  /* Formatting -------------------------------------------------------------------- */
  const asDate = value => value == null || value === '' ? null : value instanceof Date ? value
    : typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value);
  const valid = d => d && Number.isFinite(d.getTime());
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  const fmt = {
    date: asDate,
    clock(value) { const d = asDate(value); return valid(d) ? d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}) : '—'; },
    clockSec(value) { const d = asDate(value); return valid(d) ? d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit', second: '2-digit'}) : '—'; },
    day(value) { const d = asDate(value); return valid(d) ? d.toLocaleDateString([], {weekday: 'short', month: 'short', day: 'numeric'}) : '—'; },
    // 7:30 PM today; Fri 7:30 PM otherwise.
    when(value) {
      const d = asDate(value); if (!valid(d)) return '—';
      const time = d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
      return sameDay(d, new Date()) ? time : d.toLocaleDateString([], {weekday: 'short'}) + ' ' + time;
    },
    full(value) { const d = asDate(value); return valid(d) ? d.toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'}) : '—'; },
    dur(seconds) {
      if (!Number.isFinite(seconds)) return '–:–';
      seconds = Math.max(0, Math.round(seconds));
      const hh = Math.floor(seconds / 3600), mm = Math.floor(seconds / 60) % 60, ss = String(seconds % 60).padStart(2, '0');
      return hh ? hh + ':' + String(mm).padStart(2, '0') + ':' + ss : mm + ':' + ss;
    },
    mins(seconds) {
      if (!Number.isFinite(seconds)) return '—';
      const m = Math.round(Math.abs(seconds) / 60);
      return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + m % 60 + ' min' : '');
    },
    rel(value) {
      const d = asDate(value); if (!valid(d)) return '—';
      const s = (d.getTime() - Date.now()) / 1000;
      if (Math.abs(s) < 45) return 'now';
      return s > 0 ? 'in ' + fmt.mins(s) : fmt.mins(s) + ' ago';
    },
    bytes(n) { if (!Number.isFinite(n)) return '—'; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (n >= 1000 && i < u.length - 1) { n /= 1000; i++; } return (n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)) + ' ' + u[i]; },
    // The value a datetime-local input takes for a Date.
    local(d) { const p = n => String(n).padStart(2, '0'); return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes()); },
  };

  /* The API -------------------------------------------------------------------------- */
  let key = store.get('key', '');
  let blocked = false;  // 401 until a key is given: pollers wait.
  async function api(path, body, {method, timeout = 20000, raw = false} = {}) {
    const response = await fetch(path, {method: method || (body === undefined ? 'GET' : 'POST'),
      headers: {...(key ? {'X-API-Key': key} : {}), ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeout)});
    if (response.status === 401) { blocked = true; signin(); throw Object.assign(new Error('An API key is required'), {status: 401}); }
    if (raw) return response;
    let result = null;
    try { result = await response.json(); } catch { result = null; }
    if (!response.ok) throw Object.assign(new Error(result?.error?.message || 'HTTP ' + response.status), {status: response.status, code: result?.error?.code, details: result?.error?.details});
    return result;
  }

  /* Ad mute's pictures ------------------------------------------------------------------------ */
  // The detector keeps a small picture a second per analysed input for three hours, named
  // by the wall-clock second it saw it (it airs the programme delay later). Fetched with the
  // API key, so as blob URLs, and cached; a missing recent one is asked for again.
  const adFrames = new Map();
  function adFrame(input, sec) {
    const k = input + '/' + Math.round(sec);
    if (!adFrames.has(k)) {
      const p = api('v1/admute/frame/' + k + '.jpg', undefined, {raw: true, timeout: 8000})
        .then(r => r.ok ? r.blob() : null).then(b => b && URL.createObjectURL(b)).catch(() => null);
      adFrames.set(k, p);
      p.then(url => { if (!url && sec > Date.now() / 1000 - 20) adFrames.delete(k); });
      if (adFrames.size > 800) {
        const [old, q] = adFrames.entries().next().value;
        adFrames.delete(old); q.then(u => u && setTimeout(() => URL.revokeObjectURL(u), 60000));
      }
    }
    return adFrames.get(k);
  }
  // Show that picture in a .shot box (an <img> inside); 'none' while there is none.
  function adPicture(box, input, sec) {
    const img = box.querySelector('img'), want = input + '/' + Math.round(sec);
    if (img.dataset.want === want) return;
    img.dataset.want = want;
    adFrame(input, sec).then(url => {
      if (img.dataset.want !== want) return;
      if (url) img.src = url; else img.removeAttribute('src');
      box.classList.toggle('none', !url);
    });
  }

  /* Shared polling ---------------------------------------------------------------------- */
  const watchers = new Map();
  function watcher(path) {
    let w = watchers.get(path);
    if (!w) { w = {path, subs: new Set(), timer: null, data: undefined, at: 0, error: null, busy: false, took: 0}; watchers.set(path, w); }
    return w;
  }
  const every = w => Math.min(...[...w.subs].map(s => s.ms));
  function schedule(w, delay) {
    clearTimeout(w.timer);
    if (!w.subs.size) return;
    w.timer = setTimeout(() => pull(w), delay ?? every(w));
  }
  async function pull(w) {
    if (!w.subs.size) return;
    if (document.hidden || blocked || w.busy) { schedule(w); return; }
    w.busy = true; const started = performance.now();
    try { w.data = await api(w.path); w.error = null; w.at = Date.now(); }
    catch (error) { w.error = error; }
    finally { w.busy = false; w.took = performance.now() - started; }
    for (const sub of [...w.subs]) { try { sub.cb(w.data, w); } catch (e) { console.error(e); } }
    schedule(w);
  }
  function watch(path, ms, cb) {
    const w = watcher(path), sub = {ms, cb};
    w.subs.add(sub);
    if (w.data !== undefined) queueMicrotask(() => { if (w.subs.has(sub)) cb(w.data, w); });
    if (!w.busy) schedule(w, w.data === undefined || Date.now() - w.at > ms ? 0 : undefined);
    return () => { w.subs.delete(sub); if (!w.subs.size) { clearTimeout(w.timer); watchers.delete(path); } };
  }
  const poke = path => { const w = watchers.get(path); if (w) { clearTimeout(w.timer); pull(w); } };
  const pokeAll = () => watchers.forEach(w => { clearTimeout(w.timer); pull(w); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pokeAll(); });

  /* Sign in ------------------------------------------------------------------------------- */
  let signinDialog = null;
  function signin() {
    if (!signinDialog) {
      const input = h('input', {type: 'password', autocomplete: 'off', id: 'key', 'aria-label': 'API key'});
      const go = h('button', {class: 'primary', id: 'connect', type: 'submit'}, 'Connect');
      const form = h('form', {class: 'body'}, h('p', {class: 'hint'}, 'This VizelVision server asks for its API key. It is kept in this browser, for every page.'),
        h('label', {class: 'field'}, h('span', 'API key'), input), h('div', {class: 'actions'}, go));
      form.onsubmit = event => {
        event.preventDefault();
        setKey(input.value.trim()); input.value = '';
        signinDialog.close();
      };
      signinDialog = h('dialog', {id: 'signin', 'aria-label': 'Connect to VizelVision'}, h('div', {class: 'head'}, h('h2', 'Connect')), form);
      signinDialog.addEventListener('cancel', e => e.preventDefault());
      document.body.append(signinDialog);
    }
    if (!signinDialog.open) signinDialog.showModal();
    signinDialog.querySelector('input').focus();
  }
  function setKey(value) {
    key = value || ''; store.set('key', key); blocked = false;
    document.dispatchEvent(new CustomEvent('vv:auth'));
    pokeAll();
  }

  /* Toasts and confirmations ----------------------------------------------------------------- */
  let toasts = null;
  function toast(text, {error = false, ok = false, timeout} = {}) {
    if (!text) return;
    if (!toasts) { toasts = h('div', {class: 'toasts', role: 'status', 'aria-live': 'polite'}); document.body.append(toasts); }
    const node = h('div', {class: 'toast' + (error ? ' error' : ok ? ' ok' : '')}, text);
    toasts.append(node);
    while (toasts.children.length > 4) toasts.firstChild.remove();
    setTimeout(() => node.remove(), timeout || (error ? 14000 : 6000));
    return node;
  }
  function confirm(text, {title = 'Are you sure?', ok = 'OK', danger = false, detail = ''} = {}) {
    return new Promise(resolve => {
      const yes = h('button', {class: danger ? 'danger' : 'primary', type: 'button'}, ok);
      const no = h('button', {class: 'quiet', type: 'button'}, 'Cancel');
      const dialog = h('dialog', {class: 'confirm', 'aria-label': title}, h('div', {class: 'head'}, h('h2', title)),
        h('div', {class: 'body'}, h('p', text), detail ? h('p', {class: 'hint'}, detail) : null), h('div', {class: 'foot'}, no, yes));
      let answer = false;
      yes.onclick = () => { answer = true; dialog.close(); };
      no.onclick = () => dialog.close();
      dialog.addEventListener('close', () => { dialog.remove(); resolve(answer); });
      document.body.append(dialog); dialog.showModal(); (danger ? no : yes).focus();
    });
  }

  /* Naming targets -------------------------------------------------------------------------- */
  // Pages that load the catalog share it here, so every page (and the top bar) names things alike.
  const known = {sources: [], programs: new Map(), networks: []};
  const ROKU = ['youtube-tv', 'mlb', 'sunday-ticket', 'thursday-night-football'];
  const same = (a, b) => !!a && !!b && ['source_id', 'channel_id', 'date'].every(k => (a[k] ?? null) === (b[k] ?? null));
  function libraryItem(id) { return known.programs.get('library')?.items?.find(i => i.id === id); }
  function mediaName(item) {
    return item.title + (item.channel ? ' · ' + item.channel : '') + (item.aired ? ' · ' + fmt.day(item.aired) : '') + (item.variant ? ' (' + item.variant + ')' : '');
  }
  function label(target) {
    if (!target || target.source_id === 'off-air') return 'OFF AIR · test card';
    if (target.source_id === 'ident') return 'Station ID';
    if (target.source_id === 'schedule') return 'the weekly grid';
    if (target.source_id === 'library') {
      const item = libraryItem(target.channel_id);
      return 'Library · ' + (item ? mediaName(item) : String(target.channel_id).split('/').pop().replace(/\.[a-z0-9]{2,4}$/i, ''));
    }
    const source = known.sources.find(s => s.id === target.source_id);
    const channel = known.programs.get(target.source_id)?.channels?.find(c => String(c.id) === String(target.channel_id));
    const name = target.label || (channel ? (channel.number ? channel.number + ' · ' : '') + channel.name : target.resolved_source?.label || target.channel_id);
    return (source?.name || target.source_id) + ' · ' + name;
  }
  // The networks YouTube TV and the antenna (TV-Thing) both carry: [{network, call_sign, youtube_tv,
  // antenna: {source_id, channel_id, number, name} | null}]. Up next plays one from YouTube TV when it is
  // ready in time, else from the antenna; a target with antenna: false waits for YouTube TV.
  let networksLoading = null;
  function networks() {
    networksLoading ||= api('v1/networks').then(r => (known.networks = r.networks || []))
      .catch(() => { networksLoading = null; return known.networks; });
    return networksLoading;
  }
  // The network row of a YouTube TV channel or an antenna station; youtubeTv names the channel an MLB game is on.
  function networkOf(target, youtubeTv) {
    const t = target || {}, list = known.networks.filter(n => n.youtube_tv && n.antenna);
    if (t.source_id === 'youtube-tv') return list.find(n => n.youtube_tv === t.channel_id) || null;
    if (t.source_id === 'tv-thing-digital') return list.find(n => n.antenna.channel_id === t.channel_id) || null;
    if (t.source_id === 'mlb' && youtubeTv) return list.find(n => n.youtube_tv === youtubeTv) || null;
    return null;
  }
  // The top bar names what is on master even on a page that never loaded the guide.
  let namedAt = 0;
  async function learnFor(target) {
    if (!target || ['ident', 'off-air'].includes(target.source_id)) return;
    const id = target.source_id;
    if (Date.now() - namedAt < 120000 && known.programs.has(id) && known.sources.length) return;
    namedAt = Date.now();
    try {
      if (!known.sources.length) known.sources = (await api('v1/sources')).sources || [];
      if (!known.programs.has(id)) known.programs.set(id, await api('v1/sources/' + encodeURIComponent(id) + '/programs'));
    } catch {}
  }

  /* hls.js, which needs the key ----------------------------------------------------------------- */
  let hlsLoading = null;
  function hls() {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (!hlsLoading) hlsLoading = (async () => {
      const response = await fetch('static/vendor/hls-1.7.2.min.js', {headers: key ? {'X-API-Key': key} : {}, signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw Error('Could not load the video player');
      const script = document.createElement('script'); script.textContent = await response.text(); document.head.append(script);
      return window.Hls;
    })().catch(error => { hlsLoading = null; throw error; });
    return hlsLoading;
  }
  // Plays an HLS path in a <video>; returns a stop function.
  async function play(video, path, options = {}) {
    const Hls = await hls();
    if (Hls.isSupported()) {
      const player = new Hls({enableWorker: false, lowLatencyMode: false, ...options, xhrSetup: xhr => { if (key) xhr.setRequestHeader('X-API-Key', key); }});
      player.loadSource(path); player.attachMedia(video);
      return player;
    }
    if (video.canPlayType('application/vnd.apple.mpegurl') && !key) { video.src = path; return {destroy() { video.removeAttribute('src'); video.load(); }, on() {}}; }
    throw Error('This browser cannot play the stream');
  }

  /* JSON, readable ---------------------------------------------------------------------------------- */
  function json(value) {
    const pre = h('pre', {class: 'json'});
    const text = JSON.stringify(value, null, 2) ?? 'undefined';
    pre.innerHTML = text.replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]))
      .replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, (m, str, colon, word) =>
        str ? (colon ? '<span class="k">' + str + '</span>' + colon : '<span class="s">' + str + '</span>') : word ? '<span class="b">' + m + '</span>' : '<span class="n">' + m + '</span>');
    return pre;
  }

  /* The machinery switch -------------------------------------------------------------------------- */
  const machinery = {
    get on() { return document.body.classList.contains('show-machinery'); },
    set(on) {
      document.body.classList.toggle('show-machinery', !!on); store.set('machinery', !!on);
      $$('.tool[data-tool=machinery]').forEach(b => b.setAttribute('aria-pressed', String(!!on)));
      document.dispatchEvent(new CustomEvent('vv:machinery', {detail: {on: !!on}}));
    },
    toggle() { machinery.set(!machinery.on); },
  };

  /* Commands: the palette and keys ------------------------------------------------------------------- */
  const registry = [];
  const commands = {
    add(...list) { for (const c of list.flat()) { const i = registry.findIndex(r => r.id === c.id); if (i >= 0) registry.splice(i, 1); registry.push(c); } },
    remove(prefix) { for (let i = registry.length - 1; i >= 0; i--) if (registry[i].id.startsWith(prefix)) registry.splice(i, 1); },
    list: () => registry.filter(c => !c.when || c.when()),
  };
  let paletteNode = null;
  function palette() {
    if (!store.get('palette', true) || paletteNode) return;
    const input = h('input', {type: 'text', placeholder: 'Go to a page, or do something…', 'aria-label': 'Command', autocomplete: 'off', spellcheck: 'false'});
    const list = h('ul', {role: 'listbox', 'aria-label': 'Commands'});
    paletteNode = h('div', {class: 'palette', role: 'dialog', 'aria-label': 'Command palette'}, h('div', {class: 'box'}, input, list));
    let shown = [], index = 0;
    const close = () => { paletteNode?.remove(); paletteNode = null; };
    const run = async c => {
      close();
      try { const result = await c.run(); if (typeof result === 'string') toast(result, {ok: true}); }
      catch (e) { toast(e.message, {error: true}); }
    };
    function draw() {
      const q = input.value.trim().toLowerCase();
      shown = commands.list().filter(c => !q || (c.title + ' ' + (c.group || '') + ' ' + (c.words || '')).toLowerCase().includes(q)).slice(0, 60);
      index = Math.min(index, Math.max(0, shown.length - 1));
      list.replaceChildren(...shown.map((c, i) => {
        const li = h('li', {role: 'option', 'aria-selected': String(i === index)}, h('span', c.title), c.keys ? h('kbd', c.keys) : null, h('span', {class: 'group'}, c.group || ''));
        li.onmousemove = () => { if (index !== i) { index = i; draw(); } };
        li.onclick = () => run(c);
        return li;
      }));
      if (!shown.length) list.append(h('li', {class: 'empty'}, 'Nothing matches.'));
      list.querySelector('[aria-selected=true]')?.scrollIntoView({block: 'nearest'});
    }
    input.oninput = () => { index = 0; draw(); };
    input.onkeydown = e => {
      if (e.key === 'ArrowDown') { index = Math.min(index + 1, shown.length - 1); draw(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { index = Math.max(index - 1, 0); draw(); e.preventDefault(); }
      else if (e.key === 'Enter' && shown[index]) { run(shown[index]); e.preventDefault(); }
      else if (e.key === 'Escape') { close(); e.preventDefault(); }
    };
    paletteNode.onclick = e => { if (e.target === paletteNode) close(); };
    document.body.append(paletteNode); draw(); input.focus();
  }
  function shortcuts() {
    const rows = [['Ctrl/⌘ K', 'Command palette'], ['?', 'This list'], ['m', 'Show or hide the machinery (how it works)'], ['/', 'Search on this page'],
      ...PAGES.map(([, name], i) => ['g ' + (i + 1), 'Go to ' + name]), ...registry.filter(c => c.keys && !c.id.startsWith('go:')).map(c => [c.keys, c.title])];
    const close = h('button', {class: 'quiet', type: 'button'}, 'Close');
    const dialog = h('dialog', {'aria-label': 'Keyboard shortcuts'}, h('div', {class: 'head'}, h('h2', 'Keys')),
      h('div', {class: 'body'}, h('dl', {class: 'kv'}, rows.map(([k, v]) => [h('dt', h('kbd', k)), h('dd', v)]))), h('div', {class: 'foot'}, close));
    close.onclick = () => dialog.close(); dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog); dialog.showModal();
  }
  let chord = null;
  document.addEventListener('keydown', e => {
    const typing = e.target.closest?.('input,textarea,select,[contenteditable=true]') || document.querySelector('dialog[open]');
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { if (store.get('palette', true)) { e.preventDefault(); palette(); } return; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey || paletteNode) return;
    if (chord === 'g') {
      chord = null;
      const page = PAGES[Number(e.key) - 1];
      if (page) { location.href = page[0]; e.preventDefault(); }
      return;
    }
    if (e.key === 'g') { chord = 'g'; setTimeout(() => { chord = null; }, 1200); return; }
    if (e.key === '?') { shortcuts(); e.preventDefault(); return; }
    if (e.key === 'm') { machinery.toggle(); e.preventDefault(); return; }
    if (e.key === '/') { const search = $('[data-search]'); if (search) { search.focus(); search.select?.(); e.preventDefault(); } return; }
    const command = registry.find(c => c.keys === e.key && (!c.when || c.when()));
    if (command) { e.preventDefault(); Promise.resolve().then(command.run).then(r => { if (typeof r === 'string') toast(r, {ok: true}); }).catch(err => toast(err.message, {error: true})); }
  });

  /* The shell: top bar, tally, clock ---------------------------------------------------------------------- */
  const header = $('header.topbar');
  const shell = {};
  if (header && window.top === window) {
    const page = header.dataset.page;
    const mark = h('a', {class: 'wordmark', href: 'air', 'aria-label': 'VizelVision · On Air'}, h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i'), h('i')), 'VizelVision');
    const nav = h('nav', {class: 'nav', 'aria-label': 'VizelVision'}, PAGES.map(([href, name]) =>
      h('a', {href, 'aria-current': href === page ? 'page' : null, data: {page: href}}, name)));
    const tallyLamp = h('span', {class: 'lamp'}), tallyTag = h('b', 'MASTER'), tallyText = h('span', 'Connecting…');
    const tally = h('a', {class: 'tally', href: 'air', title: 'What master has on air', data: {state: 'offline'}}, tallyLamp, h('span', {class: 'what'}, tallyTag, tallyText));
    const clock = h('div', {class: 'clock', 'aria-hidden': 'true'});
    const gear = h('button', {class: 'tool', type: 'button', data: {tool: 'machinery'}, 'aria-pressed': 'false', title: 'Show how things work: live diagrams of the machinery (m)'},
      icon(ICONS.gear), h('span', {class: 'word'}, 'Machinery'));
    gear.onclick = () => machinery.toggle();
    const find = h('button', {class: 'tool', type: 'button', title: 'Command palette (Ctrl/⌘-K)', 'aria-label': 'Command palette'}, icon(ICONS.search));
    find.onclick = palette;
    find.hidden = !store.get('palette', true);
    header.replaceChildren(mark, nav, h('div', {class: 'console'}, tally, clock, find, gear));
    const tick = () => {
      const d = new Date(), seconds = store.get('clockSeconds', true);
      fill(clock, d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0'), seconds ? h('small', ':' + String(d.getSeconds()).padStart(2, '0')) : null);
    };
    tick(); setInterval(tick, 1000);
    let queue = null;
    watch('v1/queue', 2000, data => { queue = data; });
    watch('v1/master', 2000, (master, w) => {
      const navAir = $('[data-page=air]', nav);
      const set = (state, tag, text, lamp) => {
        tally.dataset.state = state; tallyTag.textContent = tag; tallyText.textContent = text;
        tallyLamp.className = 'lamp' + (lamp ? ' ' + lamp : '');
        fill(navAir, state === 'live' ? h('span', {class: 'lamp pgm'}) : null, 'On Air');
      };
      if (w.error) { if (w.error.status !== 401) set('offline', 'MASTER', 'Unavailable', 'warn'); return; }
      if (['not_configured', 'unavailable', 'stopped'].includes(master.state)) return set('offline', 'MASTER', 'Not connected', 'warn');
      if (master.state === 'reconnecting') return set('offline', 'MASTER', 'Reconnecting…', 'warn blink');
      const onAir = master.on_air;
      if (!onAir) return set('off', 'OFF AIR', master.recovery ? 'Recovering ' + label(master.recovery.target) + '…' : 'Test card', master.recovery ? 'warn blink' : '');
      learnFor(onAir);
      const aired = queue?.items?.find(i => i.status === 'succeeded' && same(i.target, onAir));
      const hold = queue?.hold && same(queue.hold.target, onAir) ? queue.hold : null;
      const media = onAir.media?.duration_seconds ? fmt.dur(onAir.media.position_seconds) + ' / ' + fmt.dur(onAir.media.duration_seconds) : null;
      const parts = [onAir.source_id === 'ident' ? 'Station ID' : label(onAir).replace(/^Library · /, ''), aired?.origin === 'programming' ? aired.title : null,
        hold?.detail || hold?.game?.title || null, media];
      set('live', 'ON AIR' + (queue?.paused ? ' · UP NEXT PAUSED' : ''), parts.filter((v, i, a) => v && a.indexOf(v) === i).join(' · '), 'pgm');
    });
    commands.add(PAGES.map(([href, name], i) => ({id: 'go:' + href, title: 'Go to ' + name, group: 'Pages', keys: 'g ' + (i + 1), run: () => { location.href = href; }})),
      {id: 'go:roku', title: 'Go to the source Roku (in TV Thing)', group: 'Pages', run: () => { location.href = 'engineering#roku'; }},
      {id: 'go:sonic', title: 'Go to the Sonic identity sheet', group: 'Pages', run: () => { location.href = 'sonic'; }},
      {id: 'ui:machinery', title: 'Show or hide the machinery', group: 'Interface', keys: 'm', run: () => machinery.toggle()},
      {id: 'ui:keys', title: 'Keyboard shortcuts', group: 'Interface', keys: '?', run: shortcuts},
      {id: 'queue:pause', title: 'Pause Up next', group: 'Up next', when: () => queue && !queue.paused && !queue.hold,
        run: async () => { await api('v1/queue/pause', {}); poke('v1/queue'); return 'Up next paused.'; }},
      {id: 'queue:resume', title: 'Resume Up next', group: 'Up next', when: () => queue?.paused,
        run: async () => { await api('v1/queue/resume', {}); poke('v1/queue'); return 'Up next resumed.'; }},
      {id: 'ui:forget', title: 'Forget the API key on this browser', group: 'Interface', when: () => !!key, run: () => { setKey(''); return 'API key forgotten.'; }});
    Object.assign(shell, {header, nav, tally});
  } else if (header) header.hidden = true;  // Framed inside another VizelVision page.
  if (store.get('machinery', false)) document.body.classList.add('show-machinery');
  queueMicrotask(() => $$('.tool[data-tool=machinery]').forEach(b => b.setAttribute('aria-pressed', String(machinery.on))));

  return {api, watch, poke, pokeAll, h, append, fill, $, $$, icon, ICONS, fmt, toast, confirm, label, same, known, ROKU, mediaName, libraryItem, networks, networkOf,
    hls, play, json, machinery, commands, palette, shortcuts, store, signin, setKey, shell, PAGES, adFrame, adPicture,
    get key() { return key; }, watchers};
})();
