# Verified Roku master takes

Since September 30 the page puts the Roku on air only through Up next: the Roku card
has **+ Queue** instead of Prepare Roku and Take to master, and its **Last known** line
says when queuing the selected channel or game reuses a recent verification. Live
capture opens while Up next navigates and closes once the selection is prepared. See
[Up next is the only way on air](source-queue.md#up-next-is-the-only-way-on-air-september-30).
The description below is the page before that change; the API is unchanged.

Open `http://viviserv:6970/sources`. One **Roku** card has a grouped dropdown for
YouTube TV channels and MLB games, a last-known selection and preparation time,
**Prepare Roku**, and **Take to master**. Preparing a new Roku
target returns the master to black/silence, selects and visually verifies the
requested channel/game using the existing Roku controller, and starts decoding
the shared capture contribution. **Take to master** becomes available after both
tracks remain fresh for two seconds. Prepare alone never takes the source.

Preparation is optional when the dropdown matches the last verified selection
and that selection is at most 15 minutes old. Taking that selection reconnects
its decoded media if needed, without navigating the Roku again. An already-live
matching selection is a successful no-op. **Prepare Roku** explicitly navigates
again. Queue releases also reuse recent matching selections and otherwise prepare
normally, while retaining their program-identity and release-condition checks.

`master.roku_prepare_max_age_seconds` configures the freshness window (default
900, range 1–3600 seconds). Reusing media never extends the original preparation
timestamp. Source, channel/game ID, and game date must match. Capture/publisher
replacement and application-controlled navigation invalidate reuse. The history
is saved in `roku-last-prepared.json` beside the worker socket; after a web restart
it is displayed as historical state and cannot authorize playback until verified
again. Expiry blocks new takes; it does not interrupt a program already on air.

Baseball uses the catalog's exact game ID and date, then its existing preferred
source resolver: a game may route through YouTube TV or MLB.TV. The prepared and
on-air labels show the resolved route. No new program guide or baseball streaming
availability is inferred. Analog hardware validation remains deferred.

## Coordination and failure behavior

`SourceCoordinator` serializes master commands with all Roku playback operations,
including the original buttons, timed jobs, queue cues, and network calibration
that navigates. Conflicting operations are rejected. If a legacy Roku action
starts while Roku is prepared/on air, the coordinator invalidates that selection
and waits for confirmed fallback before permitting any navigation. Independent
TV-Thing playback can remain on air when no Roku input is prepared/on air.

The coordinator returns an operation ID immediately. `/v1/master` exposes its
pending/succeeded/failed status while the existing `/v1/operation` continues to
show detailed Roku navigation progress. Cancel preparation interrupts only the
coordinator's own Roku cue and cancels pending media preparation. Return to
fallback is accepted during preparation and runs after bounded cleanup.

After successful visual selection and Roku playback confirmation, the web app
writes a private 0600 selection record beside the worker socket. It names the
exact source target, verification operation, capture publisher, and selection
generation. A background heartbeat maintains a five-second expiry while capture
identity remains valid; browser tabs are not required. This record is not restored
on web restart. It is invalidated before another navigation or on shutdown.

The media worker never navigates the Roku. It checks the unexpired selection
record, expected target/generation, and MediaMTX contribution publisher identity
during preparation, at take, and during playout. It requires fresh decoded A/V;
missing audio, stopped video, expired verification, or publisher replacement makes
that input unavailable and returns an on-air Roku input to fallback. A web crash
can take up to about seven seconds to invalidate selection (five-second expiry
plus the worker's two-second polling interval). Decoder failures may be detected
sooner. Recovery never replays an old selection or automatically takes a source.

This verifies the selected guide row/game and subsequent reported playback. It
does not independently identify the channel from broadcast pixels continuously.
An external physical Roku remote bypasses application coordination. Lip sync and
long-duration media stability remain separate validation work.

## API

Use the existing authenticated/prefix-aware master API:

```json
POST /v1/master/prepare
{"source_id":"youtube-tv","channel_id":"NBC"}
```

```json
POST /v1/master/prepare
{"source_id":"mlb","channel_id":"<game ID>","date":"YYYY-MM-DD"}
```

Poll `GET /v1/master`, then send the exact `prepared.id` to
`POST /v1/master/take` as `{"prepared_id":"..."}`. `cancel` and `fallback` accept
empty objects. Client requests cannot supply a contribution URL or fabricate a
verified selection; these are generated by the coordinator from local config and
successful controller results.

`GET /v1/master` includes `roku_last_prepared` with `target`, `prepared_at` (Unix
seconds), `age_seconds`, `max_age_seconds`, `reusable`, and an unavailable reason.
The stored timestamp is distinct from the short-lived capture authority record.
Prepare defaults to reuse; add `"force":true` to navigate again. MLB schedule
resolution happens after operation admission, so the prepare response remains
asynchronous and cancellation is available during lookup.

To take a recent matching Roku state without navigation:

```json
POST /v1/master/take-known
{"source_id":"mlb","channel_id":"<game ID>","date":"YYYY-MM-DD"}
```

This fails if no matching recent verification remains. It never substitutes
another game or falls back to navigating. Manual takes pause automatic queue
release; every actual cut still submits the exact worker preparation ID and
requires live audio/video readiness.

## Validation and next milestone

The [generated-media gate](roku-master-validation.json) uses the actual coordinator,
private IPC, worker, GStreamer, and MediaMTX with simulated Roku controls. It checks
two prepare/take cycles, navigation/fallback ordering, web shutdown, subscriber
identity, monotonic timestamps, and decoded H.264/AAC HLS. Limits: timestamp gaps
below 500 ms and subscriber arrival gaps below one second. Unit coverage includes
failed verification, stale capture/selection, expiry, competing legacy controls,
cancellation at the readiness boundary, exact baseball selection, and cleanup.
Browser checks cover readiness gating, exact take IDs, game dates, resolved-route
labels, application prefixes, and mobile layout.

The NBC live test exposed two YouTube TV navigation cases, both now covered by
regression tests: Home recommendations can contain multiple clock times without
being a guide, and the return-to-playback banner shifts the navigation row down.
Home focus now requires a narrow pill with dark sides, rejecting that wider
banner. The controller moves down from a focused return banner and confirms a
Home/Live tab before selecting the guide. Both captured layouts were checked.

```bash
/usr/bin/python3 -m unittest discover -s tests -q
/usr/bin/python3 tests/roku_master_integration.py
node tests/browser_ui_sources.cjs /path/to/playwright
```

`tests/live_roku_master.py` is an explicitly opt-in live gate: it navigates to NBC,
prepares and takes NBC to master, checks 30 seconds of subscriber continuity and
one hardware reader, and leaves NBC on air. Its report is written to
`docs/live-roku-master-validation.json` only on success. It does not test real MLB
selection or independently measure lip sync.

The successful [live NBC report](live-roku-master-validation.json) and
[deployed browser playback report](roku-master-browser-validation.json) record
the actual master take and Chromium HLS playback, respectively.

The [master source queue](source-queue.md) now uses this coordinator for automatic prepare/take and legacy timed schedules. It supports qualified targets, program snapshots, missed/failed blocking, pause/resume, and operator review after restart. Automatic preparation ahead of release is still pending.
