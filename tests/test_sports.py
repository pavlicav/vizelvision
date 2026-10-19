import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from roku_stream.errors import BaseballScheduleError, ConfigError
from roku_stream.sports import EspnScoreboard, SportsCatalog, closing, estimated_end

SUMMARY = {'header': {'id': '401872978', 'competitions': [{
    'date': '2026-10-05T00:20Z',
    'status': {'period': 0, 'type': {'name': 'STATUS_SCHEDULED', 'state': 'pre', 'completed': False,
                                     'description': 'Scheduled', 'shortDetail': '10/4 - 8:20 PM EDT'}},
    'competitors': [{'homeAway': 'home', 'team': {'displayName': 'Carolina Panthers', 'name': 'Panthers', 'abbreviation': 'CAR'}},
                    {'homeAway': 'away', 'team': {'displayName': 'Detroit Lions', 'name': 'Lions', 'abbreviation': 'DET'}}]}]}}


class EspnEventTests(unittest.TestCase):
    def test_event_reads_one_game_by_id(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            return io.BytesIO(json.dumps(SUMMARY).encode())
        game = EspnScoreboard(opener=opener).event('nfl', 401872978)
        self.assertEqual(urls, ['https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=401872978'])
        self.assertEqual((game['game_id'], game['title'], game['start_time'], game['status'], game['finished']),
                         (401872978, 'Detroit Lions at Carolina Panthers', '2026-10-05T00:20Z', 'Scheduled', False))

    def test_an_unknown_event_is_gone_but_an_outage_is_an_error(self):
        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, 'Not Found', {}, None)

        def down(request, timeout):
            raise HTTPError(request.full_url, 503, 'Unavailable', {}, None)
        self.assertIsNone(EspnScoreboard(opener=missing).event('nfl', 1))
        with self.assertRaises(BaseballScheduleError):
            EspnScoreboard(opener=down).event('nfl', 1)


class LocateTests(unittest.TestCase):
    def test_locate_gives_the_eastern_date_and_cancellation(self):
        scoreboard = Mock()
        scoreboard.event.return_value = {'title': 'Detroit Lions at Carolina Panthers', 'start_time': '2026-10-05T00:20Z',
                                         'status': 'Canceled', 'start_time_tbd': False}
        game = SportsCatalog(None, None, scoreboard=scoreboard).locate('nfl', 401872978)
        self.assertEqual((game['game_date'], game['cancelled'], game['start_time_tbd']), ('2026-10-04', True, False))
        scoreboard.event.return_value = None
        self.assertIsNone(SportsCatalog(None, None, scoreboard=scoreboard).locate('nfl', 401872978))

    def test_locate_mlb_uses_the_official_date(self):
        baseball = Mock()
        baseball.locate.return_value = {'title': 'Phillies at Braves', 'start_time': '2026-10-02T00:08:00Z',
                                        'official_date': '2026-10-01', 'status': 'Scheduled', 'start_time_tbd': False}
        game = SportsCatalog(None, baseball).locate('mlb', 849844)
        baseball.locate.assert_called_once_with(849844)
        self.assertEqual((game['game_date'], game['start_time'], game['cancelled']),
                         ('2026-10-01', '2026-10-02T00:08:00Z', False))


def espn_event(id, away, home, state='pre', period=0, detail='7:00 PM', broadcasts=('TNT',)):
    return {'id': str(id), 'name': f'{away} at {home}', 'shortName': f'{away[:3].upper()} @ {home[:3].upper()}',
            'date': '2026-10-02T23:00Z',
            'status': {'period': period, 'type': {'state': state, 'shortDetail': detail, 'description': detail}},
            'competitions': [{'broadcasts': [{'market': 'national', 'names': list(broadcasts)}], 'competitors': [
                {'homeAway': 'home', 'score': '2', 'team': {'id': '23', 'displayName': home, 'name': home.split()[-1], 'abbreviation': 'WSH'}},
                {'homeAway': 'away', 'score': '1', 'team': {'id': '1', 'displayName': away, 'name': away.split()[-1], 'abbreviation': 'BOS'}}]}]}


