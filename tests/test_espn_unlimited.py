"""NHL on ESPN Unlimited as a vizelVision source. Finding the game on YouTube TV's ESPN
page and refusing a blacked-out stream is TV Thing's Roku lane's job (its roku_control
tests cover it, from the 2026-10-22 frames)."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.errors import ChannelNotFoundError, ConfigError
from roku_stream.espn_unlimited import SOURCE_ID, nhl_on_espn_unlimited, nwsl_on_espn_unlimited, on_espn_unlimited, refused
from roku_stream.roku_input import roku_target
from roku_stream.sources import SourceCatalog
from roku_stream.sports import SportsCatalog
from roku_stream.sports_join import game_of
from roku_stream.tv_control import target_from
from tests.test_programming import youtube_tv_in_lansing


# Verified on the Roku 2026-10-22: an ESPN+ exclusive (also on Disney+ and Hulu).
GAME = {'league': 'nhl', 'game_id': 401802671, 'title': 'Utah Mammoth at Seattle Kraken',
        'away': {'name': 'Utah Mammoth', 'nickname': 'Mammoth', 'abbreviation': 'UTA'},
        'home': {'name': 'Seattle Kraken', 'nickname': 'Kraken', 'abbreviation': 'SEA'},
        'broadcasts': [{'name': 'ESPN+', 'market': 'national'}, {'name': 'Hulu', 'market': 'national'},
                       {'name': 'Disney+', 'market': 'national'}],
        'state': 'in', 'start_time': '2026-10-23T02:00Z', 'status': 'In Progress', 'finished': False,
        'period': 2, 'clock': 600.0}
# Out of market (NHL Power Play): one stream per team's regional broadcast, and Detroit's
# blacked out where YouTube TV placed the Roku that night (Lansing).
POWER_PLAY = {**GAME, 'game_id': 401802672, 'title': 'Detroit Red Wings at Vancouver Canucks',
              'away': {'name': 'Detroit Red Wings', 'nickname': 'Red Wings', 'abbreviation': 'DET'},
              'home': {'name': 'Vancouver Canucks', 'nickname': 'Canucks', 'abbreviation': 'VAN'},
              'broadcasts': [{'name': 'ESPN+', 'market': 'national'}, {'name': 'SNP', 'market': 'home'},
                             {'name': 'FDSNDET', 'market': 'away'}]}
ON_TNT = {**GAME, 'game_id': 401802673, 'broadcasts': [{'name': 'TNT', 'market': 'national'}]}


def catalog(channels=()):
    def resolve(name):
        if name not in channels:
            raise ChannelNotFoundError('none')
        return 0, SimpleNamespace(name=name)
    config = Mock(channels=[])
    config.resolve_channel.side_effect = resolve
    return SportsCatalog(config, None, scoreboard=Mock())


def nwsl(game_id, *names):
    """An NWSL game as ESPN's scoreboard has it; 401854095 and its broadcast are the real one's."""
    return {**GAME, 'league': 'nwsl', 'game_id': game_id, 'title': 'Boston Legacy FC at Angel City FC',
            'away': {'name': 'Boston Legacy FC', 'nickname': 'Boston Legacy FC', 'abbreviation': 'BOS'},
            'home': {'name': 'Angel City FC', 'nickname': 'Angel City FC', 'abbreviation': 'LA'},
            'start_time': '2026-11-01T22:00Z', 'period': 2, 'clock': 4020.0,
            'broadcasts': [{'name': name, 'market': 'national'} for name in names]}


class NwslTests(unittest.TestCase):
    def test_espn_plus_nwsl_games_stream_on_espn_unlimited(self):
        self.assertEqual(on_espn_unlimited(nwsl(1, 'ESPN+')), {'exclusive': True, 'blackout': {}, 'home': [], 'away': []})
        self.assertTrue(on_espn_unlimited(nwsl(2, 'ESPN2', 'ESPN Unlmtd')))
        for names in (('ESPN',), ('ION',), ('NWSL+',), ('Victory+',), ('Prime Video',)):
            with self.subTest(names=names):
                self.assertIsNone(on_espn_unlimited(nwsl(3, *names)))
        self.assertIsNone(nwsl_on_espn_unlimited({**nwsl(1, 'ESPN+'), 'league': 'wnba'}), 'only NWSL games')

    def test_it_is_suggested_on_its_own_source_and_its_target_is_a_roku_input(self):
        game = catalog()._suggest(nwsl(401854095, 'ESPN+'))
        target = {'source_id': 'nwsl', 'channel_id': '401854095', 'date': '2026-11-01'}
        self.assertEqual((game['suggested_target'], game['espn_unlimited_target']), (target, target))
        self.assertEqual(roku_target(target), target)
        self.assertIn('NWSL on ESPN Unlimited', game['note'])

    def test_a_game_on_a_channel_stays_there_with_espn_unlimited_offered(self):
        game = catalog(channels=('ESPN2',))._suggest(nwsl(1, 'ESPN2', 'ESPN Unlmtd'))
        self.assertEqual(game['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'ESPN2'})
        self.assertEqual(game['espn_unlimited_target']['source_id'], 'nwsl')

    def test_the_source_lists_only_the_days_espn_unlimited_games(self):
        self.enterContext(youtube_tv_in_lansing())
        sports = catalog()
        games = [nwsl(1, 'ESPN+'), nwsl(2, 'ION'), nwsl(3, 'NWSL+')]
        sports.games = Mock(return_value={'date': '2026-11-01', 'games': [sports._suggest(g) for g in games]})
        listing = SourceCatalog(Mock(), sports=sports).programs('nwsl', '2026-11-01')
        sports.games.assert_called_once_with('nwsl', '2026-11-01')
        self.assertEqual([c['id'] for c in listing['channels']], ['1'])
        self.assertEqual(listing['channels'][0]['game']['id'], 'nwsl:1')
        self.assertIn('espn_unlimited', listing['channels'][0]['game'])

    def test_a_queued_game_holds_until_its_final_and_is_joined_as_soccer(self):
        sports = catalog()
        sports.scoreboard.games.return_value = [nwsl(401854095, 'ESPN+')]
        target = {'source_id': 'nwsl', 'channel_id': '401854095', 'date': '2026-11-01'}
        games, _ = sports.games_on(target)
        self.assertEqual([(g['league'], g['game_pk'], g['live']) for g in games], [('nwsl', 401854095, True)])
        sports.scoreboard.games.assert_called_with('nwsl', '2026-11-01')
        self.assertEqual(game_of(target=target), {'league': 'nwsl', 'game_pk': 401854095, 'game_date': '2026-11-01'})


ION = {'source_id': 'tv-thing-digital', 'channel_id': 'ion_66_1', 'number': '66.1', 'name': 'ION'}


class IonTests(unittest.TestCase):
    """61 of the NWSL's 240 games in 2026 (and the WNBA's): on the antenna, not YouTube TV."""

    def catalog(self):
        sports = catalog()
        sports.antenna_only = lambda network: ION if network == 'ION' else None
        return sports

    def test_an_ion_game_is_suggested_on_the_antenna(self):
        game = self.catalog()._suggest(nwsl(1, 'ION'))
        target = {'source_id': 'tv-thing-digital', 'channel_id': 'ion_66_1'}
        self.assertEqual((game['suggested_target'], game['antenna_target']), (target, target))
        self.assertEqual(game['channels'], [])
        self.assertEqual(game['note'], 'On ION, over the air on 66.1.')
        self.assertEqual(target_from(target)['channel_id'], 'ion_66_1')
        wnba = self.catalog()._suggest({**nwsl(2, 'ION'), 'league': 'wnba'})
        self.assertEqual(wnba['suggested_target'], target)

    def test_without_the_antenna_it_has_no_channel_as_before(self):
        sports = self.catalog()
        sports.antenna_only = lambda network: None
        game = sports._suggest(nwsl(1, 'ION'))
        self.assertIsNone(game['suggested_target'])
        self.assertIn('choose a source', game['note'])
        self.assertIsNone(catalog()._suggest(nwsl(1, 'ION'))['suggested_target'])

    def test_other_games_are_untouched(self):
        sports = self.catalog()
        self.assertEqual(sports._suggest(nwsl(1, 'ESPN+'))['suggested_target']['source_id'], 'nwsl')
        self.assertIsNone(sports._suggest(nwsl(1, 'ESPN+'))['antenna_target'])
        self.assertIsNone(sports._suggest(nwsl(2, 'NWSL+'))['suggested_target'])
        on_a_channel = SportsCatalog(catalog(channels=('CBS Sports Network',)).config, None, scoreboard=Mock())
        on_a_channel.antenna_only = sports.antenna_only
        self.assertEqual(on_a_channel._suggest(nwsl(3, 'CBS Sports Network', 'ION'))['suggested_target'],
                         {'source_id': 'youtube-tv', 'channel_id': 'CBS Sports Network'})

    def test_the_game_on_ion_is_found_for_a_take_of_the_station(self):
        sports = self.catalog()
        sports.baseball = Mock(games=Mock(return_value={'games': []}))
        game = nwsl(401854000, 'ION')
        sports.scoreboard.games.side_effect = lambda league, day: [game] if league == 'nwsl' else []
        now = datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc)
        ion = {'source_id': 'tv-thing-digital', 'channel_id': 'ion_66_1'}
        games, _ = sports.games_on(ion, channel_name='ION', now=now)
        self.assertEqual([(g['league'], g['game_pk'], g['live']) for g in games], [('nwsl', 401854000, True)])
        other, _ = sports.games_on({'source_id': 'tv-thing-digital', 'channel_id': 'nhk'}, channel_name='NHK-WLD', now=now)
        self.assertEqual(other, [])


class StreamTests(unittest.TestCase):
    def test_espn_plus_nhl_games_stream_on_espn_unlimited(self):
        self.assertEqual(nhl_on_espn_unlimited(GAME), {'exclusive': True, 'blackout': {}, 'home': [], 'away': []})
        # The Red Wings: out of market since YouTube TV placed the Roku in DC (2026-11-07).
        self.assertEqual(nhl_on_espn_unlimited(POWER_PLAY), {'exclusive': False, 'blackout': {},
                                                             'home': ['SNP'], 'away': ['FDSNDET']})
        with youtube_tv_in_lansing():
            self.assertEqual(nhl_on_espn_unlimited(POWER_PLAY)['blackout'], {'DET': 'Lansing'})
        self.assertIsNone(nhl_on_espn_unlimited(ON_TNT), 'a national channel carries it')
        self.assertIsNone(nhl_on_espn_unlimited({**GAME, 'league': 'nba'}), 'only NHL games')

    def test_only_a_blackout_is_refused_not_a_game_that_has_not_started(self):
        self.assertTrue(refused({'code': 'navigation_failed',
                                 'message': 'Detroit Red Wings at Vancouver Canucks is blacked out on YouTube TV where the Roku is'}))
        self.assertTrue(refused({'code': 'program_blocked', 'message': 'YouTube TV blocks this program where the Roku is'}))
        self.assertFalse(refused({'code': 'navigation_failed', 'message': (
            "Utah Mammoth at Seattle Kraken is not among the ESPN page's live NHL games; "
            'it may not have started, or be blacked out')}))
        self.assertFalse(refused({'code': 'navigation_failed',
                                  'message': 'The ESPN page lists no NHL games live; it may not have started'}))
        self.assertFalse(refused(None))


class RoutingTests(unittest.TestCase):
    def test_an_espn_plus_game_is_suggested_on_the_nhl_source_with_its_eastern_date(self):
        game = catalog()._suggest(GAME)
        target = {'source_id': SOURCE_ID, 'channel_id': '401802671', 'date': '2026-10-22'}
        self.assertEqual((game['suggested_target'], game['espn_unlimited_target']), (target, target))
        self.assertEqual(roku_target(target), target)
        self.assertIn('ESPN Unlimited', game['note'])
        with self.assertRaises(ConfigError):
            roku_target({**target, 'channel_id': 'Kraken'})
        self.assertNotIn('blacked out', catalog()._suggest(POWER_PLAY)['note'])
        with youtube_tv_in_lansing():
            blackout = catalog()._suggest(POWER_PLAY)['note']
        self.assertIn('May be blacked out: YouTube TV places the Roku in Lansing (DET)', blackout)

    def test_a_game_on_a_channel_stays_there_with_espn_unlimited_offered(self):
        both = {**POWER_PLAY, 'broadcasts': [*POWER_PLAY['broadcasts'], {'name': 'TNT', 'market': 'national'}]}
        game = catalog(channels=('TNT',))._suggest(both)
        self.assertEqual(game['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'TNT'})
        self.assertEqual(game['espn_unlimited_target']['source_id'], SOURCE_ID)
        self.assertIsNone(catalog(channels=('TNT',))._suggest(ON_TNT)['espn_unlimited_target'])

    def test_the_source_lists_only_the_days_espn_unlimited_games(self):
        self.enterContext(youtube_tv_in_lansing())
        sports = catalog()
        sports.games = Mock(return_value={'date': '2026-10-22', 'games': [sports._suggest(g) for g in (GAME, POWER_PLAY, ON_TNT)]})
        listing = SourceCatalog(Mock(), sports=sports).programs(SOURCE_ID, '2026-10-22')
        sports.games.assert_called_once_with('nhl', '2026-10-22')
        self.assertEqual([c['id'] for c in listing['channels']], ['401802671', '401802672'])
        program = listing['channels'][1]['game']
        self.assertEqual((program['id'], program['state']), ('nhl:401802672', 'live'))
        self.assertEqual(program['espn_unlimited']['blackout'], {'DET': 'Lansing'})
        self.assertIs(listing['channels'][1]['now'], program)

    def test_a_queued_nhl_game_holds_until_its_final_and_is_joined_as_hockey(self):
        sports = catalog()
        sports.scoreboard.games.return_value = [GAME]
        target = {'source_id': SOURCE_ID, 'channel_id': '401802671', 'date': '2026-10-22'}
        games, warnings = sports.games_on(target)
        self.assertEqual([(g['league'], g['game_pk'], g['live']) for g in games], [('nhl', 401802671, True)])
        sports.scoreboard.games.assert_called_with('nhl', '2026-10-22')
        self.assertEqual(game_of(target=target), {'league': 'nhl', 'game_pk': 401802671, 'game_date': '2026-10-22'})


if __name__ == '__main__':
    unittest.main()
