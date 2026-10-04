# GStreamer → MediaMTX publication workflow

Implemented and validated September 10, 2026, using GStreamer 1.22.0 and MediaMTX v1.21.0. This milestone publishes the existing synthetic switch graph, verifies it through independent RTSP and HLS consumers, and cleans up its owned processes. It does not yet connect TV-Thing, Roku capture, the master UI, or the mixed-source queue.

## Run

From the repository, use Debian's system Python (including when Conda's
`(base)` environment is active):

```bash
/usr/bin/python3 -m roku_stream master-check
/usr/bin/python3 -m roku_stream master-publication-test
```

The test uses a MediaMTX executable on PATH, or the pinned copy at `vendor/mediamtx/1.21.0/mediamtx`. To choose an executable explicitly:

```bash
/usr/bin/python3 -m roku_stream master-publication-test \
  --mediamtx /path/to/mediamtx --duration 20
```

The installed GStreamer RTSP plugin and `rtpmp4gpay`, FFmpeg/ffprobe, and the existing encoder/decoder plugins are required. No sudo is required to run the test. On this host, all required components are present and the pinned MediaMTX copy has been downloaded.

The apt-installed `python3-gi` bindings belong to `/usr/bin/python3`.
Conda's `python3` does not see them. Calling `/usr/bin/python3` explicitly
avoids changing your Conda environment or reinstalling dependencies.
`master-check` reports the interpreter it inspected.

For a fresh Linux amd64 checkout, fetch that exact release with:

```bash
python3 deploy/fetch-mediamtx.py
```

The downloader verifies SHA-256 `e02e34c3337a35f20ac9e5aa31524566108964e6e37dbc46cf8292169f6c792b` against the downloaded archive, extracts only the binary, upstream configuration and license, and records origin metadata. It refuses an existing destination. This is a workspace-local binary, not a system package/service install. [Official v1.21.0 release](https://github.com/bluenviron/mediamtx/releases/tag/v1.21.0).

## Lifecycle

1. Start a private MediaMTX process on three automatically allocated loopback TCP ports. RTSP, HLS and the control API bind only to `127.0.0.1`. The configuration permits one unique `vv-publication-…` path, disallows publisher replacement, and disables recording and other listeners. Inherited `MTX_*` settings are removed so they cannot change the test's configuration.
2. Start one GStreamer graph with persistent H.264/AAC encoders after the audio/video selectors. Feed the two elementary tracks to `rtspclientsink` over TCP. Wait for MediaMTX to report the path ready and capture the publisher session identity.
3. Connect an independent GStreamer RTSP decoder and wait until it has received both video and audio. Readiness is established by decoded media, not just a connected socket or encoder buffers.
4. Keep that same reader connected while taking black/silence → red/440 Hz → blue/880 Hz → black/silence. Check its content before each take and at the end. Verify that both reader and publisher session identities remain unchanged.
5. At each phase, read the HLS master playlist, follow its video and audio rendition playlists, download complete initialization/media segments, inspect their codecs with ffprobe, and decode the served segments with FFmpeg. Require advancing media sequences and no end-of-playlist marker.
6. Stop the publisher and reader, verify that the path is no longer ready and RTSP sessions are gone, and then terminate/reap the owned MediaMTX process. Temporary configuration/log files are removed. Ctrl-C and SIGTERM unwind the same cleanup path.

`--duration` accepts 16–30 seconds of verified playout after publisher/reader startup, default 20. Startup, HTTP, subprocess and shutdown operations have additional bounded timeouts. The command finishes with a JSON report or a nonzero exit status with the failing stage and relevant server log. It does not leave a stream running after success.

## Compatibility details

GStreamer's automatic AAC RTP payloader initially chose LATM. RTSP playback worked, but MediaMTX v1.21.0's HLS muxer rejected the resulting stream with `unsupported frameLengthType 2`. The publication path now explicitly assigns `rtpmp4gpay` to the audio request pad, producing MPEG4-GENERIC AAC. This is an RTP packaging choice; the audio codec remains AAC. [GStreamer payloader documentation](https://gstreamer.freedesktop.org/documentation/rtp/rtpmp4gpay.html).

MediaMTX serves the audio as a separate HLS rendition in this configuration. Testing only the video media playlist would miss audio failures, so both renditions are validated. The test uses fMP4 HLS and keeps its segments in memory.

The previous audio normalization remains in place before the persistent AAC encoder to prevent backward timestamps at cuts. Neither master encoders nor publisher sessions are restarted to change the selected synthetic input.

## Validation results

The [complete successful report](publication-validation.json) records:

- Three cuts, one publisher session, one continuously connected RTSP reader; zero reader reconnects.
- Correct decoded video levels and audio silence/440 Hz/880 Hz changes at the subscriber.
- Zero backward decoded timestamps. Largest observed video PTS interval: approximately 100.5 ms at the 10 fps test rate. Audio: approximately 21.3 ms. Maximum subscriber arrival gaps remained below 103 ms.
- HLS video media sequences `2 → 6 → 10 → 15`; audio `3 → 7 → 11 → 15`. Every inspected rendition segment decoded successfully.
- Served HLS codecs: H.264 at 320×180; AAC stereo at 48 kHz.
- Path and RTSP sessions released on stop.

The Python suite passes 129 tests, including coverage of listener/path isolation, disabled publisher replacement, inherited configuration removal, startup failure cleanup, forced process cleanup, HLS rendition handling, missing audio, URL containment, release failure, size limits, and signal-handler restoration. A separate real SIGTERM check confirmed exit code 130 and that the owned MediaMTX child was reaped.

This is a low-resource synthetic validation, not a 720p resource gate or a frame-accurate synchronization measurement for dissimilar live inputs. It does not validate publication recovery after a server crash, browser HLS playback, or real TV-Thing/Roku contribution latency. Those remain explicit next steps.

## Next integration step

Implemented next: [persistent master worker and TV-Thing takes](master-worker.md).
The paragraph below records the remaining work at the synthetic-publication milestone.

Use the validated H.264/MPEG4-GENERIC AAC publishing path in the long-running master worker. Add its health/reconnect supervision and fixed master destination, then connect a TV-Thing HLS contribution with lease ownership and generation checks. Roku requires a separate capture-sharing change that supplies audio/video while retaining fresh-frame verification. Until those are ready, source discovery continues to report master takes and the mixed-source queue as unavailable.
