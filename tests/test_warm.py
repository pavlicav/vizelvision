"""Warm-ups: the Roku entry that follows a program about to end is prepared while another
source finishes it (a game's closing stretch; a recording or a held show's last 3 minutes)."""
import copy
from datetime import timedelta
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.errors import ControlBusyError, CueCancelledError
from roku_stream.master import MasterStreamError
from roku_stream.networks import Networks
from roku_stream.scheduler import parse_time, utc_now
from roku_stream.source_queue import ENDING_SECONDS, SourceQueue, WARM_ATTEMPTS
from roku_stream.sports import EspnScoreboard, SportsCatalog, closing
from tests.test_antenna import FakeTv
import tests.test_baseball as baseball_tests
import tests.test_source_coordinator as coordinator_tests

TV = {'source_id': 'tv-thing-digital', 'channel_id': 'wttg_dt_5_1'}
NBC = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
ESPN = {'source_id': 'youtube-tv', 'channel_id': 'ESPN'}
MLB = {'source_id': 'mlb', 'channel_id': '849835', 'date': '2026-10-03'}
GAME = {'league': 'mlb', 'game_pk': 123, 'game_date': '2026-10-03', 'title': 'Phillies at Braves'}


def soon(seconds):
    return (utc_now() + timedelta(seconds=seconds)).isoformat()


def key(target):
    return tuple(target.get(k) for k in ('source_id', 'channel_id', 'date'))


class ClosingTests(unittest.TestCase):
    def test_baseball_from_the_9th_inning(self):
        self.assertFalse(closing('mlb', {'state': 'Live', 'period': 8}))
        self.assertTrue(closing('mlb', {'state': 'Live', 'period': 9}))
        self.assertTrue(closing('mlb', {'state': 'Live', 'period': 12}))
        self.assertFalse(closing('mlb', {'state': 'Preview', 'period': None}))
        self.assertTrue(closing('mlb', {'state': 'Final', 'finished': True}))

    def test_football_in_the_last_two_minutes_or_overtime(self):
        self.assertFalse(closing('nfl', {'state': 'in', 'period': 4, 'clock': 151.0}))
        self.assertTrue(closing('nfl', {'state': 'in', 'period': 4, 'clock': 120.0}))
        self.assertFalse(closing('nfl', {'state': 'in', 'period': 2, 'clock': 30.0}), 'not before halftime')
        self.assertTrue(closing('nfl', {'state': 'in', 'period': 5, 'clock': 540.0}))
        self.assertFalse(closing('nfl', {'state': 'in', 'period': 4}), 'no clock: wait for one')
        self.assertTrue(closing('nfl', {'state': 'post', 'period': 4, 'clock': 0.0}))
        self.assertFalse(closing('nfl', {'state': 'pre', 'period': 0, 'clock': 0.0}))

    def test_hockey_counts_down_and_soccer_counts_up(self):
        self.assertTrue(closing('nhl', {'state': 'in', 'period': 3, 'clock': 90.0}))
        self.assertFalse(closing('nhl', {'state': 'in', 'period': 3, 'clock': 600.0}))
        self.assertFalse(closing('nwsl', {'state': 'in', 'period': 2, 'clock': 5100.0}))
        self.assertTrue(closing('nwsl', {'state': 'in', 'period': 2, 'clock': 5300.0}))

    def test_espn_status_carries_the_clock_and_game_status_says_closing(self):
        event = {'id': '1', 'name': 'Lions at Panthers', 'date': '2026-10-05T00:20Z', 'competitions': [{}],
                 'status': {'clock': 83.0, 'displayClock': '1:23', 'period': 4,
                            'type': {'state': 'in', 'completed': False, 'shortDetail': '1:23 - 4th'}}}
        game = EspnScoreboard._normalize('nfl', event)
        self.assertEqual((game['clock'], game['period']), (83.0, 4))
        catalog = SportsCatalog(None, Mock())
        catalog.game = Mock(return_value=game)
        self.assertTrue(catalog.game_status(1, '2026-10-04', 'nfl')['closing'])

    def test_mlb_game_status_says_closing_from_the_9th(self):
        case = baseball_tests.BaseballTests('test_game_status_marks_final_as_finished')
        with tempfile.TemporaryDirectory() as directory:
            config = case.config(Path(directory))
            for inning, expected in ((8, False), (9, True)):
                baseball = case.catalog(config, linescore={'currentInning': inning, 'inningState': 'Top'})
                self.assertIs(SportsCatalog(config, baseball).game_status(42, '2026-09-02', 'mlb')['closing'], expected)


class WarmQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.on = dict(TV, id='tv')  # What master shows.
        self.game = {'finished': False, 'status': 'Top 8th', 'closing': False}
        self.warmed, self.aired, self.stops = [], [], []
        self.prepared = set()
        self.result = 'prepared'
        self.file_done = False
        # A warm-up that runs until released (block), to race a release against it.
        self.block, self.warming, self.release, self.cancelled = False, threading.Event(), threading.Event(), False

        def preroll(item):
            if self.warming.is_set():  # One preparation at a time, as in the coordinator.
                raise ControlBusyError('A master operation is already running')
            self.warmed.append(copy.deepcopy(item))
            if self.block:
                self.warming.set()
                self.release.wait(3)
                self.warming.clear()
                if self.cancelled:
                    raise MasterStreamError('Master preparation cancelled')
            if isinstance(self.result, Exception):
                raise self.result
            if self.result == 'prepared':
                self.prepared.add(key(item.target))
            return self.result

        def execute(item):
            if self.warming.is_set():
                raise ControlBusyError('A master operation is already running')
            self.aired.append(item.target)
            self.on = dict(item.target, id='taken')
            return {'on_air': self.on}

        def stop(item_id):
            self.stops.append(item_id)
            self.cancelled = True
            self.release.set()

        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', execute, lambda *_: dict(self.game),
                                 poll_seconds=.01, hold_poll_seconds=.01, retry_seconds=.05, final_buffer_seconds=0,
                                 preroll=preroll, on_air=lambda: self.on, ready=lambda target: key(target) in self.prepared,
                                 stop_preroll=stop, media_gate=lambda item: {'finished': self.file_done,
                                                                             'status': 'Plays when the recording ends'})
        self.addCleanup(self.queue.close)

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(repr(self.queue.status()))

    def test_a_game_in_its_closing_stretch_warms_what_follows_it(self):
        nbc = self.queue.add_target(NBC, 'at_time', run_at=soon(.05))  # Due while the game is held.
        self.queue.hold_for(self.on, {'game': GAME})
        self.wait(lambda: self.queue.status()['hold']['detail'] == 'Top 8th')
        time.sleep(.1)
        self.assertEqual(self.warmed, [])
        self.game.update(status='Top 9th', closing=True)
        self.wait(lambda: self.warmed)
        self.assertEqual((self.warmed[0].id, self.warmed[0].target), (nbc.id, NBC))
        self.assertIsNone(self.warmed[0].run_at, 'a final has no time: YouTube TV takes as long as it takes')
        self.wait(lambda: self.queue.get(nbc.id).gate_status == 'prepared')
        self.assertEqual(self.queue.get(nbc.id).gate_detail, 'Prepared early; goes on when Phillies at Braves ends')
        self.assertTrue(self.queue.status()['paused'], 'the game stays on until its final')
        time.sleep(.1)
        self.assertEqual((len(self.warmed), self.aired), (1, []), 'ready: not prepared again')
        self.game.update(finished=True, status='Final')
        self.wait(lambda: self.aired == [NBC])

    def test_a_held_game_with_nothing_waiting_warms_the_schedule_block(self):
        self.queue.schedule_now = lambda: {'target': NBC, 'title': 'NBC evening', 'key': 'k1'}
        self.game.update(status='Bottom 9th', closing=True)
        self.queue.hold_for(self.on, {'game': GAME})
        self.wait(lambda: self.warmed)
        self.assertEqual((self.warmed[0].id, self.warmed[0].target), ('schedule:k1', NBC))
        self.wait(lambda: (self.queue.status()['warm'] or {}).get('state') == 'ready')
        self.assertEqual(self.queue.status()['warm'], {'target': NBC, 'title': 'NBC evening', 'ends': 'Phillies at Braves',
                                                       'state': 'ready', 'error': None})

    def test_a_show_held_to_an_end_time_warms_in_its_last_three_minutes(self):
        game = self.queue.add_target(MLB, 'after_current')
        self.queue.hold_for(self.on, {'until': soon(ENDING_SECONDS + 200), 'program': {'id': 'p', 'title': 'MLB Baseball'}})
        time.sleep(.15)
        self.assertEqual(self.warmed, [])
        with self.queue._condition:
            self.queue.hold['until'] = soon(ENDING_SECONDS - 10)
        self.wait(lambda: self.warmed)
        self.assertEqual(self.warmed[0].id, game.id)
        self.assertEqual(self.warmed[0].run_at, self.queue.status()['hold']['until'], 'ready by the end time')
        self.wait(lambda: self.queue.get(game.id).gate_detail == 'Prepared early; goes on when MLB Baseball ends')

    def test_nothing_is_warmed_while_the_roku_is_on_air(self):
        self.on = dict(ESPN, id='roku')
        self.game.update(closing=True)
        self.queue.add_target(NBC, 'at_time', run_at=soon(.05))
        self.queue.hold_for(self.on, {'game': GAME})
        self.wait(lambda: self.queue.status()['hold']['detail'])
        time.sleep(.15)
        self.assertEqual(self.warmed, [])

    def test_a_scheduled_games_return_warms_in_the_closing_stretch(self):
        back = self.queue.add_scheduled({'target': NBC, 'run_at': soon(-3600), 'key': 'k', 'kind': 'backup',
                                         'title': 'NBC', 'after_game': dict(GAME), 'skip_after': soon(3600)})
        self.queue.resume()
        self.wait(lambda: self.queue.get(back.id).gate_detail == 'Top 8th')
        time.sleep(.1)
        self.assertEqual(self.warmed, [])
        self.game.update(status='Top 9th', closing=True)
        self.wait(lambda: self.warmed)
        self.assertEqual((self.warmed[0].id, self.warmed[0].run_at), (back.id, None))
        self.wait(lambda: self.queue.get(back.id).gate_detail == 'Top 9th · prepared early')
        self.game.update(finished=True, status='Final')
        self.wait(lambda: self.aired == [NBC])

    def test_a_roku_entry_after_a_recording_warms_in_its_last_three_minutes(self):
        self.on = {'id': 'file', 'source_id': 'library', 'channel_id': 'tv-recordings/a.mp4',
                   'media': {'position_seconds': 0, 'duration_seconds': 1200}}
        nbc = self.queue.add_target(NBC, 'after_current')
        self.queue.resume()
        self.wait(lambda: self.queue.get(nbc.id).gate_detail == 'Plays when the recording ends')
        time.sleep(.1)
        self.assertEqual(self.warmed, [], 'not at once: it would be stale twenty minutes later')
        self.on['media']['position_seconds'] = 1050
        self.wait(lambda: self.warmed)
        self.assertAlmostEqual(parse_time(self.warmed[0].run_at).timestamp(), time.time() + 150, delta=3)
        self.wait(lambda: self.queue.get(nbc.id).gate_detail == 'Plays when the recording ends · prepared early')
        self.file_done = True
        self.wait(lambda: self.aired == [NBC])
        self.assertEqual(len(self.warmed), 1)

    def test_a_failing_warm_up_is_tried_three_times_then_left_to_the_cut(self):
        self.result = MasterStreamError('guide row not found')
        self.game.update(closing=True)
        nbc = self.queue.add_target(NBC, 'at_time', run_at=soon(.05))
        self.queue.hold_for(self.on, {'game': GAME})
        self.wait(lambda: len(self.warmed) == WARM_ATTEMPTS)
        time.sleep(.3)
        self.assertEqual(len(self.warmed), WARM_ATTEMPTS)
        self.assertEqual(self.queue.get(nbc.id).gate_detail,
                         'Early preparation failed (guide row not found); it prepares when it goes on')
        self.assertEqual(self.queue.status()['warm']['state'], 'failed')

    def test_a_release_for_another_channel_stops_the_warm_up(self):
        self.block = True
        self.game.update(closing=True)
        back = self.queue.add_scheduled({'target': NBC, 'run_at': soon(-3600), 'key': 'k', 'kind': 'backup',
                                         'title': 'NBC', 'after_game': dict(GAME), 'skip_after': soon(3600)})
        self.queue.resume()
        self.wait(self.warming.is_set)
        self.queue.add_target(ESPN, 'now')
        self.wait(lambda: self.aired == [ESPN])
        self.assertEqual(self.stops, [back.id])
        self.assertEqual(self.queue.status()['warm'], None, 'ESPN is on the Roku now')

    def test_a_release_for_the_same_channel_waits_for_the_warm_up(self):
        self.block = True
        self.game.update(closing=True)
        self.queue.add_scheduled({'target': NBC, 'run_at': soon(-3600), 'key': 'k', 'kind': 'backup',
                                  'title': 'NBC', 'after_game': dict(GAME), 'skip_after': soon(3600)})
        self.queue.resume()
        self.wait(self.warming.is_set)
        self.game.update(finished=True, status='Final')
        time.sleep(.2)
        self.assertEqual((self.aired, self.stops), ([], []))
        self.release.set()
        self.wait(lambda: self.aired == [NBC])

    def test_a_warm_up_is_admitted_behind_a_held_take_but_not_after_a_pause(self):
        self.queue.preroll = None
        nbc = self.queue.add_target(NBC, 'at_time', run_at=soon(60))
        self.queue.hold_for(self.on, {'game': GAME})
        with self.assertRaises(ControlBusyError):
            self.queue.admitted(nbc.id, preroll=True)
        self.queue._warming = nbc.id
        self.queue.admitted(nbc.id, preroll=True)
        self.queue.pause()
        with self.assertRaises(ControlBusyError):
            self.queue.admitted(nbc.id, preroll=True)


