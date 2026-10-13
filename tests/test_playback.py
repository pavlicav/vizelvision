"""The Schedule page's projection of what will actually air."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from roku_stream.playback import Entry, Fill, Program, Projector, describe, project
from roku_stream.programming import OFF_AIR, Programming
from roku_stream.source_queue import SourceQueue

T0 = datetime(2026, 9, 30, 18, tzinfo=timezone.utc)
MLB = {'source_id': 'mlb', 'channel_id': '849841', 'date': '2026-09-30'}
NBC = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
ESPN = {'source_id': 'youtube-tv', 'channel_id': 'ESPN'}
PHILLIES = {'league': 'mlb', 'game_pk': 849841, 'game_date': '2026-09-30', 'title': 'Phillies at Braves'}
WHITE_SOX = {'league': 'mlb', 'game_pk': 849846, 'game_date': '2026-09-30', 'title': 'White Sox at Astros'}
H = timedelta(hours=1)
M = timedelta(minutes=1)


def at(delta):
    return T0 + delta


class ProjectionTests(unittest.TestCase):
    def run_projection(self, current, entries, recordings=(), finals=None, schedule=None, hours=6):
        finals = finals or {}
        return [(s['title'], datetime.fromisoformat(s['start']) - T0, datetime.fromisoformat(s['end']) - T0, s['notes'])
                for s in project(T0, T0 + hours * H, current, entries, list(recordings),
                                 game_end=lambda game, start=None: finals.get(game['game_pk']),
                                 schedule_at=lambda when: schedule)]

    def game_now(self, until):
        return Program('Phillies at Braves', 'game', MLB, T0 - H, at(until), True, PHILLIES)

    def test_game_then_recordings_then_test_card_then_the_schedule(self):
        entries = [Entry(at(H), 'OFF AIR', 'backup', dict(OFF_AIR), 0, at(3.5 * H), True),
                   Entry(at(3.5 * H), 'News', 'block', NBC, 1, at(4 * H), True),
                   Entry(at(4 * H), 'White Sox at Astros', 'game', ESPN, 2, None, False, WHITE_SOX)]
        rows = self.run_projection(self.game_now(H), entries,
                                   [('Jeopardy!', {'source_id': 'library'}, 40 * M)] * 2,
                                   finals={849846: at(7 * H)})
        self.assertEqual([(r[0], r[1], r[2]) for r in rows],
                         [('Phillies at Braves', timedelta(), H), ('Jeopardy!', H, H + 40 * M),
                          ('Jeopardy!', H + 40 * M, H + 80 * M), ('OFF AIR', H + 80 * M, 3.5 * H),
                          ('News', 3.5 * H, 4 * H), ('White Sox at Astros', 4 * H, 6 * H)])
        self.assertEqual(rows[1][3], ['Instead of OFF AIR'])

    def test_a_game_that_runs_long_joins_the_next_game_in_progress(self):
        entries = [Entry(at(H), 'White Sox at Astros', 'game', ESPN, 0, None, False, WHITE_SOX)]
        rows = self.run_projection(self.game_now(2 * H), entries, finals={849846: at(4 * H)})
        self.assertEqual([(r[0], r[1], r[3]) for r in rows],
                         [('Phillies at Braves', timedelta(), []), ('White Sox at Astros', 2 * H, ['Joins in progress']),
                          ('OFF AIR', 4 * H, [])])

    def test_a_live_show_starting_cuts_a_recording(self):
        current = Program('Jeopardy!', 'recording', {'source_id': 'library'}, T0, at(H))
        rows = self.run_projection(current, [Entry(at(30 * M), 'News', 'block', NBC, 0, at(H), True)])
        self.assertEqual(rows[0], ('Jeopardy!', timedelta(), 30 * M, ['Cut when News starts']))
        self.assertEqual(rows[1][:2], ('News', 30 * M))

    def test_off_air_lets_a_recording_finish(self):
        current = Program('Jeopardy!', 'recording', {'source_id': 'library'}, T0, at(H))
        rows = self.run_projection(current, [Entry(at(10 * M), 'OFF AIR', 'off_air', dict(OFF_AIR), 0, at(3 * H), True)])
        self.assertEqual([(r[0], r[1], r[2]) for r in rows],
                         [('Jeopardy!', timedelta(), H), ('OFF AIR', H, 6 * H)])
        self.assertEqual(rows[0][3], ['OFF AIR gives way'])

    def test_after_a_held_take_the_schedule_block_joins_in_progress(self):
        news = Entry(T0 - H, 'News', 'block', NBC, regular=True)
        rows = self.run_projection(self.game_now(30 * M), [], schedule=news)
        self.assertEqual([(r[0], r[1], r[3]) for r in rows],
                         [('Phillies at Braves', timedelta(), []), ('News', 30 * M, ['Joins in progress'])])


    def test_a_show_of_higher_priority_cuts_a_held_game_at_its_start(self):
        lions = {'league': 'nfl', 'game_pk': 401, 'game_date': '2026-09-30', 'title': 'Lions at Panthers'}
        entries = [Entry(at(30 * M), 'News', 'block', NBC, 0, at(2 * H), True),
                   Entry(at(H), 'Lions at Panthers', 'game', NBC, 1, None, False, lions, rank=2)]
        rows = self.run_projection(self.game_now(3 * H), entries, finals={401: at(4 * H)})
        self.assertEqual(rows, [('Phillies at Braves', timedelta(), H, ['Cut when Lions at Panthers starts']),
                                ('Lions at Panthers', H, 4 * H, []), ('OFF AIR', 4 * H, 6 * H, [])])
        # Of equal priority it waits for the final and joins in progress.
        entries[1].rank = 1
        rows = self.run_projection(self.game_now(3 * H), entries, finals={401: at(4 * H)})
        self.assertEqual([(r[0], r[1]) for r in rows], [('Phillies at Braves', timedelta()), ('Lions at Panthers', 3 * H),
                                                        ('OFF AIR', 4 * H)])

class DroppedTests(unittest.TestCase):
    """What never airs, and why: On Air's Up next folds these away (Won't air)."""

    def run_projection(self, current, entries, recordings=(), finals=None):
        dropped = []
        segments = project(T0, T0 + 6 * H, current, entries, list(recordings),
                           game_end=lambda game, start=None: (finals or {}).get(game['game_pk']),
                           schedule_at=lambda when: None, dropped=dropped)
        return segments, [(entry.item or entry.title, why) for entry, why in dropped]

    def game_now(self, until):
        return Program('Phillies at Braves', 'game', MLB, T0 - H, at(until), True, PHILLIES, item='game')

    def test_slots_that_end_while_the_game_runs_on_never_air(self):
        entries = [Entry(at(30 * M), 'News 10', 'block', NBC, 0, at(H), True, item='news'),
                   Entry(at(H), 'OFF AIR', 'off_air', dict(OFF_AIR), 1, at(90 * M), True, item='off'),
                   Entry(at(90 * M), 'Jeopardy', 'block', NBC, 2, at(2 * H), True, item='jeopardy')]
        segments, dropped = self.run_projection(self.game_now(3 * H), entries)
        self.assertEqual([(s['title'], s['item']) for s in segments], [('Phillies at Braves', 'game'), ('OFF AIR', None)])
        self.assertEqual(dropped, [(name, 'Its slot ends before Phillies at Braves does') for name in ('news', 'off', 'jeopardy')])

    def test_a_game_under_way_at_the_final_drops_what_it_replaces(self):
        entries = [Entry(at(H), 'News 10', 'block', NBC, 0, at(4 * H), True, item='news'),
                   Entry(at(H), 'White Sox at Astros', 'game', ESPN, 1, None, False, WHITE_SOX, item='sox')]
        segments, dropped = self.run_projection(self.game_now(2 * H), entries, finals={849846: at(5 * H)})
        self.assertEqual([(s['title'], s['item'], s['notes']) for s in segments][1], ('White Sox at Astros', 'sox', ['Joins in progress']))
        self.assertEqual(dropped, [('news', 'White Sox at Astros airs instead')])

    def test_a_live_channel_queued_to_fill_stays_on_until_the_next_entry(self):
        recording = Program('Jeopardy!', 'recording', {'source_id': 'library'}, T0, at(30 * M), item='rec')
        tbs = {'source_id': 'youtube-tv', 'channel_id': 'TBS'}
        entries = [Entry(at(H), 'OFF AIR', 'off_air', dict(OFF_AIR), 0, at(5 * H), True),
                   Entry(at(5 * H), 'News', 'block', NBC, 1, at(6 * H), True)]
        segments, dropped = self.run_projection(recording, entries, [Fill('', tbs, None, 'tbs', live=True)])
        self.assertEqual([(s['kind'], s['item'], datetime.fromisoformat(s['start']) - T0) for s in segments],
                         [('recording', 'rec', timedelta()), ('manual', 'tbs', 30 * M), ('off_air', None, H), ('block', None, 5 * H)])
        self.assertEqual(dropped, [])

    def test_a_live_fill_given_an_end_holds_until_it_or_is_dropped_once_it_has_passed(self):
        tbs = {'source_id': 'youtube-tv', 'channel_id': 'TBS'}
        entries = [Entry(at(H), 'OFF AIR', 'off_air', dict(OFF_AIR), 0, at(5 * H), True)]
        segments, _ = self.run_projection(Program('OFF AIR', 'off_air', dict(OFF_AIR), T0), entries,
                                          [Fill('TBS', tbs, None, 'tbs', live=True, until=at(2 * H))])
        self.assertEqual([(s['title'], datetime.fromisoformat(s['end']) - T0) for s in segments], [('TBS', 2 * H), ('OFF AIR', 6 * H)])
        segments, dropped = self.run_projection(self.game_now(3 * H), [], [Fill('TBS', tbs, None, 'tbs', live=True, until=at(2 * H))])
        self.assertEqual(dropped, [('tbs', 'Its end time passes before it could air')])
        self.assertEqual([s['title'] for s in segments], ['Phillies at Braves', 'OFF AIR'])

    def test_a_game_queued_to_follow_is_joined_in_progress(self):
        tbs = {'source_id': 'youtube-tv', 'channel_id': 'TBS'}
        rays = Fill('Rays at Yankees', tbs, None, 'tbs', True, at(5 * H), WHITE_SOX, at(H))
        segments, _ = self.run_projection(self.game_now(2 * H), [], [rays])
        self.assertEqual([(s['title'], s['kind'], s['notes'], s['estimated']) for s in segments][1],
                         ('Rays at Yankees', 'game', ['Joins in progress'], True))


class DescribeTests(unittest.TestCase):
    def test_up_next_and_the_schedule_become_one_projection(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        queue = SourceQueue(Path(tmp.name) / 'queue.json', lambda item: {}, lambda *_: {}, start_worker=False)
        self.addCleanup(queue.close)
        programming = Programming(Path(tmp.name) / 'programming.json', queue, start_worker=False)
        queue.add_target({'source_id': 'library', 'channel_id': 'rec/a.mp4'}, 'after_current')
        now = datetime.now(timezone.utc)
        result = describe(now, now + 6 * H, queue=queue, programming=programming, on_air=None,
                          game_info=lambda game: None, length=lambda channel: 1800, label=lambda channel: 'Jeopardy!')
        self.assertEqual([(s['title'], s['kind']) for s in result['segments']],
                         [('Jeopardy!', 'recording'), ('OFF AIR', 'off_air')])
        self.assertEqual(datetime.fromisoformat(result['segments'][0]['end']) - now, timedelta(minutes=30))
        self.assertTrue(result['paused'])



class SpokenTests(unittest.TestCase):
    def test_a_game_queued_by_hand_is_named_by_its_teams(self):
        projector = object.__new__(Projector)
        asked = []
        teams = {'away': {'nickname': 'Steelers'}, 'home': {'nickname': 'Browns'}, 'title': 'Pittsburgh Steelers at Cleveland Browns'}
        projector.game_info = lambda game: asked.append(game) or teams
        prime = {'title': None, 'target': {'source_id': 'thursday-night-football', 'channel_id': '401872964', 'date': '2026-10-01'}}
        self.assertEqual(projector.spoken(prime, 'fr'), 'les Steelers et les Browns')
        self.assertEqual(asked, [{'league': 'nfl', 'game_pk': 401872964, 'game_date': '2026-10-01'}])
        projector.game_info = lambda game: {'title': 'Pittsburgh Steelers at Cleveland Browns'}
        self.assertEqual(projector.spoken(prime), 'Pittsburgh Steelers at Cleveland Browns')
        projector.game_info = lambda game: None
        self.assertEqual(projector.spoken({'title': 'News 10', 'target': {'source_id': 'youtube-tv', 'channel_id': 'NBC'}}), 'News 10')
        self.assertEqual(projector.spoken({'title': None, 'target': {'source_id': 'youtube-tv', 'channel_id': 'NBC'}}), 'NBC')


if __name__ == '__main__':
    unittest.main()
