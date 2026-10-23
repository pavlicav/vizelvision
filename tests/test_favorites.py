"""Favorites: the ranked list, the planner that schedules their games, and their ranks."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from roku_stream import crawl_feeds
from roku_stream.errors import ConfigError
from roku_stream.favorites import Favorites, FavoritesPlanner, matches
from roku_stream.programming import SCHEDULE, Programming, show_rank
from roku_stream.scheduler import parse_time
from roku_stream.source_queue import SourceQueue
from roku_stream.sports import EspnScoreboard, SportsCatalog

from tests.test_programming import ESPN, NBC, ZONE
from tests.test_sports import espn_event

PEACOCK = {'source_id': 'youtube-tv', 'channel_id': 'NBC Sports Network'}


def at(hours):
    return (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)).isoformat()


def espn(game_id, away, home, start, *, target=ESPN, state='pre', postseason=False, networks=('ESPN',), tbd=False):
    """A game as SportsCatalog.upcoming lists it for an ESPN league."""
    return {'league': 'ncaaf', 'game_id': game_id, 'game_date': start[:10], 'title': f'{away} at {home}',
            'start_time': start, 'start_time_tbd': tbd, 'state': state, 'status': 'Scheduled',
            'finished': state == 'post', 'postseason': postseason,
            'away': {'id': away.split()[-1]}, 'home': {'id': home.split()[-1]},
            'broadcasts': [{'name': n, 'market': 'national'} for n in networks], 'suggested_target': target}


class FakeSports:
    def __init__(self):
        self.games, self.mlb_teams, self.down = {}, [], set()

    def upcoming(self, league, days):
        if league in self.down:
            raise ConfigError(f'{league} is down')
        return {'games': self.games.get(league, [])}

    def teams(self, league):
        return self.mlb_teams

    def game(self, league, pk, day):
        return next(g for g in self.games.get(league, []) if g['game_id'] == pk)


class FavoritesStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'favorites.json'

    def test_the_crawls_teams_seed_the_list_once(self):
        store = Favorites(self.path, seed=lambda: ['nhl:5', 'nfl:8', 'nfl:8', 'bad'])
        self.assertEqual(store.read(), {'favorites': ['nhl:5', 'nfl:8'], 'air': False})
        store.update({'favorites': ['mlb:playoffs', 'nhl:5']})
        again = Favorites(self.path, seed=lambda: ['nba:8'])
        self.assertEqual(again.order(), ['mlb:playoffs', 'nhl:5'])

    def test_changes_are_validated_and_wake_the_planner(self):
        store = Favorites(self.path)
        store.changed = Mock()
        self.assertEqual(store.update({'favorites': ['ncaaf:127', 'mlb:playoffs'], 'air': True}),
                         {'favorites': ['ncaaf:127', 'mlb:playoffs'], 'air': True})
        store.changed.assert_called_once_with()
        for bad in ({'favorites': ['xfl:1']}, {'favorites': ['nhl:5', 'nhl:5']}, {'favorites': ['nhl:all']},
                    {'air': 'yes'}, {'teams': []}, {}):
            with self.assertRaises(ConfigError):
                store.update(bad)
        self.assertEqual(json.loads(self.path.read_text())['favorites'], ['ncaaf:127', 'mlb:playoffs'])

    def test_a_game_is_its_teams_and_after_the_regular_season_its_playoffs(self):
        self.assertEqual(matches('mlb', {'postseason': True}, ['19', None]), ['mlb:19', 'mlb:playoffs'])
        self.assertEqual(matches('nfl', {}, ['8', '29']), ['nfl:8', 'nfl:29'])


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.queue = SourceQueue(folder / 'queue.json', lambda item: {}, lambda *_: {'finished': False},
                                 poll_seconds=.01, start_worker=False)
        self.addCleanup(self.queue.close)
        self.sports = FakeSports()
        self.programming = Programming(folder / 'programming.json', self.queue, zone=ZONE,
                                       game=self.sports.game, start_worker=False)
        self.store = Favorites(folder / 'favorites.json')
        self.programming.favorites = self.store.order
        self.planner = FavoritesPlanner(self.store, self.programming, self.sports)

    def favor(self, *favorites, air=True):
        self.store.update({'favorites': list(favorites), 'air': air})

    def status(self):
        return {g['title']: g['status'] for g in self.planner.plan()}

    def test_a_favorites_game_goes_on_the_schedule_and_back_to_it_after_the_final(self):
        self.sports.games['ncaaf'] = [espn(401, 'Northwestern 77', 'Michigan State 127', at(2), target=PEACOCK,
                                           networks=('Peacock',)),
                                      espn(402, 'Penn State 213', 'Michigan 130', at(3))]
        self.favor('ncaaf:127')
        self.assertEqual(self.status(), {'Northwestern 77 at Michigan State 127': 'scheduled'})
        show, = self.programming.shows()
        self.assertEqual((show['target'], show['backup'], show['priority'], show['added_by'], show['favorites']),
                         (PEACOCK, SCHEDULE, 'normal', 'favorites', ['ncaaf:77', 'ncaaf:127']))
        self.assertEqual(parse_time(show['end']) - parse_time(show['start']), timedelta(hours=4))
        self.assertEqual(self.status(), {'Northwestern 77 at Michigan State 127': 'scheduled'}, 'scheduled once')
        self.assertEqual(len(self.programming.shows()), 1)

    def test_a_game_under_way_goes_on_now(self):
        self.sports.games['ncaaf'] = [espn(401, 'Northwestern 77', 'Michigan State 127', at(-1.5), state='in')]
        self.favor('ncaaf:127')
        self.planner.plan()
        show, = self.programming.shows()
        start = parse_time(show['start']) - datetime.now(timezone.utc)
        self.assertTrue(timedelta(0) < start <= timedelta(minutes=1), start)
        self.assertEqual(show['game_start'], self.sports.games['ncaaf'][0]['start_time'].replace('Z', '+00:00'))
        self.assertEqual(parse_time(show['end']) - parse_time(show['game_start']), timedelta(hours=4))

    def test_games_it_cannot_air_are_listed_and_finals_are_not(self):
        self.sports.games['ncaaf'] = [espn(1, 'A 1', 'Michigan State 127', at(2), target=None, networks=('ESPN+',)),
                                      espn(2, 'B 2', 'Michigan State 127', at(30), tbd=True),
                                      espn(3, 'C 3', 'Michigan State 127', at(-4), state='post')]
        self.favor('ncaaf:127')
        games = {g['game_pk']: g for g in self.planner.plan()}
        self.assertEqual({pk: g['status'] for pk, g in games.items()}, {1: 'no_channel', 2: 'tbd'})
        self.assertEqual((games[1]['networks'], games[1]['favorite'], games[1]['rank']), (['ESPN+'], 'ncaaf:127', 1))
        self.assertEqual(self.programming.shows(), [])

    def test_off_the_air_it_only_lists_and_turning_it_off_takes_games_off(self):
        self.sports.games['ncaaf'] = [espn(401, 'Northwestern 77', 'Michigan State 127', at(2))]
        self.favor('ncaaf:127', air=False)
        self.assertEqual(self.status(), {'Northwestern 77 at Michigan State 127': 'off'})
        self.assertEqual(self.programming.shows(), [])
        self.store.update({'air': True})
        self.planner.plan()
        self.assertEqual(len(self.programming.shows()), 1)
        self.store.update({'air': False})
        self.assertEqual(self.status(), {'Northwestern 77 at Michigan State 127': 'off'})
        self.assertEqual(self.programming.shows(), [])
        self.store.update({'air': True})
        self.assertEqual(self.status(), {'Northwestern 77 at Michigan State 127': 'scheduled'}, 'and back on again')

    def test_a_game_no_longer_a_favorites_comes_off_unless_under_way(self):
        self.sports.games['ncaaf'] = [espn(401, 'Northwestern 77', 'Michigan State 127', at(2)),
                                      espn(402, 'Michigan State 127', 'Ohio State 194', at(-1), state='in')]
        self.favor('ncaaf:127', 'ncaaf:194')
        self.planner.plan()
        self.assertEqual(len(self.programming.shows()), 2)
        self.store.update({'favorites': ['ncaaf:194']})
        self.planner.plan()
        self.assertEqual([s['game']['game_pk'] for s in self.programming.shows()], [402])
        # Starting now, it stays even with no favorite left.
        self.programming.data['shows'][0]['start'] = at(-.1)
        self.store.update({'favorites': []})
        self.planner.plan()
        self.assertEqual([s['game']['game_pk'] for s in self.programming.shows()], [402])

    def test_a_game_removed_from_the_schedule_stays_off_and_one_scheduled_by_hand_is_left_alone(self):
        self.sports.games['ncaaf'] = [espn(401, 'Northwestern 77', 'Michigan State 127', at(2)),
                                      espn(402, 'Michigan State 127', 'Ohio State 194', at(26))]
        self.programming.add_show({'mode': 'game', 'game': {'league': 'ncaaf', 'game_pk': 402, 'game_date': at(26)[:10]},
                                   'target': NBC, 'backup': dict(SCHEDULE), 'start': at(26), 'end': at(30)})
        self.favor('ncaaf:127')
        self.planner.plan()
        mine = next(s for s in self.programming.shows() if s.get('added_by') == 'favorites')
        self.programming.remove_show(mine['id'])
        self.assertEqual(self.status(), {'Northwestern 77 at Michigan State 127': 'removed',
                                         'Michigan State 127 at Ohio State 194': 'by_hand'})
        self.assertEqual([s.get('added_by') for s in self.programming.shows()], [None])

    def test_mlb_favorites_are_matched_by_name_and_playoffs_by_game_type(self):
        self.sports.mlb_teams = [{'id': '19', 'name': 'Los Angeles Dodgers'}, {'id': '20', 'name': 'Washington Nationals'}]
        mlb = lambda pk, away, home, **extra: {'game_id': pk, 'game_date': at(2)[:10], 'title': f'{away} at {home}',
                                               'start_time': at(2 + pk / 10), 'state': 'preview', 'status': 'Scheduled',
                                               'away': {'name': away}, 'home': {'name': home}, 'broadcasts': [],
                                               'suggested_target': None, 'postseason': False, 'streams': False, **extra}
        self.sports.games['mlb'] = [
            mlb(1, 'Milwaukee Brewers', 'Los Angeles Dodgers', postseason=True,
                suggested_target={'source_id': 'youtube-tv', 'channel_id': 'FOX'}),
            mlb(2, 'Washington Nationals', 'New York Mets', streams=True),
            mlb(3, 'Washington Nationals', 'Atlanta Braves')]
        self.favor('mlb:playoffs', 'mlb:20')
        games = {g['game_pk']: g for g in self.planner.plan()}
        self.assertEqual({pk: (g['status'], g['favorite']) for pk, g in games.items()},
                         {1: ('scheduled', 'mlb:playoffs'), 2: ('scheduled', 'mlb:20'), 3: ('no_channel', 'mlb:20')})
        targets = {s['game']['game_pk']: s['target'] for s in self.programming.shows()}
        self.assertEqual(targets, {1: {'source_id': 'youtube-tv', 'channel_id': 'FOX'},
                                   2: {'source_id': 'mlb', 'channel_id': '2', 'date': at(2)[:10]}})
        self.assertEqual(games[1]['favorites'], ['mlb:19', 'mlb:playoffs'])

    def test_a_league_feed_down_keeps_what_is_scheduled(self):
        self.sports.games['ncaaf'] = [espn(401, 'Northwestern 77', 'Michigan State 127', at(2))]
        self.favor('ncaaf:127')
        self.planner.plan()
        self.sports.down.add('ncaaf')
        self.assertEqual(self.planner.plan(), [])
        self.assertEqual(self.planner.view()['errors'], {'ncaaf': 'ncaaf is down'})
        self.assertEqual(len(self.programming.shows()), 1)


class RankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', lambda item: {}, lambda *_: {'finished': True},
                                 poll_seconds=.01, start_worker=False)
        self.addCleanup(self.queue.close)
        self.order = ['mlb:playoffs', 'ncaaf:127', 'nfl:8']
        self.programming = Programming(Path(self.tmp.name) / 'programming.json', self.queue, zone=ZONE,
                                       game=lambda league, pk, day: {'title': f'Game {pk}'}, start_worker=False)
        self.programming.favorites = lambda: self.order

    def game(self, pk, start, favorites=None, priority='normal', league='ncaaf'):
        end = (parse_time(start) + timedelta(hours=4)).isoformat()
        return self.programming.add_show({'mode': 'game', 'game': {'league': league, 'game_pk': pk, 'game_date': start[:10]},
                                          'target': ESPN, 'backup': dict(SCHEDULE), 'start': start, 'end': end,
                                          'priority': priority}, favorites=favorites)

    def test_favorites_rank_above_normal_by_place_and_below_high_and_held_takes(self):
        ranks = [show_rank({'priority': 'normal', 'favorites': [f]}, self.order) for f in self.order]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        self.assertTrue(all(1 < r < 1.5 for r in ranks), ranks)
        self.assertEqual(show_rank({'priority': 'normal', 'favorites': ['nfl:8', 'mlb:playoffs']}, self.order), ranks[0])
        self.assertEqual(show_rank({'priority': 'high', 'favorites': ['mlb:playoffs']}, self.order), 2)
        self.assertEqual(show_rank({'priority': 'low', 'favorites': ['mlb:playoffs']}, self.order), 0)
        self.assertEqual(show_rank({'priority': 'normal', 'favorites': ['nba:8']}, self.order), 1)

    def test_up_next_reads_a_favorites_rank_live(self):
        show = self.game(1, at(24), ['ncaaf:127'])
        key = next(t['key'] for t in self.programming.transitions(parse_time(show['start']) - timedelta(minutes=1),
                                                                   parse_time(show['start']) + timedelta(minutes=1))
                   if t['kind'] == 'game')
        before = self.programming.rank(key)
        self.order = ['ncaaf:127', 'mlb:playoffs', 'nfl:8']
        self.assertGreater(self.programming.rank(key), before)
        self.order = []
        self.assertEqual(self.programming.rank(key), 1)

    def test_a_favorite_starting_with_another_show_goes_first_unless_that_one_outranks_it(self):
        start = at(24)
        self.game(1, start)  # Normal, by hand.
        first = self.game(2, start, ['ncaaf:127'])
        self.assertEqual(parse_time(first['start']), parse_time(start) - timedelta(seconds=1))
        high = at(48)
        self.game(3, high, priority='high')
        after = self.game(4, high, ['mlb:playoffs'])
        self.assertEqual(parse_time(after['start']), parse_time(high) + timedelta(seconds=1))
        # Of two favorites together, the higher goes on first; the lower waits for its final.
        both = at(72)
        lower = self.game(5, both, ['nfl:8'], league='nfl')
        higher = self.game(6, both, ['mlb:playoffs'], league='mlb')
        self.assertEqual(parse_time(lower['start']), parse_time(both))
        self.assertEqual(parse_time(higher['start']), parse_time(both) - timedelta(seconds=1))
        timeline = self.programming.timeline(parse_time(both) - timedelta(minutes=5), parse_time(both) + timedelta(hours=1))
        self.assertEqual([s['title'] for s in timeline if s['kind'] == 'game'], ['Game 6', 'Game 5'])


class ScoresFeedTests(unittest.TestCase):
    NOW = datetime(2026, 10, 17, 17, tzinfo=timezone.utc)

    def test_playoff_favorites_bring_every_postseason_game_and_rank_orders_them(self):
        team = lambda ident, name, score='0': {'id': ident, 'nickname': name, 'score': score}
        games = {'mlb': [{'state': 'pre', 'postseason': True, 'away': team('8', 'Brewers'), 'home': team('19', 'Dodgers'),
                          'start_time': '2026-10-18T00:08Z', 'broadcasts': [{'name': 'FOX', 'market': 'national'}]},
                         {'state': 'pre', 'postseason': False, 'away': team('1', 'Orioles'), 'home': team('2', 'Red Sox'),
                          'start_time': '2026-10-17T23:00Z', 'broadcasts': []}],
                 'ncaaf': [{'state': 'in', 'away': team('77', 'Wildcats', '13'), 'home': team('127', 'Spartans', '14'),
                            'detail': '3rd 4:18'},
                           {'state': 'pre', 'away': team('213', 'Nittany Lions'), 'home': team('127', 'Spartans'),
                            'start_time': '2026-10-17T19:30Z', 'broadcasts': []}]}
        scoreboard = Mock()
        scoreboard.games.side_effect = lambda league, day: games[league]
        feed = crawl_feeds.ScoresFeed(scoreboard, lambda: ['mlb:playoffs', 'ncaaf:127'], clock=lambda: self.NOW.timestamp())
        feed.refresh()
        self.assertEqual([i['text'] for i in feed.items()],
                         ['Wildcats 13, Spartans 14 · 3rd 4:18', 'Brewers at Dodgers, 8:08 PM on FOX',
                          'Nittany Lions at Spartans, 3:30 PM'])


class PeacockTests(unittest.TestCase):
    def test_peacock_exclusives_are_suggested_on_nbc_sports_network(self):
        event = espn_event(401858491, 'Northwestern Wildcats', 'Michigan State Spartans', broadcasts=('Peacock',))
        event['season'] = {'year': 2026, 'type': 2}

        def opener(request, timeout):
            return io.BytesIO(json.dumps({'events': [event]}).encode())
        config = Mock()
        known = {'nbc sports network': 'NBC Sports Network'}

        def resolve(name):
            if name.casefold() not in known:
                from roku_stream.errors import ChannelNotFoundError
                raise ChannelNotFoundError(name)
            return 0, type('Channel', (), {'name': known[name.casefold()]})()
        config.resolve_channel.side_effect = resolve
        game, = SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener)).games('nfl', '2026-10-17')['games']
        self.assertEqual(game['suggested_target'], PEACOCK)
        self.assertFalse(game['postseason'])
        # Also on a channel of its own (NBC/Peacock), it is there.
        known['nbc'] = 'NBC'
        event['competitions'][0]['broadcasts'] = [{'market': 'national', 'names': ['NBC', 'Peacock']}]
        game, = SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener)).games('nfl', '2026-10-18')['games']
        self.assertEqual(game['channels'], ['NBC'])
        # ESPN+ is streaming, not ESPN (a lookup that drops the "+" finds ESPN): since
        # 2026-10-22 an NHL game there airs from ESPN Unlimited inside YouTube TV.
        known['espn+'] = known['espn'] = 'ESPN'
        event['competitions'][0]['broadcasts'] = [{'market': 'national', 'names': ['ESPN+']}]
        game, = SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener)).games('nhl', '2026-10-18')['games']
        self.assertEqual((game['channels'], game['suggested_target']['source_id']), ([], 'nhl'))
        event['competitions'][0]['broadcasts'] = [{'market': 'national', 'names': ['Peacock']}]
        event['season']['type'] = 3
        game, = SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener)).games('nba', '2026-10-17')['games']
        self.assertTrue(game['postseason'])


if __name__ == '__main__':
    unittest.main()
