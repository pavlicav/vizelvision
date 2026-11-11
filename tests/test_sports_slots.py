"""Sports slots: standing appointments with a league (sports_slots.py)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from roku_stream.errors import ConfigError
from roku_stream.programming import Programming
from roku_stream.source_queue import SourceQueue
from roku_stream.sports_slots import PRESETS, SportsSlots, matches

ZONE = ZoneInfo('America/New_York')
ESPN = {'source_id': 'youtube-tv', 'channel_id': 'ESPN'}
MNF = {'title': 'Monday Night Football', 'league': 'nfl', 'days': ['mon'], 'from': '19:00', 'to': '23:30',
       'networks': ['ESPN', 'ABC'], 'priority': 'high', 'preset': 'nfl-mnf'}


def coming(weekday, hour, minute=0):
    """The next such weekday and time, at least a day ahead, in the station's zone."""
    now = datetime.now(ZONE)
    day = now.date() + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


def game(game_id, title, start, channels=('ESPN',), target='channel', teams=(('1', 'AAA'), ('2', 'BBB')), league='nfl'):
    if target == 'channel':
        target = {'source_id': 'youtube-tv', 'channel_id': channels[0]} if channels else None
    sides = [{'id': team, 'abbreviation': short, 'name': short + ' City', 'nickname': short} for team, short in teams]
    return {'league': league, 'game_id': game_id, 'title': title, 'start_time': start.astimezone(timezone.utc).isoformat(),
            'start_time_tbd': False, 'state': 'pre', 'status': 'Scheduled', 'finished': False,
            'game_date': start.date().isoformat(), 'channels': list(channels), 'suggested_target': target,
            'away': sides[0], 'home': sides[1], 'broadcasts': [{'name': c, 'market': 'national'} for c in channels]}


class FakeSports:
    def __init__(self):
        self.games = {}
        self.down = set()

    def upcoming(self, league, days):
        if league in self.down:
            raise OSError('feed down')
        return {'games': list(self.games.get(league, []))}

    def game(self, league, game_id, day):
        return next(g for g in self.games[league] if g['game_id'] == game_id)


class SportsSlotsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', lambda item: {}, lambda *_: {'finished': False},
                                 start_worker=False)
        self.addCleanup(self.queue.close)
        self.sports = FakeSports()
        self.programming = Programming(Path(self.tmp.name) / 'programming.json', self.queue, zone=ZONE,
                                       game=self.sports.game, start_worker=False)
        self.order = []
        self.programming.favorites = lambda: self.order
        self.slots = SportsSlots(self.programming, self.sports, favorites=lambda: self.order)
        self.monday = coming(0, 20, 15)
        self.sunday = coming(6, 13)

    def shows(self):
        return {s['game']['game_pk']: s for s in self.programming.shows()}

    def test_a_slot_schedules_the_games_its_rule_finds_with_its_priority(self):
        self.sports.games['nfl'] = [game(1, 'Bills at Vikings', self.monday, ('ESPN', 'ABC')),
                                    game(2, 'Jets at Colts', self.sunday, ('CBS',)),
                                    game(3, 'Rams at Bears', self.monday - timedelta(hours=3), ('ESPN',)),   # 5:15 PM: before the slot
                                    game(4, 'Lions at Packers', self.monday, ('NFL Network',))]
        made = self.programming.add_sports_slot(MNF)
        found = self.slots.plan()
        self.assertEqual([(g['game_pk'], g['status']) for g in found], [(1, 'scheduled')])
        [show] = self.programming.shows()
        self.assertEqual((show['title'], show['priority'], show['added_by'], show['slot'], show['target']),
                         ('Bills at Vikings', 'high', 'slot', made['id'], {'source_id': 'youtube-tv', 'channel_id': 'ESPN'}))
        self.assertEqual(datetime.fromisoformat(show['start']), self.monday.astimezone(timezone.utc))
        self.assertEqual(datetime.fromisoformat(show['end']) - datetime.fromisoformat(show['start']), timedelta(hours=3, minutes=45))
        self.assertEqual(show['backup'], {'source_id': 'schedule', 'channel_id': 'schedule'})
        # Another pass changes nothing; the view lists the slot, what it found and the other presets.
        self.slots.plan()
        self.assertEqual(len(self.programming.shows()), 1)
        view = self.slots.view()
        self.assertEqual((len(view['slots']), view['games'][0]['slot_title']), (1, 'Monday Night Football'))
        self.assertNotIn('nfl-mnf', [p['preset'] for p in view['presets']])
        self.assertEqual(len(view['presets']), len(PRESETS) - 1)

    def test_the_best_game_of_a_day_is_a_favorites_then_one_on_a_channel(self):
        ticket = {'source_id': 'sunday-ticket', 'channel_id': '11', 'date': self.sunday.date().isoformat()}
        self.sports.games['nfl'] = [game(10, 'Jets at Colts', self.sunday, ('CBS',)),
                                    game(11, 'Lions at Bears', self.sunday, ('FOX',), target=ticket, teams=(('8', 'DET'), ('3', 'CHI'))),
                                    game(12, 'Titans at Jaguars', self.sunday + timedelta(minutes=5), (), target=None)]
        early = {'title': 'NFL early', 'league': 'nfl', 'days': ['sun'], 'from': '12:00', 'to': '15:30', 'pick': 'best'}
        self.programming.add_sports_slot(early)
        # No favorites: the one on a channel, not Sunday Ticket's.
        self.assertEqual({g['game_pk']: g['status'] for g in self.slots.preview(early)}, {10: 'would', 11: 'passed', 12: 'no_channel'})
        self.order[:] = ['nfl:8']
        found = {g['game_pk']: g['status'] for g in self.slots.plan()}
        self.assertEqual(found, {10: 'passed', 11: 'scheduled', 12: 'passed'})
        show = self.shows()[11]
        self.assertEqual((show['target']['source_id'], show['favorites'], show['priority']), ('sunday-ticket', ['nfl:8', 'nfl:3'], 'normal'))

    def test_a_game_already_scheduled_takes_the_slots_priority_and_gives_it_back(self):
        self.sports.games['nfl'] = [game(1, 'Bills at Vikings', self.monday)]
        by_hand = self.programming.add_show({'mode': 'game', 'game': {'league': 'nfl', 'game_pk': 1, 'game_date': 'x'},
                                             'target': ESPN, 'backup': {'source_id': 'schedule'},
                                             'start': self.monday.isoformat(), 'end': (self.monday + timedelta(hours=4)).isoformat()})
        made = self.programming.add_sports_slot(MNF)
        self.assertEqual([g['status'] for g in self.slots.plan()], ['shared'])
        show = self.shows()[1]
        self.assertEqual((show['id'], show['priority'], show['slot'], show.get('added_by')), (by_hand['id'], 'high', made['id'], None))
        # A Low slot never lowers a show that was there before it: back to its own Normal.
        self.programming.update_sports_slot(made['id'], {'priority': 'low'})
        self.slots.plan()
        self.assertEqual(self.shows()[1]['priority'], 'normal')
        self.programming.update_sports_slot(made['id'], {'priority': 'high'})
        self.slots.plan()
        self.assertEqual(self.shows()[1]['priority'], 'high')
        # Once someone sets the show's priority themselves, the slot leaves it alone.
        self.programming.set_priority(by_hand['id'], 'low')
        self.programming.update_sports_slot(made['id'], {'priority': 'normal'})
        self.slots.plan()
        self.assertEqual(self.shows()[1]['priority'], 'low')
        # Without the slot the show stays, with its own priority again.
        self.programming.set_priority(by_hand['id'], 'high')
        self.programming.tag_show(by_hand['id'], slot_priority='high')
        self.programming.remove_sports_slot(made['id'])
        self.slots.plan()
        show = self.shows()[1]
        self.assertEqual((show['priority'], show.get('slot')), ('normal', None))

    def test_its_games_come_off_with_the_slot_and_a_removed_one_stays_off(self):
        self.sports.games['nfl'] = [game(1, 'Bills at Vikings', self.monday), game(5, 'Chargers at Ravens', self.monday + timedelta(days=7))]
        made = self.programming.add_sports_slot(MNF)
        self.slots.plan()
        self.assertEqual(sorted(self.shows()), [1, 5])
        # Someone takes next week's off: it stays off.
        self.programming.remove_show(self.shows()[5]['id'])
        self.assertEqual({g['game_pk']: g['status'] for g in self.slots.plan()}, {1: 'scheduled', 5: 'removed'})
        # The feed is down: nothing is taken off on its account.
        self.sports.down.add('nfl')
        self.slots.plan()
        self.assertEqual(sorted(self.shows()), [1])
        self.assertIn('nfl', self.slots.view()['errors'])
        self.sports.down.clear()
        # Switched off: its game that has not started comes off.
        self.programming.update_sports_slot(made['id'], {'enabled': False})
        self.assertEqual(self.slots.plan(), [])
        self.assertEqual(self.shows(), {})

    def test_what_a_rule_matches(self):
        thursday = coming(3, 20, 15)
        prime = {'source_id': 'thursday-night-football', 'channel_id': '9', 'date': 'x'}
        tnf = game(9, 'Commanders at Giants', thursday, (), target=prime, teams=(('28', 'WSH'), ('19', 'NYG')))
        rule = {'league': 'nfl', 'days': ['thu'], 'from': '19:00', 'to': '23:30', 'networks': [], 'teams': []}
        start = datetime.fromisoformat(tnf['start_time'])
        self.assertTrue(matches(rule, tnf, start, ZONE, prime))
        self.assertTrue(matches({**rule, 'networks': ['prime video']}, tnf, start, ZONE, prime))
        self.assertFalse(matches({**rule, 'networks': ['NBC']}, tnf, start, ZONE, prime))
        self.assertFalse(matches({**rule, 'days': ['mon']}, tnf, start, ZONE, prime))
        self.assertFalse(matches({**rule, 'league': 'nba'}, tnf, start, ZONE, prime))
        self.assertFalse(matches({**rule, 'from': '21:00'}, tnf, start, ZONE, prime))
        for team in ('WSH', 'commanders', 'nfl:28', 'WSH City'):
            self.assertTrue(matches({**rule, 'teams': [team]}, {**tnf, 'home': {**tnf['home'], 'nickname': 'Giants'},
                                                                'away': {**tnf['away'], 'nickname': 'Commanders'}}, start, ZONE, prime), team)
        self.assertFalse(matches({**rule, 'teams': ['DAL']}, tnf, start, ZONE, prime))

    def test_invalid_sports_slots_are_refused(self):
        for change in ({'league': 'cricket'}, {'days': []}, {'from': 'noon'}, {'pick': 'worst'}, {'priority': 'top'},
                       {'title': ''}, {'lead_minutes': 500}, {'networks': 'ESPN'}):
            with self.assertRaises(ConfigError, msg=change):
                self.programming.add_sports_slot({**MNF, **change})
        self.assertEqual(self.programming.sports_slots(), [])


if __name__ == '__main__':
    unittest.main()
