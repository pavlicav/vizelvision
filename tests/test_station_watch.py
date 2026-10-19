"""The station watch tells someone when the station is stuck.

On 2026-10-08 a failed entry blocked Up next from Thursday night until Monday morning, and
nobody knew."""
import json
from pathlib import Path
import tempfile
import unittest

from roku_stream.station_watch import GRACE_SECONDS, StationWatch

TARGET = {'source_id': 'youtube-tv', 'channel_id': 'FOX'}


class StationWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / 'alerts.json'
        self.status = {'paused': False, 'pause_reason': None, 'hold': None, 'items': []}
        self.master = {'id': 'in-1', **TARGET}
        self.now_on = None
        self.clock = 0.
        self.sent = []
        self.watch = StationWatch(lambda: self.status, self.on_air, lambda: self.now_on, self.settings,
                                  clock=lambda: self.clock, send=lambda *args: self.sent.append(args))
        self.logs = self.enterContext(self.assertLogs('roku_stream.station_watch', 'WARNING'))

    def on_air(self):
        if isinstance(self.master, Exception):
            raise self.master
        return self.master

    def after(self, seconds):
        self.clock += seconds
        self.watch.check()

    def test_a_blocked_entry_is_reported_once_after_its_grace_then_cleared(self):
        self.settings.write_text(json.dumps({'ntfy': 'https://ntfy.sh/vv-test'}))
        self.status['items'] = [{'id': 'tnf', 'status': 'blocked', 'title': 'Buccaneers at Cowboys',
                                 'gate_detail': 'This Prime Video game has ended'}]
        self.after(0)
        self.after(GRACE_SECONDS['blocked'] - 1)
        self.assertEqual(self.sent, [])
        self.after(1)
        self.after(60)
        self.assertEqual(self.sent, [('https://ntfy.sh/vv-test',
                                      'Buccaneers at Cowboys is blocked: This Prime Video game has ended', False)])
        self.status['items'] = []
        self.after(60)
        self.assertEqual(self.sent[-1][2], True)
        self.assertEqual(self.watch.view(), {'problems': [], 'push': True})

    def test_a_paused_queue_counts_but_a_held_take_does_not(self):
        self.status.update(paused=True, pause_reason='On air until its end time')
        self.after(0)
        self.after(GRACE_SECONDS['paused'])
        self.assertEqual(self.watch.view()['problems'], [])
        self.status['pause_reason'] = 'Paused by operator'
        self.after(0)
        self.after(GRACE_SECONDS['paused'])
        self.assertIn('Station watch: Up next is paused (Paused by operator)', '\n'.join(self.logs.output))

    def test_the_test_card_counts_only_while_the_schedule_wants_a_program(self):
        self.master = None
        self.after(0)
        self.after(GRACE_SECONDS['test_card'])
        self.assertEqual(self.watch.view()['problems'], [], 'OFF AIR: the test card is right')
        self.now_on = {'title': 'The View'}
        self.after(0)
        self.after(GRACE_SECONDS['test_card'])
        self.assertIn('The test card is on, but The View should be', '\n'.join(self.logs.output))

    def test_master_not_answering_counts(self):
        self.master = OSError('Master worker is unavailable')
        self.after(0)
        self.after(GRACE_SECONDS['master'])
        self.assertEqual([p['key'] for p in self.watch.view()['problems']], ['master'])
        self.assertTrue(self.watch.view()['problems'][0]['reported'])

    def test_without_alerts_json_it_only_logs(self):
        self.status['items'] = [{'id': 'x', 'status': 'blocked', 'target': TARGET, 'error': {'message': 'Bad'}}]
        self.after(0)
        self.after(GRACE_SECONDS['blocked'])
        self.assertEqual(self.sent, [])
        self.assertIn('Station watch: FOX is blocked: Bad', '\n'.join(self.logs.output))
        self.assertFalse(self.watch.view()['push'])

    def test_a_failed_push_is_logged_not_raised(self):
        self.settings.write_text(json.dumps({'ntfy': 'https://ntfy.sh/vv-test'}))
        self.watch.send = lambda *_: (_ for _ in ()).throw(OSError('offline'))
        self.status.update(paused=True, pause_reason='Paused by operator')
        self.after(0)
        self.after(GRACE_SECONDS['paused'])
        self.assertIn('could not send its alert: offline', '\n'.join(self.logs.output))


if __name__ == '__main__':
    unittest.main()
