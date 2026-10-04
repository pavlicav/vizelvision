# Persistent master worker and source takes

The master can now publish continuously to one MediaMTX path, prepare a TV-Thing
HLS feed or a verified Roku channel/game, and switch to it through Up next (`/sources`, `/air`). On Air includes a master video
monitor that stays attached across takes and guide refreshes. Digital and analog
use independent tuner leases. The existing Roku controls and queue now use a
navigation guard that removes any prepared/on-air Roku input before navigating.

The [shared Roku A/V contribution](roku-contribution.md) and
[verified Roku master takes](roku-master.md), and
[the persistent mixed-source queue](source-queue.md) are implemented. Publication status and
browser playback status are separate: the monitor reports playing only while its
media clock is advancing, and the page notes HLS buffering delay.

## Candidate setup

Use **`/usr/bin/python3`**, since the host's Conda Python cannot import `gi`.
No additional packages were needed beyond the dependencies installed for the
publication test. The worker requires GStreamer 1.22 or newer.

A private `config.master.json` has been prepared locally from the existing
configuration. It enables TV-Thing and master controls, uses HTTP port **6970**,
and keeps candidate jobs, queue, operations, and the master socket under
`state/master-candidate/`. The original `config.json` and its saved state remain
on disk, but the old Roku service is stopped and disabled. Master control now
provides both the Roku controls and the Sources page.
The candidate config is ignored by Git and has mode 0600.

The three processes are now managed together by **`vizelvision-stack.target`**.
Install or update the stack from the repository root with:

```bash
./deploy/install-master-stack.sh
```

The installer validates dependencies and unit files, installs the user units,
enables startup, stops and disables the old `vizelvision.service` if installed,
restarts the stack, and checks the web API, publisher, and served
HLS playlist. Running it again restarts the stack on fallback. The host already
has lingering enabled for `vivian`, so it starts at boot and continues after logout.
Individual processes restart automatically after unexpected exits. Group stop
and restart propagate to all three processes; shutdown orders the web app and
worker before MediaMTX so the worker can release publication cleanly.

```bash
systemctl --user restart vizelvision-stack.target
systemctl --user stop vizelvision-stack.target
systemctl --user start vizelvision-stack.target
/usr/bin/python3 deploy/check-master-stack.py
journalctl --user -u vizelvision-web -u vizelvision-master -u vizelvision-mediamtx -f
```

Use `systemctl --user disable --now vizelvision-stack.target` to stop it and
disable automatic startup. The target groups `vizelvision-web.service`,
`vizelvision-master.service`, and `vizelvision-mediamtx.service`; inspect those
units when diagnosing a component failure. Keep the original `vizelvision.service`
on port 6969 disabled: running both web apps competes for the Hauppauge device.

Open **`http://viviserv:6970/sources`** from another device on the
local network. If `viviserv` does not resolve on that device, replace it with the
server's LAN IP address. The web service listens on `0.0.0.0:6970` and serves the
page, controls, player assets, and HLS together. MediaMTX's ports remain on loopback.
Use **`http://viviserv:6970/`** for Roku controls and the Hauppauge preview.
The old `http://viviserv/vizelvision/` Apache route still targets the retired
port 6969 and is no longer a working entry point.

LAN access uses `server.host: "0.0.0.0"` in `config.master.json` and requires no
Apache changes or SSH tunnel. Set it back to `127.0.0.1` and restart
`vizelvision-web.service` to limit access to the server itself. For a direct local
check, use `http://127.0.0.1:6970/sources`. Candidate Roku controls remain real
controls; use the Sources page for the new master workflow.

The worker starts on the uploaded test card and a 1 kHz tone (−20 dBFS peak), and does not tune anything until
**Prepare** is requested. Inspect it without opening a device:

```bash
/usr/bin/python3 -m roku_stream --config config.master.json master-status
```

Open **Presentation** (`/presentation`) to edit the master,
TV-Thing, and Roku off-air captions, choose center technical details, add an
engineering note, and select the 1 kHz tone, silence, or Cairo radio. The default captions are
`VIZELVISION MASTER OFF-AIR`, `TV-THING OFF`, and `ROKU OFF`. The packaged
`static/test-pattern.webp` is the uploaded SMPTE card. The tone is a sine wave
at −20 dBFS peak, encoded as 48 kHz stereo AAC with the master video.

Cairo radio plays the local Liquidsoap station from `master.off_air_radio_url`
(default `http://127.0.0.1:1615/cairo.mp3`), set only in the config file. The
worker decodes it in a separate pipeline mixed under the off-air card, so an
unreachable or ended stream only makes off-air audio silent; it retries every
5 seconds and never fails the master publisher. Live sources replace it when taken.
The station is mastered hot (about −15 LUFS, −4 dBTP), so the worker trims it by
`master.off_air_radio_gain_db` (default −9) to sit near the −24 LKFS of broadcast
sources. This leaves headroom for the Roku Express+ output, which distorted at the
original level.

