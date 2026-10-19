"""Station promos: settings, the library of built promos, the live values, the live text,
the web app's desk (temperature, programme, voiced copies), the break on master with
stand-in reels (ad_break.py), and the routes."""
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream import promo_overlay, promos
from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.my_ads import validate as my_ads_validate

TEXT = {'field': 'programme', 'box': [100, 100, 300, 120], 'from': 1.0, 'to': 5.0,
        'style': {'size': 80, 'min_size': 12, 'lines': 2}, 'enter': {'kind': 'flip', 'seconds': .5},
        'exit': {'kind': 'fade', 'seconds': .5}}


def manifest(promo_id, overlays=(), duration=10.0, **extra):
    return {'id': promo_id, 'name': promo_id.title(), 'duration': duration, 'file': promo_id + '.mp4',
            'still': promo_id + '.png', 'overlays': list(overlays), **extra}


def library(folder, *items, present=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for item in items:
        (folder / f"{item['id']}.json").write_text(json.dumps(item))
        if present:
            (folder / item['file']).write_bytes(b'video')
    return promos.Library(folder)


class SettingsTests(unittest.TestCase):
    def test_defaults_and_checks(self):
        self.assertEqual(promos.validate({}), {'enabled': True, 'every': 15, 'fill': False, 'promos': {}})
        for bad in ({'every': 2}, {'every': 15.5}, {'fill': 'yes'}, {'promos': {'Bad Id': {'enabled': True}}},
                    {'promos': {'legal': {'enabled': 1}}}, {'colour': 'red'}):
            with self.assertRaises(ConfigError, msg=bad):
                promos.validate(bad)
        lenient = promos.validate({'colour': 'red', 'promos': {'Bad Id': {}, 'legal': {'enabled': False, 'x': 1}}},
                                  lenient=True)
        self.assertEqual(lenient['promos'], {'legal': {'enabled': False}})

    def test_every_break(self):
        self.assertEqual(promos.validate({'every': 0})['every'], promos.EVERY_BREAK)
        self.assertIn(0, promos.EVERY_CHOICES)
        for bad in (1, 4, 241, -5):
            with self.assertRaises(ConfigError, msg=bad):
                promos.validate({'every': bad})
        settings = promos.validate({'every': 0})
        self.assertTrue(promos.due(settings, None, 1000))
        self.assertTrue(promos.due(settings, 1000, 1000), 'due again at once: master limits it to a break\'s start')

    def test_store_update_and_switch_a_promo_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = promos.Promos(Path(tmp) / 'master.sock', library=library(Path(tmp) / 'lib', manifest('legal')))
            self.assertEqual(store.update({'every': 30, 'fill': True})['every'], 30)
            with self.assertRaises(ConfigError):
                store.update({'promos': {}})
            self.assertFalse(store.set_promo('legal', {'enabled': False})['promos']['legal']['enabled'])
            with self.assertRaises(ConfigError):
                store.set_promo('nope', {'enabled': False})
            self.assertFalse(promos.switched_on(store.read(), 'legal'))
            self.assertTrue(promos.switched_on(store.read(), 'other'), 'a promo not listed is on')


class LibraryTests(unittest.TestCase):
    def test_reads_manifests_in_order_and_says_what_it_needs(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = library(tmp, manifest('legal', order=4), manifest('time-temp', [{**TEXT, 'field': 'time'},
                                                                                     {**TEXT, 'field': 'temperature'}], order=1),
                          manifest('only-on', [TEXT], order=3))
            found = lib.read()
            self.assertEqual([p['id'] for p in found], ['time-temp', 'only-on', 'legal'])
            self.assertEqual([p['needs'] for p in found], [['temperature'], ['programme'], []])
            self.assertTrue(all(p['present'] for p in found))
            (Path(tmp) / 'legal.mp4').unlink()
            self.assertFalse(lib.read()[2]['present'], 'presence is checked every read')

    def test_a_bad_manifest_is_set_aside_with_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = library(tmp, manifest('good'), {**manifest('bad'), 'file': 'other.mp4'},
                          manifest('worse', [{**TEXT, 'field': 'weather'}]), manifest('odd', leagues='mlb'),
                          manifest('odder', leagues=['MLB']))
            self.assertEqual([p['id'] for p in lib.read()], ['good'])
            self.assertEqual(sorted(lib.problems), ['bad', 'odd', 'odder', 'worse'])

    def test_a_sports_promo_needs_the_league_on_air(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = library(tmp, manifest('baseball', [TEXT], leagues=['mlb']), manifest('legal'))
            found = {p['id']: p for p in lib.read()}
            self.assertEqual((found['baseball']['leagues'], found['baseball']['needs']), (['mlb'], ['league', 'programme']))
            self.assertEqual((found['legal']['leagues'], found['legal']['needs']), ([], []))

    def test_library_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = library(tmp, manifest('legal'))
            self.assertEqual(lib.path('legal.mp4').name, 'legal.mp4')
            self.assertIsNone(lib.path('../config.json'))
            self.assertIsNone(lib.path('missing.png'))


class ValuesTests(unittest.TestCase):
    def test_fresh_values_only(self):
        now = 1_800_000_000
        values = {'at': now - 10, 'temperature': {'f': 61, 'observed_at': now - 3600, 'place': 'Reagan National'},
                  'programme': {'title': ' Jeopardy! ', 'spoken': 'Jeopardy!',
                                'variants': {'only-on': 'only-on-0123456789abcdef.mp4', 'x': '../../etc'}}}
        got = promos.fresh(values, now)
        self.assertEqual((got['temperature']['f'], got['programme']['title'], got['programme']['variants']),
                         (61, 'Jeopardy!', {'only-on': 'only-on-0123456789abcdef.mp4'}))
        self.assertEqual(promos.fresh({**values, 'at': now - 400}, now), {}, 'the web app went quiet')
        stale = {**values, 'temperature': {'f': 61, 'observed_at': now - 4 * 3600}}
        self.assertNotIn('temperature', promos.fresh(stale, now))
        self.assertNotIn('league', got['programme'])
        game = {**values, 'programme': {**values['programme'], 'league': 'mlb'}}
        self.assertEqual(promos.fresh(game, now)['programme']['league'], 'mlb')
        self.assertNotIn('league', promos.fresh({**values, 'programme': {**values['programme'], 'league': '../x'}}, now)['programme'])

    def test_readiness(self):
        promo = {'present': True, 'needs': ['temperature']}
        self.assertEqual(promos.readiness(promo, {}), 'no recent temperature reading')
        self.assertIsNone(promos.readiness(promo, {'temperature': {'f': 60}}))
        self.assertEqual(promos.readiness({'present': False, 'needs': []}, {}), 'its video is not built')

    def test_a_sports_promo_airs_only_during_its_leagues_games(self):
        football = {'present': True, 'needs': ['league'], 'leagues': ['nfl', 'ncaaf']}
        self.assertEqual(promos.readiness(football, {}), 'only during NFL or NCAAF games')
        self.assertEqual(promos.readiness(football, {'programme': {'title': 'Jeopardy!'}}), 'only during NFL or NCAAF games')
        self.assertEqual(promos.readiness(football, {'programme': {'title': 'Guardians at White Sox', 'league': 'mlb'}}),
                         'only during NFL or NCAAF games')
        self.assertIsNone(promos.readiness(football, {'programme': {'title': 'Lions at Panthers', 'league': 'nfl'}}))
        self.assertIsNone(promos.readiness({'present': True, 'needs': [], 'leagues': []}, {}), 'not a sports promo')

    def test_league_of_a_segment(self):
        self.assertEqual(promos.league_of({'kind': 'game', 'game': {'game_pk': 1, 'league': 'nfl'}}), 'nfl')
        self.assertEqual(promos.league_of({'kind': 'game', 'game': {'game_pk': 7}}), 'mlb', "a game's league defaults to MLB")
        self.assertIsNone(promos.league_of({'kind': 'manual', 'title': 'Jeopardy!'}))
        self.assertIsNone(promos.league_of({'kind': 'game', 'game': {'title': 'TBD'}}), 'no game id: not a game')
        self.assertIsNone(promos.league_of(None))

    def test_due(self):
        settings = promos.validate({'every': 15})
        self.assertTrue(promos.due(settings, None, 1000))
        self.assertFalse(promos.due(settings, 1000, 1000 + 899))
        self.assertTrue(promos.due(settings, 1000, 1000 + 900))
        plays = [{'kind': 'promo', 'at': 50, 'counted': True}, {'kind': 'promo', 'at': 90, 'counted': False},
                 {'kind': 'ad', 'at': 99, 'counted': True}]
        self.assertEqual(promos.last_promo(plays), 50)

    def test_names(self):
        info = lambda game: {'away': {'nickname': 'Lions'}, 'home': {'nickname': 'Panthers'}}  # noqa: E731
        game = {'kind': 'game', 'title': 'Detroit Lions at Carolina Panthers',
                'game': {'game_pk': 1, 'league': 'nfl'}, 'target': {'source_id': 'youtube-tv'}}
        self.assertEqual(promos.display_name(game, info), 'Lions at Panthers')
        self.assertEqual(promos.display_name(game, None), 'Detroit Lions at Carolina Panthers')
        self.assertIsNone(promos.display_name({'kind': 'off_air', 'title': 'OFF AIR'}))
        self.assertIsNone(promos.display_name({'kind': 'manual', 'title': '', 'target': {'channel_id': 'wrc_hd_4_1'}}))
        self.assertEqual(promos.spoken_line('{name}... only on Vizel Vision.', 'the Lions and the Panthers'),
                         'The Lions and the Panthers... only on Vizel Vision.')


class OverlayTests(unittest.TestCase):
    def test_validate(self):
        spec = promo_overlay.validate(TEXT)
        self.assertEqual((spec['box'], spec['style']['lines'], spec['enter']['kind']), ((100, 100, 300, 120), 2, 'flip'))
        for bad in ({**TEXT, 'field': 'x'}, {**TEXT, 'box': [0, 0, 1]}, {**TEXT, 'to': .5},
                    {**TEXT, 'style': {'colour': 1}}, {**TEXT, 'enter': {'kind': 'spin'}}):
            with self.assertRaises(ValueError):
                promo_overlay.validate(bad)

    def test_field_text(self):
        at = time.mktime((2026, 10, 4, 22, 5, 0, 0, 0, -1))
        values = {'temperature': {'f': 61, 'c': 16.1, 'place': 'Reagan National'}, 'programme': {'title': 'Jeopardy!'}}
        self.assertEqual([promo_overlay.field_text(f, values, at) for f in promo_overlay.FIELDS],
                         ['10:05', 'PM', '61°', 'Jeopardy!', 'Reagan National', '9:20:13', '16°C'])
        noon = time.mktime((2026, 10, 4, 12, 0, 0, 0, 0, -1))
        self.assertEqual(promo_overlay.field_text('decimal_time', {}, noon), '5:00:00')
        self.assertEqual(promo_overlay.field_text('decimal_time', {}, noon - 12 * 3600), '0:00:00')
        self.assertEqual(promo_overlay.field_text('decimal_time', {}, noon + 12 * 3600 - 0.5), '9:99:99')
        self.assertEqual(promo_overlay.field_text('celsius', {'temperature': {'f': 50}}), '10°C')
        self.assertIsNone(promo_overlay.field_text('celsius', {}))
        self.assertEqual(promo_overlay.field_text('time', {}, time.mktime((2026, 10, 4, 0, 30, 0, 0, 0, -1))), '12:30')
        self.assertIsNone(promo_overlay.field_text('temperature', {}))

    def test_long_text_shrinks_or_wraps_and_is_drawn_inside_its_box(self):
        import cairo
        spec = promo_overlay.validate(TEXT)
        ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))
        lines, size = promo_overlay.fit(ctx, spec['style'], 'WHO WANTS TO BE A MILLIONAIRE', 290, 110)
        self.assertEqual(len(lines), 2)
        lines, size = promo_overlay.fit(ctx, {**spec['style'], 'lines': 1}, 'A' * 200, 290, 110)
        self.assertTrue(lines[0].endswith('…'))
        surface = promo_overlay.render(spec['style'], 'Lions at Panthers', 300, 120)
        data = surface.get_data()
        alpha = [data[i + 3] for i in range(0, len(data), 4)]
        self.assertGreater(sum(1 for a in alpha if a), 1000, 'the text is drawn')
        self.assertEqual((surface.get_width(), surface.get_height()), (300, 120))

    def test_place_over_time(self):
        spec = promo_overlay.validate(TEXT)
        self.assertIsNone(promo_overlay.place(spec, .9))
        x, y, w, h, alpha = promo_overlay.place(spec, 1.0)
        self.assertLess(h, 10, 'a flip starts as a line')
        self.assertEqual(promo_overlay.place(spec, 3.0), (100, 100, 300, 120, 1.0))
        self.assertAlmostEqual(promo_overlay.place(spec, 4.75)[4], .5, places=2)
        self.assertIsNone(promo_overlay.place(spec, 5.0))


class Weather:
    def __init__(self, observation=None):
        self.observation, self.wanted = observation, []

    def want(self, wanted):
        self.wanted.append(wanted)

    def status(self):
        return {'error': None}

    def stop(self):
        pass


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)
        voice = {'model': 'aura-2-ophelia-en', 'template': '{name}... only on Vizel Vision.', 'music': 'only-on-music.wav',
                 'earliest': 5.0, 'start': 5.5, 'end': 9.0}
        lib = library(self.tmp / 'lib', manifest('time-temp', [{**TEXT, 'field': 'temperature'}]),
                      manifest('only-on', [TEXT], voice=voice), manifest('legal'))
        (self.tmp / 'lib' / 'only-on-music.wav').write_bytes(b'wav')
        self.store = promos.Promos(self.tmp / 'master.sock', library=lib)
        self.now = 1_800_000_000.
        self.weather = Weather({'f': 58, 'c': 14.4, 'place': 'Reagan National', 'station': 'KDCA',
                                'observed_at': self.now - 600})
        self.segment = {'kind': 'game', 'title': 'Lions at Panthers'}
        self.line = Mock(return_value=self.tmp / 'line.wav')
        self.mixed = []

        def mix(voiced, out, *, music, video, length):
            self.mixed.append((voiced, music.name, video.name, length))
            Path(out).write_bytes(b'mp4')
        self.desk = promos.PromoDesk(self.store, programme=lambda: self.segment,
                                     name=lambda s: (s['title'], 'the Lions and the Panthers'),
                                     weather=self.weather, voice=SimpleNamespace(line=self.line), mix=mix,
                                     clock=lambda: self.now, start_worker=False)

    def tearDown(self):
        self.dir.cleanup()

    def test_values_for_master_and_a_voiced_copy(self):
        with patch('roku_stream.continuity.seconds', return_value=2.8):
            self.desk.step()
        values = json.loads(self.store.values_path.read_text())
        self.assertEqual(values['temperature']['f'], 58)
        self.assertEqual(self.weather.wanted, [True], 'fetched only while a promo shows it')
        self.assertEqual((values['programme']['title'], values['programme']['spoken']), ('Lions at Panthers', 'the Lions and the Panthers'))
        variant = values['programme']['variants']['only-on']
        self.assertTrue((self.store.folder / variant).exists())
        self.line.assert_called_once_with('aura-2-ophelia-en', 'The Lions and the Panthers... only on Vizel Vision.')
        self.assertEqual(self.mixed, [([(self.tmp / 'line.wav', 5.5)], 'only-on-music.wav', 'only-on.mp4', 10.0)])
        with patch('roku_stream.continuity.seconds', return_value=2.8):
            self.desk.step()
        self.assertEqual(len(self.mixed), 1, 'made once per programme')

    def test_a_long_name_starts_earlier_and_a_too_long_one_keeps_its_own_line(self):
        with patch('roku_stream.continuity.seconds', return_value=3.8):
            self.desk.step()
        self.assertEqual(self.mixed[0][0][0][1], 5.2)
        self.segment = {'kind': 'show', 'title': 'Long'}
        self.desk.name = lambda s: (s['title'], 'a very long title')
        with patch('roku_stream.continuity.seconds', return_value=5.0):
            self.desk.step()
        values = json.loads(self.store.values_path.read_text())
        self.assertEqual(values['programme']['variants'], {})
        self.assertIn('too long', self.desk.errors['voice'])

    def test_the_league_on_air_for_a_sports_promo(self):
        library(self.tmp / 'lib', manifest('football', leagues=['nfl', 'ncaaf']))
        self.store.save({'promos': {'time-temp': {'enabled': False}, 'only-on': {'enabled': False}}})
        self.segment = {'kind': 'game', 'title': 'Lions at Panthers', 'game': {'game_pk': 1, 'league': 'nfl'}}
        self.desk.step()
        values = json.loads(self.store.values_path.read_text())
        self.assertEqual((values['programme']['title'], values['programme']['league']), ('Lions at Panthers', 'nfl'))
        self.assertIsNone(promos.readiness(next(p for p in self.store.library.read() if p['id'] == 'football'),
                                           promos.fresh(values, self.now)))
        self.segment = {'kind': 'show', 'title': 'Jeopardy!'}
        self.desk.step()
        values = json.loads(self.store.values_path.read_text())
        self.assertNotIn('league', values['programme'])
        self.line.assert_not_called()

    def test_nothing_needed_nothing_fetched(self):
        self.store.save({'promos': {'time-temp': {'enabled': False}, 'only-on': {'enabled': False}}})
        self.desk.step()
        values = json.loads(self.store.values_path.read_text())
        self.assertEqual((self.weather.wanted, set(values)), ([False], {'at'}))
        self.line.assert_not_called()

    def test_preview_stand_in_names_the_configured_place(self):
        self.assertEqual(self.desk._sample()['temperature']['place'], 'Reagan National')
        self.weather.status = lambda: {'error': None, 'place': 'Dupont Circle'}
        self.assertEqual(self.desk._sample()['temperature']['place'], 'Dupont Circle')

    def test_status_for_the_page(self):
        self.desk.master = Mock(request=Mock(return_value={'state': 'live', 'my_ads': {'promos': {'cued': 'legal'}}}))
        from roku_stream.my_ads import append_play
        append_play(self.store.plays_path, {'kind': 'promo', 'id': 'legal', 'at': self.now - 300, 'counted': True,
                                            'seconds': 5, 'length': 5, 'complete': True})
        append_play(self.store.plays_path, {'kind': 'ad', 'id': 'a' * 12, 'at': self.now - 200, 'counted': True})
        with patch('roku_stream.continuity.seconds', return_value=2.8):
            self.desk.step()
        view = self.desk.status()
        self.assertEqual([p['id'] for p in view['recent']], ['legal'], 'promos only')
        self.assertEqual((view['last'], view['next_due'], view['due']), (self.now - 300, self.now + 600, False))
        legal = next(p for p in view['promos'] if p['id'] == 'legal')
        self.assertEqual((legal['ready'], legal['played']['day']), (True, 1))
        self.assertEqual(view['master'], {'promos': {'cued': 'legal'}})


