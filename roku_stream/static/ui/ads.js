// Ads: ad mute, the ad database, my ads and the mix, a tab each (admute.js, ad-database.js, my-ads.js, mix.js).
// Each tab script puts in AdsTabs a function that starts polling what the tab shows and returns
// its stop, so only the tab on screen asks the server for anything.
(() => {
  'use strict';
  const tabs = [...document.querySelectorAll('[role=tab]')];
  let current = null, stop = null;
  function show(name, focus) {
    const tab = tabs.find(t => t.dataset.tab === name) || tabs[0];
    if (focus) tab.focus();
    if (location.hash !== '#' + tab.dataset.tab) history.replaceState(null, '', '#' + tab.dataset.tab);
    if (tab.dataset.tab === current) return;
    current = tab.dataset.tab;
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1;
      document.getElementById('panel-' + t.dataset.tab).hidden = !on;
    }
    VV.store.set('adsTab', current);
    stop?.();
    stop = window.AdsTabs?.[current]?.() || null;
  }
  tabs.forEach((t, i) => {
    t.onclick = () => show(t.dataset.tab);
    t.onkeydown = e => { const step = {ArrowRight: 1, ArrowLeft: -1}[e.key]; if (step) { e.preventDefault(); show(tabs[(i + step + tabs.length) % tabs.length].dataset.tab, true); } };
  });
  // The old pages' addresses land here (/admute is ads#admute, /my-ads is ads#my-ads), and links between tabs are #names.
  addEventListener('hashchange', () => show(location.hash.slice(1)));
  VV.commands.add(tabs.map(t => ({id: 'ads:' + t.dataset.tab, title: 'Ads: ' + t.textContent, group: 'Ads', run: () => show(t.dataset.tab)})));
  show(location.hash.slice(1) || VV.store.get('adsTab', 'admute'));
})();
