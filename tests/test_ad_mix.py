"""The mix (ad_mix.py): kinds of ads in balance, the ads seen most rested, every knob of it
tunable; its file, the days-ahead preview, its routes, and master drawing Next up with it."""
import collections
import io
import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream import ad_mix, my_ads
from roku_stream.ad_mix import Exposure, Mix, MixStore, chance, seen, simulate, validate
from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError

NOW = 2_000_000_000.
DAY = 86400
TUNED = validate({})['tuning']


def ad(i, **extra):
    return {'id': f'{i:012x}', 'file': f'{i:012x}.mp4', 'duration': 20.0, 'name': f'Ad {i}', **extra}


def settings(*ads):
    return my_ads.validate({'ads': list(ads)})


def mix(kinds, weights=None, tuning=None, overrides=None, wear=None, **extra):
    """kinds: {key: [ad numbers]}."""
    weights, wear = weights or {}, wear or {}
    return validate({'enabled': True, 'tuning': tuning or {},
                     'categories': [{'key': k, 'name': k.title(), 'weight': weights.get(k, 1), 'wear': wear.get(k, 1)} for k in kinds],
                     'ads': {ad(i)['id']: k for k, ids in kinds.items() for i in ids},
                     'overrides': {ad(i)['id']: v for i, v in (overrides or {}).items()}, **extra})


def play(i, at):
    return {'kind': 'ad', 'id': ad(i)['id'], 'at': at, 'counted': True}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.log = Path(self.dir.name) / 'my-ads-plays.jsonl'
        self.mixer = Mix(self.log, rng=random.Random(4))

    def tearDown(self):
        self.dir.cleanup()

    def write(self, rows):
        with open(self.log, 'a') as f:
            for row in rows:
                f.write(json.dumps(row) + '\n')

    def draw(self, s, m, n, now=NOW, plays=()):
        """n picks as master draws them: each one counted as just played."""
        plays, out = list(plays), []
        for _ in range(n):
            pick = self.mixer.pick(s, plays, now, mix=m)
            if pick is None:
                break
            self.mixer.played(pick['id'])
            plays.append(play(int(pick['id'], 16), now))
            out.append(int(pick['id'], 16))
            now += 30
        return out

    def count(self, s, m, n=300, now=NOW):
        """n single picks, nothing played in between: who the chances favour."""
        counts = collections.Counter()
        for _ in range(n):
            self.mixer.last = None
            counts[int(self.mixer.pick(s, [], now, mix=m)['id'], 16)] += 1
        return counts


class SettingsTests(unittest.TestCase):
    def test_defaults_and_refusals(self):
        value = validate({})
        self.assertEqual((value['enabled'], value['categories'], value['ads'], value['overrides']), (False, [], {}, {}))
        self.assertEqual(value['tuning'], {k: v[0] for k, v in ad_mix.TUNING.items()})
        cat = {'key': 'cats', 'name': 'Cats'}
        for bad in ({'tuning': {'familiar': 0}}, {'tuning': {'curve': 9}}, {'tuning': {'loudness': 1}},
                    {'enabled': 'yes'}, {'categories': [{**cat, 'key': 'Cats!'}]}, {'categories': [cat, cat]},
                    {'categories': [{**cat, 'key': 'unsorted'}]}, {'categories': [{**cat, 'weight': 11}]},
                    {'categories': [{**cat, 'wear': 4}]}, {'categories': [{**cat, 'name': ''}]},
                    {'categories': [cat], 'ads': {ad(1)['id']: 'dogs'}}, {'overrides': {ad(1)['id']: {'boost': 6}}},
                    {'overrides': {ad(1)['id']: {'volume': 1}}}, {'surprise': 1}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                validate(bad)
        lenient = validate({'categories': [cat], 'ads': {ad(1)['id']: 'dogs', ad(2)['id']: 'cats'}, 'surprise': 1,
                            'tuning': {'familiar': 0, 'curve': 3, 'loudness': 1}, 'overrides': {ad(1)['id']: {'boost': 9}}},
                           lenient=True)
        self.assertEqual(lenient['ads'], {ad(2)['id']: 'cats'}, 'master keeps what it can read')
        self.assertEqual((lenient['tuning']['familiar'], lenient['tuning']['curve'], lenient['overrides']), (6., 3., {}))

    def test_the_old_rest_setting_becomes_the_tuning(self):
        self.assertEqual(validate({'rest': 'strong'})['tuning']['familiar'], 3.)
        self.assertEqual(validate({'rest': 'off'})['tuning']['curve'], 0.)
        self.assertEqual(validate({'rest': 'gentle', 'tuning': {'familiar': 20}})['tuning']['familiar'], 20., 'the tuning wins')
        self.assertNotIn('rest', validate({'rest': 'normal'}))

    def test_overrides_at_their_defaults_are_dropped_and_gone_ads_too(self):
        value = validate({'overrides': {ad(1)['id']: {'boost': 1, 'wear': 1}, ad(2)['id']: {'wear': 0}, ad(3)['id']: {'boost': 2}}},
                         ad_ids={ad(2)['id']})
        self.assertEqual(value['overrides'], {ad(2)['id']: {'boost': 1., 'wear': 0.}})

    def test_the_file_round_trips_and_master_reads_a_broken_one_as_off(self):
        with tempfile.TemporaryDirectory() as d:
            store, master = MixStore(Path(d) / 'master.sock'), MixStore(Path(d) / 'master.sock', lenient=True)
            self.assertFalse(store.read()['enabled'])
            store.save(mix({'cats': [1]}))
            self.assertEqual(master.read()['ads'], {ad(1)['id']: 'cats'})
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o660, 'master and the web app both read it')
            store.change(lambda m: m['tuning'].update(familiar=12))
            self.assertEqual(master.read()['tuning']['familiar'], 12.)
            store.path.write_text('{not json')
            self.assertFalse(master.read()['enabled'])
            with self.assertRaises(ValueError):
                store.read()