# ---------------------------------------------------------------- the break, on master

try:
    from roku_stream.master import _gst
    from roku_stream import ad_break
    GST = _gst()
except Exception:      # no GStreamer (the conda interpreter)
    GST = None

W, H = 64, 36
SIZE = W * H * 3 // 2


class FakeReel:
    def __init__(self, ad, length_ns, colour):
        self.ad, self.length, self.failed = ad, length_ns, None
        self.buffer = GST.Buffer.new_wrapped(bytes((colour,)) * (W * H) + bytes((128,)) * (W * H // 2))
        self.path = Path(ad.get('file', 'x'))

    def frame(self, t):
        return self.buffer

    def ended(self, t):
        return t >= self.length

    def sound(self, t, size):
        return bytes(size)

    def close(self):
        pass


class Tap:
    def __init__(self):
        self.mutes = []

    def gain(self, pts):
        return 0. if any(a <= pts < b for a, b in self.mutes) else 1.


def ad(i):
    return {'id': f'{i:012x}', 'file': f'{i:012x}.mp4', 'duration': 20.0, 'name': f'Ad {i}'}


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class PromoBreakTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        output = SimpleNamespace(gst=GST, width=W, height=H, audio_caps='audio/x-raw',
                                 video_caps=f'video/x-raw,format=I420,width={W},height={H},framerate=30/1')
        with patch.object(ad_break.AdBreak, '_run', lambda self: None):
            self.b = ad_break.AdBreak(output, self.dir.name, Path(self.dir.name) / 'plays.jsonl')
        self.b.configure(my_ads_validate({'pip': {'enabled': False}, 'ads': [ad(1)]}), {'mode': 'on'})
        self.promo = promos._manifest(manifest('legal', duration=5.0), Path(self.dir.name), 'legal')
        self.configure()
        self.tap = Tap()
        self.live = GST.Buffer.new_wrapped(bytes((200,)) * SIZE)

    def configure(self, **settings):
        self.b.configure_promos({'settings': promos.validate(settings), 'values': {}, 'promos': [self.promo],
                                 'library': Path(self.dir.name), 'variants': Path(self.dir.name)})

    def tearDown(self):
        self.dir.cleanup()

    def frame(self, t):
        ns = int(t * 1e9)
        out = self.b.picture(self.live, ns, ns, (self.tap, 0, 1))
        return None if out is None else out.extract_dup(0, 1)[0]

    def test_a_due_promo_opens_the_break_then_the_ads(self):
        self.b.cued, self.b.cued_promo = FakeReel(ad(1), int(10e9), 50), FakeReel(self.promo, int(1e9), 90)
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 90, 'the promo first')
        self.assertEqual(self.b.state, 'promo')
        self.assertEqual(self.frame(2.0), 50, 'then my ad')
        row = self.b.log[0]
        self.assertEqual((row['kind'], row['id'], row['complete'], row['counted']), ('promo', 'legal', True, True))
        self.assertIsNotNone(self.b.last_promo)
        self.assertIn('legal', self.b.break_promos)

    def test_not_due_my_ads_first(self):
        self.b.last_promo = time.time() - 60
        self.b.cued, self.b.cued_promo = FakeReel(ad(1), int(10e9), 50), FakeReel(self.promo, int(1e9), 90)
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 50)

    def test_cut_short_before_half_does_not_count(self):
        self.b.cued_promo = FakeReel(self.promo, int(5e9), 90)
        self.tap.mutes.append((int(1e9), int(2e9)))
        self.assertEqual(self.frame(1.0), 90)
        self.assertIsNone(self.frame(2.0), 'the show is back')
        row = self.b.log[-1]
        self.assertEqual((row['kind'], row['complete'], row['counted']), ('promo', False, False))
        self.assertIsNone(self.b.last_promo, 'still due at the next break')

    def test_fill_stands_in_for_the_card_each_promo_once(self):
        self.configure(fill=True)
        self.b.last_promo = time.time() - 60
        self.b.cued_promo = FakeReel(self.promo, int(1e9), 90)
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 90, 'no ad: a promo fills in')
        self.b.cued_promo = FakeReel(self.promo, int(1e9), 90)
        self.assertEqual(self.frame(2.0), 16, 'the same promo twice in a break: the card')
        self.b.cued = FakeReel(ad(1), int(10e9), 50)
        self.assertEqual(self.frame(2.5), 50, 'an ad ready: it airs')

    def test_my_ads_off_a_due_promo_still_plays_then_nothing_is_replaced(self):
        self.b.configure(my_ads_validate({'enabled': False, 'pip': {'enabled': False}}), {'mode': 'on'})
        self.assertTrue(self.b.active)
        self.b.cued_promo = FakeReel(self.promo, int(1e9), 90)
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 90)
        self.assertIsNone(self.frame(2.5), 'the break goes on as ad mute has it')
        self.assertEqual(self.b.state, 'pass')
        self.assertIsNone(self.b.sound(int(2.6e9), int(2.6e9), self.tap.gain, bytes(960 * 8)), 'the usual break sound')

    def test_promos_off_and_ad_mute_shadow(self):
        self.configure(enabled=False)
        self.b.cued, self.b.cued_promo = FakeReel(ad(1), int(10e9), 50), FakeReel(self.promo, int(1e9), 90)
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 50)
        self.b.configure(my_ads_validate({'enabled': False}), {'mode': 'on'})
        self.assertFalse(self.b.active, 'both off: nothing replaces a break')

    def test_status(self):
        self.b.cued_promo = FakeReel(self.promo, int(1e9), 90)
        status = self.b.status()
        self.assertEqual((status['promos']['cued'], status['promos']['due'], status['promo']), ('legal', True, None))
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.frame(1.0)
        self.assertEqual(self.b.status()['promo']['id'], 'legal')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name)
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                                 master=MasterConfig(socket_path=self.state / 'master.sock'),
                                 tv_thing=SimpleNamespace(base_url='http://127.0.0.1:8080/'))
        lib = library(self.state / 'lib', manifest('legal'), manifest('only-on', [TEXT]))
        (self.state / 'lib' / 'legal.png').write_bytes(b'\x89PNG')
        coordinator = Mock()
        coordinator.request.return_value = {'state': 'live', 'my_ads': {'promos': {'cued': 'legal'}}}
        self.desk = promos.PromoDesk(promos.Promos(self.state / 'master.sock', library=lib), master=coordinator,
                                     start_worker=False)
        with patch('roku_stream.api.MasterClient', return_value=Mock()):
            from roku_stream.api import handler_factory
            self.handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                coordinator=coordinator, promo_desk=self.desk)

    def tearDown(self):
        self.dir.cleanup()

    def handler(self, method, path, body=None):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler._authorize = lambda: True
        handler._json = Mock()
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        handler.wfile = io.BytesIO()
        handler._body = Mock(return_value=body or {})
        getattr(handler, 'do_' + method)()
        return handler

    def call(self, method, path, body=None):
        status, payload = self.handler(method, path, body)._json.call_args[0]
        return int(status), payload

    def test_view_settings_and_files(self):
        status, view = self.call('GET', '/v1/promos')
        self.assertEqual((status, [p['id'] for p in view['promos']], view['admute_mode']), (200, ['legal', 'only-on'], 'off'))
        only_on = view['promos'][1]
        self.assertEqual((only_on['ready'], only_on['why']), (False, 'no programme name on air'))
        status, view = self.call('POST', '/v1/promos', {'every': 20})
        self.assertEqual((status, view['settings']['every']), (200, 20))
        self.assertEqual(self.call('POST', '/v1/promos', {'every': 1})[0], 400)
        status, view = self.call('POST', '/v1/promos/promo/legal', {'enabled': False})
        self.assertFalse(view['promos'][0]['enabled'])
        served = self.handler('GET', '/v1/promos/file/legal.mp4')
        self.assertEqual(served.wfile.getvalue(), b'video')
        self.assertEqual(self.call('GET', '/v1/promos/file/..%2Fmaster.sock')[0], 404)
        self.assertEqual(self.call('GET', '/v1/promos/still/nope.png')[0], 400)

    def test_ident_files(self):
        # Ads › Idents shows the station ID and the Sports ID beside the promos: each video and its end card.
        video = self.state / 'vizelvision-id.mp4'
        video.write_bytes(b'id')
        video.with_suffix('.png').write_bytes(b'\x89PNG')
        with patch.dict('roku_stream.ident.IDENT_FILES', {'station-id': video, 'sports-id': self.state / 'vizelvision-sports.mp4'}):
            self.assertEqual(self.handler('GET', '/v1/idents/station-id.mp4').wfile.getvalue(), b'id')
            served = self.handler('GET', '/v1/idents/station-id.png')
            self.assertEqual(served.wfile.getvalue(), b'\x89PNG')
            served.send_header.assert_any_call('Content-Type', 'image/png')
            for name in ('sports-id.png', 'vizelvision-id.mp4', '..%2Fmaster.sock', 'station-id.wav'):
                self.assertEqual(self.call('GET', '/v1/idents/' + name)[0], 404, name)


if __name__ == '__main__':
    unittest.main()
