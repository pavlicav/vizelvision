// Station promos: VizelVision's own bumpers in the breaks ad mute takes off air.
//   PromosPanel.mount(host) → {refresh, stop}
//   PromosPanel.preview(promo, values): a promo playing in a dialog, its live text drawn as master would (also on Ads › Idents)
//   PromosPanel.blob(path, fresh) → a blob URL of a file the API serves (it needs the API key)
window.PromosPanel = (() => {
  'use strict';
  const {h, api, fmt, toast} = VV;
  const STYLE = `
.pp .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.pp .promo{border:1px solid var(--line);background:var(--well);border-radius:var(--r-lg);overflow:hidden;display:grid;align-content:start}
.pp .promo.off{opacity:.6}.pp .promo.onair{box-shadow:0 0 0 2px var(--pgm,#e5484d)}.pp .promo.cued{box-shadow:0 0 0 1px var(--touch)}
.pp .still{position:relative;aspect-ratio:16/9;background:#000;border:0;padding:0;cursor:pointer;display:block;width:100%}
.pp .still img{width:100%;height:100%;object-fit:cover;display:block}
.pp .still .play{position:absolute;inset:auto 10px 10px auto;background:rgba(0,0,0,.6);color:#fff;border-radius:999px;padding:4px 12px;font:600 12px/1.4 var(--mono)}
.pp .promo .text{padding:12px 14px;display:grid;gap:8px}
.pp .promo h3{font-size:16px;margin:0;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.pp .promo p{margin:0}.pp .why{color:var(--warn)}
.pp .live-row{display:flex;gap:6px;flex-wrap:wrap}
.pp table{width:100%;border-collapse:collapse;font-size:13px}.pp td{padding:5px 6px;border-top:1px solid var(--line)}
.pp td.when{white-space:nowrap;color:var(--muted)}.pp td.num{text-align:right;font-variant-numeric:tabular-nums}
dialog.promo-preview{width:min(960px,94vw)}
dialog.promo-preview .stage{position:relative;aspect-ratio:16/9;background:#000;border-radius:var(--r);overflow:hidden}
dialog.promo-preview video{width:100%;height:100%;display:block}
dialog.promo-preview .stage img{position:absolute;pointer-events:none;transform-origin:center}`;
  const W = 1280, H = 720;

  // Files need the API key: fetched as blobs. Stills change with the live text, so they are fetched again on a refresh.
  const blobs = new Map();
  function blob(path, fresh) {
    if (fresh || !blobs.has(path)) {
      const old = blobs.get(path);
      blobs.set(path, api(path, undefined, {raw: true, timeout: 120000}).then(r => r.ok ? r.blob() : null)
        .then(b => b && URL.createObjectURL(b)).catch(() => null));
      if (old) old.then(url => url && setTimeout(() => URL.revokeObjectURL(url), 30000));
    }
    return blobs.get(path);
  }

  // Where master draws a live text at promo time t (roku_stream/promo_overlay.py place()).
  const backOut = (x, s = 1.7) => { x -= 1; return 1 + x * x * ((s + 1) * x + s); };
  function place(spec, t) {
    if (t < spec.from || t >= spec.to) return null;
    const [x, y, w, hh] = spec.box;
    let sx = 1, sy = 1, alpha = 1;
    const p = spec.enter.seconds > 0 ? (t - spec.from) / spec.enter.seconds : 1;
    if (p < 1) {
      if (spec.enter.kind === 'fade') alpha = p * p * (3 - 2 * p);
      else if (spec.enter.kind === 'flip') sy = Math.max(.02, backOut(p));
      else if (spec.enter.kind === 'pop') { sx = sy = .55 + .45 * backOut(p, 2.4); alpha = Math.min(1, p * 3); }
    }
    const q = spec.exit.seconds > 0 ? (spec.to - t) / spec.exit.seconds : 1;
    if (q < 1 && spec.exit.kind === 'fade') alpha *= Math.max(0, q);
    return {x, y, w, h: hh, sx, sy, alpha};
  }

  const style = () => { if (!document.getElementById('pp-style')) document.head.append(h('style', {id: 'pp-style'}, STYLE)); };

  // values: GET /v1/promos' live values, for the programme's voiced 'only-on'.
  function preview(promo, values) {
    style();
    const variant = promo.id === 'only-on' && values?.programme?.variants?.[promo.id];
    const file = variant || promo.file;
    const video = h('video', {controls: true, playsinline: true, preload: 'auto'});
    const stage = h('div', {class: 'stage'}, video);
    const layers = promo.overlays.map((spec, i) => {
      const img = h('img', {alt: '', hidden: true});
      blob(`v1/promos/overlay/${promo.id}/${i}.png`, true).then(url => { if (url) img.src = url; });
      stage.append(img);
      return [spec, img];
    });
    const close = h('button', {class: 'quiet', type: 'button'}, 'Close');
    const note = h('p', {class: 'tiny muted'}, promo.overlays.length ? 'The live text is drawn over the picture as master draws it, with today\'s values' +
      (variant ? '; the voice says this programme\'s name.' : '.') : 'As it airs.');
    const dialog = h('dialog', {class: 'preview promo-preview', 'aria-label': 'Preview ' + promo.name}, h('div', {class: 'head'}, h('h2', null, promo.name)),
      h('div', {class: 'body stack tight'}, stage, note), h('div', {class: 'foot'}, close));
    let frame = 0;
    const tick = () => {
      const t = video.currentTime, sw = stage.clientWidth / W, sh = stage.clientHeight / H;
      for (const [spec, img] of layers) {
        const at = place(spec, t);
        img.hidden = !at;
        if (!at) continue;
        Object.assign(img.style, {left: at.x * sw + 'px', top: at.y * sh + 'px', width: at.w * sw + 'px', height: at.h * sh + 'px',
          opacity: at.alpha, transform: `scale(${at.sx},${at.sy})`});
      }
      frame = requestAnimationFrame(tick);
    };
    close.onclick = () => dialog.close();
    dialog.addEventListener('close', () => { cancelAnimationFrame(frame); video.pause(); dialog.remove(); });
    document.body.append(dialog); dialog.showModal();
    blob('v1/promos/file/' + file, false).then(url => {
      if (!url) { note.textContent = 'Could not load it.'; return; }
      video.src = url; video.play().catch(() => {}); tick();
    });
  }

  function mount(host) {
    style();
    host.classList.add('pp', 'stack');
    host.innerHTML = `
<div class="cols-2">
 <section class="panel" aria-label="Station promo settings"><div class="head"><span class="lamp" data-id="lamp"></span><h2>Station promos</h2></div><div class="body stack tight">
  <label class="switch"><input type="checkbox" data-id="enabled"><span>Play promos in ad breaks</span></label>
  <label class="field"><span>How often</span><select data-id="every"></select></label>
  <label class="switch"><input type="checkbox" data-id="fill"><span>Fill in when My ads runs out<small class="muted" style="display:block">Promos stand in before the break card, each once a break</small></span></label>
  <p class="note warn" data-id="warning" role="status"></p>
  <p class="hint tiny">Promos play in the breaks ad mute takes off air (its mode On), in My ads' place. With <b>Every break</b>, each break opens with one; otherwise, once the interval has passed since the last one, the next break opens with a promo. One cut short by the programme's return before half of it airs doesn't count, so the next break tries again. Time and temperature and the programme's name are drawn live by master as they air.</p></div></section>
 <section class="panel" aria-label="Promos on master"><div class="head"><h2>On master</h2></div><div class="body"><dl class="kv" data-id="master"></dl></div></section>
</div>
<section class="panel" aria-label="The promos"><div class="head"><h2>The promos</h2><div class="end"><span class="chip" data-id="count"></span></div></div>
 <div class="body stack tight"><p class="hint tiny">Built by <code>ident/promos/build.py</code> from the sonic identity, at the station's −20 LUFS. Click a picture to preview it with its live text as it would read now.</p>
  <div class="grid" data-id="grid"></div><p class="note warn" data-id="problems"></p></div></section>
<section class="panel" aria-label="Recent promos"><div class="head"><h2>Recently on air</h2></div><div class="body">
 <table><tbody data-id="recent"></tbody></table><p class="tiny muted" data-id="recent-empty">No promo has aired yet.</p></div></section>`;
    const $ = id => host.querySelector(`[data-id="${id}"]`);
    let view = null, drawn = null, busy = false;

    async function save(path, body, done) {
      busy = true;
      try { view = await api(path, body); render(true); if (done) toast(done, {ok: true}); }
      catch (e) { toast(e.message, {error: true}); render(true); }
      finally { busy = false; }
    }
    $('enabled').onchange = () => save('v1/promos', {enabled: $('enabled').checked},
      $('enabled').checked ? 'Promos are on: the next break they may play in, they will.' : 'Promos are off.');
    $('fill').onchange = () => save('v1/promos', {fill: $('fill').checked}, 'Saved.');
    $('every').onchange = () => save('v1/promos', {every: Number($('every').value)}, 'Saved.');

    function masterRows() {
      const m = view.master || {}, p = m.promos || {}, s = view.settings, byId = Object.fromEntries(view.promos.map(x => [x.id, x]));
      const values = view.values || {}, temp = values.temperature, prog = values.programme;
      const rows = [];
      if (m.error) rows.push(['Master', m.error]);
      if (m.promo) rows.push(['On air now', `${m.promo.name} · ${fmt.dur(m.promo.position || 0)} of ${fmt.dur(m.promo.duration)}`]);
      rows.push(['Cued next', p.cued ? (byId[p.cued]?.name || p.cued) : s.enabled ? 'Nothing yet' : '—']);
      rows.push(['Last promo', view.last ? `${fmt.clock(view.last)} (${fmt.rel(view.last)})` : 'None yet']);
      rows.push(['Next one', !s.enabled ? 'Promos are off' : s.every === 0 ? 'Every break opens with one'
        : view.due ? 'Due: it opens the next break' : 'At the first break after ' + fmt.clock(view.next_due)]);
      rows.push(['Temperature', temp ? `${temp.f}°F · ${temp.place || 'unknown station'} · read ${fmt.clock(temp.observed_at)}` : (view.errors.temperature || 'Not needed')]);
      rows.push(['Programme', prog ? h('span', null, prog.title, ' ', prog.variants && prog.variants['only-on'] ? h('span', {class: 'chip pvw'}, 'voiced') :
        h('span', {class: 'chip warn', title: view.errors.voice || 'Voicing it…'}, 'own line')) : (view.errors.programme || 'None on air with a name')]);
      return rows;
    }

    function card(promo) {
      const m = view.master || {}, onAir = m.promo && m.promo.id === promo.id, cued = (m.promos || {}).cued === promo.id;
      const img = h('img', {alt: promo.name + ' — a still', loading: 'lazy'});
      blob(`v1/promos/still/${promo.id}.png`, false).then(url => { if (url) img.src = url; });
      const toggle = h('input', {type: 'checkbox', checked: promo.enabled, 'aria-label': 'Play ' + promo.name});
      toggle.onchange = () => save('v1/promos/promo/' + promo.id, {enabled: toggle.checked}, `${promo.name} ${toggle.checked ? 'is in' : 'sits out'}.`);
      const needs = promo.needs.map(n => h('span', {class: 'chip'}, {temperature: 'live time & temp', programme: 'live programme name'}[n] || n));
      return h('article', {class: 'promo' + (promo.enabled ? '' : ' off') + (onAir ? ' onair' : cued ? ' cued' : '')},
        h('button', {class: 'still', type: 'button', title: 'Preview ' + promo.name, onclick: () => preview(promo, view.values)}, img, h('span', {class: 'play'}, '▶ ' + fmt.dur(promo.duration))),
        h('div', {class: 'text'},
          h('h3', null, promo.name, h('span', {class: 'chip'}, promo.kind === 'ident' ? 'ident' : 'promo'),
            onAir ? h('span', {class: 'chip solid pgm'}, 'on air') : cued ? h('span', {class: 'chip pvw'}, 'cued') : null),
          h('p', {class: 'small muted'}, promo.description),
          needs.length ? h('div', {class: 'live-row'}, ...needs) : null,
          !promo.present ? h('p', {class: 'small why'}, 'Not built yet') : promo.why ? h('p', {class: 'small why'}, 'Sits out now: ' + promo.why) : null,
          h('p', {class: 'tiny muted'}, `Today ${promo.played.day} · this week ${promo.played.week}` + (promo.played.last ? ` · last ${fmt.rel(promo.played.last)}` : '')),
          h('label', {class: 'switch'}, toggle, h('span', null, 'In the rotation'))));
    }

    function render(force) {
      if (!view) return;
      const s = view.settings, m = view.master || {};
      if (!busy) {
        $('enabled').checked = s.enabled; $('fill').checked = s.fill;
        if ($('every').options.length !== view.every_choices.length + (view.every_choices.includes(s.every) ? 0 : 1))
          VV.fill($('every'), ...[...new Set([...view.every_choices, s.every])].sort((a, b) => a - b)
            .map(n => new Option(n === 0 ? 'Every break' : `At least one every ${n} minutes`, n)));
        $('every').value = String(s.every);
      }
      $('lamp').className = 'lamp' + (m.promo ? ' pgm' : (m.promos || {}).active ? ' pvw' : s.enabled ? ' warn' : '');
      const mode = view.admute_mode;
      $('warning').textContent = !s.enabled ? '' : m.error ? m.error : !(m.promos || {}).active
        ? 'Not playing now: promos play only while ad mute is On' + (mode && mode !== 'on' ? ` (it is ${mode === 'off' ? 'Off' : 'in Shadow'}).` : '.') : '';
      VV.fill($('master'), ...masterRows().flatMap(([k, v]) => [h('dt', null, k), h('dd', null, v)]));
      $('count').textContent = view.promos.length + (view.promos.length === 1 ? ' promo' : ' promos');
      const problems = Object.entries(view.problems || {});
      $('problems').textContent = problems.length ? 'Cannot read: ' + problems.map(([k, v]) => `${k} (${v})`).join('; ') : '';
      const key = JSON.stringify([view.promos.map(p => [p.id, p.enabled, p.ready, p.why, p.played, p.built_at]), m.promo && m.promo.id, (m.promos || {}).cued]);
      if (force || key !== drawn) { drawn = key; VV.fill($('grid'), ...view.promos.map(card)); }
      const names = Object.fromEntries(view.promos.map(p => [p.id, p.name]));
      const rows = view.recent.slice(0, 25).map(p => h('tr', null, h('td', {class: 'when'}, fmt.when(p.at)), h('td', null, names[p.id] || p.name || p.id),
        h('td', {class: 'num'}, fmt.dur(p.seconds) + ' of ' + fmt.dur(p.length)),
        h('td', {class: 'small muted'}, p.error ? h('span', {class: 'chip pgm', title: p.error}, 'failed') : p.complete ? 'complete' : 'cut short' + (p.counted ? '' : ' · didn\'t count'))));
      VV.fill($('recent'), ...rows);
      $('recent-empty').hidden = rows.length > 0;
    }

    const stopWatch = VV.watch('v1/promos', 5000, (value, w) => {
      if (w.error) { $('warning').textContent = w.error.message || String(w.error); return; }
      if (busy) return;
      view = value; render();
    });
    return {refresh: async () => { view = await api('v1/promos'); render(true); }, stop: stopWatch};
  }
  return {mount, preview, blob};
})();
