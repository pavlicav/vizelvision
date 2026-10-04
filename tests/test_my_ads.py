"""My ads: settings, the rotation and its limits, the store, the routes, and the break as
master shows it (ad_break.py) with stand-in ads."""
import io
import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream import my_ads
from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.my_ads import MyAds, Rotation, allowed, allowed_again, validate

AD = {'id': 'a' * 12, 'file': 'a' * 12 + '.mp4', 'duration': 30.0}


def ad(i, **extra):
    return {'id': f'{i:012x}', 'file': f'{i:012x}.mp4', 'duration': 20.0, 'name': f'Ad {i}', **extra}


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        value = validate({})
        self.assertEqual((value['enabled'], value['order'], value['pip'], value['card']['text'], value['ads']),
                         (True, 'shuffle', {'enabled': True, 'corner': 'bottom-right', 'size': 'medium'}, 'STAY TUNED', []))

    def test_strict_refuses_what_lenient_skips(self):
        for bad in ({'order': 'random'}, {'pip': {'corner': 'middle'}}, {'card': {'text': ''}}, {'card': {'text': 'x' * 40}},
                    {'default_limit': {'count': 0, 'minutes': 60}}, {'default_limit': {'count': 1, 'minutes': 1}},
                    {'ads': [{**AD, 'file': '../x.mp4'}]}, {'ads': [AD, AD]}, {'ads': [{**AD, 'limit': {'count': 1}}]},
                    {'card': {'text': 'OK', 'image': '../../etc/passwd'}}, {'surprise': 1}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                validate(bad)
        value = validate({'ads': [{**AD, 'file': '../x.mp4'}, ad(2)], 'surprise': 1}, lenient=True)
        self.assertEqual([a['id'] for a in value['ads']], [ad(2)['id']], 'the worker plays the ads it can read')

    def test_card_words_are_tidied(self):
        self.assertEqual(validate({'card': {'text': "  we'll   be right back "}})['card']['text'], "WE'LL BE RIGHT BACK")


class RotationTests(unittest.TestCase):
    def settings(self, n=4, order='shuffle', **extra):
        return validate({'order': order, 'ads': [ad(i, **extra) for i in range(1, n + 1)]})

    def test_list_order_goes_round(self):
        s, r = self.settings(order='list'), Rotation()
        seen = []
        for _ in range(6):
            pick = r.pick(s, [], 0)
            r.played(pick['id'])
            seen.append(pick['name'])
        self.assertEqual(seen, ['Ad 1', 'Ad 2', 'Ad 3', 'Ad 4', 'Ad 1', 'Ad 2'])

    def test_shuffle_plays_each_once_before_any_repeats_and_never_twice_running(self):
        s = self.settings(n=5)
        for seed in range(30):
            r, seen = Rotation(random.Random(seed)), []
            for _ in range(15):
                pick = r.pick(s, [], 0)
                r.played(pick['id'])
                seen.append(pick['id'])
            for k in range(0, 15, 5):
                self.assertEqual(len(set(seen[k:k + 5])), 5, seen)
            self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])), seen)

    def test_pick_only_looks(self):
        s, r = self.settings(), Rotation(random.Random(1))
        self.assertEqual(r.pick(s, [], 0)['id'], r.pick(s, [], 0)['id'])

    def test_limits(self):
        hour = {'count': 1, 'minutes': 60}
        a = validate({'ads': [ad(1, limit=hour)]})['ads'][0]
        now = 100000.
        plays = [{'kind': 'ad', 'id': a['id'], 'at': now - 600, 'counted': True}]
        self.assertFalse(allowed(a, plays, now))
        self.assertEqual(allowed_again(a, plays, now), now - 600 + 3600)
        self.assertTrue(allowed(a, plays, now + 3001))
        uncounted = [{**plays[0], 'counted': False}]
        self.assertTrue(allowed(a, uncounted, now), 'a play cut short before half does not count')
        twice = {**a, 'limit': {'count': 2, 'minutes': 60}}
        self.assertTrue(allowed(twice, plays, now))
        self.assertFalse(allowed({**a, 'enabled': False}, [], now))
        s = validate({'order': 'list', 'ads': [ad(1, limit=hour), ad(2)]})
        self.assertEqual(Rotation().pick(s, plays[:0] + [{**plays[0], 'id': ad(1)['id']}], now)['name'], 'Ad 2')
        s = validate({'ads': [ad(1, limit=hour)]})
        self.assertIsNone(Rotation().pick(s, [{**plays[0], 'id': ad(1)['id']}], now), 'nothing left: the card')
        self.assertIsNone(Rotation().pick(self.settings(n=1), [], now, skip={ad(1)['id']}))

    def test_counts_from_half(self):
        self.assertFalse(my_ads.counts(14.9, 30))
        self.assertTrue(my_ads.counts(15, 30))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = MyAds(Path(self.dir.name) / 'master.sock')

    def tearDown(self):
        self.dir.cleanup()

    def upload(self, name='Cousin_Vinny pizza.MP4', **info):
        part = Path(self.dir.name) / 'upload.part'
        part.write_bytes(b'video')
        info = {'duration': 30.0, 'width': 1920, 'height': 1080, 'audio': True, 'lufs': -24.0, 'gain_db': 4.0, **info}
        return self.store.add(part, name, examine=lambda p: info, pictures=lambda *a: 4)

    def test_add_edit_order_remove(self):
        self.store.update({'default_limit': {'count': 1, 'minutes': 60}})
        _, first = self.upload()
        _, second = self.upload('second.webm')
        self.assertEqual((first['name'], first['limit'], first['gain_db'], first['pics']),
                         ('Cousin Vinny pizza', {'count': 1, 'minutes': 60}, 4.0, 4))
        self.assertTrue((self.store.folder / first['file']).is_file() and first['file'].endswith('.mp4'))
        self.store.edit(first['id'], {'name': ' Pizza ', 'enabled': False, 'limit': None, 'trim_db': -3})
        with self.assertRaises(ConfigError):
            self.store.edit(first['id'], {'file': 'x.mp4'})
        with self.assertRaises(ConfigError):
            self.store.edit(first['id'], {'trim_db': 40})
        value = self.store.reorder([second['id'], first['id']])
        self.assertEqual([(a['name'], a['enabled'], a['limit'], a['trim_db']) for a in value['ads']],
                         [('second', True, {'count': 1, 'minutes': 60}, 0.0), ('Pizza', False, None, -3.0)])
        with self.assertRaises(ConfigError):
            self.store.reorder([second['id']])
        (self.store.folder / f'{first["id"]}-0.jpg').write_bytes(b'jpg')
        value = self.store.remove(first['id'])
        self.assertEqual([a['id'] for a in value['ads']], [second['id']])
        self.assertFalse((self.store.folder / first['file']).exists() or (self.store.folder / f'{first["id"]}-0.jpg').exists())

    def test_a_file_that_is_not_an_ad_is_deleted(self):
        part = Path(self.dir.name) / 'upload.part'
        part.write_bytes(b'x')

        def refuse(path):
            raise ConfigError('That file has no picture')
        with self.assertRaises(ConfigError):
            self.store.add(part, 'song.mp4', examine=refuse)
        self.assertFalse(part.exists())
        part.write_bytes(b'x')
        with self.assertRaises(ConfigError):
            self.store.add(part, 'notes.txt', examine=lambda p: {})
        self.assertFalse(part.exists())

    def test_card(self):
        drawn = []
        with patch.object(my_ads, 'render_card', side_effect=lambda text, out: (drawn.append(text), Path(out).write_bytes(b'png'))):
            first = self.store.card()
            self.assertEqual((first.name, drawn), (my_ads.card_file(self.store.read()), ['STAY TUNED']))
            self.store.update({'card': {'text': 'back soon'}})
            second = self.store.card()
            self.assertEqual(drawn[-1], 'BACK SOON')
            self.assertFalse(first.exists(), 'earlier wordings are cleared away')
            self.store.card()
            self.assertEqual(len(drawn), 2, 'drawn once per wording')
        part = Path(self.dir.name) / 'card.part'
        part.write_bytes(b'png')
        with patch.object(my_ads, 'examine_image', return_value={'width': 800, 'height': 600}):
            value, _ = self.store.set_card_image(part, 'mine.PNG')
        own = value['card']['image']
        self.assertRegex(own, r'^card-own-[0-9a-f]{8}\.png$')
        self.assertEqual(my_ads.card_file(value), own)
        self.assertTrue(second.exists())
        value = self.store.clear_card_image()
        self.assertIsNone(value['card']['image'])
        self.assertFalse((self.store.folder / own).exists())
        with self.assertRaises(ConfigError):
            self.store.update({'card': {'image': 'card-own-00000000.png'}})

    def test_plays_log(self):
        for i in range(3):
            my_ads.append_play(self.store.plays_path, {'kind': 'ad', 'id': 'x', 'at': 100. + i})
        with open(self.store.plays_path, 'a') as f:
            f.write('not json\n')
        self.assertEqual([r['at'] for r in self.store.plays(101)], [101., 102.])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name)
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                                 master=MasterConfig(socket_path=self.state / 'master.sock'),
                                 tv_thing=SimpleNamespace(base_url='http://127.0.0.1:8080/'))
        self.coordinator = Mock()
        self.coordinator.request.return_value = {'state': 'live', 'on_air': {'id': 'k1'},
                                                 'my_ads': {'active': True, 'state': 'ad', 'cued': None}}
        self.render = patch.object(my_ads, 'render_card', side_effect=lambda text, out: Path(out).write_bytes(b'\x89PNG'))
        self.render.start()
        with patch('roku_stream.api.MasterClient', return_value=Mock()):
            from roku_stream.api import handler_factory
            self.handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                coordinator=self.coordinator)
        self.store = MyAds(self.state / 'master.sock')

    def tearDown(self):
        self.render.stop()
        self.dir.cleanup()

    def handler(self, method, path, body=None, raw=None):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler._authorize = lambda: True
        handler._json = Mock()
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        handler.wfile = io.BytesIO()
        if raw is not None:
            handler.rfile = io.BytesIO(raw)
            handler.headers = {'Content-Length': str(len(raw))}
        else:
            handler._body = Mock(return_value=body or {})
        getattr(handler, 'do_' + method)()
        return handler

    def call(self, method, path, body=None, raw=None):
        handler = self.handler(method, path, body, raw)
        status, payload = handler._json.call_args[0]
        return int(status), payload

    def test_upload_lists_and_serves(self):
        info = {'duration': 15.0, 'width': 1280, 'height': 720, 'audio': True, 'lufs': -23.0, 'gain_db': 3.0}
        with patch.object(my_ads, 'examine_video', return_value=info), patch.object(my_ads, 'take_pictures', return_value=4):
            status, view = self.call('POST', '/v1/my-ads/upload?name=Big%20Sale.mov', raw=b'x' * 300000)
        self.assertEqual(status, 200, view)
        ad_id = view['added']
        listed = view['ads'][0]
        self.assertEqual((listed['id'], listed['name'], listed['present'], listed['allowed'], listed['played']['last']),
                         (ad_id, 'Big Sale', True, True, None))
        self.assertEqual((self.store.folder / f'{ad_id}.mov').stat().st_size, 300000)
        self.assertEqual(view['status']['state'], 'ad')
        served = self.handler('GET', f'/v1/my-ads/file/{ad_id}')
        headers = dict(c[0] for c in served.send_header.call_args_list)
        self.assertEqual((headers['Content-Type'], len(served.wfile.getvalue())), ('video/quicktime', 300000))
        self.assertEqual(self.call('GET', '/v1/my-ads/file/../../config.json')[0], 400)
        self.assertEqual(self.call('GET', f'/v1/my-ads/file/{"f" * 12}-0.jpg')[0], 404)

    def test_upload_refusals(self):
        status, body = self.call('POST', '/v1/my-ads/upload?name=notes.txt', raw=b'hello')
        self.assertEqual((status, body['error']['code']), (400, 'invalid_config'), body)
        with patch.object(my_ads, 'examine_video', side_effect=ConfigError('That file has no picture')):
            status, body = self.call('POST', '/v1/my-ads/upload?name=song.mp4', raw=b'x' * 10)
        self.assertEqual((status, body['error']['message']), (400, 'That file has no picture'))
        self.assertEqual([p.name for p in self.store.folder.iterdir() if not p.name.startswith('card-')], [],
                         'nothing left behind')

    def test_settings_edit_order_delete(self):
        for i in (1, 2):
            self.store.folder.mkdir(exist_ok=True)
            (self.store.folder / ad(i)['file']).write_bytes(b'v')
        self.store.save({'ads': [ad(1), ad(2)]})
        now = time.time()
        my_ads.append_play(self.store.plays_path, {'kind': 'ad', 'id': ad(1)['id'], 'at': now - 100, 'counted': True,
                                                   'seconds': 20, 'length': 20, 'complete': True})
        my_ads.append_play(self.store.plays_path, {'kind': 'card', 'at': now - 50, 'seconds': 12.5})
        status, view = self.call('POST', f'/v1/my-ads/ads/{ad(1)["id"]}', {'limit': {'count': 1, 'minutes': 60}})
        first = view['ads'][0]
        self.assertEqual((status, first['allowed'], round(first['again'] - now), first['played']['hour']), (200, False, 3500, 1))
        self.assertEqual(view['card']['seconds_today'], 12)
        self.assertEqual(view['recent'][0]['kind'], 'card', 'newest first')
        status, view = self.call('POST', '/v1/my-ads/order', {'ids': [ad(2)['id'], ad(1)['id']]})
        self.assertEqual([a['name'] for a in view['ads']], ['Ad 2', 'Ad 1'])
        status, view = self.call('POST', '/v1/my-ads', {'order': 'list', 'pip': {'corner': 'top-left'}, 'card': {'text': 'back soon'}})
        self.assertEqual((view['settings']['order'], view['settings']['pip']['corner'], view['settings']['pip']['size']),
                         ('list', 'top-left', 'medium'))
        self.assertTrue((self.store.folder / view['card']['file']).exists(), 'the new card is drawn before master is told')
        self.assertEqual(self.call('POST', '/v1/my-ads', {'card': {'image': 'card-own-00000000.png'}})[0], 400)
        status, view = self.call('DELETE', f'/v1/my-ads/ads/{ad(2)["id"]}')
        self.assertEqual(([a['name'] for a in view['ads']], (self.store.folder / ad(2)['file']).exists()), (['Ad 1'], False))
        self.assertEqual(self.call('DELETE', f'/v1/my-ads/ads/{ad(2)["id"]}')[0], 400)


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
        self.closed = False
        self.asked = []

    def frame(self, t):
        return self.buffer

    def ended(self, t):
        return t >= self.length

    def sound(self, t, size):
        self.asked.append(t)
        return bytes(size)

    def close(self):
        self.closed = True


