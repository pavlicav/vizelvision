"""Ad mute's sidecar pieces that need numpy: text evidence, the detector's handling of
late words, the page's pictures, and the session's audio for Whisper.

  /home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_text
"""
import math
import os
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

try:
    import numpy as np
except ImportError:  # the system Python (unittest discover): these run under conda
    raise unittest.SkipTest("needs numpy: run with /home/vivian/miniconda3/bin/python3")

from admute import detector as D, features, fingerprint as FP, speech as W, text as T
from admute.frames import FrameStore
from admute.service import Session, Service


def say(t, text, step=0.4):
    """Words of a phrase starting at t."""
    return [[round(t + i * step, 2), round(t + i * step + step * 0.8, 2), w] for i, w in enumerate(text.split())]


class TextEvidenceTests(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(T.token("Phillies,"), "phillies")
        self.assertEqual(T.token("You’re"), "you're")
        self.assertEqual(T.token("$19.99"), "<money>")
        self.assertEqual(T.token("2026"), "<num>")
        self.assertIsNone(T.token("—"))
        self.assertTrue(T.content("schwarber"))
        self.assertFalse(T.content("the"))

    def test_window_stops_at_black_seams(self):
        ev = T.TextEvidence({"insurance": 2.0, "inning": -2.0})
        ev.add(0, 8, say(1, "top of the inning") + say(5.2, "insurance today"))
        f = ev.features(4, blacks=[5.0])            # the second before the seam
        self.assertLess(f["lexicon"], 0)
        f = ev.features(5, blacks=[5.0])            # the break's first second
        self.assertGreater(f["lexicon"], 0)
        self.assertTrue(math.isnan(ev.features(40, blacks=[5.0])["lexicon"]), "no words: neutral")

    def test_ads_repeat_and_talk_does_not(self):
        ev = T.TextEvidence()
        spot = "get more with xfinity mobile switch today and save"
        ev.add(0, 20, say(10, spot))
        ev.add(100, 120, say(105, "and he lines it into left field for a single"))
        ev.add(200, 220, say(210, spot))
        self.assertEqual(ev.features(11, [])["repeat"], 0.0, "the first time is not a repeat")
        self.assertGreater(ev.features(211, [])["repeat"], 0.9)
        self.assertEqual(ev.features(106, [])["repeat"], 0.0)

    @unittest.mock.patch.object(T, "MIN_VOCAB", 40)
    def test_programme_vocabulary(self):
        ev = T.TextEvidence()
        ev.add(0, 400, say(10, " ".join(["schwarber harper acuna riley inning pitch count swing"] * 6), step=0.5)
               + say(300, "schwarber and harper on the bases") + say(350, "you can save with your new plan"))
        ev.learn(200, [0] * 200)
        f = ev.features(300, [])
        self.assertAlmostEqual(f["show_vocab"], 2 / 3)
        self.assertEqual(f["ad_vocab"], 0.0)
        self.assertEqual(f["you"], 0.0)
        self.assertAlmostEqual(ev.features(351, [])["you"], 2 / 7)


class AdLibraryTests(unittest.TestCase):
    def test_known_after_two_breaks_and_kept_across_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "adtext.json")
            lib = T.AdLibrary(seed=["call now to save"], path=path)
            spot = T.shingles("switch to xfinity mobile today and save".split())
            self.assertTrue(lib.known(("call", "now", "to", "save")), "seeded from the recordings")
            lib.learn(spot)
            self.assertFalse(lib.known(("switch", "to", "xfinity", "mobile")), "one break is not enough")
            lib.learn(spot)
            self.assertTrue(lib.known(("switch", "to", "xfinity", "mobile")))
            lib.save()
            again = T.AdLibrary(path=path)
            self.assertTrue(again.known(("xfinity", "mobile", "today", "and")))
            again.learnt[("old", "ad", "from", "summer")] = [5, time.time() - 90 * 86400]
            again.dirty = True
            again.save()
            self.assertNotIn(("old", "ad", "from", "summer"), T.AdLibrary(path=path).learnt)

    def test_known_ad_feature(self):
        lib = T.AdLibrary(seed=["get zero percent apr"])
        ev = T.TextEvidence(library=lib)
        ev.add(0, 10, say(1, "today get zero percent apr on tucson"))
        self.assertAlmostEqual(ev.features(2, [])["known_ad"], 4 / 7)
        self.assertEqual(ev.features(2, [])["repeat"], 0.0)


class FakeSource:
    """A steady, featureless picture and sound; words as given."""

    def __init__(self, chunks, latency=1.5):
        self.src = D.ArraySource(self._sig(), chunks, latency)

    @staticmethod
    def _sig(seconds=400):
        from admute import features as F
        rng = np.random.default_rng(1)
        n = seconds * F.STEP_HZ
        packed = len(np.packbits(np.zeros(180 * 320, np.uint8)))
        return {"frame_t": np.arange(0, seconds, 1 / 30), "frame_mean": np.full(seconds * 30, 90.0),
                "frame_max": np.full(seconds * 30, 220.0), "cut": np.zeros(n), "rms_db": np.full(n, -20.0),
                "edges": np.zeros((int(seconds * F.EDGE_HZ), packed), np.uint8),
                "emb": rng.normal(size=(seconds, 1000)).astype(np.float32),
                "hist": rng.random((seconds, 64)).astype(np.float32)}

    def __getattr__(self, name):
        return getattr(self.src, name)


