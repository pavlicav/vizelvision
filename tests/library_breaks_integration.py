"""Opt-in real-media check of a show's ad break: a real file from a show folder, decoded by
FileInput as master would (the English sound picked when it has several), stopped at a break
found by a scan, held, then played on from the break's resume point. The master output is the
ID hold test's stand-in (appsrc -> fakesink), so no encoder, publisher or hardware is used.

Run off air from the repository root, as a user who can read the file:
    nice -n 19 /usr/bin/python3 tests/library_breaks_integration.py FILE [--scan]
With --scan it scans the file first (library_breaks.detect); else it uses the cached scan.
Checks: with several sound tracks the English one plays; the last frame passed on before the
hold is dark (the fade); while held the file does not advance, and does not decode on in the
background (it once ran to its end during a break, and "ended"); after the hold it plays on
from the resume point; timestamps never go backwards and no gap exceeds 150 ms.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream import library_breaks  # noqa: E402
from roku_stream.library import probe  # noqa: E402
from roku_stream.master_media import FileInput  # noqa: E402
from tests.ident_hold_integration import Output, wait  # noqa: E402

HOLD_SECONDS = 20
LEAD = 6          # start this long before the break


def played_language(decoder):
    """The language of the sound track the decoder is playing."""
    element = decoder.pipeline.get_by_name('decoder')
    for pad in element.srcpads:
        stream = pad.get_stream()
        if stream is not None and stream.get_stream_type() & decoder.gst.StreamType.AUDIO:
            tags = stream.get_tags()
            found, value = tags.get_string('language-code') if tags is not None else (False, None)
            return value if found else None
    return None


def main(path, scan):
    path = Path(path)
    duration = probe(path)['duration']
    found = library_breaks.detect(path, duration) if scan else None
    if not found or not found['breaks']:
        raise SystemExit(f'No breaks to try: {found}')
    point = found['breaks'][0]
    _, _, tracks = library_breaks.tracks(path)
    output = Output()
    gst = output.gst
    decoder = FileInput(output, 3, path.as_uri(), start_seconds=point['at'] - LEAD, select_audio=tracks > 1)
    report = {'ok': False, 'file': path.name, 'break': point, 'audio_tracks': tracks}
    try:
        wait(decoder.ready, 30, 'the file decodes')
        decoder.cue()
        decoder.start()
        report['language'] = played_language(decoder)
        if tracks > 1:
            assert report['language'] in ('en', 'eng'), f"playing the {report['language']} track"
        decoder.stop_at(point['at'])
        wait(lambda: decoder.stopped, LEAD + 5, 'the break frame')
        started = time.monotonic()
        assert decoder.freeze(), 'freeze refused'
        frame = decoder.last_frame.extract_dup(0, 320 * 180)
        report['held_luma'] = round(sum(frame) / len(frame), 1)
        assert report['held_luma'] < 40, f"the held frame is not dark: {report['held_luma']}"
        held_at = decoder.progress()['position_seconds']
        time.sleep(HOLD_SECONDS)
        decoder.poll()
        assert decoder.ready(), 'a held file must stay ready'
        position = decoder.progress()['position_seconds']
        assert position - point['at'] < .5, f'the file advanced while held: {held_at} -> {position}'
        report['dropped_at_stop'] = decoder.dropped
        assert decoder.dropped < 100, f'it decoded on while held: {decoder.dropped} buffers dropped'
        assert not decoder.ended and not decoder.finished, 'it ran to its end while held'
        report['thaw_at_s'] = round(time.monotonic() - started, 2)
        decoder.thaw(point['resume'])
        report['thaw_took_s'] = round(time.monotonic() - started - report['thaw_at_s'], 3)
        wait(lambda: (decoder.poll() or (decoder.progress()['position_seconds'] or 0)) >= point['resume'] + 3, 10,
             'the file plays on after the break')
        report['resumed_at'] = decoder.progress()['position_seconds']
        assert decoder.error is None, decoder.error
        with output.lock:
            seen = {k: list(v) for k, v in output.seen.items()}
        for kind, buffers in seen.items():
            # From the stop on: a file started partway in can stutter at its own start.
            buffers = [b for b in buffers if b[2] >= started - 1]
            pts = [p for p, _, _ in buffers]
            gaps = [(b - (a + max(d, 0))) / gst.MSECOND for (a, d, _), (b, _, _) in zip(buffers, buffers[1:])
                    if d != gst.CLOCK_TIME_NONE]
            worst = max(range(len(gaps)), key=gaps.__getitem__) if gaps else None
            report[kind] = {'buffers': len(pts), 'backwards': sum(b < a for a, b in zip(pts, pts[1:])),
                            'max_gap_ms': round(max(gaps, default=0), 1),
                            'worst_at_s': round(buffers[worst][2] - started, 2) if worst is not None else None}
            assert report[kind]['backwards'] == 0, f'{kind} timestamps went backwards: {report[kind]}'
            assert report[kind]['max_gap_ms'] < 150, f'{kind} timeline gap: {report[kind]}'
        report.update(ok=True, held_seconds=round(time.monotonic() - started, 1))
    finally:
        decoder.close()
        output.pipeline.set_state(gst.State.NULL)
        print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], '--scan' in sys.argv[2:]))
