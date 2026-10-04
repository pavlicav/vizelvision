import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.errors import ConfigError, ControlBusyError
from roku_stream.master import MasterStreamError
from roku_stream.playout_queue import QueueItem
from roku_stream.scheduler import ScheduledJob, utc_now, parse_time
from roku_stream.source_queue import SourceQueue, SourceQueueItem, QueueSchedules, QueuePrograms

TARGET = {'source_id': 'tv-thing-digital', 'channel_id': 'wrc'}


class SourceQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.json'
        self.calls = []
        self.executor = lambda item: self.calls.append(item.target) or {'on_air': item.target}
        self.queue = SourceQueue(self.path, self.executor, lambda *_: {'finished': True}, poll_seconds=.01,
                                 final_buffer_seconds=0)
        self.addCleanup(self.queue.close)

    def add(self, **kwargs):
        return self.queue.add_target(TARGET, 'after_game',
            after_game={'game_pk': 123, 'game_date': '2026-09-12', 'title': 'Game'}, **kwargs)

    def wait(self, check, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.005)
        self.fail('Timed out: ' + repr(self.queue.status()))

    def test_starts_paused_then_executes_qualified_target(self):
        item = self.add()
        self.assertTrue(self.queue.status()['paused'])
        self.assertEqual(self.calls, [])
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertEqual(self.calls, [TARGET])
        self.assertEqual(self.queue.get(item.id).gate_status, 'taken')

    def test_ended_schedule_slots_are_skipped_while_paused(self):
        now = utc_now()
        def scheduled(key, start, end):
            return self.queue.add_scheduled({'key': key, 'target': TARGET, 'title': key,
                'run_at': start.isoformat(), 'skip_after': end.isoformat()})
        ended = scheduled('ended', now - timedelta(hours=2), now - timedelta(hours=1))
        current = scheduled('current', now - timedelta(hours=1), now + timedelta(hours=1))
        self.wait(lambda: self.queue.get(ended.id).status == 'skipped')
        self.assertTrue(self.queue.status()['paused'])
        self.assertEqual(self.queue.get(ended.id).gate_status, 'superseded')
        self.assertEqual(self.queue.get(current.id).status, 'queued')
        self.assertEqual(self.calls, [])

    def test_strict_head_prevents_due_tail_from_jumping(self):
        head = self.queue.add_target(TARGET, 'at_time', run_at=(utc_now()+timedelta(hours=1)).isoformat())
        tail = self.add()
        self.queue.resume()
        self.queue.move(tail.id, 'up')
        self.wait(lambda: self.queue.get(tail.id).status == 'succeeded')
        self.assertEqual(self.queue.get(head.id).status, 'queued')
        self.assertEqual(len(self.calls), 1)

    def test_now_goes_to_the_head_and_releases(self):
        later = self.queue.add_target(TARGET, 'at_time', run_at=(utc_now()+timedelta(hours=1)).isoformat())
        game = self.add()
        now = self.queue.add_target({'source_id': 'youtube-tv', 'channel_id': 'NBC'}, 'now')
        self.assertEqual((now.release_type, now.position), ('at_time', 0))
        self.assertLessEqual(parse_time(now.run_at), utc_now() + timedelta(seconds=2))
        self.assertEqual([i['id'] for i in self.queue.status()['items']], [now.id, later.id, game.id])
        self.queue.resume()
        self.wait(lambda: self.queue.get(now.id).status == 'succeeded', timeout=5)
        self.assertEqual(self.calls, [{'source_id': 'youtube-tv', 'channel_id': 'NBC'}])
        self.assertEqual(self.queue.get(later.id).status, 'queued')

    def test_now_refuses_a_program_that_has_not_started(self):
        upcoming = {'id': 'news', 'title': 'News', 'start': (utc_now()+timedelta(hours=1)).timestamp()}
        with self.assertRaisesRegex(ConfigError, 'not started'):
            self.queue.add_target(TARGET, 'now', program=upcoming)
        self.assertEqual(self.queue.list(), [])

    def test_failure_blocks_tail_until_retry_or_skip(self):
        self.queue.executor = Mock(side_effect=MasterStreamError('Bad source'))
        first, second = self.add(), self.add()
        self.queue.resume()
        self.wait(lambda: self.queue.get(first.id).status == 'blocked')
        self.assertEqual(self.queue.executor.call_count, 1)
        self.queue.executor = self.executor
        self.queue.action(first.id, 'retry')
        self.wait(lambda: self.queue.get(second.id).status == 'succeeded')
        self.assertEqual(len(self.calls), 2)

    def test_busy_retries_same_head_without_failing(self):
        self.queue.executor = Mock(side_effect=[ControlBusyError('busy'), {'on_air': TARGET}])
        first = self.add()
        self.queue.resume()
        self.wait(lambda: self.queue.get(first.id).status == 'succeeded')
        self.assertEqual(self.queue.executor.call_count, 2)

    def test_ended_program_blocks_until_explicit_channel_override(self):
        now = utc_now().timestamp()
        item = self.add(program={'id': 'event', 'title': 'News', 'start': now-100, 'end': now-1})
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).gate_status == 'missed')
        self.assertEqual(self.calls, [])
        self.queue.action(item.id, 'tune-anyway')
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertTrue(self.queue.get(item.id).tune_anyway)

    def test_late_program_revalidates_and_joins_live(self):
        now = utc_now().timestamp()
        self.queue.validate_program = Mock(return_value=None)
        item = self.add(program={'id': 'event', 'title': 'News', 'start': now-100, 'end': now+100})
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).status == 'succeeded')
        self.assertTrue(self.queue.get(item.id).late)
        self.queue.validate_program.assert_called_once()

    def test_changed_listing_blocks(self):
        self.queue.validate_program = lambda _: 'Listing changed'
        item = self.add(program={'id': 'event', 'start': 1, 'end': utc_now().timestamp()+100})
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).gate_status == 'changed')
        self.assertFalse(self.calls)

    def test_early_game_finish_cannot_take_a_future_program(self):
        now = utc_now().timestamp()
        item = self.add(program={'id': 'future', 'start': now+100, 'end': now+200})
        self.queue.resume()
        self.wait(lambda: self.queue.get(item.id).gate_detail == 'Waiting for the queued program to start')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.queue.get(item.id).status, 'queued')

    def test_pause_during_game_lookup_prevents_release(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def lookup(*_):
            entered.set()
            release.wait(2)
            return {'finished': True}
        self.queue.game_status = lookup
        item = self.add()
        self.queue.resume()
        self.assertTrue(entered.wait(1))
        self.queue.pause()
        release.set()
        self.assertEqual(self.queue.get(item.id).status, 'queued')
        self.assertFalse(self.calls)

    def test_reorder_during_game_lookup_rechecks_head(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def lookup(*_):
            entered.set()
            release.wait(2)
            return {'finished': True}
        self.queue.game_status = lookup
        first = self.add()
        second = self.queue.add_target(TARGET, 'at_time', run_at=(utc_now()+timedelta(hours=1)).isoformat())
        self.queue.resume()
        self.assertTrue(entered.wait(1))
        self.queue.move(second.id, 'up')
        release.set()
        self.queue.pause()
        self.assertEqual(self.queue.get(first.id).status, 'queued')
        self.assertFalse(self.calls)

    def test_pause_at_take_submission_boundary(self):
        item = self.add()
        with self.queue._condition:
            self.queue._items[item.id].status = 'running'
        with self.assertRaisesRegex(MasterStreamError, 'paused'):
            with self.queue.take_guard(item.id):
                self.fail('Must not submit a cut')

    def test_restart_blocks_ambiguous_running_and_stays_paused(self):
        self.queue.close()
        item = self.add()
        with self.queue._condition:
            self.queue._items[item.id].status = 'running'
            self.queue.paused = False
            self.queue._save_locked()
        reopened = SourceQueue(self.path, self.executor, lambda *_: {}, start_worker=False)
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.paused)
        self.assertEqual(reopened.get(item.id).gate_status, 'interrupted')
        self.assertEqual(reopened.get(item.id).status, 'blocked')

    def test_migrates_legacy_queue_and_schedules_once_preserving_order(self):
        self.queue.close()
        legacy = QueueItem('old', 0, 'NBC', 'after_game', utc_now().isoformat(), after_game_pk=1)
        self.path.write_text(json.dumps([asdict(legacy)]))
        jobs = self.path.with_name('jobs.json')
        job = ScheduledJob('job', 'ESPN', (utc_now()+timedelta(hours=1)).isoformat(), utc_now().isoformat())
        jobs.write_text(json.dumps([asdict(job)]))
        for _ in range(2):
            queue = SourceQueue(self.path, self.executor, lambda *_: {}, schedules_file=jobs, start_worker=False)
            self.assertEqual([i.channel for i in queue.list()], ['NBC', 'ESPN'])
            self.assertEqual(queue.list()[0].target['source_id'], 'youtube-tv')
            self.assertEqual(QueueSchedules(queue).get('job').channel, 'ESPN')
            queue.close()
        self.assertEqual(json.loads(self.path.with_suffix('.pre-master.json').read_text())[0]['id'], 'old')
        self.assertEqual(json.loads(jobs.read_text())[0]['status'], 'queued')

    def test_legacy_schedule_add_and_cancel_share_queue(self):
        schedules = QueueSchedules(self.queue)
        job = schedules.add('NBC', utc_now()+timedelta(hours=1))
        self.assertEqual(self.queue.list()[0].schedule_id, job.id)
        self.assertEqual(schedules.cancel(job.id).status, 'cancelled')
        self.assertEqual(self.queue.list()[0].status, 'skipped')


class ProgramTests(unittest.TestCase):
    def test_missing_or_changed_program_blocks_but_outage_retries(self):
        catalog = Mock()
        programs = QueuePrograms(catalog)
        item = SimpleNamespace(target=TARGET, program={'id': 'event', 'title': 'News', 'start': 100, 'end': 200})
        catalog.programs.return_value = {'channels': [{'id': 'wrc', 'now': {**item.program, 'end': 300}}]}
        self.assertIn('changed', programs.validate(item))
        catalog.programs.return_value = {'channels': [{'id': 'wrc', 'now': None}]}
        self.assertIn('no longer listed', programs.validate(item))
        catalog.programs.return_value = {'stale': True, 'channels': []}
        with self.assertRaisesRegex(Exception, 'Fresh listings'):
            programs.validate(item)


class QueueRemoveTests(unittest.TestCase):
    """The homepage's Remove and Clear queue."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.disarm = Mock()
        self.queue = SourceQueue(Path(self.tmp.name)/'q.json', Mock(), Mock(), start_worker=False, on_pause=self.disarm)
        self.addCleanup(self.queue.close)
        self.later = (utc_now()+timedelta(hours=1)).isoformat()

    def recording(self, name):
        return self.queue.add_target({'source_id': 'library', 'channel_id': f'tv-recordings/{name}.mp4'}, 'after_current')

    def test_remove_takes_your_entry_out_and_keeps_the_rest_in_order(self):
        first, second, third = (self.recording(n) for n in ('9-28', '9-29', '9-30'))
        removed = self.queue.remove_entry(second.id)
        self.assertEqual(removed.id, second.id)
        self.assertEqual([(i.id, i.position) for i in self.queue.list() if i.status == 'queued'],
                         [(first.id, 0), (third.id, 1)])
        self.assertIsNone(self.queue.get(second.id))
        self.disarm.assert_not_called()
        self.assertIsNone(self.queue.remove_entry('missing'))

    def test_removing_a_cued_recording_uncues_it(self):
        cued = self.recording('9-29')
        with self.queue._condition:
            self.queue._items[cued.id].prerolled_at = utc_now().isoformat()
            self.queue._items[cued.id].prepared_input_id = 'input-1'
        self.queue.remove_entry(cued.id)
        self.disarm.assert_called_once_with()

    def test_skipping_a_cued_recording_uncues_it_too(self):
        cued = self.recording('9-29')
        with self.queue._condition:
            self.queue._items[cued.id].prerolled_at = utc_now().isoformat()
        self.assertEqual(self.queue.action(cued.id, 'skip').status, 'skipped')
        self.disarm.assert_called_once_with()
        self.assertIsNone(self.queue.get(cued.id).prerolled_at)

    def test_a_scheduled_entry_stays_listed_so_the_schedule_does_not_add_it_back(self):
        news = self.queue.add_scheduled({'key': 'news-6pm', 'target': TARGET, 'title': 'News 10', 'run_at': self.later})
        self.queue.remove_entry(news.id)
        kept = self.queue.get(news.id)
        self.assertEqual((kept.status, kept.gate_detail, kept.schedule_key), ('skipped', 'Removed from Up next', 'news-6pm'))

    def test_blocked_entries_can_be_removed_but_not_running_ones(self):
        blocked, running = self.recording('a'), self.recording('b')
        with self.queue._condition:
            self.queue._items[blocked.id].status = 'blocked'
            self.queue._items[running.id].status = 'running'
        self.queue.remove_entry(blocked.id)
        self.assertIsNone(self.queue.get(blocked.id))
        with self.assertRaisesRegex(ConfigError, 'Only waiting or blocked'):
            self.queue.remove_entry(running.id)

    def test_clear_removes_what_you_added_and_leaves_the_schedule(self):
        reruns = [self.recording(n) for n in ('9-28', '9-29', '9-30')]
        news = self.queue.add_scheduled({'key': 'news-6pm', 'target': TARGET, 'title': 'News 10', 'run_at': self.later})
        self.assertEqual(self.queue.clear_added(), 3)
        self.assertEqual([i.id for i in self.queue.list() if i.status == 'queued'], [news.id])
        self.assertTrue(all(self.queue.get(r.id) is None for r in reruns))
        self.assertEqual(self.queue.clear_added(), 0)


class QueueApiTests(unittest.TestCase):
    def setUp(self):
        from roku_stream.api import handler_factory
        from roku_stream.config import MasterConfig
        from roku_stream.tv_control import target_from
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = SourceQueue(Path(self.tmp.name)/'q.json', Mock(), Mock(), start_worker=False)
        self.addCleanup(self.queue.close)
        self.master = Mock()
        self.master.request.return_value = {'on_air': TARGET}
        self.master.normalize_target.side_effect = lambda target: (target_from(target) if target['source_id'].startswith('tv-thing') else target, None)
        self.sources = Mock()
        self.sources.programs.return_value = {'channels': [{'id': 'wrc', 'now': {'id': 'news', 'title': 'News',
            'start': utc_now().timestamp()-100, 'end': utc_now().timestamp()+100}}]}
        self.controller = Mock()
        self.controller.on_air_source.return_value = {'type': 'baseball', 'game_pk': 123, 'game_date': '2026-09-12'}
        self.baseball = Mock()
        self.baseball.game.return_value = {'title': 'Game'}
        config = SimpleNamespace(master=MasterConfig(enabled=True), server=SimpleNamespace(api_key=None),
                                 resolve_channel=lambda s: (0, SimpleNamespace(name=s)))
        handler = handler_factory(config, self.controller, QueueSchedules(self.queue), self.baseball,
                                  self.queue, self.sources, self.master)
        self.handler = object.__new__(handler)
        self.handler._authorize = lambda: True
        self.handler.log_error = Mock()

    def request(self, path, body=None):
        result = {}
        self.handler.path = path
        self.handler._json = lambda status, payload: result.update(status=status, payload=payload)
        self.handler._body = lambda: body
        if body is None:
            self.handler.do_GET()
        else:
            self.handler.do_POST()
        return result

    def test_source_program_snapshot_and_estimated_end_are_server_resolved(self):
        result = self.request('/v1/queue', {'target': TARGET, 'release_type': 'scheduled_end',
            'after_program': {'target': TARGET, 'program_id': 'news'}})
        self.assertEqual(result['status'], 201, result)
        item = result['payload']
        self.assertEqual(item['after_program']['program']['title'], 'News')
        self.assertEqual(parse_time(item['run_at']).timestamp(), item['after_program']['program']['end'])
        self.master.request.assert_not_called()

    def test_legacy_after_game_and_schedule_routes_feed_master_queue(self):
        result = self.request('/v1/queue', {'channel': 'NBC', 'release_type': 'after_game'})
        self.assertEqual(result['status'], 201, result)
        self.assertEqual(result['payload']['target']['source_id'], 'youtube-tv')
        result = self.request('/v1/schedules', {'channel': 'NBC', 'run_at': (utc_now()+timedelta(hours=1)).isoformat()})
        self.assertEqual(result['status'], 201, result)
        self.assertEqual(len(self.queue.list()), 2)
        self.master.request.assert_not_called()

    def test_remove_and_clear_routes(self):
        first = self.request('/v1/queue', {'channel': 'NBC', 'release_type': 'after_game'})['payload']
        self.request('/v1/queue', {'channel': 'CBS', 'release_type': 'after_game'})
        result = {}
        self.handler.path = '/v1/queue/' + first['id']
        self.handler._json = lambda status, payload: result.update(status=status, payload=payload)
        self.handler.do_DELETE()
        self.assertEqual((result['status'], result['payload']['id']), (200, first['id']))
        cleared = self.request('/v1/queue/clear', {})
        self.assertEqual((cleared['status'], cleared['payload']['removed']), (200, 1))
        self.assertEqual(self.queue.list(), [])
        self.assertEqual(self.request('/v1/queue/clear', {'all': True})['status'], 400)

    def test_pause_resume_skip_and_distinct_master_on_air(self):
        item = self.request('/v1/queue', {'channel': 'NBC', 'release_type': 'after_game'})['payload']
        self.assertFalse(self.request('/v1/queue/resume', {})['payload']['paused'])
        self.assertTrue(self.request('/v1/queue/pause', {})['payload']['paused'])
        self.assertEqual(self.request('/v1/queue/'+item['id']+'/skip', {})['payload']['status'], 'skipped')
        status = self.request('/v1/queue')['payload']
        self.assertEqual(status['master_on_air'], TARGET)
        self.assertEqual(status['on_air']['type'], 'baseball')

    def test_play_now_until_a_time_ends_what_is_held_on_air(self):
        at = (utc_now() + timedelta(hours=1)).isoformat()
        self.master.queue_end.side_effect = lambda until, target: {'until': until['at']}
        self.queue.hold_for(TARGET, {'until': at})
        result = self.request('/v1/queue', {'target': TARGET, 'release_type': 'now', 'until': {'kind': 'time', 'at': at}})
        self.assertEqual(result['status'], 201, result)
        self.assertEqual(result['payload']['hold_end'], {'until': at})
        self.assertTrue(self.queue.status()['hold']['ending'])

    def test_add_to_queue_is_open_ended_and_leaves_what_is_on_air(self):
        self.queue.hold_for(TARGET, {'until': (utc_now() + timedelta(hours=1)).isoformat()})
        result = self.request('/v1/queue', {'target': TARGET, 'release_type': 'after_current'})
        self.assertEqual(result['status'], 201, result)
        self.assertIsNone(result['payload']['hold_end'])
        self.master.queue_end.assert_not_called()
        self.assertFalse(self.queue.status()['hold'].get('ending'))

    def test_play_now_resumes_a_paused_queue_only_when_asked(self):
        self.request('/v1/queue', {'target': TARGET, 'release_type': 'now'})
        self.assertTrue(self.queue.status()['paused'])
        self.request('/v1/queue', {'target': TARGET, 'release_type': 'now', 'resume': True})
        self.assertFalse(self.queue.status()['paused'])

    def test_bad_target_time_or_program_cannot_enqueue(self):
        for body in ({'target': 'bad'}, {'target': TARGET, 'release_type': 'at_time', 'run_at': 'tomorrow'},
                     {'target': TARGET, 'release_type': 'at_time', 'program_id': 'missing'}):
            self.assertEqual(self.request('/v1/queue', body)['status'], 400)
        self.assertEqual(self.queue.list(), [])
