> **Retired 2026-10-06.** The source Roku is TV Thing's Roku lane: TV Thing is the only reader
> of the HD PVR and copies its H.264/AAC to HLS (`/tv/stream/roku.m3u8`), which master control
> plays like a tuner's feed. There is no RTSP contribution and no MediaMTX `roku` path. What
> follows describes the earlier design.

# Shared Roku audio/video contribution

The master-control web service now keeps one Hauppauge reader alive and uses it
for both fresh Roku verification images and a private audio/video contribution.
Enable it with `feedback.contribution_url: "rtsp://127.0.0.1:18554/roku"` in
`config.master.json`. It is enabled on viviserv. The default remains disabled for
other configurations; only direct MPEG-TS capture supports this option.

The existing FFmpeg process continues decoding and draining PPM images, retaining
one latest frame. The added output copies compressed H.264 and encodes stereo
48 kHz AAC. It publishes through a separate FIFO writer to MediaMTX's loopback-only
`roku` path. The 60-packet queue drops on overflow, retries network failures, and
resumes at a keyframe. This follows FFmpeg's documented
[FIFO output and recovery behavior](https://ffmpeg.org/ffmpeg-formats.html#fifo).
Missing audio does not prevent the image branch from operating; master
takes still require both decoded tracks.

The web service supervises capture even with every browser closed. Failed capture
is retried after a bounded pause. Existing device-identity checks, resolution-change
handling, fresh-frame barriers, and cancellation remain in place. Background
observations do not overwrite the last cue's evidence and yield to active Roku
operations. A MediaMTX restart can interrupt the contribution but must not restart
the hardware reader or stop verification images. A hardware reader crash or
device disconnect interrupts both branches until capture recovers.

There is no extra capture service and no second hardware reader. The original
`vizelvision.service` must remain disabled. The deployment YAML grants only
loopback publish/read access to the private path and forbids replacing its
publisher. The master remains on its separate `master` path. Configuration and
service commands are documented in [master-worker.md](master-worker.md).

## Validation

`tests/roku_contribution_integration.py` generates H.264/AC-3 MPEG-TS, then tests
the same dual-output capture command. It verifies concurrent fresh images and
master A/V, two cuts to the contribution, master HLS decoding, unchanged master
publisher/reader identity, and capture survival through a contribution-server
outage and recovery. Limits: no backward output timestamps, maximum timestamp
gap below 500 ms, and maximum subscriber arrival gap below one second. Results:
[generated-media report](roku-contribution-validation.json).

`tests/current_roku_input_integration.py` reads the existing live contribution
without opening hardware or navigating the Roku. It checks a 30-second take on
a temporary master, concurrent MJPEG previews, H.264/AAC HLS decoding, the same
continuity limits, and unchanged single-device ownership. Results:
[live Hauppauge report](current-roku-input-validation.json).

```bash
/usr/bin/python3 -m unittest discover -s tests -q
/usr/bin/python3 tests/roku_contribution_integration.py
/usr/bin/python3 tests/current_roku_input_integration.py
```

These gates do not measure lip sync or prove long-duration stability. The private
contribution shows whatever the Roku currently displays, including menus. It is
not automatically selected for the public master. The
[source coordinator](roku-master.md) now takes fallback before Roku preparation,
verifies the requested channel/game with the existing controls, and enables a
separate take after both tracks are ready. Legacy navigation also uses its guard.
Routing the mixed-source queue through coordinator prepare/take remains next.
