"""Games for sports mode: MLB from the Stats API; college football and other leagues from ESPN's
public scoreboard (which also gives MLB score lines and every league's teams, for the crawl).

Each game has a league, an integer id, a title, a start time and its TV
networks. `game_status()` is the queue's end-of-game gate for every league.
Suggested channels are only hints: Sunday-afternoon NFL games on CBS and FOX
are regional, so only the DC-market game is on WUSA or FOX 5. Other games in
those windows are suggested as Sunday Ticket, which blacks out the local game.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .baseball import EXCLUSIVES, scoreline
from .errors import BaseballScheduleError, ChannelNotFoundError, ConfigError

ESPN_URL = 'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day}'
ESPN_WEEK_URL = 'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard{query}'
ESPN_EVENT_URL = 'https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={id}'
ESPN_TEAMS_URL = 'https://site.api.espn.com/apis/site/v2/sports/{path}/teams'
LEAGUES = {'mlb': 'MLB', 'nfl': 'NFL', 'ncaaf': 'College Football (Power 5)',
           'nba': 'NBA', 'nhl': 'NHL', 'wnba': 'WNBA', 'nwsl': 'NWSL'}
ESPN_PATHS = {'mlb': 'baseball/mlb', 'nfl': 'football/nfl', 'nba': 'basketball/nba', 'nhl': 'hockey/nhl',
              'wnba': 'basketball/wnba', 'nwsl': 'soccer/usa.nwsl', 'ncaaf': 'football/college-football'}
# Leagues whose games come from ESPN in sports mode (MLB uses the Stats API and its own routing).
ESPN_LEAGUES = ('nfl', 'nba', 'nhl', 'wnba', 'nwsl', 'ncaaf')
# ESPN's current conference memberships: ACC, Big 12, Big Ten, SEC, Pac-12.
POWER_FIVE_CONFERENCES = frozenset({'1', '4', '5', '8', '9'})
NOTRE_DAME_ID = '87'
# Teams whose Sunday CBS/FOX games are broadcast in the DC market rather than on Sunday Ticket.
LOCAL_NFL_TEAMS = {'WSH', 'BAL'}
# A Commanders game on a national cable channel is also broadcast over the air in DC: the
# channel -> the station's call sign. ESPN's feed does not list these. NFL Network on FOX 5
# was seen on 2026-10-04 (Colts at Commanders, in London); add others once seen.
LOCAL_SIMULCASTS = {'WSH': {'NFL Network': 'WTTG'}}
# ESPN network labels that differ from a configured channel name or alias.
NETWORK_ALIASES = {'NFL NET': 'NFL Network', 'NFL NETWORK': 'NFL Network', 'ESPN 2': 'ESPN2',
                   'FOX SPORTS 1': 'FS1', 'NBA TV': 'NBA TV', 'NHL NET': 'NHL Network',
                   'USA NET': 'USA Network'}
_EASTERN = ZoneInfo('America/New_York')
# A typical game from first pitch or kickoff to the final, for a schedule projection.
TYPICAL = {'mlb': timedelta(hours=2, minutes=50), 'nfl': timedelta(hours=3, minutes=10),
           'ncaaf': timedelta(hours=3, minutes=30),
           'nba': timedelta(hours=2, minutes=20), 'nhl': timedelta(hours=2, minutes=35),
           'wnba': timedelta(hours=2), 'nwsl': timedelta(hours=1, minutes=55)}
# Clock sports: (periods, real minutes per period, minutes of each long break, periods followed by one).
PERIODS = {'nfl': (4, 45, 15, (2,)), 'nba': (4, 35, 15, (2,)), 'wnba': (4, 28, 15, (2,)),
           'nhl': (3, 38, 18, (1, 2)), 'nwsl': (2, 52, 15, (1,)), 'ncaaf': (4, 48, 20, (2,))}
# MLB's game types for the wild card, division series, league championship and World Series.
MLB_POSTSEASON = frozenset({'F', 'D', 'L', 'W'})
# A game this close to its start already counts as on the channel (pregame coverage).
SOON = timedelta(hours=1)
# A game's closing stretch, when what follows it is prepared while it finishes (source_queue):
# baseball from this inning, clock sports with this many seconds left in regulation, or overtime.
CLOSING_INNING = 9
CLOSING_SECONDS = 120


def closing(league, game):
    """Whether a game is in its closing stretch or over: the 9th inning or later, the last
    2 minutes of regulation, or overtime. ESPN's clock counts down, except soccer's."""
    state = str(game.get('state') or '').casefold()
    if game.get('finished') is True or state in ('final', 'post'):
        return True
    period = game.get('period')
    if state not in ('live', 'in') or isinstance(period, bool) or not isinstance(period, int):
        return False
    if league == 'mlb':
        return period >= CLOSING_INNING
    count = PERIODS.get(league, PERIODS['nba'])[0]
    clock = game.get('clock')
    if period != count or isinstance(clock, bool) or not isinstance(clock, (int, float)):
        return period > count
    if league == 'nwsl':
        return clock >= 90 * 60 - CLOSING_SECONDS
    return clock <= CLOSING_SECONDS


def estimated_end(league, game, now):
    """When a game will likely go final: now for a final, from the inning or quarter while
    live, else a typical length from its start. An estimate for projections only."""
    state = str(game.get('state') or '').casefold()
    start = game.get('start_time')
    try:
        start = datetime.fromisoformat(str(start).replace('Z', '+00:00')) if start else None
    except ValueError:
        start = None
    if game.get('finished') is True or state in ('final', 'post'):
        return now
    period = game.get('period') if isinstance(game.get('period'), int) else None
    if state in ('live', 'in') and period:
        if league == 'mlb':
            # Half-innings played: Top 3rd is 4.5, Bottom 3rd 5.5, End 3rd 6.
            half = {'top': .5, 'middle': 1, 'bottom': 1.5, 'end': 2}.get(str(game.get('half') or '').casefold(), 1)
            left = max(18 - ((period - 1) * 2 + half), .5) * 9
        else:
            count, minutes, pause, breaks = PERIODS.get(league, PERIODS['nba'])
            left = max(count - period + .5, .25) * minutes + pause * sum(1 for after in breaks if after >= period)
        return now + timedelta(minutes=left)
    if start is None:
        return now + TYPICAL.get(league, TYPICAL['mlb'])
    return max(start + TYPICAL.get(league, TYPICAL['mlb']), now + timedelta(minutes=10) if state in ('live', 'in') else start)


def _day(value):
    if value is None:
        return datetime.now(_EASTERN).date().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ConfigError('date must use YYYY-MM-DD format') from exc


class EspnScoreboard:
    def __init__(self, *, timeout=8, cache_seconds=30, opener=urlopen):
        self.timeout, self.cache_seconds, self.opener = timeout, cache_seconds, opener
        self._cache = {}
        self._lock = threading.Lock()

    def _get(self, url, league, details):
        try:
            with self.opener(Request(url, headers={'Accept': 'application/json', 'User-Agent': 'VizelVision/0.2'}),
                             timeout=self.timeout) as response:
                payload = json.loads(response.read(4 * 1024 * 1024))
        except (OSError, URLError, ValueError) as exc:
            raise BaseballScheduleError(f'Could not load the {LEAGUES[league]} schedule: {exc}',
                                        details={'league': league, **details}) from exc
        return payload if isinstance(payload, dict) else {}

    def _fetch(self, key, url, league, details):
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self.cache_seconds:
                return cached[1]
        payload = self._get(url, league, details)
        games = [self._normalize(league, event) for event in payload.get('events', [])
                 if isinstance(event, dict) and (league != 'ncaaf' or self._power_five_game(event))]
        games.sort(key=lambda g: g['start_time'] or '')
        result = (games, payload)
        with self._lock:
            self._cache[key] = (time.monotonic(), result)
        return result

    @staticmethod
    def _power_five_game(event):
        # Either team qualifies, so nonconference games and postseason matchups stay visible.
        competition = (event.get('competitions') or [{}])[0]
        return any(str(team.get('conferenceId')) in POWER_FIVE_CONFERENCES
                   or str(team.get('id')) == NOTRE_DAME_ID
                   for competitor in competition.get('competitors') or [] if isinstance(competitor, dict)
                   for team in [competitor.get('team') or {}])

    def games(self, league, day):
        url = ESPN_URL.format(path=ESPN_PATHS[league], day=day.replace('-', ''))
        if league == 'ncaaf':
            # Default ESPN college scoreboards only list ranked teams; request all FBS games.
            url += '&groups=80&limit=1000'
        return self._fetch((league, day), url, league, {'date': day})[0]

    def week(self, league, season_type=None, week=None):
        """One NFL week, the current one when week is None, with the season's week calendar."""
        query = f'?seasontype={season_type}&week={week}' if week is not None else ''
        games, payload = self._fetch((league, 'week', season_type, week),
                                     ESPN_WEEK_URL.format(path=ESPN_PATHS[league], query=query), league,
                                     {'season_type': season_type, 'week': week})
        season = payload.get('season') or {}
        weeks = []
        for league_info in (payload.get('leagues') or [])[:1]:
            for part in league_info.get('calendar') or []:
                for entry in part.get('entries') or []:
                    weeks.append({'season_type': int(part.get('value') or 0), 'week': int(entry.get('value') or 0),
                                  'label': entry.get('label'), 'detail': entry.get('detail'),
                                  'start': entry.get('startDate'), 'end': entry.get('endDate')})
        current = {'season_type': season.get('type', season_type),
                   'week': (payload.get('week') or {}).get('number', week), 'year': season.get('year')}
        return games, current, weeks

    def teams(self, league):
        key = (league, 'teams')
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 86400:
                return cached[1]
        # Without a limit ESPN lists 50 teams: no Michigan State among college football's.
        payload = self._get(ESPN_TEAMS_URL.format(path=ESPN_PATHS[league]) + '?limit=1000', league, {'teams': True})
        teams = []
        for sport in payload.get('sports') or []:
            for entry in (sport.get('leagues') or [{}])[0].get('teams') or []:
                team = entry.get('team') or {}
                if team.get('id') and team.get('displayName'):
                    teams.append({'id': str(team['id']), 'abbreviation': team.get('abbreviation') or '',
                                  'name': team['displayName'], 'short': team.get('shortDisplayName') or team['displayName']})
        teams.sort(key=lambda team: team['name'])
        if teams:
            with self._lock:
                self._cache[key] = (time.monotonic(), teams)
        return teams

    def event(self, league, event_id):
        """One game by id on whatever date it is now, or None once ESPN no longer has it."""
        try:
            payload = self._get(ESPN_EVENT_URL.format(path=ESPN_PATHS[league], id=event_id), league, {'event': event_id})
        except BaseballScheduleError as exc:
            if isinstance(exc.__cause__, HTTPError) and exc.__cause__.code == 404:
                return None
            raise
        header = payload.get('header') or {}
        competition = (header.get('competitions') or [None])[0]
        if not isinstance(competition, dict):
            return None
        teams = {c.get('homeAway'): (c.get('team') or {}).get('displayName')
                 for c in competition.get('competitors') or [] if isinstance(c, dict)}
        return self._normalize(league, {'id': header.get('id') or event_id, 'date': competition.get('date'),
                                        'status': competition.get('status'), 'competitions': [competition],
                                        'season': header.get('season'),
                                        'name': f"{teams.get('away')} at {teams.get('home')}"
                                                if teams.get('away') and teams.get('home') else None})

    @staticmethod
    def _normalize(league, event):
        competition = (event.get('competitions') or [{}])[0]
        clock = event.get('status') or {}
        status = clock.get('type') or {}
        broadcasts = [{'name': name, 'market': item.get('market')}
                      for item in competition.get('broadcasts') or [] if isinstance(item, dict)
                      for name in item.get('names') or []]
        name = str(status.get('name') or '')
        teams = {c.get('homeAway'): {'id': (c.get('team') or {}).get('id'),
                                     'name': (c.get('team') or {}).get('displayName'),
                                     'nickname': (c.get('team') or {}).get('name'),
                                     'abbreviation': (c.get('team') or {}).get('abbreviation'),
                                     'score': c.get('score')}
                 for c in competition.get('competitors') or [] if isinstance(c, dict)}
        return {'league': league, 'away': teams.get('away'), 'home': teams.get('home'), 'game_id': int(event['id']), 'title': event.get('name') or event.get('shortName'),
                'short_title': event.get('shortName'), 'start_time': event.get('date'),
                'start_time_tbd': competition.get('timeValid') is False,
                'status': status.get('description') or status.get('detail') or 'Unknown',
                'state': status.get('state') or 'unknown',
                # "4th - 2:31", "Halftime", "Final/OT".
                'detail': status.get('shortDetail') or None,
                'period': clock.get('period'),
                # Seconds left in the period (soccer: seconds played).
                'clock': clock.get('clock'),
                # Postponed and cancelled games also release the backup.
                'finished': status.get('completed') is True or status.get('state') == 'post'
                            or name in ('STATUS_POSTPONED', 'STATUS_CANCELED', 'STATUS_CANCELLED'),
                # Playoffs, the World Series, bowls: ESPN's season type 3.
                'postseason': (event.get('season') or {}).get('type') == 3,
                'broadcasts': broadcasts}


