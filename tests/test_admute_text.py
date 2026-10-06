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

from admute import detector as D, features, fingerprint as FP, overlays as OV, speech as W, text as T
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


def words_at(text, t0, step=0.5):
    """A phrase spoken from t0, one word every ``step`` s: [[start, end, word]]."""
    return [[round(t0 + i * step, 2), round(t0 + i * step + 0.4, 2), w] for i, w in enumerate(text.split())]


class FakeWhisper:
    """Hears the words said in a window, a little off in time, and garbles any word the
    window cuts off at either edge (as Whisper does)."""

    def __init__(self, said, jitter=0.15):
        self.said, self.jitter, self.n = said, jitter, 0

    def __call__(self, model, audio, t0, prompt=None):
        t1 = t0 + len(audio) / W.RATE
        self.n += 1
        nudge = self.jitter if self.n % 2 else -self.jitter
        out = []
        for a, b, w in self.said:
            if b <= t0 or a >= t1:
                continue
            word = w if a >= t0 and b <= t1 else w[:2] + "#"
            out.append([round(max(t0, a + nudge), 2), round(min(t1, b + nudge), 2), word])
        return out


class WindowTests(unittest.TestCase):
    def stream(self, seconds, fake, gap_at=None, gap=0.0):
        windows, committer, chunks = W.Windower(), W.Committer(), []
        t = 0.0
        for i in range(int(seconds * 10)):
            if gap_at is not None and abs(t - gap_at) < 1e-6:
                t += gap
            for t0, audio, upto in windows.push(t, np.full(1600, 0.1, np.float32)):
                chunks.append(committer.take(t0, upto, fake(None, audio, t0)))
            t += 0.1
        for t0, audio, upto in windows.flush():
            chunks.append(committer.take(t0, upto, fake(None, audio, t0)))
        return chunks

    def test_every_word_once_and_whole_despite_window_edges_and_timing(self):
        said = words_at(" ".join(f"word{i}" for i in range(60)), 0.3)       # 0.3 .. 30 s
        chunks = self.stream(31, FakeWhisper(said))
        got = [w[2] for _, _, ws in chunks for w in ws]
        self.assertEqual(got, [w[2] for w in said])
        for (a0, a1, _), (b0, b1, _) in zip(chunks, chunks[1:]):
            self.assertEqual(a1, b0, "the chunks are contiguous")

    def test_a_gap_gives_the_held_back_words_and_starts_over(self):
        said = words_at("one two three four five", 4.5) + words_at("six seven eight", 12.5)
        chunks = self.stream(10, FakeWhisper(said, jitter=0.0), gap_at=7.0, gap=5.0)
        got = [w[2] for _, _, ws in chunks for w in ws]
        self.assertEqual(got, [w[2] for w in said])
        spans = [(round(a, 2), round(b, 2)) for a, b, _ in chunks]
        self.assertEqual(spans[:3], [(0.0, 3.0), (3.0, 7.0), (12.0, 15.0)])

    def test_dropped_windows_leave_a_hole_not_duplicates(self):
        committer = W.Committer()
        self.assertEqual(committer.take(0.0, 3.0, words_at("a b c d e", 0.2))[2:], ([w for w in words_at("a b c d e", 0.2)],))
        got = committer.take(8.0, 15.0, words_at("x y", 8.2))            # the windows between were dropped
        self.assertEqual((got[0], got[1], [w[2] for w in got[2]]), (8.0, 15.0, ["x", "y"]))
        self.assertIsNone(committer.take(4.0, 11.0, []), "a window from before is ignored")

    def test_speech_over_music_passes_but_hallucinations_and_garbage_do_not(self):
        seg = lambda text, no_speech=0.1, logprob=-0.3, ratio=1.5: SimpleNamespace(
            text=text, no_speech_prob=no_speech, avg_logprob=logprob, compression_ratio=ratio)
        self.assertTrue(W.speech_like(seg("Get zero percent APR", no_speech=0.7, logprob=-0.6)), "music under a voice")
        self.assertTrue(W.speech_like(seg("Get zero percent APR", no_speech=0.2, logprob=-1.2)), "unsure but speech")
        self.assertFalse(W.speech_like(seg("la la", no_speech=0.7, logprob=-1.2)), "Whisper's own silence")
        self.assertFalse(W.speech_like(seg("whatever", logprob=-1.6)))
        self.assertFalse(W.speech_like(seg("go go go go go go", ratio=2.6)))
        self.assertFalse(W.speech_like(seg(" Thank you. ")))
        self.assertFalse(W.speech_like(seg("Thanks for watching!")))

    def test_prompt(self):
        self.assertIsNone(W.prompt(None))
        self.assertEqual(W.prompt("Jeopardy!"), "Jeopardy!")
        long = W.prompt("Game", [f"Player Number{i}" for i in range(200)])
        self.assertLessEqual(len(long), W.PROMPT_CHARS + 1)
        self.assertTrue(long.startswith("Game. Player Number0, Player Number1"))


