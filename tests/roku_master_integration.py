"""Real media/IPC gate with simulated Roku controls; no hardware or navigation."""
import json
import re
import argparse
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.input_preview import InputPreview
from roku_stream.master import MasterStreamError
from roku_stream.config import FeedbackConfig, MasterConfig, TvThingConfig
from roku_stream.master_media import DecodedInput, MasterMedia
from roku_stream.master_worker import MasterWorker, MasterClient, control_socket
from roku_stream.publication import LocalMediaMtx, PublicationMonitor, candidate_config, cancellation_handlers
from roku_stream.source_coordinator import SourceCoordinator
from roku_stream.source_queue import SourceQueue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise-recovery', action='store_true')
    args = parser.parse_args()
    def configuration(ports, path):
        result = candidate_config(ports, path)
        result['paths']['roku'] = {'source': 'publisher', 'overridePublisher': False}
        result['authInternalUsers'][0]['permissions'] += [
            {'action': 'publish', 'path': 'roku'}, {'action': 'read', 'path': 'roku'}]
        return result

    report = {'ok': False, 'hardware_opened': False, 'roku_controls': 'simulated', 'phases': []}
    with cancellation_handlers(), tempfile.TemporaryDirectory(prefix='vv-roku-master-') as directory, \
            patch('roku_stream.publication.candidate_config', side_effect=configuration):
        root = Path(directory)
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), root) as server:
            contribution_url = server.rtsp_url.rsplit('/', 1)[0] + '/roku'
            source = MasterMedia(contribution_url, width=320, height=180, fps=10, bitrate=256)
            generated = DecodedInput(source, 1, '', test_pattern=4)
            config = SimpleNamespace(
                master=MasterConfig(enabled=True, socket_path=root / 'master.sock', rtsp_url=server.rtsp_url,
                                    status_url=server.api_url + 'paths/get/' + server.path,
                                    hls_url=server.hls_url.rsplit('/', 1)[0] + '/',
                                    width=1280, height=720, fps=30, bitrate=2500),
                feedback=FeedbackConfig(backend='direct', device='/dev/video1', input_format='mpegts',
                                        contribution_url=contribution_url), tv_thing=TvThingConfig(enabled=False),
                resolve_channel=lambda _: (0, SimpleNamespace(name='NBC')))
            feedback = Mock(last_capture={'fresh': True, 'stream_id': 'fixture-capture'})
            feedback.status.return_value = {'ready': True, 'stream_id': 'fixture-capture'}
            feedback._stream.process.poll.return_value = None
            controller = Mock(feedback=feedback)
            worker = MasterWorker(config)
            client = MasterClient(config.master)
            preview = InputPreview(client)
            monitor = PublicationMonitor(server)
            coordinator = thread = playout = None
            try:
                def wait(check, timeout=35):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        source.poll()
                        generated.poll()
                        monitor.poll()
                        if check():
                            return
                        time.sleep(.04)
                    raise AssertionError('Timed out: ' + repr(check))

                wait(lambda: source.healthy() and generated.ready())
                source.take(1)
                with control_socket(worker):
                    thread = threading.Thread(target=worker.run)
                    thread.start()
                    wait(lambda: client.request().get('can_prepare'))
                    coordinator = SourceCoordinator(config, controller, Mock())
                    def play(_):
                        with coordinator.navigation_guard():
                            assert client.request()['on_air'] is None
                            assert not coordinator.path.exists()
                            report['phases'].append('fallback confirmed before simulated navigation')
                            return {'ok': True, 'channel': 'NBC', 'operation_id': 'fixture-cue', 'verification': {
                                'player_state': 'play', 'visible_channel_template': {'matched': True},
                                'playback_evidence': 'simulated verified selection'}}
                    controller.play.side_effect = play
                    monitor.started(lambda: time.sleep(.03))
                    target = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
                    for cycle in range(2):
                        coordinator.request('prepare', target)
                        def prepared():
                            status = coordinator.status()
                            if (status.get('operation') or {}).get('state') == 'failed':
                                raise AssertionError(status)
                            return status.get('can_take')
                        wait(prepared)
                        assert client.request()['on_air'] is None
                        key = coordinator.status()['prepared']['id']
                        visited = set()
                        def check_preview(name):
                            if name in visited:
                                return
                            visited.add(name)
                            raw, mime = preview.read(key, name)
                            assert raw
                            if name.endswith('.m3u8'):
                                for token in re.findall(rb'[a-f0-9]{32}\.(?:m3u8|mp4|m4s|ts|aac)', raw):
                                    check_preview(token.decode())
                        check_preview('index.m3u8')
                        assert any(name.endswith(('.mp4', '.m4s')) for name in visited)
                        report['phases'].append('prepared-source HLS manifest, renditions and media proxied through selection ID')
                        coordinator.request('take', {'prepared_id': key})
                        wait(lambda: not coordinator.busy and coordinator.status().get('state') == 'live')
                        until = time.monotonic() + 6
                        wait(lambda: time.monotonic() >= until)
                        with monitor.lock:
                            assert all(abs(sample - 81) < 4 for sample in list(monitor.tracks['video']['samples'])[-5:])
                            assert sum(s[0] for s in monitor.tracks['audio']['samples']) > .05
                        monitor._hls()
                        report['phases'].append('verified selection and fresh A/V taken')
                        if cycle == 0:
                            with coordinator.navigation_guard():
                                assert client.request()['on_air'] is None
                                assert not coordinator.path.exists()
                            try:
                                preview.read(key, 'index.m3u8')
                            except MasterStreamError:
                                pass
                            else:
                                raise AssertionError('Cancelled selection still served preview')
                            report['phases'].append('legacy navigation invalidates on-air Roku and its preview first')
                    playout = SourceQueue(root / 'queue.json', coordinator.execute_queue,
                                          lambda *_: {'finished': True}, poll_seconds=.1)
                    coordinator.queue = playout
                    item = playout.add_target(target, 'after_game', after_game={
                        'game_pk': 123, 'game_date': '2026-09-12', 'title': 'Simulated final game'})
                    assert playout.paused
                    playout.resume()
                    def queue_taken():
                        current = playout.get(item.id)
                        if current.status == 'blocked':
                            raise AssertionError(current)
                        return current.status == 'succeeded'
                    wait(queue_taken)
                    assert client.request()['on_air']['channel_id'] == 'NBC'
                    report['phases'].append('persistent source queue prepared and confirmed an automatic master take')
                    playout.pause()
                    if args.exercise_recovery:
                        key = worker.active
                        decoder = worker.inputs[key]['decoder']
                        interrupted = threading.Event()
                        sink = decoder.pipeline.get_by_name('video')
                        sink.disconnect_by_func(decoder._sample)
                        def deliver(sample_sink):
                            if interrupted.is_set():
                                sample_sink.emit('pull-sample')
                                return decoder.gst.FlowReturn.OK
                            return decoder._sample(sample_sink, 'video')
                        sink.connect('new-sample', deliver)
                        interrupted.set()
                        resume_video = threading.Timer(1.5, interrupted.clear)
                        resume_video.start()
                        wait(lambda: worker.recovering == key, timeout=6)
                        assert worker.active is None and client.request()['on_air'] is None
                        resume_video.join(timeout=2)
                        wait(lambda: worker.active == key and worker.recovering is None, timeout=5)
                        report['recovery'] = client.request().get('last_recovery')
                        report['phases'].append('1.5-second decoded-video interruption: fallback then same-source recovery')
                        # Observe recovered content before verifying lease loss below.
                        until = time.monotonic() + 3
                        wait(lambda: time.monotonic() >= until)
                        assert decoder.ready()
                    coordinator.close()
                    wait(lambda: client.request()['on_air'] is None)
                    report['phases'].append('web shutdown returns master to fallback')
                    assert server.status()['source']['id'] == monitor.publisher_id
                    assert monitor.reader_id in {s['id'] for s in server.sessions() if s['state'] == 'read'}
                    with monitor.lock:
                        assert all(not t['backwards'] and t['max_pts_gap_seconds'] < (1.5 if args.exercise_recovery else .5)
                                   and t['max_arrival_gap_seconds'] < (1.5 if args.exercise_recovery else 1) for t in monitor.tracks.values())
                        report['tracks'] = {k: {f: v for f, v in t.items()
                                                if f not in ('samples', 'last_at', 'last_pts')}
                                            for k, t in monitor.tracks.items()}
                    report.update(ok=True, same_master_publisher_and_reader=True, hls_streams=monitor.hls_probe)
                    worker.stopping.set()
                    thread.join(timeout=10)
                    assert not thread.is_alive()
            finally:
                if playout:
                    playout.pause()
                if coordinator:
                    coordinator.close()
                if playout:
                    playout.close()
                worker.stopping.set()
                if thread:
                    thread.join(timeout=10)
                if monitor.pipeline:
                    monitor.pipeline.set_state(monitor.gst.State.NULL)
                generated.close()
                source.close()
    Path('docs/input-recovery-validation.json' if args.exercise_recovery else 'docs/roku-master-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
