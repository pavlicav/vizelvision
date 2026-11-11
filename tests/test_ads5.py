"""Ads 5 (roku_stream/ads5*.py): the fork and its independence from VizelVision, settings, the
format's draw (idents and the station ID when due), Next up by hand, the splice of real encoded
clips into one stream with timestamps that run on, and the routes. Needs ffmpeg; run with the
system Python (promo overlays use cairo):
    /usr/bin/python3 -m unittest tests.test_ads5"""
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from roku_stream import ads5, ads5_prep
from roku_stream.ads5_ts import CLOCK, Splicer, first_pts
from roku_stream.errors import ConfigError

FFMPEG = shutil.which('ffmpeg') and shutil.which('ffprobe')


def write(path, value):
    path.write_text(json.dumps(value))


def fake_vizelvision(folder, n=8):
    (folder / 'my-ads').mkdir(parents=True)
    ads = []
    for i in range(n):
        ad_id = f'{i:012x}'
        (folder / 'my-ads' / f'{ad_id}.mp4').write_bytes(b'v')
        ads.append({'id': ad_id, 'name': f'ad {i}', 'file': f'{ad_id}.mp4', 'duration': 30.0, 'enabled': i != 3,
                    'limit': {'count': 1, 'minutes': 60} if i == 2 else None, 'gain_db': 1.0, 'trim_db': 0.0,
                    'audio': True, 'added': 1.0})
    write(folder / 'my-ads.json', {'enabled': True, 'order': 'shuffle', 'limits': True,
                                   'default_limit': {'count': 1, 'minutes': 30}, 'ads': ads})
    write(folder / 'my-ads-mix.json', {'enabled': True, 'tuning': {'rest_hours': 6},
                                       'categories': [{'key': 'cats', 'name': 'Cats', 'weight': 2, 'wear': 1, 'about': ''}],
                                       'ads': {ads[0]['id']: 'cats'}, 'overrides': {ads[1]['id']: {'boost': 2, 'wear': 1}}})
    write(folder / 'promos.json', {'enabled': True, 'every': 10, 'fill': False, 'promos': {'legal': {'enabled': False}}})
    return ads


class FakeClips:
    """Every clip ready, each 30 s (ads) or 10 s (idents), without encoding anything."""

    def __init__(self, store, promo_ids=('metro', 'legal')):
        self.store, self.promo_ids, self.wanted = store, promo_ids, []

    def spec(self, kind, item_id, *, start=None, ad=None):
        if kind == 'ad':
            ad = ad or self.store.ad(item_id)
            return ad and {'folder': Path(f'/clips/ad-{item_id}'), 'duration': ad['duration'], 'name': ad['name']}
        if kind == 'id':
            return {'folder': Path('/clips/id'), 'duration': 30.0, 'name': 'Station ID'}
        return {'folder': Path(f'/clips/{item_id}'), 'duration': 10.0, 'name': item_id} if item_id in self.promo_ids else None

    def meta(self, folder):
        seconds = 30.0 if 'ad-' in str(folder) or str(folder).endswith('/id') else 10.0
        return {'start': 0, 'span': int(seconds * CLOCK), 'seconds': seconds,
                'segments': [{'name': 's0.ts', 'seconds': seconds}]}

    def state(self, folder):
        return 'ready'

    def want(self, spec, priority):
        self.wanted.append((spec['name'], priority))


class Ads5Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = Path(self.dir.name)
        self.vv, self.state = root / 'vv', root / 'ads5'
        self.ads = fake_vizelvision(self.vv)
        self.store = ads5.Store(self.state, self.vv, promo_library=FakeLibrary())

    def vv_hashes(self):
        return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in self.vv.glob('*.json')}