class SpeechLaneTests(unittest.TestCase):
    def setUp(self):
        from admute import service
        self.service_mod = service
        self.svc = SimpleNamespace(settings={"speech_model": "base.en"}, stopping=unittest.mock.Mock())
        self.svc.stopping.is_set.return_value = False

    def session(self):
        heard = []

        class FakeSession:
            def heard(self, gen, *chunk):
                heard.append((gen,) + chunk)

            def hint(self):
                return None
        return FakeSession(), heard

    def test_each_input_has_its_own_lane_and_backlog(self):
        sp = self.service_mod.Speech(self.svc)
        a, _ = self.session()
        b, _ = self.session()
        for i in range(4):
            sp.submit(a, 1, 4.0 * i, np.zeros(16), 4.0 * i + 3)
        sp.submit(b, 1, 0.0, np.zeros(16), 3.0)
        self.assertEqual(sp.dropped, 2, "a slow input drops its own oldest windows ...")
        self.assertEqual(len(sp.lanes[b].jobs), 1, "... and never another input's")
        first = sp._next()
        self.assertIs(first[0], a, "the window that has waited longest goes first")
        first[1].busy = True
        self.assertIs(sp._next()[0], b, "a busy input's lane waits; the other is transcribed meanwhile")
        sp.forget(a)
        self.assertNotIn(a, sp.lanes)

    def test_words_arrive_as_contiguous_chunks(self):
        sp = self.service_mod.Speech(self.svc)
        s, heard = self.session()
        lane = self.service_mod.Lane()
        fake = FakeWhisper(words_at("alpha beta gamma delta epsilon zeta eta theta", 1.0))
        with unittest.mock.patch.object(W, "load", return_value=object()), \
                unittest.mock.patch.object(W, "transcribe", side_effect=fake):
            win = W.Windower()
            for t0, audio, upto in win.push(0.0, np.zeros(12 * W.RATE, np.float32)):
                sp._work(s, lane, 1, t0, audio, upto, time.monotonic())
        self.assertEqual([(c[1], c[2]) for c in heard], [(0.0, 3.0), (3.0, 7.0), (7.0, 11.0)])
        self.assertEqual([w[2] for c in heard for w in c[3]], "alpha beta gamma delta epsilon zeta eta theta".split())
        self.assertIsNotNone(sp.status()["load"])

    def test_a_model_that_will_not_load_falls_back_to_base(self):
        sp = self.service_mod.Speech(self.svc)
        self.svc.settings["speech_model"] = "distil-large-v3"
        loaded = []

        def load(name, threads, workers):
            if name != "base.en":
                raise OSError("not cached")
            loaded.append((name, threads, workers))
            return object()
        with unittest.mock.patch.object(W, "load", side_effect=load):
            self.assertIsNotNone(sp._model())
            self.assertEqual(sp.model_name, "base.en")
            self.assertIn("distil-large-v3 is unavailable", sp.error)
            self.assertTrue(sp.usable)
            sp._model()
        self.assertEqual(len(loaded), 1, "not loaded again for every window")
        with unittest.mock.patch.object(W, "load", side_effect=OSError("gone")):
            sp.failed.clear()
            sp.model = None
            self.assertIsNone(sp._model())
        self.assertFalse(sp.usable, "no words at all: detection goes on without them")


