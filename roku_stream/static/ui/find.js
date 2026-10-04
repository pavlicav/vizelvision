// Find: one search box that adds a channel, game, show or recording to Up next.
//   Find.box() → element. Picking a live source asks how long it plays (OnAir.add); a
//   recording goes straight to the end of Up next; a later program opens Schedule.
// The listings are loaded on first use and shared with the page through VV.known.
window.Find = (() => {
  'use strict';
  const {h, api, fmt, toast, icon, ICONS} = VV;
  const FRESH = 120000, SHOWN = 8;
  let loadedAt = 0, loading = null, error = '';
  const fold = text => String(text ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const sources = () => VV.known.sources.filter(s => s.configured && s.id !== 'tv-thing-analog' && s.capabilities?.master_queue !== false);

  function load(changed) {
    if (loading || (Date.now() - loadedAt < FRESH && VV.known.sources.length)) return loading || Promise.resolve();
    error = '';
    loading = (async () => {
      try {
        VV.known.sources = (await api('v1/sources')).sources || [];
        await Promise.allSettled(sources().map(async s => { VV.known.programs.set(s.id, await api('v1/sources/' + encodeURIComponent(s.id) + '/programs')); changed(); }));
        loadedAt = Date.now();
      } catch (e) { error = e.message; }
      finally { loading = null; changed(); }
    })();
    return loading;
  }

  /* Everything that can go on: channels (or their games), recordings, then later programs ------ */
  function candidates() {
    const out = [], now = Date.now() / 1000;
    for (const source of sources()) {
      const data = VV.known.programs.get(source.id);
      if (source.id === 'library') {
        for (const file of data?.items || []) if (file.playable !== false)
          out.push({item: OnAir.recordingItem(file), name: file.title, also: [file.collection, file.channel, file.path], order: 2, kind: 'rec',
            detail: ['Recording', file.channel, file.aired ? fmt.day(file.aired) : null, file.variant, file.duration ? fmt.dur(file.duration) : null].filter(Boolean).join(' · ')});
        continue;
      }
      for (const channel of data?.channels || []) {
        const item = OnAir.guideItem(source, channel, data);
        const live = ['in', 'live'].includes(item.game?.state);
        out.push({item, name: item.title, also: [channel.name, channel.number, channel.now?.title, channel.game?.title, source.name], order: item.game ? 0 : 1,
          kind: live ? 'live' : '', detail: item.game ? [item.detail, item.game.status].filter(Boolean).join(' · ') : item.detail});
        const seen = new Set();
        if (!channel.game) for (const p of channel.upcoming || []) {
          if (!p.id || !(p.start > now) || seen.has(p.title)) continue;
          seen.add(p.title);
          out.push({item: OnAir.guideItem(source, channel, data, p), name: p.title, also: [], order: 3, kind: 'later',
            detail: fmt.when(p.start) + ' · ' + (channel.number ? channel.number + ' ' : '') + channel.name});
        }
      }
    }
    return out;
  }
  function search(query) {
    const words = fold(query).split(/\s+/).filter(Boolean), phrase = words.join(' ');
    if (!words.length) return [];
    const found = [];
    for (const c of candidates()) {
      const name = fold(c.name), all = name + ' ' + fold(c.also.filter(Boolean).join(' '));
      if (!words.every(w => all.includes(w))) continue;
      c.rank = name.startsWith(phrase) ? 0 : name.includes(phrase) ? 1 : words.every(w => name.includes(w)) ? 2 : 3;
      found.push(c);
    }
    return found.sort((a, b) => a.rank - b.rank || a.order - b.order || a.name.localeCompare(b.name));
  }

  /* The box ------------------------------------------------------------------------------------ */
  function box() {
    const input = h('input', {type: 'search', class: 'find-input', id: 'find-input', placeholder: 'Add a channel, game or recording…', autocomplete: 'off',
      spellcheck: 'false', 'aria-label': 'Find something to add to Up next', role: 'combobox', 'aria-expanded': 'false', 'aria-controls': 'find-results', 'aria-autocomplete': 'list', data: {search: ''}});
    const list = h('ul', {class: 'find-results', id: 'find-results', role: 'listbox', 'aria-label': 'Matches', hidden: true});
    const status = h('p', {class: 'find-status tiny muted', role: 'status'});
    const pop = h('div', {class: 'find-pop', hidden: true}, list, status);
    const root = h('div', {class: 'find'}, h('span', {class: 'find-icon', 'aria-hidden': 'true'}, icon(ICONS.search)), input, pop);
    let results = [], active = 0, open = false;

    function render() {
      const query = input.value.trim();
      open = !!query && document.activeElement === input;
      results = open ? search(query) : [];
      active = Math.min(active, Math.max(0, results.length - 1));
      list.replaceChildren(...results.slice(0, SHOWN).map((r, i) => {
        const go = !OnAir.playable(r.item) ? 'Schedule' : '+ Queue';
        const row = h('li', {id: 'find-option-' + i, class: 'find-option ' + r.kind, role: 'option', 'aria-selected': String(i === active)},
          h('div', {class: 'what'}, h('strong', (r.item.game ? OnAir.ICON[r.item.game.league] || '' : '') + r.name), h('small', r.detail)),
          h('span', {class: 'go'}, go));
        row.addEventListener('mousedown', e => e.preventDefault());  // Keep the focus in the box.
        row.onclick = () => pick(r);
        row.onmouseenter = () => { active = i; mark(); };
        return row;
      }));
      list.hidden = !open || !results.length;
      input.setAttribute('aria-expanded', String(!list.hidden));
      mark();
      const more = results.length - SHOWN;
      status.textContent = !open ? '' : error ? 'Could not load the listings: ' + error
        : !results.length ? (loading ? 'Loading listings…' : 'Nothing matches “' + query + '”.')
        : more > 0 ? more + ' more · keep typing to narrow it' : loading ? 'Still loading some listings…' : '';
      status.hidden = !status.textContent;
      pop.hidden = list.hidden && status.hidden;
    }
    function mark() {
      [...list.children].forEach((li, i) => li.setAttribute('aria-selected', String(i === active)));
      if (list.hidden) input.removeAttribute('aria-activedescendant');
      else { input.setAttribute('aria-activedescendant', 'find-option-' + active); list.children[active]?.scrollIntoView({block: 'nearest'}); }
    }
    function clear() { input.value = ''; active = 0; render(); }
    async function pick(r) {
      try {
        if (!OnAir.playable(r.item)) await OnAir.open(r.item, {action: 'schedule', done: clear});
        else await OnAir.add(r.item, {done: clear});
      } catch (e) { toast(e.message, {error: true}); }
    }
    input.addEventListener('focus', () => { load(render); render(); });
    input.addEventListener('blur', () => setTimeout(render, 0));
    input.addEventListener('input', () => { active = 0; load(render); render(); });
    input.addEventListener('keydown', e => {
      const shown = Math.min(results.length, SHOWN);
      if (e.key === 'ArrowDown' && shown) { active = (active + 1) % shown; mark(); e.preventDefault(); }
      else if (e.key === 'ArrowUp' && shown) { active = (active - 1 + shown) % shown; mark(); e.preventDefault(); }
      else if (e.key === 'Enter' && results[active]) { e.preventDefault(); pick(results[active]); }
      else if (e.key === 'Escape') { if (input.value) clear(); else input.blur(); e.preventDefault(); e.stopPropagation(); }
    });
    VV.commands.add({id: 'find:queue', title: 'Add to Up next: find a channel, game or recording', group: 'Up next', run: () => input.focus()});
    return root;
  }
  return {box, search};
})();
