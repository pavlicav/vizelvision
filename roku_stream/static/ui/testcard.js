window.TestCard = (() => {
  const defaults={master:{caption:'VIZELVISION MASTER OFF-AIR',lines:['NO PROGRAM LIVE']},'tv-thing':{caption:'TV-THING OFF',lines:['NO PROGRAM LIVE']},roku:{caption:'ROKU OFF',lines:['NO PROGRAM LIVE']}};
  let cards=defaults;
  function kind(source){return source.startsWith('tv-thing')?'tv-thing':source==='master'?'master':'roku';}
  function update(node,card){node.querySelector('strong').textContent=card.caption;node.querySelector('span').textContent=card.lines.join('\n');node.setAttribute('aria-label',[card.caption,...card.lines].join('. '));}
  function create(source){const node=document.createElement('div');node.className='test-card';node.dataset.card=kind(source);node.setAttribute('role','img');const copy=document.createElement('div');copy.className='test-card-copy';copy.append(document.createElement('strong'),document.createElement('span'));node.append(copy);update(node,cards[node.dataset.card]);return node;}
  function set(data){cards=data;document.querySelectorAll('.test-card').forEach(node=>update(node,cards[node.dataset.card]));}
  return {create,set,update};
})();