class GameNamesTests(unittest.TestCase):
    def test_teams_then_lineups_then_rosters(self):
        from admute.sports import names_from_feed
        feed = {"gameData": {"teams": {"away": {"name": "Atlanta Braves", "teamName": "Braves"},
                                       "home": {"name": "Los Angeles Dodgers", "teamName": "Dodgers"}},
                             "players": {"ID1": {"fullName": "Bench Guy"}, "ID2": {"fullName": "Matt Olson"},
                                         "ID3": {"fullName": "Yoshinobu Yamamoto"}}},
                "liveData": {"boxscore": {"teams": {"away": {"battingOrder": [2]}, "home": {"pitchers": [3]}}}}}
        self.assertEqual(names_from_feed(feed), ["Atlanta Braves", "Braves", "Los Angeles Dodgers", "Dodgers",
                                                 "Matt Olson", "Yoshinobu Yamamoto", "Bench Guy"])
        self.assertEqual(names_from_feed({}), [])


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
        svc = SimpleNamespace(embed=None, model=D.DEFAULT_MODEL, overlays=OV.Library(catalogue=None), settings={"speech": True, "sensitivity": .5, "max_mute": 300},
                              library=T.AdLibrary(), marked_show=lambda span_id: span_id.endswith("-199"),
                              prints=FP.PrintDB(), note=lambda *a, **k: None,
                              speech=SimpleNamespace(usable=True, submit=lambda *a: sent.append(a)),
                              frames=SimpleNamespace(save=lambda *a: None), quiet=lambda *a: False)
        svc.policy_config = lambda lookahead: Service.policy_config(svc, lookahead)
        return svc, sent

    def test_audio_is_cut_into_overlapping_whisper_windows(self):
        svc, sent = self.service()
        s = Session(svc, "k" * 32, {"lookahead": 3})
        s.base = 0
        piece = np.zeros(1600, np.float32)
        for i in range(130):                       # 13 s in 0.1 s buffers
            s._hear(i / 10, piece)
        # (session, gen, window start, audio, words given up to)
        self.assertEqual([(round(c[2], 2), len(c[3]) / W.RATE, round(c[4], 2)) for c in sent],
                         [(0.0, 4.0, 3.0), (0.0, 8.0, 7.0), (4.0, 8.0, 11.0)])
        for i in range(150, 200):                  # a gap: the last window gives all it held back ...
            s._hear(i / 10, piece)
        self.assertEqual((round(sent[3][2], 2), round(sent[3][4], 2)), (8.0, 13.0))
        self.assertEqual((round(sent[4][2], 2), round(sent[4][4], 2)), (15.0, 18.0), "... and a new run starts")
        gen = sent[0][1]
        s.heard(gen, 0.0, 3.0, [[1.0, 1.3, "hello"]])
        s._reset()
        s.heard(gen, 3.0, 7.0, [[5.0, 5.3, "stale"]])
        self.assertEqual(s.speech, [], "words for an earlier timeline are dropped")

    def test_new_words_go_to_master_once_on_the_input_clock(self):
        svc, _ = self.service()
        s = Session(svc, "k" * 32, {"lookahead": 3})
        s.base = 50 * 1_000_000_000
        s.heard(s.gen, 0.0, 3.0, [[1.0, 1.25, "hello"], [1.5, 1.75, "there"]])
        msg = s._message()
        self.assertTrue(msg["speech"])
        self.assertEqual(msg["words"], [[51_000_000_000, 51_250_000_000, "hello"], [51_500_000_000, 51_750_000_000, "there"]])
        self.assertNotIn("words", s._message(), "each word once")
        svc.speech.usable = False
        self.assertFalse(s._message()["speech"], "captions transcribe for themselves")

    def test_whisper_is_told_the_programme_and_its_names(self):
        svc, _ = self.service()
        s = Session(svc, "k" * 32, {"lookahead": 3, "title": "Baseball Night"})
        self.assertEqual(s.hint(), "Baseball Night.")
        s.game = {"title": "Atlanta Braves at Los Angeles Dodgers"}
        s.gate = SimpleNamespace(names=["Atlanta Braves", "Braves", "Freddie Freeman"])
        self.assertEqual(s.hint(), "Atlanta Braves at Los Angeles Dodgers. Atlanta Braves, Braves, Freddie Freeman.")

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
