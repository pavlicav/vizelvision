"""The "We now join..." bumper: before master joins a game already under way, the
VizelVision Sports voice says where it stands, over a 10-second cut of the Sports ID
(ident/vizelvision-sports-join.mp4, built by ident/build.py --join):

    "We now join the Bengals and the Jaguars, who are tied at 7 in the fourth quarter."
    "We now join the Dodgers and the Braves, with the Braves leading 3 to 1 in the bottom
     of the fifth."

The source coordinator asks for it once the game's source is ready (clip), with the score
as the sports feeds have it then (MLB's within a minute, ESPN's within 30 s). The line is
voiced by Deepgram in the Sports ID's voice (kept by its text) and mixed over the cut's
music as continuity's announcements are (continuity.mix). warm() voices it as soon as the
source starts preparing, so it is usually ready by the time it is wanted; a game whose
score changes meanwhile is voiced again then, within clip's timeout, or goes without.

Master plays it where the station ID holds its end card, after the wait fill's ads, in
place of the Sports ID's second half, and the take lands at its end (ad_break.py,
master_worker.py). A game not yet under way gets the Sports ID as before.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import threading

from .errors import ConfigError
from .ident import IDENT_PATH, file_identity

JOIN_VIDEO = IDENT_PATH.with_name('vizelvision-sports-join.mp4')
JOIN_MUSIC = IDENT_PATH.parent / 'build' / 'sports-join-music.wav'
LENGTH = 10.0
# The line starts once SPORTS has slammed in (0.7 s), earlier if it is long, and ends as the
# iris closes (8.2 to 9.3 s, then black): the take lands at 10 s (ident/build.py JOIN_CUTS).
EARLIEST, START, END = 0.8, 1.2, 9.0
# The Sports ID's voice (ident/sports_script.json).
MODEL = 'aura-2-jupiter-en'
PREFIX = 'join-'
MIX_VERSION = 1
GAME_SOURCES = {'thursday-night-football': 'nfl', 'sunday-ticket': 'nfl', 'mlb': 'mlb'}
ORDINALS = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
            'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth',
            'eighteenth', 'nineteenth', 'twentieth')
QUARTERS = ('nfl', 'ncaaf', 'nba', 'wnba')
LOG = logging.getLogger(__name__)


def ordinal(n):
    return ORDINALS[n - 1] if isinstance(n, int) and 1 <= n <= len(ORDINALS) else f'{n}th'


def _number(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def in_progress(league, game):
    """Whether a game (the sports catalog's) is under way: MLB with an inning on the board,
    ESPN's leagues in their 'in' state."""
    if not isinstance(game, dict):
        return False
    state = str(game.get('state') or '').casefold()
    if league == 'mlb':
        inning = _number(game.get('period'))
        warming = str(game.get('status') or '').casefold() in ('warmup', 'pre-game', 'delayed start')
        return state == 'live' and not warming and inning is not None and inning >= 1
    return state == 'in'


def score(away, home, a, b):
    """'who are tied at 7', 'who are scoreless', 'with the Braves leading 3 to 1'."""
    if a == b:
        return 'who are scoreless' if a == 0 else f'who are tied at {a}'
    leader, high, low = (away, a, b) if a > b else (home, b, a)
    return f'with the {leader} leading {high} to {low}'


def moment(league, game):
    """Where the game stands, as said after the score: 'in the bottom of the fifth', 'at
    halftime', 'with under 3 minutes left in the fourth quarter'; '' when not known."""
    period = _number(game.get('period'))
    detail = str(game.get('detail') or '').strip()
    folded = detail.casefold()
    if league == 'mlb':
        half = str(game.get('half') or '').casefold()
        if period is None:
            return ''
        return {'top': f'in the top of the {ordinal(period)}', 'bottom': f'in the bottom of the {ordinal(period)}',
                'middle': f'in the middle of the {ordinal(period)}', 'end': f'at the end of the {ordinal(period)}'
                }.get(half, f'in the {ordinal(period)} inning')
    if 'halftime' in folded:
        return 'at halftime'
    if period is None:
        return ''
    if league == 'nwsl':
        return {1: 'in the first half', 2: 'in the second half'}.get(period, 'in extra time')
    unit, regulation = ('period', 3) if league == 'nhl' else ('quarter', 4)
    if period > regulation:
        return 'in overtime'
    if folded.startswith('end of') or 'intermission' in folded:
        return f'at the end of the {ordinal(period)} {unit}'
    clock = game.get('clock')
    left = float(clock) if isinstance(clock, (int, float)) and not isinstance(clock, bool) else None
    if league in QUARTERS and period == regulation and left is not None and 0 < left <= 300:
        minutes = -(-int(left) // 60)
        return (f'with under {minutes} minutes left in the {ordinal(period)} {unit}' if minutes > 1
                else f'with under a minute left in the {ordinal(period)} {unit}')
    return f'in the {ordinal(period)} {unit}'


def line(league, game):
    """The update read over the bumper, or None when the game is not under way (or its
    teams or score are not known)."""
    if not in_progress(league, game):
        return None
    away, home = game.get('away') or {}, game.get('home') or {}
    names = [(team.get('nickname') or team.get('name') or '').strip() for team in (away, home)]
    a, b = _number(away.get('score')), _number(home.get('score'))
    if not all(names) or a is None or b is None:
        return None
    where = moment(league, game)
    said = score(names[0], names[1], a, b)
    joiner = ', ' if where.startswith('with') and said.startswith('with') else ' '
    return f'We now join the {names[0]} and the {names[1]}, {said}{joiner + where if where else ""}.'


def game_of(item=None, target=None, game=None):
    """The game a queue entry airs ({'league', 'game_pk', 'game_date'}), or None: a scheduled
    game's, the one a take is held for, or the game a game source's channel names."""
    for candidate in (getattr(item, 'game', None), (getattr(item, 'hold_end', None) or {}).get('game')):
        if isinstance(candidate, dict) and candidate.get('game_pk') is not None:
            return {'league': candidate.get('league') or 'mlb', 'game_pk': int(candidate['game_pk']),
                    'game_date': candidate.get('game_date')}
    target = target or getattr(item, 'target', None) or {}
    league = GAME_SOURCES.get(target.get('source_id'))
    if league and str(target.get('channel_id') or '').isdigit():
        return {'league': league, 'game_pk': int(target['channel_id']),
                'game_date': target.get('date') or (game or {}).get('official_date')}
    return None


class SportsJoin:
    """Makes the bumper for a game: sports(league, game_pk, date) is the catalog's game, voice
    a continuity.Voice, mix continuity.mix. Its files go in work_dir (the announcements folder,
    which master plays from), named join-<hash>.mp4."""
    KEEP = 8

    def __init__(self, work_dir, *, voice, sports, mix, video=JOIN_VIDEO, music=JOIN_MUSIC):
        self.work_dir, self.voice, self.sports, self.mix = Path(work_dir), voice, sports, mix
        self.video, self.music = Path(video), Path(music)
        self.lock = threading.Lock()
        self.making = {}             # line -> threading.Event, while it is voiced and mixed
        self.last = None             # {'line', 'file', 'at'} of the last clip handed out, for the page
        self.error = None

    def ready(self):
        return self.video.is_file() and self.music.is_file()

    def line_for(self, ref):
        """The update for a game ({'league', 'game_pk', 'game_date'}) as it stands, or None."""
        found = self.sports(ref['league'], ref['game_pk'], ref.get('game_date'))
        return line(ref['league'], found)

    def _path(self, text):
        key = json.dumps([MODEL, text, file_identity(self.video), file_identity(self.music), MIX_VERSION])
        return self.work_dir / (PREFIX + hashlib.sha256(key.encode()).hexdigest()[:16] + '.mp4')

    def _render(self, text):
        from .continuity import seconds
        out = self._path(text)
        if out.exists():
            return out
        spoken = self.voice.line(MODEL, text)
        length = seconds(spoken)
        start = START if START + length <= END else max(EARLIEST, END - length)
        if start + length > END + .25:
            raise ConfigError(f'"{text}" is too long to say in time ({length:.1f} s)')
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.mix([(spoken, start)], out, music=self.music, video=self.video, length=LENGTH)
        self._tidy(out)
        return out

    def _tidy(self, keep):
        files = sorted((p for p in self.work_dir.glob(PREFIX + '*.mp4')), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[self.KEEP:]:
            if path != keep:
                path.unlink(missing_ok=True)

    def _made(self, text, timeout):
        """The clip for text: made now (or by another thread meanwhile) within timeout
        seconds (None: as long as it takes); None when it is not ready by then."""
        out = self._path(text)
        if out.exists():
            return out
        with self.lock:
            event = self.making.get(text)
            mine = event is None
            if mine:
                event = self.making[text] = threading.Event()
        if mine:
            def make():
                try:
                    self._render(text)
                    self.error = None
                except (ConfigError, OSError) as exc:
                    self.error = f'The join bumper could not be made: {exc}'
                    LOG.warning('%s', self.error)
                finally:
                    with self.lock:
                        self.making.pop(text, None)
                    event.set()
            threading.Thread(target=make, name='sports-join', daemon=True).start()
        event.wait(timeout)
        return out if out.exists() else None

    def clip(self, ref, timeout=6.0):
        """{'path', 'seconds', 'line'} of the bumper for a game under way, as it stands now;
        None when it is not under way, or the bumper is not built or not ready in time."""
        if ref is None or not self.ready():
            return None
        try:
            text = self.line_for(ref)
            if text is None:
                return None
            out = self._made(text, timeout)
        except Exception as exc:  # A nicety: the take never waits on it.
            LOG.warning('No join bumper for %s: %s', json.dumps(ref), exc)
            return None
        if out is None:
            return None
        self.last = {'line': text, 'file': out.name, 'game': dict(ref)}
        return {'path': str(out), 'seconds': LENGTH, 'line': text}

    def warm(self, ref):
        """Voice the bumper for a game being prepared now, in the background, so clip()
        finds it made."""
        if ref is None or not self.ready():
            return

        def run():
            try:
                text = self.line_for(ref)
                if text:
                    self._made(text, None)
            except Exception as exc:
                LOG.info('Could not voice the join bumper ahead: %s', exc)
        threading.Thread(target=run, name='sports-join-warm', daemon=True).start()