class ChanceTests(unittest.TestCase):
    def test_a_new_ad_is_one_a_worn_one_little(self):
        self.assertEqual(chance(0, None, NOW, TUNED), 1.)
        worn = [NOW - DAY - i * 3600 for i in range(40)]
        self.assertLess(chance(seen(worn, NOW), max(worn), NOW, TUNED), 1 / 50)
        self.assertGreater(chance(seen(worn, NOW), max(worn), NOW, {**TUNED, 'familiar': 12}),
                           chance(seen(worn, NOW), max(worn), NOW, TUNED))
        self.assertEqual(chance(seen(worn, NOW), None, NOW, {**TUNED, 'curve': 0}), 1., 'curve 0: never worn')

    def test_plays_fade_by_their_half_life(self):
        self.assertAlmostEqual(seen([NOW - 14 * DAY], NOW), .5)
        self.assertAlmostEqual(seen([NOW - 2 * DAY], NOW, 2), .5)
        worn = [NOW - 8 * 14 * DAY] * 40
        self.assertGreater(chance(seen(worn, NOW), None, NOW, TUNED), .9, 'a tired ad comes back')

    def test_the_rest_after_a_play(self):
        self.assertAlmostEqual(chance(0, NOW - 12 * 3600, NOW, TUNED), .25)
        self.assertEqual(chance(0, NOW - 30 * 3600, NOW, TUNED), 1.)
        self.assertEqual(chance(0, NOW - 60, NOW, {**TUNED, 'rest_hours': 0}), 1., 'rest 0: none')
        self.assertEqual(chance(0, NOW, NOW, TUNED), 1e-6, 'just aired: as good as out')

    def test_floor_wear_boost_and_new_uploads(self):
        lots = 100
        self.assertAlmostEqual(chance(lots, None, NOW, {**TUNED, 'floor': .2}), .2 + .8 / (1 + lots / 6) ** 2)
        self.assertEqual(chance(lots, None, NOW, TUNED, wear=0), 1., 'wear 0: never tires')
        self.assertAlmostEqual(chance(3, None, NOW, TUNED, wear=2), chance(6, None, NOW, TUNED))
        self.assertEqual(chance(0, None, NOW, TUNED, boost=2.5), 2.5)
        fresh = {**TUNED, 'new_days': 7, 'new_boost': 3}
        self.assertEqual(chance(0, None, NOW, fresh, added=NOW - 2 * DAY), 3.)
        self.assertEqual(chance(0, None, NOW, fresh, added=NOW - 9 * DAY), 1.)