class NflRecoveryTests(unittest.TestCase):
    """Where an NFL game can also be found: over the air in DC, and on Sunday Ticket."""

    def catalog(self, *events):
        def opener(request, timeout):
            return io.BytesIO(json.dumps({'events': list(events)}).encode())
        config = Mock()
        config.resolve_channel.side_effect = lambda name: (0, type('Channel', (), {'name': name})())
        return SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener))

    def event(self, id, broadcasts, date, home='WSH'):
        event = espn_event(id, 'Indianapolis Colts', 'Washington Commanders', broadcasts=broadcasts)
        event['date'] = date
        event['competitions'][0]['competitors'][0]['team']['abbreviation'] = home
        return event

    def test_a_commanders_game_on_nfl_network_is_also_on_fox_5(self):
        catalog = self.catalog(self.event(1, ('NFL Net',), '2026-10-04T13:30Z'),
                               self.event(2, ('NFL Net',), '2026-10-04T13:30Z', home='DAL'),
                               self.event(3, ('CBS',), '2026-10-04T17:00Z'))
        self.assertEqual(catalog.local_simulcast('nfl', 1, '2026-10-04'), 'WTTG')
        self.assertIsNone(catalog.local_simulcast('nfl', 2, '2026-10-04'), 'not a Washington game')
        self.assertIsNone(catalog.local_simulcast('nfl', 3, '2026-10-04'), 'already on a network')
        self.assertIsNone(catalog.local_simulcast('mlb', 1, '2026-10-04'))

    def test_sunday_ticket_lists_only_sunday_afternoon_cbs_and_fox_games(self):
        catalog = self.catalog(self.event(1, ('NFL Net',), '2026-10-04T13:30Z'),
                               self.event(2, ('CBS',), '2026-10-04T17:00Z', home='CIN'),
                               self.event(3, ('NBC',), '2026-10-05T00:20Z'),
                               self.event(4, (), '2026-10-04T20:25Z'))
        games = {g['game_id']: g for g in catalog.games('nfl', '2026-10-04')['games']}
        self.assertEqual({i: g['on_sunday_ticket'] for i, g in games.items()}, {1: False, 2: True, 3: False, 4: True})
        self.assertIsNone(games[1]['sunday_ticket_target'])
        self.assertEqual(games[2]['sunday_ticket_target']['source_id'], 'sunday-ticket')