class FakeLibrary:
    folder = Path('/nowhere')

    def read(self):
        return [{'id': pid, 'name': pid, 'kind': 'ident', 'duration': 10.0, 'file': pid + '.mp4', 'overlays': [],
                 'needs': [], 'leagues': [], 'season': None, 'present': True, 'description': '', 'still': None}
                for pid in ('metro', 'legal')]

    def path(self, name):
        return None


class ForkTests(Ads5Case):
    def test_fork_copies_vizelvisions_settings(self):
        s = self.store.settings()
        self.assertEqual(s['order'], 'mix')
        self.assertEqual(s['ident_every'], 10)
        self.assertTrue(s['limits'])
        self.assertEqual(s['default_limit'], {'count': 1, 'minutes': 30})
        self.assertFalse(s['ads'][self.ads[3]['id']]['enabled'])
        self.assertEqual(s['ads'][self.ads[2]['id']]['limit'], {'count': 1, 'minutes': 60})
        self.assertEqual(s['promos'], {'legal': {'enabled': False}})
        mix = self.store.mix()
        self.assertEqual(mix['tuning']['rest_hours'], 6)
        self.assertEqual(mix['ads'], {self.ads[0]['id']: 'cats'})
        self.assertEqual(mix['overrides'][self.ads[1]['id']]['boost'], 2)

    def test_changes_on_ads5_never_touch_vizelvision(self):
        before = self.vv_hashes()
        self.store.update({'ident_every': 2, 'order': 'list', 'limits_from': 'now'})
        self.store.set_ad(self.ads[0]['id'], {'enabled': False, 'limit': None, 'boost': 3})
        self.store.set_promo('metro', {'enabled': False})
        self.store.change_mix({'kinds': {'cats': {'weight': 7}}, 'tuning': {'rest_hours': 1}})
        self.store.log({'kind': 'ad', 'id': self.ads[0]['id'], 'at': time.time(), 'seconds': 30, 'length': 30, 'counted': True})
        self.assertEqual(self.vv_hashes(), before)
        self.assertFalse(self.store.ads()[0]['enabled'])
        self.assertEqual(self.store.mix()['categories'][0]['weight'], 7)
        self.assertEqual(self.store.mix()['overrides'][self.ads[0]['id']]['boost'], 3)

    def test_vizelvision_library_changes_reach_ads5_but_not_its_switches(self):
        data = json.loads((self.vv / 'my-ads.json').read_text())
        data['ads'][0]['enabled'] = False            # switched off on VizelVision
        data['ads'][0]['name'] = 'renamed'
        data['ads'].append({**data['ads'][1], 'id': 'ffffffffffff', 'file': 'ffffffffffff.mp4', 'name': 'new upload'})
        time.sleep(0.01)
        write(self.vv / 'my-ads.json', data)
        ads = {a['id']: a for a in self.store.ads()}
        self.assertTrue(ads[self.ads[0]['id']]['enabled'])
        self.assertEqual(ads[self.ads[0]['id']]['name'], 'renamed')
        self.assertTrue(ads['ffffffffffff']['enabled'])
        self.assertEqual(ads['ffffffffffff']['limit'], {'count': 1, 'minutes': 30})   # Ads 5's default limit

    def test_settings_are_checked(self):
        for bad in ({'ident_every': 500}, {'order': 'random'}, {'limits': 'yes'}, {'ads': {}}, {'nope': 1}):
            with self.assertRaises(ConfigError):
                self.store.update(bad)
        self.assertEqual(self.store.update({'ident_every': 0})['ident_every'], 0)
        lenient = ads5.validate({'ident_every': 'x', 'order': 'mix', 'extra': 1}, lenient=True)
        self.assertEqual(lenient['ident_every'], 5)


