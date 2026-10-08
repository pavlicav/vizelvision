"""Ad mute's overlays: score bugs, network/station logos and YouTube TV's ad label
(admute/overlays.py), and what the detector and the policy do with them.

  /home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_overlays
"""
import json
import math
import os
import tempfile
import unittest

try:
    import numpy as np
except ImportError:  # the system Python (unittest discover): these run under conda
    raise unittest.SkipTest("needs numpy: run with /home/vivian/miniconda3/bin/python3")

from admute import detector as D, features as F, overlays as OV, train
from admute.policy import Policy, PolicyConfig

H, W = F.tap.H, F.tap.W
LOGO = (280, 8, 310, 24)          # x0, y0, x1, y1: a station bug, top right
TICKER = (0, 164, W, 180)          # a crawl along the bottom, the frame's whole width


def logo_on(m, box=LOGO, dx=0, dy=0):
    """Draw an opaque bug: a filled box (no edges inside) with an outline and a bar."""
    x0, y0, x1, y1 = box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy
    m[y0:y1, x0:x1] = False
    m[y0, x0:x1] = m[y1 - 1, x0:x1] = True
    m[y0:y1, x0] = m[y0:y1, x1 - 1] = True
    m[(y0 + y1) // 2, x0 + 4:x1 - 4] = True
    return m


def ticker_on(m, rng):
    x0, y0, x1, y1 = TICKER
    m[y0, :] = m[y1 - 1, :] = True
    m[y0 + 1:y1 - 1, :] = rng.random((y1 - y0 - 2, W)) < 0.4
    return m


def picture(rng, density=0.15):
    return rng.random((H, W)) < density


def pack(m):
    return np.packbits(m.ravel())


def overlay_from(maps, box=LOGO, kind="channel", **kw):
    x0, y0, x1, y1 = box
    crops = np.array([m[y0:y1, x0:x1] for m in maps])
    on, off, _ = OV.template(crops, crops.mean(0) >= OV.SEED_FREQ)
    return OV.Overlay(id=kw.pop("id", "bug"), name=kw.pop("name", "Test bug"), kind=kind, box=box, on=on, off=off, **kw)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(3)
        self.ov = overlay_from([logo_on(picture(self.rng)) for _ in range(60)])

    def test_up_over_any_picture_and_a_little_off_place(self):
        for dx, dy in ((0, 0), (2, -1), (-2, 2)):
            with self.subTest(dx=dx, dy=dy):
                self.assertTrue(self.ov.up(logo_on(picture(self.rng), dx=dx, dy=dy)))
        self.assertFalse(self.ov.up(logo_on(picture(self.rng), dy=5)), "too far from where it sits")

    def test_down_over_busy_and_flat_pictures(self):
        for density in (0.0, 0.15, 0.4):
            with self.subTest(density=density):
                self.assertFalse(self.ov.up(picture(self.rng, density)))

    def test_json_round_trip(self):
        ov = OV.Overlay.from_json(json.loads(json.dumps(self.ov.to_json())))
        self.assertEqual(ov.box, self.ov.box)
        self.assertTrue((ov.on == self.ov.on).all() and (ov.off == self.ov.off).all())
        self.assertTrue(ov.up(logo_on(picture(self.rng))))

    def test_strong_level(self):
        ov = OV.Overlay.from_json({**self.ov.to_json(), "strong": 0.95})
        self.assertEqual(ov.level(picture(self.rng)), 0)
        m = logo_on(picture(self.rng))
        self.assertEqual(ov.level(m), 2 if ov.score(m) >= 0.95 else 1)


class CandidateTests(unittest.TestCase):
    def freqs(self, n=300, ticker=True, logo_in_ads=False):
        rng = np.random.default_rng(5)
        show = [logo_on(ticker_on(picture(rng), rng) if ticker else picture(rng)) for _ in range(n)]
        ads = [ticker_on(picture(rng), rng) if ticker else picture(rng) for _ in range(n // 2)]
        if logo_in_ads:
            ads = [logo_on(m) for m in ads]
        return np.mean(show, 0), np.mean(ads, 0), len(ads)

    def test_a_bug_in_the_programme_is_a_candidate_and_the_ticker_is_not(self):
        fs, fa, na = self.freqs()
        boxes = OV.candidates(fs, fa, na)
        self.assertTrue(any(OV.iou(b, LOGO) > 0.5 for b in boxes), boxes)
        self.assertFalse(any(b[1] >= 150 for b in boxes), f"the ticker became an overlay: {boxes}")

    def test_the_ticker_is_a_band_even_before_any_break_is_known(self):
        fs, _, _ = self.freqs()
        self.assertFalse(any(b[1] >= 150 for b in OV.candidates(fs)))

    def test_a_bug_up_in_the_breaks_too_is_not_a_candidate(self):
        fs, fa, na = self.freqs(logo_in_ads=True)
        self.assertFalse(any(OV.iou(b, LOGO) > 0.5 for b in OV.candidates(fs, fa, na)))

    def test_a_line_along_the_frame_does_not_swallow_a_bug_by_it(self):
        fs, fa, na = self.freqs(ticker=False)
        fs[5, :] = 0.5          # a line along the picture's top edge, as on NBC's SNF tape
        self.assertTrue(any(OV.iou(b, LOGO) > 0.5 for b in OV.candidates(fs, fa, na)))


class LearnTests(unittest.TestCase):
    def tape(self, seconds=400, set_piece=False):
        """Packed edge maps (2/s), labels and step cuts: show with the bug, a break of
        ads without it (the ticker runs throughout); a cut every 5 s."""
        rng = np.random.default_rng(7)
        maps, labels = [], []
        for i in range(seconds * 2):
            ad = 200 <= i // 2 < 260
            m = ticker_on(picture(rng), rng)
            if not ad:
                logo_on(m)
                if set_piece and (i // 10) % 2 == 0:          # one camera's shot only
                    logo_on(m, box=(20, 140, 60, 160))
            maps.append(pack(m))
            labels.append(1 if ad else 0)
        cut = np.zeros(seconds * 10)
        cut[np.arange(25, seconds * 10, 50)] = 60.0
        return np.array(maps), np.array(labels, np.int8), cut

    def test_learns_the_bug_with_its_rates(self):
        maps, labels, cut = self.tape()
        got = OV.learn(maps, labels, cut=cut)
        self.assertEqual(len(got), 1, [g["overlay"].box for g in got])
        g = got[0]
        self.assertGreater(OV.iou(g["overlay"].box, LOGO), 0.5)
        self.assertGreater(g["show"], 0.95)
        self.assertEqual(g["ad"], 0.0)
        self.assertGreaterEqual(g["cuts"][1], OV.CUT_KEPT * g["cuts"][0])

    def test_a_set_piece_that_goes_with_the_shot_is_left_out(self):
        maps, labels, cut = self.tape(set_piece=True)
        # cuts land where the camera changes (every 5 s: maps 10, 20, ...)
        cut = np.zeros(len(maps) * 5)
        cut[np.arange(50, len(cut), 50)] = 60.0
        boxes = [g["overlay"].box for g in OV.learn(maps, labels, cut=cut)]
        self.assertTrue(any(OV.iou(b, LOGO) > 0.5 for b in boxes))
        self.assertFalse(any(b[1] >= 130 for b in boxes), boxes)


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(11)
        self.lib = OV.Library(catalogue=None)
        self.bug = overlay_from([logo_on(picture(self.rng)) for _ in range(60)], kind="score", name="Score bug")
        self.lib.add(self.bug)

    def feed(self, tr, seconds, up=True, settle=None, clear=False, t0=0):
        for s in range(t0, t0 + seconds):
            for _ in range(2):
                m = picture(self.rng)
                if up:
                    logo_on(m)
                tr.see(m, pack(m))
            if settle is not None:
                tr.settle(s, settle, clear_ad=clear)

    def test_features_while_up_nothing_otherwise(self):
        tr = OV.Tracker(self.lib)
        self.feed(tr, 5, up=True)
        self.feed(tr, 5, up=False, t0=5)
        self.assertEqual(tr.features(2)["ov_score"], 1.0)
        self.assertTrue(math.isnan(tr.features(8)["ov_score"]))
        self.assertTrue(math.isnan(tr.features(2)["ov_logo"]))
        self.assertEqual(tr.showing(2, "score"), "Score bug")

    def test_with_no_game_on_a_score_bug_is_a_logo(self):
        # 2026-10-08: a WJLA "score bug" (a news graphic) matched an ad's fine print on The View.
        tr = OV.Tracker(self.lib)
        tr.game = False
        self.feed(tr, 5, up=True)
        self.assertTrue(math.isnan(tr.features(2)["ov_score"]))
        self.assertEqual(tr.features(2)["ov_logo"], 1.0)
        self.assertIsNone(tr.showing(2, "score"), "no mute is barred")
        tr.game = True
        self.assertEqual(tr.features(2)["ov_score"], 1.0)

    def test_a_flash_is_not_up(self):
        tr = OV.Tracker(self.lib)
        self.feed(tr, 2, up=False)
        m = logo_on(picture(self.rng))
        tr.see(m, pack(m))                      # one map
        self.feed(tr, 3, up=False, t0=3)
        self.assertTrue(all(math.isnan(tr.features(s)["ov_score"]) for s in range(5)))

    def test_up_during_clear_ads_it_stops_counting_and_twice_is_rejected(self):
        for session in (1, 2):
            tr = OV.Tracker(self.lib)
            self.feed(tr, 30, up=True, settle=1, clear=True)
            self.assertIn(self.bug.id, tr.distrusted)
            self.assertTrue(math.isnan(tr.features(29)["ov_score"]))
        self.assertEqual(self.lib.items[self.bug.id].status, "rejected")
        self.assertNotIn(self.bug.id, OV.Tracker(self.lib).watch)

    def test_the_operators_it_is_an_ad_counts_as_clear(self):
        tr = OV.Tracker(self.lib)
        tr.mark("ad", 0, 30)
        self.feed(tr, 30, up=True, settle=-1)
        self.assertIn(self.bug.id, tr.distrusted)

    def test_down_during_clear_ads_keeps_its_trust(self):
        tr = OV.Tracker(self.lib)
        self.feed(tr, 30, up=False, settle=1, clear=True)
        self.feed(tr, 30, up=True, settle=0, t0=30)
        self.assertNotIn(self.bug.id, tr.distrusted)


class LiveLearningTests(unittest.TestCase):
    def run_input(self, set_piece=False, logo_in_ads=False, seconds=760):
        """An input whose detector settles seconds 60 s late: programme with a bug (and a
        ticker), a 60 s break every 5 min. A cut every 5 s."""
        rng = np.random.default_rng(13)
        lib = OV.Library(catalogue=None)
        tr = OV.Tracker(lib, channel="TBS")
        label = lambda s: 1 if s % 300 >= 240 else 0          # noqa: E731
        for s in range(seconds):
            for k in range(2):
                m = ticker_on(picture(rng), rng)
                if label(s) == 0 or logo_in_ads:
                    logo_on(m)
                if set_piece and label(s) == 0 and (s // 5) % 2 == 0:
                    logo_on(m, box=(20, 120, 60, 140))
                tr.see(m, pack(m))
            if s >= 60:
                tr.settle(s - 60, label(s - 60), cut=(s - 60) % 5 == 4)
            tr.learn(float(s))
        return lib, tr

    def test_a_bug_up_in_the_programme_only_is_learnt_and_kept(self):
        lib, tr = self.run_input()
        live = [ov for ov in lib.items.values() if ov.origin == "live"]
        self.assertEqual(len(live), 1, [(o.box, o.status, o.note) for o in lib.items.values()])
        ov = live[0]
        self.assertEqual(ov.status, "active")
        self.assertIn("TBS", ov.channels)
        self.assertGreater(OV.iou(ov.box, LOGO), 0.5)
        self.assertIn(ov.id, tr.trusted)
        with tempfile.TemporaryDirectory() as d:
            lib.path = os.path.join(d, "admute-overlays.json")
            lib.save()
            again = OV.Library(path=lib.path, catalogue=None)
            self.assertEqual(again.items[ov.id].status, "active")
            self.assertIn(ov.id, OV.Tracker(again).trusted, "the next time it counts from the start")

    def test_another_channels_overlay_in_the_same_place_does_not_block_learning(self):
        rng = np.random.default_rng(21)
        other = overlay_from([logo_on(picture(rng), box=(280, 8, 316, 28)) for _ in range(60)], box=(280, 8, 316, 28),
                             kind="score", id="nbc", name="NBC bug", channels=["NBC"])
        lib = OV.Library(catalogue=None)
        lib.add(other)
        tr = OV.Tracker(lib, channel="TBS")
        label = lambda s: 1 if s % 300 >= 240 else 0          # noqa: E731
        for s in range(760):
            for k in range(2):
                m = ticker_on(picture(rng), rng)
                if label(s) == 0:
                    logo_on(m)
                tr.see(m, pack(m))
            if s >= 60:
                tr.settle(s - 60, label(s - 60), cut=(s - 60) % 5 == 4)
            tr.learn(float(s))
        live = [ov for ov in lib.items.values() if ov.origin == "live" and ov.status == "active"]
        self.assertEqual(len(live), 1, [(o.id, o.box, o.status) for o in lib.items.values()])
        self.assertGreater(OV.iou(live[0].box, LOGO), 0.5)

    def test_nothing_from_the_ticker_or_a_bug_left_on_in_breaks(self):
        lib, tr = self.run_input(logo_in_ads=True)
        self.assertFalse([o for o in lib.items.values() if o.status == "active"])
        self.assertFalse(tr.trusted)

    def test_a_set_piece_is_rejected(self):
        lib, _ = self.run_input(set_piece=True)
        pieces = [o for o in lib.items.values() if o.box[1] >= 100]
        self.assertTrue(pieces, "it was looked at")
        self.assertTrue(all(o.status == "rejected" for o in pieces), [(o.box, o.status) for o in pieces])


class HomeTests(unittest.TestCase):
    """A programme's graphic is its channel's (2026-10-07: FS1's score bug, carried to TBS,
    matched a ro ad's corner text and held 29 s of it audible)."""

    def fs1_bug(self, rng, **kw):
        ov = overlay_from([logo_on(picture(rng)) for _ in range(60)], kind="score", id="live-fs1-280-8-27002",
                          name="FS1 · top right score bug", origin="live")
        d = {**ov.to_json(), "channels": ["FS1", "wjla_7_1", "TBS"], **kw}     # watched everywhere since
        return OV.Overlay.from_json(d)

    def run_tbs(self, lib, up_in_show, up_in_ads, seconds=760):
        rng = np.random.default_rng(31)
        tr = OV.Tracker(lib, channel="TBS")
        label = lambda s: 1 if s % 300 >= 240 else 0          # noqa: E731
        for s in range(seconds):
            for _ in range(2):
                m = picture(rng)
                if (up_in_ads if label(s) else up_in_show):
                    logo_on(m)
                tr.see(m, pack(m))
            if s >= 60:
                tr.settle(s - 60, label(s - 60), cut=(s - 60) % 5 == 4)
        return tr

    def test_it_counts_at_once_only_where_it_was_learnt(self):
        lib = OV.Library(catalogue=None)
        lib.add(self.fs1_bug(np.random.default_rng(30)))
        self.assertEqual(lib.items["live-fs1-280-8-27002"].home, ["FS1"], "from its id, not where it was carried")
        self.assertIn("live-fs1-280-8-27002", OV.Tracker(lib, channel="FS1").trusted)
        tbs = OV.Tracker(lib, channel="TBS")
        self.assertNotIn("live-fs1-280-8-27002", tbs.trusted)
        self.assertEqual(tbs.describe(0)[0]["state"], "checking")

    def test_up_in_this_channels_ads_it_is_ignored_here_only(self):
        lib = OV.Library(catalogue=None)
        lib.add(self.fs1_bug(np.random.default_rng(30)))
        tr = self.run_tbs(lib, up_in_show=False, up_in_ads=True)
        self.assertIn("not this channel's", tr.distrusted["live-fs1-280-8-27002"])
        self.assertTrue(all(math.isnan(tr.features(s)["ov_score"]) for s in range(240, 300)))
        ov = lib.items["live-fs1-280-8-27002"]
        self.assertEqual((ov.status, ov.strikes, ov.home), ("active", 0, ["FS1"]), "still FS1's")

    def test_proving_itself_here_it_counts_here_too(self):
        lib = OV.Library(catalogue=None)
        lib.add(self.fs1_bug(np.random.default_rng(30)))
        tr = self.run_tbs(lib, up_in_show=True, up_in_ads=False)
        self.assertIn("live-fs1-280-8-27002", tr.trusted)
        self.assertEqual(lib.items["live-fs1-280-8-27002"].home, ["FS1", "TBS"])
        with tempfile.TemporaryDirectory() as d:
            lib.path = os.path.join(d, "admute-overlays.json")
            lib.dirty = True
            lib.save()
            again = OV.Library(path=lib.path, catalogue=None)
            self.assertIn("live-fs1-280-8-27002", OV.Tracker(again, channel="TBS").trusted)

    def test_a_catalogue_entry_is_at_home_on_its_own_channels(self):
        with tempfile.TemporaryDirectory() as d:
            cat = os.path.join(d, "overlays.json")
            ov = self.fs1_bug(np.random.default_rng(30))
            entry = {**ov.to_json(), "id": "nbc-mlb-score", "origin": "catalogue", "channels": ["NBC", "WRC"]}
            entry.pop("home", None)
            with open(cat, "w") as f:
                json.dump({"overlays": [entry]}, f)
            saved = os.path.join(d, "admute-overlays.json")
            with open(saved, "w") as f:
                json.dump({"overlays": [{"id": "nbc-mlb-score", "origin": "catalogue", "status": "active",
                                         "channels": ["NBC", "WRC", "TBS", "FS1"]}]}, f)
            lib = OV.Library(path=saved, catalogue=cat)
            self.assertEqual(lib.items["nbc-mlb-score"].home, ["NBC", "WRC"])
            self.assertIn("nbc-mlb-score", OV.Tracker(lib, channel="NBC").trusted, "YouTube TV's NBC")
            self.assertIn("nbc-mlb-score", OV.Tracker(lib, channel="wrc_hd_4_1").trusted, "WRC over the antenna")
            self.assertNotIn("nbc-mlb-score", OV.Tracker(lib, channel="TBS").trusted)
            self.assertNotIn("nbc-mlb-score", OV.Tracker(lib, channel="wrcx_2").trusted, "a whole word only")

    def test_an_ad_label_counts_everywhere(self):
        lib = OV.Library(catalogue=None)
        label = overlay_from([logo_on(picture(np.random.default_rng(32))) for _ in range(60)], kind="ad",
                             id="yttv-sponsored", name="YouTube TV ad label", channels=["youtube-tv"], home=["youtube-tv"])
        lib.add(label)
        self.assertIn("yttv-sponsored", OV.Tracker(lib, channel="TBS").trusted)


class AdLabelTests(unittest.TestCase):
    def setUp(self):
        self.lib = OV.Library(catalogue=None)
        on = np.zeros((10, 20), bool)
        on[2:8, 2:18:2] = True
        self.label = OV.Overlay(id="pill", name="Ad label", kind="ad", box=(10, 10, 30, 20), on=on, off=~on,
                                space="pic", thresh=0.35, strong=0.5)
        self.lib.add(self.label)

    def pic(self, score):
        """A picture on which the label scores about ``score``."""
        m = np.zeros((OV.PIC, OV.PIC), bool)
        ys, xs = np.nonzero(self.label.on)
        keep = int(round(score * len(ys)))
        m[ys[:keep] + 10, xs[:keep] + 10] = True
        return m

    def test_hysteresis(self):
        tr = OV.Tracker(self.lib)
        for sc in (0.0, 0.4, 0.4, 0.4, 0.0, 0.4, 0.9, 0.4, 0.4, 0.0):
            tr.see_pic(self.pic(sc))
        ups = [tr.up_in("pill", s) for s in range(10)]
        self.assertEqual(ups, [False, False, False, False, False, True, True, True, True, False],
                         "weak alone (TBS's own graphics) never; weak by a clear one, yes")
        self.assertEqual(tr.features(6)["ov_ad"], 1.0)

    def test_a_score_bug_up_cancels_it(self):
        rng = np.random.default_rng(2)
        bug = overlay_from([logo_on(picture(rng)) for _ in range(60)], kind="score", id="sb", name="Score bug")
        self.lib.add(bug)
        tr = OV.Tracker(self.lib)
        for _ in range(4):
            tr.see_pic(self.pic(0.9))
            for _ in range(2):
                m = logo_on(picture(rng))
                tr.see(m, pack(m))
        self.assertIsNone(tr.showing(2, "ad"))
        self.assertTrue(math.isnan(tr.features(2)["ov_ad"]))
        self.assertEqual(tr.features(2)["ov_score"], 1.0)

    def test_up_during_clear_programme_it_stops_counting(self):
        tr = OV.Tracker(self.lib)
        for s in range(30):
            tr.see_pic(self.pic(0.9))
        tr.mark("show", 0, 30)
        for s in range(1, 29):
            tr.settle(s, 0)
        self.assertIn("pill", tr.distrusted)


def segment(t, p, seam=None, **kw):
    return D.Segment(t, t + 1, p, seam, **kw)


class PolicyTests(unittest.TestCase):
    def test_a_dark_frame_mid_break_ends_a_game_mute_only_after_a_typical_break(self):
        # 2026-10-07: TBS and FS1 breaks ran 121-162 s; at 100 s, dark frames 105-119 s in let
        # three promos through. A seam into what is only moderately ad-like ends it from 130 s.
        def at(t):
            pol = Policy(PolicyConfig(grace=0), gate=lambda w: "break")
            pol._open(0.0)
            pol.current.confirmed = True
            pol.step([segment(t, 1.0, "black", post_z=1.0)], t + 8)
            return pol.muted
        self.assertTrue(at(110.0), "a Fox News promo 110 s in stays muted")
        self.assertFalse(at(131.0), "past a typical break, the dark frame may be the return")

    def test_no_mute_starts_under_a_score_bug(self):
        pol = Policy(PolicyConfig(grace=0, open_at="any"))
        for t in range(10):
            pol.step([segment(t, 0.99, "black", overlay="NBC MLB score bug")], t + 5, ahead=[segment(t + 1, 0.99)])
        self.assertFalse(pol.muted)
        pol.step([segment(10, 0.99, "black")], 15, ahead=[segment(11, 0.99)])
        self.assertTrue(pol.muted, "once the bug has gone")

    def test_an_ad_label_mutes_at_once_and_holds(self):
        pol = Policy(PolicyConfig(grace=0, open_at="seam"))
        pol.need_seam = True                         # just unmuted: normally only a seam re-arms
        pol.step([segment(30, 0.4, ad_overlay="YouTube TV ad label")], 35, ahead=[segment(31, 0.2)])
        self.assertTrue(pol.muted)
        self.assertTrue(pol.current.confirmed)
        for t in range(31, 60):
            pol.step([segment(t, 0.1, ad_overlay="YouTube TV ad label")], t + 5, ahead=[segment(t + 1, 0.1)])
        self.assertTrue(pol.muted, "the label holds the mute whatever P(ad) says")
        pol.step([segment(60, 0.1, "black")], 65, ahead=[segment(61, 0.1)])
        self.assertFalse(pol.muted)

    def test_a_return_needs_only_the_next_few_seconds_to_agree(self):
        pol = Policy(PolicyConfig(grace=0, open_at="any"))
        pol.step([segment(10, 0.99, "black")], 15, ahead=[segment(11, 0.99)])
        far = [segment(21 + k, 0.1) for k in range(4)] + [segment(25, 0.9)]     # an ad-like flash 5 s ahead
        pol.step([segment(20, 0.1)], 28, ahead=far)
        self.assertFalse(pol.muted, "only the next 3 s must agree")
        pol = Policy(PolicyConfig(grace=0, open_at="any"))
        pol.step([segment(10, 0.99, "black")], 15, ahead=[segment(11, 0.99)])
        pol.step([segment(20, 0.1)], 28, ahead=[segment(21, 0.1), segment(22, 0.9)])
        self.assertTrue(pol.muted, "an ad-like second right after still holds it")

    def test_an_ad_label_does_not_beat_its_the_show(self):
        pol = Policy(PolicyConfig(grace=0))
        pol.override_unmute(10)
        pol.step([segment(11, 0.99, ad_overlay="YouTube TV ad label")], 16, ahead=[segment(12, 0.99)])
        self.assertFalse(pol.muted)


class GameReturnTests(unittest.TestCase):
    """In a game whose score bug has been seen, only its return (or the feed, or the cap)
    ends a mute: MLB's partners' ads are full of baseball footage."""

    def run_break(self, bug_back_at, gate=None, labelled_until=None):
        pol = Policy(PolicyConfig(grace=0, open_at="any", bug_return=True), gate=gate)
        pol.step([segment(10, 0.99, "black", bug_after=False)], 15, ahead=[segment(11, 0.99)])
        self.assertTrue(pol.muted)
        for t in range(11, 200):
            back = t >= bug_back_at
            label = "YouTube TV ad label" if labelled_until and t < labelled_until else None
            pol.step([segment(t, 0.1, "black", post_z=-4.0, bug_after=back, ad_overlay=label)], t + 5,
                     ahead=[segment(t + 1, 0.1, bug_after=back)])
            if not pol.muted:
                return t
        return None

    def test_a_game_looking_ad_does_not_end_the_mute(self):
        self.assertEqual(self.run_break(bug_back_at=60), 60)

    def test_without_the_rule_it_would_have(self):
        pol = Policy(PolicyConfig(grace=0, open_at="any"))
        pol.step([segment(10, 0.99, "black")], 15, ahead=[segment(11, 0.99)])
        pol.step([segment(11, 0.1, "black", post_z=-4.0, bug_after=False)], 16, ahead=[segment(12, 0.1)])
        self.assertFalse(pol.muted)

    def test_the_feed_still_ends_it(self):
        self.assertEqual(self.run_break(bug_back_at=1000, gate=lambda t: "live" if t >= 40 else "break"), 40)

    def run_live(self, p_until, label_start=False):
        """A mute from 10 s; the feed says live from 40 s; the detector sure of an ad until p_until."""
        pol = Policy(PolicyConfig(grace=0, open_at="any"), gate=lambda t: "live" if t >= 40 else "break")
        pol.step([segment(10, 0.999, "black", ad_overlay="YouTube TV ad label" if label_start else None)], 15,
                 ahead=[segment(11, 0.999)])
        self.assertTrue(pol.muted)
        for t in range(11, 200):
            p = 1.0 if t < p_until else 0.1
            pol.step([segment(t, p)], t + 5, ahead=[segment(t + k, 1.0 if t + k < p_until else 0.1) for k in (1, 2, 3)])
            if not pol.muted:
                return t, pol.spans[-1].end_reason
        return None

    def test_a_sure_detector_holds_the_feeds_live_until_it_sees_the_return(self):
        # 2026-10-07: "live" came 4-15 s before YouTube TV's return, six times, at P(ad) 1.00.
        self.assertEqual(self.run_live(p_until=53)[0], 51, "its look ahead sees the return coming")
        self.assertEqual(self.run_live(p_until=1000), (60, "gated"), "at most gate_hold")
        self.assertEqual(self.run_live(p_until=0), (40, "gated"), "not sure: the feed's word at once")

    def test_a_mute_the_label_began_does_not_hold_the_feed(self):
        self.assertEqual(self.run_live(p_until=1000, label_start=True), (40, "gated"))

    def test_an_ad_label_beats_the_feed(self):
        self.assertEqual(self.run_break(bug_back_at=1000, gate=lambda t: "live" if t >= 40 else "break",
                                        labelled_until=55), 55)

    def test_an_ad_label_mutes_even_when_the_feed_says_live(self):
        pol = Policy(PolicyConfig(grace=0), gate=lambda t: "live")
        pol.step([segment(10, 0.2, ad_overlay="YouTube TV ad label")], 15, ahead=[segment(11, 0.2)])
        self.assertTrue(pol.muted)

    def test_no_score_bug_seen_no_rule(self):
        self.assertEqual(self.run_break(bug_back_at=-1), 11)


class GateTests(unittest.TestCase):
    def gate(self, pitches, live_now=True):
        from admute import sports
        before = [-900.0, -880.0]                       # an earlier half, done (the gate needs one)
        halves = [tuple(before)] + ([] if live_now else [(pitches[0], pitches[-1])])
        return sports.Gate(halves, [], False, live_now=pitches[0] if live_now else None, pitches=before + pitches)

    def test_live_while_pitches_come(self):
        g = self.gate([0, 20, 40, 65, 90])
        self.assertEqual(g(30), "live")
        self.assertEqual(g(100), "live")

    def test_a_long_gap_inside_a_half_is_no_opinion(self):
        g = self.gate([0, 20, 40, 260, 280], live_now=False)        # a mid-inning break, 40-260
        self.assertEqual(g(30), "live")
        self.assertIsNone(g(150))
        self.assertIsNone(g(265), "the broadcast is back a little after play resumes")
        self.assertEqual(g(275), "live")

    def test_the_half_in_progress_goes_quiet_after_its_last_pitch(self):
        g = self.gate([0, 20, 40])
        self.assertEqual(g(80), "live")
        self.assertIsNone(g(40 + 46), "a pitch this overdue: maybe a pitching change, and the break")
        self.assertIsNone(g(40 + 95))

    def test_a_pitching_change_before_the_feed_has_it(self):
        # 2026-10-07, bottom 1st on TBS: a mound visit, the break 72 s after the last pitch,
        # the pitching change in the feed 9 s later. The gate had said "live" (GAP: 90 s).
        g = self.gate([0, 22, 44, 66])
        self.assertEqual(g(66 + 30), "live")
        self.assertIsNone(g(66 + 72), "the break's first ads may be muted")

    def test_realtime_reads_a_finished_feed_as_it_stood(self):
        from admute import sports
        before = [-900.0, -880.0]
        pitches = [0, 20, 40, 260, 280]
        halves = [tuple(before), (0, 280)]
        full = sports.Gate(halves, [150.0], False, pitches=before + pitches)
        now = sports.Gate(halves, [150.0], False, pitches=before + pitches, realtime=True)
        self.assertEqual(full(125), "break", "the pitching change 25 s ahead is known")
        self.assertIsNone(now(125), "not yet in the feed; the last pitch 85 s ago")
        self.assertEqual(now(150), "break")
        self.assertIsNone(full(80), "in hindsight, a 220 s pause")
        self.assertEqual(now(80), "live", "40 s after a pitch, the next one not known yet")

    def test_a_stale_feed_has_no_opinion(self):
        g = self.gate([0, 20, 40], live_now=False)
        self.assertEqual(g(200), "break", "between halves")
        self.assertIsNone(g(40 + 361), "no pitch for over 6 min: stuck, or the wrong game")

    def test_a_half_with_no_pitch_yet_is_not_live(self):
        from admute import sports
        import datetime as dt
        def ts(sec):
            return dt.datetime.fromtimestamp(1_800_000_000 + sec, dt.timezone.utc).isoformat().replace("+00:00", "Z")
        def play(inning, half, secs):
            return {"about": {"inning": inning, "halfInning": half},
                    "playEvents": [{"isPitch": True, "startTime": ts(x), "endTime": ts(x + 2)} for x in secs]}
        feed = {"liveData": {"plays": {"allPlays": [play(8, "top", [0, 20, 40])]},
                             "linescore": {"inningState": "Bottom", "currentInning": 8, "outs": 0}},
                "gameData": {"status": {"abstractGameState": "Live"}}}
        g = sports.Gate.from_feed(feed)
        self.assertEqual(g(1_800_000_000 + 70), "break", "the top is over; the bottom has no pitch yet")
        feed["liveData"]["plays"]["allPlays"].append(play(8, "bottom", [200, 220]))
        g = sports.Gate.from_feed(feed)
        self.assertEqual(g(1_800_000_000 + 230), "live")

    def test_without_pitches_as_before(self):
        from admute import sports
        g = sports.Gate([(0, 300)], [], False)
        self.assertEqual(g(150), "live")


class SessionGameTests(unittest.TestCase):
    def session(self, resumed=()):
        from types import SimpleNamespace
        from admute import text as T
        from admute.service import Session, Service
        svc = SimpleNamespace(embed=None, model=D.DEFAULT_MODEL, models={"classic": D.DEFAULT_MODEL}, engine="classic",
                              overlays=OV.Library(catalogue=None), prints=None,
                              library=T.AdLibrary(), settings={"sensitivity": .5, "max_mute": 300, "sports_gate": True},
                              speech=SimpleNamespace(usable=False), frames=SimpleNamespace(save=lambda *a: None),
                              quiet=lambda *a: False, resumed=set(resumed))
        svc.policy_config = lambda la, game=False, engine="classic": Service.policy_config(svc, la, game, engine)
        svc.lookahead = lambda info: 3.0
        return Session(svc, "k" * 32, {"lookahead": 3}), svc

    def test_an_input_on_air_before_a_restart_gets_no_take_grace(self):
        s, svc = self.session(resumed=["k" * 32])
        self.assertEqual(s.pol.start, -math.inf)
        self.assertFalse(svc.resumed)
        s2, _ = self.session()
        self.assertEqual(s2.pol.start, 0.0)

    def test_the_gate_reads_the_feed_as_it_comes(self):
        s, _ = self.session()
        seen = []
        s.gate = lambda w: seen.append(w) or "break"
        s.wall_off = 1000.0
        self.assertEqual(s._gate(10.0), "break")
        self.assertEqual(seen, [1010.0])

    def test_games_do_not_wait_for_the_score_bug(self):
        s, svc = self.session()
        self.assertFalse(svc.policy_config(3.0, game=True).bug_return)


class DetectorTests(unittest.TestCase):
    def sig(self, seconds=120, bug_until=60, label_from=None):
        rng = np.random.default_rng(17)
        n = seconds * F.STEP_HZ
        maps = []
        for i in range(int(seconds * F.EDGE_HZ)):
            m = picture(rng)
            if i / F.EDGE_HZ < bug_until:
                logo_on(m)
            maps.append(pack(m))
        sig = {"frame_t": np.arange(0, seconds, 1 / 30), "frame_mean": np.full(seconds * 30, 90.0),
               "frame_max": np.full(seconds * 30, 220.0), "cut": np.zeros(n), "rms_db": np.full(n, -20.0),
               "edges": np.array(maps), "emb": rng.normal(size=(seconds, 1000)).astype(np.float32),
               "hist": rng.random((seconds, 64)).astype(np.float32)}
        if label_from is not None:
            on = np.zeros((10, 20), bool)
            on[2:8, 2:18:2] = True
            pics = []
            for s in range(seconds):
                p = np.zeros((OV.PIC, OV.PIC), bool)
                if s >= label_from:
                    p[12:18, 12:28:2] = True
                pics.append(np.packbits(p.ravel()))
            sig["pic"] = np.array(pics)
        return sig

    def library(self, label=False):
        rng = np.random.default_rng(4)
        lib = OV.Library(catalogue=None)
        lib.add(overlay_from([logo_on(picture(rng)) for _ in range(60)], kind="score", name="Score bug"))
        if label:
            on = np.zeros((10, 20), bool)
            on[2:8, 2:18:2] = True
            lib.add(OV.Overlay(id="pill", name="Ad label", kind="ad", box=(10, 10, 30, 20), on=on, off=~on,
                               space="pic", thresh=0.35, strong=0.5))
        return lib

    def model(self):
        m = dict(D.DEFAULT_MODEL)
        for key, vals in (("features", OV.FEATURES), ("mean", (0, 0, 0)), ("scale", (1, 1, 1)), ("coef", (-4, -1.5, 6))):
            m[key] = list(m[key]) + list(vals)
        return m

    def test_score_bug_evidence_and_segments(self):
        det = D.Detector(self.model(), overlays=self.library())
        src = D.ArraySource(self.sig())
        for edge in range(1, 120):
            det.update(src, float(edge))
        ov = det.feats["ov_score"]
        self.assertTrue(all(v == 1.0 for v in ov[2:58]))
        self.assertTrue(all(math.isnan(v) for v in ov[62:110]))
        z_up, z_down = det.logit(30), det.logit(80)
        self.assertLess(z_up, z_down - 3.5, "the bug argues for the programme")
        segs = det.decide(29, 31, settle=False)
        self.assertTrue(segs and all(sg.overlay == "Score bug" for sg in segs))
        self.assertIsNone(det.decide(79, 81, settle=False)[0].overlay)

    def test_score_bug_return_is_reported_once_it_has_been_seen(self):
        det = D.Detector(self.model(), overlays=self.library())
        src = D.ArraySource(self.sig(seconds=400, bug_until=300))
        for edge in range(1, 200):
            det.update(src, float(edge))
            det.decide(max(0, edge - 4), edge - 3)
        self.assertTrue(det.overlays.score_here())
        self.assertTrue(det.decide(150, 151, settle=False)[0].bug_after)
        for edge in range(200, 399):
            det.update(src, float(edge))
            det.decide(max(0, edge - 4), edge - 3)
        self.assertFalse(det.decide(380, 381, settle=False)[0].bug_after)
        fresh = D.Detector(self.model(), overlays=self.library())
        for edge in range(1, 30):
            fresh.update(src, float(edge))
        self.assertIsNone(fresh.decide(20, 21, settle=False)[0].bug_after, "not seen here yet: no rule")

    def test_ad_label_from_the_pictures(self):
        det = D.Detector(self.model(), overlays=self.library(label=True))
        src = D.ArraySource(self.sig(bug_until=0, label_from=70))
        for edge in range(1, 120):
            det.update(src, float(edge))
        lab = det.feats["ov_ad"]
        self.assertTrue(all(math.isnan(v) for v in lab[:69]))
        self.assertTrue(all(v == 1.0 for v in lab[70:115]), "including the first second (revised a second later)")
        self.assertGreater(det.logit(90), det.logit(40) + 5)
        self.assertEqual(det.decide(90, 91, settle=False)[0].ad_overlay, "Ad label")

    def test_the_model_can_switch_overlays_off(self):
        det = D.Detector({**self.model(), "overlays": False}, overlays=self.library(label=True))
        src = D.ArraySource(self.sig(label_from=30))
        for edge in range(1, 90):
            det.update(src, float(edge))
        self.assertFalse(det.overlays.watch)
        self.assertTrue(all(math.isnan(v) for name in OV.FEATURES for v in det.feats[name]))
        self.assertIsNone(det.decide(40, 41, settle=False)[0].ad_overlay)

    def test_replay_signals_without_pictures_just_lack_labels(self):
        det = D.Detector(self.model(), overlays=self.library(label=True))
        src = D.ArraySource(self.sig(bug_until=0))
        for edge in range(1, 60):
            det.update(src, float(edge))
        self.assertTrue(all(math.isnan(v) for v in det.feats["ov_ad"]))

    def test_signals_keep_the_pictures_for_the_detector(self):
        sig = F.Signals()
        sig.push_gray(np.array([0.0]), np.zeros((1, H, W), np.uint8))
        rgb = np.zeros((1, OV.PIC, OV.PIC, 3), np.uint8)
        rgb[0, 50:60, 50:60] = 255
        sig.push_rgb(np.array([0.0]), rgb)
        sig.push_rgb(np.array([2.0]), rgb)             # second 1 is missing: the next one repeats
        self.assertEqual(len(sig.pics), 3)
        self.assertTrue(F.unpack_pic(sig.pics[0])[50, 49:51].any())
        sig.trim_seconds(2)
        self.assertEqual(len(sig.pics), len(sig.emb))
        self.assertNotIn("pic", sig.snapshot(), "replay caches stay as they were")


class CatalogueTests(unittest.TestCase):
    def test_the_shipped_catalogue(self):
        lib = OV.Library()
        ids = set(lib.items)
        self.assertTrue({"yttv-sponsored", "nbc-mlb-score", "fox-mlb-score"} <= ids, ids)
        for ov in lib.items.values():
            with self.subTest(ov=ov.id):
                self.assertIn(ov.kind, OV.KINDS)
                self.assertGreaterEqual(int(ov.on.sum()), OV.MIN_ON)
        pill = lib.items["yttv-sponsored"]
        self.assertEqual((pill.kind, pill.space), ("ad", "pic"))
        self.assertGreater(pill.strong, pill.thresh)

    def test_the_model_weighs_overlays_and_training_keeps_them(self):
        m = D.load_model()
        w = dict(zip(m["features"], m["coef"]))
        self.assertLess(w["ov_score"], w["ov_logo"])
        self.assertLess(w["ov_logo"], 0)
        self.assertGreater(w["ov_ad"], 0)
        fitted = {"features": ["bug"], "mean": [0.5], "scale": [0.3], "coef": [-1.0], "intercept": 0.0}
        both = train.with_hand_set(fitted, m)
        self.assertEqual(both["features"], ["bug", "ov_score", "ov_logo", "ov_ad"])
        self.assertEqual(both["coef"][1:], [w["ov_score"], w["ov_logo"], w["ov_ad"]])


if __name__ == "__main__":
    unittest.main()
