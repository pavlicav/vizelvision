"""Favorites: the station's favorite teams, and whole playoffs, ranked best first.

One list (favorites.json beside queue.json) serves two things:

- The crawl's Scores segment shows the favorites' games today (crawl_feeds.ScoresFeed).
- With "on air" on, each favorite's game goes on the Schedule whenever it is on a channel
  VizelVision gets (FavoritesPlanner): a game show from its start that returns to the
  schedule after the final. Games on no such channel (ESPN+ only), or with no start time
  yet, are listed for the operator instead.

A favorite is "league:<ESPN team id>" or "league:playoffs": every postseason game of the
league (the World Series, the NFL playoffs, college bowls). Places on the list rank
favorites' games among themselves, above normal shows and below high ones and takes put on
by hand (programming.show_rank): the higher favorite cuts in on a lower one at its start,
and a lower one starting during a higher one joins after its final, if still on.

The planner looks DAYS ahead every CHECK, and at once after a change. Games it scheduled
that have not started are taken off again once none of their favorites is on the list or
"on air" is off. A game it scheduled that someone removed from the Schedule stays off.

Until 2026-10-17 the crawl kept its followed teams in crawl.json (which the master worker
also reads and validates); they seed this list once.
"""
from __future__ import annotations

import copy
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading

from .errors import ConfigError
from .programming import SCHEDULE
from .scheduler import parse_time, utc_now
from .sports import LEAGUES

LIMIT = 80
PLAYOFFS = 'playoffs'
_FAVORITE = re.compile(r'([a-z]+):(\d{1,8}|playoffs)')
DAYS = 7
CHECK = timedelta(minutes=10)
# How long a favorite's game is scheduled for, from its start (the pages' OnAir.HOURS). The
# queue keeps a game on air until its final whatever its window.
WINDOW = {'nfl': 3.75, 'ncaaf': 4, 'nba': 2.75, 'mlb': 4, 'nhl': 3, 'wnba': 2.5, 'nwsl': 2.25}
# A scheduled game's record is kept this long past its start, so a removed game stays off.
KEPT = timedelta(days=3)
DONE = frozenset({'post', 'final', 'game over', 'completed early', 'postponed', 'cancelled', 'canceled'})
log = logging.getLogger(__name__)


def validate(value):
    if (not isinstance(value, list) or len(value) > LIMIT or len(set(value)) != len(value)
            or any(not isinstance(item, str) or not _FAVORITE.fullmatch(item) or item.split(':')[0] not in LEAGUES
                   for item in value)):
        raise ConfigError(f'favorites must list at most {LIMIT} unique "league:team id" or "league:playoffs"')
    return list(value)


def matches(league, game, team_ids):
    """The favorites a game is: each team's, and its league's playoffs after the regular season."""
    found = [f'{league}:{team}' for team in team_ids if team]
    if game.get('postseason'):
        found.append(f'{league}:{PLAYOFFS}')
    return found


class Favorites:
    """The ranked list, whether favorites go on air, and the games the planner scheduled."""

    def __init__(self, path, seed=lambda: ()):
        """seed() gives the crawl's old followed teams, read when there is no favorites.json."""
        self.path = Path(path)
        self.lock = threading.Lock()
        self.changed = lambda: None  # The planner's wake.
        self.data = self._load(seed)

    def _load(self, seed):
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            try:
                teams = [t for t in seed() if isinstance(t, str) and _FAVORITE.fullmatch(t)]
            except Exception as exc:  # No crawl settings: start empty.
                log.warning('Favorites: cannot read the crawl\'s teams: %s', exc)
                teams = []
            data = {'version': 1, 'favorites': validate(list(dict.fromkeys(teams))[:LIMIT]), 'air': False, 'planned': {}}
            self._write(data)
            return data
        except (OSError, ValueError) as exc:
            raise ConfigError(f'Cannot read favorites {self.path}: {exc}') from exc
        if not isinstance(raw, dict) or raw.get('version') != 1:
            raise ConfigError('Unsupported favorites file')
        return {'version': 1, 'favorites': validate(raw.get('favorites', [])), 'air': raw.get('air') is True,
                'planned': raw.get('planned') if isinstance(raw.get('planned'), dict) else {}}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.favorites-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
                stream.write('\n')
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def order(self):
        """The favorites, best first. Up next asks often: it is never read from disk."""
        with self.lock:
            return list(self.data['favorites'])

    def read(self):
        with self.lock:
            return {'favorites': list(self.data['favorites']), 'air': self.data['air']}

    def update(self, changes):
        """Changes favorites (the whole ranked list) and/or air (true or false)."""
        if not isinstance(changes, dict) or not changes or not set(changes) <= {'favorites', 'air'}:
            raise ConfigError('Favorites take favorites (a ranked list) and air (true or false)')
        if 'air' in changes and not isinstance(changes['air'], bool):
            raise ConfigError('air must be true or false')
        favorites = validate(changes['favorites']) if 'favorites' in changes else None
        with self.lock:
            if favorites is not None:
                self.data['favorites'] = favorites
            if 'air' in changes:
                self.data['air'] = changes['air']
            self._write(self.data)
        self.changed()
        return self.read()

    # The planner's record ---------------------------------------------------
    def planned(self):
        with self.lock:
            return copy.deepcopy(self.data['planned'])

    def note(self, key, show):
        with self.lock:
            self.data['planned'][key] = {'show_id': show['id'], 'start': show['start']}
            self._write(self.data)

    def forget(self, keys):
        with self.lock:
            gone = [k for k in keys if k in self.data['planned']]
            for key in gone:
                del self.data['planned'][key]
            if gone:
                self._write(self.data)