class PickTests(Base):
    def test_kinds_take_turns_by_their_weights(self):
        s = settings(*(ad(i) for i in range(1, 13)))
        out = self.draw(s, mix({'a': range(1, 7), 'b': range(7, 13)}), 12)
        kinds = ['a' if i < 7 else 'b' for i in out]
        self.assertEqual(kinds.count('a'), 6)
        self.assertTrue(all(x != y for x, y in zip(kinds, kinds[1:])), kinds)
        self.mixer = Mix(self.log, rng=random.Random(4))
        out = self.draw(s, mix({'a': range(1, 7), 'b': range(7, 13)}, {'a': 2}), 9)
        self.assertEqual(sum(i < 7 for i in out), 6, 'twice the weight, twice the plays')

    def test_again_holds_back_the_kind_that_just_aired(self):
        s = settings(*(ad(i) for i in range(1, 13)))
        runs = lambda out: sum(1 for x, y in zip(out, out[1:]) if (x < 7) == (y < 7))
        loose = self.draw(s, mix({'a': range(1, 7), 'b': range(7, 13)}, {'a': 3}, tuning={'again': 0}), 8)
        self.mixer = Mix(self.log, rng=random.Random(4))
        strict = self.draw(s, mix({'a': range(1, 7), 'b': range(7, 13)}, {'a': 3}, tuning={'again': 3}), 8)
        self.assertGreater(runs(loose), runs(strict))

    def test_the_ads_seen_most_rest_and_a_favourite_does_not(self):
        s = settings(*(ad(i) for i in range(1, 5)))
        self.write([play(i, NOW - DAY - k * 600) for i in (1, 2) for k in range(60)])
        counts = self.count(s, mix({'a': [1, 2, 3, 4]}))
        self.assertGreater(counts[3] + counts[4], 290, counts)
        counts = self.count(s, mix({'a': [1, 2, 3, 4]}, overrides={1: {'wear': 0}}))
        self.assertGreater(counts[1], 60, 'never wears: as good as new')
        counts = self.count(s, mix({'a': [1, 2, 3, 4]}, wear={'a': 0}))
        self.assertTrue(all(counts[i] > 40 for i in (1, 2, 3, 4)), 'a kind that never wears: all alike')
        self.assertIn(self.draw(settings(ad(1), ad(2)), mix({'a': [1, 2]}), 1)[0], (1, 2), 'worn, but all there is: still airs')

    def test_boost_raises_an_ads_chance_and_zero_leaves_it_out(self):
        s = settings(*(ad(i) for i in range(1, 5)))
        self.assertGreater(self.count(s, mix({'a': [1, 2, 3, 4]}, overrides={1: {'boost': 5}}))[1], 150)
        self.assertNotIn(1, self.draw(s, mix({'a': [1, 2, 3, 4]}, overrides={1: {'boost': 0}}), 8))

    def test_new_uploads_get_their_boost(self):
        s = settings(ad(1, added=NOW - DAY), *(ad(i, added=NOW - 60 * DAY) for i in range(2, 6)))
        plain = self.count(s, mix({'a': range(1, 6)}))
        boosted = self.count(s, mix({'a': range(1, 6)}, tuning={'new_days': 7, 'new_boost': 5}))
        self.assertGreater(boosted[1], 2 * plain[1])

    def test_a_small_tired_kind_gives_way(self):
        s = settings(*(ad(i) for i in range(1, 8)))
        self.write([play(7, NOW - 3600)])
        recent = [play(7, NOW - 3600)] + [play(i, NOW - 600 * i) for i in range(1, 5)]   # small is behind
        self.assertNotIn(7, self.draw(s, mix({'big': range(1, 7), 'small': [7]}), 2, plays=recent),
                         'its one ad aired an hour ago: the big kind\'s fresh ones go instead')
        self.assertIn(7, self.draw(s, mix({'big': range(1, 7), 'small': [7]}), 4, now=NOW + DAY, plays=recent), 'rested, it is back')
        self.mixer = Mix(self.log, rng=random.Random(4))
        self.assertIn(7, self.draw(s, mix({'big': range(1, 7), 'small': [7]}, tuning={'tired': 0}), 1, plays=recent),
                      'tired 0: it never steps aside')

    def test_off_kinds_never_air_and_unsorted_ads_share_one_kind(self):
        s = settings(*(ad(i) for i in range(1, 5)))
        out = self.draw(s, mix({'a': [1, 2], 'b': [3]}, {'b': 0}), 6)
        self.assertNotIn(3, out)
        self.assertIn(4, out, 'ad 4 has no kind: unsorted')
        self.assertNotIn(4, self.draw(s, mix({'a': [1, 2], 'b': [3]}, tuning={'unsorted': 0}), 6), 'unsorted off')
        self.assertIsNone(Mix(self.log).pick(settings(ad(3)), [], NOW, mix=mix({'b': [3]}, {'b': 0})))

    def test_limits_and_skips_still_hold(self):
        s = settings(ad(1, limit={'count': 1, 'minutes': 60}), ad(2))
        m = mix({'a': [1, 2]})
        self.assertEqual(self.mixer.pick(s, [play(1, NOW - 60)], NOW, mix=m)['id'], ad(2)['id'])
        self.assertIsNone(self.mixer.pick(s, [play(1, NOW - 60)], NOW, skip={ad(2)['id']}, mix=m))

    def test_drawn_ahead_counts_as_just_played(self):
        self.assertEqual(sorted(self.draw(settings(ad(1), ad(2)), mix({'a': [1, 2]}), 2)), [1, 2])


