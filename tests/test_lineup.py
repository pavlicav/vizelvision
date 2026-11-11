"""The lineup's slots (lineup.py, programming.py) and the listings they follow (guide_index.py)."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from roku_stream import lineup, programming as programming_module
from roku_stream.errors import ConfigError
from roku_stream.guide_index import GuideIndex, normal
from roku_stream.programming import OFF_AIR, Programming, empty
from roku_stream.source_queue import SourceQueue

ZONE = ZoneInfo('America/New_York')
NBC = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
ABC = {'source_id': 'youtube-tv', 'channel_id': 'ABC'}
WJLA = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}
# Wednesday 2026-09-23, local noon.
NOON = datetime(2026, 9, 23, 12, tzinfo=ZONE).astimezone(timezone.utc)


def local(hour, minute=0, day=23):
    return datetime(2026, 9, day, hour, minute, tzinfo=ZONE).astimezone(timezone.utc)


def slot(title, start, minutes, what, days=('wed',), **more):
    return {'title': title, 'days': list(days), 'start': start, 'minutes': minutes, 'what': what, **more}


def channel(target):
    return {'kind': 'channel', 'target': target}


def guide_rows(*airings):
    """TV Thing's guide: airings are (row key, title, start, minutes, extra)."""
    rows = {'7.1': {'kind': 'digital', 'id': 'wjla_7_1', 'number': '7.1', 'name': 'WJLA', 'events': []},
            'youtube-tv/ABC': {'kind': 'roku', 'source_id': 'youtube-tv', 'channel_id': 'ABC', 'name': 'ABC', 'events': []},
            'youtube-tv/NBC': {'kind': 'roku', 'source_id': 'youtube-tv', 'channel_id': 'NBC', 'name': 'NBC', 'events': []},
            'games/71': {'kind': 'games', 'name': 'Live Sports', 'events': [{'title': 'Jeopardy!', 'start': 0, 'duration': 9e9}]}}
    for key, title, start, minutes, *extra in airings:
        rows[key]['events'].append({'title': title, 'start': start.timestamp(), 'duration': minutes * 60, **(extra[0] if extra else {})})
    guide_rows.made += 1   # A newer guide each time, as TV Thing's generated_at says.
    return {'generated_at': guide_rows.made, 'channels': rows}


guide_rows.made = 0


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FromGridTests(unittest.TestCase):
    def grid(self, **painted):
        value = {day: [None] * 48 for day in lineup.DAYS}
        for day, spans in painted.items():
            for start, end, block in spans:
                value[day][start:end] = [block] * (end - start)
        return value

    def test_days_sharing_a_run_share_a_slot_and_a_run_through_midnight_is_one_airing(self):
        blocks = [{'id': 'j', 'name': 'Jeopardy', 'color': '#3a6f8f', 'target': WJLA},
                  {'id': 'n', 'name': 'News', 'color': '#7a4f9a', 'target': NBC}]
        slots = lineup.from_grid(blocks, self.grid(mon=[(39, 40, 'j')], tue=[(39, 40, 'j'), (36, 37, 'n')],
                                                   sat=[(46, 48, 'n')], sun=[(0, 2, 'n')]))
        found = {(s['title'], s['start'], s['minutes']): s['days'] for s in slots}
        self.assertEqual(found, {('Jeopardy', '19:30', 30): ['mon', 'tue'], ('News', '18:00', 30): ['tue'],
                                 ('News', '23:00', 120): ['sat']})
        self.assertTrue(all(s['what'] == {'kind': 'channel', 'target': b['target']}
                            for s in slots for b in blocks if b['name'] == s['title']))

    def test_the_old_state_file_becomes_slots_and_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'programming.json'
            old = {**empty(), 'enabled': True, 'blocks': [{'id': 'j', 'name': 'Jeopardy', 'color': '#3a6f8f', 'target': WJLA}],
                   'shows': [{'id': 's', 'mode': 'program', 'title': 'Special', 'target': NBC,
                              'start': NOON.isoformat(), 'end': (NOON + timedelta(hours=1)).isoformat()}]}
            old['grid']['wed'][39] = 'j'
            path.write_text(json.dumps(old))
            queue = SourceQueue(Path(folder) / 'queue.json', lambda item: {}, lambda *_: {}, start_worker=False)
            self.addCleanup(queue.close)
            programming = Programming(path, queue, zone=ZONE, start_worker=False)
            self.assertEqual([(s['title'], s['days'], s['start']) for s in programming.slots()], [('Jeopardy', ['wed'], '19:30')])
            self.assertEqual([s['id'] for s in programming.shows()], ['s'])
            self.assertTrue(programming.enabled)
            self.assertEqual(json.loads(path.read_text())['version'], 2)
            self.assertEqual(json.loads((Path(folder) / 'programming.v1.json').read_text())['grid']['wed'][39], 'j')
            # And it loads again as it is.
            again = Programming(path, queue, zone=ZONE, start_worker=False)
            self.assertEqual(again.slots(), programming.slots())


class SlotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', lambda item: {}, lambda *_: {'finished': True},
                                 poll_seconds=.01, start_worker=False)
        self.addCleanup(self.queue.close)
        self.programming = Programming(Path(self.tmp.name) / 'programming.json', self.queue, zone=ZONE, start_worker=False)
        self.clock = Clock()
        self.listed = guide_rows()
        self.programming.guide = GuideIndex(lambda: self.listed, Path(self.tmp.name) / 'atlas.json', zone=ZONE,
                                            clock=self.clock, wall=lambda: NOON.timestamp())

    def relist(self, *airings):
        self.listed = guide_rows(*airings)
        self.clock.now += 1000  # Past the index's refresh.

    def titles(self, start, end):
        return [(s['title'], s['start'].astimezone(ZONE).strftime('%H:%M'), s['end'].astimezone(ZONE).strftime('%H:%M'),
                 s['target']['channel_id']) for s in self.programming.timeline(start, end)]

    def test_a_slot_starts_to_the_minute_and_the_rest_is_off_air(self):
        added = self.programming.add_slot(slot('Jeopardy', '19:35', 25, channel(WJLA), days=['wed', 'thu']))
        self.assertEqual(added['priority'], 'normal')
        self.assertEqual(self.titles(local(19), local(20, 30)),
                         [('OFF AIR', '19:00', '19:35', 'off-air'), ('Jeopardy', '19:35', '20:00', 'wjla_7_1'),
                          ('OFF AIR', '20:00', '20:30', 'off-air')])
        self.assertEqual(self.programming.colors(), {added['id']: added['color']})
        # Thursday too, and not Friday.
        self.assertEqual([t[0] for t in self.titles(local(19, 40, day=24), local(19, 41, day=24))], ['Jeopardy'])
        self.assertEqual([t[0] for t in self.titles(local(19, 40, day=25), local(19, 41, day=25))], ['OFF AIR'])

    def test_of_two_slots_the_later_start_has_the_time_and_the_other_resumes(self):
        self.programming.add_slot(slot('News', '18:00', 120, channel(NBC)))
        self.programming.add_slot(slot('Jeopardy', '19:00', 30, channel(WJLA)))
        self.assertEqual([t[:3] for t in self.titles(local(18), local(20))],
                         [('News', '18:00', '19:00'), ('Jeopardy', '19:00', '19:30'), ('News', '19:30', '20:00')])
        # A higher priority has the time whenever it starts.
        news = next(s for s in self.programming.slots() if s['title'] == 'News')
        self.programming.update_slot(news['id'], {'priority': 'high'})
        self.assertEqual([t[:3] for t in self.titles(local(18), local(20))], [('News', '18:00', '20:00')])

    def test_two_slots_on_one_channel_are_one_run_and_one_segment_when_named_alike(self):
        self.programming.add_slot(slot('News', '18:00', 30, channel(NBC)))
        self.programming.add_slot(slot('News', '18:30', 30, channel(NBC)))
        self.programming.add_slot(slot('Nightly', '19:00', 30, channel(NBC)))
        self.assertEqual([t[:3] for t in self.titles(local(18), local(19, 30))],
                         [('News', '18:00', '19:00'), ('Nightly', '19:00', '19:30')])
        with self.programming.lock:
            self.programming.data['enabled'] = True
        changes = self.programming.transitions(local(17), local(20))
        # NBC stays on from six to half past seven: one entry, then OFF AIR.
        self.assertEqual([(c['title'], c['run_at'][11:16]) for c in changes], [('News', '22:00'), ('OFF AIR', '23:30')])

    def test_a_programme_slot_follows_the_listings_to_its_channel_and_times(self):
        self.relist(('youtube-tv/ABC', 'Jeopardy!', local(19, 30), 30), ('youtube-tv/NBC', 'News', local(19, 30), 30))
        self.programming.add_slot(slot('Jeopardy', '19:30', 30, {'kind': 'program', 'title': 'jeopardy', 'target': WJLA}))
        # Listed on YouTube TV's ABC only: there it is, though its usual channel is WJLA.
        self.assertEqual(self.titles(local(19, 30), local(20)), [('Jeopardy', '19:30', '20:00', 'ABC')])
        # On the antenna too: its usual channel. And it starts at 19:32 tonight, for 28 minutes.
        self.relist(('youtube-tv/ABC', 'Jeopardy!', local(19, 30), 30), ('7.1', 'Jeopardy!', local(19, 32), 28, {'new': True}))
        self.assertEqual(self.titles(local(19), local(20, 15)),
                         [('OFF AIR', '19:00', '19:32', 'off-air'), ('Jeopardy', '19:32', '20:00', 'wjla_7_1'),
                          ('OFF AIR', '20:00', '20:15', 'off-air')])
        [airing] = self.programming.airings(local(19), local(20))
        self.assertEqual((airing['by'], airing['label'], airing['listed']['new']), ('listings', '7.1 WJLA', True))
        # Not listed (the listings reach it): its usual channel anyway, and it says so.
        self.relist(('7.1', 'Wheel of Fortune', local(19), 120))
        self.assertEqual(self.titles(local(19, 30), local(20)), [('Jeopardy', '19:30', '20:00', 'wjla_7_1')])
        [airing] = self.programming.airings(local(19), local(20))
        self.assertEqual((airing['by'], airing['why']), ('usual', 'Not in the listings at this time'))

    def test_without_a_usual_channel_an_unlisted_airing_is_skipped(self):
        self.relist(('7.1', 'Wheel of Fortune', local(19), 60))
        self.programming.add_slot(slot('Jeopardy', '19:30', 30, {'kind': 'program', 'title': 'Jeopardy!'}))
        self.assertEqual([t[0] for t in self.titles(local(19, 30), local(20))], ['OFF AIR'])
        [airing] = self.programming.airings(local(19), local(20))
        self.assertEqual((airing['by'], airing['target']), ('unlisted', None))
        # A week on, the listings do not reach.
        [later] = self.programming.airings(local(19, day=30), local(20, day=30))
        self.assertEqual(later['why'], 'The listings do not reach this far yet')

    def test_a_channel_the_station_cannot_tune_is_passed_over(self):
        from roku_stream.errors import ChannelNotFoundError

        def normalize(target):
            if target.get('channel_id') == 'ABC':
                raise ChannelNotFoundError('Not a configured channel')
            return target
        self.programming.normalize = normalize
        self.relist(('youtube-tv/ABC', 'Jeopardy!', local(19, 30), 30), ('7.1', 'Jeopardy!', local(19, 30), 30))
        self.programming.add_slot(slot('Jeopardy', '19:30', 30, {'kind': 'program', 'title': 'Jeopardy!', 'target': NBC}))
        self.assertEqual(self.titles(local(19, 30), local(20)), [('Jeopardy', '19:30', '20:00', 'wjla_7_1')])
        with self.assertRaises(ChannelNotFoundError):   # Nor can it be a slot's usual channel.
            self.programming.add_slot(slot('Jeopardy', '19:30', 30, {'kind': 'program', 'title': 'Jeopardy!', 'target': ABC}))

    def test_an_airing_about_to_start_keeps_its_source_whatever_the_listings_do(self):
        self.relist(('7.1', 'Jeopardy!', local(19, 30), 30))
        self.programming.add_slot(slot('Jeopardy', '19:30', 30, {'kind': 'program', 'title': 'Jeopardy!'}))
        with mock.patch.object(programming_module, 'utc_now', lambda: local(19, 20)):
            self.assertEqual(self.titles(local(19, 30), local(20)), [('Jeopardy', '19:30', '20:00', 'wjla_7_1')])
            self.relist(('youtube-tv/ABC', 'Jeopardy!', local(19, 30), 30))
            self.assertEqual(self.titles(local(19, 30), local(20)), [('Jeopardy', '19:30', '20:00', 'wjla_7_1')])
        # Saved: a restart mid-programme finds the same source.
        again = Programming(self.programming.path, self.queue, zone=ZONE, start_worker=False)
        again.guide = self.programming.guide
        self.assertEqual([s['target']['channel_id'] for s in again.timeline(local(19, 30), local(20))], ['wjla_7_1'])
        # Editing the slot settles it afresh.
        [saved] = self.programming.slots()
        self.programming.update_slot(saved['id'], {'what': {'kind': 'program', 'title': 'Jeopardy!', 'target': NBC}})
        with mock.patch.object(programming_module, 'utc_now', lambda: local(19, 20)):
            self.assertEqual(self.titles(local(19, 30), local(20)), [('Jeopardy', '19:30', '20:00', 'ABC')])

    def test_a_library_slot_airs_the_next_file_each_time_and_ends_with_it(self):
        files = [{'id': f'shows/Made/S01E{n:02d}.mkv', 'root': 'shows', 'path': f'Made/S01E{n:02d}.mkv', 'title': f'E{n}',
                  'duration': 21 * 60, 'playable': True, 'aired': None} for n in (10, 2, 1)]
        files.append({'id': 'shows/Other/x.mkv', 'root': 'shows', 'path': 'Other/x.mkv', 'title': 'x', 'duration': 60, 'playable': True})
        files.append({'id': 'shows/Made/S01E00.mkv', 'root': 'shows', 'path': 'Made/S01E00.mkv', 'title': 'bad', 'playable': False})
        self.programming.library = lambda: {'items': files, 'roots': [{'id': 'shows', 'name': 'Shows'}]}
        what = {'kind': 'library', 'root': 'shows', 'path': 'Made/', 'order': 'next'}
        made = self.programming.add_slot(slot("How It's Made", '20:00', 30, what, days=list(lineup.DAYS)))
        with mock.patch.object(programming_module, 'utc_now', lambda: local(12)):
            week = self.programming.airings(local(0), local(0, day=27))
            self.assertEqual([a['label'] for a in week], ['E1', 'E2', 'E10', 'E1'])
            # The file ends at 20:21; the rest of the half hour is OFF AIR.
            self.assertEqual(self.titles(local(20), local(20, 30)),
                             [("How It's Made", '20:00', '20:21', 'shows/Made/S01E01.mkv'), ('OFF AIR', '20:21', '20:30', 'off-air')])
        # Once tonight's is settled, tomorrow's is the one after it.
        with mock.patch.object(programming_module, 'utc_now', lambda: local(19, 50)):
            self.programming.timeline(local(20), local(20, 30))
        with mock.patch.object(programming_module, 'utc_now', lambda: local(21)):
            tomorrow = self.programming.airings(local(0, day=24), local(0, day=25))
            self.assertEqual([a['label'] for a in tomorrow], ['E2'])
        folders = self.programming.library_folders()
        self.assertEqual([(f['label'], f['files'], f['minutes'], f['order']) for f in folders if not f['whole']],
                         [('Made', 3, 21, 'next'), ('Other', 1, 1, 'next')])
        self.assertEqual(made['what'], what)

    def test_skipping_one_airing_and_switching_a_slot_off(self):
        made = self.programming.add_slot(slot('News', '18:00', 30, channel(NBC), days=list(lineup.DAYS)))
        with mock.patch.object(programming_module, 'datetime', wraps=datetime) as fake:
            fake.now.return_value = datetime(2026, 9, 23, 12, tzinfo=ZONE)
            self.programming.skip_slot(made['id'], '2026-09-23')
        self.assertEqual([t[0] for t in self.titles(local(18), local(18, 30))], ['OFF AIR'])
        self.assertEqual([t[0] for t in self.titles(local(18, day=24), local(18, 30, day=24))], ['News'])
        [skipped] = self.programming.airings(local(18), local(18, 30))
        self.assertEqual((skipped['skipped'], skipped['by']), (True, 'skipped'))
        self.programming.skip_slot(made['id'], '2026-09-23', False)
        self.assertEqual([t[0] for t in self.titles(local(18), local(18, 30))], ['News'])
        self.programming.update_slot(made['id'], {'enabled': False})
        self.assertEqual([t[0] for t in self.titles(local(18), local(18, 30))], ['OFF AIR'])
        self.assertEqual(self.programming.remove_slot(made['id'])['title'], 'News')
        self.assertIsNone(self.programming.remove_slot(made['id']))
        self.assertIsNone(self.programming.update_slot('nope', {'title': 'x'}))

    def test_invalid_slots_are_refused(self):
        good = slot('News', '18:00', 30, channel(NBC))
        for change in ({'days': []}, {'days': ['funday']}, {'start': '25:00'}, {'start': '6pm'}, {'minutes': 2}, {'minutes': 2000},
                       {'title': ''}, {'color': 'red'}, {'priority': 'urgent'}, {'what': {'kind': 'film'}},
                       {'what': {'kind': 'program', 'title': ''}}, {'what': {'kind': 'program', 'title': 'x', 'target': OFF_AIR}},
                       {'what': {'kind': 'library', 'root': 'x', 'order': 'backwards'}},
                       {'what': {'kind': 'library', 'root': 'x', 'ad_breaks': 50}}, {'skip': ['tomorrow']}):
            with self.assertRaises(ConfigError, msg=change):
                self.programming.add_slot({**good, **change})
        self.assertEqual(self.programming.slots(), [])

    def test_the_switch_and_an_old_grid_body_still_work(self):
        self.assertFalse(self.programming.enabled)
        self.assertTrue(self.programming.set_enabled(True)['settings']['enabled'])
        with self.assertRaises(ConfigError):
            self.programming.set_enabled('yes')
        body = empty()
        body.update(enabled=True, blocks=[{'id': 'n', 'name': 'News', 'color': '#3a6f8f', 'target': NBC}])
        body['grid']['wed'][36:38] = ['n', 'n']
        described = self.programming.save_grid(body)
        self.assertEqual([(s['title'], s['start'], s['minutes']) for s in described['settings']['slots']], [('News', '18:00', 60)])
        self.assertNotIn('pins', described['settings'])


