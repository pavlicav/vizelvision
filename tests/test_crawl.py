import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest.mock
from unittest.mock import Mock

from roku_stream import crawl, crawl_feeds
from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.crawl_desk import CrawlDesk
from roku_stream.crawl_ledger import CrawlLedger
from roku_stream.errors import ConfigError
from roku_stream.master_worker import MasterWorker

NOW = datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc)  # 3:00 PM in Washington, a Thursday
DC = ('011001',)


def event(id=1, code='SVR', desc='Severe Thunderstorm Warning', severity='warning', locations=('011001', '024031'),
          expires=NOW + timedelta(minutes=45), **extra):
    names = {'011001': 'District of Columbia, DC', '024031': 'Montgomery County, MD', '051059': 'Fairfax County, VA',
             '073535': 'Tidal Potomac'}
    return {'id': id, 'valid': 1, 'event_code': code, 'event_desc': desc, 'severity': severity, 'originator': 'WXR',
            'originator_desc': 'National Weather Service', 'origin': 'radio', 'locations': list(locations),
            'locations_detail': [{'code': c, 'name': names.get(c, c), 'marine': c.startswith('07')} for c in locations],
            'issued_utc': (NOW - timedelta(minutes=5)).isoformat(), 'expires_utc': expires.isoformat(),
            'transcript': '', **extra}


def nws(id='urn:1', event='Severe Thunderstorm Warning', severity='Severe', urgency='Immediate', **extra):
    properties = {'id': id, 'status': 'Actual', 'event': event, 'severity': severity, 'urgency': urgency,
                  'headline': f'{event} issued October 1 at 2:55PM EDT until October 1 at 3:45PM EDT by NWS Sterling VA',
                  'parameters': {'NWSheadline': []}, 'sent': (NOW - timedelta(minutes=5)).isoformat(),
                  'expires': (NOW + timedelta(minutes=45)).isoformat(), 'ends': None, 'areaDesc': 'District of Columbia',
                  'senderName': 'NWS Sterling VA',
                  'description': 'At 254 PM EDT, a severe thunderstorm was located over Arlington.\n\nHAZARD...60 mph wind gusts.',
                  **extra}
    return crawl.nws_alert({'properties': properties})


class Eastern(unittest.TestCase):
    def setUp(self):
        self.tz = os.environ.get('TZ')
        os.environ['TZ'] = 'America/New_York'
        time.tzset()

    def tearDown(self):
        if self.tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self.tz
        time.tzset()


