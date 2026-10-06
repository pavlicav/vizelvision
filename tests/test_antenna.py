"""A network YouTube TV is not ready with in time goes on from the antenna (networks.py)."""
import contextlib
from datetime import timedelta
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from roku_stream import source_coordinator
from roku_stream.config import TvThingConfig
from roku_stream.errors import ChannelNotFoundError, ConfigError
from roku_stream.master import MasterStreamError
from roku_stream.networks import Networks, call_sign
from roku_stream.programming import target_key
from roku_stream.scheduler import utc_now
from roku_stream.source_coordinator import SourcePrepareError
from roku_stream.tv_thing import SourceUnavailableError
import tests.test_source_coordinator as base


ITEMS = [{'id': 'wrc_hd_4_1', 'number': '4.1', 'name': 'WRC-HD'},
         {'id': 'cozi_4_2', 'number': '4.2', 'name': 'COZI'},
         {'id': 'wttg_dt_5_1', 'number': '5.1', 'name': 'WTTG-DT'},
         {'id': 'buzzr_5_2', 'number': '5.2', 'name': 'BUZZR'},
         {'id': 'wjla_7_1', 'number': '7.1', 'name': 'WJLA'},
         {'id': 'wusa_hd_9_1', 'number': '9.1', 'name': 'WUSA-HD'},
         {'id': 'wdcw_dt_50_1', 'number': '50.1', 'name': 'WDCW-DT'},
         {'id': 'cwwnuv_54_1', 'number': '54.1', 'name': 'CWWNUV'}]
WRC = {'source_id': 'tv-thing-digital', 'channel_id': 'wrc_hd_4_1', 'number': '4.1', 'name': 'WRC-HD'}
ALIASES = {'NBC': 'NBC', 'WRC': 'NBC', 'FOX': 'FOX', 'FOX 5': 'FOX', 'ABC': 'ABC', 'CBS': 'CBS',
           'The CW': 'The CW', 'CW': 'The CW', 'TBS': 'TBS', 'NBC Sports Network': 'NBC Sports Network'}


class FakeTv:
    def __init__(self, items=ITEMS, enabled=True, guide=None):
        self.config = TvThingConfig(enabled=enabled)
        self.items, self.error, self.guide = items, None, guide or {}

    def get(self, key):
        assert key in ('digital', 'guide')
        if self.error:
            raise self.error
        if key == 'guide':
            return {'data': {'available': True, 'channels': self.guide}, 'stale': False, 'error': None}
        return {'data': {'items': self.items}, 'stale': False, 'error': None}


def resolve(name):
    if name not in ALIASES:
        raise ChannelNotFoundError(f'Unknown channel {name}')
    return 0, SimpleNamespace(name=ALIASES[name])