class FormatTests(Ads5Case):
    def channel(self, **settings):
        self.store.update({'limits': False, **settings})
        clips = FakeClips(self.store)
        channel = ads5.Channel(self.store, clips)
        channel.settings = self.store.settings()
        return channel

    def test_an_ident_every_n_minutes_of_ads(self):
        ch = self.channel(ident_every=2, station_id_every=0)
        self.store.log({'kind': 'promo', 'id': 'metro', 'at': time.time(), 'seconds': 10, 'length': 10, 'counted': True})
        ch._fill()
        kinds = [e['kind'] for e in ch.next]
        # 30 s ads: four of them make 2 minutes, then an ident (metro: legal is switched off on the fork)
        self.assertEqual(kinds[:5], ['ad', 'ad', 'ad', 'ad', 'promo'])
        self.assertEqual(ch.next[4]['id'], 'metro')

    def test_station_id_when_due_and_none_when_off(self):
        self.store.update({'station_id_every': 15})
        ch = self.channel(ident_every=0)
        self.store.log({'kind': 'id', 'id': 'station', 'at': time.time() - 15 * 60, 'seconds': 30, 'length': 30,
                        'counted': True})
        ch._fill()
        self.assertEqual(ch.next[0]['kind'], 'id')
        self.assertNotIn('promo', [e['kind'] for e in ch.next])
        ch = self.channel(ident_every=0, station_id_every=0, idents=False)
        ch._fill()
        self.assertEqual({e['kind'] for e in ch.next}, {'ad'})

    def test_switched_off_and_too_long_ads_sit_out(self):
        off = self.ads[0]['id']
        self.store.set_ad(off, {'enabled': False})
        ch = self.channel(ident_every=0, station_id_every=0, longest_ad=20)
        ch._fill()
        self.assertEqual(ch.next and [e for e in ch.next if e['kind'] == 'ad'], [])   # every ad is 30 s
        ch = self.channel(ident_every=0, station_id_every=0, longest_ad=0)
        for _ in range(5):
            ch.redraw()
            self.assertNotIn(off, [e['id'] for e in ch.next])

    def test_queue_by_hand_goes_first_and_survives_a_redraw_and_restart(self):
        ch = self.channel(ident_every=0, station_id_every=0)
        ch._fill()
        ch.queue_add('ad', self.ads[5]['id'])
        ch.queue_add('id', 'station', first=True)
        self.assertEqual([(e['kind'], e['by']) for e in ch.next[:2]], [('id', 'you'), ('ad', 'you')])
        ch.redraw()
        self.assertEqual([e['by'] for e in ch.next[:2]], ['you', 'you'])
        again = ads5.Channel(self.store, FakeClips(self.store))
        self.assertEqual([(e['kind'], e['id']) for e in again.next], [('id', 'station'), ('ad', self.ads[5]['id'])])
        key = ch.next[0]['key']
        self.assertEqual(ch.skip(key), 'skipped')
        self.assertEqual(ch.next[0]['id'], self.ads[5]['id'])
        with self.assertRaises(ConfigError):
            ch.queue_add('ad', 'nope')


