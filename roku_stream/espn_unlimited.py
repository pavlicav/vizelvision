"""ESPN Unlimited: which NHL and NWSL games stream inside YouTube TV, and how.

ESPN Unlimited, in YouTube TV's main plan since 2026-09-01, streams the NHL's
out-of-market games (NHL Power Play), its ESPN+ exclusives and the NWSL's ESPN+
games. Finding the game on YouTube TV's ESPN page, skipping a blacked-out stream
and verifying it plays is TV Thing's Roku lane's job since 2026-10-22; vizelVision
only offers and schedules it. Mirrors TV Thing's roku_control.sports
nhl_on_espn_unlimited and nwsl_on_espn_unlimited.
"""

SOURCE_ID = 'nhl'
NWSL_SOURCE_ID = 'nwsl'
# ESPN Unlimited's game sources, each named for its league.
SOURCE_IDS = (SOURCE_ID, NWSL_SOURCE_ID)
# "ESPN+" alone (7 of the last day's 8 in 2026) or beside another broadcast, which ESPN's
# scoreboard also writes "ESPN Unlmtd" (ESPN2, ESPN Unlmtd).
ESPN_UNLIMITED_NWSL = frozenset({'ESPN+', 'ESPN UNLMTD'})
# ESPN's scoreboard names both kinds with a national "ESPN+" broadcast; a game on ESPN, ABC,
# TNT or NHL Network has none and is on that channel instead. An exclusive also streams on
# Disney+ and Hulu (LA at NYI, 2026-10-22).
ESPN_UNLIMITED_NHL = 'ESPN+'
ESPN_EXCLUSIVE_ALSO = frozenset({'DISNEY+', 'HULU'})
# Teams ESPN Unlimited blacks out, and where: those of YouTube TV's market for the Roku
# (the Red Wings in Lansing until 2026-11-07, the Capitals in DC since).
NHL_LOCAL_TEAMS = {'WSH': 'DC'}
# TV Thing's refusals of a game it will not play here, not worth another walk of the ESPN page
# (minutes of Roku each): blacked out on the card before Select, or by the player after it.
# Its operation names the first only as navigation_failed, in these words (its code,
# espn_game_blacked_out, stays in the exception's details).
REFUSALS = ('program_blocked', 'espn_game_blacked_out')
BLACKED_OUT = 'blacked out on YouTube TV where the Roku is'


def nhl_on_espn_unlimited(game):
    """How an NHL game streams on ESPN Unlimited, or None when it does not.

    ``exclusive``: an ESPN+ exclusive, with no regional broadcast to black it out.
    ``blackout``: the markets that may black it out, by team (``{'WSH': 'DC'}``).
    ``home``/``away``: the regional broadcasts whose commentary those streams carry.
    """
    if game.get('league') != 'nhl':
        return None
    broadcasts = [b for b in game.get('broadcasts') or [] if isinstance(b, dict)]
    national = {str(b.get('name') or '').upper() for b in broadcasts if b.get('market') in (None, 'national')}
    if ESPN_UNLIMITED_NHL not in national:
        return None
    feeds = {side: [str(b['name']) for b in broadcasts if b.get('market') == side and b.get('name')]
             for side in ('home', 'away')}
    exclusive = bool(national & ESPN_EXCLUSIVE_ALSO)
    teams = [(game.get(side) or {}).get('abbreviation') for side in ('away', 'home')]
    blackout = {} if exclusive else {team: NHL_LOCAL_TEAMS[team] for team in teams if team in NHL_LOCAL_TEAMS}
    return {'exclusive': exclusive, 'blackout': blackout, **feeds}


def nwsl_on_espn_unlimited(game):
    """How an NWSL game streams on ESPN Unlimited, in nhl_on_espn_unlimited's terms, or None when
    it does not. No regional broadcast or local team to black it out is known of."""
    if game.get('league') != 'nwsl':
        return None
    names = {str(b.get('name') or '').upper() for b in game.get('broadcasts') or []
             if isinstance(b, dict) and b.get('market') in (None, 'national')}
    if not names & ESPN_UNLIMITED_NWSL:
        return None
    return {'exclusive': True, 'blackout': {}, 'home': [], 'away': []}


def on_espn_unlimited(game):
    """How a game of any league streams on ESPN Unlimited, or None when it does not."""
    return nhl_on_espn_unlimited(game) or nwsl_on_espn_unlimited(game)


def note(stream, league=SOURCE_ID):
    """What the schedule says about an ESPN Unlimited game: its kind, and where it may be blacked out."""
    if league == NWSL_SOURCE_ID:
        return 'NWSL on ESPN Unlimited in YouTube TV (ESPN+); the Roku takes 3-4 minutes to find it.'
    kind = 'an ESPN+ exclusive' if stream['exclusive'] else 'out of market'
    text = f'NHL on ESPN Unlimited in YouTube TV ({kind}); the Roku takes 3-4 minutes to find it.'
    if stream['blackout']:
        markets = ' or '.join(f'{market} ({team})' for team, market in stream['blackout'].items())
        text += f' May be blacked out: YouTube TV places the Roku in {markets}.'
    return text


def refused(error):
    """Whether TV Thing's failed navigation ({'code', 'message'}) refuses the game where the Roku
    is, so trying again would only repeat it."""
    error = error or {}
    return error.get('code') in REFUSALS or BLACKED_OUT in str(error.get('message') or '')
