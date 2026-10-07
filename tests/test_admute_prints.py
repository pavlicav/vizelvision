"""Known ads by audio fingerprint (admute/fingerprint.py) and their use in the sidecar.

  /home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_prints
"""
import math
import os
import tempfile
import unittest
from types import SimpleNamespace

try:
    import numpy as np
except ImportError:  # the system Python (unittest discover): these run under conda
    raise unittest.SkipTest("needs numpy: run with /home/vivian/miniconda3/bin/python3")

from admute import detector as D, fingerprint as FP, overlays as OV


def sound(seconds, seed):
    """Music-like test audio: a few tones changing every 0.25 s, distinct per seed."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(int(seconds * 4)):
        t = np.arange(FP.RATE // 4) / FP.RATE
        notes = rng.uniform(200, 3500, 3)
        out.append(sum(np.sin(2 * np.pi * f * t) for f in notes) / 3)
    return np.concatenate(out).astype(np.float32) * 0.3


def lm(audio, t0=0.0):
    a = np.array(FP.prints(audio, t0), np.float64).reshape(-1, 2)
    k = FP.keep(a[:, 1].astype(np.uint32))
    return a[k, 0], a[k, 1].astype(np.uint32)


def fake_landmarks(t0, seconds, seed, rate=40):
    """Kept-style landmarks without audio: (t, h) at `rate` per second."""
    rng = np.random.default_rng(seed)
    t = np.sort(rng.uniform(t0, t0 + seconds, int(seconds * rate)))
    return t, rng.integers(1, 2 ** 31, len(t)).astype(np.uint32)


class PrinterTests(unittest.TestCase):
    def test_a_rerun_matches_at_its_offset_and_other_sound_does_not(self):
        ad, other = sound(20, 1), sound(20, 2)
        audio = np.concatenate([ad, other, ad * 0.5])
        t, h = lm(audio)
        db = FP.PrintDB()
        first = t < 20
        cid = db._insert("ad", t[first], h[first], {"seed": "test"})
        w = (t >= 45) & (t < 49)
        votes, got, offset = db.match(t[w], h[w], "ad")
        self.assertEqual(got, cid)
        self.assertGreater(votes, 0.5 * w.sum())
        self.assertAlmostEqual(offset, 40.0, delta=0.5)
        w = (t >= 25) & (t < 29)
        self.assertLess(db.match(t[w], h[w], "ad")[0], 0.1 * max(1, w.sum()))

    def test_block_boundaries_change_nothing(self):
        audio = sound(12, 3)
        a = FP.prints(audio, block=4.0)
        b = FP.prints(audio, block=1.3)
        common = set(a) & set(b)
        self.assertGreater(len(common), 0.8 * len(a))


class PrintDBTests(unittest.TestCase):
    def test_an_ad_counts_after_two_breaks_and_can_be_forgotten(self):
        db = FP.PrintDB()
        t, h = fake_landmarks(0, 30, 1)
        cid = db.add_clip("ad", t, h, {"spans": ["a-1"]})
        self.assertFalse(db.known(cid))
        self.assertEqual(db.match(t[:200], h[:200], "ad")[0], 0, "a candidate is not yet evidence")
        self.assertEqual(db.add_clip("ad", t + 500, h, {"spans": ["a-2"]}), cid, "heard again: the same clip")
        self.assertTrue(db.known(cid))
        self.assertEqual(db.clips[cid]["spans"], ["a-1", "a-2"])
        self.assertGreater(db.match(t[:200] + 900, h[:200], "ad")[0], 150)
        self.assertEqual(db.clips_of({"a-2"}), [cid])
        self.assertEqual(db.remove([cid]), [cid])
        self.assertEqual(db.match(t[:200], h[:200], "ad")[0], 0)

    def test_saved_and_seeded_once(self):
        with tempfile.TemporaryDirectory() as d:
            seed = FP.PrintDB()
            t, h = fake_landmarks(0, 30, 2)
            seed._insert("ad", t, h, {"seed": "recordings"})
            path = os.path.join(d, "prints.npz")
            db = FP.PrintDB(path)
            db.merge_seed(seed, "recordings-v1")
            db.merge_seed(seed, "recordings-v1")
            self.assertEqual(db.summary()["seeded"], 1)
            db.save()
            again = FP.PrintDB(path)
            self.assertEqual(again.summary(), db.summary())
            self.assertGreater(again.match(t[:100], h[:100], "ad")[0], 80)

    def test_the_oldest_learnt_clips_go_first(self):
        db = FP.PrintDB()
        db.MAX_CLIPS = {"ad": 2, "show": 2}
        ids = [db.add_clip("ad", *fake_landmarks(0, 10, seed)) for seed in (1, 2, 3)]
        self.assertEqual(sorted(db.clips), ids[1:])


class EvidenceTests(unittest.TestCase):
    def test_repeats_count_only_when_they_repeat_an_ad(self):
        ev = FP.PrintEvidence()
        theme_t, theme_h = fake_landmarks(10, 20, 7)
        spot_t, spot_h = fake_landmarks(100, 20, 8)
        both = np.concatenate([theme_t, spot_t, theme_t + 600, spot_t + 600])
        hs = np.concatenate([theme_h, spot_h, theme_h, spot_h])
        order = np.argsort(both)
        ev.add(list(zip(both[order], hs[order])), 1000.0)
        labels = [0] * 100 + [1] * 20 + [0] * 900       # the spot was called an ad, the theme was not
        ev.learn(700, labels)
        ev.ads.REBUILD = 0
        self.assertGreater(ev.features(705)["repeat"], 0.5, "the spot again")
        self.assertEqual(ev.features(615)["repeat"], 0.0, "the theme again is no evidence of an ad")

    def test_show_sound_that_repeats_becomes_known_show_and_is_never_learnt_as_an_ad(self):
        db = FP.PrintDB()
        ev = FP.PrintEvidence(db)
        theme_t, theme_h = fake_landmarks(40, 10, 9)
        t = np.concatenate([theme_t, theme_t + 300])
        ev.add(list(zip(t, np.concatenate([theme_h, theme_h]))), 400.0)
        ev.show.REBUILD = 0
        ev.learn(360, [0] * 400)
        self.assertEqual(db.summary()["show"], 1)
        self.assertGreater(ev.features(345)["show"], 0.5)
        labels = [0] * 300 + [1] * 100                  # suppose a break was wrongly called over it
        got_t, _ = ev.ad_clip(290, 360, labels)
        self.assertFalse(((got_t >= 340) & (got_t < 350)).any(), "show sound never joins the ads")

    def test_no_sound_no_evidence(self):
        ev = FP.PrintEvidence()
        ev.add([], 100.0)
        self.assertTrue(all(math.isnan(v) for v in ev.features(50).values()))


class DetectorTests(unittest.TestCase):
    def test_a_known_ad_is_recognised(self):
        det = D.Detector(D.DEFAULT_MODEL)
        det.feats["fp_known"] = [0.0] * 10 + [0.5, 0.6, 0.4] + [0.0] * 5
        self.assertTrue(det.known_ad(10))
        self.assertFalse(det.known_ad(2))
        self.assertFalse(det.known_ad(15))


class SessionTests(unittest.TestCase):
    def test_its_the_show_forgets_the_ad_playing(self):
        from admute.service import Session, Service
        db = FP.PrintDB()
        t, h = fake_landmarks(100, 30, 5)
        cid = db._insert("ad", t - 100, h, {"seed": "x"})
        labels_written = []
        svc = SimpleNamespace(embed=None, model=D.DEFAULT_MODEL, models={"classic": D.DEFAULT_MODEL}, engine="classic",
                              overlays=OV.Library(catalogue=None), prints=db, library=None,
                              settings={"speech": False, "known_ads": True, "sensitivity": .5, "max_mute": 300, "learn": True},
                              speech=SimpleNamespace(usable=False), frames=SimpleNamespace(save=lambda *a: None),
                              label=labels_written.append, note=lambda *a, **k: None)
        from admute import text as T
        svc.library = T.AdLibrary()
        svc.policy_config = lambda lookahead, game=False, engine="classic": Service.policy_config(svc, lookahead, game, engine)
        s = Session(svc, "k" * 32, {"lookahead": 3})
        s.base = 0
        s.det.prints.add(list(zip(t, h)), 140.0)
        s.override(int(120 * 1e9), "unmute", 1)
        self.assertNotIn(cid, db.clips)
        self.assertEqual(labels_written[-1]["label"], "show")


if __name__ == "__main__":
    unittest.main()


class GameLearningTests(unittest.TestCase):
    """Breaks from MLB's feed, aligned to the broadcast's own black seams."""

    def setUp(self):
        from admute import seed
        self.seed = seed
        # a game on the broadcast clock: breaks at 300-420 and 900-1030, black seams at their
        # edges and a few elsewhere; the broadcast runs 50 s behind the feed
        self.blacks = [120.0, 300.4, 330.0, 362.1, 419.6, 650.0, 900.2, 960.0, 1029.8, 1500.0]
        self.logit = np.full(1600, -3.0)
        self.logit[300:420] = 3.0
        self.logit[900:1030] = 3.0
        # feed: last pitch ~25 s before the break, next first pitch ~15 s after it (feed clock)
        self.edges = [(300 - 50 - 25, 420 - 50 + 15), (900 - 50 - 25, 1030 - 50 + 15)]

    def test_lag_found_and_edges_snapped_to_black(self):
        spans, lag, lags, rejected = self.seed.align_breaks(self.edges, self.blacks, self.logit)
        self.assertEqual([(a, b) for a, b, _ in spans], [(300.4, 419.6), (900.2, 1029.8)])
        self.assertTrue(30 <= lag <= 80, lag)
        self.assertEqual(rejected, 0)

    def test_a_span_that_does_not_look_like_ads_is_not_learnt(self):
        logit = self.logit.copy()
        logit[900:1030] = -3.0                          # the detector sees the programme there
        spans, _, _, rejected = self.seed.align_breaks(self.edges, self.blacks, logit)
        self.assertEqual([(a, b) for a, b, _ in spans], [(300.4, 419.6)])
        self.assertEqual(rejected, 1)

    def test_live_breaks_become_known_ads_once(self):
        from admute import sports, text as T
        from admute.service import Session, Service
        db = FP.PrintDB()
        noted = []
        svc = SimpleNamespace(embed=None, model=D.DEFAULT_MODEL, models={"classic": D.DEFAULT_MODEL}, engine="classic",
                              overlays=OV.Library(catalogue=None), prints=db, library=T.AdLibrary(),
                              settings={"speech": False, "known_ads": True, "learn_games": True, "sensitivity": .5,
                                        "max_mute": 300},
                              speech=SimpleNamespace(usable=False), frames=SimpleNamespace(save=lambda *a: None),
                              note=lambda what, **k: noted.append((what, k)))
        svc.policy_config = lambda lookahead, game=False, engine="classic": Service.policy_config(svc, lookahead, game, engine)
        s = Session(svc, "g" * 32, {"lookahead": 3})
        s.base, s.wall_off = 0, 1000.0                   # session time t is wall time t + 1000
        wall = lambda t: t + 1000.0 - 50                 # feed times: 50 s ahead of the broadcast
        halves = [(wall(0), wall(250)), (wall(435), wall(875)), (wall(1045), wall(1400))]
        s.gate = SimpleNamespace(gate=sports.Gate(halves, [], False))
        s.game = {"title": "Test at Test", "game_pk": 1}
        s.det.seam_list = lambda: [SimpleNamespace(t=b, kind="black") for b in self.blacks]
        s.det.lp_ad, s.det.lp_show = list(self.logit / 2), list(-self.logit / 2)
        s.det.frozen_to = 1590.0
        t, h = fake_landmarks(0, 1600, 3)
        s.det.prints.add(list(zip(t, h)), 1600.0)
        s.learn_game(final=True)
        got = db.summary()
        self.assertGreaterEqual(got["ads"], 2, "both breaks, spot by spot")
        self.assertEqual(got["ads"], got["ad_candidates"], "known at once: MLB's feed is sure")
        self.assertEqual(noted[-1][0], "game")
        s.learn_game(final=True)
        self.assertEqual(db.summary(), got, "never twice")

    def test_a_confirmed_break_is_learnt_spot_by_spot(self):
        """A spot wedged between two others counts once it airs again; one at a break's
        edge (which may be the programme's own sound) only after three airings."""
        ev = FP.PrintEvidence()
        spot = {k: fake_landmarks(0, 30, 100 + k) for k in range(3)}
        def air(t0, order):
            out, t = [], t0
            for k in order:
                st, sh = spot[k]
                out += list(zip(st + t, sh))
                t += 30
            return out, [t0 + 30 * i for i in range(len(order) + 1)]
        first, blacks1 = air(1000, [0, 1, 2])
        second, blacks2 = air(5000, [2, 1, 0])
        ev.add(sorted(first + second), 6000.0)
        det = D.Detector(D.DEFAULT_MODEL)
        det.prints = ev
        det.seam_list = lambda: [SimpleNamespace(t=b, kind="black") for b in blacks1 + blacks2]
        det.learn_break(1000, 1090, "a")
        self.assertEqual(ev.db.summary()["ads"], 0, "heard once: candidates")
        det.learn_break(5000, 5090, "b")
        known = {c["src"]: c for c in ev.db.catalogue()}
        self.assertEqual(ev.db.summary()["ad_candidates"], 3, "three spots, each stored once")
        self.assertEqual(ev.db.summary()["ads"], 1, "the wedged spot (aired twice) is known; the edge ones need a third")


class WhyTests(unittest.TestCase):
    """The diagnostic reason: how sure, and what says so."""

    def session(self):
        from admute import text as T
        from admute.service import Session, Service
        db = FP.PrintDB()
        svc = SimpleNamespace(embed=None, model=D.DEFAULT_MODEL, models={"classic": D.DEFAULT_MODEL}, engine="classic",
                              overlays=OV.Library(catalogue=None), prints=db, library=T.AdLibrary(),
                              settings={"speech": False, "known_ads": True, "sensitivity": .5, "max_mute": 300},
                              speech=SimpleNamespace(usable=False), frames=SimpleNamespace(save=lambda *a: None),
                              note=lambda *a, **k: None)
        svc.policy_config = lambda lookahead, game=False, engine="classic": Service.policy_config(svc, lookahead, game, engine)
        s = Session(svc, "w" * 32, {"lookahead": 3})
        s.base, s.aired, s.p_ad = 0, 20.0, 0.97
        for name in s.det.feats:
            s.det.feats[name] = [math.nan] * 30
        s.det.lp_ad, s.det.lp_show = [0.0] * 30, [0.0] * 30
        return s, db

    def test_you(self):
        from admute.policy import Span
        s, _ = self.session()
        self.assertEqual(s.why(Span(start=10, start_reason="override")), ["YOU · it's an ad", "detector: 95% ad"])

    def test_a_known_ad_names_itself(self):
        s, db = self.session()
        t, h = fake_landmarks(0, 30, 11)
        db._insert("ad", t, h, {"src": "Braves at Dodgers", "seed": "game-1"})
        s.det.prints.add(list(zip(t, h)), 30.0)
        s.det.feats["fp_known"][20] = 0.6
        head, detail = s.why()
        self.assertEqual(head, "95% · KNOWN AD")
        self.assertEqual(detail, "from Braves at Dodgers")

    def test_the_reason_is_fixed_per_mute(self):
        from admute.policy import Span
        s, _ = self.session()
        s.service.quiet = lambda *a: False
        s.pol.current = Span(start=10, seam="black")
        first = s._message()["why"]
        s.p_ad = 0.62                                         # the evidence moves on...
        self.assertEqual(s._message()["why"], first, "...but the badge keeps its words")
        s.pol.current.confirmed = True
        self.assertEqual(s._message()["why"][0], "60% · PICTURE", "once more when it confirms")

    def test_otherwise_the_strongest_evidence(self):
        from admute.policy import Span
        s, _ = self.session()
        s.det.feats["bug"][18:21] = [0.0, 0.0, 0.0]          # no bug: the model's strongest ad sign
        head, detail = s.why(Span(start=10, seam="black"))
        self.assertEqual(head, "95% · PICTURE")
        self.assertIn("no station or score bug", detail)
        self.assertIn("black frame", detail)


class ScriptTests(unittest.TestCase):
    """Each clip keeps the words said over it, on its own clock, for the Ad database."""

    def test_a_new_clip_keeps_its_words_and_a_rerun_fills_in_only_what_is_missing(self):
        db = FP.PrintDB()
        t, h = fake_landmarks(100, 30, 1)
        words = [[100.5, "Fifteen"], [101.0, "minutes"], [101.5, "could"], [104.0, "save"], [120.0, "you"]]
        cid = db.add_clip("ad", t, h, words=words, span=(100.0, 130.0))
        c = db.catalogue()[0]
        self.assertEqual(c["script"][0][1], "Fifteen minutes could", "a pause starts a new line")
        self.assertAlmostEqual(c["script"][0][0], 100.5 - t[0], delta=0.1, msg="on the clip's own clock")
        self.assertGreaterEqual(c["script_cover"], 0.9)
        # Heard again 500 s later: the same clip, and no fuller, so the script stays.
        again = [[w + 500, x] for w, x in words[:2]]
        self.assertEqual(db.add_clip("ad", t + 500, h, words=again, span=(600.0, 630.0)), cid)
        self.assertEqual(len(db.clips[cid]["script"]["words"]), 5)

    def test_not_transcribed_is_not_silent(self):
        db = FP.PrintDB()
        cid = db.add_clip("ad", *fake_landmarks(0, 30, 2), words=None)
        self.assertIsNone(db.catalogue()[0]["script"], "no script yet")
        db.set_script(cid, [], 0.0, "broadcast", (0.0, 30.0))
        self.assertEqual(db.catalogue()[0]["script"], [], "heard, and no words: music only")

    def test_a_stored_break_is_scripted_a_spot_at_a_time(self):
        db = FP.PrintDB()
        cid = db._insert("ad", *fake_landmarks(0, 120, 3), {"dur": 120.0})
        self.assertTrue(db.set_script(cid, [[1030.0, "first"]], 1000.0, "broadcast", (1028.0, 1058.0)))
        self.assertTrue(db.set_script(cid, [[2090.0, "third"]], 2000.0, "broadcast", (2088.0, 2118.0)))
        sc = db.clips[cid]["script"]
        self.assertEqual([w[1] for w in sc["words"]], ["first", "third"])
        self.assertEqual(sc["cover"], [[28.0, 58.0], [88.0, 118.0]])
        self.assertLess(db.catalogue()[0]["script_cover"], 0.8, "partial")
        self.assertFalse(db.set_script(cid, [[1031.0, "x"]], 1000.0, "broadcast", (1029.0, 1057.0)), "already scripted there")

    def test_seed_scripts_move_onto_the_clip_they_merge_into(self):
        db, seed = FP.PrintDB(), FP.PrintDB()
        t, h = fake_landmarks(0, 30, 4)
        mine = db._insert("ad", t, h, {"dur": 30.0})
        sid = seed._insert("ad", t + 5, h, {"dur": 30.0})       # the same sound, its clock 5 s later
        seed.set_script(sid, [[10.0, "hello"]], 0.0, "recording", (0.0, 30.0))
        db.merge_seed(seed, "s1")
        self.assertEqual(db.clips[mine]["script"]["words"], [[5.0, "hello"]])

    def test_names(self):
        db = FP.PrintDB()
        cid = db.add_clip("ad", *fake_landmarks(0, 30, 5))
        db.rename(cid, "  GEICO   camel ")
        self.assertEqual(db.catalogue()[0]["name"], "GEICO camel")
        db.rename(cid, "")
        self.assertIsNone(db.catalogue()[0]["name"])

    def test_a_known_ad_heard_again_gets_its_script_once_the_airing_is_over(self):
        db = FP.PrintDB()
        t, h = fake_landmarks(0, 20, 6)
        cid = db._insert("ad", t - t[0], h, {"seed": "test", "dur": 20.0})
        ev = FP.PrintEvidence(db)
        ev.words = lambda a, b: [[x, w] for x, w in [[501.0, "buy"], [510.0, "now"], [530.0, "show"]] if a <= x < b]
        offset = 500.0 - t[0]
        for s in range(499, 521):
            ev.hits[s] = (cid, offset)
        ev.scribe(530)
        self.assertEqual([w[1] for w in db.clips[cid]["script"]["words"]], ["buy", "now"], "only over the ad")
        self.assertEqual(ev.aired[-1][0], cid, "and its pictures are wanted")

    def test_detector_words_need_whisper_to_have_heard_the_stretch(self):
        det = D.Detector()
        det.heard = [(0.0, 4.0, [[1.0, 1.4, "one"], [2.0, 2.5, "two"]]), (4.0, 8.0, [[5.0, 5.5, "three"]])]
        self.assertEqual([w for _, w in det.words_in(0.0, 8.0)], ["one", "two", "three"])
        self.assertIsNone(det.words_in(0.0, 12.0), "a dropped chunk says nothing")


class CutSeamTests(unittest.TestCase):
    """A break may begin at a hard cut: cable feeds don't always fade to black."""

    def feed(self, det, cut, rms=-20.0, black_at=()):
        steps = len(cut)
        frames_t = np.arange(steps * 3) / 30.0
        mean = np.full(len(frames_t), 90.0, np.float32)
        mx = np.full(len(frames_t), 200.0, np.float32)
        for b in black_at:
            k = np.abs(frames_t - b) < 0.05
            mean[k], mx[k] = 5.0, 10.0
        src = SimpleNamespace(frames=lambda a, t_end: (frames_t[a:int(np.searchsorted(frames_t, t_end))],
                                                       mean[a:int(np.searchsorted(frames_t, t_end))],
                                                       mx[a:int(np.searchsorted(frames_t, t_end))]),
                              steps=lambda kind, a, b: (np.asarray(cut, np.float32) if kind == "cut"
                                                        else np.full(steps, rms, np.float32))[a:b],
                              edge_maps=lambda a, b: np.zeros((0, 0), np.uint8),
                              seconds=lambda a, b: (np.zeros((0, 1000), np.float32), np.zeros((0, 64), np.float32)))
        det._consume(src, steps / 10.0)
        return det.seam_list()

    def test_a_hard_cut_is_a_seam_and_black_beside_it_wins(self):
        cut = np.full(200, 3.0)
        cut[50], cut[120] = 80.0, 90.0
        seams = self.feed(D.Detector(), cut, black_at=(12.05,))
        self.assertEqual(sorted((round(s.t, 1), s.kind) for s in seams), [(5.0, "cut"), (12.1, "black")])

    def test_off_before_10_3(self):
        cut = np.full(200, 3.0)
        cut[50] = 80.0
        self.assertEqual(self.feed(D.Detector({**D.load_model(), "cut_seam": 0}), cut), [])

    def test_a_break_may_begin_at_a_cut(self):
        self.assertLess(D.DEFAULT_MODEL["show_ad"]["cut"], 50)
        self.assertGreater(D.DEFAULT_MODEL["show_ad"]["cut"], D.DEFAULT_MODEL["show_ad"]["black"], "black is cheaper")