class SettingsTests(Eastern):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = crawl.CrawlSettings(MasterConfig(socket_path=Path(self.temp.name) / 'master.sock'))

    def test_the_first_versions_file_becomes_the_override(self):
        self.settings.path.write_text(json.dumps({'message': 'Game 3 tonight', 'label': 'Update', 'style': 'station',
                                                  'eas': True, 'eas_tests': True, 'eas_transcript': True, 'dismissed': [3]}))
        value = self.settings.read()
        self.assertEqual(value['override'], {'text': 'Game 3 tonight', 'label': 'Update', 'style': 'station', 'until': None})
        self.assertEqual((value['eas_tests'], value['dismissed'], value['rules']['off_air']), (True, [3], 'always'))

    def test_update_merges_rules_and_segments_and_keeps_dismissals(self):
        self.settings.dismiss('eas', 9)
        self.settings.dismiss('nws', 'urn:x')
        value = self.settings.update({'rules': {'game': 'popups'}, 'segments': {'scores': {'every': 10}},
                                      'teams': ['nhl:23', 'mlb:22']})
        self.assertEqual((value['rules']['game'], value['rules']['program']), ('popups', 'popups'))
        self.assertEqual((value['segments']['scores']['every'], value['segments']['scores']['enabled']), (10, True))
        self.assertEqual((value['dismissed'], value['nws_dismissed']), ([9], ['urn:x']))
        self.settings.dismiss('nws', 'urn:x', False)
        self.assertEqual(self.settings.read()['nws_dismissed'], [])
        for bad in ({'rules': {'game': 'loud'}}, {'rules': {'per_hour': 0}}, {'segments': {'tv': {}}},
                    {'segments': {'scores': {'every': 1}}}, {'teams': ['xfl:1']}, {'teams': ['nhl:23', 'nhl:23']},
                    {'override': {'text': 'two\nlines'}}, {'important': {'until': 'soon'}}, {'dismissed': [1]},
                    {'messages': [{'text': 'x', 'days': []}]}, {'messages': [{'text': 'x', 'start': '25:00'}]},
                    {'surprise': 1}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                self.settings.update(bad)
        with self.assertRaises(ConfigError):
            self.settings.dismiss('eas', 'nine')

    def test_messages_run_on_their_days_times_and_dates(self):
        message = crawl.CrawlSettings.validate({'messages': [
            {'text': ' Late  show ', 'tag': 'tonight', 'days': [3], 'start': '22:00', 'end': '02:00'}]})['messages'][0]
        self.assertEqual((message['text'], message['tag'], len(message['id'])), ('Late show', 'TONIGHT', 12))
        at = lambda hour, day=1: datetime(2026, 10, day, hour, 30).astimezone()  # Oct 1 is a Thursday (3)
        self.assertFalse(crawl.message_active(message, at(15)))
        self.assertTrue(crawl.message_active(message, at(23)))
        self.assertTrue(crawl.message_active(message, at(1)))  # the overnight window, still on Thursday's date
        self.assertFalse(crawl.message_active(message, at(23, 2)))  # Friday
        dated = {**message, 'start': '', 'end': '', 'from': '2026-10-02'}
        self.assertFalse(crawl.message_active(dated, at(12)))


class AlertTests(Eastern):
    def test_covers_county_any_part_whole_state_and_country(self):
        for code, expected in (('011001', True), ('311001', True), ('011000', True), ('000000', True),
                               ('024031', False), ('011003', False), ('bad', False)):
            with self.subTest(code=code):
                self.assertEqual(crawl.covers(code, '011001'), expected)

    def test_describe_words_an_eas_alert_with_the_area_first(self):
        item = crawl.describe(event(locations=('024031', '011001', '073535'),
                                    transcript='  The storm  was located near Rockville. '), DC, NOW)
        self.assertEqual(item['heading'], 'SEVERE THUNDERSTORM WARNING')
        self.assertEqual(item['text'], 'The National Weather Service has issued a Severe Thunderstorm Warning for '
                                       'District of Columbia, DC; Montgomery County, MD until 3:45 PM. '
                                       'The storm was located near Rockville.')
        later = crawl.describe(event(code='FLA', desc='Flood Watch', expires=NOW + timedelta(days=1, hours=-4)),
                               DC, NOW, transcript=False)
        self.assertTrue(later['text'].endswith('until 11 AM Friday.'))

    def test_active_alerts_filter_area_expiry_tests_and_validity(self):
        events = [event(id=1, code='SVA', desc='Severe Thunderstorm Watch', severity='watch'), event(id=2),
                  event(id=3, locations=('051059',)), event(id=4, expires=NOW - timedelta(seconds=1)),
                  event(id=5, code='RWT', desc='Required Weekly Test', severity='test'),
                  event(id=6, origin='selftest', locations=('000000',)), event(id=7, valid=0), event(id='8')]
        self.assertEqual([a['id'] for a in crawl.active_alerts(events, DC, NOW)], [2, 1])
        self.assertEqual([a['id'] for a in crawl.active_alerts(events, DC, NOW, tests=True)], [2, 1, 5, 6])

    def test_nws_alerts_are_worded_and_severe_ones_are_important(self):
        warning = nws()
        self.assertTrue(crawl.nws_important(warning))
        self.assertFalse(crawl.nws_important(nws(event='Tornado Watch', urgency='Future')))
        self.assertFalse(crawl.nws_important(nws(event='Heat Advisory', severity='Moderate', urgency='Expected')))
        item = crawl.nws_item(warning, NOW)
        self.assertEqual(item['heading'], 'SEVERE THUNDERSTORM WARNING')
        self.assertTrue(item['text'].startswith('Severe Thunderstorm Warning issued October 1 at 2:55PM EDT until'))
        self.assertIn('Hazard: 60 mph wind gusts.', item['text'])
        self.assertIsNone(crawl.nws_alert({'properties': {'id': 'x', 'status': 'Test'}}))

    def test_layers_split_severe_from_lesser_and_prefer_nws_wording(self):
        settings = crawl.CrawlSettings.validate({})
        eas = crawl.active_alerts([event(id=2), event(id=1, code='SVA', desc='Severe Thunderstorm Watch', severity='watch')],
                                  DC, NOW)
        alerts = [nws(), nws(id='urn:2', event='Heat Advisory', severity='Moderate', urgency='Expected')]
        important, label, rotation, summaries = crawl.alert_layers(settings, eas, alerts, NOW, DC)
        self.assertEqual(label, 'WEATHER ALERT')
        self.assertEqual([i['heading'] for i in important], ['SEVERE THUNDERSTORM WARNING'])  # the NWS one, once
        self.assertEqual([i['heading'] for i in rotation], ['HEAT ADVISORY', 'SEVERE THUNDERSTORM WATCH'])
        duplicate = next(s for s in summaries if s['source'] == 'eas' and s['id'] == 2)
        self.assertTrue(duplicate['duplicate'])
        quiet = crawl.alert_layers({**settings, 'nws_dismissed': ['urn:1'], 'dismissed': [2]}, eas, alerts, NOW, DC)
        self.assertEqual(quiet[0], [])
        self.assertEqual(crawl.alert_layers({**settings, 'nws': False}, eas, alerts, NOW, DC)[0][0]['heading'],
                         'SEVERE THUNDERSTORM WARNING')

    def test_compose_keys_follow_the_alerts_not_their_words(self):
        settings = crawl.CrawlSettings.validate({'override': {'text': 'Game 3 tonight', 'label': 'vv'}})
        override = crawl.compose(settings, [], None, NOW)
        self.assertEqual((override['kind'], override['label'], override['passes']), ('override', 'VV', 0))
        first = crawl.compose(settings, [crawl.describe(event(), DC, NOW)], 'WEATHER ALERT', NOW)
        heard = crawl.compose(settings, [crawl.describe(event(transcript='Take cover.'), DC, NOW)], 'WEATHER ALERT', NOW)
        second = crawl.compose(settings, [crawl.describe(event(), DC, NOW),
                                          crawl.describe(event(id=9, desc='Tornado Warning'), DC, NOW)], 'WEATHER ALERT', NOW)
        self.assertEqual(first['kind'], 'important')
        self.assertEqual(first['key'], heard['key'])
        self.assertNotEqual(first['key'], second['key'])
        manual = {**settings, 'important': {'text': 'Shelter in place', 'label': 'Important', 'until': None}}
        alone = crawl.compose(manual, [], None, NOW)
        self.assertEqual((alone['label'], alone['items'][0]['text']), ('IMPORTANT', 'Shelter in place'))
        expired = {**settings, 'override': {**settings['override'], 'until': (NOW - timedelta(minutes=1)).isoformat()}}
        self.assertIsNone(crawl.compose(expired, [], None, NOW))

    def test_bulletins_are_validated(self):
        good = {'key': 'scores-1', 'label': 'SCORES', 'style': 'station', 'passes': 1, 'lease': 600,
                'items': [{'tag': 'NHL', 'text': 'Capitals 3, Bruins 2'}]}
        self.assertEqual(crawl.validate_bulletin(good)['items'][0], {'tag': 'NHL', 'heading': '', 'text': 'Capitals 3, Bruins 2'})
        for change in ({'key': 'Bad Key'}, {'passes': 9}, {'lease': 1}, {'items': []}, {'style': 'pink'},
                       {'items': [{'text': ''}]}):
            with self.subTest(change=change), self.assertRaises(ConfigError):
                crawl.validate_bulletin({**good, **change})


class WorkerCrawlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        master = MasterConfig(enabled=True, socket_path=Path(self.directory.name) / 'master.sock')
        self.worker = MasterWorker(SimpleNamespace(master=master, tv_thing=TvThingConfig(enabled=True)),
                                   tv=Mock(), status_reader=lambda: {"ready": True})
        self.worker.output = Mock()
        self.worker.output.crawl_finished.return_value = None
        self.worker.eas, self.worker.nws = Mock(), Mock()
        self.worker.eas.status.return_value = self.worker.nws.status.return_value = {'error': None}
        self.alerts = []
        self.worker.eas.alerts.side_effect = lambda tests: crawl.active_alerts(
            self.alerts, DC, datetime.now(timezone.utc), tests=tests)
        self.worker.nws.alerts.return_value = []

    def tearDown(self):
        self.directory.cleanup()

    def bulletin(self, key='scores-1', passes=1, lease=600):
        return {'key': key, 'label': 'SCORES', 'style': 'station', 'passes': passes, 'lease': lease,
                'items': [{'tag': 'NHL', 'heading': '', 'text': 'Capitals 3, Bruins 2'}]}

    def shown(self):
        return self.worker.output.set_crawl.call_args

    def test_a_bulletin_runs_its_pass_and_ends(self):
        self.assertEqual(self.worker.submit('crawl', {'bulletin': self.bulletin()}), {'accepted': True})
        self.assertTrue(self.worker.crawl_wake)
        self.worker._crawl()
        content = self.shown().args[0]
        self.assertEqual((content['kind'], content['key'], content['passes']), ('bulletin', 'scores-1', 1))
        self.assertEqual(self.worker.status()['crawl']['bulletin']['key'], 'scores-1')
        self.worker.output.crawl_finished.return_value = 'scores-1'
        calls = self.worker.output.set_crawl.call_count
        self.worker._crawl()
        self.assertEqual(self.worker.output.set_crawl.call_count, calls)  # it slid away by itself
        status = self.worker.status()['crawl']
        self.assertIsNone(status['bulletin'])
        self.assertEqual(status['bulletins_ended'][-1]['how'], 'done')

    def test_important_and_override_come_first(self):
        self.worker.submit('crawl', {'bulletin': self.bulletin(passes=0, lease=30)})
        self.worker._crawl()
        self.alerts = [event(id=2, expires=datetime.now(timezone.utc) + timedelta(minutes=30))]
        self.worker._crawl()
        content = self.shown().args[0]
        self.assertEqual((content['kind'], self.shown().kwargs), ('important', {'restart': True}))
        self.assertEqual(self.worker.status()['crawl']['bulletins_ended'][-1]['how'], 'preempted by important')
        self.assertEqual(self.worker.submit('crawl', {'bulletin': self.bulletin(key='b-2')}),
                         {'accepted': False, 'reason': 'important'})
        self.alerts = [event(id=2, expires=datetime.now(timezone.utc) + timedelta(minutes=30), transcript='Take cover.')]
        self.worker._crawl()
        self.assertEqual(self.shown().kwargs, {'restart': False})  # the transcript follows the running pass
        self.alerts = []
        self.worker.crawl_settings.update({'override': {'text': 'Game 3 tonight'}})
        self.worker._crawl()
        self.assertEqual(self.shown().args[0]['kind'], 'override')
        self.worker.crawl_settings.update({'override': {'text': ''}})
        self.worker._crawl()
        self.assertEqual(self.shown().args, (None,))

    def test_a_loop_ends_when_its_lease_runs_out(self):
        self.worker.submit('crawl', {'bulletin': self.bulletin(passes=0, lease=30)})
        self.worker._crawl()
        self.worker.bulletin['deadline'] = time.monotonic() - 1
        self.worker._crawl()
        self.assertEqual(self.shown().args, (None,))
        self.assertEqual(self.worker.status()['crawl']['bulletins_ended'][-1]['how'], 'expired')

    def test_a_bad_crawl_never_fails_the_worker(self):
        self.worker.crawl_settings.path.write_text('{')
        self.worker._crawl()
        self.assertIn('Crawl not updated', self.worker.status()['crawl']['error'])
        self.worker.crawl_settings.path.unlink()
        self.worker.eas.alerts.side_effect = RuntimeError('odd event')
        self.worker._crawl()
        self.assertIn('odd event', self.worker.status()['crawl']['error'])
        with self.assertRaises(ConfigError):
            self.worker.submit('crawl', {'bulletin': {'key': 'x'}})


class FakeMaster:
    def __init__(self):
        self.state = {'on_air': {'id': 'p'}, 'ident': {'on_air': False},
                      'crawl': {'kind': None, 'bulletin': None, 'bulletins_ended': [], 'rotation_alerts': []}}
        self.sent = []

    def request(self, action='status', body=None):
        if action == 'status':
            return self.state
        self.sent.append(body['bulletin'])
        self.state['crawl']['bulletin'] = {'key': body['bulletin']['key']} if body['bulletin'] else None
        return {'accepted': True}


class FakeFeed:
    def __init__(self, items):
        self._items = items
        self.wanted = None

    def items(self):
        return list(self._items)

    def want(self, wanted):
        self.wanted = wanted

    def status(self):
        return {'error': None, 'fetched_at': 1}

    def stop(self):
        pass


class DeskTests(Eastern):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = crawl.CrawlSettings(MasterConfig(socket_path=Path(self.temp.name) / 'master.sock'))
        self.master = FakeMaster()
        self.now = NOW.timestamp()
        self.feeds = {'transit': FakeFeed([{'tag': 'RED LINE', 'heading': '', 'text': 'Single-tracking.'}]),
                      'scores': FakeFeed([{'tag': 'NHL', 'heading': '', 'text': 'Capitals 3, Bruins 2'}]),
                      'cairo': FakeFeed([{'tag': 'NOW ON CAIRO RADIO', 'heading': '', 'text': 'CLASSICAL SHOW'}])}
        self.production = Mock()
        self.production.read.return_value = {'audio': 'radio'}
        self.desk = CrawlDesk(self.settings, self.master, feeds=self.feeds, production=self.production,
                              clock=lambda: self.now)

    def finish(self):
        key = self.master.state['crawl']['bulletin']['key']
        self.master.state['crawl']['bulletin'] = None
        self.master.state['crawl']['bulletins_ended'] = [{'key': key, 'how': 'done', 'at': self.now}]

    def test_popups_take_turns_within_the_hourly_limit_and_gap(self):
        self.settings.update({'segments': {k: {'enabled': k in ('transit', 'scores')} for k in crawl.SEGMENTS}})
        self.desk.tick()
        first = self.master.sent[-1]
        self.assertEqual((first['label'], first['passes'], first['items'][0]['tag']), ('METRO & BUS', 1, 'RED LINE'))
        self.assertTrue(self.feeds['transit'].wanted)
        self.desk.tick()
        self.assertEqual(len(self.master.sent), 1)  # one pop-up at a time
        self.finish()
        self.now += 60
        self.desk.tick()
        self.assertEqual(len(self.master.sent), 1)  # five minutes apart
        self.now += 4 * 60
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['label'], 'SCORES')
        for _ in range(2):
            self.finish()
            self.now += 20 * 60
            self.desk.tick()
        self.assertEqual(len(self.master.sent), 4)
        self.finish()
        self.now += 6 * 60
        sent = len(self.master.sent)
        self.desk.tick()
        self.assertEqual(len(self.master.sent), sent)  # four an hour at most
        self.assertEqual([h['how'] for h in self.desk.status()['history']], ['done'] * 4)

    def test_changed_only_waits_for_new_items(self):
        self.settings.update({'segments': {k: {'enabled': k == 'transit', 'changed_only': True} for k in crawl.SEGMENTS}})
        self.desk.tick()
        self.finish()
        self.now += 3600
        self.desk.tick()
        self.assertEqual(len(self.master.sent), 1)
        self.feeds['transit']._items = [{'tag': 'BUS D50', 'heading': '', 'text': 'Detour.'}]
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['items'][0]['tag'], 'BUS D50')

    def test_the_off_air_card_loops_everything_and_games_are_quiet(self):
        self.master.state['on_air'] = None
        self.desk.tick()
        loop = self.master.sent[-1]
        self.assertEqual((loop['key'], loop['passes'], loop['lease']), ('loop-off_air', 0, 30))
        self.assertIn('NOW ON CAIRO RADIO', [item['tag'] for item in loop['items']])
        self.desk.tick()
        self.assertEqual(len(self.master.sent), 1)  # renewed every 10 s, not every tick
        self.now += 10
        self.desk.tick()
        self.assertEqual(len(self.master.sent), 2)
        self.master.state['on_air'] = {'id': 'game'}
        self.desk.projector = Mock()
        self.desk.projector.describe.return_value = {'segments': [{'kind': 'game'}]}
        self.desk.tick()
        self.assertEqual((self.desk.view['context'], self.master.sent[-1]), ('game', None))

    def test_cairo_only_airs_under_the_off_air_card_with_radio(self):
        settings = self.settings.read()
        self.assertEqual(self.desk.items('cairo', settings, {}, 'program'), [])
        self.assertEqual(len(self.desk.items('cairo', settings, {}, 'off_air')), 1)
        self.production.read.return_value = {'audio': 'tone'}
        self.assertEqual(self.desk.items('cairo', settings, {}, 'off_air'), [])

    def test_messages_take_turns_and_run_now_skips_the_rules(self):
        self.settings.update({'messages': [{'text': 'One'}, {'text': 'Two'}],
                              'segments': {k: {'enabled': k == 'messages'} for k in crawl.SEGMENTS},
                              'rules': {'program': 'quiet'}})
        self.desk.tick()
        self.assertEqual(self.master.sent, [])
        self.desk.run_now('messages')
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['items'][0]['text'], 'One')
        self.finish()
        self.desk.run_now('messages')
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['items'][0]['text'], 'Two')
        self.assertTrue(self.desk.status()['history'][0]['forced'])
        with self.assertRaises(ConfigError):
            self.desk.run_now('tv')

    def test_a_worker_from_before_the_rotation_gets_nothing(self):
        del self.master.state['crawl']['bulletins_ended']
        self.desk.tick()
        self.assertEqual(self.master.sent, [])
        self.assertIn('restart vizelvision-master', self.desk.view['error'])

    def options(self, **segments):
        value = crawl.FeedSettings.validate({'segments': segments})
        self.desk.feed_options = lambda: value

    def test_new_items_pop_up_at_once_but_not_the_ones_already_listed(self):
        self.settings.update({'segments': {k: {'enabled': k in ('dc_alerts', 'transit')} for k in crawl.SEGMENTS}})
        self.feeds['dc_alerts'] = FakeFeed([{'tag': 'ALERTDC', 'heading': '', 'text': 'Red Mass closures.'}])
        self.options(dc_alerts={'new_now': True, 'repeat': False})
        self.desk.tick()  # learns what is listed; the timer sends transit
        self.assertEqual([b['label'] for b in self.master.sent], ['METRO & BUS'])
        self.finish()
        self.desk.tick()
        self.assertEqual(len(self.master.sent), 1)  # within the gap, and Red Mass is not new
        self.feeds['dc_alerts']._items.append({'tag': 'ALERTDC', 'heading': '', 'text': 'Bridge opening at 11 PM.'})
        self.desk.tick()
        new = self.master.sent[-1]
        self.assertEqual((new['label'], [i['text'] for i in new['items']]), ('DC ALERTS', ['Bridge opening at 11 PM.']))
        self.assertTrue(self.desk.status()['history'][0]['new'])
        self.finish()
        self.now += 3600
        self.desk.tick()  # once each: repeat is off, so the timer never brings it back
        self.assertEqual(self.master.sent[-1]['label'], 'METRO & BUS')

    def test_new_items_wait_out_quiet_contexts_and_running_popups(self):
        self.settings.update({'segments': {k: {'enabled': k == 'dc_alerts'} for k in crawl.SEGMENTS}})
        self.feeds['dc_alerts'] = FakeFeed([])
        self.options(dc_alerts={'new_now': True, 'repeat': False})
        self.desk.tick()
        self.master.state['on_air'] = {'id': 'game'}
        self.desk.projector = Mock()
        self.desk.projector.describe.return_value = {'segments': [{'kind': 'game'}]}
        self.feeds['dc_alerts']._items = [{'tag': 'ALERTDC', 'heading': '', 'text': 'Road closed.'}]
        self.desk.tick()
        self.assertEqual((self.master.sent, self.desk.view['new']), ([], {'dc_alerts': 1}))
        self.desk.projector.describe.return_value = {'segments': [{'kind': 'block'}]}
        self.now += 20
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['items'][0]['text'], 'Road closed.')

    def test_a_segment_airs_only_where_it_is_allowed(self):
        self.settings.update({'segments': {k: {'enabled': k in ('weather', 'transit')} for k in crawl.SEGMENTS}})
        self.feeds['weather'] = FakeFeed([{'tag': 'NOW', 'heading': '', 'text': 'Clear, 82°F.'}])
        self.options(weather={'contexts': ['off_air']})
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['label'], 'METRO & BUS')
        self.assertEqual([s for s, _, _ in self.desk.due(self.settings.read(), self.master.state['crawl'], 'program',
                                                         self.now + 3600, self.desk.feed_options())], ['transit'])
        self.finish()
        self.master.state['on_air'] = None
        self.desk.tick()
        self.assertIn('NOW', [item['tag'] for item in self.master.sent[-1]['items']])

    def test_important_and_override_hold_the_rotation(self):
        self.master.state['crawl']['kind'] = 'override'
        self.desk.tick()
        self.assertEqual((self.master.sent, self.desk.view['higher']), ([], 'override'))


    # ------------------------------------------------------------------ the register

    def entry(self, ident):
        return next(e for e in self.desk.register()['items'] if e['id'] == ident)

    def test_items_air_bare_and_the_register_says_first_then_repeat(self):
        self.settings.update({'segments': {k: {'enabled': k == 'transit'} for k in crawl.SEGMENTS}})
        self.feeds['transit']._items = [{'tag': 'RED LINE', 'heading': '', 'text': 'Single-tracking.', 'id': 'rail:7',
                                         'issued': '2026-10-01T14:50:00'}]
        self.desk.tick()
        sent = self.master.sent[-1]
        self.assertEqual(sent['items'], [{'tag': 'RED LINE', 'heading': '', 'text': 'Single-tracking.'}])
        crawl.validate_bulletin(sent)  # the worker takes it
        entry = self.entry('rail:7')
        self.assertEqual((entry['status'], entry['airing'], entry['air_count'], entry['kind'], entry['source_name']),
                         ('on_air', 'first', 1, 'alert', 'Metrorail'))
        self.finish()
        self.now += 60
        self.desk.tick()
        entry = self.entry('rail:7')
        self.assertEqual((entry['status'], entry['airing'], entry['next_how']), ('next', 'repeat', 'popup'))
        self.assertEqual(entry['next_at'], NOW.timestamp() + 15 * 60)  # every 15 minutes from when it aired
        self.assertEqual(entry['airings'][0]['how'], 'done')

    def test_worker_alerts_are_known_by_their_eas_and_nws_ids(self):
        self.settings.update({'segments': {k: {'enabled': k == 'alerts'} for k in crawl.SEGMENTS}})
        settings = {**self.settings.read(), 'dismissed': [10]}
        eas = crawl.active_alerts([event(id=8, code='SVA', desc='Severe Thunderstorm Watch', severity='watch'),
                                   event(id=9, code='FLA', desc='Flood Watch', severity='watch'),
                                   event(id=10, code='WIY', desc='Wind Advisory', severity='advisory')], DC, NOW)
        flood = nws(id='urn:w', event='Flood Watch', severity='Moderate', urgency='Future')
        _, _, rotation, summaries = crawl.alert_layers(settings, eas, [flood], NOW, DC)
        self.master.state['crawl'].update(alerts=summaries, rotation_alerts=rotation)
        self.desk.tick()
        self.assertEqual(self.master.sent[-1]['label'], 'WEATHER')
        crawl.validate_bulletin(self.master.sent[-1])
        statuses = {e['id']: e['status'] for e in self.desk.register()['items']}
        self.assertEqual(statuses, {'nws:urn:w': 'on_air', 'eas:8': 'on_air', 'eas:9': 'duplicate', 'eas:10': 'muted'})
        self.assertEqual(self.entry('nws:urn:w')['text'], rotation[0]['text'])
        self.assertEqual(self.entry('eas:8')['severity'], 'watch')

    def test_the_important_layer_counts_as_an_airing(self):
        settings = self.settings.read()
        important, label, _, summaries = crawl.alert_layers(settings, crawl.active_alerts([event(id=3)], DC, NOW), [], NOW, DC)
        content = crawl.compose(settings, important, label, NOW)
        self.master.state['crawl'].update(kind='important', key=content['key'], items=content['items'], alerts=summaries)
        self.desk.tick()
        self.desk.tick()
        entry = self.entry('eas:3')
        self.assertEqual((entry['status'], entry['layer'], entry['air_count'], entry['airing']),
                         ('looping', 'important', 1, 'first'))
        self.assertEqual(self.master.sent, [])  # nothing else airs over it
        with self.assertRaises(ConfigError):
            self.desk.air(['eas:3'])
        self.master.state['crawl'].update(kind=None, items=[], alerts=[])
        self.desk.tick()
        self.assertEqual(self.desk.ledger.get('eas:3')['airings'][-1]['how'], 'cleared')

    def test_the_plan_follows_the_rules_and_the_schedule(self):
        self.settings.update({'segments': {k: {'enabled': k in ('transit', 'scores')} for k in crawl.SEGMENTS}})
        self.desk.projector = Mock()
        game = NOW + timedelta(minutes=30)
        self.desk.projector.describe.return_value = {'segments': [
            {'kind': 'block', 'start': NOW.isoformat(), 'end': game.isoformat()},
            {'kind': 'game', 'game': {'league': 'mlb'}, 'start': game.isoformat(),
             'end': (NOW + timedelta(hours=4)).isoformat()}]}
        self.desk.tick()  # transit pops up during the program
        plan = self.desk.plan()
        self.assertEqual([(s['context'], s['mode']) for s in plan['spans']], [('program', 'popups'), ('game', 'quiet')])
        slots = [(s['segment'], s['at'] - self.now) for s in plan['slots']]
        self.assertEqual([segment for segment, _ in slots], ['scores', 'transit', 'scores'])
        self.assertGreaterEqual(slots[0][1], 5 * 60)  # after the gap
        self.assertEqual(slots[1][1], 15 * 60)  # transit's own every
        self.assertTrue(all(at < 30 * 60 for _, at in slots))  # quiet once the game starts
        entry = self.entry(self.desk.snapshot['listings']['scores'][0]['id'])
        self.assertEqual((entry['status'], entry['airing']), ('next', 'first'))
        self.assertIn('First airing', entry['why'])

    def test_an_item_can_be_aired_now_or_muted(self):
        self.settings.update({'segments': {k: {'enabled': k in ('transit', 'scores')} for k in crawl.SEGMENTS},
                              'rules': {'program': 'quiet'}})
        self.feeds['transit']._items = [{'tag': 'RED LINE', 'heading': '', 'text': 'Single-tracking.', 'id': 'rail:1'},
                                        {'tag': 'BUS D60', 'heading': '', 'text': 'Detour.', 'id': 'bus:2'}]
        self.desk.tick()
        self.assertEqual(self.master.sent, [])
        self.assertEqual((self.entry('bus:2')['status'], self.entry('bus:2')['why']), ('held', 'Quiet during programs'))
        scores = self.desk.snapshot['listings']['scores'][0]['id']
        for bad in (['rail:1', scores], ['gone:1'], [], 'rail:1'):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                self.desk.air(bad)
        self.desk.air(['bus:2'])
        self.desk.tick()
        self.assertEqual([i['text'] for i in self.master.sent[-1]['items']], ['Detour.'])
        self.assertTrue(self.desk.status()['history'][0]['forced'])
        self.finish()
        self.desk.mute('rail:1', True)
        self.settings.update({'rules': {'program': 'popups'}, 'segments': {'scores': {'enabled': False}}})
        self.now += 3600
        self.desk.tick()
        self.assertEqual([i['text'] for i in self.master.sent[-1]['items']], ['Detour.'])
        self.assertEqual(self.entry('rail:1')['status'], 'muted')
        self.desk.mute('eas:12', True)
        self.assertEqual(self.settings.read()['dismissed'], [12])
        self.desk.mute('nws:urn:x', True)
        self.assertEqual(self.settings.read()['nws_dismissed'], ['urn:x'])
        with self.assertRaises(ConfigError):
            self.desk.mute('manual:important', True)

    def test_the_ledger_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'crawl-ledger.json'
            clock = [NOW.timestamp()]
            ledger = CrawlLedger(path, clock=lambda: clock[0])
            old = {'id': 'alertdc:a', 'tag': 'ALERTDC', 'heading': '', 'text': 'Road closed.'}
            new = {'id': 'alertdc:b', 'tag': 'ALERTDC', 'heading': '', 'text': 'Bridge opens.'}
            self.assertEqual(ledger.listed('dc_alerts', [old]), [])  # the first look is background
            self.assertEqual(ledger.listed('dc_alerts', [old, new]), [new])
            self.assertEqual(ledger.listed('transit', [{**old, 'id': 'rail:1'}], ready=False), [])
            self.assertNotIn('transit', ledger.learned)  # an unready feed's first look waits
            ledger.aired([new], key='k', context='program', layer='rotation', segment='dc_alerts')
            ledger.save(force=True)
            later = {'id': 'alertdc:c', 'tag': 'ALERTDC', 'heading': '', 'text': 'Parade.'}
            again = CrawlLedger(path, clock=lambda: clock[0])
            self.assertEqual(again.listed('dc_alerts', [old, new, later]), [later])  # restarted: not a first look
            self.assertEqual(again.listed('weather', [{'id': 'weather:now', 'tag': 'NOW', 'heading': '', 'text': 'Hot.'}],
                                          news=False), [])
            self.assertEqual((again.get('alertdc:b')['air_count'], again.get('alertdc:b')['airings'][0]['key']), (1, 'k'))
            clock[0] += 86400 + 1
            again.prune()
            self.assertIsNone(again.get('alertdc:a'))


