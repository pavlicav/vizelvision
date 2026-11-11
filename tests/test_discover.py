"""Discovery: ideas for the schedule from what there is to air (discover.py), and its API."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.discover import Discovery
from roku_stream.guide_index import GuideIndex
from roku_stream.programming import Programming
from roku_stream.source_queue import SourceQueue
from roku_stream.sports_slots import SportsSlots

from tests.test_lineup import Clock, NBC, WJLA, guide_rows, slot
from tests.test_sports_slots import FakeSports, coming, game

ZONE = ZoneInfo('America/New_York')


def at(day, hour, minute=0):
    """A time `day` days from today, in the station's zone."""
    date = datetime.now(ZONE).date() + timedelta(days=day)
    return datetime(date.year, date.month, date.day, hour, minute, tzinfo=ZONE).astimezone(timezone.utc)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.queue = SourceQueue(folder / 'queue.json', lambda item: {}, lambda *_: {'finished': False}, start_worker=False)
        self.addCleanup(self.queue.close)
        self.sports = FakeSports()
        self.programming = Programming(folder / 'programming.json', self.queue, zone=ZONE, game=self.sports.game, start_worker=False)
        self.clock = Clock()
        # Two evenings of listings: Jeopardy! and the news at the same times, a special once.
        self.rows = guide_rows(*[(key, title, at(day, hour, minute), minutes, extra)
                                 for day in (1, 2)
                                 for key, title, hour, minute, minutes, extra in (
                                     ('7.1', 'Jeopardy!', 19, 30, 30, {'new': True}), ('youtube-tv/ABC', 'Jeopardy!', 19, 30, 30, {'new': True}),
                                     ('youtube-tv/NBC', 'News4 at 6', 18, 0, 60, {'new': True}),
                                     ('7.1', 'Paid Programming', 3, 0, 30, {}))],
                               ('youtube-tv/NBC', 'The Big Special', at(1, 20), 120, {'new': True, 'live': True}))
        self.guide = GuideIndex(lambda: self.rows, folder / 'atlas.json', zone=ZONE, clock=self.clock)
        self.programming.guide = self.guide
        self.files = [{'id': f'shows/Made/E{n:02d}.mkv', 'root': 'shows', 'path': f'Made/E{n:02d}.mkv', 'title': f'E{n}',
                       'duration': 21 * 60, 'playable': True, 'ad_breaks': {'state': 'ok', 'at': [300, 600, 900]}} for n in range(6)]
        self.programming.library = lambda: {'items': self.files, 'roots': [{'id': 'shows', 'name': 'Shows'}]}
        self.slots = SportsSlots(self.programming, self.sports)
        self.discovery = Discovery(self.programming, self.guide, sports_slots=self.slots, queue=self.queue)

    def ideas(self):
        found = self.discovery.ideas(force=True)
        return found, {group['id']: group['ideas'] for group in found['groups']}

    def test_strips_events_folders_and_sports_slots_are_suggested(self):
        monday = coming(0, 20, 15)
        self.sports.games['nfl'] = [game(1, 'Bills at Vikings', monday, ('ESPN',))]
        found, groups = self.ideas()
        # Jeopardy! is one idea (the antenna's, not YouTube TV's too); the paid programme is none.
        strips = {idea['title']: idea for idea in groups['strips']}
        self.assertEqual(sorted(strips), ['Jeopardy!', 'News4 at 6'])
        jeopardy = strips['Jeopardy!']['apply']
        self.assertEqual((jeopardy['method'], jeopardy['path']), ('POST', 'v1/programming/slots'))
        self.assertEqual(jeopardy['body']['what'], {'kind': 'program', 'title': 'Jeopardy!', 'target': WJLA, 'follow': True})
        self.assertEqual((jeopardy['body']['start'], jeopardy['body']['minutes']), ('19:30', 30))
        self.assertEqual([idea['title'] for idea in groups['soon']], ['The Big Special'])
        self.assertEqual(groups['soon'][0]['apply']['path'], 'v1/programming/shows')
        [made] = groups['library']
        self.assertEqual((made['title'], made['apply']['body']['what']),
                         ('Made', {'kind': 'library', 'root': 'shows', 'order': 'next', 'path': 'Made/', 'ad_breaks': 120}))
        self.assertEqual([idea['title'] for idea in groups['sports']], ['Monday Night Football'])
        self.assertEqual(groups['sports'][0]['games'][0]['title'], 'Bills at Vikings')
        # The draft: ideas that fit beside each other.
        self.assertEqual({d['id'] for d in found['draft']}, {jeopardy_id for jeopardy_id in (strips['Jeopardy!']['id'], strips['News4 at 6']['id'], made['id'])})
        # Every idea can be applied as it is.
        for idea in (strips['Jeopardy!'], made):
            self.programming.add_slot(idea['apply']['body'])
        self.programming.add_sports_slot(groups['sports'][0]['apply']['body'])
        _, groups = self.ideas()
        self.assertEqual([idea['title'] for idea in groups.get('strips', [])], ['News4 at 6'])
        self.assertNotIn('library', groups)
        self.assertNotIn('sports', groups)

    def test_a_fixed_slot_whose_time_the_listings_name_can_follow_them(self):
        tomorrow = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][(datetime.now(ZONE).date() + timedelta(days=1)).weekday()]
        news = self.programming.add_slot(slot('News 10', '18:00', 60, {'kind': 'channel', 'target': NBC}, days=[tomorrow]))
        _, groups = self.ideas()
        [fix] = groups['fixups']
        self.assertEqual(fix['title'], 'News 10 is News4 at 6')
        self.assertEqual(fix['apply'], {'method': 'POST', 'path': 'v1/programming/slots/' + news['id'], 'body': {
            'what': {'kind': 'program', 'title': 'News4 at 6', 'target': NBC, 'follow': True}, 'title': 'News4 at 6'}})
        self.programming.update_slot(news['id'], fix['apply']['body'])
        _, groups = self.ideas()
        self.assertNotIn('fixups', groups)
        self.assertNotIn('News4 at 6', [idea['title'] for idea in groups.get('strips', [])])

    def test_ideas_are_kept_for_a_while_and_one_source_failing_leaves_the_rest(self):
        first = self.discovery.ideas()
        self.assertIs(self.discovery.ideas(), first)
        self.discovery.forget()
        self.programming.library = Mock(side_effect=OSError('the disk is away'))
        self.programming._files = (None, [])
        found, groups = self.ideas()
        self.assertIn('strips', groups)
        self.assertNotIn('library', groups)


