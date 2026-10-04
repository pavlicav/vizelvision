(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const storageKey = 'vv-calibration-cycle:' + location.pathname;
  let key = VV.key || '', busy = false, unauthorized = false, pollTimer, lastReceipt = 0;
  let data = null, stableSince = null, previousSignal = '', previousDevice = '', failed = false;
  let cycle = readCycle();
  const history = [];
  function restoreDuration() {
    if (Number.isInteger(cycle?.seconds) && cycle.seconds >= 10 && cycle.seconds <= 600) $('settle-seconds').value = cycle.seconds;
  }
  restoreDuration();

  function readCycle() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey));
      if (Number.isFinite(value?.until) && Number.isFinite(value?.started) && value.until >= value.started) return value;
    } catch {}
    return null;
  }
  function saveCycle() {
    try { localStorage.setItem(storageKey, JSON.stringify(cycle)); } catch {}
  }
  function log(message) {
    history.unshift({at: new Date(), message});
    history.splice(40);
    $('history').replaceChildren(...history.map(entry => {
      const li = document.createElement('li'), time = document.createElement('time'), text = document.createElement('span');
      time.dateTime = entry.at.toISOString(); time.textContent = entry.at.toLocaleTimeString();
      text.textContent = entry.message; li.append(time, text); return li;
    }));
  }
  function renderClock() {
    const now = Date.now(), waiting = cycle && now < cycle.until;
    const fresh = !!lastReceipt && now - lastReceipt < 4000 && !failed;
    if (!fresh) stableSince = null;
    $('start-cycle').disabled = !!waiting;
    $('settle-seconds').disabled = !!waiting;
    $('extend-cycle').hidden = !waiting;
    $('countdown').textContent = waiting ? Math.ceil((cycle.until - now) / 1000) + ' s · let it run'
      : cycle ? 'Wait complete' : 'Ready to watch';
    const stableSeconds = stableSince === null ? 0 : Math.floor((performance.now() - stableSince) / 1000);
    const confirmed = fresh && data?.target.matches && stableSeconds >= 10 && !waiting;
    $('target-status').textContent = waiting ? 'Resolution cycle in progress'
      : confirmed ? '720p60 confirmed · stable for ' + stableSeconds + ' s'
      : fresh && data?.target.matches ? '720p60 detected · verifying stability (' + stableSeconds + '/10 s)'
      : 'Target not confirmed';
    $('signal-panel').dataset.tone = confirmed ? 'good' : !fresh || data?.signal.state === 'unavailable' ? 'bad' : 'waiting';
    $('cycle-message').textContent = waiting ? 'Let the resolution cycle finish. A temporary signal match does not finish the watch.'
      : cycle && confirmed ? '720p60 is stable. The watch is complete; live monitoring continues.'
      : cycle ? 'The wait is complete. Keep watching until the input holds 720p60 for 10 seconds.'
      : 'Live monitoring stays on before, during, and after the timer.';
    if (lastReceipt) $('freshness').textContent = fresh ? 'Updated ' + ((now - lastReceipt) / 1000).toFixed(1) + ' s ago'
      : 'Reading stale · waiting for a fresh response';
    if (!fresh && lastReceipt && !failed) {
      $('input-resolution').textContent = 'Reading stale';
      $('signal-detail').textContent = 'The last signal reading has expired. Reconnecting…';
    }
  }
  function render(result) {
    const now = Date.now();
    if (now - lastReceipt >= 4000) stableSince = null;
    data = result; failed = false; lastReceipt = now;
    const waiting = cycle && now < cycle.until;
    if (!result.target.matches || waiting) stableSince = null;
    else if (stableSince === null) stableSince = performance.now();
    const signal = result.signal, device = result.device, capture = result.capture;
    $('input-resolution').textContent = signal.state === 'locked' ? signal.width + ' × ' + signal.height : signal.label;
    $('signal-detail').textContent = signal.state === 'locked'
      ? signal.scan + ' · ' + (signal.rate == null ? 'Frame rate unknown' : signal.rate + (signal.scan === 'interlaced' ? ' fields/s' : ' frames/s'))
      : signal.error || 'Waiting for a detected input signal. Monitoring continues automatically.';
    $('device-status').textContent = device.label;
    $('device-path').textContent = device.path;
    $('capture-input').textContent = result.source_name + (result.input_index == null ? '' : ' · input ' + result.input_index);
    $('usb-status').textContent = device.usb ? device.usb.product + ' · USB ' + device.usb.port + ' · driver: ' + (device.usb.drivers.join(', ') || 'not attached')
      : device.state === 'ready' ? 'Capture path available; USB identity not reported' : 'Configured USB unit not found';
    $('decoder-status').textContent = !capture.capture ? 'Not running' : capture.capture.error || 'Running · latest frame ' + (capture.capture.frame_age_seconds == null ? 'pending' : capture.capture.frame_age_seconds.toFixed(1) + ' s ago');
    const help = {
      driver_missing: 'The Hauppauge is on USB, but Linux has not attached its capture driver. Restore the capture connection before adjusting resolution.',
      node_missing: 'USB and a driver are present, but the configured capture path is missing. Check the device path and udev device links.',
      missing: 'Check the Hauppauge power supply and USB cable. The page will detect it when it returns.',
      permission_denied: 'The service cannot read and write this device. Check its video-group membership and device permissions.',
      ready: 'The device is accessible. Use the live timing readout above to verify the incoming signal.',
    };
    $('device-help').textContent = help[device.state] || device.error || device.label;
    $('diagnostics').textContent = JSON.stringify(result, null, 2);
    const signature = JSON.stringify([signal.state, signal.width, signal.height, signal.scan, signal.rate]);
    if (signature !== previousSignal) { log(signal.label); previousSignal = signature; }
    if (device.state !== previousDevice) { log(device.label); previousDevice = device.state; }
    renderClock();
  }
  async function poll() {
    if (busy || unauthorized) return;
    clearTimeout(pollTimer); busy = true;
    try {
      const response = await fetch('v1/roku/calibration', {cache: 'no-store', headers: key ? {'X-API-Key': key} : {}, signal: AbortSignal.timeout(3500)});
      if (response.status === 401) {
        unauthorized = true; $('signin').hidden = false; $('workspace').hidden = true;
        $('auth-error').textContent = key ? 'API key not accepted' : ''; stableSince = null; return;
      }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'HTTP ' + response.status);
      $('signin').hidden = true; $('workspace').hidden = false;
      if (failed) log('Calibration connection restored');
      render(result);
    } catch (error) {
      if (!failed) log('Calibration connection lost · ' + error.message);
      failed = true; stableSince = null;
      $('input-resolution').textContent = 'Input reading unavailable';
      $('signal-detail').textContent = error.message + ' · retrying automatically';
      $('device-status').textContent = 'Connection status unavailable';
      $('usb-status').textContent = 'Awaiting a fresh reading';
      $('decoder-status').textContent = 'Awaiting a fresh reading';
      $('device-help').textContent = 'The server could not provide a current reading. USB and capture status are unverified.';
      renderClock();
    } finally {
      busy = false;
      if (!unauthorized) pollTimer = setTimeout(poll, document.hidden ? 2000 : 500);
    }
  }
  $('start-cycle').addEventListener('click', () => {
    const seconds = Number($('settle-seconds').value);
    if (!Number.isInteger(seconds) || seconds < 10 || seconds > 600) { $('settle-seconds').reportValidity(); return; }
    cycle = {started: Date.now(), until: Date.now() + seconds * 1000, seconds};
    saveCycle(); stableSince = null; log('Resolution button press recorded · watch for at least ' + seconds + ' seconds'); renderClock(); poll();
  });
  $('extend-cycle').addEventListener('click', () => {
    if (!cycle) return;
    cycle.until = Math.max(Date.now(), cycle.until) + 30000;
    saveCycle(); stableSince = null; log('Resolution watch extended by 30 seconds'); renderClock();
  });
  $('connect').addEventListener('click', () => {
    key = $('api-key').value.trim(); unauthorized = false; failed = true; stableSince = null;
    VV.setKey(key); poll();
  });
  $('api-key').addEventListener('keydown', event => { if (event.key === 'Enter') $('connect').click(); });
  window.addEventListener('storage', event => { if (event.key === storageKey) { cycle = readCycle(); restoreDuration(); stableSince = null; renderClock(); } });
  document.addEventListener('visibilitychange', () => { stableSince = null; if (!document.hidden) poll(); });
  setInterval(renderClock, 200);
  renderClock(); poll();
})();
