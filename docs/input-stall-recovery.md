# Input stall investigation and recovery

September 16, 2026. Recovery and capture diagnostics are deployed with the source-preview backend. Deployment found master on fallback, NBC prepared, and the queue paused with an already missed/blocked NFL entry. The queue and its history were preserved.

## Evidence

The September 13 NBC master take succeeded at 12:53 PM EDT. At 2:13:42 PM EDT the worker observed video age 1.045 seconds and audio age 0.958 seconds and discarded the input. MediaMTX logged the master's reader teardown at that time; the Roku capture publisher remained connected until 3:20:53 PM. This rules out a publisher disconnection at the exact recorded stall, but does not distinguish absent capture packets from decoder buffering or scheduling.

The current Roku contribution passed another 300-second isolated decode/publication check without navigation, retuning or a competing hardware reader. The same contribution publisher remained connected. The live reader already negotiates TCP. No transport or buffer-size tuning was applied. GStreamer negotiates transport and performs RTP jitter processing inside `rtspsrc`; see the [official rtspsrc documentation](https://gstreamer.freedesktop.org/documentation/rtsp/rtspsrc.html).

Previously, continuous-capture FFmpeg stderr was discarded. There is no historical FFmpeg error record for the original interruption. The original spontaneous fault has not been reproduced or attributed to a hardware/decoder root cause.

## Changes

- Retain the existing one-second freshness threshold. On an on-air freshness stall, select fallback immediately and retain the same decoder/lease for at most eight seconds.
- Resume only after both tracks are ready continuously for 0.5 seconds, renewing/checking the same source identity and URL immediately before the cut. There is no retune, navigation, new lease acquisition or decoder timestamp reset during recovery.
- Source/lease changes, timestamp errors, decoder errors/EOS and repeated stalls remain terminal. A fourth stall within 60 seconds discards the input. A prepared-only input failure still drops that preparation.
- An admitted master command supersedes pending recovery. Recovery never replays a queue entry or marks another source on air. Status reports fallback with a recovery target until a confirmed cut restores it.
- Expose active/prepared/recovering decoder track statistics, including decoded buffer age/count and RTSP RTP-pad delivery age/count. These RTP-pad values are after GStreamer's RTP processing, not raw socket-arrival measurements.
- Drain capture stderr on a separate thread, retaining only its last 8 KiB. Track frame age, largest frame-delivery gap and the last gap over a second. Record diagnostics before closing a failed capture process. `GET /v1/roku/capture` reads these statistics without navigating the Roku.
- `deploy/observe-master.py` provides bounded read-only recording of master, capture and contribution state. By default it observes for two hours at two-second intervals, retaining at most three 4 MB log files under the configured state directory.

## Verification

218 Python tests pass across the current implementation. New tests cover recovery, lease loss, timeout, pending manual commands, repeated-stall limits, and draining a large stderr stream without blocking image delivery. Existing queue and navigation regression tests also pass.

`/usr/bin/python3 tests/roku_master_integration.py --exercise-recovery` uses real GStreamer, worker IPC and MediaMTX with simulated Roku control. It suppresses decoded video delivery for 1.5 seconds after appsink clock synchronization. The worker selected fallback, then restored the same selection after fresh delivery resumed. The same publisher and viewer remained connected. No backwards timestamps occurred. Current measured gaps and recovery duration are recorded in `input-recovery-validation.json`. Numeric fault-injection limit: under 1.5 seconds for either gap, with unchanged codec format and sessions. Ordinary no-fault limits remain unchanged.

The test also confirms that invalidating the verified Roku claim returns master to fallback. The isolated result is recorded in `input-recovery-validation.json`. It proves bounded recovery behavior for an injected delivery pause, not that the original intermittent source problem has been fixed.

## Deployment

Restarting the master worker clears prepared media; restarting the web service invalidates its Roku verification and pauses queue release. Recheck the current prepared/on-air source, active operation and pending queue before promotion. Do not replace a newer user selection with the earlier NBC test target. Keep the existing queue entry and its history intact.

After promotion, a read-only observation can be started with:

```sh
systemd-run --user --collect --unit=vizelvision-observe \
  --property=RuntimeMaxSec=7300 --property=UMask=0077 \
  /usr/bin/python3 /home/vivian/vizelVision/deploy/observe-master.py --seconds 7200
```

Results are `state/master-candidate/master-observation.jsonl` (with bounded rotations) and `master-observation-summary.json` when the observation exits. No automatic notification or future assistant follow-up is implied by this recorder.

## Source-controls regression found during deployment

Opening the first Roku signal-status query changed `_input_signature` from `None` to detected timings. The capture maintainer interpreted that first observation as a format change and restarted the existing capture, invalidating the prepared selection. The first query now establishes a baseline without restarting the stream. Subsequent detected format changes still reopen the decoder. A regression test verifies that the first query preserves the capture instance and selection identity.

Live revalidation confirmed advancing NBC preview playback and a still-ready prepared selection after opening diagnostics and closing the browser. Master was left on fallback, with queue release paused. The two-hour observer is running; sustained on-air recovery remains to be assessed during actual use.
