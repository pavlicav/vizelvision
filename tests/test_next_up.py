"""Next up in breaks (ad_break.py): the rotation drawn ahead, entries skipped or queued by
hand, what is on air skipped, the next promo placed by its timing; and its route. The
break's tests need GStreamer: run them with the system Python,
    /usr/bin/python3 -m unittest tests.test_next_up"""
import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream import my_ads, promos
from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.my_ads import validate
from tests.test_my_ads import GST, H, SIZE, W, FakeReel, Tap, ad
from tests.test_promos import manifest

if GST is not None:
    from roku_stream import ad_break

S = 1_000_000_000
COLOURS = {'legal': 100, 'metro': 110, 'baseball': 120}


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class NextUpTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = Path(self.dir.name)
        self.output = SimpleNamespace(gst=GST, width=W, height=H, audio_caps='audio/x-raw',
                                      video_caps=f'video/x-raw,format=I420,width={W},height={H},framerate=30/1')
        self.ads = [ad(i) for i in range(1, 9)]
        for a in self.ads:
            (self.folder / a['file']).write_bytes(b'v')
        for name in COLOURS:
            (self.folder / f'{name}.mp4').write_bytes(b'v')
        self.promos = [promos._manifest(manifest('legal', duration=5.0), self.folder, 'legal'),
                       promos._manifest(manifest('metro', duration=5.0), self.folder, 'metro'),
                       promos._manifest(manifest('baseball', duration=5.0, leagues=['mlb']), self.folder, 'baseball')]
        self.b = self.make()
        self.settings()
        self.configure_promos()
        self.tap = Tap()
        self.live = GST.Buffer.new_wrapped(bytes((200,)) * SIZE)

    def make(self):
        with patch.object(ad_break.AdBreak, '_run', lambda self: None):   # no helper thread: the test is the helper
            b = ad_break.AdBreak(self.output, self.folder, self.folder / 'plays.jsonl')
        b._reel = self.reel
        b.last_promo = time.time() - 60      # not due
        return b

    def settings(self, ads=None, **extra):
        self.b.configure(validate({'pip': {'enabled': False}, 'ads': self.ads if ads is None else ads, **extra}), {'mode': 'on'})

    def configure_promos(self, **settings):
        self.b.configure_promos({'settings': promos.validate({'every': 5, **settings}), 'values': {}, 'promos': self.promos,
                                 'library': self.folder, 'variants': self.folder})

    def reel(self, entry):
        """A stand-in reel for an entry: an ad's colour is its number times ten, a promo's its own."""
        if entry['kind'] == 'ad':
            item = next(a for a in self.b.settings['ads'] if a['id'] == entry['id'])
            colour = int(item['id'], 16) * 10
        else:
            item, colour = self.b.library[entry['id']], COLOURS[entry['id']]
        reel = FakeReel(item, int(item['duration'] * S), colour)
        reel.entry = entry
        if entry['kind'] == 'promo':
            reel.path = self.b._promo_path(item, self.b.promo_values)
        return reel

    def help(self):
        """The helper thread's turn: Next up kept, its first cued, the next promo cued."""
        self.b._cue()
        self.b._cue_promo()

    def frame(self, t):
        out = self.b.picture(self.live, int(t * S), int(t * S), (self.tap, 0, 1))
        return None if out is None else out.extract_dup(0, 1)[0]

    def next(self, kind=None):
        return [r for r in self.b.status()['next'] if kind is None or r['kind'] == kind]

    def colour(self, row):
        return int(row['id'], 16) * 10

    # ------------------------------------------------------------------------------------------
    def test_the_rotation_is_drawn_ahead_and_its_first_is_cued(self):
        self.help()
        ads = self.next('ad')
        self.assertEqual(len(ads), 5)
        self.assertEqual(len({r['id'] for r in ads}), 5, 'shuffled: none twice')
        self.assertEqual([r['by'] for r in ads], ['rotation'] * 5)
        self.assertEqual([r['cued'] for r in ads], [True, False, False, False, False])
        self.assertEqual(self.b.cued.entry['key'], ads[0]['key'])
        self.tap.mutes.append((S, 60 * S))
        self.assertEqual(self.frame(1.0), self.colour(ads[0]))
        self.help()
        after = self.next('ad')
        self.assertEqual([r['id'] for r in after[:4]], [r['id'] for r in ads[1:]], 'the rest move up')
        self.assertEqual(len(after), 5, 'and one more is drawn')
        self.assertEqual(after[0]['in'], 20.0, 'in a break: when it starts if the break lasts')

    def test_skipping_an_entry_takes_it_out_of_the_round(self):
        self.help()
        first, second = self.next('ad')[:2]
        self.assertEqual(self.b.command({'op': 'skip', 'key': first['key']}), {'accepted': True, 'on_air': False})
        self.help()
        ads = self.next('ad')
        self.assertNotIn(first['id'], [r['id'] for r in ads])
        self.assertEqual((ads[0]['id'], ads[0]['cued']), (second['id'], True), 'the next is cued in its place')
        self.assertNotIn(first['id'], self.b.rotation.bag, 'out of this round')
        with self.assertRaises(ConfigError):
            self.b.command({'op': 'skip', 'key': first['key']})

    def test_queued_by_hand_goes_first_whatever_its_switch_or_limit(self):
        self.ads[2] = ad(3, enabled=False)
        self.settings()
        self.b.last_promo = None             # a promo is due
        self.help()
        self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(3)['id'], 'next': True})
        self.help()
        rows = self.next()
        self.assertEqual([(r['kind'], r['by']) for r in rows[:3]], [('ad', 'you'), ('promo', 'promos'), ('ad', 'rotation')])
        self.tap.mutes.append((S, 60 * S))
        self.assertEqual(self.frame(1.0), 30, 'what you queued, before the due promo')
        self.help()
        self.assertIn(self.frame(21.0), (100, 110), 'then the promo')
        self.assertEqual(self.b.log[0]['queued'], True)

    def test_queueing_a_drawn_ad_by_hand_moves_it_up(self):
        self.settings([ad(i) for i in range(1, 4)])     # no limits: only the move keeps it from airing twice
        self.help()
        third = self.next('ad')[2]
        self.b.command({'op': 'add', 'kind': 'ad', 'id': third['id'], 'next': True})
        self.assertEqual([r['id'] for r in self.next('ad')].count(third['id']), 1)
        self.assertEqual(self.next('ad')[0]['by'], 'you')

    def test_add_to_queue_goes_after_the_others_queued_by_hand(self):
        self.help()
        for i in (4, 5):
            self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(i)['id']})
        self.b.command({'op': 'add', 'kind': 'promo', 'id': 'metro'})
        self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(6)['id'], 'next': True})
        self.help()
        mine = [(r['kind'], r['id']) for r in self.next() if r['by'] == 'you']
        self.assertEqual(mine, [('ad', ad(6)['id']), ('ad', ad(4)['id']), ('ad', ad(5)['id']), ('promo', 'metro')])
        self.assertEqual(len(self.next('ad')) - 3, 5, 'the rotation still has five ahead')

    def test_a_promo_queued_by_hand_plays_as_an_item_and_counts(self):
        self.help()
        self.b.command({'op': 'add', 'kind': 'promo', 'id': 'metro', 'next': True})
        self.help()
        self.tap.mutes.append((S, 60 * S))
        self.assertEqual(self.frame(1.0), 110)
        self.assertEqual(self.b.state, 'promo')
        self.help()
        self.frame(6.0)
        self.assertEqual((self.b.log[0]['kind'], self.b.log[0]['counted']), ('promo', True))
        self.assertGreater(self.b.last_promo, time.time() - 5, 'it was the break\'s promo')

    def test_skipping_what_is_on_air(self):
        self.help()
        first, second = self.next('ad')[:2]
        self.tap.mutes.append((S, 60 * S))
        self.assertEqual(self.frame(1.0), self.colour(first))
        self.help()
        on_air = self.b.status()['ad']
        self.assertEqual((on_air['key'], on_air['by']), (first['key'], 'rotation'))
        self.assertEqual(self.b.command({'op': 'skip', 'key': first['key']}), {'accepted': True, 'on_air': True})
        self.assertEqual(self.frame(3.0), self.colour(second), 'cut at the next frame: the next goes on')
        row = self.b.log[0]
        self.assertEqual((row['id'], row['skipped'], row['complete'], row['counted'], row['seconds']),
                         (first['id'], True, False, False, 2.0))

    def test_a_promo_skipped_on_air_is_the_break_s_promo_and_the_ads_follow(self):
        self.b.last_promo = None
        self.help()
        self.tap.mutes.append((S, 60 * S))
        self.assertIn(self.frame(1.0), (100, 110))
        self.help()                          # the next promo is cued already
        self.assertIsNotNone(self.b.cued_promo)
        key, first = self.b.status()['promo']['key'], self.next('ad')[0]
        self.b.command({'op': 'skip', 'key': key})
        self.assertEqual(self.frame(1.5), self.colour(first), 'an ad, not another promo')
        self.assertEqual((self.b.log[0]['skipped'], self.b.log[0]['counted']), (True, True))

    def test_skipping_the_next_promo_brings_another(self):
        self.configure_promos()
        self.help()
        promo = self.next('promo')[0]
        self.b.command({'op': 'skip', 'key': promo['key']})
        self.help()
        other = self.next('promo')[0]
        self.assertNotEqual(other['id'], promo['id'])
        self.assertEqual(self.b.cued_promo.entry['key'], other['key'])

    def test_the_promo_shows_where_it_would_go_on(self):
        self.configure_promos()
        self.help()
        rows = self.next()
        self.assertEqual((rows[0]['kind'], rows[0]['opens']), ('promo', True), 'between breaks: it opens the next one')
        self.assertAlmostEqual(rows[0]['due_at'], self.b.last_promo + 300, places=0)
        self.tap.mutes.append((S, 120 * S))
        self.b.last_promo = time.time() - 270    # due in 30 s
        self.frame(1.0)                      # a 20 s ad goes on
        self.help()
        rows = self.next()
        self.assertEqual([r['kind'] for r in rows[:3]], ['ad', 'promo', 'ad'], 'after the ad that ends past its due time')
        self.assertEqual((rows[1]['in'], rows[1]['opens']), (40.0, False))

    def test_the_rotation_never_queues_an_ad_past_its_limit(self):
        self.settings([ad(1, limit={'count': 1, 'minutes': 60}), ad(2)])
        self.help()
        self.assertEqual([r['id'] for r in self.next('ad')].count(ad(1)['id']), 1)
        self.assertEqual(len(self.next('ad')), 5, 'the other, unlimited, fills Next up')

    def test_a_new_list_order_redraws_after_the_last_that_aired(self):
        self.settings(order='list')
        self.help()
        self.assertEqual([r['id'] for r in self.next('ad')], [ad(i)['id'] for i in range(1, 6)])
        self.tap.mutes.append((S, 60 * S))
        self.assertEqual(self.frame(1.0), 10)
        self.settings(self.ads[::-1], order='list')
        self.help()
        self.assertEqual([r['id'] for r in self.next('ad')], [ad(i)['id'] for i in (8, 7, 6, 5, 4)])

    def test_what_is_queued_by_hand_survives_a_restart(self):
        self.help()
        self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(2)['id']})
        self.b.command({'op': 'add', 'kind': 'promo', 'id': 'legal'})
        self.b._save_queue()
        again = self.make()
        self.assertEqual([(e['kind'], e['id'], e['by']) for e in again.queue],
                         [('ad', ad(2)['id'], 'you'), ('promo', 'legal', 'you')])

    def test_a_wait_fill_passes_over_a_long_ad_queued_by_hand(self):
        self.ads[0] = ad(1, duration=60.0)
        self.settings()
        self.help()
        self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(1)['id'], 'next': True})
        self.b.fill_start(10 * S)
        self.help()
        short = next(r for r in self.next('ad') if r['by'] == 'rotation')
        self.assertEqual(self.b.cued.entry['key'], short['key'])
        self.assertEqual(self.b.picture(self.live, 10 * S, 10 * S, (None, 0, 7)).extract_dup(0, 1)[0], self.colour(short))
        self.assertEqual(self.next('ad')[0]['id'], ad(1)['id'], 'it waits for a real break')

    def test_refusals(self):
        self.help()
        for body in ({'op': 'add', 'kind': 'ad', 'id': 'f' * 12}, {'op': 'add', 'kind': 'promo', 'id': 'nope'},
                     {'op': 'add', 'kind': 'promo', 'id': 'baseball'}, {'op': 'add', 'kind': 'card', 'id': 'x'},
                     {'op': 'add', 'kind': 'ad', 'id': ad(1)['id'], 'next': 'yes'}, {'op': 'skip', 'key': 'zz'},
                     {'op': 'shuffle'}):
            with self.subTest(body=body), self.assertRaises(ConfigError):
                self.b.command(body)
        try:
            self.b.command({'op': 'add', 'kind': 'promo', 'id': 'baseball'})
        except ConfigError as exc:
            self.assertIn('only during MLB games', str(exc))
        for _ in range(ad_break.AdBreak.QUEUED_MOST):
            self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(1)['id']})
        with self.assertRaises(ConfigError):
            self.b.command({'op': 'add', 'kind': 'ad', 'id': ad(1)['id']})


class NextUpApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        state = Path(self.dir.name)
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                                 master=MasterConfig(socket_path=state / 'master.sock'),
                                 tv_thing=SimpleNamespace(base_url='http://127.0.0.1:8080/'))
        coordinator = Mock()
        coordinator.request.return_value = {'state': 'live', 'my_ads': {'active': True, 'state': 'idle', 'next': []}}
        self.worker = Mock()
        self.worker.request.return_value = {'accepted': True, 'key': 'k1',
                                            'my_ads': {'state': 'idle', 'next': [{'key': 'k1', 'kind': 'ad'}]}}
        with patch('roku_stream.api.MasterClient', return_value=self.worker):
            from roku_stream.api import handler_factory
            self.handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                coordinator=coordinator)

    def call(self, path, body):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler._authorize = lambda: True
        handler._json = Mock()
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        handler.wfile = io.BytesIO()
        handler._body = Mock(return_value=body)
        handler.do_POST()
        status, payload = handler._json.call_args[0]
        return int(status), payload

    def test_commands_go_to_master_and_the_view_has_its_fresh_next_up(self):
        status, view = self.call('/v1/my-ads/next', {'op': 'add', 'kind': 'ad', 'id': 'a' * 12, 'next': True})
        self.assertEqual(status, 200, view)
        self.worker.request.assert_called_once_with('my_ads', {'op': 'add', 'kind': 'ad', 'id': 'a' * 12, 'next': True})
        self.assertEqual((view['result'], view['status']['next']), ({'accepted': True, 'key': 'k1'}, [{'key': 'k1', 'kind': 'ad'}]))
        self.assertIn('list', view['promos'], 'the promos, for the picker')

    def test_refusals(self):
        self.assertEqual(self.call('/v1/my-ads/next', {'op': 'clear'})[0], 400)
        self.assertEqual(self.call('/v1/my-ads/next', {'op': 'skip', 'key': 'k', 'force': True})[0], 400)
        self.worker.request.side_effect = ConfigError('That is no longer in Next up')
        status, body = self.call('/v1/my-ads/next', {'op': 'skip', 'key': 'k'})
        self.assertEqual((status, body['error']['message']), (400, 'That is no longer in Next up'))


if __name__ == '__main__':
    unittest.main()
