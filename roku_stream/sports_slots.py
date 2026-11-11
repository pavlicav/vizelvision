"""Sports slots: standing appointments with a league ("Monday Night Football").

A sports slot (lineup.validate_sports, kept with the lineup in programming.json) is a rule:
a league, the days of the week, the time of day a game starts between, and optionally the
networks carrying it and the teams playing. Every CHECK (and at once after a change) the
planner looks DAYS ahead and puts each game a slot finds on the Schedule as a game show:
from its start (less the slot's lead-in) for the league's usual length, on the channel the
sports catalog suggests, then back to the schedule after the final. The show has the slot's
priority, which is what decides overlaps: a High slot cuts in at kickoff on whatever is on.

``pick: best`` airs one game a day from the slot: a favorite's first (by its place on the
favorites list), then one on a channel rather than Sunday Ticket, then the earliest.

Like the favorites planner (favorites.py), it only touches what it made:

- A game already on the Schedule (by hand, or a favorite's) is left there, but takes the
  slot's priority while it still has the one it was given, and is marked as the slot's.
- Its shows that have not started come off when their slot is gone, switched off or no
  longer finds them. Ones under way stay.
- A game it scheduled that someone removed stays off (``planned`` in programming.json).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import logging
import threading

from . import favorites as favorites_module
from .errors import ConfigError
from .lineup import DAYS, clock
from .programming import PRIORITIES, SCHEDULE
from .scheduler import parse_time, utc_now

AHEAD_DAYS = 8
CHECK = timedelta(minutes=10)
KEPT = timedelta(days=3)
# Ready-made slots. `networks` are the sports catalog's channel names (and 'Prime Video',
# 'Sunday Ticket', 'ESPN Unlimited' for games only those carry).
PRESETS = (
    {'preset': 'nfl-mnf', 'title': 'Monday Night Football', 'league': 'nfl', 'days': ['mon'], 'from': '19:00', 'to': '23:30',
     'networks': ['ESPN', 'ABC'], 'pick': 'all', 'priority': 'high', 'blurb': 'The Monday game on ESPN or ABC.'},
    {'preset': 'nfl-tnf', 'title': 'Thursday Night Football', 'league': 'nfl', 'days': ['thu'], 'from': '19:00', 'to': '23:30',
     'networks': [], 'pick': 'all', 'priority': 'high', 'blurb': 'The Thursday game, on Prime Video most weeks.'},
    {'preset': 'nfl-snf', 'title': 'Sunday Night Football', 'league': 'nfl', 'days': ['sun'], 'from': '19:00', 'to': '23:30',
     'networks': ['NBC'], 'pick': 'all', 'priority': 'high', 'blurb': 'The Sunday night game on NBC.'},
    {'preset': 'nfl-early', 'title': 'NFL Sunday · early game', 'league': 'nfl', 'days': ['sun'], 'from': '12:00', 'to': '15:30',
     'networks': [], 'pick': 'best', 'priority': 'normal', 'blurb': 'One 1 PM game: a favorite, else the local station\'s.'},
    {'preset': 'nfl-late', 'title': 'NFL Sunday · late game', 'league': 'nfl', 'days': ['sun'], 'from': '15:30', 'to': '19:00',
     'networks': [], 'pick': 'best', 'priority': 'normal', 'blurb': 'One late-afternoon game: a favorite, else the local station\'s.'},
    {'preset': 'ncaaf-noon', 'title': 'College Football · noon', 'league': 'ncaaf', 'days': ['sat'], 'from': '11:30', 'to': '14:30',
     'networks': [], 'pick': 'best', 'priority': 'normal', 'blurb': 'One Saturday noon kickoff.'},
    {'preset': 'ncaaf-afternoon', 'title': 'College Football · afternoon', 'league': 'ncaaf', 'days': ['sat'], 'from': '14:30', 'to': '18:30',
     'networks': [], 'pick': 'best', 'priority': 'normal', 'blurb': 'One Saturday 3:30 game.'},
    {'preset': 'ncaaf-prime', 'title': 'College Football · primetime', 'league': 'ncaaf', 'days': ['sat'], 'from': '18:30', 'to': '23:00',
     'networks': [], 'pick': 'best', 'priority': 'normal', 'blurb': 'One Saturday night game.'},
    {'preset': 'nba-national', 'title': 'NBA on national TV', 'league': 'nba', 'days': list(DAYS), 'from': '18:00', 'to': '23:30',
     'networks': ['NBC', 'ESPN', 'ABC'], 'pick': 'best', 'priority': 'normal', 'blurb': 'One national NBA game a night.'},
    {'preset': 'nhl-national', 'title': 'NHL on national TV', 'league': 'nhl', 'days': list(DAYS), 'from': '18:00', 'to': '23:30',
     'networks': ['TNT', 'ESPN', 'ABC', 'TBS'], 'pick': 'best', 'priority': 'normal', 'blurb': 'One national NHL game a night.'},
    {'preset': 'mlb-national', 'title': 'MLB on national TV', 'league': 'mlb', 'days': list(DAYS), 'from': '12:00', 'to': '23:30',
     'networks': [], 'pick': 'best', 'priority': 'normal', 'blurb': 'One MLB game a day on a channel you get.'},
)
# What a game's target is called when it is on no ordinary channel.
SPECIAL = {'thursday-night-football': 'Prime Video', 'sunday-ticket': 'Sunday Ticket', 'nhl': 'ESPN Unlimited',
           'nwsl': 'ESPN Unlimited', 'mlb': 'MLB.TV'}
log = logging.getLogger(__name__)


def carried_on(game, target):
    """The names a slot's `networks` can match for a game: its channels, and where its
    target is when that is no channel."""
    names = list(game.get('channels') or ())
    if target and target.get('source_id') in SPECIAL:
        names.append(SPECIAL[target['source_id']])
    return names


def matches(slot, game, start, zone, target):
    """Whether a game is a slot's: its league's, starting on one of its days between its
    times, on one of its networks, with one of its teams."""
    if game.get('league') != slot['league']:
        return False
    local = start.astimezone(zone)
    if DAYS[local.weekday()] not in slot['days']:
        return False
    minute = local.hour * 60 + local.minute
    (from_hour, from_minute), (to_hour, to_minute) = clock(slot['from']), clock(slot['to'])
    if not from_hour * 60 + from_minute <= minute <= to_hour * 60 + to_minute:
        return False
    if slot['networks']:
        wanted = {name.casefold() for name in slot['networks']}
        if not wanted & {name.casefold() for name in carried_on(game, target)}:
            return False
    if slot['teams']:
        sides = [game.get(side) or {} for side in ('away', 'home')]
        named = {str(v).casefold() for side in sides for v in (side.get('id'), side.get('abbreviation'), side.get('name'),
                                                               side.get('nickname')) if v}
        named |= {f"{slot['league']}:{side.get('id')}" for side in sides if side.get('id')}
        if not {team.casefold() for team in slot['teams']} & named:
            return False
    return True


class SportsSlots:
    def __init__(self, programming, sports, *, favorites=lambda: [], clock=utc_now):
        """favorites(): the ranked favorites list, for `best` and for a game's own rank."""
        self.programming, self.sports, self.favorites, self.clock = programming, sports, favorites, clock
        self.lock = threading.Lock()
        self.wake = threading.Condition()
        self.closed = self.poked = False
        self.thread = None
        self.last = {'checked_at': None, 'games': [], 'errors': {}}
        self._reported = set()
        programming.sports_changed = self.poke

    def _games(self, league):
        """A league's games in the next AHEAD_DAYS with a start time, and where each is on."""
        found = []
        for game in self.sports.upcoming(league, AHEAD_DAYS)['games']:
            if not game.get('start_time') or game.get('start_time_tbd'):
                continue
            state = str(game.get('state') or '').casefold()
            if game.get('finished') is True or state in favorites_module.DONE \
                    or str(game.get('status') or '').casefold() in favorites_module.DONE:
                continue
            target = game.get('suggested_target')
            if league == 'mlb' and target is None and game.get('streams'):
                target = {'source_id': 'mlb', 'channel_id': str(game['game_id']), 'date': game.get('game_date')}
            teams = [] if league == 'mlb' else [str((game.get(side) or {}).get('id') or '') for side in ('away', 'home')]
            found.append({'game': game, 'target': target, 'start': parse_time(game['start_time']),
                          'favorites': favorites_module.matches(league, game, teams)})
        return found

    @staticmethod
    def _best(candidates, order):
        """Of one day's games for a slot: a favorite's (the best-placed), then one on a
        channel rather than a game-by-game stream, then the earliest."""
        def score(candidate):
            places = [order.index(f) for f in candidate['favorites'] if f in order]
            special = (candidate['target'] or {}).get('source_id') in SPECIAL
            return (min(places) if places else len(order) + 1, candidate['target'] is None, special, candidate['start'])
        return min(candidates, key=score)

    def plan(self, now=None):
        """One pass. Returns what each slot found: [{slot, league, game_pk, title, start_time,
        status, ...}], status one of scheduled, shared (on the Schedule already, now the
        slot's too), removed, no_channel, passed (not the day's best), error."""
        now = now or self.clock()
        zone = self.programming.zone
        with self.lock:
            slots = [slot for slot in self.programming.sports_slots()]
            active = {slot['id']: slot for slot in slots if slot['enabled']}
            order = list(self.favorites() or ())
            games, errors = {}, {}
            for league in dict.fromkeys(slot['league'] for slot in active.values()):
                try:
                    games[league] = self._games(league)
                except Exception as exc:  # A feed down: what is scheduled stays, nothing new.
                    errors[league] = str(exc)
            # What each slot wants: every match, or the best of each day.
            wanted, listed = {}, []
            for slot in active.values():
                found = [c for c in games.get(slot['league'], ()) if matches(slot, c['game'], c['start'], zone, c['target'])]
                chosen = found
                if slot['pick'] == 'best':
                    by_day = {}
                    for candidate in found:
                        by_day.setdefault(candidate['start'].astimezone(zone).date(), []).append(candidate)
                    chosen = [self._best(group, order) for group in by_day.values()]
                for candidate in found:
                    key = f"{slot['league']}:{candidate['game']['game_id']}"
                    picked = any(candidate is c for c in chosen)
                    if picked and key not in wanted:
                        wanted[key] = (slot, candidate)
                    elif not picked:
                        listed.append(self._row(slot, candidate, 'passed'))
            shows = self.programming.shows()
            planned = self.programming.planned()
            # Ours that have not started come off when no slot wants them any more. A feed that
            # could not be read says nothing either way.
            for show in shows:
                if show.get('added_by') != 'slot' or parse_time(show['start']) <= now:
                    continue
                key = f"{show['game']['league']}:{show['game']['game_pk']}"
                if key in wanted or show['game']['league'] in errors:
                    continue
                self.programming.remove_show(show['id'])
                self.programming.forget_planned([key])
                planned.pop(key, None)
                log.info('Sports slots: %s is off the Schedule (no slot has it now)', show['title'])
            shows = self.programming.shows()
            by_game = {f"{s['game']['league']}:{s['game']['game_pk']}": s for s in shows if s.get('mode') == 'game'}
            # A show marked as a slot's that no slot wants now is its own again.
            for key, show in by_game.items():
                if show.get('slot') and show.get('added_by') != 'slot' and key not in wanted \
                        and show['game']['league'] not in errors:
                    back = {'slot': None, 'slot_priority': None, 'own_priority': None}
                    if show.get('priority') == show.get('slot_priority') and parse_time(show['start']) > now:
                        back['priority'] = show.get('own_priority') or 'normal'
                    self.programming.tag_show(show['id'], **back)
            for key, (slot, candidate) in sorted(wanted.items(), key=lambda item: item[1][1]['start']):
                existing = by_game.get(key)
                if existing is not None:
                    listed.append(self._row(slot, candidate, 'scheduled' if existing.get('added_by') == 'slot' else 'shared',
                                            show=self._adopt(existing, slot, now)))
                elif key in planned:
                    listed.append(self._row(slot, candidate, 'removed'))
                elif candidate['target'] is None:
                    listed.append(self._row(slot, candidate, 'no_channel'))
                else:
                    listed.append(self._row(slot, candidate, **self._schedule(slot, candidate, key, now)))
            current = {s['id'] for s in self.programming.shows()}
            self.programming.forget_planned([k for k, v in self.programming.planned().items()
                                             if v.get('show_id') not in current and parse_time(v['start']) < now - KEPT])
            listed.sort(key=lambda row: row['start_time'] or '')
            self.last = {'checked_at': now.isoformat(), 'games': listed, 'errors': errors}
            return listed

    @staticmethod
    def _row(slot, candidate, status, show=None, error=None):
        game = candidate['game']
        row = {'slot': slot['id'], 'slot_title': slot['title'], 'league': slot['league'], 'game_pk': game['game_id'],
               'game_date': game.get('game_date'), 'title': game.get('title'), 'start_time': game.get('start_time'),
               'networks': carried_on(game, candidate['target']), 'target': candidate['target'],
               'favorites': candidate['favorites'], 'status': status}
        if show:
            row.update(show_id=show['id'], start=show['start'], priority=show.get('priority'))
        if error:
            row['error'] = error
        return row

    def _adopt(self, show, slot, now):
        """Mark a show as a slot's game, and keep its priority in step with the slot's.

        The slot's own shows have its priority. A show that was there already (by hand, or a
        favorite's) keeps the higher of its own and the slot's: a High slot raises it, a Low
        one never lowers it. Once someone sets the show's priority themselves it is left alone
        (it no longer is what the slot last gave it: slot_priority)."""
        changes = {}
        if show.get('slot') != slot['id']:
            changes['slot'] = slot['id']
        current, applied = show.get('priority') or 'normal', show.get('slot_priority')
        own = show.get('own_priority')
        if applied is None:   # Here before the slot: what it had is its own.
            own = changes['own_priority'] = current
        if applied is None or current == applied:
            wanted = slot['priority'] if own is None else max(own, slot['priority'], key=PRIORITIES.index)
            if wanted != applied:
                changes['slot_priority'] = wanted
                if wanted != current and parse_time(show['start']) > now:
                    changes['priority'] = wanted
                elif wanted != current:
                    changes['slot_priority'] = current   # Under way: as it is.
        return (self.programming.tag_show(show['id'], **changes) or show) if changes else show

    def _schedule(self, slot, candidate, key, now):
        game = candidate['game']
        start = candidate['start'] - timedelta(minutes=slot['lead_minutes'])
        end = candidate['start'] + timedelta(hours=favorites_module.WINDOW.get(slot['league'], 3))
        # Under way (or about to be): it goes on now and joins in progress.
        start = max(start, now + timedelta(minutes=1))
        end = max(end, start + timedelta(minutes=30))
        value = {'mode': 'game', 'start': start.isoformat(), 'end': end.isoformat(), 'priority': slot['priority'],
                 'game': {'league': slot['league'], 'game_pk': game['game_id'], 'game_date': game.get('game_date')},
                 'target': candidate['target'], 'backup': dict(SCHEDULE)}
        try:
            show = self.programming.add_show(value, favorites=candidate['favorites'], slot=slot['id'])
        except ConfigError as exc:  # Tried again at the next pass.
            if key not in self._reported:
                self._reported.add(key)
                log.warning('Sports slots: cannot schedule %s for %s: %s', game.get('title'), slot['title'], exc)
            return {'status': 'error', 'error': str(exc)}
        self._reported.discard(key)
        self.programming.note_planned(key, show, slot['id'])
        log.info('Sports slots: %s scheduled for %s (%s)', show['title'], show['start'], slot['title'])
        return {'status': 'scheduled', 'show': show}

    def view(self):
        """The slots, the presets not yet added, and what the last pass found."""
        slots = self.programming.sports_slots()
        taken = {slot.get('preset') for slot in slots}
        return {'slots': slots, 'presets': [copy.deepcopy(p) for p in PRESETS if p['preset'] not in taken],
                **copy.deepcopy(self.last), 'days': AHEAD_DAYS, 'check_minutes': int(CHECK.total_seconds() // 60)}

    def preview(self, value, now=None):
        """The games a slot (not yet saved) would find, without scheduling anything."""
        from .lineup import validate_sports
        from .sports import LEAGUES
        now = now or self.clock()
        slot = validate_sports(value, LEAGUES)
        zone = self.programming.zone
        found = [c for c in self._games(slot['league']) if matches(slot, c['game'], c['start'], zone, c['target'])]
        chosen = found
        if slot['pick'] == 'best':
            by_day = {}
            for candidate in found:
                by_day.setdefault(candidate['start'].astimezone(zone).date(), []).append(candidate)
            order = list(self.favorites() or ())
            chosen = [self._best(group, order) for group in by_day.values()]
        rows = [self._row(slot, c, 'no_channel' if c['target'] is None else 'would' if any(c is x for x in chosen) else 'passed')
                for c in found]
        return sorted(rows, key=lambda row: row['start_time'] or '')

    # Worker ------------------------------------------------------------------
    def poke(self):
        with self.wake:
            self.poked = True
            self.wake.notify_all()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='sports-slots', daemon=True)
            self.thread.start()

    def _run(self):
        while True:
            with self.wake:
                self.poked = False
            try:
                self.plan()
            except Exception:  # Keep planning alive; the next pass retries.
                log.exception('Planning the sports slots failed')
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
