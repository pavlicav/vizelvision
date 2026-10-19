import copy
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.config import LibraryConfig, LibraryRoot, MasterConfig, TvThingConfig, _library
from roku_stream.errors import ChannelNotFoundError, ConfigError
from roku_stream.library import FileLease, MediaLibrary, describe_name, library_target, resolve
from roku_stream.master import MasterStreamError
from roku_stream.master_worker import MasterWorker
from roku_stream.source_coordinator import SourceCoordinator
from roku_stream.source_queue import SourceQueue

PLAYABLE = {'probe': 'ok', 'playable': True, 'reason': None, 'duration': 60.0}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'Recordings'
        (self.root / 'Show' / '.hidden').mkdir(parents=True)
        for name in ('Jeopardy! - 7.1 WJLA - 2026-09-24 1930 (2).mp4', 'Show/[Grp]Show_-_01.mkv',
                     'In progress.ts.part', 'Show/.hidden/secret.mp4', 'notes.txt'):
            (self.root / name).write_bytes(b'x')
        (self.base / 'outside.mp4').write_bytes(b'x')
        (self.root / 'escape.mp4').symlink_to(self.base / 'outside.mp4')
        self.config = LibraryConfig(True, (LibraryRoot('rec', 'Recordings', self.root),))
        self.library = MediaLibrary(self.config, self.base / 'cache.json', prober=lambda path: PLAYABLE,
                                    start_worker=False)

    def test_lists_finished_visible_video_files_only(self):
        ids = sorted(i['id'] for i in self.library.listing()['items'])
        self.assertEqual(ids, ['rec/Jeopardy! - 7.1 WJLA - 2026-09-24 1930 (2).mp4',
                               'rec/Show/[Grp]Show_-_01.mkv', 'rec/escape.mp4'])

    def test_recording_names_and_folders_describe_items(self):
        info = describe_name('Jeopardy! - 7.1 WJLA - 2026-09-24 1930 (2).mp4', 'Recordings')
        self.assertEqual((info['title'], info['channel'], info['variant'], info['collection']),
                         ('Jeopardy!', '7.1 WJLA', '2', 'Recordings'))
        self.assertIsNotNone(info['aired'])
        info = describe_name('Show/[Grp]Show_-_01.mkv', 'Recordings')
        self.assertEqual((info['title'], info['collection'], info['aired']), ('[Grp]Show - 01', 'Show', None))

    def test_ids_cannot_leave_their_root(self):
        for bad in ('rec/../outside.mp4', '/rec/a.mp4', 'rec//a.mp4', 'rec/.hidden/a.mp4', 'rec/a.txt', 'rec', 'rec/./a.mp4'):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                library_target({'source_id': 'library', 'channel_id': bad})
        with self.assertRaises(ChannelNotFoundError):
            resolve(self.config, 'rec/escape.mp4')  # A symlink out of the root is refused.
        with self.assertRaises(ChannelNotFoundError):
            resolve(self.config, 'other/a.mp4')
        self.assertEqual(resolve(self.config, 'rec/Show/[Grp]Show_-_01.mkv').name, '[Grp]Show_-_01.mkv')

    def test_probe_results_are_cached_until_the_file_changes(self):
        item_id = 'rec/Show/[Grp]Show_-_01.mkv'
        self.assertEqual(self.library.item(item_id)['probe'], 'pending')
        calls = []
        self.library.prober = lambda path: calls.append(path) or {'probe': 'ok', 'playable': False, 'reason': 'No audio track'}
        self.library.thread = threading.Thread(target=self.library._probe_loop, daemon=True)
        self.library.thread.start()
        self.addCleanup(self.library.close)
        deadline = time.monotonic() + 2
        while self.library.item(item_id)['probe'] == 'pending' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.library.item(item_id)['playable'])
        with self.assertRaisesRegex(ConfigError, 'No audio track'):
            self.library.target({'source_id': 'library', 'channel_id': item_id})
        reloaded = MediaLibrary(self.config, self.base / 'cache.json', start_worker=False)
        self.assertEqual(reloaded.item(item_id)['reason'], 'No audio track')

    def test_config_validation(self):
        self.assertEqual(_library({}).enabled, False)
        for raw in ({'enabled': True}, {'roots': [{'id': 'Bad Id', 'name': 'x', 'path': '/x'}]},
                    {'roots': [{'id': 'a', 'name': 'x', 'path': 'relative'}]},
                    {'roots': [{'id': 'a', 'name': 'x', 'path': '/x'}, {'id': 'a', 'name': 'y', 'path': '/y'}]}):
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                _library(raw)


class FileWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name in ('a.mp4', 'b.mp4'):
            (root / name).write_bytes(b'x')
        library = LibraryConfig(True, (LibraryRoot('rec', 'Recordings', root),))
        config = SimpleNamespace(master=MasterConfig(enabled=True), tv_thing=TvThingConfig(enabled=False), library=library)
        self.library = library
        self.worker = MasterWorker(config, tv=Mock(), status_reader=lambda: {'ready': True, 'source': {'id': 'p'}})
        self.worker.output = Mock()
        self.worker.output.healthy.return_value = True
        self.worker.output.status.return_value = {}
        self.worker.publisher_ready = True
        self.worker.output_started = time.monotonic()
        self.worker._refresh()

    def entry(self, name, slot, *, cued=True, started=False):
        decoder = Mock(cued=cued, started=started, finished=False, START_TIMEOUT=1)
        decoder.ready.return_value = True
        decoder.status.return_value = {}
        decoder.progress.return_value = {'position_seconds': 10.0, 'duration_seconds': 60.0}
        def start():
            decoder.cued, decoder.started = False, True
        decoder.start.side_effect = start
        lease = FileLease(self.library, {'source_id': 'library', 'channel_id': 'rec/' + name})
        return {'lease': lease, 'decoder': decoder, 'slot': slot, 'was_ready': True, 'check_at': 0, 'url': lease.uri}

    def test_library_prepare_is_accepted_without_tv_thing(self):
        self.assertTrue(self.worker.status()['can_prepare'])
        with self.assertRaises(ConfigError):
            self.worker.submit('prepare', {'source_id': 'library', 'channel_id': 'rec/../x.mp4'})

    def test_take_plays_cued_file_from_its_start(self):
        self.worker.inputs['a'] = self.entry('a.mp4', 1)
        self.worker.prepared = 'a'
        self.worker._take({'prepared_id': 'a'})
        self.worker.inputs['a']['decoder'].start.assert_called_once()
        self.worker.output.take.assert_called_once_with(1)
        self.worker._refresh()
        self.assertEqual(self.worker.status()['on_air']['media']['duration_seconds'], 60.0)

    def test_end_of_file_cuts_to_armed_next_file(self):
        self.worker.inputs = {'a': self.entry('a.mp4', 1, cued=False, started=True), 'b': self.entry('b.mp4', 2)}
        self.worker.active, self.worker.prepared, self.worker.arm = 'a', 'b', ('b', 'a')
        self.worker.inputs['a']['decoder'].finished = True
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(2)
        status = self.worker.status()
        self.assertEqual((status['on_air']['id'], status['last_completed']['input_id'], status['prepared']),
                         ('b', 'a', None))
        self.assertEqual(status['last_completed']['next_input_id'], 'b')

    def test_disarmed_or_unarmed_end_of_file_returns_to_fallback(self):
        self.worker.inputs = {'a': self.entry('a.mp4', 1, cued=False, started=True), 'b': self.entry('b.mp4', 2)}
        self.worker.active, self.worker.prepared, self.worker.arm = 'a', 'b', ('b', 'a')
        self.worker.submit('disarm', {})
        self.worker.inputs['a']['decoder'].finished = True
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(0)
        status = self.worker.status()
        self.assertIsNone(status['on_air'])
        self.assertEqual(status['prepared']['id'], 'b')  # Still cued for an explicit take.

    def test_armed_next_file_starts_just_before_the_end(self):
        self.worker.inputs = {'a': self.entry('a.mp4', 1, cued=False, started=True), 'b': self.entry('b.mp4', 2)}
        self.worker.active, self.worker.prepared, self.worker.arm = 'a', 'b', ('b', 'a')
        self.worker._tick()
        self.worker.inputs['b']['decoder'].start.assert_not_called()
        self.worker.inputs['a']['decoder'].progress.return_value = {'position_seconds': 59.8, 'duration_seconds': 60.0}
        self.worker._tick()
        self.worker.inputs['b']['decoder'].start.assert_called_once()
        self.worker.output.take.assert_not_called()  # The cut still waits for the end.

    def test_prepared_file_ending_before_take_is_a_failure(self):
        self.worker.inputs['b'] = self.entry('b.mp4', 2)
        self.worker.prepared = 'b'
        self.worker.inputs['b']['decoder'].finished = True
        self.worker._tick()
        self.assertNotIn('b', self.worker.inputs)
        self.assertIn('ended before', self.worker.status()['error'])