class WarmCoordinatorTests(unittest.TestCase):
    def setUp(self):
        case = coordinator_tests.CoordinatorTests('test_prime_game_preparation_creates_a_game_specific_claim')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case, self.coordinator, self.master = case, case.coordinator, case.master
        self.coordinator.networks = Networks(case.config, FakeTv())  # NBC has the antenna as backup.
        self.navigated = []

        def play(channel):
            with self.coordinator.navigation_guard():
                self.navigated.append((channel, copy.deepcopy(self.master.state['on_air'])))
                return case.result
        case.controller.play.side_effect = play
        self.master.state.update(state='live', on_air={'id': 'tv', **TV})

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail('timed out')

    def test_the_roku_is_prepared_under_a_game_on_the_antenna_and_taken_without_navigating_again(self):
        game = {'finished': False, 'status': 'Top 8th', 'closing': False}
        queue = SourceQueue(Path(self.case.directory.name) / 'queue.json', self.coordinator.execute_queue,
                            lambda *_: dict(game), poll_seconds=.01, hold_poll_seconds=.01, final_buffer_seconds=0,
                            preroll=self.coordinator.preroll_queue, on_air=self.coordinator.on_air,
                            ready=self.coordinator.roku_ready, stop_preroll=self.coordinator.stop_preroll)
        self.addCleanup(queue.close)
        self.coordinator.queue = queue
        nbc = queue.add_target(NBC, 'at_time', run_at=soon(.05))  # Its time passes during the game.
        queue.hold_for(self.master.state['on_air'], {'game': GAME})
        time.sleep(.2)
        self.assertEqual(self.navigated, [])
        game.update(status='Bottom 9th', closing=True)
        self.wait(lambda: queue.get(nbc.id).gate_status == 'prepared')
        self.assertEqual(self.master.state['on_air']['channel_id'], 'wttg_dt_5_1', 'the game stays on')
        self.assertEqual(self.master.state['prepared']['channel_id'], 'NBC')
        self.assertEqual(self.navigated[0][1]['channel_id'], 'wttg_dt_5_1')
        self.assertNotIn('fallback', [action for action, _ in self.master.calls])
        game.update(finished=True, status='Final')
        self.wait(lambda: queue.get(nbc.id).status == 'succeeded')
        self.assertEqual(self.master.state['on_air']['channel_id'], 'NBC')
        self.assertEqual(len(self.navigated), 1, 'taken from the warm-up, not navigated again')
        self.assertNotIn('antenna', queue.get(nbc.id).result)

    def test_stop_preroll_stops_the_navigation_and_leaves_the_queue_alone(self):
        stopped = threading.Event()
        self.addCleanup(stopped.set)

        def play(*_):
            with self.coordinator.navigation_guard():
                self.assertTrue(stopped.wait(5))
                raise CueCancelledError('Cue stopped by the operator')
        self.case.controller.play.side_effect = play
        self.case.controller.cancel_operation.side_effect = stopped.set
        self.coordinator.queue = Mock()
        item = SimpleNamespace(id='w', target=dict(NBC), run_at=None, release_type='after_game')
        done = {}
        thread = threading.Thread(target=lambda: done.setdefault('error', self._preroll(item)))
        thread.start()
        self.wait(lambda: self.coordinator.navigating)
        self.coordinator.stop_preroll('another')
        time.sleep(.1)
        self.assertTrue(self.coordinator.navigating, 'only the warm-up named is stopped')
        self.coordinator.stop_preroll('w')
        thread.join(5)
        self.assertIsInstance(done['error'], MasterStreamError)
        self.coordinator.queue.pause.assert_not_called()
        self.assertFalse(self.coordinator.roku_ready(NBC))
        self.assertEqual(self.master.state['on_air']['channel_id'], 'wttg_dt_5_1')

    def _preroll(self, item):
        try:
            self.coordinator.preroll_queue(item)
        except Exception as exc:
            return exc
        return None


if __name__ == '__main__':
    unittest.main()
