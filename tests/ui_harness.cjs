// A mocked VizelVision for the browser tests of the web UI (tests/browser_ui_*.cjs).
//
// Pages and their scripts come from roku_stream/static/ui on disk; the API answers from
// tests/fixtures/ui (real responses, trimmed), served under the Apache prefix /vizelvision/.
// Writes are recorded in `posts` and answered by `api` handlers, so a test can say what a
// button sends and what the server says back. The clock is fixed at the fixtures' moment.
//
//   const {open, run} = require('./ui_harness.cjs');
//   run(async browser => { const t = await open(browser, '/crawl', {api: {'POST /v1/crawl/run': () => ({})}}); … });
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const ROOT = path.resolve(__dirname, '..');
const STATIC = path.join(ROOT, 'roku_stream', 'static');
const FIXTURES = path.join(__dirname, 'fixtures', 'ui');
const PAGES = new Set(['/air', '/sources', '/schedule', '/crawl', '/presentation', '/ads', '/engineering', '/sonic']);
const NOW = new Date('2026-10-02T02:16:40Z');
const TYPES = {js: 'text/javascript', css: 'text/css', html: 'text/html', woff2: 'font/woff2', webp: 'image/webp', mp3: 'audio/mpeg'};

function fixtures() {
  const all = {};
  for (const file of fs.readdirSync(FIXTURES)) if (file.endsWith('.json')) all[file.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(FIXTURES, file)));
  return all;
}

function reads(F) {
  return [
    [/^\/v1\/master$/, () => F.master], [/^\/v1\/queue$/, () => F.queue], [/^\/v1\/playback$/, () => F.playback],
    [/^\/v1\/programming$/, () => F.programming], [/^\/v1\/sources$/, () => F.sources], [/^\/v1\/networks$/, () => F.networks],
    [/^\/v1\/sources\/([^/]+)\/programs$/, m => F.programs[decodeURIComponent(m[1])] || {channels: [], items: []}],
    [/^\/v1\/crawl$/, () => F.crawl], [/^\/v1\/crawl\/alerts$/, () => F.alerts], [/^\/v1\/crawl\/bus-routes$/, () => ({routes: [{id: 'D60', name: '14TH ST - D60'}, {id: 'D6X', name: 'SIBLEY - D6X'}, {id: 'X2', name: 'BENNING RD-H ST - X2'}]})],
    [/^\/v1\/admute$/, () => F.admute], [/^\/v1\/admute\/recordings$/, () => F.admute_recordings],
    [/^\/v1\/admute\/known$/, () => F.admute_known], [/^\/v1\/my-ads$/, () => F.my_ads],
    [/^\/v1\/captions$/, () => F.captions],
    [/^\/v1\/promos$/, () => F.promos],
    [/^\/v1\/continuity$/, () => F.continuity], [/^\/v1\/production$/, () => F.production], [/^\/v1\/production\/monitor$/, () => F.monitor],
    [/^\/v1\/sports\/week$/, () => F.nfl], [/^\/v1\/sports\/upcoming$/, () => F.mlb], [/^\/v1\/sports\/teams$/, () => F.teams_nhl],
    [/^\/v1\/sports\/games$/, () => ({games: F.nfl.games.slice(0, 3)})],
    // The source Roku is TV Thing's Roku lane: its status and navigation, as vizelVision relays them.
    [/^\/v1\/operation$/, () => F.operation], [/^\/v1\/roku\/status$/, () => F.roku_status],
    [/^\/v1\/master\/end-options$/, () => ({games: [], program: null, warnings: []})],
    [/^\/v1\/channels$/, () => ({channels: []})], [/^\/health$/, () => ({ready: true})],
  ];
}