class SimulateTests(unittest.TestCase):
    def setUp(self):
        self.settings = settings(*(ad(i, limit={'count': 1, 'minutes': 60}) for i in range(1, 41)))
        # Three weeks of breaks, 6 ads each, 30 a day; ads 1-5 aired far more than the rest.
        rng, self.rows, t = random.Random(1), [], NOW - 21 * DAY
        while t < NOW:
            for k in range(6):
                i = rng.choice(range(1, 6)) if rng.random() < .5 else rng.randint(6, 40)
                self.rows.append(play(i, t + 30 * k))
            t += DAY / 30
        self.kinds = {'a': range(1, 21), 'b': range(21, 41)}

    def test_pace_comes_from_the_log(self):
        breaks, per_break = ad_mix.pace(self.rows, NOW)
        self.assertAlmostEqual(breaks, 30, delta=1)
        self.assertEqual(per_break, 6)
        self.assertEqual(ad_mix.pace([], NOW), (40., 6), 'no log yet: a usual day')

    def test_the_mix_rests_the_worn_ads_the_shuffle_does_not(self):
        result = simulate(self.settings, self.rows, mix(self.kinds), NOW, days=3)
        self.assertEqual(set(result['worn'][:5]), {ad(i)['id'] for i in range(1, 6)})
        self.assertLess(result['mix']['worn_share'], result['shuffle']['worn_share'])
        self.assertEqual(result['mix']['plays'], result['shuffle']['plays'])
        self.assertAlmostEqual(result['mix']['kinds']['a'], .5, delta=.06)
        self.assertEqual(set(result['mix']), {'plays', 'distinct', 'ads', 'kinds', 'worn_share', 'seldom_share', 'most_in_a_day', 'gap_hours'})
        again = simulate(self.settings, self.rows, mix(self.kinds), NOW, days=3)
        self.assertEqual(again['mix']['ads'], result['mix']['ads'], 'the same draft, the same preview')

    def test_the_draft_shows_in_the_preview(self):
        base = simulate(self.settings, self.rows, mix(self.kinds), NOW, days=2)
        more = simulate(self.settings, self.rows, mix(self.kinds, {'a': 3}), NOW, days=2)
        self.assertGreater(more['mix']['kinds']['a'], base['mix']['kinds']['a'] + .05)
        keen = simulate(self.settings, self.rows, mix(self.kinds, {'a': 3}, tuning={'tired': 0}), NOW, days=2)
        self.assertGreater(keen['mix']['kinds']['a'], .7, 'nothing steps aside: kind a gets its three quarters')
        loved = simulate(self.settings, self.rows, mix(self.kinds, overrides={i: {'wear': 0} for i in range(1, 6)}), NOW, days=2)
        self.assertGreater(loved['mix']['worn_share'], base['mix']['worn_share'], 'never wears: the worn ones air again')


