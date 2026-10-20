"""Election night on the crawl: when polls close, then results as they come in.

An election is a JSON definition in roku_stream/elections/ (alberta-2026.json; a US
midterm night is another file, docs/election.md): its name, when it shows, when polls close
(one closing or several, each with where), its contests (questions or races, each with its
options) and its sources, official first. ElectionFeed is the crawl's "election" segment
(crawl_desk.py), whose new items pop up at once, marked NEW:

- before polls close: when they close and how long until then. At each warning (60, 30
  and 10 minutes before) the item's id changes, so it is news again;
- at the close: polls are closed (news), until results come in;
- then one item per contest with results: each option's share and votes, and how many of
  its reporting units are in, from the first source that has it (official first). A large
  batch of results starts a new edition of the contest's item, which is news again: the
  first results, everything in, or since the last poll at least batch.votes more votes or
  batch.reporting more of the units. At most one edition every batch.minutes per contest;
  a batch inside that waits for the next.

Results are fetched only from five minutes before the first close. Editions are saved in
election-state.json beside crawl.json, so a web restart neither repeats one nor misses a
batch that came in meanwhile.
"""
from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
import logging
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from urllib.request import Request
from zoneinfo import ZoneInfo

from . import crawl
from .crawl_feeds import EASTERN, Feed, _fit

DEFINITIONS = Path(__file__).with_name('elections')
YES_NO = [{'key': 'yes', 'label': 'Yes', 'match': ['yes']}, {'key': 'no', 'label': 'No', 'match': ['no']}]
BATCH = {'votes': 20000, 'reporting': 0.02, 'minutes': 10}
CLOSED_FOR = 1800      # a closing's "polls are closed" item stays this long after results come in
STALE_RESULTS = 1800   # results not read again for this long are dropped (a dead source must not freeze a count)
FETCH_BEFORE = 300     # results are fetched from this long before the first close
NUMBER = re.compile(r'\d[\d,]*')
OF = re.compile(r'(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*)')
UNITS_IN_TEXT = re.compile(r'(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*)\s+(voting (?:locations|places|stations)|polls|precincts)', re.I)
UNIT_WORDS = ('voting location', 'voting place', 'voting station', 'polls', 'precinct', 'stations')


def _when(value):
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def _number(text):
    found = NUMBER.search(str(text or ''))
    return int(found.group().replace(',', '')) if found else None


def _norm(text):
    return ' '.join(str(text or '').casefold().split())


def load(path):
    """An election definition, checked, with times as epochs and every contest's options."""
    value = json.loads(Path(path).read_text())
    for key in ('id', 'name', 'tag', 'show_from', 'show_until', 'polls', 'contests', 'sources'):
        if key not in value:
            raise ValueError(f'{path}: an election needs {key}')
    if not re.fullmatch(r'[a-z0-9_-]{1,24}', value['id']):
        raise ValueError(f'{path}: id is up to 24 lowercase letters, digits, - and _')
    election = copy.deepcopy(value)
    election['show_from'], election['show_until'] = _when(value['show_from']), _when(value['show_until'])
    election['polls'] = sorted(({**poll, 'close': _when(poll['close'])} for poll in value['polls']),
                               key=lambda poll: poll['close'])
    if not election['polls']:
        raise ValueError(f'{path}: polls lists at least one closing')
    election['warnings'] = sorted({int(w) for w in value.get('warnings', [60, 30, 10]) if int(w) > 0}, reverse=True)
    election['batch'] = {**BATCH, **(value.get('batch') or {})}
    election.setdefault('zone', 'America/New_York')
    ZoneInfo(election['zone'])
    seen = set()
    for contest in election['contests']:
        if not re.fullmatch(r'[a-z0-9_-]{1,24}', str(contest.get('id'))) or contest['id'] in seen:
            raise ValueError(f'{path}: every contest needs its own short id')
        seen.add(contest['id'])
        contest.setdefault('tag', contest['id'].upper())
        contest.setdefault('name', contest['tag'])
        contest.setdefault('keys', {})
        contest['options'] = contest.get('options') or copy.deepcopy(YES_NO)
    return election


