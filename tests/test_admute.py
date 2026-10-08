"""Ad mute: settings, the worker's link (gain, leases, overrides), the wire format,
and the policy's lean towards sound. Pure Python (runs under the worker's Python)."""
import json
import tempfile
import time
import unittest
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from admute.policy import Policy, PolicyConfig
from roku_stream import admute_protocol as proto
from roku_stream.admute_link import AdMuteLink, apply_gain, badge_words, _schedule, BADGE_SETTLE, LEASE_FADE, SECOND
from roku_stream.admute_settings import AdMuteSettings, DEFAULTS, lane_enabled, validate
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError
from roku_stream.master_worker import MasterWorker


class SettingsTests(unittest.TestCase):
    def test_defaults_ship_off(self):
        self.assertEqual(validate({})['mode'], 'off')
        self.assertEqual(validate({}), DEFAULTS)

    def test_strict_rejects_unknown_and_bad_values(self):
        for bad in ({'mode': 'loud'}, {'nope': 1}, {'lookahead': 0.2}, {'sources': {'tv_thing': 'yes'}},
                    {'exceptions': [''] }, {'sound': 'tone'}, {'sensitivity': True}, {'speech_model': 'large'},
                    {'lookahead': 8.5}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                validate(bad)

    def test_whisper_model(self):
        self.assertEqual(validate({})['speech_model'], 'base.en')
        self.assertEqual(validate({'speech_model': 'small.en'})['speech_model'], 'small.en')

    def test_lenient_ignores_newer_keys(self):
        self.assertEqual(validate({'mode': 'on', 'future': 1}, lenient=True)['mode'], 'on')

    def test_update_merges_and_saves(self):
        with tempfile.TemporaryDirectory() as d:
            store = AdMuteSettings(Path(d) / 'master.sock')
            store.update({'mode': 'on', 'sources': {'roku': False}})
            saved = json.loads((Path(d) / 'admute.json').read_text())
            self.assertEqual(saved['mode'], 'on')
            self.assertEqual(saved['sources'], {'tv_thing': True, 'roku': False})

    def test_lanes(self):
        s = validate({'mode': 'shadow', 'sources': {'roku': False}})
        self.assertTrue(lane_enabled(s, 'digital'))
        self.assertFalse(lane_enabled(s, 'roku'))
        self.assertFalse(lane_enabled(s, 'library'))
        self.assertFalse(lane_enabled(validate({'mode': 'off'}), 'digital'))


class ProtocolTests(unittest.TestCase):
    def test_round_trip_and_partial_frames(self):
        key = 'ab' * 16
        data = proto.frame(b'G', key, 123, b'x' * 10) + proto.json_frame(b'S', key, 0, {'lane': 'digital'})
        buf = bytearray(data[:20])
        self.assertEqual(list(proto.read_frames(buf)), [])
        buf += data[20:]
        frames = list(proto.read_frames(buf))
        self.assertEqual([(k, key_, p) for k, key_, p, _ in frames], [(b'G', key, 123), (b'S', key, 0)])
        self.assertEqual(json.loads(frames[1][3]), {'lane': 'digital'})
        self.assertEqual(buf, bytearray())


def link_with(events, lease, mode='on'):
    link = AdMuteLink('/nonexistent/admute.sock')
    link.inputs['k'] = Mock(events=[], lease=None, override=None, ack=0, last_pts=None)
    from roku_stream.admute_link import InputState
    link.inputs['k'] = InputState('k', {})
    link.set_mode(mode)
    link._message({'input': 'k', 'events': events, 'lease': lease, 'ack': 0})
    return link


class LinkTests(unittest.TestCase):
    MUTE = [[10 * SECOND, 0.0, 100_000_000], [20 * SECOND, 1.0, 200_000_000]]

    def test_schedule_ramps(self):
        ev = [(10, 0.0, 4), (20, 1.0, 10)]
        self.assertEqual(_schedule(ev, 5), 1.0)
        self.assertAlmostEqual(_schedule(ev, 12), 0.5)
        self.assertEqual(_schedule(ev, 19), 0.0)
        self.assertAlmostEqual(_schedule(ev, 25), 0.5)
        self.assertEqual(_schedule(ev, 40), 1.0)

    def test_follows_schedule_within_lease(self):
        link = link_with(self.MUTE, 30 * SECOND)
        self.assertEqual(link.gain('k', 15 * SECOND), 0.0)
        self.assertEqual(link.gain('k', 25 * SECOND), 1.0)

    def test_sound_comes_back_after_the_lease(self):
        link = link_with([[10 * SECOND, 0.0, 0]], 15 * SECOND)  # muted, then the sidecar went quiet
        self.assertEqual(link.gain('k', 14 * SECOND), 0.0)
        self.assertAlmostEqual(link.gain('k', 15 * SECOND + LEASE_FADE // 2), 0.5)
        self.assertEqual(link.gain('k', 16 * SECOND), 1.0)

    def test_shadow_and_unknown_inputs_never_touch_the_sound(self):
        self.assertEqual(link_with(self.MUTE, 30 * SECOND, mode='shadow').gain('k', 15 * SECOND), 1.0)
        self.assertEqual(link_with(self.MUTE, 30 * SECOND).gain('other', 15 * SECOND), 1.0)
        self.assertEqual(link_with(self.MUTE, None).gain('k', 15 * SECOND), 1.0)

    def test_the_reason_rides_along_without_changing_the_badge(self):
        link = link_with(self.MUTE, 30 * SECOND)
        link._message({'input': 'k', 'events': [], 'lease': None, 'badge': [1, None, 'AD', .97],
                       'why': ['95% · KNOWN AD', 'Braves at Dodgers · heard 3x', 'extra', 'more'], 'state': 'muted'})
        st = link.status('k')
        self.assertEqual(st['badge'], [1, None, 'AD', .97], 'the four items every worker unpacks')
        self.assertEqual(st['why'], ['95% · KNOWN AD', 'Braves at Dodgers · heard 3x'])
        link._message({'input': 'k', 'events': [], 'lease': None, 'badge': None, 'why': 'not a list', 'state': 'listening'})
        self.assertIsNone(link.status('k')['why'])

    def test_words_wait_for_live_captions_while_the_sidecar_transcribes(self):
        link = link_with(self.MUTE, 30 * SECOND)
        base = {'input': 'k', 'events': [], 'lease': None, 'badge': None, 'state': 'listening'}
        self.assertIsNone(link.take_words('k'), 'an older sidecar sends no words: captions transcribe')
        link._message({**base, 'speech': True, 'words': [[SECOND, 2 * SECOND, 'hello'], [3, 2, 'backwards'],
                                                          ['x', 1, 'bad'], [4 * SECOND, 5 * SECOND, 'there']]})
        self.assertEqual(link.take_words('k'), [(SECOND, 2 * SECOND, 'hello'), (4 * SECOND, 5 * SECOND, 'there')])
        self.assertEqual(link.take_words('k'), [], 'each word once')
        self.assertIsNone(link.take_words('other'))
        link._message({**base, 'speech': False})
        self.assertIsNone(link.take_words('k'), 'Whisper off or down in the sidecar')
        link._message({**base, 'speech': True})
        link.inputs['k'].updated -= 5
        self.assertIsNone(link.take_words('k'), 'the sidecar went quiet')

    def test_the_badge_says_not_muted_when_the_sound_is_up(self):
        status = {'badge': [10 * SECOND, None, 'AD', .97], 'why': ['100% · PICTURE', 'no station or score bug']}
        on = {'mode': 'on', 'badge': 'always'}
        late = 10 * SECOND + BADGE_SETTLE
        self.assertEqual(badge_words(status, on, late, 0.0), ('AD', 'MUTED'))
        self.assertEqual(badge_words(status, on, late, 1.0), ('AD', 'NOT MUTED'), 'lease lapsed: the sound is up')
        self.assertEqual(badge_words(status, on, 10 * SECOND, 1.0), ('AD', 'MUTED'), 'still fading down')
        self.assertIsNone(badge_words(status, on, 9 * SECOND, 1.0), 'before the call')
        self.assertEqual(badge_words(status, {**on, 'diagnostic': True}, late, 1.0),
                         ('AD', 'NOT MUTED · 100% · PICTURE\nno station or score bug'))
        self.assertEqual(badge_words(status, {**on, 'diagnostic': True}, late, 0.0),
                         ('AD', '100% · PICTURE\nno station or score bug'))
        shadow = {'mode': 'shadow', 'badge': 'shadow'}
        self.assertEqual(badge_words(status, shadow, late, 1.0), ('AD', 'SHADOW · 97%'), 'shadow never mutes')
        self.assertIsNone(badge_words(status, {'mode': 'off', 'badge': 'always'}, late, 1.0))
        self.assertIsNone(badge_words({'badge': [1, 5, 'AD', .9]}, on, 5, 1.0), 'ended')

    def test_a_two_line_diagnostic_badge_is_taller(self):
        try:
            from roku_stream.admute_badge import Plate
            from roku_stream.master_media import _gst
        except Exception as exc:   # no GStreamer here
            self.skipTest(str(exc))
        gst = _gst()
        one = Plate(gst, 'AD', 'MUTED', 120)
        two = Plate(gst, 'AD', '95% · KNOWN AD\nBraves at Dodgers · heard 3x', 120)
        self.assertEqual(one.height, 120)
        self.assertGreater(two.height, one.height)
        self.assertGreater(two.width, one.width)

    def test_new_words_on_a_showing_badge_do_not_fade_it_in_again(self):
        try:
            from roku_stream.admute_badge import AdBadge
        except Exception as exc:   # no GStreamer here
            self.skipTest(str(exc))
        badge = AdBadge.__new__(AdBadge)
        badge.lock, badge.intervals, badge.size = __import__('threading').Lock(), [], 120
        badge.plates = {('AD?', 'a'): 'plate-a', ('AD', 'b'): 'plate-b', ('AD', 'c'): 'plate-c'}
        badge._block = lambda block: None
        badge.show([(10, None, 'AD?', 'a')])
        badge.show([(25, None, 'AD', 'b')])                 # confirmed: same badge, new words
        self.assertEqual(badge.intervals, [(10, None, 'plate-b')])
        badge.show([(40, 50, 'AD', 'b')])                   # ending: its own fade-out
        self.assertEqual(badge.intervals, [(40, 50, 'plate-b')])
        badge.show([])
        badge.show([(60, None, 'AD', 'c')])                 # a new mute fades in
        self.assertEqual(badge.intervals, [(60, None, 'plate-c')])

    def test_override_wins_until_acknowledged(self):
        link = link_with([[10 * SECOND, 0.0, 0]], 60 * SECOND)
        link.gain('k', 12 * SECOND)                                 # programme heard at 12 s
        link.inputs['k'].info = {}
        self.assertTrue(link.override('k', 'unmute'))
        self.assertEqual(link.gain('k', 14 * SECOND), 1.0)         # a stale schedule cannot re-mute
        link._message({'input': 'k', 'events': [[10 * SECOND, 0.0, 0]], 'lease': 60 * SECOND, 'ack': 0})
        self.assertEqual(link.gain('k', 14 * SECOND), 1.0)
        link._message({'input': 'k', 'events': [], 'lease': 60 * SECOND, 'ack': 1})
        self.assertEqual(link.gain('k', 14 * SECOND), 1.0)
        self.assertTrue(link.override('k', 'mute'))
        self.assertEqual(link.gain('k', 20 * SECOND), 0.0)
        self.assertFalse(link.override('missing', 'mute'))

    def test_apply_gain(self):
        data = array('f', [0.5, -0.5] * 4800).tobytes()          # 100 ms of stereo
        self.assertIsNone(apply_gain(data, 0, 48000, 2, lambda p: 1.0))
        self.assertEqual(apply_gain(data, 0, 48000, 2, lambda p: 0.0), bytes(len(data)))
        out = array('f')
        out.frombytes(apply_gain(data, 0, 48000, 2, lambda p: min(1.0, p / (100 * 1_000_000))))
        self.assertAlmostEqual(out[0], 0.0, places=3)
        self.assertAlmostEqual(out[4800], 0.25, places=2)         # halfway: gain .5 of 0.5
        self.assertAlmostEqual(out[4801], -0.25, places=2)


class Seg:
    def __init__(self, start, end, p, seam=None, post_z=None, overlay=None):
        self.start, self.end, self.p_ad, self.seam, self.post_z = start, end, p, seam, post_z
        self.overlay = overlay


def run(policy, segs, lookahead=3.0):
    for s in segs:
        policy.step([s], s.end + lookahead)
    return policy


def run_seen(policy, segs, lookahead=3.0):
    """As live: each piece airs with the detector's view of the pieces after it, up to the edge."""
    for i, s in enumerate(segs):
        edge = s.end + lookahead
        policy.step([s], edge, ahead=[r for r in segs[i + 1:] if r.start < edge])
    return policy


def secs(a, b, p):
    return [Seg(t, t + 1, p) for t in range(a, b)]


class PolicyTests(unittest.TestCase):
    def test_mutes_at_a_seam_and_unmutes_quickly(self):
        p = run(Policy(PolicyConfig()), [Seg(100, 101, .1), Seg(101, 102, .99, 'black'), Seg(102, 103, .999),
                                         Seg(103, 104, .3)])
        self.assertEqual([(s.start, s.end, s.end_reason) for s in p.spans], [(101, 103, 'show')])

    def test_never_mutes_during_grace(self):
        p = run(Policy(PolicyConfig()), [Seg(5, 6, .999, 'black')])
        self.assertFalse(p.spans or p.current)

    def test_mutes_before_the_programme_memory_exists(self):
        # No warm-up (2026-10-03): a sure break right after the grace is muted.
        p = run(Policy(PolicyConfig()), [Seg(30, 31, .999, 'black'), Seg(31, 32, .999), Seg(32, 33, .1)])
        self.assertEqual([(s.start, s.end_reason) for s in p.spans], [(30, 'show')])

    def test_unconfirmed_mute_is_retracted(self):
        segs = [Seg(100, 101, .95, 'black')] + [Seg(t, t + 1, .95) for t in range(101, 115)]
        p = run(Policy(PolicyConfig()), segs)
        self.assertEqual(p.spans[0].end_reason, 'retracted')
        self.assertIsNone(p.current)                       # and it does not come straight back

    def test_after_an_unmute_only_a_black_seam_mutes_again(self):
        segs = [Seg(100, 101, .999, 'black'), Seg(101, 102, .1),
                Seg(102, 103, .999, 'silence'), Seg(103, 104, .999), Seg(104, 105, .999, 'black')]
        p = run(Policy(PolicyConfig()), segs)
        self.assertEqual(p.current.start, 104)

    def test_sports_feed_vetoes_and_ends_mutes(self):
        live = lambda t: 'live' if t >= 110 else 'break'
        # A detector still sure of an ad holds the feed's word (YouTube TV runs behind it), at most gate_hold.
        p = run(Policy(PolicyConfig(), gate=live), [Seg(100, 101, .999, 'black'), Seg(110, 111, .999), Seg(115, 116, .5)])
        self.assertEqual((p.spans[0].end, p.spans[0].end_reason), (115, 'gated'))
        p = run(Policy(PolicyConfig(), gate=live), [Seg(100, 101, .999, 'black')] + secs(110, 140, .999))
        self.assertEqual((p.spans[0].end, p.spans[0].end_reason), (130, 'gated'))
        p = run(Policy(PolicyConfig(), gate=lambda t: 'live'), [Seg(100, 101, .999, 'black')])
        self.assertFalse(p.spans or p.current)

    def test_long_sports_break_returns_at_an_ambiguous_seam(self):
        gate = lambda t: 'break'
        segs = [Seg(100, 101, .999, 'black'), Seg(205, 206, 1.0, 'black', post_z=8.0),
                Seg(221, 222, 1.0, 'black', post_z=1.5),     # 121 s in: a promo (FS1's breaks run 121-135 s)
                Seg(241, 242, 1.0, 'black', post_z=1.5)]
        p = run(Policy(PolicyConfig(), gate=gate), segs)
        self.assertEqual((p.spans[0].start, p.spans[0].end), (100, 241))

    def test_a_dip_the_lookahead_disagrees_with_keeps_the_mute(self):
        segs = [Seg(100, 101, .999, 'black')] + secs(101, 104, .999) + [Seg(104, 105, .3)] + secs(105, 110, .99) + secs(110, 115, .1)
        p = run_seen(Policy(PolicyConfig()), segs)
        self.assertEqual([(s.start, s.end, s.end_reason) for s in p.spans], [(100, 110, 'show')])

    def test_a_flash_does_not_start_a_mute(self):
        p = run_seen(Policy(PolicyConfig()), [Seg(100, 101, .95, 'black')] + secs(101, 106, .2))
        self.assertFalse(p.spans or p.current)

    def test_early_in_an_inning_break_only_clearly_the_show_ends_a_mute(self):
        gate = lambda t: 'break'
        segs = ([Seg(100, 101, .999, 'black')] + secs(101, 130, .999)
                + [Seg(130, 131, .2, 'black', post_z=-.8)] + secs(131, 140, .2)       # a game-looking spot
                + [Seg(140, 141, .999, 'black')] + secs(141, 150, .999)
                + [Seg(150, 151, .05, 'black', post_z=-3.5)] + secs(151, 160, .05))   # the game
        p = run_seen(Policy(PolicyConfig(), gate=gate), segs)
        self.assertEqual([(s.start, s.end, s.end_reason) for s in p.spans], [(100, 150, 'show')])

    def test_late_in_an_inning_break_the_detector_is_trusted_again(self):
        gate = lambda t: 'break'
        segs = [Seg(100, 101, .999, 'black')] + secs(101, 235, .999) + secs(235, 245, .1)
        p = run_seen(Policy(PolicyConfig(), gate=gate), segs)
        self.assertEqual([(s.start, s.end, s.end_reason) for s in p.spans], [(100, 235, 'show')])

    def test_a_mute_may_start_at_a_cut_without_black(self):
        # TBS on YouTube TV cuts straight into ads: a hard cut is a place to start.
        segs = [Seg(100, 101, .1), Seg(101, 102, .99, 'cut', post_z=3.0), Seg(102, 103, .999), Seg(103, 104, .3)]
        self.assertEqual([s.start for s in run(Policy(PolicyConfig(open_at='seam')), segs).spans], [101])
        self.assertEqual(run(Policy(PolicyConfig(open_at='black')), segs).spans, [], 'black only: as before 10/3')
        self.assertEqual(run(Policy(PolicyConfig(open_at='seam')), [Seg(101, 102, .99, 'silence')]).spans, [],
                         'not at silence alone')
        segs[1].post_z = 1.0
        self.assertEqual(run(Policy(PolicyConfig(open_at='seam')), segs).spans, [],
                         'nor at a camera cut that is only a bit ad-like after it')

    def test_after_an_unmute_a_cut_rearms_it(self):
        # The 14:48 TBS break: the sound came back mid-break, and the next ads began without black.
        segs = [Seg(100, 101, .999, 'black'), Seg(101, 102, .2), Seg(102, 103, .999), Seg(103, 104, .999, 'cut', post_z=3.0),
                Seg(104, 105, .999)]
        p = run(Policy(PolicyConfig(open_at='seam', rearm_gap=0.0)), segs)
        self.assertEqual(p.current.start, 103, 'at the cut, not the dip after the unmute')
        p = run(Policy(PolicyConfig(open_at='seam', rearm=('black',))), segs)
        self.assertIsNone(p.current, 'black only: stayed audible through the rest of the break')
        p = run(Policy(PolicyConfig(open_at='seam', rearm_gap=10.0)), segs)
        self.assertIsNone(p.current, 'but not at a cut moments after the sound came back: the game may open with a sponsor')
        p = run(Policy(PolicyConfig(open_at='seam', rearm_gap=10.0)), segs[:3] + secs(103, 120, .999)
                + [Seg(120, 121, .999, 'cut', post_z=3.0)])
        self.assertEqual(p.current.start, 120)

    def test_overrides(self):
        p = run(Policy(PolicyConfig()), [Seg(100, 101, .999, 'black')])
        p.override_unmute(102)
        run(p, [Seg(103, 104, .999, 'black')])
        self.assertIsNone(p.current)                       # suppressed until a show stretch
        p.override_mute(110)
        run(p, [Seg(111, 112, .1), Seg(112, 113, .2, 'black')] + secs(113, 140, .2))
        self.assertTrue(p.muted)                           # locked: at least 30 s
        run(p, [Seg(140, 141, .2)])
        self.assertEqual((p.spans[-1].end, p.spans[-1].end_reason), (140, 'show'))   # the black frame during the lock counts

    def test_its_an_ad_locks_for_thirty_seconds(self):
        p = Policy(PolicyConfig())
        p.override_mute(200)
        run_seen(p, [Seg(200, 201, .05, 'black', post_z=-4)] + secs(201, 205, .05) + [Seg(205, 206, .05, 'cut')]
                 + secs(206, 230, .05))
        self.assertTrue(p.muted)                           # the detector is sure it's the show: still quiet
        # A seam into show, then an ad-like stretch, then no seam: it holds on after the lock.
        p = Policy(PolicyConfig())
        p.override_mute(200)
        run(p, [Seg(202, 203, .1, 'black')] + secs(203, 206, .99) + secs(206, 235, .1))
        self.assertTrue(p.muted)
        run(p, [Seg(235, 236, .1, 'black')])
        self.assertEqual(p.spans[-1].end_reason, 'show')

    def test_its_an_ad_is_not_ended_by_a_cut(self):
        # 2026-10-07, WJLA's noon news: the detector called a long local ad the programme (its
        # phone-number band read as the station's bug), and each press held only to the next cut.
        p = Policy(PolicyConfig())
        p.override_mute(300)
        segs = []
        for t in range(300, 400, 5):                       # an ad cutting every 5 s, read as the show
            segs += [Seg(t, t + 1, .02, 'cut', post_z=-4)] + secs(t + 1, t + 5, .02)
        run(p, segs)
        self.assertTrue(p.muted, 'cuts never end it')
        run(p, [Seg(400, 401, .02, 'black', post_z=-4)])
        self.assertEqual((p.spans[-1].end, p.spans[-1].end_reason), (400, 'show'), 'the black frame into the programme does')
        # A trusted score bug back ends it too: the game is on again.
        p = Policy(PolicyConfig())
        p.override_mute(300)
        run(p, secs(300, 340, .02) + [Seg(340, 341, .02, overlay='score')])
        self.assertEqual(p.spans[-1].end, 340)
        # "It's the show" still ends it at once.
        p = Policy(PolicyConfig())
        p.override_mute(200)
        p.override_unmute(203)
        self.assertEqual((p.spans[-1].end, p.spans[-1].end_reason), (203, 'override'))


class WorkerAdMuteTests(unittest.TestCase):
    def setUp(self):
        config = SimpleNamespace(master=MasterConfig(enabled=True), tv_thing=TvThingConfig(enabled=True))
        self.worker = MasterWorker(config, tv=Mock(), status_reader=lambda: {"ready": True})
        self.worker.admute = Mock()

    def test_override_needs_an_analysed_input_on_air(self):
        self.assertFalse(self.worker.submit('admute', {'action': 'unmute'})['accepted'])
        self.worker.inputs['k'] = {'tap': object()}
        self.worker.active = 'k'
        self.worker.admute.override.return_value = True
        self.assertTrue(self.worker.submit('admute', {'action': 'unmute'})['accepted'])
        self.worker.admute.override.assert_called_once_with('k', 'unmute')
        with self.assertRaises(ConfigError):
            self.worker.submit('admute', {'action': 'louder'})


if __name__ == '__main__':
    unittest.main()
