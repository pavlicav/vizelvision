"""Thursday Night Football as a vizelVision source. Finding the game in the Prime Video
app is TV Thing's Roku lane's job (its roku_control tests cover it)."""
import unittest
from unittest.mock import Mock

from roku_stream.errors import ChannelNotFoundError, ConfigError
from roku_stream.prime_video import SOURCE_ID, prime_nfl_game
from roku_stream.roku_input import roku_target
from roku_stream.sources import SourceCatalog
from roku_stream.sports import SportsCatalog


GAME = {'league': 'nfl', 'game_id': 401872964, 'title': 'Pittsburgh Steelers at Cleveland Browns',
        'away': {'name': 'Pittsburgh Steelers', 'nickname': 'Steelers'},
        'home': {'name': 'Cleveland Browns', 'nickname': 'Browns'},
        'broadcasts': [{'name': 'Prime Video', 'market': 'national'}], 'state': 'in',
        'start_time': '2026-10-02T00:15Z', 'status': 'In Progress', 'finished': False}


class RoutingTests(unittest.TestCase):
    def test_prime_schedule_and_source_rows_keep_espn_game_and_date(self):
        config = Mock(channels=[])
        config.resolve_channel.side_effect = ChannelNotFoundError('none')
        sports = SportsCatalog(config, None)
        game = sports._suggest(GAME)
        target = {'source_id': SOURCE_ID, 'channel_id': str(GAME['game_id']), 'date': '2026-10-01'}
        self.assertEqual(game['suggested_target'], target)
        self.assertEqual(roku_target(target), target)
        for invalid in ('B0GZ57JWXN', '0', '-1', '１２'):
            with self.assertRaises(ConfigError):
                roku_target({**target, 'channel_id': invalid})
        sports.games = Mock(return_value={'date': '2026-10-01', 'games': [game, {**game, 'prime_video_target': None}]})
        listing = SourceCatalog(config, sports=sports).programs(SOURCE_ID, '2026-10-01')
        self.assertEqual(len(listing['channels']), 1)
        self.assertEqual(listing['channels'][0]['game']['id'], 'nfl:401872964')

    def test_only_prime_broadcasts_are_thursday_night_football(self):
        self.assertTrue(prime_nfl_game(GAME))
        self.assertFalse(prime_nfl_game({**GAME, 'broadcasts': [{'name': 'NBC'}]}))
        self.assertFalse(prime_nfl_game({**GAME, 'league': 'mlb'}))


if __name__ == '__main__':
    unittest.main()