class DetectorTextTests(unittest.TestCase):
    def chunks(self, until):
        return [(t, t + 4, say(t + 0.2, "and the pitch is outside ball two")) for t in range(0, until, 4)]

    def test_text_evidence_arrives_late_and_freezing_waits_for_it(self):
        det = D.Detector({**D.DEFAULT_MODEL, "text": {"lexicon": {"pitch": -2}}})
        src = FakeSource(self.chunks(400))
        for edge in range(1, 120):
            det.update(src, float(edge))
            if edge > 30:
                self.assertLessEqual(det.frozen_to, max(det.text_done, edge - D.TEXT_HOLD) + 1e-9)
                self.assertGreater(det.frozen_to, edge - D.TEXT_HOLD - 2)
        lex = det.feats["txt_lexicon"]
        self.assertTrue(all(v < 0 for v in lex[5:100]), "every second hears the commentary")
        self.assertTrue(math.isnan(lex[-1]), "the last seconds have no words yet")

    def test_transcription_stalling_never_holds_detection_back_far(self):
        det = D.Detector()
        src = FakeSource(self.chunks(60))
        for edge in range(1, 200):
            det.update(src, float(edge))
        self.assertGreaterEqual(det.frozen_to, 199 - D.TEXT_HOLD - 1)

    def test_text_features_change_the_evidence_only_through_the_model(self):
        # With no weight on the text, decisions are those of a detector without words.
        a, b = D.Detector(D.DEFAULT_MODEL), D.Detector(D.DEFAULT_MODEL)   # visual features only
        sa, sb = FakeSource(self.chunks(400)), FakeSource(None)
        for edge in range(1, 300):
            a.update(sa, float(edge))
            b.update(sb, float(edge))
        np.testing.assert_allclose(a.lp_ad, b.lp_ad)
        pa = [s.p_ad for s in a.decide(250, 290)]
        pb = [s.p_ad for s in b.decide(250, 290)]
        np.testing.assert_allclose(pa, pb, atol=1e-9)


class AudioGridTests(unittest.TestCase):
    """The audio level grid stays on input time, so a hole never holds the edge back
    (2026-10-03: a 4 s gap left detection 4.8 s behind and nothing was muted)."""

    def edge(self, sig):
        return (sig.audio_since + len(sig.rms_db)) / features.STEP_HZ

    def feed(self, sig, t0, seconds):
        for i in range(int(seconds * 50)):
            sig.push_audio(t0 + i * 0.02, np.full(320, 0.01, np.float32))

    def test_a_hole_is_silence_and_costs_nothing_after_it(self):
        sig = features.Signals()
        self.feed(sig, 0.0, 10)
        self.feed(sig, 14.0, 10)
        self.assertAlmostEqual(self.edge(sig), 24.0)
        self.assertEqual(max(sig.rms_db[101:139]), features.SILENT_DB)
        self.assertGreater(sig.rms_db[141], -50)

    def test_dropped_buffers_and_overlaps_do_not_add_up(self):
        sig = features.Signals()
        for second in range(100):           # a 20 ms buffer lost every second
            for i in range(49):
                sig.push_audio(second + i * 0.02, np.full(320, 0.01, np.float32))
        sig.push_audio(99.5, np.full(16000, 0.01, np.float32))   # half of it again
        self.assertAlmostEqual(self.edge(sig), 100.5)

    def test_timestamp_jitter_is_continuous(self):
        sig = features.Signals()
        rng = np.random.default_rng(1)
        for i in range(5000):
            sig.push_audio(i * 0.02 + rng.uniform(-0.001, 0.001), np.full(320, 0.01, np.float32))
        self.assertAlmostEqual(self.edge(sig), 100.0)
        self.assertGreater(min(sig.rms_db), -50)


class FrameStoreTests(unittest.TestCase):
    def test_save_and_prune(self):
        with tempfile.TemporaryDirectory() as d:
            store = FrameStore(Path(d), keep=60)
            key = "ab" * 16
            now = time.time()
            store.save(key, now - 120, np.zeros((224, 224, 3), np.uint8))
            store.save(key, now, np.full((224, 224, 3), 200, np.uint8))
            files = sorted(os.listdir(Path(d) / key))
            self.assertEqual(files, sorted([f"{int(now - 120)}.jpg", f"{int(now)}.jpg"]))
            from PIL import Image
            with Image.open(Path(d) / key / f"{int(now)}.jpg") as im:
                self.assertEqual(im.size, (256, 144))
            store.prune(now)
            self.assertEqual(os.listdir(Path(d) / key), [f"{int(now)}.jpg"])
            store.prune(now + 3600 + 61)
            self.assertFalse((Path(d) / key).exists(), "an input gone for good leaves nothing behind")


