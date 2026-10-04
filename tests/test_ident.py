from datetime import timedelta
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from roku_stream.errors import ConfigError
from roku_stream.config import LibraryConfig, LibraryRoot, MasterConfig, TvThingConfig
from roku_stream.ident import IDENT_SLOT, IdentLease
from roku_stream.library import FileLease
from roku_stream.master import MasterStreamError
from roku_stream.master_worker import MasterWorker
from roku_stream.scheduler import utc_now
from roku_stream.source_coordinator import SourceCoordinator
from roku_stream.source_queue import SourceQueue
from tests.test_library import FakeMaster

TV = {'source_id': 'tv-thing-digital', 'channel_id': 'wrc'}
NEWS = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla'}


def soon(seconds):
    return (utc_now() + timedelta(seconds=seconds)).isoformat()


class FakeFile:
    """A FileInput stand-in: decodes at once, then plays only when started."""
    START_TIMEOUT = 1

    def __init__(self, duration=30.0, position=0.0):
        self.cued = self.started = self.finished = self.closed = self.frozen = False
        self.duration, self.position, self.error = duration, position, None

    def freeze(self):
        if not self.started or self.frozen:
            return False
        self.frozen = True
        return True

    def thaw(self):
        self.frozen = False
        return True

    def ready(self):
        return not self.closed and not self.error

    def cue(self):
        self.cued = True

    def start(self):
        self.cued, self.started = False, True

    def poll(self):
        if self.error:
            raise MasterStreamError(self.error)

    def progress(self):
        return {'position_seconds': self.position, 'duration_seconds': self.duration}

    def status(self):
        return {}

    def close(self):
        self.closed = True


class IdentWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name in ('a.mp4', 'b.mp4'):
            (root / name).write_bytes(b'x')
        self.ident_file = root / 'station-id.mp4'
        self.ident_file.write_bytes(b'id')
        self.library = LibraryConfig(True, (LibraryRoot('rec', 'Recordings', root),))
        config = SimpleNamespace(master=MasterConfig(enabled=True), tv_thing=TvThingConfig(enabled=False),
                                 library=self.library, state_file=root / 'state' / 'jobs.json')
        self.continuity = root / 'state' / 'continuity'
        self.continuity.mkdir(parents=True)
        self.opened = []

        def open_file(output, slot, url):
            decoder = FakeFile()
            decoder.slot, decoder.url = slot, url
            self.opened.append(decoder)
            return decoder

        self.worker = MasterWorker(config, tv=Mock(), status_reader=lambda: {'ready': True, 'source': {'id': 'p'}},
                                   file_decoder_factory=open_file, ident_path=self.ident_file)
        self.worker.output = Mock()
        self.worker.output.healthy.return_value = True
        self.worker.output.status.return_value = {}
        self.worker.publisher_ready = True
        self.worker.output_started = time.monotonic()

    def cue_ident(self):
        self.worker._tick()  # Opens the ID in its own slot...
        self.worker._tick()  # ...and parks it at its start once it decodes.
        self.worker.output.take.reset_mock()
        return self.worker.ident_key

    def program(self, key, name, slot, position, duration, *, on_air):
        decoder = FakeFile(duration, position)
        decoder.started, decoder.cued = on_air, not on_air
        lease = FileLease(self.library, {'source_id': 'library', 'channel_id': 'rec/' + name})
        self.worker.inputs[key] = {'lease': lease, 'decoder': decoder, 'slot': slot, 'was_ready': True,
                                   'check_at': 0, 'url': lease.uri}
        return decoder

    def test_id_is_cued_in_its_own_slot_without_taking_it(self):
        key = self.cue_ident()
        decoder = self.worker.inputs[key]['decoder']
        self.assertEqual((decoder.slot, decoder.cued), (IDENT_SLOT, True))
        self.assertEqual(decoder.url, self.ident_file.resolve().as_uri())
        self.worker.output.take.assert_not_called()
        status = self.worker.status()
        self.assertEqual(status['ident'], {'enabled': True, 'ready': True, 'on_air': False, 'held': False,
                                           'file': 'station-id.mp4', 'duration_seconds': 30.0, 'error': None})
        self.assertIsNone(status['on_air'])

    def test_a_file_with_the_next_one_armed_plays_to_its_end_then_the_id(self):
        ident = self.cue_ident()
        worker = self.worker
        a = self.program('a', 'a.mp4', 1, 590.0, 600.0, on_air=True)
        b = self.program('b', 'b.mp4', 2, 0.0, 600.0, on_air=False)
        worker.active, worker.prepared, worker.arm = 'a', 'b', ('b', 'a')
        worker._tick()
        worker.output.take.assert_not_called()  # 10 s left: the ending is the show's (final scores).
        a.position = 599.8
        worker._tick()
        self.assertFalse(b.started, 'the next file waits for the ID, not this file')
        a.finished = True
        worker._tick()
        worker.output.take.assert_called_once_with(IDENT_SLOT)
        self.assertTrue(a.closed)
        status = worker.status()
        self.assertEqual(status['on_air']['source_id'], 'ident')
        self.assertEqual((status['prepared']['id'], status['prepared']['after_input_id']), ('b', ident))
        self.assertEqual((status['last_completed']['input_id'], status['last_completed']['next_input_id']), ('a', ident))
        self.assertNotIn('cut_for_station_id', status['last_completed'])
        # Just before the ID ends the armed file starts, and it follows the ID on the same publisher.
        id_decoder = worker.inputs[ident]['decoder']
        id_decoder.duration, id_decoder.position = 30.0, 29.8
        worker._tick()
        self.assertTrue(b.started)
        self.assertEqual(b.position, 0.0)
        id_decoder.finished = True
        worker._tick()
        worker.output.take.assert_called_with(2)
        status = worker.status()
        self.assertEqual((status['on_air']['id'], status['last_completed']['input_id']), ('b', ident))

    def test_a_short_file_keeps_its_ending_and_the_id_follows_it(self):
        ident = self.cue_ident()
        worker = self.worker
        a = self.program('a', 'a.mp4', 1, 45.0, 60.0, on_air=True)
        self.program('b', 'b.mp4', 2, 0.0, 600.0, on_air=False)
        worker.active, worker.prepared, worker.arm = 'a', 'b', ('b', 'a')
        worker._tick()
        worker.output.take.assert_not_called()
        a.finished = True
        worker._tick()
        worker.output.take.assert_called_once_with(IDENT_SLOT)
        self.assertEqual((worker.active, worker.arm), (ident, ('b', ident)))
        self.assertEqual(worker.status()['last_completed']['next_input_id'], ident)

    def test_a_program_with_nothing_next_is_followed_by_the_id_then_fallback(self):
        ident = self.cue_ident()
        worker = self.worker
        a = self.program('a', 'a.mp4', 1, 590.0, 600.0, on_air=True)
        worker.active = 'a'
        worker._tick()
        worker.output.take.assert_not_called()  # Nothing waits behind it: it plays to the end.
        a.finished = True
        worker._tick()
        worker.output.take.assert_called_once_with(IDENT_SLOT)
        worker.inputs[ident]['decoder'].finished = True
        worker._tick()
        worker.output.take.assert_called_with(0)
        self.assertIsNone(worker.status()['on_air'])
        # A fresh copy is cued for the next time.
        self.assertIsNotNone(worker.ident_key)
        self.assertNotEqual(worker.ident_key, ident)

    def test_a_schedule_request_lets_a_recording_ending_inside_the_id_finish(self):
        ident = self.cue_ident()
        worker = self.worker
        a = self.program('a', 'a.mp4', 1, 575.0, 600.0, on_air=True)
        worker.active = 'a'
        self.assertEqual(worker.submit('ident', {}), {'accepted': True})
        worker._tick()
        worker.output.take.assert_not_called()  # 25 s left: it ends before the timed entry.
        self.assertFalse(a.closed)
        a.finished = True
        worker._tick()
        worker.output.take.assert_called_once_with(IDENT_SLOT)  # Then the ID, and the take waits for it.
        self.assertEqual(worker.active, ident)
        self.assertEqual(worker.status()['last_station_id']['after']['channel_id'], 'rec/a.mp4')

    def test_a_schedule_request_cuts_a_recording_the_timed_entry_would_cut_anyway(self):
        ident = self.cue_ident()
        worker = self.worker
        a = self.program('a', 'a.mp4', 1, 100.0, 600.0, on_air=True)
        worker.active = 'a'
        worker.submit('ident', {})
        worker._tick()
        worker.output.take.assert_called_once_with(IDENT_SLOT)
        self.assertTrue(a.closed)
        self.assertEqual(worker.active, ident)
        self.assertTrue(worker.status()['last_completed']['cut_for_station_id'])

    def test_the_old_follow_hint_is_refused(self):
        with self.assertRaises(ConfigError):
            self.worker.submit('follow', {'input_id': 'a'})

    def test_a_schedule_request_replaces_the_end_of_a_live_program(self):
        ident = self.cue_ident()
        worker = self.worker
        lease = Mock(lane='digital', target={'source_id': 'tv-thing-digital', 'channel_id': '7.1'}, generation='g')
        lease.check.return_value = 'rtsp://tuner'
        lease.release.return_value = True
        decoder = Mock(finished=False)
        decoder.ready.return_value = True
        decoder.status.return_value = {}
        worker.inputs['tv'] = {'lease': lease, 'decoder': decoder, 'slot': 1, 'was_ready': True,
                               'check_at': 0, 'url': 'rtsp://tuner'}
        worker.active = 'tv'
        self.assertEqual(worker.submit('ident', {}), {'accepted': True})
        worker._tick()
        worker.output.take.assert_called_once_with(IDENT_SLOT)
        lease.release.assert_called_once()  # The tuner is free for the next program.
        status = worker.status()
        self.assertEqual((status['on_air']['id'], status['last_station_id']['after']['channel_id']), (ident, '7.1'))

    def air_ident_over_a_program(self):
        ident = self.cue_ident()
        self.program('a', 'a.mp4', 1, 10, 600, on_air=True)
        self.worker.active = 'a'
        self.worker.submit('ident', {})
        self.worker._tick()
        self.assertEqual(self.worker.active, ident)
        return ident, self.worker.inputs[ident]['decoder']

    def test_the_id_holds_its_end_card_until_the_next_source_is_ready(self):
        ident, decoder = self.air_ident_over_a_program()
        self.assertEqual(self.worker.submit('ident_hold', {'hold': True}), {'accepted': True})
        decoder.position = 20.0
        self.worker._tick()
        self.assertFalse(decoder.frozen, 'the ID plays on until its end card')
        decoder.position = 27.95
        self.worker._tick()
        self.assertTrue(decoder.frozen)
        self.assertTrue(self.worker.status()['ident']['held'])
        self.worker._tick()
        self.assertEqual((self.worker.active, decoder.frozen), (ident, True))
        self.worker.submit('ident_hold', {'hold': False})  # Ready: the iris closes, then the take.
        self.worker._tick()
        self.assertFalse(decoder.frozen)
        self.assertFalse(self.worker.status()['ident']['held'])

    def test_an_id_with_no_hold_plays_through(self):
        _, decoder = self.air_ident_over_a_program()
        decoder.position = 28.5
        self.worker._tick()
        self.assertFalse(decoder.frozen)

    def test_a_held_end_card_gives_up_after_its_limit(self):
        _, decoder = self.air_ident_over_a_program()
        self.worker.submit('ident_hold', {'hold': True})
        decoder.position = 28.0
        self.worker._tick()
        self.assertTrue(decoder.frozen)
        self.worker.ident_hold_until = time.monotonic() - 1
        self.worker._tick()
        self.assertFalse(decoder.frozen)

    def test_a_hold_belongs_to_the_airing(self):
        ident, _ = self.air_ident_over_a_program()
        self.worker.submit('ident_hold', {'hold': True})
        self.worker._drop(ident)  # Cut away (a take), or ended.
        self.assertIsNone(self.worker.ident_hold_until)
        with self.assertRaises(Exception):
            self.worker.submit('ident_hold', {'hold': 'yes'})

    def test_a_continuity_announcement_plays_once_in_place_of_the_id(self):
        self.cue_ident()
        announcement = self.continuity / 'phillies-then-white-sox.mp4'
        announcement.write_bytes(b'announcement')
        self.assertEqual(self.worker.submit('ident_file', {'path': str(announcement)}), {'accepted': True})
        self.worker._tick()  # The plain ID's cued copy makes way...
        self.worker._tick()  # ...for the announcement, cued at its start.
        self.assertEqual(self.worker.status()['ident']['file'], announcement.name)
        self.assertEqual(self.opened[-1].url, announcement.resolve().as_uri())
        self.program('a', 'a.mp4', 1, 10, 600, on_air=True)
        self.worker.active = 'a'
        self.worker.submit('ident', {})
        self.worker._tick()
        self.assertEqual(self.worker.status()['last_station_id']['file'], announcement.name)
        self.worker._drop(self.worker.active)  # The announcement has aired...
        self.worker._tick()
        self.worker._tick()
        self.assertEqual(self.worker.status()['ident']['file'], 'station-id.mp4', '...and the plain ID is cued again')

    def test_only_continuity_files_can_replace_the_id(self):
        for path in ('/etc/passwd', str(self.ident_file), str(self.continuity / 'missing.mp4')):
            with self.assertRaises(Exception):
                self.worker.submit('ident_file', {'path': path})
        (self.continuity / 'note.txt').write_text('x')
        with self.assertRaises(Exception):
            self.worker.submit('ident_file', {'path': str(self.continuity / 'note.txt')})
        self.assertEqual(self.worker.submit('ident_file', {'path': None}), {'accepted': True})

    def test_a_schedule_request_with_nothing_on_air_is_ignored(self):
        self.cue_ident()
        self.worker.submit('ident', {})
        self.worker._tick()
        self.worker.output.take.assert_not_called()

    def test_the_sports_id_can_start_from_the_test_card_and_returns_to_it(self):
        ident = self.cue_ident()
        self.assertEqual(self.worker.submit('ident', {'from_test_card': True}), {'accepted': True})
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(IDENT_SLOT)
        status = self.worker.status()
        self.assertEqual((status['on_air']['id'], status['last_station_id']['after']), (ident, None))
        self.worker.output.take.reset_mock()
        self.worker.inputs[ident]['decoder'].finished = True  # Nothing was taken: back to the card.
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(0)
        self.assertIsNone(self.worker.active)

    def test_a_test_card_request_is_one_shot(self):
        self.cue_ident()
        self.worker.submit('ident', {'from_test_card': True})
        self.worker.ident_request = None  # Stale: never acted on.
        self.worker._tick()
        self.worker.submit('ident', {})  # A plain request later stays a plain one.
        self.worker._tick()
        self.worker.output.take.assert_not_called()

    def test_a_cued_id_that_fails_is_not_a_master_error(self):
        ident = self.cue_ident()
        self.worker.inputs[ident]['decoder'].error = 'Could not decode'
        self.worker._tick()
        status = self.worker.status()
        self.assertIsNone(status['error'])
        self.assertEqual(status['ident']['error'], 'Could not decode')
        self.assertIsNone(self.worker.ident_key)
        self.worker._tick()  # Retries later, not on every tick.
        self.assertEqual(len(self.opened), 1)

    def test_a_rebuilt_file_replaces_the_cued_copy(self):
        ident = self.cue_ident()
        old = self.worker.inputs[ident]['decoder']
        self.ident_file.write_bytes(b'a new id')
        self.worker.inputs[ident]['ident_check_at'] = 0
        self.worker._tick()
        self.assertTrue(old.closed)
        self.assertEqual(len(self.opened), 2)

    def test_no_file_means_no_id(self):
        self.ident_file.unlink()
        self.worker._tick()
        self.assertEqual(self.opened, [])
        self.assertFalse(self.worker.status()['ident']['ready'])

    def test_without_a_path_the_worker_never_opens_an_id(self):
        self.worker.ident_path = None
        self.worker._tick()
        self.assertEqual(self.opened, [])
        self.assertFalse(self.worker.status()['ident']['enabled'])