class FakeMaster:
    def __init__(self):
        self.calls = []
        self.state = {'state': 'fallback', 'publisher_ready': True, 'can_prepare': True, 'can_take': False,
                      'on_air': None, 'prepared': None}

    def request(self, action='status', body=None):
        if action == 'status':
            return copy.deepcopy(self.state)
        self.calls.append((action, body or {}))
        operation = {'id': str(len(self.calls)), 'state': 'succeeded', 'action': action}
        self.state['operation'] = operation
        if action == 'prepare':
            self.state.update(prepared={'id': 'in' + str(len(self.calls)), **body}, can_take=True)
        if action == 'take':
            self.state.update(state='live', on_air=self.state['prepared'], prepared=None, can_take=False)
        if action == 'cancel':
            self.state.update(prepared=None, can_take=False)
        return operation


class LibraryQueueTests(unittest.TestCase):
    """Queue + coordinator with a fake worker: early cue, arming, reuse and pause."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / 'media'
        root.mkdir()
        for name in ('a.mp4', 'b.mp4'):
            (root / name).write_bytes(b'x')
        library_config = LibraryConfig(True, (LibraryRoot('rec', 'Recordings', root),))
        config = SimpleNamespace(master=MasterConfig(enabled=True, socket_path=Path(self.tmp.name) / 'master.sock'),
                                 feedback=SimpleNamespace(contribution_url=None), tv_thing=TvThingConfig(enabled=False),
                                 library=library_config)
        self.master = FakeMaster()
        self.coordinator = SourceCoordinator(config, None, Mock(), master=self.master)
        self.coordinator.library = MediaLibrary(library_config, prober=lambda path: PLAYABLE, start_worker=False)
        self.addCleanup(self.coordinator.close)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', self.coordinator.execute_queue, Mock(),
                                 poll_seconds=.01, preroll=self.coordinator.preroll_queue,
                                 media_gate=self.coordinator.media_gate, on_pause=self.coordinator.disarm,
                                 on_air=self.coordinator.on_air)
        self.coordinator.queue = self.queue
        self.addCleanup(self.queue.close)

    def add(self, name):
        target, _ = self.coordinator.normalize_target({'source_id': 'library', 'channel_id': 'rec/' + name})
        return self.queue.add_target(target, 'after_current')

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.005)
        self.fail('Timed out: ' + repr(self.queue.status()))

    def test_first_entry_cues_then_takes_without_preparing_twice(self):
        item = self.add('a.mp4')
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual([a for a, _ in self.master.calls], ['prepare', 'take'])
        self.assertIsNone(self.master.calls[0][1]['after_input_id'])
        self.assertEqual(self.master.state['on_air']['channel_id'], 'rec/a.mp4')

    def test_next_entry_is_armed_behind_the_playing_file_and_completes_when_cut_in(self):
        self.master.state.update(state='live', on_air={'id': 'playing', 'source_id': 'library', 'channel_id': 'rec/a.mp4',
                                                       'media': {'position_seconds': 30.0, 'duration_seconds': 95.0}})
        item = self.add('b.mp4')
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).gate_detail and 'left' in self.queue.get(item.id).gate_detail)
        current = self.queue.get(item.id)
        self.assertEqual(current.status, 'queued')
        self.assertEqual(current.gate_detail, 'Plays when a ends · 1:05 left')
        self.assertEqual(self.master.calls[0][1]['after_input_id'], 'playing')
        cued = current.prepared_input_id
        # The worker cuts in the cued file when the playing one ends.
        self.master.state.update(on_air=self.master.state['prepared'], prepared=None, can_take=False)
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual(self.master.state['on_air']['id'], cued)
        self.assertEqual([a for a, _ in self.master.calls], ['prepare'])  # No second prepare or take.

    def test_pause_disarms_and_forgets_the_cue(self):
        self.master.state.update(state='live', on_air={'id': 'playing', 'source_id': 'library', 'channel_id': 'rec/a.mp4'})
        item = self.add('b.mp4')
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).prerolled_at)
        self.queue.pause()
        self.assertIn(('disarm', {}), self.master.calls)
        self.assertIsNone(self.queue.get(item.id).prepared_input_id)

    def test_live_channel_on_air_holds_the_recording_until_master_is_free(self):
        self.master.state.update(state='live', on_air={'id': 'tv', 'source_id': 'tv-thing-digital', 'channel_id': 'wrc'})
        time.sleep(.05)  # The queue's pass already under way read the test card: let it look again.
        item = self.add('a.mp4')
        self.queue.resume()
        self.wait(lambda: 'what is on air ends' in (self.queue.get(item.id).gate_detail or ''))
        self.assertEqual((self.queue.get(item.id).status, self.master.calls), ('queued', []))
        self.master.state.update(state='fallback', on_air=None)  # The test card: master is free.
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual(self.master.state['on_air']['channel_id'], 'rec/a.mp4')


if __name__ == '__main__':
    unittest.main()