class SessionSpeechTests(unittest.TestCase):
    def service(self):
        sent = []
        svc = SimpleNamespace(embed=None, model=D.DEFAULT_MODEL, settings={"speech": True, "sensitivity": .5, "max_mute": 300},
                              library=T.AdLibrary(), marked_show=lambda span_id: span_id.endswith("-199"),
                              prints=FP.PrintDB(), note=lambda *a, **k: None,
                              speech=SimpleNamespace(usable=True, submit=lambda *a: sent.append(a)),
                              frames=SimpleNamespace(save=lambda *a: None))
        svc.policy_config = lambda lookahead: Service.policy_config(svc, lookahead)
        return svc, sent

    def test_audio_is_cut_into_whisper_chunks(self):
        svc, sent = self.service()
        s = Session(svc, "k" * 32, {"lookahead": 3})
        s.base = 0
        piece = np.zeros(1600, np.float32)
        for i in range(100):                       # 10 s in 0.1 s buffers
            s._hear(i / 10, piece)
        self.assertEqual([round(c[2], 2) for c in sent], [0.0, 4.0])
        self.assertTrue(all(len(c[3]) == W.CHUNK * W.RATE for c in sent))
        for i in range(150, 200):                  # after a gap: a new chunk starts at 15 s
            s._hear(i / 10, piece)
        self.assertEqual(round(sent[-1][2], 2), 15.0)
        gen = sent[0][1]
        s.heard(gen, 0.0, 4.0, [[1.0, 1.3, "hello"]])
        s._reset()
        s.heard(gen, 4.0, 8.0, [[5.0, 5.3, "stale"]])
        self.assertEqual(s.speech, [], "words for an earlier timeline are dropped")

    def test_only_confirmed_breaks_teach_the_library(self):
        from admute.policy import Span
        svc, _ = self.service()
        s = Session(svc, "k" * 32, {"lookahead": 3})
        words = say(100, "get zero percent apr on a new tucson today") + say(200, "and the pitch is low ball one count")
        s.det.text.add(0, 300, words)
        s.det.label = [1] * 300
        s.pol.spans = [Span(start=99, end=110, confirmed=True, end_reason="show"),
                       Span(start=199, end=210, confirmed=True, end_reason="show"),      # marked "Was the show"
                       Span(start=150, end=160, confirmed=False, end_reason="retracted")]
        s.aired = 105 + 600
        s._learn()
        self.assertEqual(svc.library.learnt, {}, "not until ten minutes after it ends")
        s.aired = 1000
        s._learn()
        self.assertIn(("zero", "percent", "apr", "on"), svc.library.learnt)
        self.assertFalse(any("pitch" in sh for sh in svc.library.learnt), "a break marked as the show teaches nothing")
        s._learn()
        self.assertEqual(svc.library.learnt[("zero", "percent", "apr", "on")][0], 1, "each break once")

    def test_a_frame_off_the_timeline_is_dropped_not_a_restart(self):
        from roku_stream import admute_protocol as proto
        from admute import service
        svc, _ = self.service()
        s = Session(svc, "k" * 32, {"lookahead": 3})
        gray = bytes(proto.GRAY_W * proto.GRAY_H)
        sec = 1_000_000_000
        for i in range(60):
            s.push(b"G", 100 * sec + i * sec // 30, gray)
        sig, base = s.sig, s.base
        s.push(b"G", 90 * sec, gray)                      # one stray frame, 10 s back
        s.push(b"G", 102 * sec, gray)
        self.assertIs(s.sig, sig, "a stray frame does not cost the warm-up")
        self.assertEqual((s.base, s.off_since), (base, None))
        with unittest.mock.patch.object(service, "NEW_TIMELINE", 0.05):
            s.push(b"G", 5 * sec, gray)                   # the source restarted ...
            time.sleep(0.06)
            s.push(b"G", 5 * sec + sec // 30, gray)       # ... and stays restarted
        self.assertIsNot(s.sig, sig)
        self.assertEqual(s.base, 5 * sec + sec // 30)

    def test_an_empty_tick_reads_no_edge_maps(self):
        from admute import features
        from admute.service import Source
        src = Source(features.Signals(), [])
        self.assertEqual(len(src.edge_maps(0, 0)), 0)
        self.assertEqual(list(src.edge_maps(3, 3)), [])

    def test_lookahead_follows_the_shared_delay(self):
        svc = SimpleNamespace(captions_on=False)
        self.assertEqual(Service.lookahead(svc, {"lookahead": 3}), 3.0)
        svc.captions_on = True
        self.assertEqual(Service.lookahead(svc, {"lookahead": 3}), 5.0)
        self.assertEqual(Service.lookahead(svc, {"lookahead": 7}), 7.0)


if __name__ == "__main__":
    unittest.main()
