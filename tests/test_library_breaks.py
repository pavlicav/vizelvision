"""A show's ad breaks: finding them (library_breaks.py), scanning only when asked and keeping
what was found (library.py), the break of a set length (ad_break.py), and the worker stopping
the file at each one (master_worker.py). AdBreak's tests need GStreamer: run them with the
system Python,
    /usr/bin/python3 -m unittest tests.test_library_breaks"""
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from roku_stream import library_breaks as lb, master_worker
from roku_stream.config import LibraryConfig, LibraryRoot, MasterConfig, TvThingConfig, _library
from roku_stream.errors import ConfigError
from roku_stream.library import FileLease, MediaLibrary, cached_breaks, library_target
from roku_stream.master_worker import MasterWorker
from roku_stream.my_ads import validate
from tests.test_my_ads import GST, H, W, FakeReel, ad

if GST is not None:
    from roku_stream import ad_break

S = 1_000_000_000
PLAYABLE = {'probe': 'ok', 'playable': True, 'reason': None, 'duration': 1320.0}


def fade(at, black=.2, silence=.6):
    return {'black': (at, at + black), 'silence': (at - .1, at - .1 + silence)}


class ChooseTests(unittest.TestCase):
    def found(self, *fades):
        return lb.candidates([f['black'] for f in fades], [f['silence'] for f in fades])

    def test_the_first_fade_of_each_transition_three_in_a_half_hour(self):
        # How It's Made S21E02 as scanned: the intro's two fades, then each act break's fade,
        # the return bumper's and the next product's title, 20-25 s apart.
        found = self.found(*map(fade, (52.1, 72.0, 348.2, 373.2, 660.3, 682.1, 707.3, 995.3, 1015.0)))
        self.assertEqual([round(b['at']) for b in lb.choose(found, 1331.5)], [348, 660, 995])

    def test_slugs_are_the_breaks_exactly_and_play_on_past_their_black(self):
        found = self.found(fade(52.5), fade(347.6, 5.74, 5.87), fade(358.4), fade(661.5, 5.77, 5.86),
                           fade(959.5, 5.77, 5.84), fade(970.2))
        breaks = lb.choose(found, 1277.7)
        self.assertEqual([b['kind'] for b in breaks], ['slug'] * 3)
        self.assertAlmostEqual(breaks[0]['resume'], 347.6 + 5.74 - lb.RESUME_BEFORE, places=2)
        self.assertLess(breaks[0]['at'], 348)

    def test_never_in_the_open_or_the_credits_and_never_close_together(self):
        found = self.found(fade(30), fade(300), fade(380), fade(1290))
        self.assertEqual([round(b['at']) for b in lb.choose(found, 1320)], [300])

    def test_a_sitcoms_long_fades_after_its_cold_open_and_before_its_tag(self):
        # Seinfeld S03E01 as scanned (a DVD rip): 2-3 s of black and silence at the very
        # start, after the stand-up, mid-episode, before the closing stand-up, and at the end.
        found = self.found(fade(0., 2.76, 2.14), fade(47.4, 2.92, 1.44), fade(922.3, 2.32, 1.88),
                           fade(1250.9, 2.72, 1.25), fade(1292.4, 2., 2.52))
        breaks = lb.choose(found, 1294.4)
        self.assertEqual([round(b['at']) for b in breaks], [48, 922, 1251])
        self.assertEqual({b['kind'] for b in breaks}, {'fade'}, 'under SLUG: fades, so one 3 s black never leaves slugs alone')
        # A title's dip in the open is a fraction of a second (How It's Made's): still not a break.
        short = self.found(fade(52.1), fade(72.0), fade(348.2), fade(660.3))
        self.assertEqual([round(b['at']) for b in lb.choose(short, 1331.5)], [348, 660])

    def test_more_transitions_than_breaks_takes_those_nearest_even_spacing(self):
        found = self.found(*map(fade, (200, 330, 500, 650, 800, 990, 1150)))
        self.assertEqual([round(b['at']) for b in lb.choose(found, 1320)], [330, 650, 990])

    def test_black_and_silence_a_moment_apart_still_count(self):
        found = lb.candidates([(986.92, 987.36)], [(987.33, 988.0)])
        self.assertEqual(len(found), 1)
        self.assertEqual(lb.candidates([(100., 100.2)], [(101., 102.)]), [], 'a cut with the sound running on')

    def test_detect_reads_ffmpeg_and_looks_only_around_the_quiet(self):
        calls = []

        def runner(args, **_):
            calls.append(args)
            if args[0] == 'ffprobe':
                streams = [{'index': 0, 'codec_type': 'video', 'disposition': {}},
                           {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'bul'}},
                           {'index': 2, 'codec_type': 'audio', 'tags': {'language': 'eng'}}]
                return SimpleNamespace(returncode=0, stdout=json.dumps({'streams': streams}).encode(), stderr=b'')
            if '-vn' in args:
                return SimpleNamespace(returncode=0, stdout=b'', stderr=(
                    b'[silencedetect] silence_start: 348.1\n[silencedetect] silence_end: 348.8 | silence_duration: 0.7\n'))
            start = float(args[args.index('-ss') + 1])
            return SimpleNamespace(returncode=0, stdout=b'',
                                   stderr=f'[blackdetect] black_start:{348.2 - start:.3f} black_end:{348.45 - start:.3f}'.encode())

        found = lb.detect('/x.mkv', 1320.0, runner=runner)
        self.assertEqual((found['state'], [round(b['at'], 1) for b in found['breaks']]), ('ok', [348.3]), 'a frame into the black')
        self.assertIn('0:2', calls[1], 'the English sound, not the first track')
        self.assertEqual(len(calls), 3, 'one look at the picture, around the one quiet moment')

    def test_an_unreadable_file_is_a_failed_scan(self):
        def runner(args, **_):
            raise subprocess.TimeoutExpired(args, 1)
        self.assertEqual(lb.detect('/x.mkv', 1320.0, runner=runner)['state'], 'failed')


class LibraryScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for folder in ('Shows', 'Recordings'):
            (base / folder).mkdir()
            (base / folder / 'ep.mkv').write_bytes(b'x')
        self.config = LibraryConfig(True, (LibraryRoot('shows', 'Jellyfin TV', base / 'Shows', ad_breaks=True),
                                           LibraryRoot('rec', 'Recordings', base / 'Recordings')))
        self.cache = base / 'cache.json'
        self.scans = []

        def detector(path, duration):
            self.scans.append(path)
            return {'state': 'ok', 'version': lb.VERSION,
                    'breaks': [{'at': 348.2, 'resume': 348.2, 'kind': 'fade', 'score': 1.}]}
        self.library = MediaLibrary(self.config, self.cache, prober=lambda path: PLAYABLE, detector=detector,
                                    start_worker=False)
        for item_id in ('shows/ep.mkv', 'rec/ep.mkv'):   # as the probe loop leaves them
            item = self.library.item(item_id)
            self.library.probes[item_id] = {**PLAYABLE, 'identity': self.library.items[item_id]['identity']}
            self.assertIsNotNone(item)

    def scan_one(self):
        with self.library.lock:
            pending = self.library._break_pending_locked()
        if pending is None:
            return False
        self.library.closed = False
        # One turn of the loop, by hand.
        info = self.library.detector(Path('/x'), 1320.)
        with self.library.lock:
            self.library.probes[pending['id']]['breaks'] = {**info, 'scanned': 1}
            self.library._save_cache_locked()
            self.library.wanted.remove(pending['id'])
        return True

    def test_nothing_is_scanned_until_asked_and_what_was_found_is_kept(self):
        self.assertEqual(self.library.item('shows/ep.mkv')['ad_breaks']['state'], 'not_scanned')
        self.assertNotIn('ad_breaks', self.library.item('rec/ep.mkv'), 'TV-Thing recordings have no ad breaks')
        self.assertFalse(self.scan_one(), 'no scan on its own')
        self.assertEqual(self.library.scan_breaks('shows/ep.mkv')['ad_breaks']['state'], 'scanning')
        self.assertTrue(self.scan_one())
        found = self.library.item('shows/ep.mkv')['ad_breaks']
        self.assertEqual((found['state'], found['at']), ('ok', [348.2]))
        reloaded = MediaLibrary(self.config, self.cache, start_worker=False)
        self.assertEqual(reloaded.item('shows/ep.mkv')['ad_breaks']['state'], 'ok', 'kept in the cache file')
        identity = self.library.items['shows/ep.mkv']['identity']
        self.assertEqual(cached_breaks(self.cache, 'shows/ep.mkv', identity)[0]['at'], 348.2)
        self.assertIsNone(cached_breaks(self.cache, 'shows/ep.mkv', '1:2'), 'a changed file is not the one scanned')

    def test_the_break_loop_scans_what_was_asked(self):
        self.library.scan_breaks('shows/ep.mkv')
        self.library.break_thread = __import__('threading').Thread(target=self.library._break_loop, daemon=True)
        self.library.break_thread.start()
        self.addCleanup(self.library.close)
        deadline = time.monotonic() + 3
        while self.library.item('shows/ep.mkv')['ad_breaks']['state'] != 'ok' and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.library.item('shows/ep.mkv')['ad_breaks']['state'], 'ok')
        self.assertEqual(len(self.scans), 1)

    def test_queueing_with_ad_breaks_needs_a_show_and_its_scan(self):
        body = {'source_id': 'library', 'channel_id': 'shows/ep.mkv', 'ad_breaks': 60}
        with self.assertRaisesRegex(ConfigError, 'Scan this file'):
            self.library.target(body)
        with self.assertRaisesRegex(ConfigError, 'not recordings'):
            self.library.target({**body, 'channel_id': 'rec/ep.mkv'})
        with self.assertRaisesRegex(ConfigError, 'not recordings'):
            self.library.scan_breaks('rec/ep.mkv')
        self.library.scan_breaks('shows/ep.mkv')
        self.scan_one()
        self.assertEqual(self.library.target(body), body)
        self.assertEqual(self.library.target({**body, 'ad_breaks': None}),
                         {'source_id': 'library', 'channel_id': 'shows/ep.mkv'})

    def test_break_lengths_go_in_15_second_steps_up_to_3_minutes(self):
        base = {'source_id': 'library', 'channel_id': 'shows/ep.mkv'}
        for seconds in (15, 90, 180):
            self.assertEqual(library_target({**base, 'ad_breaks': seconds})['ad_breaks'], seconds)
        for seconds in (0, 10, 20, 195, True, 60.0, '60'):
            with self.subTest(seconds=seconds), self.assertRaises(ConfigError):
                library_target({**base, 'ad_breaks': seconds})

    def test_config(self):
        self.assertTrue(_library({'roots': [{'id': 'a', 'name': 'x', 'path': '/x', 'ad_breaks': True}]}).roots[0].ad_breaks)
        self.assertFalse(_library({'roots': [{'id': 'a', 'name': 'x', 'path': '/x'}]}).roots[0].ad_breaks)
        with self.assertRaises(ConfigError):
            _library({'roots': [{'id': 'a', 'name': 'x', 'path': '/x', 'ad_breaks': 'yes'}]})


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class ProgrammeBreakTests(unittest.TestCase):
    FILE = (None, 0, 3)   # the show's frames: no ad-mute tap

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        output = SimpleNamespace(gst=GST, width=W, height=H, audio_caps='audio/x-raw',
                                 video_caps=f'video/x-raw,format=I420,width={W},height={H},framerate=30/1')
        with patch.object(ad_break.AdBreak, '_run', lambda self: None):   # no helper thread: the test is the helper
            self.b = ad_break.AdBreak(output, self.dir.name, Path(self.dir.name) / 'plays.jsonl')
        self.b.configure(validate({'pip': {'enabled': True}, 'ads': [ad(1), ad(2), ad(3)]}), {'mode': 'off'})
        self.live = GST.Buffer.new_wrapped(bytes((200,)) * (W * H * 3 // 2))

    def frame(self, t):
        out = self.b.picture(self.live, int(t * S), int(t * S), self.FILE)
        return None if out is None else out.extract_dup(0, 1)[0]

    def test_ads_go_on_until_the_show_is_back_and_say_where_the_last_one_ends(self):
        self.b.fill_prime()
        self.assertTrue(self.b.filling and self.b.fill_longest is None, 'cue a long ad too')
        self.b.cued = FakeReel(ad(1, duration=45.0), 45 * S, 50)
        self.assertTrue(self.b.fill_ready())
        self.b.fill_start(10 * S, length=60)
        self.assertEqual(self.frame(10.0), 50, 'a 45 s ad opens it (a wait fill would not start one)')
        self.assertIsNone(self.b.fill_end(), 'it ends before the minute: nothing to say yet')
        self.b.cued = FakeReel(ad(2, duration=30.0), 30 * S, 60)
        self.assertEqual(self.frame(55.0), 60)
        self.assertEqual(self.frame(55.1), 60)
        self.assertEqual(self.b.fill_end(), {'end': 85 * S, 'take': False, 'fixed': True},
                         'the ad past the minute is on: where it ends, a programme delay before it airs')
        self.b.fill_resume(85 * S)
        self.assertEqual(self.frame(84.9), 60)
        self.assertIsNone(self.frame(85.0), 'the show is back')
        self.assertEqual(self.b.state, 'idle')
        self.assertEqual([r.get('programme_break') for r in self.b.log], [True, True])
        self.assertNotIn('wait', self.b.log[0])

    def test_never_the_held_frame_another_ad_starts_and_is_cut_when_the_show_is_back(self):
        # 2026-10-20: the break ended where its last ad did, on what aired; the show came back a
        # programme delay later, and the held frame (black) filled 5-10 s.
        self.b.cued = FakeReel(ad(1, duration=30.0), 30 * S, 50)
        self.b.fill_start(10 * S, length=30)
        self.assertEqual(self.frame(10.0), 50)
        self.b.cued = FakeReel(ad(2, duration=60.0), 60 * S, 60)
        self.assertEqual(self.frame(40.0), 60, 'the time is up but the show is not back: the next ad')
        self.b.fill_resume(int(53.2 * S))
        self.assertEqual(self.frame(53.1), 60)
        self.assertIsNone(self.frame(53.2), 'cut where the show comes back')
        row = self.b.log[-1]
        self.assertEqual((row['id'], row['complete']), (ad(2)['id'], False))

    def test_nothing_to_show_says_so_at_once(self):
        self.b.fill_start(10 * S, length=60)
        self.assertIsNone(self.frame(10.0), 'the held frame for a moment')
        self.assertIsNone(self.frame(13.5))
        self.assertEqual(self.b.fill_end(), {'end': int(13.5 * S), 'take': False, 'fixed': True, 'empty': True})
        self.b.fill_resume(14 * S)
        self.assertIsNone(self.frame(14.0))
        self.assertEqual(self.b.state, 'idle')

    def test_a_cut_away_lands_where_the_ad_on_air_ends_and_none_starts_after_it(self):
        # 2026-10-22: a timed show (and its station ID first) came while an ad spliced into a
        # library show played: the ad plays out, then the cut.
        self.b.cued = FakeReel(ad(1, duration=45.0), 45 * S, 50)
        self.b.fill_start(10 * S, length=120)
        self.assertEqual(self.frame(10.0), 50)
        self.b.cued = FakeReel(ad(2, duration=30.0), 30 * S, 60)
        self.assertEqual(self.b.fill_land(40 * S, 90), 55 * S, 'the ad on air ends at 55 s')
        self.assertEqual(self.b.fill_land(41 * S, 90), 55 * S, 'asked again (the take after the ID): the same')
        self.assertEqual(self.frame(54.9), 50)
        self.assertIsNone(self.frame(55.0), 'no ad starts where the cut lands')
        self.b.fill_stop(55 * S)
        self.assertIsNone(self.frame(55.1))
        self.assertEqual([(r['id'], r['complete']) for r in self.b.log], [(ad(1)['id'], True)])

    def test_a_cut_after_the_ad_on_air_ends_waits_for_the_one_that_follows(self):
        self.b.cued = FakeReel(ad(1, duration=45.0), 45 * S, 50)
        self.b.fill_start(10 * S, length=120)
        self.assertEqual(self.frame(10.0), 50)
        self.b.cued = FakeReel(ad(2, duration=30.0), 30 * S, 60)
        self.assertEqual(self.b.fill_land(60 * S, 90), 85 * S, 'ad 1 ends before 60 s airs: ad 2 is on there, to 85 s')
        self.assertEqual(self.frame(55.0), 60)
        self.b.cued = FakeReel(ad(3, duration=30.0), 30 * S, 70)
        self.assertEqual(self.frame(84.9), 60)
        self.assertIsNone(self.frame(85.0), 'ad 3 never starts')
        self.assertEqual([r['complete'] for r in self.b.log], [True, True])

    def test_cut_at_once_with_nothing_to_wait_for_or_too_long_a_wait(self):
        self.b.fill_start(10 * S, length=60)
        self.assertIsNone(self.frame(10.0))
        self.assertIsNone(self.b.fill_land(11 * S, 90), 'nothing on air: the card, no ad to wait for')
        self.b.fill_stop(11 * S)
        self.b.cued = FakeReel(ad(1, duration=120.0), 120 * S, 50)
        self.b.fill_start(20 * S, length=60)
        self.assertEqual(self.frame(20.0), 50)
        self.assertIsNone(self.b.fill_land(25 * S, 90), '115 s left: cut, as before')
        self.assertIsNone(self.b.fill_land(25 * S, 90))
        self.assertEqual(self.frame(30.0), 50, 'nothing planned: it plays on until the cut')

    def test_a_cancelled_cut_lets_the_break_go_on(self):
        self.b.cued = FakeReel(ad(1, duration=20.0), 20 * S, 50)
        self.b.fill_start(10 * S, length=120)
        self.assertEqual(self.frame(10.0), 50)
        self.b.cued = FakeReel(ad(2, duration=30.0), 30 * S, 60)
        self.assertEqual(self.b.fill_land(15 * S, 90), 30 * S)
        self.b.fill_unland()
        self.assertEqual(self.frame(30.0), 60, 'the next ad starts after all')

    def test_unprime_puts_the_wait_fill_limit_back(self):
        self.b.fill_prime()
        self.b.fill_unprime()
        self.assertEqual((self.b.filling, self.b.fill_longest), (False, self.b.FILL_LONGEST))
        self.b.fill_start(10 * S)
        self.assertEqual(self.b.fill_longest, self.b.FILL_LONGEST, 'a wait fill still starts only short ads')


class WorkerBreakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / 'Shows'
        root.mkdir()
        (root / 'ep.mkv').write_bytes(b'x')
        library = LibraryConfig(True, (LibraryRoot('shows', 'Jellyfin TV', root, ad_breaks=True),))
        state = Path(self.tmp.name) / 'jobs.json'
        config = SimpleNamespace(master=MasterConfig(enabled=True), tv_thing=TvThingConfig(enabled=False),
                                 library=library, state_file=state)
        self.worker = MasterWorker(config, tv=Mock(), status_reader=lambda: {'ready': True, 'source': {'id': 'p'}})
        self.worker.output = Mock(spec=['running_time', 'ad_break', 'take', 'status', 'healthy'])
        self.worker.output.running_time.return_value = 100 * S
        self.breaks = self.worker.output.ad_break = Mock(ads_on=True, promos_on=False)
        self.breaks.fill_ready.return_value = True
        self.breaks.fill_status.return_value = {'state': 'filling'}
        self.breaks.fill_end.return_value = None
        with patch('roku_stream.library.library_breaks.tracks', return_value=(0, 2, 12)):
            lease = FileLease(library, {'source_id': 'library', 'channel_id': 'shows/ep.mkv', 'ad_breaks': 60})
        self.assertEqual(lease.audio_tracks, 12, 'the dubbed tracks are noticed: the English is picked')
        (state.with_name('library-cache.json')).write_text(json.dumps({'shows/ep.mkv': {
            'identity': lease.generation, 'breaks': {'state': 'ok', 'version': lb.VERSION, 'breaks': [
                {'at': 348.2, 'resume': 348.2}, {'at': 660.0, 'resume': 665.5}]}}}))
        self.decoder = Mock(started=True, stopped=False, frozen=False, frozen_at=99 * S)
        self.decoder.freeze.return_value = True
        self.worker.inputs['a'] = {'lease': lease, 'decoder': self.decoder, 'slot': 1}
        self.worker.inputs['a']['breaks'] = self.worker._break_plan(lease)
        self.worker.active = 'a'

    def at(self, seconds):
        self.decoder.progress.return_value = {'position_seconds': seconds, 'duration_seconds': 1320.0}
        self.worker._programme_breaks()
        return self.worker.inputs['a']['breaks']

    def test_primes_stops_holds_for_ads_then_plays_on(self):
        self.assertEqual(self.at(300)['state'], 'play')
        self.assertEqual(self.at(334)['state'], 'primed')
        self.breaks.fill_prime.assert_called_once()
        self.assertEqual(self.at(346.5)['state'], 'armed')
        self.decoder.stop_at.assert_called_once_with(348.2)
        self.assertEqual(self.at(348.3)['state'], 'armed', 'waits for the frame at the break itself')
        self.decoder.stopped = True
        self.assertEqual(self.at(348.3)['state'], 'held')
        self.breaks.fill_start.assert_called_once_with(99 * S, length=60)
        self.assertEqual(self.worker._public('a')['break_plan']['left_seconds'], 120.0)
        self.at(348.3)
        self.decoder.thaw.assert_not_called()
        self.worker.output.running_time.return_value = 158 * S
        self.at(348.3)
        self.decoder.thaw.assert_not_called()
        self.worker.output.running_time.return_value = 159 * S   # 99 s plus the minute, on the input side
        self.decoder.floor = int(159.16 * S)
        plan = self.at(348.3)
        self.decoder.thaw.assert_called_once_with(348.2)
        self.breaks.fill_resume.assert_called_once_with(int(159.16 * S))
        self.assertEqual((plan['state'], plan['index'], plan['aired']), ('play', 1, 1))

    def held(self, at=348.2):
        self.at(at - 14)
        self.at(at - 1.7)
        self.decoder.stopped = True
        self.at(at + .1)
        self.decoder.stopped = False

    def test_the_show_waits_for_an_ad_ending_soon_after_the_break_but_not_long(self):
        self.held()
        self.breaks.fill_end.return_value = {'end': 170 * S, 'take': False, 'fixed': True}
        self.worker.output.running_time.return_value = 169 * S
        self.at(348.3)
        self.decoder.thaw.assert_not_called()
        self.worker.output.running_time.return_value = 170 * S
        self.at(348.3)
        self.decoder.thaw.assert_called_once()
        self.decoder.frozen_at = 300 * S
        self.held(660.0)
        self.assertEqual(self.worker.inputs['a']['breaks']['state'], 'held')
        self.breaks.fill_end.return_value = {'end': 500 * S, 'take': False, 'fixed': True}
        self.worker.output.running_time.return_value = 374 * S   # 300 s plus the minute, plus 15 s
        self.at(660.1)
        self.assertEqual(self.decoder.thaw.call_count, 1, 'an ad ending long after: cut instead')
        self.worker.output.running_time.return_value = 375 * S
        self.at(660.1)
        self.assertEqual(self.decoder.thaw.call_count, 2)

    def test_an_empty_break_gives_the_show_back_at_once(self):
        self.held()
        self.breaks.fill_end.return_value = {'end': 102 * S, 'take': False, 'fixed': True, 'empty': True}
        self.worker.output.running_time.return_value = 102 * S
        self.at(348.3)
        self.decoder.thaw.assert_called_once()

    def test_a_break_with_nothing_to_show_is_skipped(self):
        self.breaks.fill_ready.return_value = False
        self.at(334)
        plan = self.at(346.5)
        self.decoder.stop_at.assert_called_with(None)
        self.breaks.fill_unprime.assert_called_once()
        self.assertEqual((plan['state'], plan['index'], plan['skipped']), ('play', 1, 1))

    def test_leaving_air_in_a_break_closes_it(self):
        self.at(334)
        self.at(346.5)
        self.decoder.stopped = True
        self.at(348.3)
        self.worker._drop('a')
        self.breaks.fill_stop.assert_called_once_with(100 * S)

    def ready(self, key='b', slot=2):
        """A prepared input to cut to."""
        decoder, lease = Mock(), Mock()
        decoder.ready.return_value = lease.check.return_value = True
        lease.target, lease.generation = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}, 'g1'
        self.worker.inputs[key] = {'lease': lease, 'decoder': decoder, 'slot': slot}
        self.worker.prepared, self.worker.busy, self.worker.pending_fallback = key, True, False   # as request() leaves it

    def test_the_station_id_waits_for_the_ad_on_air_and_the_show_waits_with_it(self):
        self.held()
        self.breaks.fill_land.return_value = 170 * S
        self.worker._ident_after = Mock(return_value=True)
        self.worker._ident_for_timed('a')
        self.breaks.fill_land.assert_called_once_with(100 * S, master_worker.CUT_WAIT_MOST)
        self.worker._ident_after.assert_not_called()
        self.assertEqual(self.worker._ident_status()['waits_for_ad'], 70.0)
        self.worker.output.running_time.return_value = 165 * S   # the break's minute is up
        self.at(348.3)
        self.decoder.thaw.assert_not_called()
        self.worker._landings()
        self.worker._ident_after.assert_not_called()
        self.worker.output.running_time.return_value = 170 * S
        self.worker._landings()
        self.worker._ident_after.assert_called_once_with('a', 'schedule')
        self.assertIsNone(self.worker._ident_status()['waits_for_ad'])
        self.breaks.fill_unland.assert_not_called()

    def test_no_ad_to_wait_for_the_id_cuts_at_once(self):
        self.held()
        self.breaks.fill_land.return_value = None
        self.worker._ident_after = Mock(return_value=True)
        self.worker._ident_for_timed('a')
        self.worker._ident_after.assert_called_once_with('a', 'schedule')

    def test_up_nexts_take_waits_for_the_ad_on_air_a_take_by_hand_does_not(self):
        self.held()
        self.ready()
        self.breaks.fill_land.return_value = 170 * S
        self.assertFalse(self.worker._defer_take({'prepared_id': 'b'}, 'op0'), 'by hand: at once')
        self.assertTrue(self.worker._defer_take({'prepared_id': 'b', 'after_ad': True}, 'op1'))
        self.worker.output.take.assert_not_called()
        self.worker.output.running_time.return_value = 169 * S
        self.worker._landings()
        self.worker.output.take.assert_not_called()
        self.assertTrue(self.worker.busy, 'the take is still under way')
        self.worker.output.running_time.return_value = 170 * S
        self.worker._landings()
        self.worker.output.take.assert_called_once_with(2)
        self.assertEqual(self.worker.active, 'b')
        self.breaks.fill_stop.assert_called_once_with(170 * S)
        self.assertEqual(self.worker.snapshot['operation'],
                         {'id': 'op1', 'action': 'take', 'state': 'succeeded', 'error': None, 'error_code': None})
        self.assertFalse(self.worker.busy)

    def test_a_cancelled_take_ends_failed_and_the_break_goes_on(self):
        self.held()
        self.ready()
        self.breaks.fill_land.return_value = 170 * S
        self.assertTrue(self.worker._defer_take({'prepared_id': 'b', 'after_ad': True}, 'op1'))
        self.worker.cancel.set()
        self.worker._landings()
        self.worker.output.take.assert_not_called()
        self.breaks.fill_unland.assert_called_once()
        self.assertEqual((self.worker.snapshot['operation']['state'], self.worker.snapshot['operation']['error']),
                         ('failed', 'Take cancelled'))
        self.assertEqual(self.worker.active, 'a')

    def test_live_tv_and_recordings_never_wait(self):
        self.ready()
        self.worker.inputs['a']['breaks'] = None   # no spliced breaks: ad mute over the real ones
        self.assertFalse(self.worker._defer_take({'prepared_id': 'b', 'after_ad': True}, 'op1'))
        self.breaks.fill_land.assert_not_called()
        self.worker.inputs['a']['breaks'] = self.worker._break_plan(self.worker.inputs['a']['lease'])
        self.assertFalse(self.worker._defer_take({'prepared_id': 'b', 'after_ad': True}, 'op1'), 'not in a break: at once')
        self.breaks.fill_land.assert_not_called()

    def test_unknown_breaks_play_straight_through(self):
        self.worker.inputs['a']['breaks']['points'] = []
        self.at(348.3)
        self.decoder.stop_at.assert_not_called()


if __name__ == '__main__':
    unittest.main()
