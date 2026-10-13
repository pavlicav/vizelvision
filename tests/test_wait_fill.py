"""The wait fill: ads over the station ID's held end card while the next source gets ready,
then the iris, or the join bumper and the take at its end (ad_break.py, master_worker.py,
source_coordinator.py). AdBreak's tests need GStreamer: run them with the system Python,
    /usr/bin/python3 -m unittest tests.test_wait_fill"""
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.my_ads import validate
from roku_stream.source_coordinator import SourceCoordinator
from tests import test_ident, test_promos
from tests.test_my_ads import GST, H, W, FakeReel, ad

if GST is not None:
    from roku_stream import ad_break

S = 1_000_000_000
ID = (None, 0, 7)       # the station ID's frames: no ad-mute tap, decoder 7
ROKU = (None, 0, 9)     # the next source's, after the take
JOIN = {'path': '/state/continuity/join-0123456789abcdef.mp4', 'seconds': 10.0}


def joiner(length=10.0):
    return FakeReel({'id': 'sports-join', 'name': 'We now join', 'duration': length}, int(length * S), 90)


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class FillTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        output = SimpleNamespace(gst=GST, width=W, height=H, audio_caps='audio/x-raw',
                                 video_caps=f'video/x-raw,format=I420,width={W},height={H},framerate=30/1')
        with patch.object(ad_break.AdBreak, '_run', lambda self: None):   # no helper thread: the test is the helper
            self.b = ad_break.AdBreak(output, self.dir.name, Path(self.dir.name) / 'plays.jsonl')
        self.b.configure(validate({'pip': {'enabled': True}, 'ads': [ad(1), ad(2)]}), {'mode': 'on'})
        self.live = GST.Buffer.new_wrapped(bytes((200,)) * (W * H * 3 // 2))

    def frame(self, t, route=ID):
        """The frame shown at t seconds (pts and due alike), from the ID unless route says."""
        out = self.b.picture(self.live, int(t * S), int(t * S), route)
        return None if out is None else out.extract_dup(0, 1)[0]

    def test_ads_fill_the_held_end_card_whole_and_never_a_long_one(self):
        self.b.cued = FakeReel(ad(1, duration=2.0), 2 * S, 50)
        self.b.fill_start(10 * S)
        self.assertIsNone(self.frame(9.9), 'before the end card froze: the ID itself')
        self.assertEqual(self.frame(10.0), 50, 'the ad, full frame: nothing in a corner over a held card')
        self.assertEqual(self.b.state, 'fill')
        self.b.cued = FakeReel(ad(2, duration=60.0), 60 * S, 70)
        self.assertIsNone(self.frame(12.0), 'a minute-long ad waits for a real break: the end card shows')
        self.assertEqual(self.b.cued.ad['id'], ad(2)['id'])
        row = self.b.log[-1]
        self.assertEqual((row['kind'], row['id'], row['complete'], row['wait']), ('ad', ad(1)['id'], True, True))

    def test_ready_lets_the_ad_play_out_then_the_id_irises_out(self):
        self.b.cued = FakeReel(ad(1, duration=2.0), 2 * S, 50)
        self.b.fill_start(10 * S)
        self.assertEqual(self.frame(10.5), 50)
        self.assertTrue(self.b.fill_finish(int(10.6 * S)))
        self.assertIsNone(self.b.fill_end(), 'planned on the next frame master releases')
        self.assertEqual(self.frame(10.6), 50)
        self.assertEqual(self.b.fill_end(), {'end': int(12.5 * S), 'take': False, 'fixed': True}, 'where the ad ends')
        self.b.cued = FakeReel(ad(2, duration=2.0), 2 * S, 60)
        self.assertEqual(self.frame(12.4), 50)
        self.assertIsNone(self.frame(12.5), 'the window closes: the iris (once the worker thaws the ID)')
        self.assertEqual((self.b.state, self.b.fill, self.b.cued.ad['id']), ('idle', None, ad(2)['id']))
        self.assertIsNone(self.b.fill_end(), 'the request is over')

    def test_a_game_joined_in_progress_gets_the_bumper_then_the_take(self):
        self.b.cued = FakeReel(ad(1, duration=2.0), 2 * S, 50)
        self.b.fill_start(10 * S)
        self.assertEqual(self.frame(10.0), 50)
        self.b.fill_finish(int(10.5 * S), JOIN)
        self.assertEqual(self.frame(10.5), 50)
        self.assertEqual(self.b.fill_end(), {'end': 22 * S, 'take': True, 'fixed': False}, 'the ad, then 10 s')
        self.b.cued_join = joiner()
        self.assertEqual(self.frame(12.0), 90, 'the bumper as the ad ends')
        self.assertEqual(self.b.fill_end(), {'end': 22 * S, 'take': True, 'fixed': True})
        self.assertEqual(self.frame(21.9), 90)
        self.assertEqual(self.frame(22.1), 16, 'a take a moment late finds black, not the end card')
        self.assertIsNone(self.frame(22.2, ROKU), 'the game')
        self.assertEqual(self.b.state, 'idle')
        self.assertEqual([(r['kind'], r['complete'], r['wait']) for r in self.b.log], [('ad', True, True), ('join', True, True)])

    def test_ready_before_the_fill_airs_plays_no_ad(self):
        self.b.cued = FakeReel(ad(1, duration=2.0), 2 * S, 50)
        self.b.fill_start(10 * S)
        self.b.fill_finish(int(10.2 * S))
        self.assertEqual(self.b.fill_end(), {'end': int(10.2 * S), 'take': False, 'fixed': True}, 'iris out now')
        self.assertIsNone(self.frame(10.0))
        self.assertIsNone(self.frame(10.3), 'the iris')
        self.assertEqual(self.b.cued.ad['id'], ad(1)['id'], 'the ad stays cued for a break')

    def test_ready_before_the_fill_airs_goes_straight_to_the_bumper(self):
        self.b.cued = FakeReel(ad(1, duration=2.0), 2 * S, 50)
        self.b.fill_start(10 * S)
        self.b.fill_finish(int(10.2 * S), JOIN)
        self.assertEqual(self.b.fill_end(), {'end': 20 * S, 'take': True, 'fixed': False})
        self.b.cued_join = joiner()
        self.assertEqual(self.frame(10.0), 90, 'in the end card\'s place')
        self.assertEqual(self.b.fill_end(), {'end': 20 * S, 'take': True, 'fixed': True})
        self.assertEqual(self.b.cued.ad['id'], ad(1)['id'])

    def test_a_bumper_not_decoded_in_time_moves_the_end(self):
        self.b.fill_start(10 * S)
        self.b.fill_finish(int(10.2 * S), JOIN)
        self.assertIsNone(self.frame(10.0), 'the end card while it decodes')
        self.assertEqual(self.b.fill_end(), {'end': 20 * S, 'take': True, 'fixed': False})
        self.b.cued_join = joiner()
        self.assertEqual(self.frame(10.5), 90)
        self.assertEqual(self.b.fill_end(), {'end': int(20.5 * S), 'take': True, 'fixed': True})

    def test_stop_cuts_the_fill(self):
        self.b.cued = FakeReel(ad(1, duration=30.0), 30 * S, 50)
        self.b.fill_start(10 * S)
        self.assertEqual(self.frame(10.0), 50)
        self.b.fill_stop(11 * S)
        self.assertFalse(self.b.fill_finish(11 * S), 'a stopped fill does not finish')
        self.assertIsNone(self.frame(11.0))
        self.assertEqual((self.b.state, self.b.log[-1]['complete']), ('idle', False))

    def test_the_fill_has_the_ad_s_sound(self):
        reel = FakeReel(ad(1, duration=30.0), 30 * S, 50)
        self.b.cued = reel
        self.b.fill_start(10 * S)
        self.assertIsNone(self.b.fill_sound(int(9.9 * S), int(9.9 * S), 960 * 8))
        self.frame(10.0)
        self.assertEqual(len(self.b.fill_sound(int(10.0 * S), int(10.0 * S), 960 * 8)), 960 * 8)
        self.assertEqual(reel.asked, [0])

    def test_a_muted_break_gives_way_to_the_fill(self):
        tap = SimpleNamespace(gain=lambda pts: 0.)
        self.b.cued = FakeReel(ad(1, duration=30.0), 30 * S, 50)
        self.assertEqual(self.b.picture(self.live, 5 * S, 5 * S, (tap, 0, 3)).extract_dup(0, 1)[0], 50)
        self.b.fill_start(10 * S)
        self.b.cued = FakeReel(ad(2, duration=2.0), 2 * S, 60)
        self.assertEqual(self.frame(10.0), 60)
        self.assertEqual([(r['kind'], r['complete']) for r in self.b.log], [('ad', False)])


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class EveryBreakTests(unittest.TestCase):
    """Promos every break (every 0): one opens each break, and the wait fill too, but never
    two in a row. Uses the promo break tests' set-up (imported as a module, not run here)."""
    setUp = test_promos.PromoBreakTests.setUp
    tearDown = test_promos.PromoBreakTests.tearDown
    configure = test_promos.PromoBreakTests.configure
    frame = test_promos.PromoBreakTests.frame

    def made(self, name):
        return test_promos.promos._manifest(test_promos.manifest(name, duration=5.0), Path(self.dir.name), name)

    def test_a_promo_opens_the_break_and_an_ad_follows_it(self):
        self.configure(every=0)
        self.b.last_promo = time.time() - 30
        self.b.cued, self.b.cued_promo = FakeReel(ad(1, duration=10.0), 10 * S, 50), FakeReel(self.made('legal'), S, 90)
        self.tap.mutes.append((S, 30 * S))
        self.assertEqual(self.frame(1.0), 90, 'every break opens with a promo, however recent the last')
        self.b.cued_promo = FakeReel(self.made('metro'), S, 95)
        self.assertEqual(self.frame(2.0), 50, 'then the ad, not a second promo')

    def test_the_wait_fill_opens_with_one_too(self):
        self.configure(every=0)
        self.b.last_promo = time.time() - 30
        self.b.cued, self.b.cued_promo = FakeReel(ad(1, duration=10.0), 10 * S, 50), FakeReel(self.made('legal'), S, 90)
        self.b.fill_start(10 * S)
        self.assertEqual(self.b.picture(self.live, 10 * S, 10 * S, ID).extract_dup(0, 1)[0], 90)
        self.b.cued_promo = FakeReel(self.made('metro'), S, 95)
        self.assertEqual(self.b.picture(self.live, 11 * S, 11 * S, ID).extract_dup(0, 1)[0], 50)

    def test_every_n_minutes_is_as_before(self):
        self.configure(every=15)
        self.b.last_promo = time.time() - 30
        self.b.cued, self.b.cued_promo = FakeReel(ad(1, duration=10.0), 10 * S, 50), FakeReel(self.made('legal'), S, 90)
        self.tap.mutes.append((S, 30 * S))
        self.assertEqual(self.frame(1.0), 50, 'a promo 30 s ago: not due')


class FakeBreaks:
    """ad_break.AdBreak as the worker sees it."""
    ads_on, promos_on = True, False

    def __init__(self):
        self.calls, self.report = [], None

    def fill_start(self, pts):
        self.calls.append(('start', pts))

    def fill_finish(self, pts, join=None):
        self.calls.append(('finish', pts, join))
        return True

    def fill_stop(self, pts):
        self.calls.append(('stop', pts))

    def fill_end(self):
        return self.report


class FillWorkerTests(unittest.TestCase):
    # The station ID tests' worker (imported as a module, so its tests are not run again here).
    setUp = test_ident.IdentWorkerTests.setUp
    cue_ident = test_ident.IdentWorkerTests.cue_ident
    program = test_ident.IdentWorkerTests.program
    air_ident_over_a_program = test_ident.IdentWorkerTests.air_ident_over_a_program

    def held(self):
        ident, decoder = self.air_ident_over_a_program()
        self.breaks = self.worker.output.ad_break = FakeBreaks()
        self.worker.output.running_time.return_value = 100 * S
        decoder.frozen_at = 99 * S
        return ident, decoder

    def test_ads_fill_the_hold_and_the_iris_follows_the_last_one(self):
        _, decoder = self.held()
        self.worker.submit('ident_hold', {'hold': True})
        self.assertGreater(self.worker.ident_hold_until - time.monotonic(), 200, 'ads make a long wait bearable')
        decoder.position = 27.95
        self.worker._tick()
        self.assertTrue(decoder.frozen)
        self.assertEqual(self.breaks.calls, [('start', 99 * S)])
        self.assertEqual(self.worker.status()['ident']['fill'], {'state': 'filling', 'take': False, 'fixed': False, 'ends_in': None})
        self.worker.submit('ident_hold', {'hold': False})
        self.worker._tick()
        self.assertEqual(self.breaks.calls[-1], ('finish', 100 * S, None))
        self.assertTrue(decoder.frozen, 'the ad on air plays out first')
        self.breaks.report = {'end': 105 * S, 'take': False, 'fixed': True}
        self.worker._tick()
        self.assertEqual((decoder.frozen, self.worker.status()['ident']['fill']['ends_in']), (True, 5.0))
        self.worker.output.running_time.return_value = 105 * S
        self.worker._tick()
        self.assertFalse(decoder.frozen, 'the ad has ended: the iris')
        self.assertIsNone(self.worker.status()['ident']['fill'], 'the take waits for the ID\'s tail, not a fill')

    def test_a_game_joined_in_progress_freezes_for_the_bumper_and_the_take_ends_it(self):
        ident, decoder = self.held()
        bumper = self.continuity / 'join-0123456789abcdef.mp4'
        bumper.write_bytes(b'bumper')
        self.worker.submit('ident_hold', {'hold': False, 'join': {'path': str(bumper), 'seconds': 10}})
        decoder.position = 27.95
        self.worker._tick()
        self.worker._tick()
        self.assertTrue(decoder.frozen, 'the end card holds for the bumper')
        self.assertEqual(self.breaks.calls, [('start', 99 * S), ('finish', 100 * S, {'path': str(bumper.resolve()), 'seconds': 10.0})])
        self.breaks.report = {'end': 110 * S, 'take': True, 'fixed': True}
        self.worker._tick()
        self.assertTrue(decoder.frozen, 'no iris: the take lands at the bumper\'s end')
        self.assertEqual(self.worker.status()['ident']['fill'], {'state': 'finishing', 'take': True, 'fixed': True, 'ends_in': 10.0})
        self.worker._drop(ident)
        self.assertEqual(self.breaks.calls[-1], ('stop', 100 * S))
        self.assertIsNone(self.worker.ident_join)

    def test_a_take_that_never_comes_lets_the_id_iris_out(self):
        _, decoder = self.held()
        bumper = self.continuity / 'join-0123456789abcdef.mp4'
        bumper.write_bytes(b'bumper')
        self.worker.submit('ident_hold', {'hold': False, 'join': {'path': str(bumper), 'seconds': 10}})
        decoder.position = 28.0
        self.worker._tick()
        self.worker._tick()
        self.breaks.report = {'end': 110 * S, 'take': True, 'fixed': True}
        self.worker.output.running_time.return_value = 116 * S
        self.worker._tick()
        self.assertFalse(decoder.frozen)
        self.assertEqual(self.breaks.calls[-1], ('stop', 116 * S))

    def test_a_bumper_comes_too_late_once_the_iris_has_begun(self):
        _, decoder = self.held()
        bumper = self.continuity / 'join-0123456789abcdef.mp4'
        bumper.write_bytes(b'bumper')
        self.worker.submit('ident_hold', {'hold': False, 'join': {'path': str(bumper), 'seconds': 10}})
        decoder.position = 28.6
        self.worker._tick()
        self.assertEqual((decoder.frozen, self.breaks.calls), (False, []))

    def test_a_held_fill_gives_up_at_its_limit(self):
        _, decoder = self.held()
        self.worker.submit('ident_hold', {'hold': True})
        decoder.position = 28.0
        self.worker._tick()
        self.worker.ident_hold_until = time.monotonic() - 1
        self.worker._tick()
        self.assertFalse(decoder.frozen)
        self.assertEqual(self.breaks.calls[-1], ('stop', 100 * S))

    def test_only_a_join_bumper_from_the_announcements_folder(self):
        self.held()
        elsewhere = Path(self.tmp.name) / 'join-0123456789abcdef.mp4'
        elsewhere.write_bytes(b'x')
        named = self.continuity / 'phillies.mp4'
        named.write_bytes(b'x')
        for join in ({'path': str(elsewhere), 'seconds': 10}, {'path': str(named), 'seconds': 10},
                     {'path': str(self.continuity / 'join-0123456789abcdef.mp4'), 'seconds': 10},
                     {'path': str(named), 'seconds': 99}):
            with self.assertRaises(ConfigError):
                self.worker.submit('ident_hold', {'hold': False, 'join': join})
        with self.assertRaises(ConfigError):
            self.worker.submit('ident_hold', {'hold': True, 'join': {'path': str(named), 'seconds': 10}})


class Scripted:
    """Master as the coordinator reads it: the states in turn (the last repeats)."""

    def __init__(self, states):
        self.states, self.calls = list(states), []

    def request(self, action='status', body=None):
        if action != 'status':
            self.calls.append((action, body))
            return {'accepted': True}
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def ident(position, duration, **state):
    return {'on_air': {'source_id': 'ident', 'media': {'position_seconds': position, 'duration_seconds': duration}},
            'ident': {'held': state.pop('held', False), 'fill': state.pop('fill', None)}}


class FillCoordinatorTests(unittest.TestCase):
    def coordinator(self, states):
        master = Scripted(states)
        return SourceCoordinator(SimpleNamespace(master=MasterConfig(enabled=True)), None, None, master=master), master

    def test_the_take_lands_at_the_join_bumper_s_end(self):
        fill = lambda **f: {'state': 'finishing', 'take': True, **f}
        coordinator, master = self.coordinator([ident(27.9, 60, held=True, fill=fill(fixed=False, ends_in=12.0)),
                                                ident(27.9, 60, held=True, fill=fill(fixed=False, ends_in=12.0)),
                                                ident(27.9, 60, held=True, fill=fill(fixed=True, ends_in=1.0)),
                                                ident(27.9, 60, held=True, fill=fill(fixed=True, ends_in=.2)),
                                                {'on_air': {'source_id': 'youtube-tv'}}])
        coordinator._after_station_id(join=JOIN)
        self.assertEqual(master.calls, [('ident_hold', {'hold': False, 'join': JOIN})])
        self.assertEqual(len(master.states), 1, 'it returned once the bumper was all but over')

    def test_the_take_waits_for_the_ad_then_the_iris(self):
        filling = {'state': 'finishing', 'take': False, 'fixed': True, 'ends_in': 20.0}
        coordinator, master = self.coordinator([ident(27.9, 30, held=True, fill=filling)] * 3
                                               + [ident(28.3, 30), ident(29.6, 30), {'on_air': None}])
        coordinator._after_station_id()
        self.assertEqual(master.calls, [('ident_hold', {'hold': False})])
        self.assertEqual(len(master.states), 1, 'at the tail, not before')

    def test_a_game_under_way_gets_its_bumper(self):
        coordinator, master = self.coordinator([ident(20.0, 60)])
        asked = []
        coordinator.joiner = SimpleNamespace(clip=lambda ref, timeout: asked.append(ref) or {'path': JOIN['path'], 'seconds': 10.0,
                                                                                         'line': 'We now join...'})
        item = SimpleNamespace(game={'league': 'mlb', 'game_pk': 849822, 'game_date': '2026-10-07'}, hold_end=None, target={})
        self.assertEqual(coordinator._join(item, {}, None), JOIN)
        self.assertEqual(asked, [{'league': 'mlb', 'game_pk': 849822, 'game_date': '2026-10-07'}])
        coordinator, _ = self.coordinator([ident(31.0, 60)])
        coordinator.joiner = SimpleNamespace(clip=lambda ref, timeout: self.fail('the Sports ID is already on'))
        self.assertIsNone(coordinator._join(item, {}, None))


if __name__ == '__main__':
    unittest.main()