class FavoritesPlanner:
    """Puts the favorites' games on the Schedule (programming.Programming) from the sports
    catalog (sports.SportsCatalog), and lists what it found for the Favorites tab."""

    def __init__(self, favorites, programming, sports, *, clock=utc_now):
        self.favorites, self.programming, self.sports, self.clock = favorites, programming, sports, clock
        self.lock = threading.Lock()
        self.wake = threading.Condition()
        self.closed = self.poked = False
        self.thread = None
        self.last = {'checked_at': None, 'games': [], 'errors': {}}
        self._reported = set()
        favorites.changed = self.poke

    def _candidates(self, league, order):
        """A league's games in the next DAYS that are a favorite's, with where they are on."""
        listing = self.sports.upcoming(league, DAYS)['games']
        names = {}
        if league == 'mlb' and any(f.startswith('mlb:') and not f.endswith(PLAYOFFS) for f in order):
            # MLB's own schedule names its teams; favorites hold ESPN's ids.
            names = {t['name'].casefold(): t['id'] for t in self.sports.teams('mlb')}
        found = []
        for game in listing:
            sides = [game.get(side) or {} for side in ('away', 'home')]
            teams = ([names.get(str(side.get('name') or '').casefold()) for side in sides] if league == 'mlb'
                     else [str(side.get('id') or '') for side in sides])
            ids = matches(league, game, teams)
            if not set(ids) & set(order):
                continue
            target = game.get('suggested_target')
            if league == 'mlb' and target is None and game.get('streams'):
                # Automatic routing: MLB.TV when no national channel carries it.
                target = {'source_id': 'mlb', 'channel_id': str(game['game_id']), 'date': game.get('game_date')}
            networks = [b['name'] for b in game.get('broadcasts') or [] if league != 'mlb' or b.get('market') == 'national']
            found.append({'league': league, 'game_pk': game['game_id'], 'game_date': game.get('game_date'),
                          'title': game.get('title'), 'start_time': game.get('start_time'),
                          'tbd': game.get('start_time_tbd') is True, 'state': str(game.get('state') or '').casefold(),
                          'done': game.get('finished') is True or str(game.get('status') or '').casefold() in DONE
                                  or str(game.get('state') or '').casefold() in DONE,
                          'favorites': ids, 'target': target, 'networks': list(dict.fromkeys(networks))})
        return found

    def plan(self, now=None):
        """One pass: take off what is no longer wanted, schedule what is new. Returns the games."""
        now = now or self.clock()
        with self.lock:
            order, air = self.favorites.order(), self.favorites.read()['air']
            shows = self.programming.shows()
            planned = self.favorites.planned()
            # Ours that have not started go when no favorite of theirs is left, or air is off.
            for show in shows:
                if (show.get('added_by') == 'favorites' and parse_time(show['start']) > now
                        and (not air or not set(show.get('favorites') or ()) & set(order))):
                    self.programming.remove_show(show['id'])
                    key = f"{show['game']['league']}:{show['game']['game_pk']}"
                    self.favorites.forget([key])
                    planned.pop(key, None)
                    log.info('Favorites: %s is off the Schedule (%s)', show['title'],
                             'favorites off the air' if not air else 'no longer a favorite')
            shows = self.programming.shows()
            by_game = {(s['game']['league'], s['game']['game_pk']): s for s in shows if s.get('mode') == 'game'}
            games, errors = [], {}
            for league in dict.fromkeys(f.split(':')[0] for f in order):
                try:
                    games.extend(self._candidates(league, order))
                except Exception as exc:  # A feed down: what is scheduled stays, nothing new.
                    errors[league] = str(exc)
            games.sort(key=lambda g: (g['tbd'], g['start_time'] or ''))
            listed = []
            for game in games:
                key = f"{game['league']}:{game['game_pk']}"
                best = min((order.index(f) for f in game['favorites'] if f in order))
                entry = {k: game[k] for k in ('league', 'game_pk', 'game_date', 'title', 'start_time', 'tbd',
                                              'networks', 'target', 'favorites')}
                entry.update(favorite=order[best], rank=best + 1)
                existing = by_game.get((game['league'], game['game_pk']))
                if existing is not None:
                    entry.update(status='scheduled' if existing.get('added_by') == 'favorites' else 'by_hand',
                                 show_id=existing['id'], start=existing['start'])
                elif game['done']:
                    continue
                elif key in planned:
                    entry['status'] = 'removed'  # Someone took it off the Schedule.
                elif game['tbd'] or not game['start_time']:
                    entry['status'] = 'tbd'
                elif game['target'] is None:
                    entry['status'] = 'no_channel'
                elif not air:
                    entry['status'] = 'off'
                else:
                    entry.update(self._schedule(game, key, now))
                listed.append(entry)
            # Records of games long started whose show is gone.
            current = {s['id'] for s in shows} | {e.get('show_id') for e in listed}
            self.favorites.forget([k for k, v in self.favorites.planned().items()
                                   if v.get('show_id') not in current and parse_time(v['start']) < now - KEPT])
            self.last = {'checked_at': now.isoformat(), 'games': listed, 'errors': errors}
            return listed

    def _schedule(self, game, key, now):
        start = parse_time(game['start_time'])
        window = timedelta(hours=WINDOW.get(game['league'], 3))
        end = start + window
        # Under way (or about to be): it goes on now and joins in progress.
        start = max(start, now + timedelta(minutes=1))
        end = max(end, start + timedelta(minutes=30))
        value = {'mode': 'game', 'start': start.isoformat(), 'end': end.isoformat(), 'priority': 'normal',
                 'game': {'league': game['league'], 'game_pk': game['game_pk'], 'game_date': game['game_date']},
                 'target': game['target'], 'backup': dict(SCHEDULE)}
        try:
            show = self.programming.add_show(value, favorites=game['favorites'])
        except ConfigError as exc:  # Tried again at the next pass.
            if key not in self._reported:
                self._reported.add(key)
                log.warning('Favorites: cannot schedule %s: %s', game['title'], exc)
            return {'status': 'error', 'error': str(exc)}
        self._reported.discard(key)
        self.favorites.note(key, show)
        log.info('Favorites: %s scheduled for %s', show['title'], show['start'])
        return {'status': 'scheduled', 'show_id': show['id'], 'start': show['start']}

    def view(self):
        """The list, on air or not, and the favorites' games the last pass found."""
        return {**self.favorites.read(), **copy.deepcopy(self.last), 'days': DAYS,
                'check_minutes': int(CHECK.total_seconds() // 60)}

    # Worker ------------------------------------------------------------------
    def poke(self):
        with self.wake:
            self.poked = True
            self.wake.notify_all()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='favorites', daemon=True)
            self.thread.start()

    def _run(self):
        while True:
            with self.wake:
                self.poked = False  # A change from here on brings the next pass forward.
            try:
                self.plan()
            except Exception:  # Keep planning alive; the next pass retries.
                log.exception('Planning the favorites\' games failed')
            with self.wake:
                self.wake.wait_for(lambda: self.closed or self.poked, CHECK.total_seconds())
                if self.closed:
                    return

    def close(self):
        with self.wake:
            self.closed = True
            self.wake.notify_all()
        if self.thread:
            self.thread.join(timeout=5)