class SportsCatalog:
    def __init__(self, config, baseball, *, scoreboard=None):
        self.config, self.baseball = config, baseball
        self.scoreboard = scoreboard or EspnScoreboard()

    @staticmethod
    def league(value):
        league = value or 'mlb'
        if league not in LEAGUES:
            raise ConfigError('league must be one of ' + ', '.join(LEAGUES))
        return league

    def _channel(self, name):
        name = NETWORK_ALIASES.get(name.upper(), name)
        if name.rstrip().endswith('+'):
            # ESPN+, Paramount+: streaming, though a lookup that drops the "+" finds ESPN.
            # On 2026-10-17 ESPN+-only NHL games were suggested on ESPN.
            return None
        try:
            return self.config.resolve_channel(name)[1].name
        except ChannelNotFoundError:
            return None

    def _suggest(self, game):
        national = [b['name'] for b in game['broadcasts'] if b.get('market') in (None, 'national')]
        channels = list(dict.fromkeys(filter(None, map(self._channel, national))))
        if not channels:  # A streaming exclusive (EXCLUSIVES): the channel that carries them.
            channels = list(dict.fromkeys(filter(None, (self._channel(EXCLUSIVES[n.upper()])
                                                        for n in national if n.upper() in EXCLUSIVES))))
        start = datetime.fromisoformat(game['start_time'].replace('Z', '+00:00')).astimezone(_EASTERN) \
            if game.get('start_time') else None
        regional = bool(game['league'] == 'nfl' and start and start.weekday() == 6 and start.hour < 19
                        and any(c in ('CBS', 'FOX') for c in channels))
        local = {(game.get(side) or {}).get('abbreviation') for side in ('away', 'home')} & LOCAL_NFL_TEAMS
        # Sunday Ticket carries the Sunday-afternoon CBS and FOX games, never a national
        # exclusive (NFL Network, ESPN, NBC at night): on 2026-10-04 Colts at Commanders, on
        # NFL Network, was picked from its listing and looked for there in vain.
        networks = {NETWORK_ALIASES.get(str(b['name']).upper(), b['name']) for b in game['broadcasts']}
        on_ticket = bool(game['league'] == 'nfl' and start and start.weekday() == 6 and start.hour < 19
                         and (not networks or networks & {'CBS', 'FOX'}))
        ticket = {'source_id': 'sunday-ticket', 'channel_id': str(game['game_id']),
                  'date': start.date().isoformat() if start else None}
        from .prime_video import prime_nfl_game
        prime = {'source_id': 'thursday-night-football', 'channel_id': str(game['game_id']),
                 'date': start.date().isoformat() if start else None} if prime_nfl_game(game) else None
        # An NHL game ESPN Unlimited streams inside YouTube TV, found on its ESPN page (2026-10-22).
        from .espn_unlimited import SOURCE_ID as NHL_SOURCE, note as espn_note, nhl_on_espn_unlimited
        stream = nhl_on_espn_unlimited(game)
        espn = {'source_id': NHL_SOURCE, 'channel_id': str(game['game_id']),
                'date': start.date().isoformat() if start else None} if stream else None
        if prime:
            suggestion = prime
            note = 'Thursday Night Football on Prime Video. Sign in on the Roku if prompted.'
        elif espn and not channels:
            suggestion, note = espn, espn_note(stream)
        elif regional and not local:
            suggestion = ticket
            note = ('Out of market: NFL Sunday Ticket (found by reading the YouTube TV guide). '
                    'If this game is on WUSA or FOX 5 in DC, choose that channel instead.')
        else:
            suggestion = {'source_id': 'youtube-tv', 'channel_id': channels[0]} if channels else None
            note = ('Regional CBS/FOX window with a DC team: the local station carries it.' if regional else
                    None if channels else 'No national broadcast on a configured channel; choose a source.')
        return {**game, 'suggested_target': suggestion, 'channels': channels, 'note': note,
                'prime_video_target': prime, 'on_sunday_ticket': on_ticket,
                'sunday_ticket_target': ticket if on_ticket else None,
                'espn_unlimited': stream, 'espn_unlimited_target': espn}

    def games(self, league, requested_date=None):
        league, day = self.league(league), _day(requested_date)
        if league == 'mlb':
            catalog = self.baseball.games(day)
            games = [{'league': 'mlb', 'game_id': g['game_pk'], 'title': g['title'], 'short_title': g['title'],
                      'start_time': g['start_time'], 'status': g['status'], 'state': g['state'],
                      'broadcasts': [{'name': b['name'], 'market': 'national' if b.get('is_national') else None}
                                     for b in g.get('broadcasts', [])],
                      'suggested_target': None, 'channels': [],
                      'note': 'Automatic: MLB routing picks a national channel or MLB.TV.',
                      'official_date': g.get('official_date')} for g in catalog['games']]
        else:
            games = [self._suggest(g) for g in self.scoreboard.games(league, day)]
        return {'league': league, 'date': day, 'generated_at': datetime.now(timezone.utc).isoformat(), 'games': games}

    def week(self, league, season_type=None, week=None):
        """A whole NFL week for the schedule browser. game_date is the game's Eastern date."""
        league = self.league(league or 'nfl')
        if league != 'nfl':
            raise ConfigError('Weekly schedules are available for the NFL')
        if (season_type is None) != (week is None):
            raise ConfigError('seasontype and week go together')
        for value in (season_type, week):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 25):
                raise ConfigError('seasontype and week must be small integers')
        games, current, weeks = self.scoreboard.week(league, season_type, week)
        result = []
        for game in games:
            start = datetime.fromisoformat(game['start_time'].replace('Z', '+00:00')) if game.get('start_time') else None
            result.append({**self._suggest(game), 'game_date': start.astimezone(_EASTERN).date().isoformat() if start else None})
        return {'league': league, **current, 'weeks': [w for w in weeks if w['season_type'] in (2, 3)],
                'generated_at': datetime.now(timezone.utc).isoformat(), 'games': result}

    def upcoming(self, league, days=10):
        """A league's games from today (Eastern) for the schedule browser. ESPN takes one day per
        request, so the days are fetched side by side."""
        league = self.league(league)
        if league == 'mlb':
            return self.upcoming_mlb(days)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ConfigError('days must be from 1 through 31')
        start = datetime.now(_EASTERN).date()
        dates = [(start + timedelta(days=offset)).isoformat() for offset in range(days)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            daily = list(pool.map(lambda day: self.scoreboard.games(league, day), dates))
        games = []
        for day, listed in zip(dates, daily):
            games.extend({**self._suggest(game), 'game_date': day} for game in listed)
        return {'league': league, 'start': start.isoformat(), 'days': days,
                'generated_at': datetime.now(timezone.utc).isoformat(), 'games': games}

    def teams(self, league):
        """A league's teams from ESPN: [{id, abbreviation, name, short}] by name."""
        return self.scoreboard.teams(self.league(league))

    def upcoming_mlb(self, days=10):
        """MLB games from today (Eastern) for the schedule browser, on YouTube TV where carried."""
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ConfigError('days must be from 1 through 31')
        start = datetime.now(_EASTERN).date()
        games = []
        for g in self.baseball.range(start.isoformat(), (start + timedelta(days=days - 1)).isoformat()):
            channels = [s['channel'] for s in g.get('sources', []) if s.get('provider') == 'youtube_tv']
            national = [b['name'] for b in g.get('broadcasts', []) if b.get('is_national')]
            note = (None if channels else
                    f"{', '.join(dict.fromkeys(national))} is not a configured YouTube TV channel; automatic routing tries MLB.TV."
                    if national else 'No national broadcast; automatic routing uses MLB.TV.')
            if g.get('start_time_tbd'):
                note = ' '.join(filter(None, ['Start time to be announced.', note]))
            games.append({'league': 'mlb', 'game_id': g['game_pk'], 'title': g['title'],
                          'short_title': g['title'], 'start_time': g['start_time'], 'game_date': g.get('official_date'),
                          'status': g['status'], 'state': g['state'].casefold(),
                          'start_time_tbd': g.get('start_time_tbd', False), 'if_necessary': g.get('if_necessary', False),
                          'series': g.get('series'), 'series_game': g.get('series_game'),
                          'postseason': g.get('game_type') in MLB_POSTSEASON,
                          'away': g.get('away'), 'home': g.get('home'),
                          # MLB.TV streams it (automatic routing's last resort).
                          'streams': any(s.get('provider') == 'mlb' for s in g.get('sources', [])),
                          'broadcasts': [{'name': b['name'], 'market': 'national' if b.get('is_national') else None}
                                         for b in g.get('broadcasts', [])],
                          'channels': channels,
                          # None means automatic MLB routing (national channel or MLB.TV).
                          'suggested_target': {'source_id': 'youtube-tv', 'channel_id': channels[0]} if channels else None,
                          'note': note})
        return {'league': 'mlb', 'start': start.isoformat(), 'days': days,
                'generated_at': datetime.now(timezone.utc).isoformat(), 'games': games}

    @staticmethod
    def _airing(live, finished, start_time, now):
        if finished:
            return False
        if live:
            return True
        try:
            start = datetime.fromisoformat(str(start_time).replace('Z', '+00:00'))
        except ValueError:
            return False
        return start.tzinfo is not None and now - timedelta(hours=6) <= start <= now + SOON

    def _station(self, name):
        """The configured channel an over-the-air station matches, by name or call sign (WUSA-HD is WUSA)."""
        for candidate in dict.fromkeys((name or '', re.split(r'[-\s.]', (name or '').strip())[0])):
            channel = self._channel(candidate) if candidate else None
            if channel:
                return channel
        return None

    def games_on(self, target, channel_name=None, now=None):
        """Games a source carries now or within the hour: the game itself
        for a game source's target (MLB, Sunday Ticket, Prime Video, NHL on ESPN Unlimited),
        else national games on its channel. A TV-Thing station is matched through
        channel_name. Returns (games, warnings)."""
        now = now or datetime.now(timezone.utc)
        source = target.get('source_id')
        found, warnings = [], []

        def add(league, game_id, day, title, status, live):
            found.append({'league': league, 'game_pk': game_id, 'game_date': day, 'title': title,
                          'status': status, 'live': live})

        if source in ('mlb', 'sunday-ticket', 'thursday-night-football', 'nhl'):
            league = {'mlb': 'mlb', 'nhl': 'nhl'}.get(source, 'nfl')
            try:
                game_id = int(target.get('channel_id'))
                day = _day(target.get('date'))
                status = self.game_status(game_id, day, league)
            except (TypeError, ValueError, ConfigError, BaseballScheduleError) as exc:
                return [], [str(exc)]
            if status.get('finished') is not True:
                add(league, game_id, day, status.get('title'), status.get('status'),
                    str(status.get('state') or '').casefold() in ('live', 'in'))
            return found, warnings
        channel = self._channel(str(target.get('channel_id') or '')) if source == 'youtube-tv' else self._station(channel_name)
        if channel is None:
            return [], []
        eastern = now.astimezone(_EASTERN)
        # Late games run past midnight Eastern, so early mornings also check yesterday.
        days = dict.fromkeys(d.date().isoformat() for d in (eastern - timedelta(hours=6), eastern))
        for day in days:
            try:
                for g in self.baseball.games(day)['games']:
                    state = str(g.get('state') or '').casefold()
                    channels = [s.get('channel') for s in g.get('sources', []) if s.get('provider') == 'youtube_tv']
                    if channel in channels and self._airing(state == 'live', state == 'final', g.get('start_time'), now):
                        add('mlb', g['game_pk'], day, g['title'], g.get('status'), state == 'live')
            except BaseballScheduleError as exc:
                warnings.append(str(exc))
            for league in ESPN_LEAGUES:
                try:
                    games = self.scoreboard.games(league, day)
                except BaseballScheduleError as exc:
                    warnings.append(str(exc))
                    continue
                for g in map(self._suggest, games):
                    # Out-of-market Sunday games are suggested on Sunday Ticket, not the local station.
                    if (channel in g['channels'] and (g['suggested_target'] or {}).get('source_id') == 'youtube-tv'
                            and self._airing(g['state'] == 'in', g['finished'], g.get('start_time'), now)):
                        add(league, g['game_id'], day, g['title'], g['status'], g['state'] == 'in')
        return found, list(dict.fromkeys(warnings))

    def local_simulcast(self, league, game_id, requested_date=None):
        """The call sign of the DC station that also broadcasts a game shown on a national cable
        channel (LOCAL_SIMULCASTS), or None."""
        if league != 'nfl':
            return None
        game = self._suggest(self.game(league, game_id, requested_date))
        for side in ('home', 'away'):
            stations = LOCAL_SIMULCASTS.get((game.get(side) or {}).get('abbreviation'), {})
            sign = next((stations[c] for c in game['channels'] if c in stations), None)
            if sign:
                return sign
        return None

    def game(self, league, game_id, requested_date=None):
        league = self.league(league)
        if league == 'mlb':
            return self.baseball.game(game_id, requested_date)
        match = next((g for g in self.scoreboard.games(league, _day(requested_date)) if g['game_id'] == game_id), None)
        if match is None:
            raise ConfigError(f'{LEAGUES[league]} game {game_id} is not on the requested date')
        return match

    def locate(self, league, game_id):
        """Where a scheduled game is now, for following schedule changes: its title, start,
        date and whether it was cancelled; None once its feed no longer lists it."""
        league = self.league(league)
        game = self.baseball.locate(game_id) if league == 'mlb' else self.scoreboard.event(league, game_id)
        if game is None:
            return None
        start = game.get('start_time')
        day = game.get('official_date') if league == 'mlb' else (
            datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(_EASTERN).date().isoformat() if start else None)
        return {'league': league, 'game_id': game_id, 'title': game.get('title'), 'start_time': start,
                'start_time_tbd': game.get('start_time_tbd') is True, 'game_date': day, 'status': game.get('status'),
                'cancelled': str(game.get('status') or '').casefold() in ('cancelled', 'canceled')}

    def game_status(self, game_id, requested_date=None, league=None):
        """The queue's end-of-game gate; MLB keeps its original status rules."""
        league = self.league(league)
        if league == 'mlb':
            status = self.baseball.game_status(game_id, requested_date)
            return {**status, 'closing': closing('mlb', status)}
        game = self.game(league, game_id, requested_date)
        return {'game_pk': game_id, 'title': game['title'], 'state': game['state'],
                'status': game['status'], 'summary': scoreline(game), 'finished': game['finished'],
                'closing': closing(league, game)}
