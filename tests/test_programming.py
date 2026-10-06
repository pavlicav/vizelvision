import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from roku_stream.config import FeedbackConfig, MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError
from roku_stream.production import DEFAULTS, ProductionSettings
from roku_stream.programming import OFF_AIR, Programming, empty
from roku_stream.source_coordinator import SourceCoordinator
from roku_stream.source_queue import SourceQueue
from roku_stream.scheduler import parse_time

from tests.test_source_coordinator import FakeMaster

ZONE = ZoneInfo('America/New_York')
NBC = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
ESPN = {'source_id': 'youtube-tv', 'channel_id': 'ESPN'}
GAME = {'game_pk': 776655, 'game_date': '2026-09-23', 'title': 'Nationals at Mets'}
# Wednesday 2026-09-23, local noon.
NOON = datetime(2026, 9, 23, 12, tzinfo=ZONE).astimezone(timezone.utc)


def cell(hour, minute=0):
    return hour * 2 + minute // 30


class ProgrammingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', lambda item: {}, lambda *_: {'finished': True},
                                 poll_seconds=.01, start_worker=False)
        self.addCleanup(self.queue.close)
        self.programming = Programming(Path(self.tmp.name) / 'programming.json', self.queue, zone=ZONE,
                                       game=lambda league, pk, day: {'title': GAME['title']}, start_worker=False)

    def load(self, value):
        # save_grid() also syncs against the wall clock; tests drive sync() with fixed times.
        value = self.programming.validate_grid(value)
        with self.programming.lock:
            self.programming.data.update(value)

    def grid(self, **painted):
        value = empty()
        value['enabled'] = True
        value['blocks'] = [{'id': 'news', 'name': 'News', 'color': '#3a6f8f', 'target': NBC},
                           {'id': 'sports', 'name': 'Sports', 'color': '#2f7d5b', 'target': ESPN}]
        for day, spans in painted.items():
            for start, end, block in spans:
                for index in range(start, end):
                    value['grid'][day][index] = block
        return value

    def test_unpainted_time_is_populated_as_off_air_and_blocks_merge(self):
        self.load(self.grid(wed=[(cell(12), cell(14), 'news'), (cell(14), cell(15), 'sports')]))
        timeline = self.programming.timeline(NOON - timedelta(hours=1), NOON + timedelta(hours=4))
        self.assertEqual([(s['title'], s['start'].astimezone(ZONE).hour, s['end'].astimezone(ZONE).hour) for s in timeline],
                         [('OFF AIR', 11, 12), ('News', 12, 14), ('Sports', 14, 15), ('OFF AIR', 15, 16)])
        self.assertEqual(timeline[0]['target'], OFF_AIR)

    def test_show_overrides_grid_and_same_source_does_not_cut(self):
        self.load(self.grid(wed=[(cell(12), cell(16), 'news')]))
        self.programming.data['shows'] = [{'id': 's', 'mode': 'program', 'title': 'Special', 'target': ESPN,
                                           'start': (NOON + timedelta(hours=1)).isoformat(),
                                           'end': (NOON + timedelta(hours=2)).isoformat()},
                                          {'id': 't', 'mode': 'program', 'title': 'Same channel', 'target': NBC,
                                           'start': (NOON + timedelta(hours=3)).isoformat(),
                                           'end': (NOON + timedelta(hours=4)).isoformat()}]
        titles = [s['title'] for s in self.programming.timeline(NOON, NOON + timedelta(hours=5))]
        self.assertEqual(titles, ['News', 'Special', 'News', 'Same channel', 'OFF AIR'])
        changes = self.programming.transitions(NOON, NOON + timedelta(hours=5))
        self.assertEqual([(c['title'], c['target']['channel_id']) for c in changes],
                         [('News', 'NBC'), ('Special', 'ESPN'), ('News', 'NBC'), ('OFF AIR', 'off-air')])
        # NBC stays on through "Same channel", so the 14:00 entry lasts until 16:00.
        self.assertEqual(parse_time(changes[2]['skip_after']), NOON + timedelta(hours=4))

    def test_invalid_grid_and_same_start_shows_are_rejected(self):
        for mutate in (lambda v: v['grid'].pop('sun'), lambda v: v['grid']['mon'].__setitem__(0, 'missing'),
                       lambda v: v['blocks'][0].update(color='red'), lambda v: v['blocks'][0].update(name=''),
                       lambda v: v.update(enabled='yes')):
            value = self.grid()
            mutate(value)
            with self.assertRaises(ConfigError):
                self.programming.save_grid(value)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        self.programming.add_show({'title': 'A', 'target': NBC, 'start': future.isoformat(),
                                   'end': (future + timedelta(hours=2)).isoformat()})
        # Overlapping is fine; the later show takes over from its start.
        self.programming.add_show({'title': 'B', 'target': ESPN, 'start': (future + timedelta(hours=1)).isoformat(),
                                   'end': (future + timedelta(hours=3)).isoformat()})
        with self.assertRaisesRegex(ConfigError, 'same time'):
            self.programming.add_show({'title': 'C', 'target': ESPN, 'start': future.isoformat(),
                                       'end': (future + timedelta(hours=1)).isoformat()})
        self.programming.add_show({'mode': 'game', 'game': GAME, 'target': ESPN, 'backup': NBC,
                                   'start': (future + timedelta(minutes=30)).isoformat(),
                                   'end': (future + timedelta(hours=4)).isoformat()})
        with self.assertRaisesRegex(ConfigError, 'already scheduled'):
            self.programming.add_show({'mode': 'game', 'game': GAME, 'target': ESPN, 'backup': NBC,
                                       'start': (future + timedelta(hours=2)).isoformat(),
                                       'end': (future + timedelta(hours=5)).isoformat()})
        with self.assertRaises(ConfigError):
            self.programming.add_show({'mode': 'game', 'game': GAME, 'start': future.isoformat(),
                                       'end': (future - timedelta(hours=1)).isoformat(), 'backup': NBC})

    def test_game_mode_queues_game_then_backup_then_next_block(self):
        self.load(self.grid(wed=[(cell(12), cell(19), 'news'), (cell(19), cell(23), 'news')]))
        self.programming.data['shows'] = [{'id': 'g', 'mode': 'game', 'title': 'Nats', 'game': GAME,
            'target': {'source_id': 'mlb', 'channel_id': str(GAME['game_pk']), 'date': GAME['game_date']},
            'backup': ESPN, 'backup_title': 'Postgame',
            'start': (NOON + timedelta(hours=1)).isoformat(), 'end': (NOON + timedelta(hours=4)).isoformat()}]
        changes = self.programming.transitions(NOON + timedelta(minutes=30), NOON + timedelta(hours=5))
        self.assertEqual([c['kind'] for c in changes], ['game', 'backup', 'block'])
        game, backup, after = changes
        self.assertIsNone(game['skip_after'])
        self.assertEqual(backup['after_game'], GAME)
        self.assertEqual(parse_time(backup['skip_after']), NOON + timedelta(hours=4))
        self.assertEqual(parse_time(after['run_at']), NOON + timedelta(hours=4))

    def test_game_returns_to_schedule_with_one_backup_per_grid_change(self):
        from roku_stream.programming import SCHEDULE
        self.load(self.grid(wed=[(cell(12), cell(14), 'news'), (cell(15), cell(17), 'sports')]))
        self.programming.data['shows'] = [{'id': 'g', 'mode': 'game', 'title': 'Nats', 'game': GAME,
            'target': ESPN, 'backup': dict(SCHEDULE), 'backup_title': 'Schedule',
            'start': (NOON + timedelta(hours=1)).isoformat(), 'end': (NOON + timedelta(hours=4)).isoformat()}]
        changes = self.programming.transitions(NOON + timedelta(minutes=30), NOON + timedelta(hours=5))
        self.assertEqual([(c['kind'], c['title']) for c in changes],
                         [('game', 'Nats'), ('backup', 'News'), ('backup', 'OFF AIR'), ('backup', 'Sports'),
                          ('block', 'Sports')])
        backups = [c for c in changes if c['kind'] == 'backup']
        self.assertTrue(all(c['after_game'] == GAME for c in backups))
        self.assertEqual([(parse_time(c['run_at']) - NOON, parse_time(c['skip_after']) - NOON) for c in backups],
                         [(timedelta(hours=1), timedelta(hours=2)), (timedelta(hours=2), timedelta(hours=3)),
                          (timedelta(hours=3), timedelta(hours=4))])
        self.assertEqual(len({c['key'] for c in changes}), len(changes))

    def game_show(self, show_id, start, end, target, backup, game=GAME):
        return {'id': show_id, 'mode': 'game', 'title': show_id, 'game': game, 'target': target, 'backup': backup,
                'backup_title': 'Schedule' if backup.get('source_id') == 'schedule' else 'Backup',
                'start': (NOON + start).isoformat(), 'end': (NOON + end).isoformat()}

    def test_overlapping_games_hand_over_at_the_later_start(self):
        from roku_stream.programming import SCHEDULE
        self.load(self.grid(wed=[(cell(12), cell(19), 'news')]))
        other = {**GAME, 'game_pk': 1, 'title': 'Braves at Phillies'}
        self.programming.data['shows'] = [
            self.game_show('g1', timedelta(hours=1), timedelta(hours=4), ESPN, dict(SCHEDULE)),
            self.game_show('g2', timedelta(hours=2), timedelta(hours=5), NBC, ESPN, other)]
        changes = self.programming.transitions(NOON + timedelta(minutes=30), NOON + timedelta(hours=6))
        self.assertEqual([(c['kind'], c['title']) for c in changes],
                         [('game', 'g1'), ('backup', 'News'), ('game', 'g2'), ('backup', 'Backup'), ('block', 'News')])
        self.assertEqual([c.get('game', {}).get('game_pk') for c in changes if c['kind'] == 'game'], [GAME['game_pk'], 1])
        # Game 1's return to the schedule stops where game 2 starts; game 2 follows it in progress.
        g1_back, g2_back = [c for c in changes if c['kind'] == 'backup']
        self.assertEqual((parse_time(g1_back['skip_after']), parse_time(g2_back['skip_after'])),
                         (NOON + timedelta(hours=2), NOON + timedelta(hours=5)))
        self.assertEqual([s['title'] for s in self.programming.timeline(NOON, NOON + timedelta(hours=6))],
                         ['News', 'g1', 'g2', 'News'])

    def test_a_show_inside_a_game_takes_over_and_the_grid_returns(self):
        from roku_stream.programming import SCHEDULE
        self.load(self.grid(wed=[(cell(12), cell(19), 'news')]))
        self.programming.data['shows'] = [
            self.game_show('g', timedelta(hours=1), timedelta(hours=4), ESPN, dict(SCHEDULE)),
            {'id': 'p', 'mode': 'program', 'title': 'Special', 'target': ESPN,
             'start': (NOON + timedelta(hours=2)).isoformat(), 'end': (NOON + timedelta(hours=2, minutes=30)).isoformat()}]
        timeline = self.programming.timeline(NOON, NOON + timedelta(hours=6))
        self.assertEqual([(s['title'], s['start'] - NOON) for s in timeline],
                         [('News', timedelta()), ('g', timedelta(hours=1)), ('Special', timedelta(hours=2)),
                          ('News', timedelta(hours=2, minutes=30))])

    def test_return_to_schedule_includes_program_shows_but_not_games(self):
        from roku_stream.programming import SCHEDULE
        self.load(self.grid(wed=[(cell(12), cell(19), 'news')]))
        self.programming.data['shows'] = [
            {'id': 'p', 'mode': 'program', 'title': 'Special', 'target': NBC,
             'start': NOON.isoformat(), 'end': (NOON + timedelta(hours=5)).isoformat()},
            self.game_show('g', timedelta(hours=1), timedelta(hours=3), ESPN, dict(SCHEDULE))]
        backups = [c for c in self.programming.transitions(NOON + timedelta(minutes=30), NOON + timedelta(hours=6))
                   if c['kind'] == 'backup']
        self.assertEqual([(c['title'], c['target'], parse_time(c['skip_after']) - NOON) for c in backups],
                         [('Special', NBC, timedelta(hours=3))])

    def test_priority_is_validated_stored_changed_and_read_from_entry_keys(self):
        from roku_stream.programming import SCHEDULE
        future = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
        show = self.programming.add_show({'mode': 'game', 'game': GAME, 'target': ESPN, 'backup': dict(SCHEDULE),
                                          'priority': 'high', 'start': future.isoformat(),
                                          'end': (future + timedelta(hours=3)).isoformat()})
        self.assertEqual(show['priority'], 'high')
        with self.assertRaisesRegex(ConfigError, 'priority must be one of low, normal, high'):
            self.programming.add_show({'mode': 'program', 'title': 'X', 'target': NBC, 'priority': 'urgent',
                                       'start': (future + timedelta(hours=5)).isoformat(),
                                       'end': (future + timedelta(hours=6)).isoformat()})
        changes = self.programming.transitions(future - timedelta(minutes=1), future + timedelta(hours=4))
        game, backup = [c for c in changes if c['kind'] in ('game', 'backup')][:2]
        block = next(c for c in changes if c['kind'] == 'off_air')
        self.assertEqual([self.programming.rank(c['key']) for c in (game, backup, block)], [2, 2, 1])
        self.assertEqual(self.programming.rank(None), 1)
        described = self.programming.set_priority(show['id'], 'low')
        self.assertEqual(described['settings']['shows'][0]['priority'], 'low')
        self.assertEqual(self.programming.rank(game['key']), 0)
        self.assertIsNone(self.programming.set_priority('missing', 'high'))
        with self.assertRaises(ConfigError):
            self.programming.set_priority(show['id'], None)

    def test_a_show_starting_inside_one_that_outranks_it_waits_for_its_end(self):
        self.load(self.grid(wed=[(cell(12), cell(19), 'news')]))
        special = {'id': 'p', 'mode': 'program', 'title': 'Election night', 'target': NBC, 'priority': 'high',
                   'start': (NOON + timedelta(hours=1)).isoformat(), 'end': (NOON + timedelta(hours=4)).isoformat()}
        later = {'id': 's', 'mode': 'program', 'title': 'Movie', 'target': ESPN,
                 'start': (NOON + timedelta(hours=2)).isoformat(), 'end': (NOON + timedelta(hours=5)).isoformat()}
        self.programming.data['shows'] = [special, later]
        self.assertEqual([(s['title'], s['start'] - NOON) for s in self.programming.timeline(NOON, NOON + timedelta(hours=6))],
                         [('News', timedelta()), ('Election night', timedelta(hours=1)), ('Movie', timedelta(hours=4)),
                          ('News', timedelta(hours=5))])
        special['priority'] = 'normal'  # Of equal priority the later show takes over from its start, as before.
        self.assertEqual([s['title'] for s in self.programming.timeline(NOON, NOON + timedelta(hours=6))],
                         ['News', 'Election night', 'Movie', 'News'])
        self.assertEqual(self.programming.timeline(NOON, NOON + timedelta(hours=6))[2]['start'] - NOON, timedelta(hours=2))

    def test_a_game_held_back_by_a_show_that_outranks_it_joins_and_returns_from_there(self):
        from roku_stream.programming import SCHEDULE
        self.load(self.grid(wed=[(cell(12), cell(19), 'news')]))
        self.programming.data['shows'] = [
            {'id': 'p', 'mode': 'program', 'title': 'Election night', 'priority': 'high',
             'target': {'source_id': 'youtube-tv', 'channel_id': 'CNN'},
             'start': (NOON + timedelta(hours=1)).isoformat(), 'end': (NOON + timedelta(hours=3)).isoformat()},
            self.game_show('g', timedelta(hours=2), timedelta(hours=5), ESPN, dict(SCHEDULE))]
        changes = self.programming.transitions(NOON + timedelta(minutes=30), NOON + timedelta(hours=6))
        self.assertEqual([(c['kind'], c['title'], parse_time(c['run_at']) - NOON) for c in changes],
                         [('show', 'Election night', timedelta(hours=1)), ('game', 'g', timedelta(hours=3)),
                          ('backup', 'News', timedelta(hours=3)), ('block', 'News', timedelta(hours=5))])

    def test_sync_adds_within_lookahead_once_and_withdraws_edits(self):
        self.load(self.grid(wed=[(cell(12, 30), cell(14), 'news')]))
        self.assertEqual(self.programming.sync(NOON), [])  # 12:30 is outside the 10-minute lookahead.
        added = self.programming.sync(NOON + timedelta(minutes=25))
        self.assertEqual([(i.title, i.origin, i.release_type) for i in added], [('News', 'programming', 'at_time')])
        self.assertEqual(self.programming.sync(NOON + timedelta(minutes=26)), [])
        self.load(self.grid(wed=[(cell(12, 30), cell(14), 'sports')]))
        replaced = self.programming.sync(NOON + timedelta(minutes=27))
        self.assertEqual([i.title for i in replaced], ['Sports'])
        waiting = [i for i in self.queue.list() if i.status == 'queued']
        self.assertEqual([i.target for i in waiting], [ESPN])
        with self.programming.lock:
            self.programming.data['enabled'] = False
        self.programming.sync(NOON + timedelta(minutes=28))
        self.assertEqual([i for i in self.queue.list() if i.status == 'queued'], [])

    def test_next_program_includes_off_air_and_skips_queued_changes(self):
        self.load(self.grid(wed=[(cell(13), cell(14), 'news'), (cell(15), cell(16), 'sports')]))
        first = self.programming.next_program(NOON)
        self.assertEqual((first['title'], parse_time(first['run_at'])), ('News', NOON + timedelta(hours=1)))
        gap = self.programming.next_program(NOON, exclude={first['key']})
        self.assertEqual((gap['title'], gap['kind'], gap['target'], parse_time(gap['run_at']), parse_time(gap['skip_after'])),
                         ('OFF AIR', 'off_air', OFF_AIR, NOON + timedelta(hours=2), NOON + timedelta(hours=3)))
        after = self.programming.next_program(NOON, exclude={first['key'], gap['key']})
        self.assertEqual((after['title'], parse_time(after['run_at'])), ('Sports', NOON + timedelta(hours=3)))
        self.programming.data['enabled'] = False
        self.assertIsNone(self.programming.next_program(NOON))

    def test_upcoming_shows_list_future_shows_not_yet_queued(self):
        self.load(self.grid())
        now = datetime.now(timezone.utc)
        show = lambda i, hours: {'id': i, 'mode': 'program', 'title': i, 'target': NBC,
                                 'start': (now + timedelta(hours=hours)).isoformat(),
                                 'end': (now + timedelta(hours=hours + 1)).isoformat()}
        self.programming.data['shows'] = [show('started', -0.5), show('queued', 0.1), show('later', 5)]
        self.assertEqual([s['id'] for s in self.programming.upcoming_shows(exclude={'queued'})], ['later'])
        self.programming.data['enabled'] = False
        self.assertEqual(self.programming.upcoming_shows(), [])

    def test_manual_entries_keep_their_place_by_time(self):
        later = (NOON + timedelta(hours=2)).isoformat()
        manual = self.queue.add_target(NBC, 'at_time', run_at=(datetime.now(timezone.utc) + timedelta(days=400)).isoformat())
        scheduled = self.queue.add_scheduled({'key': 'k', 'run_at': later, 'target': ESPN, 'title': 'Sports',
                                              'skip_after': None})
        self.assertEqual([i.id for i in self.queue.list()], [scheduled.id, manual.id])

    def test_take_current_uses_the_schedule_keys(self):
        self.load(self.grid(wed=[(cell(11), cell(14), 'news')]))
        added = self.programming.take_current(NOON)
        self.assertEqual([(i.title, i.target) for i in added], [('News', NBC)])
        self.assertEqual(self.programming.take_current(NOON), [])
        # The sync loop recognises it and does not withdraw it.
        self.programming.sync(NOON + timedelta(seconds=1))
        self.assertEqual(self.queue.get(added[0].id).status, 'queued')


class GameOverrunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.aired = []
        self.game = {'finished': False}
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json',
                                 lambda item: self.aired.append(item.title) or {}, lambda *_: dict(self.game),
                                 poll_seconds=.01, final_buffer_seconds=0)
        self.addCleanup(self.queue.close)

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(repr(self.queue.status()))

    def add(self, title, target, *, run_in, skip_in=None, game=False):
        now = datetime.now(timezone.utc)
        return self.queue.add_scheduled({'key': title, 'run_at': (now + timedelta(seconds=run_in)).isoformat(),
            'target': target, 'title': title,
            'skip_after': (now + timedelta(seconds=skip_in)).isoformat() if skip_in is not None else None,
            **({'after_game': GAME} if game else {})})

    def test_backup_follows_final_and_next_block_waits_for_game(self):
        self.add('Game', {'source_id': 'mlb', 'channel_id': '1'}, run_in=.05)
        backup = self.add('Postgame', ESPN, run_in=.05, skip_in=30, game=True)
        after = self.add('News', NBC, run_in=.1, skip_in=60)
        self.queue.resume()
        self.wait(lambda: self.aired == ['Game'])
        time.sleep(.2)  # News is due but held behind the unfinished game.
        self.assertEqual(self.aired, ['Game'])
        self.assertEqual(self.queue.get(after.id).status, 'queued')
        self.game['finished'] = True
        self.wait(lambda: self.aired == ['Game', 'Postgame', 'News'])
        self.assertEqual(self.queue.get(backup.id).status, 'succeeded')

    def test_a_show_that_outranks_the_game_cuts_in_at_its_start(self):
        # 2026-10-04: Braves at Dodgers on air, Lions at Panthers set to cut in at 8:20.
        self.queue.rank = lambda key: 2 if key == 'Lions' else 1
        self.add('Game', {'source_id': 'mlb', 'channel_id': '1'}, run_in=.05)
        backup = self.add('Postgame', ESPN, run_in=.05, skip_in=.3, game=True)
        waiting = self.add('News', NBC, run_in=.1, skip_in=60)
        lions = self.add('Lions', NBC, run_in=.4)
        self.queue.resume()
        self.wait(lambda: self.aired == ['Game'])
        self.wait(lambda: self.aired == ['Game', 'Lions'])
        self.assertGreaterEqual(datetime.now(timezone.utc), parse_time(lions.run_at), 'it cuts in at its start, not before')
        self.assertFalse(self.game['finished'])
        for item in (backup, waiting):
            self.assertEqual((self.queue.get(item.id).status, self.queue.get(item.id).gate_status), ('skipped', 'cut'))
        self.assertIn('Lions cut in', self.queue.get(backup.id).gate_detail)

    def test_a_show_that_does_not_outrank_the_game_waits_for_its_final(self):
        self.queue.rank = lambda key: 0 if key == 'Game' or key == 'Postgame' else 1
        self.add('Game', {'source_id': 'mlb', 'channel_id': '1'}, run_in=.05)
        self.add('Postgame', ESPN, run_in=.05, skip_in=.1, game=True)
        self.add('Lions', NBC, run_in=.15)
        self.queue.rank = lambda key: 1  # Normal, as the game: no cut.
        self.queue.resume()
        self.wait(lambda: self.aired == ['Game'])
        time.sleep(.3)
        self.assertEqual(self.aired, ['Game'])
        self.game['finished'] = True
        self.wait(lambda: self.aired == ['Game', 'Lions'])

    def test_backup_is_superseded_when_game_overruns_its_window(self):
        self.add('Game', {'source_id': 'mlb', 'channel_id': '1'}, run_in=.05)
        backup = self.add('Postgame', ESPN, run_in=.05, skip_in=.2, game=True)
        self.add('News', NBC, run_in=.2, skip_in=60)
        self.queue.resume()
        self.wait(lambda: self.aired == ['Game'])
        time.sleep(.3)
        # Past the window the game stays on air; the next block waits for the final.
        self.assertEqual(self.aired, ['Game'])
        self.game['finished'] = True
        self.wait(lambda: self.aired == ['Game', 'News'])
        self.assertEqual((self.queue.get(backup.id).status, self.queue.get(backup.id).gate_status),
                         ('skipped', 'superseded'))