class NetworksTests(unittest.TestCase):
    def setUp(self):
        self.tv = FakeTv()
        self.networks = Networks(SimpleNamespace(resolve_channel=resolve), self.tv)

    def test_call_signs(self):
        self.assertEqual([call_sign(n) for n in ('WTTG-DT', 'WRC-HD', 'WUSA 9', 'wjla', 'WDCW.DT')],
                         ['WTTG', 'WRC', 'WUSA', 'WJLA', 'WDCW'])

    def test_each_network_has_its_station_main_channel(self):
        found = {row['network']: (row['youtube_tv'], (row['antenna'] or {}).get('channel_id'))
                 for row in self.networks.listing()}
        self.assertEqual(found, {'NBC': ('NBC', 'wrc_hd_4_1'), 'FOX': ('FOX', 'wttg_dt_5_1'),
                                 'ABC': ('ABC', 'wjla_7_1'), 'CBS': ('CBS', 'wusa_hd_9_1'),
                                 'The CW': ('The CW', 'wdcw_dt_50_1')})

    def test_youtube_tv_channel_by_name_or_alias(self):
        self.assertEqual(self.networks.antenna({'source_id': 'youtube-tv', 'channel_id': 'NBC'}), WRC)
        self.assertEqual(self.networks.antenna({'source_id': 'youtube-tv', 'channel_id': 'FOX 5'})['channel_id'], 'wttg_dt_5_1')
        self.assertEqual(self.networks.antenna({'source_id': 'youtube-tv', 'channel_id': 'CW'})['channel_id'], 'wdcw_dt_50_1')

    def test_cable_channels_unknown_names_and_youtube_only_have_no_antenna(self):
        for target in ({'source_id': 'youtube-tv', 'channel_id': 'TBS'},
                       {'source_id': 'youtube-tv', 'channel_id': 'NBC Sports Network'},
                       {'source_id': 'youtube-tv', 'channel_id': 'Nowhere'},
                       {'source_id': 'youtube-tv', 'channel_id': 'NBC', 'antenna': False},
                       {'source_id': 'sunday-ticket', 'channel_id': '401'},
                       {'source_id': 'tv-thing-digital', 'channel_id': 'wrc_hd_4_1'}):
            self.assertIsNone(self.networks.antenna(target), target)

    def test_mlb_game_follows_its_youtube_tv_channel(self):
        target = {'source_id': 'mlb', 'channel_id': '1', 'date': '2026-10-03'}
        fox = {'preferred_source': {'provider': 'youtube_tv', 'channel': 'FOX'}}
        self.assertEqual(self.networks.antenna(target, fox)['channel_id'], 'wttg_dt_5_1')
        self.assertIsNone(self.networks.antenna({**target, 'antenna': False}, fox))
        self.assertIsNone(self.networks.antenna(target, {'preferred_source': {'provider': 'mlb'}}))
        self.assertIsNone(self.networks.antenna(target, {'preferred_source': {'provider': 'youtube_tv', 'channel': 'TBS'}}))

    def test_tv_thing_unavailable_or_off_means_youtube_tv_waits(self):
        self.tv.error = SourceUnavailableError('TV-Thing digital request failed (URLError)')
        self.assertIsNone(self.networks.antenna({'source_id': 'youtube-tv', 'channel_id': 'NBC'}))
        self.assertTrue(all(row['antenna'] is None for row in self.networks.listing()))
        off = Networks(SimpleNamespace(resolve_channel=resolve), FakeTv(enabled=False))
        self.assertIsNone(off.antenna({'source_id': 'youtube-tv', 'channel_id': 'NBC'}))

    def test_schedule_keys_change_only_for_youtube_tv_only(self):
        plain = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
        self.assertEqual(target_key(plain), '{"channel_id": "NBC", "date": null, "source_id": "youtube-tv"}')
        self.assertEqual(target_key({**plain, 'antenna': True}), target_key(plain))
        self.assertNotEqual(target_key({**plain, 'antenna': False}), target_key(plain))


class RecoveryLookupTests(unittest.TestCase):
    """Feed recovery's other sources (2026-10-04: Colts at Commanders, NFL Network and FOX 5)."""

    def setUp(self):
        now = time.time()
        self.guide = {'9.1': {'id': 'wusa_hd_9_1', 'number': '9.1', 'name': 'WUSA-HD', 'events': [
                          {'title': 'The NFL Today', 'start': now - 3600, 'duration': 3000},
                          {'title': 'NFL on CBS: Tennessee Titans at Baltimore Ravens', 'start': now - 600, 'duration': 12300}]},
                      '5.1': {'id': 'wttg_dt_5_1', 'number': '5.1', 'name': 'WTTG', 'events': []}}
        self.networks = Networks(SimpleNamespace(resolve_channel=resolve), FakeTv(guide=self.guide))

    def test_stations_and_networks_both_ways(self):
        self.assertEqual(self.networks.network_of('wttg_dt_5_1'), 'FOX')
        self.assertIsNone(self.networks.network_of('buzzr_5_2'), "a subchannel is not its station's network")
        self.assertEqual(self.networks.station_for('WTTG')['channel_id'], 'wttg_dt_5_1')
        self.assertIsNone(self.networks.station_for(None))

    def test_the_guide_finds_a_game_by_both_its_teams_while_it_airs(self):
        self.assertEqual(self.networks.carrying('Tennessee Titans at Baltimore Ravens')['channel_id'], 'wusa_hd_9_1')
        self.assertIsNone(self.networks.carrying('Indianapolis Colts at Washington Commanders'), 'WTTG sends no listings')
        self.assertIsNone(self.networks.carrying('Tennessee Titans at Houston Texans'))
        self.assertIsNone(self.networks.carrying('Tennessee Titans at Baltimore Ravens', now=time.time() + 4 * 3600))
        self.assertIsNone(self.networks.carrying('News4 Today'))

    def test_coordinator_alternates(self):
        coordinator = SimpleNamespace(networks=self.networks, baseball=Mock(),
                                      sports=Mock(**{'local_simulcast.return_value': 'WTTG'}))
        alternates = lambda target, game=None: source_coordinator.SourceCoordinator.alternates(coordinator, target, game)
        colts = {'league': 'nfl', 'game_pk': 401872965, 'game_date': '2026-10-04',
                 'title': 'Indianapolis Colts at Washington Commanders'}
        nfln = {'source_id': 'youtube-tv', 'channel_id': 'NFL Network'}
        fox5 = {'source_id': 'tv-thing-digital', 'channel_id': 'wttg_dt_5_1'}
        self.assertEqual(alternates(nfln, colts), {'antenna': fox5, 'roku': {**nfln, 'antenna': False}})
        coordinator.sports.local_simulcast.assert_called_once_with('nfl', 401872965, '2026-10-04')
        self.assertEqual(alternates(nfln), {'antenna': None, 'roku': {**nfln, 'antenna': False}})
        self.assertEqual(alternates({**nfln, 'antenna': False}, colts)['antenna'], None, 'YouTube TV only')
        self.assertEqual(alternates({'source_id': 'youtube-tv', 'channel_id': 'FOX'})['antenna'], fox5)
        self.assertEqual(alternates(fox5), {'antenna': fox5, 'roku': {'source_id': 'youtube-tv', 'channel_id': 'FOX',
                                                                      'antenna': False}})
        ticket = {'source_id': 'sunday-ticket', 'channel_id': '401872973', 'date': '2026-10-04'}
        titans = {'league': 'nfl', 'game_pk': 401872973, 'game_date': '2026-10-04',
                  'title': 'Tennessee Titans at Baltimore Ravens'}
        self.assertEqual(alternates(ticket, titans), {'antenna': {'source_id': 'tv-thing-digital', 'channel_id': 'wusa_hd_9_1'},
                                                      'roku': ticket})
        self.assertEqual(alternates({'source_id': 'library', 'channel_id': 'x'}), {})