The **Cairo radio show and now playing** detail adds `CLASSICAL SHOW` (the
current show name; names already ending in SHOW are used as-is) and `ARTIST — TITLE` lines to the master card while Cairo radio is the
off-air audio. The worker polls the station API at `master.off_air_radio_info_url`
(default `http://127.0.0.1:1894`; `null` disables it) every 5 seconds on its own
thread: `/api/state` for the current item, the item's `source_slot` in `/api/log`
for the show, and `/api/grid` for the hour's show when the item is not in the log.
Buffering placeholders are omitted, lines are cut to 64 characters (long artist
credits keep the first artist), and both lines disappear 30 seconds after the
station stops answering. The Presentation page's preview shows placeholders.

`GET /v1/production` returns settings and resolved card details;
`POST /v1/production` validates and atomically saves the complete `settings`
object. Both require the configured API key. Settings live in `production.json`
beside `master.socket_path`, shared by the web app and worker. Captions and audio
reload within one second without restarting the encoder or changing a live
source. The Sources page refreshes settings every ten seconds. Source monitors
show their card while idle and preserve prepared/on-air program previews;
upstream TV-Thing and Roku contribution streams remain owned by their source
services. The master stream itself carries the encoded card and selected audio.

The Presentation page previews edits before saving and offers a browser-only tone
audition. Its Reset button changes the form; Save applies it. Master playback
starts muted; unmute its video controls to hear the transmitted tone. After
installing this feature, restart the web app and master worker once to load the
new routes and media graph. Later presentation changes require no restart.

