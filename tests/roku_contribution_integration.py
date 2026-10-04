"""Opt-in generated-media gate for shared Roku capture; opens no hardware.

One FFmpeg reads H.264/AC-3 MPEG-TS and provides PPM observations plus an RTSP
contribution. Decode that contribution into a separate master, cut to it, and
prove MediaMTX loss/recovery does not stop fresh observations or reopen capture.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.capture_stream import CaptureStream, contribution_output
from roku_stream.master_media import DecodedInput, MasterMedia
from roku_stream.publication import LocalMediaMtx, PublicationMonitor, cancellation_handlers


def main():
    executable = Path('vendor/mediamtx/1.21.0/mediamtx').resolve()
    report = {'ok': False, 'hardware_opened': False, 'phases': [],
              'limitations': 'Generated input; hardware reception and lip sync require a separate live gate.'}
    with cancellation_handlers(), tempfile.TemporaryDirectory(prefix='vv-roku-gate-') as directory:
        root = Path(directory)
        for name in ('contribution', 'master'):
            (root / name).mkdir()
        fixture = root / 'capture.ts'
        subprocess.run(['/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-t', '4', '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast',
                        '-tune', 'zerolatency', '-g', '30', '-c:a', 'ac3', '-ac', '2',
                        '-f', 'mpegts', str(fixture)], check=True, timeout=20)
        with LocalMediaMtx(executable, root / 'contribution') as contribution, \
                LocalMediaMtx(executable, root / 'master') as server:
            command = ['/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'error',
                       '-re', '-stream_loop', '-1', '-i', str(fixture),
                       '-map', '0:v:0', '-an', '-f', 'image2pipe', '-vcodec', 'ppm',
                       '-flush_packets', '1', 'pipe:1', *contribution_output(contribution.rtsp_url)]
            capture = CaptureStream(command)
            output = decoder = monitor = None
            try:
                pid = capture.process.pid
                frame = capture.next_frame(15, lambda _: None)
                assert (frame.width, frame.height) == (320, 180)
                output = MasterMedia(server.rtsp_url)
                monitor = PublicationMonitor(server)

                def poll():
                    output.poll()
                    monitor.poll()
                    if decoder:
                        decoder.poll()
                    assert capture.process.poll() is None
                    time.sleep(.03)

                def wait_ready(check, timeout=30):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        poll()
                        if check():
                            return
                    raise AssertionError('Media readiness timeout')

                def observe(seconds):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        poll()

                monitor.started(poll)
                wait_ready(lambda: contribution.status().get('ready'))
                for cycle in range(2):
                    decoder = DecodedInput(output, 1, contribution.rtsp_url)
                    wait_ready(decoder.ready)
                    # Preparation must remain usable while another input is selected.
                    observe(3)
                    output.take(1)
                    observe(8)
                    assert decoder.ready()
                    before = capture.sequence
                    capture.next_frame(3, lambda _: None)
                    assert capture.sequence >= before + 3
                    monitor._hls()
                    output.take(0)
                    decoder.close()
                    decoder = None
                    report['phases'].append('capture and master concurrently' if cycle == 0 else 'recovered contribution')
                    if cycle == 0:
                        contribution.__exit__(None, None, None)
                        before = capture.sequence
                        observe(4)
                        capture.next_frame(3, lambda _: None)
                        assert capture.sequence > before + 30
                        assert capture.process.pid == pid
                        report['phases'].append('fresh observations during MediaMTX outage')
                        contribution.__enter__()
                        wait_ready(lambda: contribution.status().get('ready'))
                observe(2)
                assert server.status()['source']['id'] == monitor.publisher_id
                assert monitor.reader_id in {s['id'] for s in server.sessions() if s['state'] == 'read'}
                with monitor.lock:
                    assert all(not t['backwards'] and t['max_pts_gap_seconds'] < .5
                               and t['max_arrival_gap_seconds'] < 1 for t in monitor.tracks.values())
                    report['tracks'] = {k: {f: v for f, v in t.items()
                                            if f not in ('samples', 'last_at', 'last_pts')}
                                        for k, t in monitor.tracks.items()}
                report.update(ok=True, same_capture_process=capture.process.pid == pid,
                              same_master_publisher_and_reader=True, hls_streams=monitor.hls_probe)
            finally:
                if decoder:
                    decoder.close()
                if monitor and monitor.pipeline:
                    monitor.pipeline.set_state(monitor.gst.State.NULL)
                if output:
                    output.close()
                capture.close()
    Path('docs/roku-contribution-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
