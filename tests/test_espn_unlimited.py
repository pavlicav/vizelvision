"""NHL on ESPN Unlimited as a vizelVision source. Finding the game on YouTube TV's ESPN
page and refusing a blacked-out stream is TV Thing's Roku lane's job (its roku_control
tests cover it, from the 2026-10-22 frames)."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.errors import ChannelNotFoundError, ConfigError
from roku_stream.espn_unlimited import SOURCE_ID, nhl_on_espn_unlimited, refused
from roku_stream.roku_input import roku_target
from roku_stream.sources import SourceCatalog
from roku_stream.sports import SportsCatalog
from roku_stream.sports_join import game_of


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


class StreamTests(unittest.TestCase):
    def test_espn_plus_nhl_games_stream_on_espn_unlimited(self):
        self.assertEqual(nhl_on_espn_unlimited(GAME), {'exclusive': True, 'blackout': {}, 'home': [], 'away': []})
        self.assertEqual(nhl_on_espn_unlimited(POWER_PLAY), {'exclusive': False, 'blackout': {'DET': 'Lansing'},
                                                             'home': ['SNP'], 'away': ['FDSNDET']})
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
        blackout = catalog()._suggest(POWER_PLAY)['note']
        self.assertIn('Blacked out if YouTube TV places the Roku in Lansing (DET)', blackout)

    def test_a_game_on_a_channel_stays_there_with_espn_unlimited_offered(self):
        both = {**POWER_PLAY, 'broadcasts': [*POWER_PLAY['broadcasts'], {'name': 'TNT', 'market': 'national'}]}
        game = catalog(channels=('TNT',))._suggest(both)
        self.assertEqual(game['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'TNT'})
        self.assertEqual(game['espn_unlimited_target']['source_id'], SOURCE_ID)
        self.assertIsNone(catalog(channels=('TNT',))._suggest(ON_TNT)['espn_unlimited_target'])

    def test_the_source_lists_only_the_days_espn_unlimited_games(self):
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