Choose **Watch master** on the Sources page to start the video monitor. It starts
muted; use the video controls to unmute. **Stop monitor** stops only that viewer.
The player and HLS files are served through the same HTTP app and API-key checks;
no extra Apache media rule or browser access to MediaMTX's loopback ports is
needed. This also works under `/vizelvision/` when the enabled app is deployed
there. The locally vendored [hls.js](https://github.com/video-dev/hls.js) 1.7.2
package has verified package integrity, provenance, and licenses under
`roku_stream/static/vendor/`; browser playback makes no CDN requests.

The dedicated MediaMTX configuration exposes only loopback listeners:

| Use | Address |
| --- | --- |
| Master RTSP | `rtsp://127.0.0.1:18554/master` |
| Master HLS | `http://127.0.0.1:18888/master/index.m3u8` |
| Publication status | `http://127.0.0.1:19997/v3/paths/get/master` |

H.264 output defaults to 1280×720 at 30 fps and 2500 kbit/s; audio is AAC stereo
at 48 kHz. HLS is fMP4 with in-memory segments. Another publisher cannot replace
the active publisher. Unit definitions and the installation script are in
`deploy/`. Do not also launch the three processes in foreground terminals while
their services are running.

For another checkout, use the `master` block in `config.example.json`, enable
`tv_thing`, and choose a separate candidate HTTP port and state directory. The
HTTP API and worker must run as the same user with the same configured socket.

## Operator workflow

Since September 30 the page puts sources on air only through Up next
([details](source-queue.md#up-next-is-the-only-way-on-air-september-30)); steps 2 and 3
below are what a queue entry does, or what an API client does directly.

1. Browse or filter sources. This only reads catalogs and guide data.
2. Choose **Prepare** on a TV-Thing channel. The worker acquires a lease, tunes,
   checks the exact selection and stream generation, then waits for fresh decoded
   audio **and** video. An operation stays pending during this wait.
3. Choose **Take to master** and pick when it ends (see
   [manual takes end on time](source-queue.md#manual-takes-end-on-time)). The request
   names the exact prepared ID; an old tab cannot accidentally take a newly prepared
   channel. The worker verifies the lease and media again before changing both selectors.
4. **Cancel preparation** releases the prepared input. **Return to fallback**
   switches away and releases all worker-owned inputs.

Preparing a different channel on the on-air tuner returns master to fallback
before retuning. Preparing the other tuner leaves the current feed selected.
The page explains this next to the controls. Upcoming program listings do not
imply recording or time shifting: Prepare selects what is airing on that channel
now. Queue buttons will arrive with the mixed-source coordinator.

## Control API

These routes use the existing HTTP API-key authorization and application prefix:

| Route | Body / response |
| --- | --- |
| `GET /v1/master` | Publication state, on-air target, prepared target, coordinator operation, errors, encoded-track counters |
| `POST /v1/master/prepare` | `{"source_id":"tv-thing-digital","channel_id":"<catalog-id>","quality":"medium"}` |
| `POST /v1/master/take` | `{"prepared_id":"<id from status.prepared>"}` |
| `POST /v1/master/cancel` | `{}` |
| `POST /v1/master/fallback` | `{}` |
| `GET /v1/master/media/<file>` | Same-origin HLS playlists and segments from the configured master path |

Analog uses `source_id: "tv-thing-analog"` and the catalog's numeric channel ID.
YouTube TV uses `source_id: "youtube-tv"` and a configured channel name. Baseball
uses `source_id: "mlb"`, the game's ID as `channel_id`, and the catalog's `date`;
the existing baseball resolver chooses its available Roku provider. See
[Roku master workflow](roku-master.md) for preparation, cancellation, and recovery.
Mutation responses are HTTP 202 acknowledgments, not successful-take claims;
poll status for `operation.state` and `on_air`. One operation runs at a time.
Cancel/fallback requests remain accepted during preparation, with execution after
the current bounded upstream request returns. Tune requests allow 15 seconds;
other TV-Thing requests allow at most 4 seconds. Input readiness has a 40-second
deadline after tuning. Lease cleanup can add time after cancellation.

The private Unix socket has mode 0600 and a lifetime file lock prevents duplicate
workers from owning it. It only accepts status, prepare, take, cancel, and fallback;
browser requests cannot supply arbitrary media URLs or GStreamer descriptions.
The media proxy restricts filenames and session/HLS query parameters, limits each
response to 16 MiB, and permits at most six concurrent upstream reads. Media
responses are not cached across publisher restarts.

## Failure behavior

- Each input has a separate decoder pipeline feeding bounded raw A/V queues.
  Decoder EOS, loss of fresh audio/video, changed selection/generation, and loss
  of tuner ownership drop that input. If it is on air, master selects fallback.
- The fallback, selectors, H.264/AAC encoders, and RTSP publisher remain running
  through ordinary input changes. Input timestamps share one A/V offset into the
  output clock. Backward/discontinuous input timestamps fail the preparation.
- Publication checks combine fresh outgoing encoded buffers with MediaMTX path
  readiness and publisher identity. Publisher failures rebuild the output on
  fallback with a 1–15 second retry backoff. A server/worker crash can disconnect
  viewers; ordinary input cuts preserve the publisher and reader sessions.
- The worker asks for 90-second tuner leases, uses the actual granted expiry,
  renews halfway through the grant, and verifies ownership with the token before
  taking. Renewal that unexpectedly acquires a new lease is rejected and released.
  It never uses override or stops the upstream shared stream.
- Tokens remain in worker memory and are never returned in status. Graceful exit
  releases them. After a crash or lost acquisition/release response, a lease can
  remain until its server-side expiry, at most 90 seconds for this worker. Restart
  starts on fallback and does not reclaim, replay, or retune prior inputs.

## Validation

The [worker media report](master-worker-validation.json) records an isolated run
with a generated HLS feed and a fake TV-Thing API. It verifies two prepare/take
cycles, manual fallback, generation-loss fallback, exact publisher/reader identity,
H.264 and AAC segment decoding, monotonic timestamps, lease release, and socket
cleanup. A subsequent publisher restart must recover to fallback without tuning.

The [current digital feed report](current-tv-input-validation.json) validates the
already-running WUSA feed through the 720p master. It acquires/releases a temporary
lease and never calls tune or stop; the selected stream generation is unchanged.
The [browser report](master-browser-validation.json) verifies actual Chromium
HLS playback and a visible red-to-fallback cut with one MediaSource attachment,
including the real API media proxy, CSP, and application prefix.

During deliberate MediaMTX shutdown, the installed GStreamer 1.22 RTSP plugin
emitted GLib socket diagnostics. The worker recovered and the gate passed; these
diagnostics are not suppressed. Ordinary takes did not require reconnection.

```bash
/usr/bin/python3 -m unittest discover -s tests -q
/usr/bin/python3 tests/master_worker_integration.py --hd
/usr/bin/python3 tests/master_preview_integration.py /path/to/playwright
node tests/browser_ui_air.cjs /path/to/playwright
node tests/browser_ui_sources.cjs /path/to/playwright
```

The Python suite also covers lease refusal/expiry/renewal/lost response, selection and
generation validation, same-lane fallback ordering, independent-lane failure
containment, stale takes, duplicate operations/cancellation, decoder stalls,
publisher rebuilding, config validation, and API authorization. Browser checks
cover exact prepare/take bodies, prefix routing, mobile fit, preserved guide
expansion during status polling, and no mutations from browsing.

The actual CLI was also checked against isolated MediaMTX: a second worker was
rejected without disturbing the first; SIGTERM exited cleanly, removed the socket,
and released publication. Both systemd templates pass `systemd-analyze --user
verify`, and the deployment MediaMTX YAML was started successfully on temporary
ports with only the `master` path configured.

These checks do not prove analog reception quality, lip sync on real broadcasts,
or long-duration resource stability. Analog validation is deferred: the input is
reserved for future analog-output testing and currently has no signal. The mixed-source
queue now prepares and takes through the source coordinator. Next: longer operational
observation, advance preparation of independent inputs, and interrupted-take reconciliation.
The earlier stall was not reproduced in five-minute observations of the current digital
and Roku feeds. Failed-source identity and track ages/counts are now retained and logged;
the intermittent failure has not been established as fixed.