class ExposureTests(Base):
    def test_reads_what_was_appended_and_starts_again_when_replaced(self):
        e = Exposure(self.log)
        self.assertEqual(e.read(), {})
        self.write([play(1, 100.), {**play(2, 101.), 'counted': False, 'seconds': 2, 'length': 30}, {'kind': 'card', 'at': 102.}])
        with open(self.log, 'a') as f:
            f.write('{"kind": "ad", "id": "000000000001", "at": 1')
        self.assertEqual(e.read(), {ad(1)['id']: [100.]}, 'counted ad plays only; half a line waits')
        with open(self.log, 'a') as f:
            f.write('03.0, "counted": true}\n')
        self.assertEqual(e.read(), {ad(1)['id']: [100., 103.]})
        self.log.write_text(json.dumps(play(3, 200.)) + '\n')
        self.assertEqual(e.read(), {ad(3)['id']: [200.]})


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name)
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                                 master=MasterConfig(socket_path=self.state / 'master.sock'),
                                 tv_thing=SimpleNamespace(base_url='http://127.0.0.1:8080/'))
        coordinator = Mock()
        coordinator.request.return_value = {'state': 'live', 'my_ads': {'active': False, 'state': 'idle'}}
        with patch('roku_stream.api.MasterClient', return_value=Mock()):
            from roku_stream.api import handler_factory
            self.handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(), coordinator=coordinator)
        self.store = my_ads.MyAds(self.state / 'master.sock')
        self.store.save(my_ads.validate({'ads': [ad(1), ad(2), ad(3)]}))
        self.mix = MixStore(self.state / 'master.sock')
        self.mix.save(mix({'cats': [1], 'trains': [2]}))
        my_ads.append_play(self.store.plays_path, play(1, time.time() - 60))

    def tearDown(self):
        self.dir.cleanup()

    def call(self, method, path, body=None, raw=None):
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
        status, payload = handler._json.call_args[0]
        return int(status), payload

    def test_the_my_ads_view_has_each_ads_kind_chance_and_the_mix(self):
        status, view = self.call('GET', '/v1/my-ads')
        self.assertEqual(status, 200, view)
        byid = {a['id']: a for a in view['ads']}
        self.assertEqual([byid[ad(i)['id']]['category'] for i in (1, 2, 3)], ['cats', 'trains', None])
        self.assertEqual((byid[ad(1)['id']]['plays_all'], byid[ad(2)['id']]['chance'], byid[ad(1)['id']]['chance']), (1, 1.0, 0.0))
        m = view['mix']
        self.assertEqual([(c['key'], c['ads'], c['day']) for c in m['categories']], [('cats', 1, 1), ('trains', 1, 0)])
        self.assertEqual((m['unsorted'], m['aired_day'], m['enabled']), ({'ads': 1, 'day': 0, 'weight': 1.0}, 1, True))

    def test_the_mix_page_view(self):
        status, view = self.call('GET', '/v1/my-ads/mix')
        self.assertEqual(status, 200, view)
        self.assertEqual(view['mix']['tuning'], TUNED)
        self.assertEqual(set(view['ranges']['tuning']), set(ad_mix.TUNING))
        self.assertEqual([(a['id'], a['kind'], len(a['plays'])) for a in view['ads']],
                         [(ad(1)['id'], 'cats', 1), (ad(2)['id'], 'trains', 0), (ad(3)['id'], 'unsorted', 0)])
        self.assertEqual(view['pace'], {'breaks_a_day': 40.0, 'per_break': 6})

    def test_kinds_change_from_the_list_and_with_other_settings(self):
        status, view = self.call('POST', f'/v1/my-ads/ads/{ad(3)["id"]}', {'category': 'cats', 'name': 'Kitten'})
        self.assertEqual(status, 200, view)
        self.assertEqual(self.mix.read()['ads'][ad(3)['id']], 'cats')
        self.assertEqual(self.store.read()['ads'][2]['name'], 'Kitten')
        self.call('POST', f'/v1/my-ads/ads/{ad(3)["id"]}', {'category': None})
        self.assertNotIn(ad(3)['id'], self.mix.read()['ads'])
        self.assertEqual(self.call('POST', f'/v1/my-ads/ads/{ad(3)["id"]}', {'category': 'dogs'})[0], 400)
        self.assertEqual(self.call('POST', '/v1/my-ads/ads/ffffffffffff', {'category': 'cats'})[0], 400)

    def test_saving_the_mix(self):
        status, view = self.call('POST', '/v1/my-ads/mix?view=mix', {
            'enabled': False, 'tuning': {'familiar': 12, 'half_life_days': 30}, 'kinds': {'cats': {'weight': 2, 'wear': 0}},
            'overrides': {ad(2)['id']: {'wear': 0}, ad(3)['id']: {'boost': 3}}})
        self.assertEqual(status, 200, view)
        saved = self.mix.read()
        self.assertEqual((saved['enabled'], saved['tuning']['familiar'], saved['tuning']['half_life_days']), (False, 12., 30.))
        self.assertEqual((saved['categories'][0]['weight'], saved['categories'][0]['wear']), (2., 0.))
        self.assertEqual(saved['overrides'], {ad(2)['id']: {'boost': 1., 'wear': 0.}, ad(3)['id']: {'boost': 3., 'wear': 1.}})
        self.assertEqual(view['mix'], saved, 'view=mix: the page\'s view back')
        self.call('POST', '/v1/my-ads/mix', {'overrides': {ad(2)['id']: None}, 'weights': {'trains': 0.5}})
        saved = self.mix.read()
        self.assertEqual((list(saved['overrides']), saved['categories'][1]['weight']), ([ad(3)['id']], .5))
        for bad in ({}, {'weights': {'dogs': 1}}, {'kinds': {'cats': {'weight': 99}}}, {'tuning': {'familiar': -1}},
                    {'tuning': {'loudness': 1}}, {'overrides': {ad(1)['id']: {'boost': 9}}}, {'categories': []}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call('POST', '/v1/my-ads/mix', bad)[0], 400)
        self.assertEqual(self.mix.read(), saved, 'nothing refused is kept')

    def test_the_preview_saves_nothing(self):
        before = self.mix.read()
        status, result = self.call('POST', '/v1/my-ads/mix/preview', {'kinds': {'cats': {'weight': 3}}, 'days': 2})
        self.assertEqual(status, 200, result)
        self.assertEqual((result['days'], set(result)), (2., {'days', 'breaks_a_day', 'per_break', 'worn', 'mix', 'shuffle'}))
        self.assertGreater(result['mix']['plays'], 0)
        self.assertEqual(self.mix.read(), before)
        self.assertEqual(self.call('POST', '/v1/my-ads/mix/preview', {'days': 30})[0], 400)

    def test_an_upload_takes_a_kind_and_a_deleted_ad_leaves_the_mix(self):
        info = {'duration': 15.0, 'width': 1280, 'height': 720, 'audio': True, 'lufs': -23.0, 'gain_db': 3.0}
        with patch.object(my_ads, 'examine_video', return_value=info), patch.object(my_ads, 'take_pictures', return_value=4):
            status, view = self.call('POST', '/v1/my-ads/upload?name=Tabby.mp4&category=cats', raw=b'x' * 1000)
            self.assertEqual(status, 200, view)
            self.assertEqual(self.mix.read()['ads'][view['added']], 'cats')
            status, body = self.call('POST', '/v1/my-ads/upload?name=Rex.mp4&category=dogs', raw=b'x' * 1000)
            self.assertEqual(status, 400, 'an unknown kind is refused before the file is taken')
            self.assertEqual(len(self.store.read()['ads']), 4)
        self.call('DELETE', f'/v1/my-ads/ads/{ad(1)["id"]}')
        self.assertNotIn(ad(1)['id'], self.mix.read()['ads'])


