// Continuity announcements: who announces each break, in which voice, saying what.
//   ContinuityPanel.mount(host) → {refresh, dirty, stop}
window.ContinuityPanel = (() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const COLOURS = ['#4fb3ff', '#ffb340', '#ff7aa2', '#34d07a', '#b495ff', '#ff9a5a', '#5fd4d0', '#d7e36b'];
  const LANGUAGES = {en: 'English', fr: 'French', es: 'Spanish', de: 'German', it: 'Italian', nl: 'Dutch', ja: 'Japanese'};
  const STYLE = `
.cp .roster{display:grid;grid-template-columns:repeat(24,minmax(0,1fr));gap:2px;touch-action:none;user-select:none}
.cp .hour{height:48px;border-radius:3px;border:0;padding:3px 0;font:600 10px/1.1 var(--mono);color:#081014;display:grid;align-content:space-between;justify-items:center;cursor:crosshair;overflow:hidden}
.cp .hour.now{box-shadow:inset 0 0 0 2px #fff}.cp .hour small{font-weight:500;font-size:9.5px}
.cp .legend{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.cp .legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.cp .people{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.cp .person{border:1px solid var(--line);background:var(--well);border-radius:var(--r-lg);padding:14px;border-top:3px solid var(--who);display:grid;gap:10px;align-content:start}
.cp .person.duty{box-shadow:0 0 0 1px var(--touch)}
.cp .script{padding:10px 14px;border-left:3px solid var(--touch);background:var(--well);border-radius:0 var(--r) var(--r) 0;display:grid;gap:3px}
.cp .script p{color:var(--ink);font-style:italic}.cp .script small{color:var(--muted);font-size:12px;margin-top:4px}
.cp audio{width:100%;margin-top:6px}
@media(max-width:700px){.cp .roster{grid-template-columns:repeat(12,minmax(0,1fr))}}`;

  function mount(host) {
    if (!document.getElementById('cp-style')) document.head.append(h('style', {id: 'cp-style'}, STYLE));
    host.classList.add('cp', 'stack');
    host.innerHTML = `
<div class="cols-2">
 <section class="panel" aria-label="Continuity on air"><div class="head"><span class="lamp" data-id="lamp"></span><h2>Announcer</h2></div><div class="body stack tight">
  <label class="switch"><input type="checkbox" data-id="enabled"><span>Announce at every break</span></label>
  <div role="radiogroup" aria-label="Who is on duty" class="stack tight" style="gap:2px">
   <label class="check"><input type="radio" name="cp-duty" value="roster"><span>Follow the roster by hour<small>Cairo Radio's shifts, painted below</small></span></label>
   <label class="check"><input type="radio" name="cp-duty" value="fixed"><span>One announcer all day</span></label></div>
  <label class="field"><span>Announcer on duty (outside the roster)</span><select data-id="on-duty"></select></label>
  <div class="row" data-id="ready" style="gap:6px"></div>
  <p class="note warn" data-id="error" role="status"></p></div></section>
 <section class="panel" aria-label="Next break"><div class="head"><h2>Next break</h2></div><div class="body" data-id="next"></div></section>
</div>
<section class="panel" aria-label="Duty roster"><div class="head"><h2>Duty roster</h2><div class="end"><label class="row tiny muted" style="gap:8px">Paint with<select data-id="brush" style="width:auto;min-width:180px"></select></label></div></div>
 <div class="body stack tight"><p class="hint tiny">Who announces at each hour, chosen by when the break airs. Click or drag across hours to paint; save below.</p>
  <div class="roster" data-id="roster"></div><div class="legend" data-id="legend"></div></div></section>
<section class="panel" aria-label="Announcer personalities"><div class="head"><h2>Personalities</h2><div class="end"><span class="tiny" data-id="dirty" style="color:var(--warn)"></span><button type="button" class="sm quiet" data-id="add">+ Add personality</button><button type="button" class="sm primary" data-id="save">Save</button></div></div>
 <div class="body stack tight"><p class="hint tiny">A Deepgram Aura voice and up to four lines, spoken on the ID's voice cues and ending before its end card. <code>{just_played}</code> and <code>{up_next}</code> are filled in at each break, in the announcer's language; a line naming something unknown is left out.</p>
  <div class="people" data-id="people"></div></div></section>
<section class="panel" aria-label="Recent announcements"><div class="head"><h2>Recent announcements</h2></div><ul class="list" data-id="recent"></ul></section>`;
    const $ = name => host.querySelector(`[data-id="${name}"]`);
    let data = null, draft = null, brush = null, painting = false;
    const say = (text, error) => toast(text, {error, ok: !error});
    const dirty = () => JSON.stringify(draft) !== JSON.stringify(data.settings);
    const colour = id => COLOURS[Math.max(0, draft.announcers.findIndex(a => a.id === id)) % COLOURS.length];
    const lang = model => String(model).split('-').pop();
    const person = id => draft.announcers.find(a => a.id === id);
    const markDirty = () => { $('dirty').textContent = dirty() ? 'Unsaved changes' : ''; $('save').disabled = !dirty(); };
    async function listen(name, box) {
      const response = await api('v1/continuity/audio/' + encodeURIComponent(name), undefined, {raw: true});
      if (!response.ok) throw Error('Could not load the audio');
      const url = URL.createObjectURL(await response.blob()); box.querySelector('audio')?.remove();
      const audio = h('audio', {controls: true, src: url}); box.append(audio); audio.play().catch(() => {});
    }
    const script = (lines, note) => h('div', {class: 'script'}, lines.map(line => h('p', '“' + line + '”')), note ? h('small', note) : null);

    function renderAir() {
      $('enabled').checked = data.settings.enabled;
      $('lamp').className = 'lamp ' + (data.settings.enabled ? 'pvw' : '');
      host.querySelectorAll('[name=cp-duty]').forEach(r => { r.checked = r.value === draft.duty; });
      $('on-duty').replaceChildren(...draft.announcers.filter(a => a.id).map(a => new Option(a.name, a.id))); $('on-duty').value = draft.on_duty;
      const r = data.ready, now = data.on_duty_now && person(data.on_duty_now);
      VV.fill($('ready'), now ? h('span', {class: 'chip touch'}, 'On duty now: ' + now.name) : null,
        ...[[r.key, 'Deepgram voice', 'No Deepgram key (continuity.keys_file)'], [r.music, 'ID music bed', 'No music bed: rebuild the ID'], [r.id, 'Station ID', 'No station ID file'], [r.sports, 'Sports ID', 'No Sports ID']]
          .filter(([ok]) => ok !== undefined).map(([ok, good, bad]) => h('span', {class: 'chip ' + (ok ? 'pvw' : 'pgm')}, ok ? good : bad)));
      const next = $('next'); next.replaceChildren();
      if (data.next) {
        const n = data.next;
        next.append(h('div', {class: 'stack tight'}, h('div', {class: 'row'}, h('strong', n.name), h('span', {class: 'tiny muted'}, n.break_at ? 'about ' + fmt.when(n.break_at) + ' (' + fmt.rel(n.break_at) + ')' : '')),
          script(n.lines, 'After ' + n.just_played + (n.up_next ? ' · before ' + n.up_next : ' · before OFF AIR'))));
        const b = h('button', {class: 'sm', type: 'button'}, '▶ Listen'); b.onclick = () => listen(n.file, next).catch(e => say(e.message, true)); next.append(h('div', {class: 'actions', style: {marginTop: '10px'}}, b));
      } else next.append(h('p', {class: 'hint'}, data.settings.enabled ? 'Nothing cued yet. The next break is worked out every 20 seconds; nothing is cued while master shows the test card.' : 'Announcements are off: the plain station ID plays.'));
      $('error').textContent = data.error || '';
    }
    function renderRoster() {
      const strip = $('roster'); strip.replaceChildren();
      draft.roster.forEach((who, hour) => {
        const id = who || draft.on_duty, p = person(id);
        strip.append(h('button', {class: 'hour' + (hour === data.hour ? ' now' : ''), type: 'button', data: {hour}, style: {background: colour(id)},
          'aria-label': `${hour}:00 · ${p ? p.name : 'on duty'}${who ? '' : ' (on duty)'}`}, h('span', String(hour)), h('small', p ? p.name.replace(/^(The|DJ) /, '').slice(0, 3) : '—')));
      });
      $('brush').replaceChildren(...draft.announcers.filter(a => a.id).map(a => new Option(a.name, a.id)));
      if (!person(brush)) brush = draft.announcers[0]?.id; $('brush').value = brush;
      VV.fill($('legend'), draft.announcers.filter(a => a.id).map(a => h('span', h('i', {style: {background: colour(a.id)}}), a.name)));
      host.querySelector('[aria-label="Duty roster"]').style.opacity = draft.duty === 'roster' ? '' : '.55';
    }
    function paint(cell) {
      if (!cell?.dataset?.hour || draft.roster[+cell.dataset.hour] === brush) return;
      draft.roster[+cell.dataset.hour] = brush; renderRoster(); markDirty();
    }
    $('roster').addEventListener('pointerdown', e => { if (e.button) return; painting = true; paint(e.target.closest('.hour')); e.preventDefault(); });
    // Keyboard: Enter or Space paints the focused hour.
    $('roster').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.closest('.hour')) { e.preventDefault(); paint(e.target.closest('.hour')); $('roster').querySelector(`[data-hour="${e.target.dataset.hour}"]`)?.focus(); } });
    window.addEventListener('pointermove', e => { if (painting) paint(document.elementFromPoint(e.clientX, e.clientY)?.closest('.cp .hour')); });
    window.addEventListener('pointerup', () => { painting = false; });
    $('brush').onchange = () => { brush = $('brush').value; };

    function voiceSelect(model) {
      const select = h('select'), groups = new Map();
      for (const v of data.voices) {
        if (!groups.has(v.language)) { const g = h('optgroup'); g.label = LANGUAGES[v.language] || v.language; groups.set(v.language, g); select.append(g); }
        const name = v.id.replace(/^aura-2-/, '').replace(/-[a-z]{2}$/, '');
        groups.get(v.language).append(new Option([name, v.accent, v.tags.slice(0, 3).join(', ')].filter(Boolean).join(' · '), v.id));
      }
      if (![...select.options].some(o => o.value === model)) select.append(new Option(model, model));
      select.value = model; return select;
    }
    const clean = a => ({...a, lines: a.lines.map(l => (l || '').trim()).filter(Boolean)});
    function renderPeople() {
      const holder = $('people'); holder.replaceChildren();
      draft.announcers.forEach((a, index) => {
        const hours = draft.roster.filter(w => w === a.id).length;
        const title = h('h3', {class: 'row', style: {gap: '8px'}}, h('span', a.name || 'New personality'), a.id === draft.on_duty ? h('span', {class: 'chip touch'}, 'On duty') : null,
          hours ? h('span', {class: 'chip'}, hours + ' h') : null, h('span', {class: 'chip ghost'}, LANGUAGES[lang(a.model)] || lang(a.model)));
        const nameIn = h('input', {maxLength: 40, value: a.name}); nameIn.oninput = () => { a.name = nameIn.value; title.firstChild.textContent = a.name || 'New personality'; markDirty(); };
        const voiceIn = voiceSelect(a.model);
        voiceIn.onchange = () => {
          const before = lang(a.model); a.model = voiceIn.value;
          const from = data.default_lines[before], to = data.default_lines[lang(a.model)];
          // Default lines follow the voice's language; lines you wrote stay.
          if (from && to && JSON.stringify(a.lines) === JSON.stringify(from)) a.lines = [...to];
          renderPeople(); markDirty();
        };
        const styleIn = h('textarea', {maxLength: 280, rows: 2}); styleIn.value = a.style || ''; styleIn.oninput = () => { a.style = styleIn.value; markDirty(); };
        const lines = [0, 1, 2, 3].map(i => { const input = h('input', {maxLength: 120, value: a.lines[i] || '', 'aria-label': (a.name || 'New personality') + ' line ' + (i + 1)}); input.oninput = () => { a.lines[i] = input.value; markDirty(); }; return h('label', {class: 'field'}, h('span', 'Line ' + (i + 1)), input); });
        const hear = h('button', {class: 'sm', type: 'button', 'aria-label': 'Listen to ' + (a.name || 'this personality')}, '▶ Listen');
        const duty = h('button', {class: 'sm quiet', type: 'button', disabled: !a.id || a.id === draft.on_duty, title: a.id ? '' : 'Save first'}, 'Put on duty');
        const remove = h('button', {class: 'sm danger', type: 'button', disabled: draft.announcers.length < 2 || a.id === draft.on_duty}, 'Remove');
        const card = h('article', {class: 'person' + (a.id && a.id === draft.on_duty ? ' duty' : ''), style: {'--who': colour(a.id)}}, title,
          h('div', {class: 'fields'}, h('label', {class: 'field'}, h('span', 'Name'), nameIn), h('label', {class: 'field'}, h('span', 'Voice'), voiceIn)),
          h('label', {class: 'field'}, h('span', 'Style notes'), styleIn), h('div', {class: 'stack tight lines'}, lines), h('div', {class: 'actions'}, hear, duty, remove));
        card.style.setProperty('--who', colour(a.id));
        hear.onclick = async () => {
          hear.disabled = true; say('Voicing ' + (a.name || 'the personality') + '…');
          try { const r = await api('v1/continuity/preview', {announcer: clean(a)}, {timeout: 60000}); card.querySelector('.script')?.remove(); card.append(script(r.lines)); await listen(r.audio, card); }
          catch (e) { say(e.message, true); } finally { hear.disabled = false; }
        };
        duty.onclick = () => { draft.on_duty = a.id; render(); markDirty(); };
        remove.onclick = () => { draft.announcers.splice(index, 1); draft.roster = draft.roster.map(w => w === a.id ? null : w); render(); markDirty(); };
        holder.append(card);
      });
    }
    function renderRecent() {
      const list = $('recent');
      VV.fill(list, data.recent.length ? data.recent.map(r => h('li', {class: 'stack tight'}, h('strong', r.name + ' · ' + fmt.when(r.aired_at)), script(r.lines))) : h('li', {class: 'hint'}, 'None aired since the web service started.'));
    }
    function render() { renderAir(); renderRoster(); renderPeople(); renderRecent(); markDirty(); }
    async function save(settings, note) { data = await api('v1/continuity', settings, {timeout: 60000}); draft = structuredClone(data.settings); render(); say(note); }
    $('save').onclick = async () => { $('save').disabled = true; try { await save({...draft, announcers: draft.announcers.map(clean)}, 'Continuity saved.'); } catch (e) { say(e.message, true); markDirty(); } };
    // The switch saves only itself; other edits stay unsaved.
    $('enabled').onchange = async () => {
      const pending = dirty() ? draft : null;
      try {
        await save({...data.settings, enabled: $('enabled').checked}, $('enabled').checked ? 'Announcements on: the next break will be announced.' : 'Announcements off: the plain station ID plays.');
        if (pending) { draft = {...pending, enabled: data.settings.enabled}; render(); }
      } catch (e) { say(e.message, true); $('enabled').checked = !$('enabled').checked; }
    };
    host.querySelectorAll('[name=cp-duty]').forEach(r => { r.onchange = () => { draft.duty = r.value; renderRoster(); markDirty(); }; });
    $('on-duty').onchange = () => { draft.on_duty = $('on-duty').value; render(); markDirty(); };
    $('add').onclick = () => { draft.announcers.push({id: '', name: '', model: 'aura-2-orpheus-en', style: '', lines: [...data.default_lines.en]}); renderPeople(); markDirty(); $('people').lastElementChild.querySelector('input').focus(); };
    async function refresh() {
      const fresh = await api('v1/continuity', undefined, {timeout: 60000}), keep = draft && data && dirty() ? draft : null;
      data = fresh; draft = keep || structuredClone(data.settings); render();
    }
    const timer = setInterval(() => { if (!document.hidden && host.offsetParent && !painting) refresh().catch(() => {}); }, 15000);
    window.addEventListener('beforeunload', e => { if (draft && data && dirty()) e.preventDefault(); });
    return {refresh, dirty: () => !!(draft && data && dirty()), stop: () => clearInterval(timer)};
  }
  return {mount};
})();
