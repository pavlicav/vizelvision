// The crawl bar as master draws it: same colours (crawl_render.PALETTE), same wording, and
// 120 pixels a second at 720p, scaled to the box it is drawn in.
//   CrawlBar.draw(screen, {label, flag?, style, position?, items: [{tag, heading, text}]} | null)
window.CrawlBar = (() => {
  'use strict';
  const {h} = VV;
  // band, text, heading, label box (and tags), label text
  const PALETTE = {
    warning: ['#9e0d12', '#fff', '#ffd94d', '#fff', '#9e0d12'], watch: ['#a84200', '#fff', '#ffe08a', '#fff', '#a84200'],
    advisory: ['#f0bf00', '#0f0f0f', '#730d0d', '#0f0f0f', '#f0bf00'], test: ['#2e4052', '#fff', '#9ed4ff', '#fff', '#2e4052'],
    station: ['#0a1730', '#fff', '#64dce4', '#64dce4', '#0a1730'], new: ['#003d8c', '#fff', '#ffd64d', '#ffd133', '#0a1730']};
  PALETTE.national = PALETTE.urgent = PALETTE.warning; PALETTE.unknown = PALETTE.advisory;
  const SEPARATOR = '  ◆  ';
  function screen({strip = false, label = 'Mimic of master\'s crawl bar'} = {}) {
    return h('div', {class: 'barscreen' + (strip ? ' strip' : ''), role: 'img', 'aria-label': label});
  }
  function draw(node, content) {
    const id = JSON.stringify(content);
    if (node.dataset.key === id) return;
    node.dataset.key = id;
    node.replaceChildren();
    if (!content || !content.items?.length) { node.append(h('div', {class: 'idle'}, 'Bar off')); return; }
    const [band, ink, head, lbg, lfg] = PALETTE[content.style] || PALETTE.station;
    const bar = h('div', {class: 'crawlbar' + (content.position === 'top' ? ' top' : '')}), run = h('div', {class: 'run'});
    Object.entries({'--band': band, '--ink': ink, '--head': head, '--lbg': lbg, '--lfg': lfg}).forEach(([k, v]) => bar.style.setProperty(k, v));
    content.items.forEach((item, i) => {
      if (item.tag) run.append(h('i', item.tag));
      if (item.heading) run.append(h('b', item.heading));
      run.append(document.createTextNode(item.text + (i < content.items.length - 1 ? SEPARATOR : '')));
    });
    bar.append(run);
    if (content.label || content.flag) bar.append(h('div', {class: 'boxlabel'}, content.flag ? h('span', {class: 'flag'}, content.flag) : null, content.label || null));
    node.append(bar);
    requestAnimationFrame(() => {
      // From the right edge until the end has left the left edge, at master's speed for this bar's height.
      const width = bar.clientWidth, length = run.scrollWidth, speed = bar.clientHeight / 54 * 120;
      run.style.setProperty('--from', width + 'px'); run.style.setProperty('--to', -length + 'px');
      run.style.setProperty('--rest', (bar.querySelector('.boxlabel')?.offsetWidth || 0) + 'px');
      run.style.animationDuration = Math.max(2, (width + length) / Math.max(speed, 1)) + 's';
    });
  }
  return {screen, draw, PALETTE};
})();