try:
    from tests.test_my_ads import GST, W, H
    from roku_stream import ad_break
except Exception:  # no GStreamer here
    GST = None


@unittest.skipIf(GST is None, 'needs GStreamer (system python)')
class NextUpTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        folder = Path(self.dir.name)
        output = SimpleNamespace(gst=GST, width=W, height=H, audio_caps='audio/x-raw',
                                 video_caps=f'video/x-raw,format=I420,width={W},height={H},framerate=30/1')
        with patch.object(ad_break.AdBreak, '_run', lambda self: None):
            self.b = ad_break.AdBreak(output, folder, folder / 'my-ads-plays.jsonl')
        self.settings = my_ads.validate({'ads': [ad(i) for i in range(1, 7)]})
        self.store = MixStore(folder / 'master.sock')

    def tearDown(self):
        self.dir.cleanup()

    def drawn(self):
        self.b._keep_queue(self.settings, [], time.time())
        return [int(e['id'], 16) for e in self.b.queue if e['by'] == 'rotation']

    def test_master_draws_with_the_mix_when_it_is_on(self):
        self.store.save(mix({'a': [1, 2, 3], 'b': [4, 5, 6]}, {'b': 0}))
        self.assertTrue(set(self.drawn()) <= {1, 2, 3}, 'kind b is off')
        self.store.save({**self.store.read(), 'enabled': False})
        self.assertEqual(len(set(self.drawn())), self.b.AHEAD, 'the mix off: the shuffle draws again, every kind')


if __name__ == '__main__':
    unittest.main()