class NewLeagueTests(unittest.TestCase):
    def test_college_football_filters_conferences_and_keeps_nonconference_games(self):
        events = []
        for event_id, conference in enumerate(('1', '4', '5', '8', '9', '151', None), 1):
            event = espn_event(event_id, 'Visitor', 'Host', broadcasts=('ABC',))
            event['competitions'][0]['competitors'][0]['team']['conferenceId'] = conference
            events.append(event)
        notre_dame = espn_event(87, 'Notre Dame', 'Navy', broadcasts=('NBC',))
        notre_dame['competitions'][0]['competitors'][1]['team']['id'] = '87'
        events.append(notre_dame)
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(json.dumps({'events': events}).encode())
        config = Mock()
        config.resolve_channel.side_effect = lambda name: (0, type('Channel', (), {'name': name})())
        catalog = SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener))
        result = catalog.games('ncaaf', '2026-10-03')
        self.assertEqual([g['game_id'] for g in result['games']], [1, 2, 3, 4, 5, 87])
        self.assertEqual(calls, ['https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard'
                                 '?dates=20261003&groups=80&limit=1000'])
        self.assertEqual(result['games'][0]['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'ABC'})
        self.assertTrue(all(g['sunday_ticket_target'] is None for g in result['games']))
        self.assertEqual(catalog.game_status(87, '2026-10-03', 'ncaaf')['finished'], False)
        self.assertEqual(len(calls), 1, 'status reuses the cached scoreboard')

    def test_college_football_final_and_overtime_release_the_queue(self):
        event = espn_event(1, 'Visitor', 'Host', state='post', period=5, detail='Final/OT')
        event['competitions'][0]['competitors'][0]['team']['conferenceId'] = 8
        board = EspnScoreboard(opener=lambda request, timeout: io.BytesIO(json.dumps({'events': [event]}).encode()))
        status = SportsCatalog(None, None, scoreboard=board).game_status(1, '2026-10-03', 'ncaaf')
        self.assertTrue(status['finished'])
        self.assertTrue(status['closing'])
        self.assertFalse(closing('ncaaf', {'state': 'in', 'period': 3, 'clock': 60}))
        self.assertTrue(closing('ncaaf', {'state': 'in', 'period': 4, 'clock': 120}))
        self.assertTrue(closing('ncaaf', {'state': 'in', 'period': 5, 'clock': 600}))
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        self.assertEqual((estimated_end('ncaaf', {}, now) - now).total_seconds(), 3.5 * 3600)

    def test_upcoming_reads_ten_espn_days_and_suggests_configured_channels(self):
        urls = []
        # The window starts today (Eastern): a game on its third day.
        third = datetime.now(ZoneInfo('America/New_York')).date() + timedelta(days=2)

        def opener(request, timeout):
            urls.append(request.full_url)
            day = request.full_url.rsplit('=', 1)[1]
            events = [espn_event(int(day), 'Boston Bruins', 'Washington Capitals')] if day == f'{third:%Y%m%d}' else []
            return io.BytesIO(json.dumps({'events': events}).encode())
        config = Mock()
        channel = Mock()
        channel.name = 'TNT'
        config.resolve_channel.return_value = (0, channel)
        result = SportsCatalog(config, None, scoreboard=EspnScoreboard(opener=opener)).upcoming('nhl', 10)
        self.assertEqual(len(urls), 10)
        self.assertTrue(all('/hockey/nhl/scoreboard?dates=' in url for url in urls))
        game, = result['games']
        self.assertEqual((game['league'], game['game_date'], game['channels'], game['home']['id']),
                         ('nhl', third.isoformat(), ['TNT'], '23'))
        self.assertEqual(game['suggested_target'], {'source_id': 'youtube-tv', 'channel_id': 'TNT'})
        with self.assertRaises(ConfigError):
            SportsCatalog(config, None).upcoming('xfl')

    def test_teams_come_from_espn_and_are_cached(self):
        calls = []
        payload = {'sports': [{'leagues': [{'teams': [
            {'team': {'id': '23', 'abbreviation': 'WSH', 'displayName': 'Washington Capitals', 'shortDisplayName': 'Capitals'}},
            {'team': {'id': '1', 'abbreviation': 'BOS', 'displayName': 'Boston Bruins', 'shortDisplayName': 'Bruins'}}]}]}]}

        def opener(request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(json.dumps(payload).encode())
        board = EspnScoreboard(opener=opener)
        teams = SportsCatalog(None, None, scoreboard=board).teams('nwsl')
        self.assertEqual([t['abbreviation'] for t in teams], ['BOS', 'WSH'])
        board.teams('nwsl')
        self.assertEqual(calls, ['https://site.api.espn.com/apis/site/v2/sports/soccer/usa.nwsl/teams?limit=1000'])

    def test_estimated_end_counts_periods_and_breaks(self):
        now = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
        minutes = lambda league, period: round((estimated_end(league, {'state': 'in', 'period': period}, now) - now).total_seconds() / 60)
        self.assertEqual(minutes('nhl', 1), round(2.5 * 38 + 2 * 18))
        self.assertEqual(minutes('nhl', 3), 19)
        self.assertEqual(minutes('nwsl', 1), round(1.5 * 52 + 15))
        self.assertEqual(minutes('wnba', 4), 14)
        self.assertEqual(minutes('nfl', 2), round(2.5 * 45 + 15))  # unchanged from before


if __name__ == '__main__':
    unittest.main()
