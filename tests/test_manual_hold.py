"""A manual take's end time: the queue holds until then, and the schedule takes master back."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.errors import ConfigError
from roku_stream.programming import OFF_AIR, Programming
from roku_stream.scheduler import parse_time, utc_now
from roku_stream.source_queue import SourceQueue

from roku_stream.sports import EspnScoreboard, SportsCatalog
from tests import test_programming, test_source_coordinator
from tests.test_programming import ESPN, NBC, NOON, ZONE, cell
from tests.test_source_coordinator import TARGET

TV = {'source_id': 'tv-thing-digital', 'channel_id': 'wrc'}
GAME = {'league': 'mlb', 'game_pk': 123, 'game_date': '2026-09-29', 'title': 'Phillies at Braves'}


def soon(seconds):
    return (utc_now() + timedelta(seconds=seconds)).isoformat()


class HoldQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ended, self.aired = [], []
        self.game = {'finished': False, 'status': 'Top 7th'}
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json',
                                 lambda item: self.aired.append(item.target) or {}, lambda *_: dict(self.game),
                                 poll_seconds=.01, hold_poll_seconds=.01, on_hold_end=self.ended.append, final_buffer_seconds=0)
        self.addCleanup(self.queue.close)

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(repr(self.queue.status()))

    def test_time_hold_keeps_the_queue_paused_then_hands_back_and_resumes(self):
        due = self.queue.add_target(ESPN, 'at_time', run_at=soon(.05))
        self.queue.hold_for({'id': 'x', 'media': {}, **TV}, {'until': soon(.3)})
        status = self.queue.status()
        self.assertTrue(status['paused'])
        self.assertEqual(status['hold']['target'], TV, 'worker-only fields are not shown')
        time.sleep(.15)
        self.assertEqual(self.aired, [], 'a due entry waits for the take to end')
        self.wait(lambda: not self.queue.status()['paused'])
        self.assertEqual(self.ended[0]['target'], TV)
        self.assertIsNone(self.queue.status()['hold'])
        self.wait(lambda: self.queue.get(due.id).status == 'succeeded')

    def test_game_hold_ends_when_the_game_is_final(self):
        self.queue.hold_for(TV, {'game': GAME})
        self.wait(lambda: (self.queue.status()['hold'] or {}).get('detail') == 'Top 7th')
        self.assertTrue(self.queue.status()['paused'])
        self.assertEqual(self.ended, [])
        self.game.update(finished=True, status='Final')
        self.wait(lambda: self.ended and not self.queue.status()['paused'])
        self.assertEqual(self.ended[0]['game']['game_pk'], 123)

    def test_a_final_game_stays_on_for_the_final_score(self):
        self.queue.final_buffer_seconds = .4
        self.queue.hold_for(TV, {'game': GAME})
        self.wait(lambda: (self.queue.status()['hold'] or {}).get('detail') == 'Top 7th')
        self.game.update(finished=True, status='Final', summary='Final · PHI 5, ATL 3')
        self.wait(lambda: 'final score' in ((self.queue.status()['hold'] or {}).get('detail') or ''))
        self.assertEqual(self.queue.status()['hold']['detail'], 'Final · PHI 5, ATL 3 · on for the final score, 1 more min')
        called = time.monotonic()
        self.assertEqual(self.ended, [])
        self.wait(lambda: self.ended and not self.queue.status()['paused'])
        self.assertGreater(time.monotonic() - called, .2)

    def test_the_buffer_starts_over_if_the_game_is_reopened(self):
        self.queue.final_buffer_seconds = 60
        self.game.update(finished=True, status='Game Over')
        self.assertFalse(self.queue._game_over('mlb', 123, '2026-09-29')['finished'])
        self.assertIn('mlb:123', self.queue._finals)
        self.game.update(finished=False, status='Bottom 9th')  # A review reopened it.
        self.queue._game_over('mlb', 123, '2026-09-29')
        self.assertNotIn('mlb:123', self.queue._finals)

    def test_resume_ends_the_take_now(self):
        self.queue.hold_for(TV, {'until': soon(3600)})
        self.queue.resume()
        self.wait(lambda: self.ended and not self.queue.status()['paused'])

    def test_operator_pause_and_fallback_clear_the_end_but_preparing_keeps_it(self):
        self.queue.hold_for(TV, {'until': soon(3600)})
        self.queue.pause('Paused by manual master control', keep_hold=True)
        self.assertEqual(self.queue.status()['pause_reason'], 'On air until its end time')
        self.queue.pause()
        status = self.queue.status()
        self.assertIsNone(status['hold'])
        self.assertEqual((status['paused'], status['pause_reason']), (True, 'Paused by operator'))
        time.sleep(.05)
        self.assertEqual(self.ended, [])

    def test_open_ended_take_pauses_as_before(self):
        self.queue.hold_for(TV, {'until': soon(3600)})
        self.queue.hold_for(ESPN, None)
        status = self.queue.status()
        self.assertIsNone(status['hold'])
        self.assertEqual(status['pause_reason'], 'Paused by manual master control')

    def drop_to_test_card(self, aired_minutes):
        self.queue.on_air = lambda: None
        self.queue.hold_lost_seconds = .05
        self.queue.hold_for(TV, {'game': GAME})
        with self.queue._condition:
            started = utc_now() - timedelta(minutes=aired_minutes)
            self.queue.hold['started_at'] = started.isoformat()

    def test_a_held_game_whose_feed_drops_goes_straight_back_on(self):
        # 2026-09-30: NBC's Red Sox at Yankees fell to the test card mid-game, and the
        # hold kept Up next paused until the final, so a Now entry for it never went.
        self.drop_to_test_card(aired_minutes=4)
        self.wait(lambda: self.aired == [TV])
        self.assertTrue(self.ended[0]['lost'])
        self.wait(lambda: (self.queue.status()['hold'] or {}).get('game', {}).get('game_pk') == 123)

    def test_a_take_that_drops_at_once_goes_back_on_too(self):
        # 2026-10-01: NHK, held to an end time, failed 56 s after its take and was not put
        # back. A feed that keeps failing is limited by the recovery budget instead.
        self.drop_to_test_card(aired_minutes=0)
        self.wait(lambda: self.aired == [TV])

    def test_a_final_game_is_not_put_back(self):
        self.game.update(finished=True, status='Final')
        self.drop_to_test_card(aired_minutes=4)
        self.wait(lambda: self.ended and not self.queue.status()['paused'])
        time.sleep(.05)
        self.assertEqual(self.aired, [])

    def test_a_short_stall_keeps_the_hold(self):
        stalled_until = time.monotonic() + .1
        self.queue.on_air = lambda: None if time.monotonic() < stalled_until else dict(TV)
        self.queue.hold_lost_seconds = .3
        self.queue.hold_for(TV, {'game': GAME})
        time.sleep(.6)
        self.assertIsNotNone(self.queue.status()['hold'])
        self.assertEqual(self.ended, [])

    def test_master_unavailable_is_not_a_lost_take(self):
        def unavailable():
            raise OSError('master socket')
        self.queue.on_air = unavailable
        self.queue.hold_lost_seconds = .05
        self.queue.hold_for(TV, {'game': GAME})
        time.sleep(.3)
        self.assertIsNotNone(self.queue.status()['hold'])

    def test_an_entry_queued_with_an_end_holds_master_until_then(self):
        end = {'until': soon(3600)}
        self.queue.add_target(TV, 'after_current', hold_end=end)
        self.queue.resume()
        self.wait(lambda: self.queue.status()['hold'])
        self.assertEqual((self.aired, self.queue.status()['hold']['until']), ([TV], end['until']))

    def test_an_entry_whose_end_passed_while_waiting_is_skipped(self):
        item = self.queue.add_target(TV, 'now', hold_end={'until': soon(-1)})
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'skipped')
        self.assertEqual((self.aired, self.queue.get(item.id).gate_status), ([], 'superseded'))

    def test_a_game_end_holds_until_the_final_and_names_the_game(self):
        item = self.queue.add_target(TV, 'now', hold_end={'game': GAME})
        self.queue.resume()
        self.wait(lambda: (self.queue.status()['hold'] or {}).get('game'))
        self.assertEqual(self.queue.get(item.id).game['title'], 'Phillies at Braves')

    def test_a_take_put_back_on_keeps_its_end_time(self):
        until = soon(3600)
        self.queue.on_air = lambda: None
        self.queue.hold_lost_seconds = .05
        self.queue.hold_for(TV, {'until': until})
        with self.queue._condition:
            self.queue.hold['started_at'] = (utc_now() - timedelta(minutes=4)).isoformat()
        self.wait(lambda: self.aired == [TV])
        self.assertEqual(self.queue.list()[-1].hold_end, {'until': until})

    def test_manual_action_while_returning_keeps_the_queue_paused(self):
        def meanwhile(hold):
            self.ended.append(hold)
            self.queue.pause('Paused by manual master control', keep_hold=True)
        self.queue.on_hold_end = meanwhile
        self.queue.hold_for(TV, {'until': soon(.02)})
        self.wait(lambda: self.ended)
        time.sleep(.05)
        self.assertEqual(self.queue.status()['pause_reason'], 'Paused by manual master control')

    def test_follows_hold_only_for_entries_ready_now(self):
        hold = {'game': {'game_pk': 123, 'game_date': '2026-09-29'}}
        self.assertFalse(self.queue.follows_hold(hold))
        later = self.queue.add_target(ESPN, 'at_time', run_at=soon(600))
        self.assertFalse(self.queue.follows_hold(hold))
        self.queue.remove(later.id)
        self.queue.add_target(ESPN, 'after_game', after_game={'game_pk': 123, 'game_date': '2026-09-29', 'title': 'G'})
        self.assertTrue(self.queue.follows_hold(hold), 'queued after the same game')
        self.assertFalse(self.queue.follows_hold({'game': {'game_pk': 9, 'game_date': '2026-09-29'}}))


class TakeBackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', lambda item: {}, lambda *_: {'finished': True},
                                 poll_seconds=.01, start_worker=False)
        self.addCleanup(self.queue.close)
        self.programming = Programming(Path(self.tmp.name) / 'programming.json', self.queue, zone=ZONE,
                                       start_worker=False)

    def paint(self, enabled=True):
        value = self.programming.validate_grid({
            'enabled': enabled, 'blocks': [{'id': 'news', 'name': 'News', 'color': '#3a6f8f', 'target': NBC}],
            'grid': {day: [None] * 48 for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')}})
        value['grid']['wed'][cell(11):cell(14)] = ['news'] * (cell(14) - cell(11))
        with self.programming.lock:
            self.programming.data.update(value)

    def test_current_block_goes_ahead_of_waiting_entries(self):
        self.paint()
        waiting = self.queue.add_target(ESPN, 'after_game', after_game={'game_pk': 9, 'game_date': 'x', 'title': 'G'})
        added = self.programming.take_back({'until': NOON.isoformat()}, NOON)
        self.assertEqual([(i.title, i.target, i.origin) for i in added], [('News', NBC, 'programming')])
        self.assertEqual([i.id for i in self.queue.list()], [added[0].id, waiting.id])
        self.programming.sync(NOON)
        self.assertEqual(self.queue.get(added[0].id).status, 'queued', 'the schedule keeps it')

    def test_schedule_off_goes_off_air(self):
        self.paint(enabled=False)
        added = self.programming.take_back({'until': NOON.isoformat()}, NOON)
        self.assertEqual([(i.target, i.origin) for i in added], [(OFF_AIR, 'manual_end')])
        self.programming.sync(NOON)
        self.assertEqual(self.queue.get(added[0].id).status, 'queued', 'a disabled schedule does not withdraw it')

    def test_nothing_is_added_when_an_entry_is_due(self):
        self.paint()
        self.queue.add_target(ESPN, 'at_time', run_at=soon(1))
        self.assertEqual(self.programming.take_back({'until': NOON.isoformat()}), [])


class CoordinatorHoldTests(unittest.TestCase):
    setUp, finish, prepare = (getattr(test_source_coordinator.CoordinatorTests, name) for name in ('setUp', 'finish', 'prepare'))

    def take(self, until, **extra):
        state = self.prepare()
        self.coordinator.queue = Mock()
        self.master.calls.clear()
        self.coordinator.request('take', {'prepared_id': state['prepared']['id'], 'until': until, **extra})
        return self.finish()

    def test_take_with_an_end_time_holds_what_is_on_air(self):
        at = soon(1800)
        state = self.take({'kind': 'time', 'at': at})
        self.assertEqual(self.master.calls, [('take', {'prepared_id': 'prepared'})], 'until is not sent to the worker')
        self.coordinator.queue.pause.assert_called_once_with('Paused by manual master control', keep_hold=True)
        on_air, end = self.coordinator.queue.hold_for.call_args.args
        self.assertEqual(on_air, state['on_air'])
        self.assertEqual(end, {'until': parse_time(at).isoformat()})

    def test_take_until_the_game_ends_names_the_game(self):
        self.baseball.game.return_value = {'title': 'Phillies at Braves'}
        self.take({'kind': 'game', 'league': 'mlb', 'game_pk': 123, 'game_date': '2026-09-29'})
        _, end = self.coordinator.queue.hold_for.call_args.args
        self.assertEqual(end['game'], {**GAME})

    def test_take_until_the_listed_program_ends_reads_the_catalog(self):
        end = utc_now().timestamp() + 1200
        self.coordinator.programs = Mock()
        self.coordinator.programs.snapshot.return_value = {'id': 'p', 'title': 'NFL Football', 'start': 1, 'end': end}
        self.take({'kind': 'program', 'program_id': 'p'})
        target, program_id = self.coordinator.programs.snapshot.call_args.args
        self.assertEqual((target['channel_id'], program_id), ('NBC', 'p'))
        _, hold = self.coordinator.queue.hold_for.call_args.args
        self.assertEqual(hold['program'], {'id': 'p', 'title': 'NFL Football'})
        self.assertEqual(parse_time(hold['until']).timestamp(), end)

    def test_take_without_an_end_is_open_ended(self):
        self.take(None)
        self.assertIsNone(self.coordinator.queue.hold_for.call_args.args[1])

    def test_invalid_ends_are_rejected_before_anything_is_cut(self):
        state = self.prepare()
        self.master.calls.clear()
        for until in ('soon', {'kind': 'time', 'at': soon(-60)}, {'kind': 'time', 'at': soon(13 * 3600)},
                      {'kind': 'time', 'at': 'noon'}, {'kind': 'game', 'league': 'xfl', 'game_pk': 1, 'game_date': '2026-09-29'},
                      {'kind': 'game', 'game_pk': '1', 'game_date': '2026-09-29'}, {'kind': 'program', 'program_id': 'p'},
                      {'kind': 'forever'}):
            with self.subTest(until=until), self.assertRaises(ConfigError):
                self.coordinator.request('take', {'prepared_id': state['prepared']['id'], 'until': until})
        self.assertEqual(self.master.calls, [])

    def test_fallback_clears_the_end_and_other_commands_keep_it(self):
        self.coordinator.queue = Mock()
        self.coordinator.request('fallback')
        self.finish()
        self.coordinator.queue.pause.assert_called_once_with('Paused by manual master control', keep_hold=False)
        self.coordinator.queue.reset_mock()
        self.prepare()
        self.coordinator.queue.pause.assert_called_once_with('Paused by manual master control', keep_hold=True)

    def test_change_end_applies_to_what_is_on_air(self):
        self.coordinator.queue = Mock()
        with self.assertRaisesRegex(ConfigError, 'Nothing is on air'):
            self.coordinator.set_hold({'kind': 'time', 'at': soon(600)})
        self.master.state['on_air'] = {'id': 'x', **TARGET}
        at = soon(600)
        self.coordinator.set_hold({'kind': 'time', 'at': at})
        self.coordinator.queue.hold_for.assert_called_once_with({'id': 'x', **TARGET}, {'until': parse_time(at).isoformat()})


class FakeScoreboard:
    def __init__(self, events):
        self.events = [EspnScoreboard._normalize('nfl', e) for e in events]

    def games(self, league, day):
        return self.events if league == 'nfl' else []


class GamesOnTests(unittest.TestCase):
    EVENT = test_programming.SportsTests.EVENT
    NOW = datetime(2026, 9, 27, 18, tzinfo=timezone.utc)

    def catalog(self, events):
        base = test_programming.SportsTests.catalog(self, [])
        base.baseball.games.return_value = {'games': []}
        return SportsCatalog(base.config, base.baseball, scoreboard=FakeScoreboard(events))

    def event(self, state='in', **changes):
        event = copy.deepcopy(self.EVENT)
        event['status']['type'].update(state=state, description='2nd Quarter' if state == 'in' else 'Scheduled')
        event.update(changes)
        return event

    def test_live_national_game_on_a_youtube_tv_channel(self):
        games, _ = self.catalog([self.event()]).games_on({'source_id': 'youtube-tv', 'channel_id': 'FOX'}, now=self.NOW)
        self.assertEqual([(g['league'], g['game_pk'], g['live']) for g in games], [('nfl', 401, True)])
        self.assertEqual(games[0]['game_date'], '2026-09-27')
        other, _ = self.catalog([self.event()]).games_on({'source_id': 'youtube-tv', 'channel_id': 'ESPN'}, now=self.NOW)
        self.assertEqual(other, [])

    def test_upcoming_within_the_hour_counts_and_later_does_not(self):
        pre = self.event('pre')
        catalog = self.catalog([pre])
        self.assertEqual(len(catalog.games_on({'source_id': 'youtube-tv', 'channel_id': 'FOX'},
                                              now=self.NOW - timedelta(hours=1, minutes=30))[0]), 1)
        catalog = self.catalog([pre])
        self.assertEqual(catalog.games_on({'source_id': 'youtube-tv', 'channel_id': 'FOX'},
                                          now=self.NOW - timedelta(hours=3))[0], [])

    def test_over_the_air_station_matches_by_call_sign(self):
        catalog = self.catalog([self.event()])
        config = catalog.config
        resolve = config.resolve_channel
        config.resolve_channel = lambda name: (0, SimpleNamespace(name='FOX')) if name.upper() == 'WTTG' else resolve(name)
        games, _ = catalog.games_on(TV, channel_name='WTTG-HD', now=self.NOW)
        self.assertEqual([g['game_pk'] for g in games], [401])
        self.assertEqual(catalog.games_on(TV, channel_name='Bounce', now=self.NOW)[0], [])

    def test_out_of_market_sunday_game_is_not_on_the_local_station(self):
        away = self.event()
        away['competitions'][0]['competitors'][0]['team'].update(displayName='Buffalo Bills', abbreviation='BUF')
        games, _ = self.catalog([away]).games_on({'source_id': 'youtube-tv', 'channel_id': 'FOX'}, now=self.NOW)
        self.assertEqual(games, [])

    def test_a_game_target_is_its_own_game_until_final(self):
        catalog = self.catalog([self.event()])
        games, _ = catalog.games_on({'source_id': 'sunday-ticket', 'channel_id': '401', 'date': '2026-09-27'}, now=self.NOW)
        self.assertEqual([(g['league'], g['game_pk']) for g in games], [('nfl', 401)])
        final = self.event('post')
        final['status']['type'].update(completed=True)
        self.assertEqual(self.catalog([final]).games_on(
            {'source_id': 'sunday-ticket', 'channel_id': '401', 'date': '2026-09-27'}, now=self.NOW)[0], [])

class EndOptionsApiTests(unittest.TestCase):
    def handler(self, path, **kwargs):
        from roku_stream.api import handler_factory
        from roku_stream.config import MasterConfig
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        handler = object.__new__(handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(), **kwargs))
        handler.path, handler._authorize, response = path, (lambda: True), {}
        handler._json = lambda status, payload: response.update(status=status, payload=payload)
        return handler, response

    def test_tv_thing_offers_its_listed_program_and_matches_games_by_station_name(self):
        end = utc_now().timestamp() + 900
        sources = Mock()
        sources.programs.return_value = {'channels': [{'id': 'wttg', 'name': 'WTTG-HD', 'now': {
            'id': 'p1', 'title': 'NFL Football', 'start': 1, 'end': end, 'state': 'current'}}]}
        sports = Mock()
        sports.games_on.return_value = ([{'league': 'nfl', 'game_pk': 401}], [])
        programming = SimpleNamespace(enabled=True)
        handler, response = self.handler('/v1/master/end-options?source_id=tv-thing-digital&channel_id=wttg',
                                         sources=sources, sports=sports, programming=programming)
        handler.do_GET()
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['payload']['program'], {'id': 'p1', 'title': 'NFL Football', 'start': 1, 'end': end})
        self.assertEqual(response['payload']['returns_to'], 'schedule')
        sports.games_on.assert_called_once_with({'source_id': 'tv-thing-digital', 'channel_id': 'wttg'},
                                                channel_name='WTTG-HD')

    def test_youtube_tv_has_no_listing_and_schedule_off_goes_off_air(self):
        sources, sports = Mock(), Mock()
        sports.games_on.return_value = ([], [])
        handler, response = self.handler('/v1/master/end-options?source_id=youtube-tv&channel_id=ESPN',
                                         sources=sources, sports=sports)
        handler.do_GET()
        self.assertEqual((response['payload']['program'], response['payload']['returns_to']), (None, 'off_air'))
        sources.programs.assert_not_called()

    def test_hold_route_requires_the_master_queue(self):
        coordinator = Mock()
        handler, response = self.handler('/v1/master/hold', coordinator=coordinator)
        handler._body = Mock(return_value={'until': {'kind': 'time', 'at': soon(600)}})
        handler.do_POST()
        self.assertEqual(response['status'], 400)
        coordinator.set_hold.assert_not_called()
