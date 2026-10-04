"""Back to YouTube TV: a program on air from the antenna in its place goes back once the Roku is ready.

On 2026-10-04 the Colts at Commanders game failed on YouTube TV's NFL Network at 12:11 and
feed recovery put it back on from FOX 5 over the antenna, which tunes in seconds. The
antenna's picture is worse (corrupt MPEG-2 frames that day), and the game stayed there:
nothing tried YouTube TV again while the antenna was going. Now the Roku is prepared beside
the antenna, which stays on air, and master cuts back to YouTube TV once it is ready.
"""
from datetime import timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from roku_stream.master import MasterStreamError
from roku_stream.scheduler import utc_now
from roku_stream.source_queue import HOLD_REASON, UPGRADE_ATTEMPTS, UPGRADE_LIMIT, SourceQueue

NFLN = {'source_id': 'youtube-tv', 'channel_id': 'NFL Network'}
YTTV = {**NFLN, 'antenna': False}
FOX5 = {'source_id': 'tv-thing-digital', 'channel_id': 'wttg_5_1'}
COLTS = {'league': 'nfl', 'game_pk': 401872965, 'game_date': '2026-10-04',
         'title': 'Indianapolis Colts at Washington Commanders'}


def soon(seconds):
    return (utc_now() + timedelta(seconds=seconds)).isoformat()


def plain(target):
    return {k: v for k, v in target.items() if k != 'antenna'}


def where(on_air):
    return {k: on_air.get(k) for k in ('source_id', 'channel_id')}


class FakeMaster:
    """Takes, early preparation on the Roku beside what is on air, and the cut back."""

    def __init__(self):
        self.on_air, self.failure, self.aired = None, None, []
        self.prepared, self.prerolls, self.fail_prerolls, self.takeover = None, [], 0, False

    def _air(self, target):
        self.on_air = {'id': uuid.uuid4().hex, **plain(target)}
        self.aired.append(dict(target))
        return {'on_air': self.on_air}

    def take(self, item):
        if self.takeover and item.target.get('source_id') == 'youtube-tv' and item.target.get('antenna') is not False:
            self.takeover = False  # YouTube TV was not ready by release: the antenna takes over.
            result = self._air(FOX5)
            return {**result, 'antenna': {'number': '5.1', 'name': 'WTTG', 'reason': 'YouTube TV could not be ready in time'}}
        return self._air(item.target)

    def preroll(self, item):
        if not item.id.startswith('upgrade:'):
            return 'prepared'  # An entry prepared ahead of its release, as usual.
        self.prerolls.append((dict(item.target), dict(self.on_air or {})))
        if self.fail_prerolls:
            self.fail_prerolls -= 1
            raise MasterStreamError('Roku playback was not verified')
        self.prepared = dict(item.target)
        return 'prepared'

    def upgrade(self, item):
        if self.prepared != item.target:
            raise MasterStreamError('YouTube TV is no longer prepared')
        self.prepared = None
        return self._air(item.target)

    def fail(self, error='Input audio/video stopped arriving'):
        self.failure = {'target': dict(self.on_air), 'error': error, 'was_on_air': True, 'at': time.time()}
        self.on_air = None


def alternates(target, game=None):
    if target.get('source_id') == 'youtube-tv':
        return {'antenna': dict(FOX5), 'roku': {**plain(target), 'antenna': False}}
    return {'antenna': dict(target), 'roku': {'source_id': 'youtube-tv', 'channel_id': 'FOX', 'antenna': False}}