@unittest.skipUnless(FFMPEG, 'needs ffmpeg')
class SpliceTests(unittest.TestCase):
    """Two real clips (a picture with sound, a picture without) encoded as Ads 5 encodes them,
    joined: the joined stream decodes cleanly and its timestamps never go back."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        root = Path(cls.dir.name)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x480:rate=30:duration=5',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=5', '-shortest', '-c:v', 'libx264',
                        '-c:a', 'aac', str(root / 'a.mp4')], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'smptebars=size=1920x1080:rate=25:duration=3.3',
                        '-c:v', 'libx264', str(root / 'b.mp4')], check=True)
        cls.metas = [ads5_prep.encode(root / 'a.mp4', root / 'ca', duration=5.0, level_db=-3, threads=2),
                     ads5_prep.encode(root / 'b.mp4', root / 'cb', duration=3.3, audio=False, threads=2)]
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_clips_are_described(self):
        a, b = self.metas
        self.assertEqual([s['name'] for s in a['segments']], ['s0000.ts', 's0001.ts', 's0002.ts'])
        self.assertAlmostEqual(a['seconds'], 5.0, delta=0.1)
        self.assertAlmostEqual(sum(s['seconds'] for s in a['segments']), a['span'] / CLOCK, places=3)
        self.assertAlmostEqual(b['seconds'], 3.3, delta=0.1)
        self.assertEqual(ads5_prep.read_meta(self.root / 'ca')['span'], a['span'])

    def test_joined_stream_runs_on(self):
        splicer, cursor, out = Splicer(), 123 * CLOCK, bytearray()
        for folder, meta in (('ca', self.metas[0]), ('cb', self.metas[1]), ('ca', self.metas[0])):
            delta = cursor - meta['start']
            for seg in meta['segments']:
                out += splicer.shift((self.root / folder / seg['name']).read_bytes(), delta)
            cursor += meta['span']
        joined = self.root / 'joined.ts'
        joined.write_bytes(bytes(out))
        self.assertEqual(first_pts(bytes(out[:188 * 200])), 123 * CLOCK)
        decode = subprocess.run(['ffmpeg', '-v', 'warning', '-i', str(joined), '-f', 'null', '-'],
                                capture_output=True, text=True)
        self.assertEqual(decode.returncode, 0)
        self.assertNotIn('discontinuity', decode.stderr.lower())
        self.assertNotIn('non-monoton', decode.stderr.lower())
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'packet=stream_index,dts,duration',
                                '-of', 'csv=p=0', str(joined)], capture_output=True, text=True).stdout
        last = {}
        for line in probe.splitlines():
            parts = line.split(',')
            if len(parts) < 3 or parts[1] == 'N/A':
                continue
            stream, dts, dur = parts[0], int(parts[1]), int(parts[2] or 0)
            if stream in last:
                self.assertGreaterEqual(dts, last[stream] - 1, f'stream {stream} goes back at {dts / CLOCK:.3f}')
                self.assertLess(dts - last[stream], 0.2 * CLOCK, f'stream {stream} gaps at {dts / CLOCK:.3f}')
            last[stream] = dts + dur
        self.assertAlmostEqual(last['0'] / CLOCK, cursor / CLOCK, delta=0.15)


class RouteTests(Ads5Case):
    def setUp(self):
        super().setUp()
        self.store.update({'limits': False, 'ident_every': 0, 'station_id_every': 0})
        self.clips = FakeClips(self.store)
        self.channel = ads5.Channel(self.store, self.clips)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ads5.make_handler(self.store, self.channel, self.clips))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}/ads5/'

    def call(self, path, body=None):
        req = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except Exception as exc:   # HTTPError carries the body
            return exc.code, json.loads(exc.read())

    def test_settings_route_redraws_next_up(self):
        self.channel._fill()
        status, body = self.call('v1/settings', {'ident_every': 1})
        self.assertEqual((status, body['settings']['ident_every']), (200, 1))
        self.assertEqual(self.store.settings()['ident_every'], 1)
        status, body = self.call('v1/settings', {'ident_every': -1})
        self.assertEqual(status, 400)
        self.assertIn('ident_every', body['error'])

    def test_next_and_status_routes(self):
        status, body = self.call('v1/next', {'op': 'add', 'kind': 'promo', 'id': 'metro', 'next': True})
        self.assertEqual(status, 200)
        self.assertEqual(body['status']['next'][0]['id'], 'metro')
        status, body = self.call('v1/status')
        self.assertEqual((status, body['name'], body['running']), (200, 'Ads 5', False))
        status, body = self.call('v1/next', {'op': 'dance'})
        self.assertEqual(status, 400)

    def test_index_playlist_and_page(self):
        with urlopen(self.base + 'index.m3u8', timeout=5) as r:
            self.assertIn(b'live.m3u8', r.read())
        with urlopen(self.base, timeout=5) as r:
            self.assertIn(b'Ads 5', r.read())


if __name__ == '__main__':
    unittest.main()