class GuideIndexTests(unittest.TestCase):
    def index(self, rows, folder=None, wall=None):
        self.clock = Clock()
        self.rows = rows
        return GuideIndex(lambda: self.rows, Path(folder) / 'atlas.json' if folder else None, zone=ZONE, clock=self.clock,
                          wall=wall or (lambda: NOON.timestamp()))

    def test_titles_match_whatever_their_punctuation(self):
        self.assertEqual(normal('Jeopardy!'), normal('JEOPARDY'))
        self.assertEqual(normal('The View'), 'view')
        self.assertEqual(normal('Law & Order: SVU'), 'law and order svu')

    def test_find_prefers_the_usual_channel_then_the_antenna_then_the_nearest(self):
        guide = self.index(guide_rows(('youtube-tv/ABC', 'Jeopardy!', local(19, 30), 30), ('7.1', 'Jeopardy!', local(19, 30), 30),
                                      ('youtube-tv/NBC', 'Jeopardy!', local(16), 30), ('7.1', 'Paid Programming', local(3), 30)))
        found = guide.find('jeopardy', local(19, 30), local(20))
        self.assertEqual([a['channel'] for a in found], ['7.1 WJLA', 'YouTube TV ABC'])
        self.assertEqual(guide.find('jeopardy', local(19, 30), local(20), usual=ABC)[0]['channel'], 'YouTube TV ABC')
        self.assertEqual(guide.find('jeopardy', local(22), local(22, 30)), [])   # The 4 PM one is not this airing.
        self.assertEqual(guide.find('Paid Programming', local(3), local(3, 30)), [])
        self.assertEqual([a['title'] for a in guide.find('jeop', local(19, 30), local(20), match='contains')][:1], ['Jeopardy!'])
        self.assertEqual(guide.on_channel(WJLA, local(19, 45))['title'], 'Jeopardy!')
        self.assertEqual(guide.status()['channels'], 3)   # The Live Sports row tunes nothing.
        self.assertEqual(guide.reach(), local(20))

    def test_the_atlas_notes_each_date_once_and_search_finds_what_was_listed(self):
        with tempfile.TemporaryDirectory() as folder:
            guide = self.index(guide_rows(('7.1', 'Jeopardy!', local(19, 30), 30, {'new': True})), folder)
            guide.airings()
            self.rows = guide_rows(('7.1', 'Jeopardy!', local(19, 30), 30), ('7.1', 'Jeopardy!', local(19, 30, day=24), 30), ('7.1', 'x', local(1), 30))
            self.clock.now += 1000
            [entry] = [e for e in guide.remembered() if e['title'] == 'Jeopardy!']
            self.assertEqual(sorted(entry['times']), [(2, 19 * 60 + 30, 30, 1, '2026-09-23'), (3, 19 * 60 + 30, 30, 1, '2026-09-24')])
            self.assertEqual(entry['new'], 1)
            # Kept on disk; a programme no longer listed is still found by name.
            later = GuideIndex(lambda: guide_rows(), Path(folder) / 'atlas.json', zone=ZONE, wall=lambda: NOON.timestamp())
            [found] = later.search('jeop')
            self.assertEqual((found['title'], found['airings'], found.get('remembered')), ('Jeopardy!', 0, True))
            [listed] = guide.search('Jeopardy')
            self.assertEqual((listed['airings'], listed['next']['channel']), (2, '7.1 WJLA'))

    def test_no_guide_keeps_the_last_index(self):
        guide = self.index(guide_rows(('7.1', 'Jeopardy!', local(19, 30), 30)))
        self.assertTrue(guide.available())

        def away():
            raise OSError('TV Thing is away')
        guide.fetch = away
        self.clock.now += 1000
        self.assertEqual(len(guide.find('Jeopardy!', local(19, 30), local(20))), 1)
        self.assertEqual(guide.status()['error'], 'TV Thing is away')


if __name__ == '__main__':
    unittest.main()