async function open(browser, page, {width = 1280, height = 900, api = {}, storage = {}, edit} = {}) {
  const F = fixtures();
  if (edit) edit(F);
  const ctx = await browser.newContext({viewport: {width, height}});
  await ctx.addInitScript(values => { for (const [k, v] of Object.entries(values)) localStorage.setItem('vv.' + k, JSON.stringify(v)); }, storage);
  const p = await ctx.newPage();
  await p.clock.setFixedTime(NOW);
  const errors = [], posts = [], unknown = [], frames = [];
  p.on('pageerror', e => errors.push(e.message));
  const table = reads(F);
  await p.route('http://vv.test/**', async route => {
    const request = route.request(), url = new URL(request.url());
    const where = url.pathname.replace(/^\/vizelvision/, '') || '/';
    if (PAGES.has(where)) return route.fulfill({contentType: 'text/html', body: fs.readFileSync(path.join(STATIC, 'ui', where.slice(1) + '.html'))});
    if (where.startsWith('/static/')) {
      const file = path.join(STATIC, where.slice('/static/'.length));
      if (!file.startsWith(STATIC) || !fs.existsSync(file)) return route.fulfill({status: 404, body: 'missing'});
      return route.fulfill({contentType: TYPES[file.split('.').pop()] || 'application/octet-stream', body: fs.readFileSync(file)});
    }
    const method = request.method(), key = method + ' ' + where;
    if (method !== 'GET') {
      // An upload's body is the file itself: recorded by its size.
      let body = null;
      try { body = request.postData() ? JSON.parse(request.postData()) : null; } catch { body = {upload: request.postDataBuffer()?.length ?? 0}; }
      posts.push({method, path: where, body});
      const handler = api[key] || Object.entries(api).find(([k]) => k.endsWith('*') && key.startsWith(k.slice(0, -1)))?.[1];
      const result = handler ? await handler(body, F, where) : {};
      return route.fulfill(result && typeof result.status === 'number' ? {status: result.status, json: result.json ?? {}} : {json: result ?? {}});
    }
    if (api[key]) { const result = await api[key](url, F); return route.fulfill(result && typeof result.status === 'number' ? {status: result.status, json: result.json ?? {}} : {json: result}); }
    for (const [pattern, answer] of table) { const m = where.match(pattern); if (m) return route.fulfill({json: answer(m)}); }
    // The ad-mute detector's pictures: one stand-in, and which seconds the page asked for.
    if (/^\/v1\/admute\/frame\/[0-9a-f]{32}\/\d+\.jpg$/.test(where)) {
      frames.push(where);
      return route.fulfill({contentType: 'image/jpeg', body: fs.readFileSync(path.join(FIXTURES, 'frame.jpg'))});
    }
    // My ads' files: pictures and the card are the stand-in picture; an ad itself is a few bytes.
    if (/^\/v1\/my-ads\/file\/[0-9a-f]{12}$/.test(where)) return route.fulfill({contentType: 'video/mp4', body: Buffer.from('not really a video')});
    if (/^\/v1\/my-ads\/file\/[0-9a-z-]+\.(jpg|png)$/.test(where)) {
      frames.push(where);
      return route.fulfill({contentType: 'image/jpeg', body: fs.readFileSync(path.join(FIXTURES, 'frame.jpg'))});
    }
    // Station promos' stills, live texts and videos: the stand-in picture (a video does not play here).
    if (/^\/v1\/promos\/(still|overlay|file)\//.test(where)) {
      frames.push(where);
      return route.fulfill({contentType: 'image/jpeg', body: fs.readFileSync(path.join(FIXTURES, 'frame.jpg'))});
    }
    // The station ID's and the Sports ID's end cards and videos.
    if (/^\/v1\/idents\/(station|sports)-id\.(png|mp4)$/.test(where)) {
      frames.push(where);
      return route.fulfill({contentType: 'image/jpeg', body: fs.readFileSync(path.join(FIXTURES, 'frame.jpg'))});
    }
    if (/^\/v1\/admute\/ad\/\d+-\d\.jpg$/.test(where)) {
      frames.push(where);
      return route.fulfill({contentType: 'image/jpeg', body: fs.readFileSync(path.join(FIXTURES, 'frame.jpg'))});
    }
    // Video (HLS previews, the MJPEG capture) is real but not mocked: no picture in these tests.
    if (/^\/v1\/(inputs\/[0-9a-f]+\/media\/|master\/media\/|preview$|continuity\/audio\/)/.test(where)) return route.fulfill({status: 404, body: ''});
    unknown.push(where);
    return route.fulfill({status: 404, json: {error: {code: 'not_found', message: 'Unknown endpoint ' + where}}});
  });
  await p.goto('http://vv.test/vizelvision' + page);
  return {page: p, ctx, errors, posts, unknown, frames, F};
}

// Runs a test file's body with a browser, reporting failures the way the other browser tests do.
function run(body) {
  const playwright = require(process.argv[2] || 'playwright');
  (async () => {
    const browser = await playwright.chromium.launch();
    try { await body(browser); console.log('ok'); }
    catch (error) { console.error(error); process.exitCode = 1; }
    finally { await browser.close(); }
  })();
}

const overflow = page => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

module.exports = {open, run, fixtures, overflow, assert, NOW, PAGES};