def protobuf(*fields):
    def varint(n):
        out = bytearray()
        while True:
            out.append((n & 0x7f) | (0x80 if n > 0x7f else 0))
            n >>= 7
            if not n:
                return bytes(out)
    out = b''
    for number, value in fields:
        if isinstance(value, int):
            out += varint(number << 3) + varint(value)
        else:
            value = value.encode() if isinstance(value, str) else value
            out += varint(number << 3 | 2) + varint(len(value)) + value
    return out


def gtfs_entity(route, header, description, start, end):
    text = lambda words: protobuf((1, protobuf((1, words), (2, 'en'))))
    alert = protobuf((1, protobuf((1, start), (2, end))), (5, protobuf((2, route))),
                     (10, text(header)), (11, text(description)))
    return protobuf((1, route), (5, alert))


class FeedTests(unittest.TestCase):
    def test_gtfs_bus_alerts_in_effect_now(self):
        feed = protobuf((1, protobuf((1, '2.0'))),
                        (2, gtfs_entity('D50', 'Delays - D50', 'Expect delays at 14th St NW.', 100, 0)),
                        (2, gtfs_entity('P32', 'Reduced Service - P32', 'Expect delays until 10:15pm.', 120, 200)),
                        (2, gtfs_entity('C25', 'Detour - C25', 'Later.', 900, 1000)))
        alerts = crawl_feeds.gtfs_alerts(feed, 150)
        self.assertEqual([(a['id'], a['routes'], a['header'], a['end']) for a in alerts],
                         [('D50', ['D50'], 'Delays - D50', 0), ('P32', ['P32'], 'Reduced Service - P32', 200)])

        def opener(request, timeout):
            assert request.get_header('Api_key') == 'k'
            if request.full_url.endswith('Incidents'):
                return io.BytesIO(json.dumps({'Incidents': [{'LinesAffected': 'RD;', 'Description': 'Red Line: delays.'},
                                                            {'LinesAffected': 'OR;SV;', 'Description': 'Track work.'},
                                                            {'LinesAffected': 'OR;BL;SV;', 'Description': 'Track problem.'}]}).encode())
            return io.BytesIO(feed)
        os.environ['WMATA_API_KEY'] = 'k'
        try:
            transit = crawl_feeds.TransitFeed(opener=opener, clock=lambda: 150)
            transit.refresh()
        finally:
            del os.environ['WMATA_API_KEY']
        self.assertEqual([(i['tag'], i['text']) for i in transit.items()],
                         [('RED LINE', 'Red Line: delays.'), ('ORANGE/SILVER LINES', 'Track work.'),
                          ('OR/BL/SV LINES', 'Track problem.'), ('BUS P32', 'Reduced Service. Expect delays until 10:15pm.'),
                          ('BUS D50', 'Expect delays at 14th St NW.')])
        self.assertEqual([i['id'] for i in transit.items()][3:], ['bus:P32', 'bus:D50'])
        self.assertTrue(all(i['id'].startswith('rail:') for i in transit.items()[:3]))

    def test_bus_routes_and_rail_are_chosen_as_items_are_read(self):
        feed = crawl_feeds.TransitFeed(opener=Mock(), clock=lambda: 150)
        feed._items = [{'tag': 'RED LINE', 'heading': '', 'text': 'Single-tracking.', 'kind': 'rail', 'routes': []},
                       {'tag': '', 'heading': '', 'text': 'Detour.', 'kind': 'bus', 'routes': ['D5X', 'D60', 'D6X', 'D50']},
                       {'tag': '', 'heading': '', 'text': 'Delays.', 'kind': 'bus', 'routes': ['P32']}]
        feed.fetched_at = 150
        options = {'rail': True, 'bus': True, 'routes': []}
        feed.options = lambda: options
        self.assertEqual([i['tag'] for i in feed.items()], ['RED LINE', 'BUS D5X/D60/D6X', 'BUS P32'])
        options['routes'] = ['D60', 'D6X', 'D50']
        self.assertEqual([i['tag'] for i in feed.items()], ['RED LINE', 'BUS D60/D6X/D50'])  # yours lead the tag
        options.update(rail=False)
        self.assertEqual([i['text'] for i in feed.items()], ['Detour.'])
        options.update(bus=False)
        self.assertEqual(feed.items(), [])

    def test_segment_options_validate_and_the_worker_reads_leniently(self):
        value = crawl.FeedSettings.validate({'segments': {'weather': {'contexts': ['off_air', 'program', 'off_air'][:2]}}})
        self.assertEqual(value['segments']['weather'], {'new_now': False, 'repeat': True, 'contexts': ['program', 'off_air']})
        self.assertTrue(value['segments']['dc_alerts']['new_now'])
        for bad in ({'segments': {'tv': {}}}, {'segments': {'weather': {'contexts': []}}},
                    {'segments': {'weather': {'contexts': ['lobby']}}}, {'segments': {'weather': {'loud': True}}}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                crawl.FeedSettings.validate(bad)
        with tempfile.TemporaryDirectory() as directory:
            master = MasterConfig(socket_path=Path(directory) / 'master.sock')
            (Path(directory) / 'crawl.json').write_text(json.dumps({'eas': False, 'future': 1,
                                                                    'segments': {'weather': {'every': 9, 'later': 2}}}))
            with self.assertRaises(ConfigError):
                crawl.CrawlSettings(master).read()
            value = crawl.CrawlSettings(master, lenient=True).read()
            self.assertEqual((value['eas'], value['segments']['weather']['every']), (False, 9))

    def test_feed_options_validate(self):
        value = crawl.FeedSettings.validate({'transit': {'routes': ['d60', 'D6X', 'd60']}})
        self.assertEqual(value['transit'], {'rail': True, 'bus': True, 'routes': ['D60', 'D6X']})
        for bad in ({'transit': {'routes': ['D60!']}}, {'transit': {'bus': 'no'}}, {'weather': {'zip': '2001'}},
                    {'weather': {'zip': '20011'}}, {'radio': {}}, {'transit': {'routes': ['A'] * 61}}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                crawl.FeedSettings.validate(bad)

    def test_a_zip_gets_its_forecast_and_the_nearest_station_reporting(self):
        responses = {
            'https://api.weather.gov/points/38.9518,-77.0203': {'properties': {
                'forecast': 'https://api.weather.gov/gridpoints/LWX/97,74/forecast',
                'observationStations': 'https://api.weather.gov/gridpoints/LWX/97,74/stations'}},
            'https://api.weather.gov/gridpoints/LWX/97,74/stations': {'features': [
                {'properties': {'stationIdentifier': 'KCGS', 'name': 'College Park Airport'}},
                {'properties': {'stationIdentifier': 'KDCA', 'name': 'Washington/Reagan National Airport, DC'}}]},
            'https://api.weather.gov/stations/KCGS/observations/latest': {'properties': {'temperature': {'value': None}}},
            'https://api.weather.gov/stations/KDCA/observations/latest': {'properties': {
                'textDescription': 'Clear', 'temperature': {'value': 28}, 'windSpeed': {'value': 16}, 'windDirection': {'value': 180}}},
            'https://api.weather.gov/gridpoints/LWX/97,74/forecast': {'properties': {'periods': [
                {'name': 'Tonight', 'isDaytime': False, 'shortForecast': 'Partly Cloudy', 'temperature': 64, 'temperatureUnit': 'F'},
                {'name': 'Friday', 'isDaytime': True, 'shortForecast': 'Sunny', 'temperature': 80, 'temperatureUnit': 'F'}]}}}
        opener = lambda request, timeout: io.BytesIO(json.dumps(responses[request.full_url]).encode())
        zipped = {'zip': '20011', 'place': 'Washington, DC', 'latitude': 38.9518, 'longitude': -77.0203}
        feed = crawl_feeds.WeatherFeed(options=lambda: zipped, opener=opener, clock=lambda: 100)
        feed.refresh()
        self.assertEqual([(i['tag'], i['text']) for i in feed.items()],
                         [('NOW', 'Reagan National: Clear, 82°F, wind S 10 mph.'),
                          ('TONIGHT', 'Partly Cloudy, low 64°F.'), ('FRIDAY', 'Sunny, high 80°F.')])
        self.assertEqual((feed.status()['zip'], feed.status()['station']), ('20011', 'College Park'))
        self.assertEqual(crawl_feeds.station_name('Camp Springs / Andrews Air Force Base'), 'Andrews Air Force Base')

    def test_zip_lookup(self):
        from urllib.error import HTTPError
        found = lambda request, timeout: io.BytesIO(json.dumps({'places': [
            {'place name': 'Washington', 'state abbreviation': 'DC', 'latitude': '38.95181', 'longitude': '-77.02034'}]}).encode())
        self.assertEqual(crawl_feeds.lookup_zip('20011', found),
                         {'place': 'Washington, DC', 'latitude': 38.9518, 'longitude': -77.0203})

        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, 'Not Found', {}, None)
        with self.assertRaisesRegex(ValueError, 'not a US ZIP code'):
            crawl_feeds.lookup_zip('00000', missing)

    def test_keys_come_from_the_environment_or_the_keys_file(self):
        with tempfile.NamedTemporaryFile('w', suffix='.env') as keys:
            keys.write('OTHER=1\nWMATA_API_KEY="secret"\n')
            keys.flush()
            self.assertEqual(crawl_feeds.read_key('WMATA_API_KEY', keys.name), 'secret')
        self.assertIsNone(crawl_feeds.read_key('WMATA_API_KEY', '/nonexistent'))
        with self.assertRaisesRegex(ValueError, 'No WMATA_API_KEY'):
            crawl_feeds.TransitFeed(None, opener=Mock()).fetch()

    def test_alertdc_rows_skip_crime_alerts_and_old_news(self):
        page = '''<tr><td style="width: 10%;" class="head">10/1/2026 12:30 PM</td><td class="head"><b>
            <a href="/x/1">[AlertDC] Bridge Opening (October 1 11PM)</a></b><br />
            [AlertDC] The bridge opens tonight at 11PM. Expect delays. Plan ahead.</td></tr>
            <tr><td class="head">10/1/2026 12:00 PM</td><td class="head"><b><a href="/x/2">[AlertDC] Crime Alert 5th District</a></b><br />Lookout.</td></tr>
            <tr><td class="head">9/28/2026 9:00 AM</td><td class="head"><b><a href="/x/3">[AlertDC] Old</a></b><br />Old news.</td></tr>'''
        feed = crawl_feeds.AlertDcFeed(opener=lambda request, timeout: io.BytesIO(page.encode()),
                                       clock=lambda: NOW.timestamp())
        feed.refresh()
        self.assertEqual(feed.items(), [{'tag': 'ALERTDC', 'heading': '',
                                         'text': 'Bridge Opening (October 1 11PM): The bridge opens tonight at 11PM. Expect delays.',
                                         'id': 'alertdc:ce10327fb8', 'issued': '2026-10-01T12:30:00-04:00'}])

    def test_score_items_say_when_live_and_final(self):
        team = lambda name, score: {'id': '1', 'nickname': name, 'score': score}
        game = {'away': team('Bruins', '2'), 'home': team('Capitals', '3'), 'start_time': '2026-10-01T23:00Z',
                'broadcasts': [{'name': 'USA Net', 'market': 'national'}]}
        self.assertEqual(crawl_feeds.score_item('nhl', {**game, 'state': 'pre'}, NOW)['text'],
                         'Bruins at Capitals, 7 PM on USA Network')
        self.assertEqual(crawl_feeds.score_item('nhl', {**game, 'state': 'in', 'detail': '2nd 12:31'}, NOW)['text'],
                         'Bruins 2, Capitals 3 · 2nd 12:31')
        self.assertEqual(crawl_feeds.score_item('nhl', {**game, 'state': 'post', 'detail': 'Final/OT'}, NOW),
                         {'tag': 'NHL', 'heading': '', 'text': 'Final/OT: Bruins 2, Capitals 3'})

    def test_scores_follow_only_the_chosen_teams(self):
        scoreboard = Mock()
        scoreboard.games.return_value = [
            {'state': 'pre', 'away': {'id': '1', 'nickname': 'Bruins'}, 'home': {'id': '23', 'nickname': 'Capitals'},
             'start_time': '2026-10-01T23:00Z', 'broadcasts': []},
            {'state': 'in', 'away': {'id': '5', 'nickname': 'Flyers', 'score': '1'},
             'home': {'id': '6', 'nickname': 'Devils', 'score': '0'}, 'detail': '1st'}]
        feed = crawl_feeds.ScoresFeed(scoreboard, lambda: ['nhl:23'], clock=lambda: NOW.timestamp())
        feed.refresh()
        self.assertEqual([i['text'] for i in feed.items()], ['Bruins at Capitals, 7 PM'])
        scoreboard.games.assert_called_once_with('nhl', '2026-10-01')


class CrawlApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.master = MasterConfig(enabled=True, socket_path=Path(self.temp.name) / 'master.sock')
        self.desk = Mock()
        self.desk.status.return_value = {'context': 'program'}

    def handler(self, path, body=None, *, authorized=True):
        config = SimpleNamespace(master=self.master, server=SimpleNamespace(api_key='secret'))
        handler = object.__new__(handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                 crawl_desk=self.desk))
        handler.path = path
        handler._authorize = Mock(return_value=authorized)
        handler._body = Mock(return_value=body)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        handler._json = Mock()
        return handler

    def test_layers_rotation_and_dismissals(self):
        h = self.handler('/v1/crawl/override', {'text': 'Game 3 tonight', 'label': 'vv', 'minutes': 30}, authorized=False)
        h.do_POST()
        h._json.assert_not_called()
        h._authorize.return_value = True
        h.do_POST()
        view = h._json.call_args.args[1]
        override = view['settings']['override']
        self.assertEqual((override['text'], override['label']), ('Game 3 tonight', 'vv'))
        self.assertGreater(datetime.fromisoformat(override['until']), datetime.now(timezone.utc) + timedelta(minutes=29))
        self.assertEqual((view['master_error'], view['rotation'], set(view['segments'])),
                         ('Master worker is unavailable', {'context': 'program'}, set(crawl.SEGMENTS)))
        h = self.handler('/v1/crawl/important', {'text': 'Shelter in place', 'minutes': None})
        h.do_POST()
        self.assertIsNone(h._json.call_args.args[1]['settings']['important']['until'])
        h = self.handler('/v1/crawl/important', {'text': 'x', 'minutes': 0})
        h.do_POST()
        self.assertEqual(h._json.call_args.args[0], 400)
        h = self.handler('/v1/crawl/run', {'segment': 'scores'})
        h.do_POST()
        self.desk.run_now.assert_called_once_with('scores')
        h = self.handler('/v1/crawl/dismiss', {'source': 'nws', 'id': 'urn:1'})
        h.do_POST()
        self.assertEqual(h._json.call_args.args[1]['settings']['nws_dismissed'], ['urn:1'])
        h = self.handler('/v1/crawl', {'teams': ['nhl:23']})
        h.do_POST()
        self.assertEqual(h._json.call_args.args[1]['settings']['teams'], ['nhl:23'])

    def test_feed_options_look_up_the_zip_and_poke_the_feeds(self):
        self.desk.feeds = {'transit': Mock(), 'weather': Mock()}
        self.desk.feeds['transit'].routes.return_value = [{'id': 'D60', 'name': 'FRANKLIN SQ - SILVER SPG'}]
        h = self.handler('/v1/crawl/feeds', {'transit': {'routes': ['d60', 'D6X', 'D50']}})
        h.do_POST()
        self.assertEqual(h._json.call_args.args[1]['feeds']['transit']['routes'], ['D60', 'D6X', 'D50'])
        self.desk.feeds['transit'].poke.assert_called_once_with()
        place = {'place': 'Washington, DC', 'latitude': 38.9518, 'longitude': -77.0203}
        with unittest.mock.patch.object(crawl_feeds, 'lookup_zip', return_value=place) as lookup:
            h = self.handler('/v1/crawl/feeds', {'weather': {'zip': '20011'}})
            h.do_POST()
        lookup.assert_called_once_with('20011')
        weather = h._json.call_args.args[1]['feeds']['weather']
        self.assertEqual((weather['zip'], weather['place']), ('20011', 'Washington, DC'))
        self.assertEqual(h._json.call_args.args[1]['feeds']['transit']['routes'], ['D60', 'D6X', 'D50'])  # kept
        with unittest.mock.patch.object(crawl_feeds, 'lookup_zip', side_effect=ValueError('00000 is not a US ZIP code')):
            h = self.handler('/v1/crawl/feeds', {'weather': {'zip': '00000'}})
            h.do_POST()
        self.assertEqual(h._json.call_args.args[0], 400)
        h = self.handler('/v1/crawl/feeds', {'segments': {'weather': {'contexts': ['off_air']}}})
        h.do_POST()
        h = self.handler('/v1/crawl/feeds', {'segments': {'weather': {'new_now': True}}})
        h.do_POST()
        self.assertEqual(h._json.call_args.args[1]['feeds']['segments']['weather'],
                         {'new_now': True, 'repeat': True, 'contexts': ['off_air']})  # kept the contexts
        h = self.handler('/v1/crawl/feeds', {'weather': {'zip': ''}})
        h.do_POST()
        self.assertEqual(h._json.call_args.args[1]['feeds']['weather']['zip'], '')
        h = self.handler('/v1/crawl/bus-routes')
        h.do_GET()
        self.assertEqual(h._json.call_args.args[1], {'routes': [{'id': 'D60', 'name': 'FRANKLIN SQ - SILVER SPG'}]})

    def test_the_register_and_its_actions(self):
        self.desk.register.return_value = {'ready': True, 'items': []}
        h = self.handler('/v1/crawl/alerts')
        h.do_GET()
        self.assertEqual(h._json.call_args.args[1], {'ready': True, 'items': []})
        h = self.handler('/v1/crawl/alerts/nws%3Aurn%3Aoid%3A2.49.0.1', {'action': 'mute'})
        h.do_POST()
        self.desk.mute.assert_called_once_with('nws:urn:oid:2.49.0.1', True)
        h = self.handler('/v1/crawl/alerts/rail%3A7', {'action': 'air'})
        h.do_POST()
        self.desk.air.assert_called_once_with(['rail:7'])
        self.assertEqual(h._json.call_args.args[0], 202)
        for body in ({'action': 'pin'}, {}, {'action': 'air', 'also': 1}):
            h = self.handler('/v1/crawl/alerts/rail%3A7', body)
            h.do_POST()
            self.assertEqual(h._json.call_args.args[0], 400)

    def test_page_script_is_public(self):
        h = self.handler('/static/ui/crawl.js', authorized=False)
        h.do_GET()
        h.send_response.assert_called_with(200)
        self.assertIn(b'v1/crawl/alerts', h.wfile.getvalue())


if __name__ == '__main__':
    unittest.main()