class ScheduleApiTests(unittest.TestCase):
    """The Schedule page's writes, through the real handler."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.queue = SourceQueue(folder / 'queue.json', lambda item: {}, lambda *_: {'finished': False}, start_worker=False)
        self.addCleanup(self.queue.close)
        self.programming = Programming(folder / 'programming.json', self.queue, zone=ZONE, start_worker=False)
        self.programming.guide = GuideIndex(lambda: guide_rows(('7.1', 'Jeopardy!', at(1, 19, 30), 30)), zone=ZONE)
        self.slots = SportsSlots(self.programming, FakeSports())
        self.discovery = Discovery(self.programming, self.programming.guide, sports_slots=self.slots)
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig(socket_path=folder / 'master.sock'))
        self.handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(), playout=self.queue,
                                            programming=self.programming, sports_slots=self.slots, discovery=self.discovery)

    def call(self, method, path, body=None):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler._authorize = lambda: True
        handler._body = Mock(return_value=body)
        handler._json = Mock()
        getattr(handler, 'do_' + method)()
        status, payload = handler._json.call_args[0]
        return int(status), payload

    def test_slots_are_added_changed_skipped_and_removed(self):
        body = slot('Jeopardy', '19:30', 30, {'kind': 'program', 'title': 'Jeopardy!'}, days=['mon', 'tue'])
        status, made = self.call('POST', '/v1/programming/slots', body)
        slot_id = made['changed']['id']
        self.assertEqual((status, [s['title'] for s in made['settings']['slots']]), (200, ['Jeopardy']))
        self.assertTrue(all(a['slot'] == slot_id for a in made['airings']))
        status, changed = self.call('POST', '/v1/programming/slots/' + slot_id, {'start': '20:00'})
        self.assertEqual((status, changed['changed']['start'], changed['changed']['title']), (200, '20:00', 'Jeopardy'))
        status, skipped = self.call('POST', f'/v1/programming/slots/{slot_id}/skip', {'date': '2099-01-05'})
        self.assertEqual((status, skipped['changed']['skip']), (200, ['2099-01-05']))
        status, removed = self.call('DELETE', '/v1/programming/slots/' + slot_id)
        self.assertEqual((status, removed['removed_slot']['id'], removed['settings']['slots']), (200, slot_id, []))
        # Put back as it was (the page's Undo).
        status, back = self.call('POST', '/v1/programming/slots', removed['removed_slot'])
        self.assertEqual((status, back['changed']['id']), (200, slot_id))
        for method, path, body in (('POST', '/v1/programming/slots/nope', {'title': 'x'}), ('DELETE', '/v1/programming/slots/nope', None),
                                   ('POST', '/v1/programming/slots/nope/skip', {'date': '2099-01-05'})):
            self.assertEqual(self.call(method, path, body)[0], 404)

    def test_the_switch_the_old_grid_and_the_reads(self):
        self.assertTrue(self.call('POST', '/v1/programming', {'enabled': True})[1]['settings']['enabled'])
        self.assertFalse(self.call('POST', '/v1/programming', {'enabled': False})[1]['settings']['enabled'])
        from roku_stream.programming import empty
        grid = empty()
        grid.update(enabled=True, blocks=[{'id': 'n', 'name': 'News', 'color': '#3a6f8f', 'target': NBC}])
        grid['grid']['mon'][36] = 'n'
        status, described = self.call('POST', '/v1/programming', grid)
        self.assertEqual((status, [s['title'] for s in described['settings']['slots']]), (200, ['News']))
        status, described = self.call('GET', '/v1/programming')
        self.assertEqual((status, described['airings_days'], described['guide']['available']), (200, 8, True))
        status, found = self.call('GET', '/v1/programming/search?q=jeop')
        self.assertEqual((status, [p['title'] for p in found['programmes']]), (200, ['Jeopardy!']))
        self.assertEqual(self.call('GET', '/v1/programming/library'), (200, {'folders': []}))
        status, ideas = self.call('GET', '/v1/programming/ideas?fresh=1')
        self.assertEqual((status, sorted(ideas)), (200, ['count', 'draft', 'generated_at', 'groups', 'guide', 'seconds']))

    def test_sports_slots_are_added_previewed_changed_and_removed(self):
        mnf = {'title': 'Monday Night Football', 'league': 'nfl', 'days': ['mon'], 'from': '19:00', 'to': '23:30', 'priority': 'high'}
        self.assertEqual(self.call('POST', '/v1/programming/sports/preview', mnf), (200, {'games': []}))
        status, made = self.call('POST', '/v1/programming/sports', mnf)
        slot_id = made['changed']['id']
        self.assertEqual((status, made['settings']['sports'][0]['priority']), (200, 'high'))
        status, view = self.call('GET', '/v1/programming/sports')
        self.assertEqual((status, [s['id'] for s in view['slots']]), (200, [slot_id]))
        self.assertEqual(self.call('POST', '/v1/programming/sports/' + slot_id, {'priority': 'normal'})[1]['changed']['priority'], 'normal')
        status, planned = self.call('POST', '/v1/programming/sports/plan', {})
        self.assertEqual((status, planned['sports']['games']), (200, []))
        self.assertEqual(self.call('DELETE', '/v1/programming/sports/' + slot_id)[1]['settings']['sports'], [])
        self.assertEqual(self.call('DELETE', '/v1/programming/sports/' + slot_id)[0], 404)


if __name__ == '__main__':
    unittest.main()
