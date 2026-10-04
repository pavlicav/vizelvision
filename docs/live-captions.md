# Live transcribed captions

**Presentation → Live captions** (`/presentation#captions`) has a switch to show
Whisper captions on the shared broadcast. It starts off. The switch saves immediately;
model and language choices have a separate Save button. Settings persist in
`captions.json` beside the master socket, and the worker reloads them within a second.
`GET /v1/captions` reports settings and worker status; authenticated
`POST /v1/captions` accepts partial changes (`enabled`, `model`, `language`).

Captions are burned into the master video, so they reach the web monitor, HLS and
Roku together. They are not a selectable subtitle track. Whisper returns word
start/end times; short phrases appear on the corresponding delayed video frames,
then clear at the end of the phrase. The UI preview reports what is being rendered.
Nothing is recorded or sent to a cloud API.

## One shared programme delay

Whisper and ad detection now run ahead of the same programme buffer, after source
selection and before publication. Audio and video use the same offset:

```text
shared delay = max(6 s if captions enabled, ad lookahead + 1 s if ad detection enabled)
```

For example, captions plus the default 3 s ad lookahead use **6 s total**, not
6 + 4 s. An 8 s ad lookahead uses 9 s total. With both features off at startup,
the shared delay is zero. Per-input ad taps no longer insert another media delay.
Presentation shows the effective shared delay.

The buffer applies to live sources, recordings, station IDs and off-air radio.
Cuts, ends of files and ID holds remain in sequence; control-room selection and
file progress run ahead of the viewer by the shared delay. The station clock is
rendered after buffering and still shows current time. The player adds its normal
network/HLS buffering on top.

Increasing lookahead fills the additional window with a held picture and silence,
while publication continues. The delay never shrinks during a worker session:
turning captions/ad detection off clears their effect immediately, but reducing
latency waits for a master restart so queued programme content is not skipped.

Ad gain, the AD badge and the replacement radio bed are applied to the delayed
programme using the original source timestamps. Detector state survives a source
cut until its buffered tail has aired. Captions from muted programme audio are
suppressed, including while replacement radio is playing. The replacement bed is
not separately captioned; off-air radio is captioned normally.

## Runtime setup

The master keeps its system Python for GStreamer. Whisper runs in a separate,
low-thread-count CPU process using `faster-whisper` and an INT8 Whisper model.
The supplied master service sets `VIZELVISION_WHISPER_PYTHON` to this installation's
Conda Python, which already has faster-whisper and cached English models. On a
different installation, set that variable to the Python with the captions extra:

```sh
/path/to/caption-python -m pip install '.[captions]'
/path/to/caption-python -c 'from faster_whisper import WhisperModel; WhisperModel("base.en", device="cpu", compute_type="int8")'
```

Run the cache command as the service user. This downloads the selected model once
from Hugging Face; runtime uses only cached files and never downloads a model when
the switch is turned on. Cache each additional model before choosing it. Supported
models are `tiny.en`, `base.en` (default), `small.en`, `tiny`, `base` and `small`.
English models require language `en`; multilingual models support the languages
offered by the UI and `auto`. Speech is transcribed in its own language, not translated.

Reload/install the updated service unit and restart master and web after deploying
the Python changes. A master restart interrupts publication and starts on fallback,
as usual; changing caption settings after that does not restart the publisher.
The UI reports when an older worker needs a restart or a model/dependency is missing.

## Timing and failure behavior

Whisper processes four-second chunks. Loading starts when captions are enabled,
while the first chunk fills. Word timestamps are relative to the captured audio;
they are preserved through transcription and mapped onto the delayed frames.
Receiving a result does not display it immediately. Source changes finish partial
audio without discarding cues for a previous source's buffered tail. Silence
between phrases remains blank, and cues which have entirely missed their on-air
window are discarded. `late_cues` counts results whose first word was already due.

The six-second processing window covers normal base.en processing on this host.
An overloaded CPU or a slower model can still return late cues; the programme
continues, and captions may be incomplete. Model timestamps and recognition can
be inaccurate, especially at chunk boundaries. This is not a verbatim captioning
service. `latency_seconds` measures chunk collection plus processing time, not
caption delay relative to the audio viewers hear.

The shared raw-media buffer has time and 1 GiB memory bounds. Transcription has
at most two pending audio chunks and 160 queued phrases. Failures are reported in
Presentation and retried with bounded backoff. The worker does not wait for Whisper.
Transcript text is escaped before reaching GStreamer's Pango overlay.

Implementation follows the [faster-whisper word-timestamp and VAD documentation](https://github.com/SYSTRAN/faster-whisper#word-level-timestamps).

## Validation

`tests/caption_timing_integration.py` runs deterministic speech markers through
real GStreamer with an ad tap, verifies that 4 s ad buffering and 6 s caption
buffering become one 6 s delay, and measures subtitle onset against the output
sound. The measured onset difference was 22–33 ms, with zero dropped buffers and
no backwards timestamps. The muted ad's caption was suppressed. This measures the
media scheduling; it does not assert that Whisper's estimated word times are exact.

`tests/captions_integration.py` separately runs the cached real Whisper model on
the local Sports ID, verifies glyphs in an independently decoded RTSP stream,
and checks the off switch. Unit tests cover future and expired cues, source cuts,
muting, malformed timestamps, overload, cancellation and buffer bounds. Browser
tests cover the switch, model options and shared-delay status.

The media tests use isolated MediaMTX instances and temporary local clips. They do
not touch production or tune hardware.
