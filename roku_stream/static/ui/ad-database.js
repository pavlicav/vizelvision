// Ads › Ad database: every clip the known-ads database holds (admute-prints.json, written by the
// sidecar), with its script, pictures and counts. Name an ad, or forget it. Its ids start db-
// where the other tabs use the same name.
(() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const $ = id => document.getElementById(id);
  const PAGE = 60;
  let clips = [], shown = PAGE, editing = null;
  let filter = VV.store.get('ads.filter', 'ads'), sort = VV.store.get('ads.sort', 'last');

  // Pictures need the API key, so they are fetched as blobs, once each, when scrolled to.
  const pics = new Map();
  const seen = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) { seen.unobserve(e.target); load(e.target); }
  }, {rootMargin: '300px'});
  function load(img) {
    const name = img.dataset.pic;
    if (!pics.has(name)) pics.set(name, api('v1/admute/ad/' + name, undefined, {raw: true})
      .then(r => r.ok ? r.blob() : null).then(b => b && URL.createObjectURL(b)).catch(() => null));
    pics.get(name).then(url => { if (url) img.src = url; else img.closest('.shot')?.classList.add('none'); });
  }
  function pictures(c) {
    if (!c.pics) return h('div', {class: 'pics none'}, h('p', null, c.kind === 'show' ? 'Show sounds have no pictures.'
      : 'No pictures yet: they are taken the next time it airs.'));
    return h('div', {class: 'pics'}, Array.from({length: c.pics}, (_, i) => {
      const img = h('img', {alt: '', 'data-pic': `${c.id}-${i}.jpg`});
      seen.observe(img);
      return h('div', {class: 'shot'}, img);
    }));
  }

  // Words ------------------------------------------------------------------------------------
  const plain = s => (s || '').toLowerCase();
  const terms = () => plain($('find').value).split(/\s+/).filter(Boolean);
  function marked(text, words) {
    if (!words.length) return text;
    const re = new RegExp('(' + words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
    return text.split(re).map((part, i) => i % 2 ? h('mark', null, part) : part);
  }
  const scriptText = c => (c.script || []).map(l => l[1]).join(' ');
  const source = c => {
    if (c.seed && c.seed.startsWith('game-')) return (c.src || 'an MLB game') + ' (play-by-play)';
    const src = (c.src || '').replace(/\.(mp4|ts|mkv)$/i, '');
    if (src && src !== 'break' && src !== 'repeat') return src;
    return c.seed ? 'recordings' : c.kind === 'show' ? 'a repeat in the programme' : 'a live break';
  };
  function title(c) {
    if (c.name) return {text: c.name, untitled: false};
    const first = (c.script || []).find(l => l[1].trim());
    if (first) {
      const words = first[1].split(/\s+/);
      return {text: '“' + words.slice(0, 9).join(' ') + (words.length > 9 ? '…' : '') + '”', untitled: true};
    }
    return {text: (c.kind === 'show' ? 'Show sound' : 'Ad') + ' #' + c.id, untitled: true};
  }

  // One ad ----------------------------------------------------------------------------------
  function status(c) {
    if (c.kind === 'show') return h('span', {class: 'chip touch', title: 'Sounds like the programme: it can only argue for sound'}, 'Show sound');
    if (c.known) return h('span', {class: 'chip pvw', title: 'Muted the moment it airs again'}, c.seed && c.breaks < 2 ? 'Known · from ' + (c.seed.startsWith('game-') ? 'a game' : 'recordings') : 'Known ad');
    const more = Math.max(1, (c.need || 2) - (c.breaks || 1));
    return h('span', {class: 'chip warn', title: c.spot === 'pod' ? 'Stored from the shape of a break: its next airing counts while it plays' : 'Counts as an ad once heard again'},
      `Heard once · needs ${more} more airing${more > 1 ? 's' : ''}`);
  }
  function script(c, words) {
    if (c.script == null) return h('div', {class: 'script empty'}, c.kind === 'show' ? 'No words written down.'
      : 'No script yet: it is written down the next time this ad airs.');
    if (!c.script.length) return h('div', {class: 'script empty'}, 'No words: music or sound only.');
    const lines = c.script.map(([t, text]) => h('div', {class: 'ln'}, h('i', null, fmt.dur(Math.max(0, t))), h('span', null, marked(text, words))));
    const long = c.script.length > 6 && !words.length;
    const box = h('div', {class: 'script' + (long ? ' folded' : '')}, lines);
    const note = c.script_cover < 0.8 ? h('p', {class: 'tiny muted'}, `Partial: ${Math.round(100 * c.script_cover)}% of it heard so far. The rest is filled in as its parts air.`) : null;
    if (!long) return [box, note];
    const more = h('button', {class: 'xs quiet', type: 'button'}, `All ${c.script.length} lines`);
    more.onclick = () => { box.classList.remove('folded'); more.remove(); };
    return [box, note, more];
  }
  function heading(c) {
    const t = title(c);
    if (editing === c.id) {
      const input = h('input', {type: 'text', value: c.name || '', maxlength: 80, placeholder: 'Advertiser or product, e.g. GEICO', 'aria-label': 'Name'});
      const form = h('form', null, input, h('button', {class: 'sm primary', type: 'submit'}, 'Save'),
        h('button', {class: 'sm quiet', type: 'button', onclick: () => { editing = null; render(); }}, 'Cancel'));
      form.onsubmit = e => { e.preventDefault(); rename(c, input.value); };
      queueMicrotask(() => input.focus());
      return h('div', {class: 'title'}, form);
    }
    return h('div', {class: 'title'}, h('h2', {class: t.untitled ? 'untitled' : null}, marked(t.text, terms())),
      h('div', {class: 'end'}, h('button', {class: 'xs quiet', type: 'button', title: 'Name it', onclick: () => { editing = c.id; render(); }}, c.name ? 'Rename' : 'Name')));
  }
  function card(c) {
    const words = terms();
    const dot = () => h('span', {class: 'sep'}, '·');
    const facts = h('div', {class: 'facts'}, status(c), c.dur ? h('span', {title: 'Length'}, fmt.dur(c.dur)) : null, dot(),
      h('span', null, c.seed && c.breaks < 2 ? 'from ' : 'heard ', c.seed && c.breaks < 2 ? source(c) : `${c.breaks}×`),
      c.seed && c.breaks < 2 ? null : [dot(), h('span', null, 'from ', marked(source(c), words))], dot(),
      h('span', {title: fmt.full(c.last)}, (c.breaks > 1 ? 'last heard ' : c.seed ? 'added ' : 'heard ') + fmt.when(c.last)));
    return h('section', {class: 'panel ad', 'aria-label': title(c).text},
      h('div', {class: 'body'}, heading(c), pictures(c), facts, script(c, words),
        h('div', {class: 'foot'}, h('span', {class: 'mach machinery'}, `clip ${c.id} · ${c.hashes} hashes` + (c.seed ? ' · ' + c.seed : '')
            + (c.script_from ? ' · words from ' + (c.script_from === 'recording' ? 'a recording' : 'the broadcast') : '')),
          h('div', {class: 'end'}, h('button', {class: 'xs danger', type: 'button', onclick: () => forget(c),
            title: c.kind === 'show' ? 'It may then be learnt as an ad' : 'It is no longer recognised; learnt again only from new breaks'}, 'Forget')))));
  }

  // The list ---------------------------------------------------------------------------------
  const KINDS = {ads: c => c.kind === 'ad', known: c => c.kind === 'ad' && c.known, learning: c => c.kind === 'ad' && !c.known, show: c => c.kind === 'show'};
  const ORDER = {last: c => -(c.last || 0), breaks: c => -(c.breaks || 0) * 1e10 - (c.last || 0), first: c => -(c.first || 0), dur: c => -(c.dur || 0)};
  function render() {
    const words = terms();
    const match = c => !words.length || words.every(w => plain(scriptText(c) + ' ' + (c.name || '') + ' ' + source(c)).includes(w));
    for (const [k, test] of Object.entries(KINDS)) $('c-' + k).textContent = clips.filter(test).length;
    $('n-known').textContent = clips.filter(KINDS.known).length;
    $('n-learning').textContent = clips.filter(KINDS.learning).length;
    $('n-show').textContent = clips.filter(KINDS.show).length;
    $('n-scripted').textContent = clips.filter(c => c.kind === 'ad' && c.script != null).length + ' / ' + clips.filter(KINDS.ads).length;
    for (const b of $('filter').querySelectorAll('[data-filter]')) b.setAttribute('aria-pressed', String(b.dataset.filter === filter));
    $('sort').value = sort;
    const list = clips.filter(KINDS[filter]).filter(match).sort((a, b) => ORDER[sort](a) - ORDER[sort](b));
    VV.fill($('db-ads'), ...list.slice(0, shown).map(card));
    $('more').hidden = list.length <= shown;
    $('more').textContent = `Show more (${list.length - shown} left)`;
    $('db-empty').hidden = list.length > 0;
    $('db-empty').textContent = words.length ? 'Nothing matches that search.' : filter === 'show' ? 'No show sounds yet.'
      : 'Nothing here yet. Breaks it confirms are learnt ten minutes after they end, and a game\'s breaks as the game goes.';
  }

  async function rename(c, name) {
    try {
      await api('v1/admute/name', {clip: c.id, name: name.trim()});
      c.name = name.trim() || null;
      editing = null;
      toast(name.trim() ? 'Named.' : 'Name cleared.', {ok: true});
      setTimeout(() => VV.poke('v1/admute/known'), 1500);
    } catch (e) { toast(e.message, {error: true}); }
    render();
  }
  async function forget(c) {
    const t = title(c).text;
    if (!await VV.confirm(c.kind === 'show' ? 'It is no longer kept as show sound.' : 'It is no longer recognised when it airs, and is learnt again only from new breaks.',
      {title: `Forget ${c.name ? t : 'this ' + (c.kind === 'show' ? 'show sound' : 'ad')}?`, ok: 'Forget', danger: true})) return;
    try {
      await api('v1/admute/forget', {clips: [c.id]});
      clips = clips.filter(x => x.id !== c.id);
      toast('Forgotten.', {ok: true});
    } catch (e) { toast(e.message, {error: true}); }
    render();
  }

  $('filter').onclick = e => {
    const f = e.target.closest('[data-filter]')?.dataset.filter;
    if (!f) return;
    filter = f; shown = PAGE; VV.store.set('ads.filter', f); render();
  };
  $('sort').onchange = () => { sort = $('sort').value; VV.store.set('ads.sort', sort); render(); };
  $('find').addEventListener('input', () => { shown = PAGE; render(); });
  $('more').onclick = () => { shown += PAGE; render(); };
  // Polled while its tab is shown (ads.js).
  (window.AdsTabs ||= {}).database = () => VV.watch('v1/admute/known', 15000, (data, w) => {
    $('db-error').textContent = w.error ? w.error.message : '';
    if (w.error || editing != null) return;      // (a refresh would drop what is being typed)
    clips = data.clips || [];
    render();
  });
})();