class IdentLeaseTests(unittest.TestCase):
    def test_lease_notices_a_rebuilt_or_removed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'id.mp4'
            path.write_bytes(b'one')
            lease = IdentLease(path)
            self.assertEqual(lease.target['source_id'], 'ident')
            self.assertTrue(lease.current())
            self.assertEqual(lease.check(), path.resolve().as_uri())
            path.write_bytes(b'two!')
            self.assertFalse(lease.current())
            path.unlink()
            self.assertFalse(lease.current())
            self.assertTrue(lease.release())


class IdentQueueTests(unittest.TestCase):
    """The queue asks for the ID 30 s (here 0.3 s) before a timed entry or a take's end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events = []
        self.game = {'finished': False}
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json',
                                 lambda item: self.events.append(('take', item.target, time.monotonic())) or {},
                                 lambda *_: dict(self.game), poll_seconds=.01, hold_poll_seconds=.01,
                                 on_hold_end=lambda hold: self.events.append(('end', hold['target'], time.monotonic())),
                                 ident=lambda target: self.events.append(('ident', target, time.monotonic())),
                                 ident_seconds=.3, final_buffer_seconds=0)
        self.addCleanup(self.queue.close)

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(repr(self.events))

    def kinds(self):
        return [kind for kind, *_ in self.events]

    def test_a_timed_entry_gets_the_id_its_length_before_release(self):
        self.queue.resume()
        item = self.queue.add_target(NEWS, 'at_time', run_at=soon(.8))
        self.wait(lambda: 'take' in self.kinds())
        (_, target, asked), (_, _, taken) = self.events
        self.assertEqual((self.kinds(), target), (['ident', 'take'], NEWS))
        self.assertAlmostEqual(taken - asked, .3, delta=.1)
        self.assertIsNotNone(self.queue.get(item.id).ident_at)

    def test_an_entry_queued_inside_the_window_goes_without(self):
        self.queue.ident_seconds = 5
        self.queue.resume()
        self.queue.add_target(NEWS, 'at_time', run_at=soon(.4))
        self.wait(lambda: 'take' in self.kinds())
        self.assertEqual(self.kinds(), ['take'])

    def test_a_paused_queue_plays_no_id(self):
        self.queue.add_target(NEWS, 'at_time', run_at=soon(.4))
        time.sleep(.6)
        self.assertEqual(self.events, [])

    def test_a_timed_take_ends_with_the_id(self):
        self.queue.hold_for(TV, {'until': soon(.7)})
        self.wait(lambda: 'end' in self.kinds())
        (_, _, asked), (_, target, ended) = self.events
        self.assertEqual((self.kinds(), target), (['ident', 'end'], TV))
        self.assertAlmostEqual(ended - asked, .3, delta=.1)

    def test_a_held_game_gets_the_id_when_it_is_final(self):
        self.queue.hold_for(TV, {'game': {'league': 'mlb', 'game_pk': 1, 'game_date': '2026-09-29'}})
        time.sleep(.1)
        self.assertEqual(self.events, [])
        self.game = {'finished': True}
        self.wait(lambda: 'end' in self.kinds())
        self.assertEqual(self.kinds(), ['ident', 'end'])

    def test_a_roku_entry_prepares_as_soon_as_the_id_frees_the_roku(self):
        roku = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
        prerolls = []
        self.queue.preroll = lambda item: prerolls.append(time.monotonic()) or ('prepared' if len(prerolls) > 1 else 'skipped')
        self.queue.retry_seconds = 60  # Without the ID's nudge, the next try would be a minute away.
        self.queue.resume()
        self.queue.add_target(roku, 'at_time', run_at=soon(1.0))
        self.wait(lambda: len(prerolls) >= 2)
        asked = next(at for kind, _, at in self.events if kind == 'ident')
        self.assertLess(prerolls[1] - asked, .2)

    def test_a_failing_id_never_holds_up_the_queue(self):
        def broken(target):
            raise MasterStreamError('worker unavailable')
        self.queue.ident = broken
        self.queue.resume()
        self.queue.add_target(NEWS, 'at_time', run_at=soon(.5))
        self.wait(lambda: 'take' in self.kinds())


class IdentCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = SimpleNamespace(master=MasterConfig(enabled=True, socket_path=Path(self.tmp.name) / 'master.sock'),
                                 feedback=SimpleNamespace(contribution_url=None), tv_thing=TvThingConfig(enabled=False),
                                 library=LibraryConfig(False, ()))
        self.master = FakeMaster()
        self.coordinator = SourceCoordinator(config, Mock(), Mock(), master=self.master, publisher_reader=lambda: 'p')
        self.addCleanup(self.coordinator.close)
        self.master.state['ident'] = {'ready': True}

    def item(self, prepared_input_id=None):
        return SimpleNamespace(prepared_input_id=prepared_input_id)

    def test_station_id_is_asked_for_only_over_a_program(self):
        self.assertEqual(self.coordinator.station_id(NEWS), 'skipped')  # Nothing on air.
        self.master.state['on_air'] = {'id': 'tv', **TV}
        self.assertEqual(self.coordinator.station_id(TV), 'skipped')  # The next entry is what is on air.
        self.master.state['ident'] = {'ready': False}
        self.assertEqual(self.coordinator.station_id(NEWS), 'skipped')
        self.master.state['ident'] = {'ready': True}
        self.assertEqual(self.coordinator.station_id(NEWS), 'requested')
        self.assertEqual(self.master.calls, [('ident', {})])
        self.master.state['on_air'] = {'id': 'id', 'source_id': 'ident', 'channel_id': 'station-id'}
        self.assertEqual(self.coordinator.station_id(None), 'skipped')  # Already on air.

    def test_the_sports_id_plays_from_the_test_card(self):
        self.master.state['ident'] = {'ready': True, 'file': 'sports-0123456789abcdef.mp4'}
        self.assertEqual(self.coordinator.station_id(TV), 'requested')  # A game is next.
        self.assertEqual(self.master.calls, [('ident', {'from_test_card': True})])
        self.master.state['on_air'] = {'id': 'news', **NEWS}
        self.assertEqual(self.coordinator.station_id(TV), 'requested')  # Over a program, as the ID.
        self.assertEqual(self.master.calls[-1], ('ident', {}))
        self.master.state['ident'] = {'ready': False, 'file': 'sports-0123456789abcdef.mp4'}
        del self.master.state['on_air']
        self.assertEqual(self.coordinator.station_id(TV), 'skipped')
        self.master.state['ident'] = {'ready': True, 'file': '0123456789abcdef0123.mp4'}  # An announcement.
        self.assertEqual(self.coordinator.station_id(TV), 'skipped')
        self.assertEqual(len(self.master.calls), 2)

    def test_a_file_armed_behind_the_id_waits_for_it(self):
        self.master.state.update(on_air={'id': 'id', 'source_id': 'ident'},
                                 prepared={'id': 'b', 'source_id': 'library', 'after_input_id': 'id'})
        self.assertFalse(self.coordinator.media_gate(self.item('b'))['finished'])
        # Anything else prepares during the ID; its take waits for the ID's end.
        self.assertTrue(self.coordinator.media_gate(self.item())['finished'])

    def test_waiting_behind_a_file_leaves_its_ending_alone(self):
        self.master.state['on_air'] = {'id': 'a', 'source_id': 'library', 'channel_id': 'rec/a.mp4',
                                       'media': {'position_seconds': 590, 'duration_seconds': 600}}
        gate = self.coordinator.media_gate(self.item())
        self.assertEqual((gate['finished'], gate['status']), (False, 'Plays when rec/a.mp4 ends · 0:10 left'))
        self.assertEqual(self.master.calls, [])  # The ID follows the file; nothing asks it to cut in.

    def test_a_queued_take_waits_for_the_end_of_the_id(self):
        self.master.state['on_air'] = {'id': 'id', 'source_id': 'ident',
                                       'media': {'position_seconds': 29.0, 'duration_seconds': 30.0}}

        def ends():
            time.sleep(.15)
            self.master.state['on_air']['media']['position_seconds'] = 29.6
        threading.Thread(target=ends).start()
        started = time.monotonic()
        self.coordinator._after_station_id()
        self.assertGreaterEqual(time.monotonic() - started, .14)

    def test_a_take_after_a_sports_break_waits_for_the_whole_sports_id(self):
        # The break before a game is two IDs long (what is next, then the Sports ID): the
        # take waits out what is left of it, not one ID's 30 s.
        self.master.state['on_air'] = {'id': 'id', 'source_id': 'ident',
                                       'media': {'position_seconds': 10.0, 'duration_seconds': 60.0}}
        clock = [0.]

        def sleep(seconds):  # Each wait plays a second of the break.
            clock[0] += 1
            self.master.state['on_air']['media']['position_seconds'] += 1
        fake_time = SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep, time=time.time)
        with patch('roku_stream.source_coordinator.time', fake_time):
            self.coordinator._after_station_id()
        self.assertGreaterEqual(self.master.state['on_air']['media']['position_seconds'], 59.5)

    def test_a_sports_break_covers_a_source_until_its_first_end_card(self):
        def at(position, duration):
            self.master.state['on_air'] = {'id': 'id', 'source_id': 'ident',
                                           'media': {'position_seconds': position, 'duration_seconds': duration}}
            return self.coordinator._ident_left()
        self.assertAlmostEqual(at(10., 30.), 19.5)  # The plain ID: until its tail.
        self.assertAlmostEqual(at(10., 60.), 17.9)  # A sports break: until it would hold.
        self.assertAlmostEqual(at(40., 60.), 19.5)  # Already in the Sports ID: until its tail.
        self.master.state['on_air'] = {'id': 'tv', **TV}
        self.assertIsNone(self.coordinator._ident_left())

    def test_a_sports_break_holds_in_its_first_half_never_in_the_sports_id(self):
        item = SimpleNamespace(id='q', target=TV, run_at=None)
        self.coordinator.queue = MagicMock()
        for position, held in ((10., True), (40., False)):
            self.master.calls.clear()
            self.master.state['on_air'] = {'id': 'id', 'source_id': 'ident',
                                           'media': {'position_seconds': position, 'duration_seconds': 60.0}}
            with patch.object(self.coordinator, '_after_station_id'):
                self.coordinator._queue_request('_queue', item)
            holds = [body['hold'] for action, body in self.master.calls if action == 'ident_hold']
            self.assertEqual(True in holds, held, position)

    def test_preparing_under_the_id_holds_its_end_card_until_the_take(self):
        self.master.state['on_air'] = {'id': 'id', 'source_id': 'ident',
                                       'media': {'position_seconds': 29.8, 'duration_seconds': 30.0}}
        item = SimpleNamespace(id='q', target=TV, run_at=None)
        self.coordinator.queue = MagicMock()
        self.coordinator._queue_request('_queue', item)
        holds = [body['hold'] for action, body in self.master.calls if action == 'ident_hold']
        self.assertEqual(holds, [True, False, False])  # Held; released before the take; and at the end.
        order = [action for action, _ in self.master.calls]
        # The hold is asked for before preparing, and released before the take.
        self.assertEqual([a for a in order if a in ('ident_hold', 'prepare', 'take')][:4],
                         ['ident_hold', 'prepare', 'ident_hold', 'take'])

    def test_preparing_with_no_id_on_air_asks_for_no_hold(self):
        self.master.state['on_air'] = {'id': 'tv', **NEWS}
        self.coordinator._queue_request('_queue', SimpleNamespace(id='q', target=TV, run_at=None))
        self.assertNotIn('ident_hold', [action for action, _ in self.master.calls])

    def test_a_take_does_not_wait_when_no_id_is_on_air(self):
        self.master.state['on_air'] = {'id': 'tv', **TV}
        started = time.monotonic()
        self.coordinator._after_station_id()
        self.assertLess(time.monotonic() - started, .05)


if __name__ == '__main__':
    unittest.main()