class OffAirTakeTests(unittest.TestCase):
    def test_off_air_entry_cuts_master_to_fallback(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = SimpleNamespace(master=MasterConfig(enabled=True, socket_path=Path(tmp.name) / 'master.sock'),
                                 feedback=FeedbackConfig(backend='direct', device='/dev/video1', input_format='mpegts',
                                                         contribution_url='rtsp://127.0.0.1:18554/roku'),
                                 tv_thing=TvThingConfig(enabled=True))
        master = FakeMaster()
        master.state.update(state='live', on_air={'id': 'x', **NBC})
        coordinator = SourceCoordinator(config, Mock(), Mock(), master=master, publisher_reader=lambda: 'p')
        self.addCleanup(coordinator.close)
        queue = SourceQueue(Path(tmp.name) / 'queue.json', coordinator.execute_queue, lambda *_: {'finished': True},
                            poll_seconds=.01)
        self.addCleanup(queue.close)
        coordinator.queue = queue
        item = queue.add_scheduled({'key': 'off', 'run_at': (datetime.now(timezone.utc) + timedelta(seconds=.05)).isoformat(),
                                    'target': dict(OFF_AIR), 'title': 'OFF AIR', 'skip_after': None})
        queue.resume()
        deadline = time.monotonic() + 3
        while queue.get(item.id).status != 'succeeded' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(queue.get(item.id).status, 'succeeded', queue.get(item.id))
        self.assertEqual([call[0] for call in master.calls], ['fallback'])
        self.assertIsNone(master.state['on_air'])


class ClockSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = ProductionSettings(MasterConfig(socket_path=Path(self.tmp.name) / 'master.sock'))

    def test_legacy_settings_without_clock_remain_valid(self):
        legacy = {k: v for k, v in copy.deepcopy(DEFAULTS).items() if k != 'clock'}
        self.settings.path.write_text(json.dumps(legacy))
        self.assertEqual(self.settings.read()['clock'], {'enabled': False, 'seconds': False})

    def test_clock_is_saved_and_validated(self):
        body = copy.deepcopy(DEFAULTS)
        body['clock'] = {'enabled': True, 'seconds': True}
        self.assertEqual(self.settings.save(body)['settings']['clock'], body['clock'])
        for clock in ({'enabled': 'yes', 'seconds': False}, {'enabled': True}, [], {'enabled': True, 'seconds': False, 'x': 1}):
            with self.subTest(clock=clock), self.assertRaises(ConfigError):
                self.settings.save({**body, 'clock': clock})
        with self.assertRaises(ConfigError):
            self.settings.save({**body, 'extra': 1})


if __name__ == '__main__':
    unittest.main()


class SportsTests(unittest.TestCase):
    EVENT = {'id': '401', 'name': 'Seattle Seahawks at Washington Commanders', 'shortName': 'SEA @ WSH',
             'date': '2026-09-27T17:00Z',
             'status': {'type': {'name': 'STATUS_SCHEDULED', 'state': 'pre', 'completed': False,
                                 'description': 'Scheduled'}},
             'competitions': [{'broadcasts': [{'market': 'national', 'names': ['FOX']}],
                               'competitors': [
                                   {'homeAway': 'home', 'team': {'displayName': 'Washington Commanders',
                                                                 'name': 'Commanders', 'abbreviation': 'WSH'}},
                                   {'homeAway': 'away', 'team': {'displayName': 'Seattle Seahawks',
                                                                 'name': 'Seahawks', 'abbreviation': 'SEA'}}]}]}

    def catalog(self, events):
        from roku_stream.sports import EspnScoreboard, SportsCatalog
        body = json.dumps({'events': events}).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _limit):
                return body
        channels = {'FOX': 'FOX', 'NFL NETWORK': 'NFL Network', 'ESPN': 'ESPN'}

        def resolve(name):
            from roku_stream.errors import ChannelNotFoundError
            if name.upper() not in channels:
                raise ChannelNotFoundError(name)
            return 0, SimpleNamespace(name=channels[name.upper()])
        baseball = Mock()
        baseball.game_status.return_value = {'finished': True, 'status': 'Final'}
        return SportsCatalog(SimpleNamespace(resolve_channel=resolve), baseball,
                             scoreboard=EspnScoreboard(opener=lambda *_a, **_k: Response()))

    def test_nfl_games_suggest_configured_channel_and_flag_regional_windows(self):
        game = self.catalog([self.EVENT]).games('nfl', '2026-09-27')['games'][0]
        self.assertEqual((game['league'], game['game_id']), ('nfl', 401))
        self.assertEqual(game['home']['nickname'], 'Commanders')
        # A DC team's regional game is on the local station.
        self.assertEqual(game['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'FOX'})
        away = copy.deepcopy(self.EVENT)
        away['id'] = '402'
        away['competitions'][0]['competitors'][0]['team'].update(
            displayName='Buffalo Bills', name='Bills', abbreviation='BUF')
        other = self.catalog([away]).games('nfl', '2026-09-27')['games'][0]
        self.assertEqual(other['suggested_target'],
                         {'source_id': 'sunday-ticket', 'channel_id': '402', 'date': '2026-09-27'})
        self.assertIn('Sunday Ticket', other['note'])

    def test_status_is_final_for_completed_and_postponed_games(self):
        final = copy.deepcopy(self.EVENT)
        final['status']['type'].update(name='STATUS_FINAL', state='post', completed=True, description='Final')
        self.assertTrue(self.catalog([final]).game_status(401, '2026-09-27', 'nfl')['finished'])
        postponed = copy.deepcopy(self.EVENT)
        postponed['status']['type'].update(name='STATUS_POSTPONED')
        self.assertTrue(self.catalog([postponed]).game_status(401, '2026-09-27', 'nfl')['finished'])
        self.assertFalse(self.catalog([self.EVENT]).game_status(401, '2026-09-27', 'nfl')['finished'])
        # Two-argument calls keep MLB's original gate.
        self.assertEqual(self.catalog([]).game_status(5, '2026-09-27')['status'], 'Final')

    def test_estimated_end_follows_the_inning_or_quarter(self):
        from roku_stream.sports import estimated_end
        now = datetime(2026, 9, 30, 20, tzinfo=timezone.utc)
        live = lambda league, **game: estimated_end(league, {'state': 'Live' if league == 'mlb' else 'in', **game}, now) - now
        self.assertEqual(live('mlb', period=8, half='Top'), timedelta(minutes=31.5))  # 3.5 half-innings left
        self.assertEqual(live('mlb', period=10, half='Bottom'), timedelta(minutes=4.5))  # Extra innings: at least half of one
        self.assertEqual(live('nfl', period=2), timedelta(minutes=127.5))  # 2.5 quarters and halftime
        self.assertEqual(live('nba', period=4), timedelta(minutes=17.5))
        self.assertEqual(estimated_end('mlb', {'state': 'Preview', 'start_time': '2026-09-30T22:00:00Z'}, now),
                         datetime(2026, 10, 1, 0, 50, tzinfo=timezone.utc))
        self.assertEqual(estimated_end('nfl', {'state': 'post', 'finished': True}, now), now)

    def test_status_carries_the_score(self):
        live = copy.deepcopy(self.EVENT)
        live['status']['type'].update(state='in', description='In Progress', shortDetail='4th - 2:31')
        for competitor, score in zip(live['competitions'][0]['competitors'], ('21', '17')):
            competitor['score'] = score
        self.assertEqual(self.catalog([live]).game_status(401, '2026-09-27', 'nfl')['summary'],
                         'Seahawks 17, Commanders 21 · 4th - 2:31')
        self.assertEqual(self.catalog([self.EVENT]).game_status(401, '2026-09-27', 'nfl')['summary'], 'Scheduled')

    def test_nfl_week_lists_games_with_eastern_dates_and_weeks(self):
        from roku_stream.sports import EspnScoreboard, SportsCatalog
        night = copy.deepcopy(self.EVENT)
        night.update(id='403', date='2026-09-29T00:15Z')
        payload = {'events': [night, self.EVENT], 'week': {'number': 3}, 'season': {'type': 2, 'year': 2026},
                   'leagues': [{'calendar': [
                       {'value': '1', 'entries': [{'label': 'Hall of Fame Weekend', 'value': '1'}]},
                       {'value': '2', 'entries': [{'label': 'Week 3', 'value': '3', 'detail': 'Sep 23-29'}]}]}]}
        urls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _limit):
                return json.dumps(payload).encode()
        catalog = SportsCatalog(SimpleNamespace(resolve_channel=self.catalog([]).config.resolve_channel), Mock(),
                                scoreboard=EspnScoreboard(opener=lambda request, **_: urls.append(request.full_url) or Response()))
        week = catalog.week('nfl', 2, 3)
        self.assertTrue(urls[0].endswith('scoreboard?seasontype=2&week=3'))
        self.assertEqual((week['season_type'], week['week'], week['year']), (2, 3, 2026))
        self.assertEqual(week['weeks'], [{'season_type': 2, 'week': 3, 'label': 'Week 3', 'detail': 'Sep 23-29',
                                          'start': None, 'end': None}])
        self.assertEqual([(g['game_id'], g['game_date']) for g in week['games']], [(401, '2026-09-27'), (403, '2026-09-28')])
        self.assertEqual(week['games'][0]['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'FOX'})
        with self.assertRaises(ConfigError):
            catalog.week('nba')
        with self.assertRaises(ConfigError):
            catalog.week('nfl', None, 3)

    def test_mlb_upcoming_suggests_youtube_tv_or_automatic_routing(self):
        from roku_stream.sports import SportsCatalog
        baseball = Mock()
        base = {'title': 'Phillies at Braves', 'start_time': '2026-09-29T18:00:00Z', 'official_date': '2026-09-29',
                'status': 'Scheduled', 'state': 'Preview', 'series': 'NL Wild Card Series', 'series_game': 1}
        baseball.range.return_value = [
            {**base, 'game_pk': 1, 'broadcasts': [{'name': 'NBC/Peacock', 'is_national': True}],
             'sources': [{'provider': 'youtube_tv', 'channel': 'NBC'}]},
            {**base, 'game_pk': 2, 'start_time_tbd': True,
             'broadcasts': [{'name': 'Universo/ Peacock', 'is_national': True}], 'sources': []}]
        result = SportsCatalog(SimpleNamespace(), baseball).upcoming_mlb(10)
        first, second = result['games']
        self.assertEqual(first['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'NBC'})
        self.assertEqual((first['game_date'], first['state'], first['series']), ('2026-09-29', 'preview', 'NL Wild Card Series'))
        self.assertIsNone(second['suggested_target'])
        self.assertIn('to be announced', second['note'])
        self.assertIn('Universo/ Peacock is not a configured YouTube TV channel', second['note'])
        with self.assertRaises(ConfigError):
            SportsCatalog(SimpleNamespace(), baseball).upcoming_mlb(0)

    def test_nfl_game_show_requires_a_source(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        queue = SourceQueue(Path(tmp.name) / 'q.json', lambda i: {}, lambda *_: {}, start_worker=False)
        self.addCleanup(queue.close)
        programming = Programming(Path(tmp.name) / 'p.json', queue, zone=ZONE, start_worker=False,
                                  game=lambda league, pk, day: {'title': 'SEA @ WSH'})
        start = datetime.now(timezone.utc) + timedelta(days=1)
        show = {'mode': 'game', 'game': {'league': 'nfl', 'game_pk': 401, 'game_date': '2026-09-27'},
                'start': start.isoformat(), 'end': (start + timedelta(hours=4)).isoformat(), 'backup': OFF_AIR}
        with self.assertRaisesRegex(ConfigError, 'source'):
            programming.add_show(show)
        tv = {'source_id': 'tv-thing-digital', 'channel_id': 'wttg'}
        saved = programming.add_show({**show, 'target': tv})
        self.assertEqual((saved['game']['league'], saved['target']), ('nfl', tv))
        later = {**show, 'target': tv, 'backup': {'source_id': 'schedule'},
                 'game': {'league': 'nfl', 'game_pk': 402, 'game_date': '2026-09-28'},
                 'start': (start + timedelta(days=1)).isoformat(), 'end': (start + timedelta(days=1, hours=4)).isoformat()}
        saved = programming.add_show(later)
        self.assertEqual((saved['backup'], saved['backup_title']),
                         ({'source_id': 'schedule', 'channel_id': 'schedule'}, 'Schedule'))
        backup = [t for t in programming.transitions(start - timedelta(minutes=1), start + timedelta(minutes=1))
                  if t['kind'] == 'backup'][0]
        item = queue.add_scheduled(backup)
        self.assertEqual((item.after_game_league, item.after_game_pk), ('nfl', 401))


class PrerollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events, self.preroll_results, self.execute_results = [], [], []

        def preroll(item):
            self.events.append(('preroll', item.target['channel_id']))
            result = self.preroll_results.pop(0) if self.preroll_results else 'prepared'
            if isinstance(result, Exception):
                raise result
            return result

        def execute(item):
            self.events.append(('take', item.target['channel_id']))
            result = self.execute_results.pop(0) if self.execute_results else {}
            if isinstance(result, Exception):
                raise result
            return result
        self.queue = SourceQueue(Path(self.tmp.name) / 'q.json', execute, lambda *_: {'finished': True},
                                 poll_seconds=.01, preroll=preroll, preroll_seconds=.3, retry_seconds=.05)
        self.addCleanup(self.queue.close)

    def add(self, target, seconds):
        return self.queue.add_target(target, 'at_time',
                                     run_at=(datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat())

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(repr((self.events, self.queue.status())))

    def test_roku_entry_prepares_ahead_then_takes_at_release(self):
        item = self.add(ESPN, .6)
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).gate_status == 'prepared')
        self.assertEqual(self.events, [('preroll', 'ESPN')])
        self.assertEqual(self.queue.get(item.id).status, 'queued')  # Not cut before its time.
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual(self.events, [('preroll', 'ESPN'), ('take', 'ESPN')])

    def test_failed_early_preparation_retries(self):
        from roku_stream.master import MasterStreamError
        self.preroll_results = [MasterStreamError('guide row not found'), 'prepared']
        item = self.add(ESPN, .6)
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).gate_status == 'prepared')
        self.assertEqual(self.queue.get(item.id).preroll_attempts, 1)
        self.assertEqual([e for e in self.events if e[0] == 'preroll'], [('preroll', 'ESPN')] * 2)

    def test_non_roku_sources_do_not_prepare_early(self):
        item = self.add({'source_id': 'tv-thing-digital', 'channel_id': 'wrc'}, .1)
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual(self.events, [('take', 'wrc')])

    def test_release_prepare_failure_is_retried_then_blocks(self):
        from roku_stream.source_coordinator import SourcePrepareError
        self.preroll_results = ['skipped'] * 50  # Roku on air: prepares at release instead.
        self.execute_results = [SourcePrepareError('no video'), SourcePrepareError('no video'), {}]
        item = self.add(ESPN, .05)
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual([e for e in self.events if e[0] == 'take'], [('take', 'ESPN')] * 3)
        self.execute_results = [SourcePrepareError('no video')] * 3
        failing = self.add(NBC, .05)
        self.wait(lambda: self.queue.get(failing.id).status == 'blocked')
        self.assertEqual(self.queue.get(failing.id).prepare_attempts, 2)
        self.assertIn('no video', self.queue.get(failing.id).gate_detail)

    def test_take_failures_are_not_retried(self):
        from roku_stream.master import MasterStreamError
        self.execute_results = [MasterStreamError('Take could not be confirmed')]
        item = self.add(ESPN, .05)
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'blocked')
        self.assertEqual([e for e in self.events if e[0] == 'take'], [('take', 'ESPN')])


class CoordinatorPrerollTests(unittest.TestCase):
    def test_preroll_keeps_a_tv_thing_program_on_air_and_skips_when_roku_is_live(self):
        from tests.test_source_coordinator import CoordinatorTests
        case = CoordinatorTests('run')  # Borrow its fixtures only.
        case.setUp()
        self.addCleanup(case.doCleanups)
        coordinator, master = case.coordinator, case.master
        navigated = []

        def play(channel):
            with coordinator.navigation_guard():
                navigated.append((channel, copy.deepcopy(master.state['on_air'])))
                return case.result
        case.controller.play.side_effect = play
        master.state.update(state='live', on_air={'id': 'tv', 'source_id': 'tv-thing-digital', 'channel_id': 'wrc'})
        queue = SourceQueue(Path(case.directory.name) / 'q.json', coordinator.execute_queue, lambda *_: {},
                            start_worker=False, preroll=coordinator.preroll_queue)
        self.addCleanup(queue.close)
        coordinator.queue = queue
        queue.resume()
        item = queue.add_target({'source_id': 'youtube-tv', 'channel_id': 'NBC'}, 'at_time',
                                run_at=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat())
        self.assertEqual(coordinator.preroll_queue(queue.get(item.id)), 'prepared')
        actions = [call[0] for call in master.calls]
        self.assertNotIn('fallback', actions)
        self.assertEqual(navigated[0][1]['source_id'], 'tv-thing-digital')  # Still on air while the Roku tunes.
        self.assertEqual(master.state['on_air']['source_id'], 'tv-thing-digital')
        self.assertEqual(master.state['prepared']['channel_id'], 'NBC')
        master.state.update(on_air={'id': 'r', 'source_id': 'youtube-tv', 'channel_id': 'ESPN'})
        self.assertEqual(coordinator.preroll_queue(queue.get(item.id)), 'skipped')


class SundayTicketRetryTests(unittest.TestCase):
    setUp, add, wait = PrerollTests.setUp, PrerollTests.add, PrerollTests.wait

    def test_sunday_ticket_keeps_trying_until_the_game_goes_live(self):
        from roku_stream.source_coordinator import SourcePrepareError
        self.preroll_results = ['skipped'] * 50
        self.execute_results = [SourcePrepareError('has not started')] * 6 + [{}]
        item = self.add({'source_id': 'sunday-ticket', 'channel_id': '401872953', 'date': '2026-09-27'}, .05)
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual(len([e for e in self.events if e[0] == 'take']), 7)


class FollowGamesTests(unittest.TestCase):
    """Scheduled games follow MLB and ESPN until they start."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', lambda item: {}, lambda *_: {'finished': True},
                                 poll_seconds=.01, start_worker=False)
        self.addCleanup(self.queue.close)
        self.listings = {}
        self.programming = Programming(Path(self.tmp.name) / 'programming.json', self.queue, zone=ZONE,
                                       game=lambda league, pk, day: {'title': GAME['title']},
                                       locate=self.locate, start_worker=False)
        with self.programming.lock:
            self.programming.data.update(enabled=True)

    def locate(self, league, pk):
        listing = self.listings[pk]
        if isinstance(listing, Exception):
            raise listing
        return listing

    def show(self, pk, start, *, lead=timedelta(), title=None, target=None, game_title='ATL/PHI at Dodgers'):
        """A game show opening `lead` before a first pitch `start` after NOON, with a 4-hour window."""
        first_pitch = NOON + start
        show = {'id': f'g{pk}', 'mode': 'game', 'title': title or game_title,
                'game': {'league': 'mlb', 'game_pk': pk, 'game_date': '2026-09-23', 'title': game_title},
                'target': target or NBC, 'backup': {'source_id': 'schedule', 'channel_id': 'schedule'},
                'backup_title': 'Schedule', 'game_start': first_pitch.isoformat(),
                'start': (first_pitch - lead).isoformat(), 'end': (first_pitch + timedelta(hours=4)).isoformat()}
        self.programming.data['shows'].append(show)
        return show

    def listing(self, pk, start, title='ATL/PHI at Dodgers', **extra):
        self.listings[pk] = {'title': title, 'start_time': (NOON + start).isoformat(), 'start_time_tbd': False,
                             'game_date': '2026-09-23', 'status': 'Scheduled', 'cancelled': False, **extra}

    def shows(self):
        return {s['id']: s for s in self.programming.data['shows']}

    def test_a_moved_game_takes_its_window_and_its_queue_entry_with_it(self):
        self.show(1, timedelta(hours=2), lead=timedelta(minutes=15))
        self.listing(1, timedelta(hours=8))
        # Due within the lookahead, the old start is already queued.
        self.programming.sync(NOON + timedelta(hours=1, minutes=40))
        self.assertEqual([i.kind for i in self.queue.list()], ['game', 'backup'])
        changes = self.programming.follow_games(NOON + timedelta(hours=1, minutes=40))
        show = self.shows()['g1']
        self.assertEqual([c['text'] for c in changes], ['Moved from 1:45 PM'])
        # The pregame lead and the window's length are kept.
        self.assertEqual((parse_time(show['start']), parse_time(show['end']), parse_time(show['game_start'])),
                         (NOON + timedelta(hours=7, minutes=45), NOON + timedelta(hours=12), NOON + timedelta(hours=8)))
        self.assertEqual(show['update']['text'], 'Moved from 1:45 PM')
        self.assertEqual(self.queue.list(), [])  # Withdrawn; it is queued again ten minutes before 7:45.
        self.assertEqual(self.programming.follow_games(NOON + timedelta(hours=2)), [])

    def test_a_series_winner_replaces_the_placeholder_unless_the_title_was_customized(self):
        self.show(1, timedelta(hours=2))
        self.show(2, timedelta(days=1), title='Game 2 on FS1')
        self.listing(1, timedelta(hours=2), title='Philadelphia Phillies at Los Angeles Dodgers')
        self.listing(2, timedelta(days=1), title='Philadelphia Phillies at Los Angeles Dodgers')
        changes = self.programming.follow_games(NOON)
        shows = self.shows()
        self.assertEqual([c['text'] for c in changes], ['Was ATL/PHI at Dodgers'] * 2)
        self.assertEqual((shows['g1']['title'], shows['g2']['title']),
                         ('Philadelphia Phillies at Los Angeles Dodgers', 'Game 2 on FS1'))
        self.assertEqual(shows['g2']['game']['title'], 'Philadelphia Phillies at Los Angeles Dodgers')

    def test_a_game_its_feed_drops_is_removed_after_a_grace_period(self):
        from roku_stream.programming import GONE_AFTER
        self.show(1, timedelta(hours=8))
        self.show(2, timedelta(hours=9))
        moved = self.show(3, timedelta(hours=8), game_title='Phillies at Braves')
        self.listings.update({1: None, 2: None})
        self.listing(3, timedelta(hours=8), title='Phillies at Braves')
        self.assertEqual(self.programming.follow_games(NOON), [])
        self.assertEqual(set(self.shows()), {'g1', 'g2', 'g3'})
        # Meanwhile a game still listed wins a shared start over one that is missing.
        self.assertEqual(self.programming.timeline(NOON + timedelta(hours=8), NOON + timedelta(hours=9))[0]['ref'], moved['id'])
        self.listing(2, timedelta(hours=9))  # A blip: listed again, so it stays.
        self.programming.follow_games(NOON + timedelta(minutes=10))
        self.assertNotIn('missing_since', self.shows()['g2'])
        self.listings[2] = None
        changes = self.programming.follow_games(NOON + GONE_AFTER)
        self.assertEqual([(c['show_id'], c['text'], c['removed']) for c in changes],
                         [('g1', 'No longer on the MLB schedule', True)])
        self.assertEqual(set(self.shows()), {'g2', 'g3'})
        self.assertEqual([r['title'] for r in self.programming.data['removed']], ['ATL/PHI at Dodgers'])
        # Saved: a restart remembers what was removed and what is missing.
        reloaded = Programming(self.programming.path, self.queue, zone=ZONE, start_worker=False)
        self.assertEqual(([s['id'] for s in reloaded.data['shows']], len(reloaded.data['removed'])), (['g3', 'g2'], 1))
        self.assertIn('missing_since', reloaded.data['shows'][1])

    def test_a_cancelled_game_is_removed_at_once(self):
        self.show(1, timedelta(hours=8))
        self.listing(1, timedelta(hours=8), status='Cancelled', cancelled=True)
        self.assertEqual([c['text'] for c in self.programming.follow_games(NOON)], ['Cancelled on the MLB schedule'])
        self.assertEqual(self.shows(), {})

    def test_outages_tbd_starts_and_started_shows_change_nothing(self):
        self.show(1, timedelta(hours=8))
        self.show(2, timedelta(hours=9))
        self.show(3, -timedelta(hours=1))
        self.listings.update({1: OSError('timed out'), 3: None})
        self.listing(2, timedelta(hours=11), start_time_tbd=True)
        before = copy.deepcopy(self.shows())
        self.assertEqual(self.programming.follow_games(NOON), [])
        self.assertEqual(self.shows(), before)
        self.assertIsNotNone(self.programming.describe(NOON)['games_checked_at'])

    def test_a_new_date_updates_the_game_and_an_mlb_target(self):
        mlb = {'source_id': 'mlb', 'channel_id': '1', 'date': '2026-09-23'}
        self.show(1, timedelta(hours=8), target=mlb)
        self.listing(1, timedelta(days=1, hours=1), game_date='2026-09-24')
        [change] = self.programming.follow_games(NOON)
        show = self.shows()['g1']
        self.assertEqual(change['text'], 'Moved from Wed 8:00 PM')  # The day it was, when that differs.
        self.assertEqual((show['game']['game_date'], show['target']['date']), ('2026-09-24', '2026-09-24'))
        self.assertEqual(self.programming._clock(NOON, NOON + timedelta(days=1)), 'Wed 12:00 PM')

    def test_add_show_records_the_first_pitch(self):
        first_pitch = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
        self.programming.game = lambda league, pk, day: {'title': 'Phillies at Braves', 'start_time': first_pitch.isoformat()}
        show = self.programming.add_show({'mode': 'game', 'game': {'league': 'mlb', 'game_pk': 9, 'game_date': '2026-10-01'},
                                          'start': (first_pitch - timedelta(minutes=15)).isoformat(),
                                          'end': (first_pitch + timedelta(hours=4)).isoformat(),
                                          'backup': {'source_id': 'schedule'}})
        self.assertEqual(show['game_start'], first_pitch.isoformat())
        self.assertNotIn('game_start', show['game'])  # The queue's copy of the game stays as it was.