@patch('roku_stream.source_queue.UPGRADE_SETTLE_SECONDS', .05)
@patch('roku_stream.source_queue.UPGRADE_RETRY_SECONDS', .05)
class BackToYouTubeTvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master = FakeMaster()
        self.game = {'finished': False, 'status': '9:04 - 4th'}
        self.ended = []
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', self.master.take, lambda *_: dict(self.game),
                                 poll_seconds=.01, hold_poll_seconds=.01, retry_seconds=.05, hold_lost_seconds=.05,
                                 on_air=lambda: self.master.on_air, input_failure=lambda: self.master.failure,
                                 on_hold_end=self.ended.append, preroll=self.master.preroll,
                                 ready=lambda target: False, upgrade=self.master.upgrade, alternates=alternates)
        self.addCleanup(self.queue.close)

    def wait(self, check, message=None):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(message or repr((self.master.aired, [(i.status, i.gate_detail) for i in self.queue.list()])))

    def scheduled(self, target=NFLN):
        self.queue.add_scheduled({'target': target, 'title': COLTS['title'], 'kind': 'game', 'game': COLTS,
                                  'run_at': soon(.02), 'skip_after': soon(3600),
                                  'key': f'{soon(0)}|game|colts|{target["channel_id"]}'})
        self.queue.resume()
        self.wait(lambda: len(self.master.aired) == 1)

    def held(self):
        self.queue.add_target(NFLN, 'now', hold_end={'game': dict(COLTS)})
        self.queue.resume()
        self.wait(lambda: self.queue.status()['hold'])

    def test_a_game_put_back_from_the_antenna_goes_back_to_youtube_tv_once_it_is_ready(self):
        self.scheduled()
        self.master.fail()
        self.wait(lambda: self.master.aired == [NFLN, FOX5, YTTV])
        # Prepared on the Roku while the antenna stayed on air.
        self.assertEqual([(t, where(o)) for t, o in self.master.prerolls], [(YTTV, FOX5)])
        self.assertEqual(self.queue.status()['upgrade']['state'], 'switched')
        self.assertIn('back on YouTube TV', self.queue.list()[0].gate_detail)
        # Watched on YouTube TV now: when that fails it goes back on, from the antenna first.
        self.master.fail()
        self.wait(lambda: len(self.master.aired) == 4)
        self.assertEqual(self.master.aired[3], FOX5)

    def test_a_held_game_goes_back_to_youtube_tv_and_keeps_its_hold(self):
        self.held()
        self.master.fail()
        self.wait(lambda: self.master.aired[-1:] == [FOX5])
        ended = len(self.ended)  # the take that dropped
        self.wait(lambda: self.master.aired == [NFLN, FOX5, YTTV])
        hold = self.queue.status()['hold']
        self.assertEqual((plain(hold['target']), hold['input_id'], hold['game']['game_pk']),
                         (NFLN, self.master.on_air['id'], COLTS['game_pk']))
        status = self.queue.status()
        self.assertEqual((status['paused'], status['pause_reason']), (True, HOLD_REASON))
        self.assertEqual(len(self.ended), ended, 'the hold carried on: nothing was queued to follow')
        self.master.fail()  # YouTube TV fails again: back on through the hold, from the antenna.
        self.wait(lambda: len(self.master.aired) == 4)
        self.assertEqual(self.master.aired[3], FOX5)

    def test_the_antenna_taking_over_at_release_gives_way_to_youtube_tv_once_it_is_ready(self):
        self.master.takeover = True
        self.scheduled()
        self.wait(lambda: self.master.aired == [FOX5, YTTV])

    def test_a_failed_preparation_leaves_the_antenna_on_and_is_tried_a_few_times(self):
        self.held()
        self.master.fail_prerolls = UPGRADE_ATTEMPTS
        self.master.fail()
        self.wait(lambda: len(self.master.prerolls) == UPGRADE_ATTEMPTS)
        time.sleep(.3)
        self.assertEqual(len(self.master.prerolls), UPGRADE_ATTEMPTS)
        self.assertEqual(self.master.aired, [NFLN, FOX5])
        note = self.queue.status()['upgrade']
        self.assertEqual((note['state'], note['retry']), ('failed', False))

    def test_not_in_a_games_closing_stretch(self):
        self.held()
        self.game['closing'] = True  # the last two minutes
        self.master.fail()
        self.wait(lambda: self.master.aired == [NFLN, FOX5])
        time.sleep(.3)
        self.assertEqual((self.master.prerolls, len(self.master.aired)), ([], 2))

    def test_youtube_tv_that_keeps_failing_is_left_on_the_antenna(self):
        self.held()
        for n in range(UPGRADE_LIMIT):
            self.master.fail()
            self.wait(lambda: len(self.master.aired) == 3 + 2 * n)
            self.assertEqual(self.master.aired[-1], YTTV)
        self.master.fail()
        self.wait(lambda: len(self.master.aired) == 2 + 2 * UPGRADE_LIMIT)
        time.sleep(.3)
        self.assertEqual(self.master.aired[-1], FOX5)
        self.assertEqual(len(self.master.prerolls), UPGRADE_LIMIT)

    def test_a_program_the_antenna_carries_as_itself_stays_there(self):
        self.scheduled(FOX5)
        time.sleep(.3)
        self.assertEqual((self.master.prerolls, self.master.aired), ([], [FOX5]))


if __name__ == '__main__':
    unittest.main()
