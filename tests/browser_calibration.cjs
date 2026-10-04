// Run: node tests/browser_calibration.cjs /path/to/playwright
const {chromium} = require(process.argv[2] || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    let signal = {state: 'unavailable', label: 'Capture device unavailable'}, deviceState = 'driver_missing';
    let offline = false, requireKey = false, calls = 0;
    await page.route('http://vv.test/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      requests.push(request.method());
      if (path === '/vizelvision/calibration') return route.fulfill({contentType: 'text/html', body: fs.readFileSync('roku_stream/static/ui/calibration.html')});
      if (path.includes('/static/')) return route.fulfill({contentType: path.endsWith('.js') ? 'text/javascript' : path.endsWith('.woff2') ? 'font/woff2' : 'text/css', body: fs.readFileSync('roku_stream/static/' + path.split('/static/')[1])});
      if (path.endsWith('/v1/master')) return route.fulfill({json: {state: 'not_configured'}});
      if (path.endsWith('/v1/queue')) return route.fulfill({json: {items: []}});
      assert.equal(path, '/vizelvision/v1/roku/calibration');
      calls++;
      if (requireKey && request.headers()['x-api-key'] !== 'test-key') return route.fulfill({status: 401, json: {error: {message: 'API key required'}}});
      if (offline) return route.fulfill({status: 503, json: {error: {message: 'Service restarting'}}});
      return route.fulfill({json: {
        signal, device: {state: deviceState, label: deviceState === 'ready' ? 'Capture device available' : 'USB detected · capture driver not attached',
          path: '/dev/v4l/by-id/usb-AMBA_Hauppauge_HD_PVR_SERIAL-video-index0', usb: {product: 'Hauppauge HD PVR', port: '2-4', drivers: deviceState === 'ready' ? ['hdpvr'] : []}},
        target: {matches: signal.state === 'locked' && signal.width === 1280 && signal.scan === 'progressive' && [59.94, 60].includes(signal.rate)},
        source_name: 'Hauppauge · Component', input_index: 0, capture: {capture: null},
      }});
    });
    await page.goto('http://vv.test/vizelvision/calibration');
    await page.waitForFunction(() => document.querySelector('#device-status').textContent.includes('driver not attached'));
    assert.equal(await page.getByRole('link', {name: 'Engineering', exact: true}).getAttribute('aria-current'), 'page');  // Calibration lives under Engineering.
    assert.match(await page.locator('#input-resolution').innerText(), /unavailable/);
    const initial = calls;
    await page.waitForTimeout(1600);
    assert.ok(calls >= initial + 2, 'polls faster than once a second');
    deviceState = 'ready';
    signal = {state: 'locked', width: 1920, height: 1080, scan: 'interlaced', rate: 60, label: '1920 × 1080 · interlaced · 60 fields/s'};
    await page.waitForFunction(() => document.querySelector('#input-resolution').textContent === '1920 × 1080');
    assert.match(await page.locator('#target-status').innerText(), /not confirmed/);
    signal = {state: 'locked', width: 1280, height: 720, scan: 'progressive', rate: null, label: '1280 × 720 · progressive'};
    await page.waitForFunction(() => document.querySelector('#signal-detail').textContent.includes('unknown'));
    assert.match(await page.locator('#target-status').innerText(), /not confirmed/);
    signal = {...signal, rate: 59.94, label: '1280 × 720 · progressive · 59.94 frames/s'};
    await page.waitForFunction(() => document.querySelector('#signal-detail').textContent.includes('59.94'));
    await page.locator('#settle-seconds').fill('10');
    await page.locator('#start-cycle').click();
    assert.equal(await page.locator('#start-cycle').isDisabled(), true);
    await page.waitForTimeout(1000);
    assert.match(await page.locator('#target-status').innerText(), /cycle in progress/);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#start-cycle').disabled);
    assert.match(await page.locator('#countdown').innerText(), /let it run/);
    assert.equal(await page.locator('#settle-seconds').inputValue(), '10', 'watch duration survives reload');
    await page.locator('#extend-cycle').click();
    assert.match(await page.locator('#countdown').innerText(), /3\d s/);
    // Advance the watch deadline; live stability still requires ten seconds of actual polls.
    await page.evaluate(() => {
      const key = 'vv-calibration-cycle:' + location.pathname;
      const value = JSON.parse(localStorage.getItem(key)); value.started -= 60000; value.until = Date.now() - 1;
      localStorage.setItem(key, JSON.stringify(value)); window.dispatchEvent(new StorageEvent('storage', {key}));
    });
    await page.waitForFunction(() => document.querySelector('#target-status').textContent.includes('720p60 confirmed'), null, {timeout: 15000});
    signal = {state: 'no_signal', label: 'No component signal'};
    await page.waitForFunction(() => document.querySelector('#input-resolution').textContent === 'No component signal');
    assert.match(await page.locator('#target-status').innerText(), /not confirmed/);
    offline = true;
    await page.waitForFunction(() => document.querySelector('#input-resolution').textContent === 'Input reading unavailable');
    assert.match(await page.locator('#device-status').innerText(), /unavailable/);
    offline = false;
    await page.waitForFunction(() => document.querySelector('#input-resolution').textContent === 'No component signal');
    requireKey = true;
    await page.reload();
    await page.locator('#signin').waitFor({state: 'visible'});
    assert.equal(await page.locator('#workspace').isVisible(), false);
    await page.locator('#api-key').fill('test-key');
    await page.locator('#api-key').press('Enter');
    await page.locator('#workspace').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'mobile fits');
    assert.ok(requests.every(method => method === 'GET'), 'calibration never mutates hardware');
    assert.deepEqual(errors, []);
    await page.screenshot({path: '/tmp/vizelvision-calibration-mobile.png', fullPage: true});
    console.log('Calibration browser checks passed: fast updates, USB/driver failure, wrong/unknown format, settling, reload, extension, stable 720p60, loss, recovery, auth, prefix, mobile, read-only.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