class Tap:
    def __init__(self):
        self.mutes = []

    def gain(self, pts):
        return 0. if any(a <= pts < b for a, b in self.mutes) else 1.


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class BreakTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        output = SimpleNamespace(gst=GST, width=W, height=H, audio_caps='audio/x-raw',
                                 video_caps=f'video/x-raw,format=I420,width={W},height={H},framerate=30/1')
        with patch.object(ad_break.AdBreak, '_run', lambda self: None):   # no helper thread: the test is the helper
            self.b = ad_break.AdBreak(output, self.dir.name, Path(self.dir.name) / 'plays.jsonl')
        self.settings = validate({'pip': {'enabled': False}, 'ads': [ad(1), ad(2)]})
        self.b.configure(self.settings, {'mode': 'on'})
        self.tap = Tap()
        self.live = GST.Buffer.new_wrapped(bytes((200,)) * SIZE)

    def tearDown(self):
        self.dir.cleanup()

    def frame(self, t):
        """The frame shown at t seconds (the programme's pts and master's due alike)."""
        ns = int(t * 1e9)
        out = self.b.picture(self.live, ns, ns, (self.tap, 0, 1))
        return None if out is None else out.extract_dup(0, 1)[0]

    def cue(self, reel):
        self.b.cued = reel

    def test_a_break_plays_ads_then_the_card_then_the_programme(self):
        one, two = FakeReel(ad(1), int(1e9), 50), FakeReel(ad(2), int(1e9), 60)
        self.cue(one)
        self.tap.mutes.append((int(1e9), int(4e9)))
        self.assertIsNone(self.frame(.9))
        self.assertEqual(self.frame(1.0), 50)
        self.cue(two)
        self.assertEqual(self.frame(1.5), 50)
        self.assertEqual(self.frame(2.0), 60, 'the next ad at the end of the first')
        self.assertEqual(self.frame(3.0), 16, 'nothing cued: the card (blank before it is loaded)')
        self.assertIsNone(self.frame(4.0), 'the programme is back')
        self.assertEqual(self.b.state, 'idle')
        rows = list(self.b.log)
        self.assertEqual([(r['kind'], r.get('id'), r.get('complete'), r.get('counted'), r['seconds']) for r in rows],
                         [('ad', ad(1)['id'], True, True, 1.0), ('ad', ad(2)['id'], True, True, 1.0), ('card', None, None, None, 1.0)])
        self.assertEqual(list(self.b.done), [one, two], 'finished ads go to the helper to close')
        self.assertEqual(self.b.rotation.last, ad(2)['id'])

    def test_the_show_coming_back_cuts_an_ad_short(self):
        self.cue(FakeReel(ad(1), int(30e9), 50))
        self.tap.mutes.append((int(1e9), int(3e9)))
        self.assertEqual(self.frame(1.0), 50)
        self.assertIsNone(self.frame(3.0))
        row = self.b.log[-1]
        self.assertEqual((row['complete'], row['counted'], row['seconds']), (False, False, 2.0))

    def test_fillers_keep_the_break_and_switching_off_ends_it(self):
        self.cue(FakeReel(ad(1), int(30e9), 50))
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 50)
        filler = self.b.picture(self.live, int(1.2e9), None, None)
        self.assertEqual(filler.extract_dup(0, 1)[0], 50)
        self.b.configure(self.settings, {'mode': 'shadow'})
        self.assertIsNone(self.frame(1.5), 'shadow mutes nothing: nothing replaced')
        self.assertFalse(self.b.log[-1]['complete'])

    def test_a_card_gives_way_to_an_ad_once_one_is_ready(self):
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 16)
        self.cue(FakeReel(ad(1), int(30e9), 50))
        self.assertEqual(self.frame(1.5), 50)
        self.assertEqual(self.b.log[-1]['kind'], 'card')

    def test_a_failed_ad_gives_way(self):
        reel = FakeReel(ad(1), int(30e9), 50)
        self.cue(reel)
        self.tap.mutes.append((int(1e9), int(30e9)))
        self.assertEqual(self.frame(1.0), 50)
        reel.failed = 'decoder error'
        self.assertEqual(self.frame(1.1), 16)
        self.assertEqual((self.b.log[-1]['error'], self.b.log[-1]['counted']), ('decoder error', False))

    def test_sound_follows_the_ad_and_starts_the_break_too(self):
        reel = FakeReel(ad(1), int(30e9), 50)
        self.cue(reel)
        self.tap.mutes.append((int(1e9), int(30e9)))
        audio = bytes(960 * 8)
        self.assertIsNone(self.b.sound(int(.5e9), int(.5e9), self.tap.gain, audio), 'not muted: not mine')
        mine = self.b.sound(int(1.0e9), int(1.0e9), self.tap.gain, audio)
        self.assertEqual((len(mine), reel.asked, self.b.state), (len(audio), [0], 'ad'))
        self.assertEqual(self.frame(1.02), 50)

    def test_the_corner_shows_the_programme_framed(self):
        self.b.configure(validate({'pip': {'size': 'large'}}), {'mode': 'on'})
        pip = self.b.pip
        live = GST.Buffer.new_wrapped(bytes((200,)) * (W * H) + bytes((90,)) * (W * H // 2))
        self.tap.mutes.append((0, int(10e9)))
        out = self.b.picture(live, int(1e9), int(1e9), (self.tap, 0, 1)).extract_dup(0, SIZE)
        inside = (pip.y + pip.h - 2) * W + pip.x + pip.w - 2
        self.assertEqual((out[inside], out[(pip.y - 2) * W + pip.x], out[(pip.y + 2) * W + pip.x - 6]),
                         (200, ad_break.Pip.EDGE[0], 16), 'programme, white frame, the card around it')


if __name__ == '__main__':
    unittest.main()