def definitions(directory=DEFINITIONS):
    elections = []
    for path in sorted(Path(directory).glob('*.json')):
        try:
            elections.append(load(path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logging.getLogger(__name__).warning('Election %s not loaded: %s', path.name, exc)
    return elections


# --------------------------------------------------------------------- reading results

class _Tables(HTMLParser):
    """Every table's rows, each a list of cell texts (a cell spanning n columns is n cells),
    from HTML that leaves its TR, TD and TH tags open, as Elections Alberta's pages do."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.open = [], []

    def _table(self):
        return self.tables[self.open[-1]] if self.open else None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            self.tables.append({'id': attrs.get('id') or '', 'rows': []})
            self.open.append(len(self.tables) - 1)
            return
        table = self._table()
        if table is None:
            return
        if tag == 'tr':
            table['rows'].append({'class': attrs.get('class') or '', 'cells': []})
        elif tag in ('td', 'th'):
            if not table['rows']:
                table['rows'].append({'class': '', 'cells': []})
            try:
                span = max(1, min(20, int(attrs.get('colspan') or 1)))
            except ValueError:
                span = 1
            table['rows'][-1]['cells'].append({'text': '', 'th': tag == 'th', 'span': span})
        elif tag == 'br':
            self.handle_data(' ')

    def handle_endtag(self, tag):
        if tag == 'table' and self.open:
            self.open.pop()

    def handle_data(self, data):
        table = self._table()
        if table and table['rows'] and table['rows'][-1]['cells']:
            table['rows'][-1]['cells'][-1]['text'] += data


def tables(page):
    """[{id, header: [column names], rows: [{class, cells}]}] of every table in a page."""
    parser = _Tables()
    parser.feed(page)
    found = []
    for table in parser.tables:
        rows = [row for row in table['rows'] if row['cells']]
        header_rows = []
        while rows and all(cell['th'] for cell in rows[0]['cells']):
            header_rows.append(rows.pop(0))
        expand = lambda row: [' '.join(cell['text'].split()) for cell in row['cells'] for _ in range(cell['span'])]
        width = max([len(expand(row)) for row in header_rows + rows] or [0])
        header = [''] * width
        for row in header_rows:
            for index, text in enumerate(expand(row)):
                header[index] = (header[index] + ' ' + text).strip()
        found.append({'id': table['id'], 'header': [_norm(name) for name in header],
                      'rows': [{'class': row['class'], 'cells': expand(row)} for row in rows]})
    return found


def _column(header, words, *, without=(), whole=True):
    """The first column whose name has one of these words (whole words, or with whole=False
    their beginnings: "voting location" finds "voting locations")."""
    end = r'\b' if whole else ''
    for index, name in enumerate(header):
        if any(re.search(r'\b' + re.escape(word) + end, name) for word in words) and not any(w in name for w in without):
            return index
    return None


def table_tally(table, contest):
    """A contest's totals from one results table: {votes, reported, units, unit}, or None
    when the table is not one (it lacks a column for each option)."""
    header = table['header']
    columns = {}
    for option in contest['options']:
        index = _column(header, [_norm(word) for word in option.get('match') or [option['label']]])
        if index is None or index in columns.values():
            return None
        columns[option['key']] = index
    rows = [row for row in table['rows'] if len(row['cells']) > max(columns.values())]
    if not rows:
        return None
    total = next((row for row in rows if 'total' in row['class'].casefold() or 'total' in _norm(row['cells'][0])), None)
    parts = [row for row in rows if row is not total]
    votes = lambda row: {key: _number(row['cells'][index]) or 0 for key, index in columns.items()}
    if total is not None:
        counted = votes(total)
    else:
        counted = {key: sum(votes(row)[key] for row in parts) for key in columns}
    reported = units = unit = None
    report_col = _column(header, ['report'], whole=False)
    units_col = _column(header, list(UNIT_WORDS), without=('report',), whole=False)
    for index in (report_col, units_col):
        if index is None or total is None:
            continue
        cell = total['cells'][index]
        both = OF.search(cell)
        if both and reported is None:
            reported, units = int(both.group(1).replace(',', '')), int(both.group(2).replace(',', ''))
        elif index == report_col:
            reported = _number(cell)
        elif units is None:
            units = _number(cell)
        unit = unit or next((word + ('' if word.endswith('s') else 's') for word in UNIT_WORDS if word in header[index]), None)
    if reported is None and parts:
        # Nothing says how many voting places are in: count the divisions with votes. Every
        # division can have some long before the count is done, so this is never "all in".
        reported = sum(1 for row in parts if sum(votes(row).values()) > 0)
        return {'votes': counted, 'reported': reported, 'units': len(parts), 'unit': 'electoral divisions', 'areas': True}
    return {'votes': counted, 'reported': reported, 'units': units, 'unit': unit}


def page_tally(page, contest):
    """A contest's totals from a results page (the main table first), or None."""
    found = tables(page)
    for table in sorted(found, key=lambda t: t['id'] != 'dataTbl'):
        tally = table_tally(table, contest)
        if tally:
            words = UNITS_IN_TEXT.search(' '.join(re.sub(r'<[^>]+>', ' ', page).split()))
            if words and tally.get('areas'):
                tally.update(reported=int(words.group(1).replace(',', '')), units=int(words.group(2).replace(',', '')),
                             unit=words.group(3).casefold(), areas=False)
            return tally
    return None


def csv_tallies(text, contests, source):
    """Every contest's totals from a results CSV with a row per area (its province-wide row,
    else the sum of its rows): {contest id: tally}."""
    rows = list(csv.DictReader(io.StringIO(text)))
    columns = source.get('options') or []
    found = {}
    for contest in contests:
        key = _norm(contest['keys'].get('csv', contest['id'])).lstrip('q')
        mine = [row for row in rows if _norm(row.get(source.get('contest', 'contest'))).lstrip('q') == key]
        if not mine or len(columns) < len(contest['options']):
            continue
        area = source.get('area')
        totals = [row for row in mine if area and _norm(row.get(area)) in source.get('total_areas', [])]
        if totals:
            mine = totals[:1]
        elif area:  # Areas of one kind only (electoral divisions, say), not a mix of levels.
            kinds = [_norm(row.get(area)) for row in mine]
            kind = max(set(kinds), key=kinds.count)
            mine = [row for row in mine if _norm(row.get(area)) == kind]
        total = lambda column: sum(_number(row.get(column)) or 0 for row in mine) if column else None
        found[contest['id']] = {
            'votes': {option['key']: total(column) for option, column in zip(contest['options'], columns)},
            'reported': total(source.get('reported')), 'units': total(source.get('units')),
            'unit': source.get('unit')}
    return found


# --------------------------------------------------------------------- the feed

def _span(seconds):
    minutes = max(0, round(seconds / 60))
    if seconds < 60:
        return 'under a minute'
    hours, minutes = divmod(minutes, 60)
    parts = ([f'{hours} hour' + ('s' if hours != 1 else '')] if hours else []) + \
            ([f'{minutes} minute' + ('s' if minutes != 1 else '')] if minutes else [])
    return ' '.join(parts)


def _clock(epoch, zone):
    return datetime.fromtimestamp(epoch, zone).strftime('%-I:%M %p').replace(':00 ', ' ')


class ElectionFeed(Feed):
    """The crawl's election special report: every election whose show window is open now."""
    INTERVAL = 60
    LIMIT = 40

    def __init__(self, directory=DEFINITIONS, state_path=None, **kwargs):
        super().__init__(**kwargs)
        self.directory, self.state_path = Path(directory), Path(state_path) if state_path else None
        self.elections, self.loaded_at = [], None
        self.note = None      # what the last source read says beyond its results ("not published yet")
        self.results = {}     # election id: {contest id: tally}
        self.sources = {}     # election id: {source name: {ok, at, error, contests}}
        self.state = self._load()
        self.state_lock = threading.Lock()

    # ------------------------------------------------------------------ definitions and state

    def _load(self):
        if self.state_path is None:
            return {}
        try:
            value = json.loads(self.state_path.read_text())
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning('Election state unreadable, starting afresh: %s', exc)
            return {}

    def _save(self):
        if self.state_path is not None:
            try:
                crawl._atomic_write(self.state_path, self.state)
            except OSError as exc:
                logging.getLogger(__name__).warning('Election state not saved: %s', exc)

    def active(self, now=None):
        now = self.clock() if now is None else now
        if self.loaded_at is None or now - self.loaded_at > 300:  # A new definition shows within minutes.
            self.elections, self.loaded_at = definitions(self.directory), now
        return [e for e in self.elections if e['show_from'] <= now < e['show_until']]

    # ------------------------------------------------------------------ fetching

    def _page(self, url):
        """A page, or None when the site sends us elsewhere (results not published yet)."""
        with self.opener(Request(url, headers={'User-Agent': 'Mozilla/5.0 (VizelVision local station crawl)'}),
                         timeout=15) as response:
            final = response.geturl() if hasattr(response, 'geturl') else url
            body = response.read(8 * 1024 * 1024).decode('utf-8', 'replace')
        if urlsplit(final).path.casefold() != urlsplit(url).path.casefold():
            return None
        return body

    def _read(self, source, contests):
        """{contest id: tally} from one source, for these contests."""
        kind = source.get('kind')
        if kind == 'elections_alberta':
            found, published, failed = {}, 0, []
            for contest in contests:  # A page per question: one failing leaves the others.
                key = contest['keys'].get('elections_alberta')
                if not key:
                    continue
                try:
                    page = self._page(source['url'].format(key=key))
                except Exception as exc:
                    failed.append(exc)
                    continue
                published += page is not None
                tally = page_tally(page, contest) if page else None
                if tally:
                    found[contest['id']] = tally
            if failed and not published and not found and len(failed) == len(contests):
                raise failed[0]
            notes = ([f'{len(failed)} of its pages unreachable'] if failed else []) + \
                ([] if published else ['results pages not published yet'])
            self.note = '; '.join(notes) or None
            return found
        if kind == 'csv':
            return csv_tallies(self._get(source['url']).decode('utf-8-sig', 'replace'), contests, source)
        raise ValueError(f'Unknown results source kind {kind!r}')

    def fetch(self):
        now = self.clock()
        for election in self.active(now):
            if now < election['polls'][0]['close'] - FETCH_BEFORE:
                continue  # No results before polls close.
            results, health = {}, self.sources.setdefault(election['id'], {})
            for source in election['sources']:
                missing = [c for c in election['contests'] if c['id'] not in results]
                if not missing:
                    break
                self.note = None
                try:
                    found = self._read(source, missing)
                except Exception as exc:
                    health[source['name']] = {'ok': False, 'at': now, 'error': _fit(str(exc), 200), 'contests': 0}
                    continue
                counted = {cid: t for cid, t in found.items() if sum(v or 0 for v in t['votes'].values()) > 0}
                for cid, tally in counted.items():
                    results[cid] = {**tally, 'source': source['name'], 'official': bool(source.get('official')),
                                    'unit': tally.get('unit') or source.get('unit') or 'voting places', 'at': now}
                health[source['name']] = {'ok': True, 'at': now, 'error': None, 'contests': len(counted), 'note': self.note}
            kept = {cid: t for cid, t in self.results.get(election['id'], {}).items() if now - t['at'] < STALE_RESULTS}
            self.results[election['id']] = {**kept, **results}
            self._batches(election, results, now)
        return []

    def _batches(self, election, results, now):
        """A new edition of each contest that took a large batch (see the module's docstring)."""
        batch, changed = election['batch'], False
        with self.state_lock:
            mine = self.state.setdefault(election['id'], {})
            for contest in election['contests']:
                tally = results.get(contest['id'])
                if not tally:
                    continue
                st = mine.setdefault(contest['id'], {'edition': 0, 'votes': 0, 'share': None, 'at': 0,
                                                     'pending': False, 'complete': False})
                total = sum(v or 0 for v in tally['votes'].values())
                share = tally['reported'] / tally['units'] if tally.get('units') and tally.get('reported') is not None else None
                complete = share is not None and share >= 1 and not tally.get('areas')
                first = st['edition'] == 0
                large = (first or total - st['votes'] >= batch['votes']
                         or (share is not None and st['share'] is not None and share - st['share'] >= batch['reporting'] - 1e-9)
                         or (complete and not st['complete']))
                if (total, share) != (st['votes'], st['share']):
                    st['votes'], st['share'], changed = total, share, True
                if large or st['pending']:
                    if first or (complete and not st['complete']) or now - st['at'] >= batch['minutes'] * 60:
                        st.update(edition=st['edition'] + 1, at=now, pending=False, complete=complete)
                    else:
                        st['pending'] = True
                    changed = True
            if changed:
                self._save()

    # ------------------------------------------------------------------ items

    def items(self):
        now = self.clock()
        items = []
        for election in self.active(now):
            items += self._polls(election, now)
            items += self._results(election, now)
        return items[:self.LIMIT]

    def _polls(self, election, now):
        """Before each closing: when, and how long until; after it: polls are closed."""
        zone = ZoneInfo(election['zone'])
        local = election['zone'] != 'America/New_York'
        counted = bool(self.results.get(election['id']))
        items = []
        for index, poll in enumerate(election['polls']):
            close, where = poll['close'], poll.get('where') or ''
            at = _clock(close, EASTERN) + ' Eastern' + (f", {_clock(close, zone)} {election.get('zone_name') or ''}".rstrip()
                                                        if local else '')
            ident = f"election:{election['id']}:polls{index or ''}"
            if now < close:
                due = [w for w in election['warnings'] if now >= close - w * 60]
                if due:
                    stage = min(due)
                    heading = f'POLLS CLOSE IN {_span(stage * 60).upper()}'
                    ident += f':{stage}'
                else:
                    heading = 'POLLS CLOSE AT ' + _clock(close, EASTERN).upper() + ' ET'
                text = f'Voting ends {where} at {at}: in {_span(close - now)}.'
                if index == 0 and election.get('preview'):
                    text += ' ' + election['preview']
                items.append({'tag': election['tag'], 'heading': heading, 'text': _fit(text, 480), 'id': ident,
                              'expires': datetime.fromtimestamp(close, timezone.utc).isoformat()})
            elif now < close + CLOSED_FOR or not counted:
                text = f'Voting has ended {where}.' + (' ' + election['closed'] if election.get('closed') and index == len(election['polls']) - 1 else '')
                items.append({'tag': election['tag'], 'heading': 'POLLS ARE CLOSED', 'text': _fit(text, 480),
                              'id': ident + ':closed', 'issued': datetime.fromtimestamp(close, timezone.utc).isoformat()})
        return items

    def _results(self, election, now):
        results = self.results.get(election['id'], {})
        state = self.state.get(election['id'], {})
        items = []
        for contest in election['contests']:
            tally = results.get(contest['id'])
            if not tally or now - tally['at'] >= STALE_RESULTS:
                continue
            total = sum(v or 0 for v in tally['votes'].values())
            options = [(option, tally['votes'].get(option['key']) or 0) for option in contest['options']]
            if (contest.get('sort') or election.get('sort')) == 'votes':
                options.sort(key=lambda pair: -pair[1])
            shares = ', '.join(f"{option['label']} {votes / total * 100:.1f}% ({votes:,})" for option, votes in options)
            reported, units, unit = tally.get('reported'), tally.get('units'), tally.get('unit') or 'voting places'
            if tally.get('areas') and units:
                reporting = f'Results from {reported:,} of {units:,} {unit}.'
            elif units and reported is not None and reported >= units:
                reporting = f'All {units:,} {unit} reporting.'
            elif units and reported is not None:
                reporting = f'{reported:,} of {units:,} {unit} reporting ({reported / units * 100:.0f}%).'
            elif reported:
                reporting = f'{reported:,} {unit} reporting.'
            else:
                reporting = f'{total:,} votes counted.'
            by = tally['source'] if tally['official'] else 'via ' + tally['source']
            text = f'{shares}. {reporting} Unofficial results, {by}.'
            edition = (state.get(contest['id']) or {}).get('edition') or 1
            items.append({'tag': _fit(f"{election['tag']} {contest['tag']}", 20), 'heading': contest['name'].upper()[:80],
                          'text': _fit(text, 480), 'id': f"election:{election['id']}:{contest['id']}:e{edition}",
                          'issued': datetime.fromtimestamp(tally['at'], timezone.utc).isoformat()})
        return items

    def status(self):
        now = self.clock()
        out = {**super().status(), 'elections': []}
        for election in self.active(now):
            out['elections'].append({
                'id': election['id'], 'name': election['name'],
                'closes': [{'where': p.get('where'), 'at': p['close']} for p in election['polls']],
                'sources': [{'name': s['name'], 'official': bool(s.get('official')),
                             **self.sources.get(election['id'], {}).get(s['name'], {})} for s in election['sources']],
                'contests': [{'id': c['id'], 'tag': c['tag'], 'name': c['name'],
                              'edition': (self.state.get(election['id'], {}).get(c['id']) or {}).get('edition', 0),
                              'tally': self.results.get(election['id'], {}).get(c['id'])}
                             for c in election['contests']]})
        return out