class AntennaCoordinatorTests(unittest.TestCase):
    setUp_base = base.CoordinatorTests.setUp
    finish = base.CoordinatorTests.finish

    def setUp(self):
        self.setUp_base()
        self.coordinator.networks = Networks(self.config, FakeTv())
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: contextlib.nullcontext()

    def item(self, target=base.TARGET, seconds=None):
        run_at = (utc_now() + timedelta(seconds=seconds)).isoformat() if seconds is not None else None
        return SimpleNamespace(id='q', target=dict(target), run_at=run_at, release_type='at_time')

    def actions(self):
        return [action for action, _ in self.master.calls if action != 'ident_hold']

    def slow_navigation(self):
        """The Roku navigates until it is stopped (the coordinator's deadline or the operator)."""
        stopped = threading.Event()
        self.addCleanup(stopped.set)
        def play(*_):
            with contextlib.nullcontext():
                self.assertTrue(stopped.wait(5))
                raise base.CueCancelledError('Cue stopped by the operator')
        self.controller.play.side_effect = play
        self.controller.cancel_operation.side_effect = stopped.set

    def test_release_without_youtube_tv_ready_takes_the_antenna_at_once(self):
        result = self.coordinator.execute_queue(self.item())
        self.controller.play.assert_not_called()
        self.assertEqual(self.actions(), ['prepare', 'take'])
        self.assertEqual(self.master.calls[0][1], {'source_id': 'tv-thing-digital', 'channel_id': 'wrc_hd_4_1', 'quality': 'medium'})
        self.assertEqual(result['on_air']['channel_id'], 'wrc_hd_4_1')
        self.assertEqual(result['antenna']['number'], '4.1')
        self.assertIn('could not be ready in time', result['antenna']['reason'])

    def test_youtube_tv_prepared_in_time_is_taken(self):
        self.coordinator.request('prepare', base.TARGET)
        self.finish()
        self.master.calls.clear()
        result = self.coordinator.execute_queue(self.item())
        self.assertEqual(result['on_air']['source_id'], 'youtube-tv')
        self.assertNotIn('antenna', result)
        self.assertEqual(self.actions(), ['take'])

    def test_youtube_tv_only_waits_for_the_roku(self):
        target, _ = self.coordinator.normalize_target({**base.TARGET, 'antenna': False}, resolve_game=False)
        self.assertEqual(target, {**base.TARGET, 'antenna': False})
        result = self.coordinator.execute_queue(self.item(target))
        self.controller.play.assert_called_once()
        self.assertEqual(result['on_air']['source_id'], 'youtube-tv')
        # The worker and the verified selection never see the operator's choice.
        self.assertNotIn('antenna', self.roku.selection)
        self.assertNotIn('antenna', self.master.calls[1][1])

    def test_antenna_choice_must_be_a_boolean_and_only_rides_youtube_tv_and_mlb(self):
        with self.assertRaises(ConfigError):
            self.coordinator.normalize_target({**base.TARGET, 'antenna': 'no'}, resolve_game=False)
        ticket, _ = self.coordinator.normalize_target({'source_id': 'sunday-ticket', 'channel_id': '401', 'antenna': False},
                                                      resolve_game=False)
        self.assertNotIn('antenna', ticket)
        game, _ = self.coordinator.normalize_target({'source_id': 'mlb', 'channel_id': '7', 'date': '2026-10-03',
                                                     'antenna': False}, resolve_game=False)
        self.assertIs(game['antenna'], False)

    def test_busy_antenna_falls_back_to_youtube_tv(self):
        def refuse(action, body):
            if action == 'prepare' and body.get('source_id') == 'tv-thing-digital':
                raise MasterStreamError('TV-Thing digital tuner is reserved by the VCR on 7.1; only that channel can be shared')
        self.master.hook = refuse
        result = self.coordinator.execute_queue(self.item())
        self.controller.play.assert_called_once()
        self.assertEqual(result['on_air']['source_id'], 'youtube-tv')
        self.assertNotIn('antenna', result)

    def test_mlb_game_on_a_network_takes_the_antenna(self):
        self.baseball.game.return_value = {'game_pk': 7, 'preferred_source': {'provider': 'youtube_tv', 'channel': 'NBC'}}
        result = self.coordinator.execute_queue(self.item({'source_id': 'mlb', 'channel_id': '7', 'date': '2026-10-03'}))
        self.controller.play_baseball_game.assert_not_called()
        self.assertEqual(result['on_air']['channel_id'], 'wrc_hd_4_1')

    @patch.object(source_coordinator, 'ROKU_FASTEST', 0)
    def test_early_preparation_is_stopped_at_release_time_and_keeps_the_id_holding(self):
        self.slow_navigation()
        self.master.state.update(state='live', on_air={'source_id': 'ident', 'id': 'ident',
                                                        'media': {'position_seconds': 2, 'duration_seconds': 30}})
        item = self.item(seconds=.6)
        started = time.monotonic()
        with self.assertRaises(SourcePrepareError) as raised:  # Retried like any early preparation.
            self.coordinator.preroll_queue(item)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn('YouTube TV was not ready by', str(raised.exception))
        self.controller.cancel_operation.assert_called()
        holds = [body['hold'] for action, body in self.master.calls if action == 'ident_hold']
        self.assertEqual(holds, [True])  # The release follows at once, still under the ID's end card.
        self.assertNotIn('prepare', self.actions())

    def test_early_preparation_with_too_little_time_does_not_navigate(self):
        with self.assertRaisesRegex(SourcePrepareError, 'could not be ready in time'):
            self.coordinator.preroll_queue(self.item(seconds=3))
        self.controller.play.assert_not_called()

    def test_early_preparation_in_good_time_is_youtube_tv(self):
        self.assertEqual(self.coordinator.preroll_queue(self.item(seconds=300)), 'prepared')
        self.controller.play.assert_called_once()
        self.assertIsNone(self.coordinator.deadline)
        self.assertFalse(self.coordinator.late.is_set())

    @patch.object(source_coordinator, 'ROKU_FASTEST', 0)
    def test_release_under_the_station_id_races_youtube_tv_then_takes_the_antenna(self):
        self.slow_navigation()
        ident = {'source_id': 'ident', 'id': 'ident', 'media': {'position_seconds': 29, 'duration_seconds': 30}}
        self.master.state.update(state='live', on_air=ident)
        def tail(action, body):
            if action == 'prepare':  # The ID reaches its tail while the antenna tunes.
                ident['media']['position_seconds'] = 29.8
        self.master.hook = tail
        result = self.coordinator.execute_queue(self.item())
        self.controller.play.assert_called_once()
        self.controller.cancel_operation.assert_called()
        self.assertEqual(result['on_air']['channel_id'], 'wrc_hd_4_1')
        self.assertIn('YouTube TV was not ready by', result['antenna']['reason'])

    @patch.object(source_coordinator, 'ROKU_FASTEST', 0)
    def test_youtube_tv_failing_outright_at_release_takes_the_antenna(self):
        ident = {'source_id': 'ident', 'id': 'ident', 'media': {'position_seconds': 10, 'duration_seconds': 30}}
        self.master.state.update(state='live', on_air=ident)
        self.result['verification'] = {}
        def play(*_):
            with contextlib.nullcontext():
                return self.result
        self.controller.play.side_effect = play
        def tail(action, body):
            if action == 'prepare':
                ident['media']['position_seconds'] = 29.8
        self.master.hook = tail
        result = self.coordinator.execute_queue(self.item())
        self.assertEqual(result['on_air']['channel_id'], 'wrc_hd_4_1')
        self.assertIn('YouTube TV failed (The Roku could not find it', result['antenna']['reason'])

    def test_operator_cancel_is_never_turned_into_the_antenna(self):
        self.slow_navigation()
        self.master.state.update(state='live', on_air={'source_id': 'ident', 'id': 'ident',
                                                        'media': {'position_seconds': 1, 'duration_seconds': 30}})
        self.coordinator.queue.admitted = Mock()
        done = {}
        thread = threading.Thread(target=lambda: done.setdefault('error', self._run_queue()))
        thread.start()
        deadline = time.monotonic() + 2
        while not self.coordinator.navigating and time.monotonic() < deadline:
            time.sleep(.02)
        self.coordinator.request('cancel')
        thread.join(5)
        self.assertIn('stopped (cancelled)', str(done['error']))
        self.assertNotIn('prepare', self.actions())

    def antenna_on_air(self):
        """FOX 5 over the antenna carries a YouTube TV program; the Roku navigates beside it."""
        self.master.state.update(state='live', on_air={'id': 'antenna', 'source_id': 'tv-thing-digital',
                                                        'channel_id': 'wrc_hd_4_1'})
        def play(*_):
            with contextlib.nullcontext():
                self.assertEqual(self.master.state['on_air']['id'], 'antenna')
                return self.result
        self.controller.play.side_effect = play
        return SimpleNamespace(id='upgrade:1', target={**base.TARGET, 'antenna': False}, run_at=None,
                               release_type='at_time')

    def test_back_to_youtube_tv_never_navigates(self):
        item = self.antenna_on_air()
        with self.assertRaisesRegex(MasterStreamError, 'no longer prepared'):
            self.coordinator.upgrade_queue(item)
        self.controller.play.assert_not_called()
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.master.state['on_air']['id'], 'antenna')

    def test_back_to_youtube_tv_takes_what_was_prepared_beside_the_antenna(self):
        item = self.antenna_on_air()
        self.assertEqual(self.coordinator.preroll_queue(item), 'prepared')
        self.assertNotIn('fallback', self.actions())
        self.master.calls.clear()
        result = self.coordinator.upgrade_queue(item)
        self.assertEqual(self.actions(), ['take'])
        self.assertEqual(result['on_air']['source_id'], 'youtube-tv')
        self.controller.play.assert_called_once()
        self.coordinator.queue.hold_for.assert_not_called()  # the queue moves its own hold
        self.coordinator.queue.pause.assert_not_called()

    def _run_queue(self):
        try:
            self.coordinator.execute_queue(self.item())
        except Exception as exc:
            return exc
        return None


class QueueNoteTests(unittest.TestCase):
    def test_an_antenna_take_says_so_in_up_next(self):
        import tempfile
        from pathlib import Path
        from roku_stream.source_queue import SourceQueue
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        result = {'on_air': {'id': 'input', 'source_id': 'tv-thing-digital', 'channel_id': 'wrc_hd_4_1'},
                  'antenna': {**WRC, 'reason': 'YouTube TV was not ready by 20:00:00'}}
        queue = SourceQueue(Path(directory.name) / 'queue.json', lambda item: result, Mock(), poll_seconds=.05)
        self.addCleanup(queue.close)
        queue.add_target(base.TARGET, 'now')
        queue.resume()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and queue.list()[0].status != 'succeeded':
            time.sleep(.05)
        item = queue.list()[0]
        self.assertEqual(item.status, 'succeeded')
        self.assertEqual(item.gate_detail, 'YouTube TV was not ready by 20:00:00: on air from the antenna, 4.1 WRC-HD')


if __name__ == '__main__':
    unittest.main()
