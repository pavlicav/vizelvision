# Source integration: first milestone

Current update: the [persistent master worker](master-worker.md) adds TV-Thing
prepare/take controls and failure recovery. This document records the earlier
read-only milestone; its unavailable-capability statements describe that version.

Implemented September 10, 2026. This is the read-only guide and synthetic media foundation for the [master-stream plan](tv-thing-integration-plan.md). No production service was restarted, no tuner was changed, and no master stream was published.

Update: the subsequent [publication milestone](publication-workflow.md) now passes
isolated MediaMTX RTSP/HLS validation. The dependency observations and media-test
limits below describe the first milestone; see the newer report for current status.

## Available now

- `/sources`: multi-source guide, linked from the existing Roku Cue Sheet. Source filters, title/channel search, current program progress, later listings, local date/time/timezone, guide age/coverage, and individual source errors. No simulated programs or nonfunctional take/queue buttons.
- `GET /v1/sources`: provider/resource identity, TV-Thing availability/selected tuner channel, and explicit `master_take: false` / `master_queue: false` capabilities. Roku capture is not opened by source discovery.
- `GET /v1/sources/{id}/programs`: normalized channels and programs. IDs are `tv-thing-digital`, `tv-thing-analog`, `youtube-tv`, and `mlb`. The baseball view retains the existing provider-neutral game schedule and suggested broadcast source; it does not claim every game is available on MLB.TV. Its optional `date` query uses `YYYY-MM-DD`.
- TV-Thing HTTP client with bounded requests/response sizes, a read-operation allowlist, application-prefix-safe URLs, concurrent refresh coalescing, independent endpoint caches, retry cooldown, and stale snapshots. Guide data is joined by channel identity and filtered against the current clock. Repeated broadcast event IDs are qualified by channel and start time.
- Existing Roku controls and ordered queue continue to use their existing routes. The new source page links back to them and clearly states that the master output is not connected.

## Enable the guide in a candidate

The integration is disabled by default to preserve existing configurations. Add this top-level block to the candidate's JSON config (full timing options are in `config.example.json`):

```json
"tv_thing": {
  "enabled": true,
  "base_url": "http://127.0.0.1:8080/"
}
```

Use `http://viviserv/tv/` when accessing TV-Thing through its Apache application prefix. Open `/sources` under the same VizelVision application prefix, e.g. `/vizelvision/sources`. **Refresh listings** reads TV-Thing's cached guide; it never invokes the upstream tuner-consuming guide-refresh endpoint.

Do not start a second ordinary `serve` process against production state files: that would start another scheduler/queue. Use separate state paths and a candidate port for a full candidate instance. The completed live adapter validation instantiated the read-only catalog directly, without any scheduler or controller.

## GStreamer foundation

```bash
/usr/bin/python3 -m roku_stream master-check
/usr/bin/python3 -m roku_stream master-smoke
```

Neither command loads Roku configuration or constructs its controller. `master-check` inspects installed bindings/plugins and whether a MediaMTX executable is on PATH; it does not prove a MediaMTX server is running or absent elsewhere.

`master-smoke` runs for 8 seconds by default (8–30 allowed), using 320×180, 10 fps generated video and stereo 48 kHz audio. Paired selectors cut fallback → red/440 Hz → blue/880 Hz → fallback, with persistent H.264/AAC encoders after selection. Output is discarded; it never opens devices, writes media files, or publishes. Both selector outputs are held idle while their active pads change, and the pipeline is stopped in cleanup.

The first test exposed AAC timestamp regressions across input changes. A continuous audio segment and `audiorate` before the encoder corrected them. GStreamer documents `audiorate` as adjusting timestamped raw audio by inserting/dropping samples as needed. [Official audiorate documentation](https://gstreamer.freedesktop.org/documentation/audiorate/index.html).

The bench checks encoded output through all transitions, backward timestamps, gaps over 500 ms, and per-phase output stalls. It verifies settled raw colors and silence/tone changes after a 250 ms queue-drain interval; this is **not** a frame-accurate A/V synchronization test. Subscriber continuity, 720p resource limits, real input buffering, and RTSP/HLS behavior remain untested.

## Validation

- Python suite: 118 tests passed, including 17 new source/config/API tests.
- New browser suite: source filtering/search, later listings, partial failures, stale display, application prefixes, safe text rendering, keyboard access, mobile fit, and no mutation requests.
- Live read-only adapter: 70 digital channels, 135 analog selections; 60 digital channels with current/upcoming programs at inspection. No catalog/guide errors. These counts are an observation, not guarantees of reception or future coverage.
- Eight-second synthetic run: three cuts; 82 H.264 buffers and 371 AAC buffers; zero backward timestamps; maximum video timestamp interval 100 ms and audio interval approximately 21.3 ms. Both color and tone changes verified. Counts vary slightly with scheduling.

Browser checks use the installed Playwright package:

```bash
node tests/browser_ui_sources.cjs /path/to/playwright
node tests/browser_ui_pages.cjs /path/to/playwright
```

## Dependencies and next milestone

The inspected host has GStreamer 1.22, Python GI, decoding, selectors, H.264 and AAC encoding. The RTSP publishing plugin and GStreamer command-line tools are missing:

```bash
sudo apt update
sudo apt install gstreamer1.0-rtsp gstreamer1.0-tools
```

MediaMTX was not found on PATH or in the bounded installation-directory search. Confirm its existing host/path or install a pinned candidate separately before publication testing. The first milestone does not change system packages or service configuration.

Next: persist/supervise the worker; connect RTSP publication to an isolated MediaMTX master path and verify subscriber continuity; add TV-Thing lease/tune/readiness handling and real HLS inputs; then share Roku audio/video capture with its existing fresh-frame verification path. Only after those are validated should master takes and the mixed-source queue be enabled. The full queue schema/coordinator and media-serving changes described in the plan are not implemented in this milestone.
