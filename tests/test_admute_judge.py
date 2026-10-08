"""The transcript judge (admute/judge.py) and how a session uses its answers.

  /home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_judge
"""
import io
import json
import math
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import numpy as np  # noqa: F401  (the session needs it)
except ImportError:  # the system Python (unittest discover): these run under conda
    raise unittest.SkipTest("needs numpy: run with /home/vivian/miniconda3/bin/python3")

from admute import detector as D, judge as J, overlays as OV


def words(text, t0):
    return [(t0 + k, t0 + k + 0.5, w) for k, w in enumerate(text.split())]


class Reply:
    def __init__(self, text, usage=(300, 40)):
        self.body = json.dumps({"content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": text}],
                                "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}}).encode()

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, *a):
        return False


class PromptTests(unittest.TestCase):
    def test_the_labs_prompt(self):
        chunks = [(0.0, 4.0, words("and that's a strikeout", 0.0)), (4.0, 8.0, []),
                  (30.0, 34.0, words("get the new iPhone on us", 30.0))]
        self.assertEqual(J.prompt(chunks, 2, J.show({"league": "mlb"}, None)),
                         "Programme: a live Major League Baseball game broadcast.\nTranscript, oldest first:\n"
                         "[-34s] and that's a strikeout\n[-30s] (no speech)\n[-4s] >>> NEWEST: get the new iPhone on us")

    def test_what_is_on(self):
        self.assertEqual(J.show({"league": "nfl"}, "x"), "a live NFL football broadcast")
        self.assertEqual(J.show(None, "The View"), "the TV programme The View")
        self.assertEqual(J.show(None, None), "a US TV channel")

    def test_the_answer_is_its_last_number(self):
        self.assertEqual(J.parse("85"), 0.85)
        self.assertEqual(J.parse('The commentator says "a 2-1 lead", so the programme.\n\n3'), 0.03)
        self.assertEqual(J.parse("150"), 1.0)
        self.assertTrue(math.isnan(J.parse("I cannot tell")))


class JudgeTests(unittest.TestCase):
    def judge(self, d, reply="90", **kw):
        keys = Path(d) / "keys.env"
        keys.write_text("OTHER=1\nexport ANTHROPIC_API_KEY='sk-test'\n")
        sent = []

        def opener(req, timeout):
            sent.append(json.loads(req.data))
            if isinstance(reply, Exception):
                raise reply
            return Reply(reply)
        return J.Judge(keys_file=keys, ledger=Path(d) / "admute-judge.json", opener=opener, **kw), sent

    def test_a_call_answers_and_counts_what_it_cost(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            j, sent = self.judge(d)
            self.assertIsNone(j.why_not(1.0))
            self.assertEqual(j.ask("Programme: x."), 0.9)
            body = sent[0]
            self.assertEqual((body["model"], body["thinking"], body["output_config"]),
                             (J.MODEL, {"type": "adaptive"}, {"effort": "medium"}))
            self.assertNotIn("temperature", body, "Haiku 5.5 takes none")
            st = j.status(1.0)
            self.assertEqual(st["calls_today"], 1)
            self.assertAlmostEqual(st["usd_today"], (300 * 0.10 + 40 * 0.50) / 1e6, places=6)
            again, _ = self.judge(d)
            self.assertEqual(again.calls, 1, "the day's spend survives a restart")

    def test_the_budget_and_the_key(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            j, _ = self.judge(d)
            j.usd = 1.0
            self.assertIn("budget", j.why_not(1.0))
            j.day = "2000-01-01"
            self.assertIsNone(j.why_not(1.0), "a new day, a new budget")
            nokey = J.Judge(keys_file=Path(d) / "missing.env")
            self.assertIn("ANTHROPIC_API_KEY", nokey.why_not(1.0))
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-env"}):
                self.assertIsNone(nokey.why_not(1.0))

    def test_workers_answer_fail_and_skip(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            stop = threading.Event()
            j, _ = self.judge(d)
            got = []
            chunks = [(0.0, 4.0, words("buy now", 0.0))]
            j.submit(got.append, chunks, 0, "a US TV channel")
            j.jobs.appendleft((time.monotonic() - J.STALE - 1, got.append, chunks, 0, "x"))   # too late to matter
            worker = threading.Thread(target=j.run, args=(stop,), daemon=True)
            worker.start()
            for _ in range(100):
                if len(got) == 2:
                    break
                time.sleep(0.02)
            self.assertTrue(math.isnan(got[0]) and got[1] == 0.9, got)
            self.assertEqual(j.dropped, 1)
            j.opener = lambda req, timeout: (_ for _ in ()).throw(OSError("down"))
            j.submit(got.append, chunks, 0, "x")
            for _ in range(100):
                if len(got) == 3:
                    break
                time.sleep(0.02)
            stop.set()
            self.assertTrue(math.isnan(got[2]))
            self.assertEqual(j.failed, 1)
            self.assertIn("down", j.error)

    def test_a_backlog_drops_the_oldest(self):
        j = J.Judge()
        got = []
        for k in range(J.BACKLOG + 2):
            j.submit(lambda p, k=k: got.append((k, p)), [], 0, "x")
        self.assertEqual([k for k, _ in got], [0, 1])
        self.assertTrue(all(math.isnan(p) for _, p in got))


class WeightsTests(unittest.TestCase):
    def test_without_the_judge_its_own_weights_decide(self):
        part = lambda c, b: {"features": ["bug", J.FEATURE][:2 if c else 1], "mean": [0.0, 0.0][:2 if c else 1],  # noqa: E731
                             "scale": [1.0, 1.0][:2 if c else 1], "coef": [-1.0, c][:2 if c else 1], "intercept": b}
        model = {**D.DEFAULT_MODEL, **part(2.0, -1.0), "warm": part(2.5, -0.5), "nojudge": {**part(0, -2.0), "warm": part(0, -1.5)}}
        det = D.Detector(model, overlays=OV.Library(catalogue=None))
        det.feats = {"bug": [1.0, 1.0], J.FEATURE: [3.0, 3.0], "recurrence": [math.nan, 0.5]}
        self.assertEqual(det.evidence(1), {"bias": -1.0, "bug": -1.0, J.FEATURE: 6.0})
        self.assertEqual(det.evidence(0)["bias"], -0.5, "warming up")
        det.judge_off = True
        self.assertEqual(det.evidence(1), {"bias": -2.0, "bug": -1.0})
        self.assertEqual(det.evidence(0)["bias"], -1.5, "warming up, without the judge")

    def test_the_shipped_model_has_both(self):
        m = D.load_model(os.path.join(os.path.dirname(D.MODEL_JSON), "model_new.json"))
        self.assertIn(J.FEATURE, m["features"])
        self.assertIn(J.FEATURE, m["warm"]["features"])
        self.assertNotIn(J.FEATURE, m["nojudge"]["features"])
        self.assertNotIn(J.FEATURE, m["nojudge"]["warm"]["features"])
        classic = D.load_model()
        for part in (m, m["warm"], m["nojudge"], m["nojudge"]["warm"]):
            for k in ("fp_show", "txt_known_ad", "ov_score", "ov_logo", "ov_ad"):
                i, j = part["features"].index(k), classic["features"].index(k)
                self.assertEqual((part["mean"][i], part["scale"][i], part["coef"][i]),
                                 (classic["mean"][j], classic["scale"][j], classic["coef"][j]), k)


class SessionTests(unittest.TestCase):
    def session(self, with_judge=True, on=True):
        from admute import text as T
        from admute.service import Session, Service
        model = dict(D.DEFAULT_MODEL)
        if with_judge:
            model = {**model, "features": model["features"] + [J.FEATURE], "mean": model["mean"] + [0.0],
                     "scale": model["scale"] + [1.0], "coef": model["coef"] + [0.6]}
        asked = []
        judge = SimpleNamespace(why_not=lambda budget: None,
                                submit=lambda done, chunks, i, what: asked.append((done, chunks, i, what)))
        svc = SimpleNamespace(embed=None, model=model, models={"classic": model}, engine="classic",
                              overlays=OV.Library(catalogue=None), prints=None, judge=judge, judge_ok=on,
                              library=T.AdLibrary(), settings={"sensitivity": .5, "max_mute": 300, "judge": on},
                              speech=SimpleNamespace(usable=False), frames=SimpleNamespace(save=lambda *a: None),
                              quiet=lambda *a: False, resumed=set())
        svc.policy_config = lambda la, game=False, engine="classic": Service.policy_config(svc, la, game, engine)
        svc.lookahead = lambda info: 3.0
        s = Session(svc, "k" * 32, {"lookahead": 3})
        s.game = {"league": "mlb"}
        return s, asked

    def test_each_chunk_with_words_is_judged_and_the_answer_is_late_evidence(self):
        s, asked = self.session()
        s.heard(s.gen, 10.0, 14.0, words("and he strikes him out", 10.0))
        s.heard(s.gen, 14.0, 18.0, [])
        s.heard(s.gen, 18.0, 22.0, words("call now for fifty percent off", 18.0))
        self.assertEqual(len(asked), 2, "a chunk without words is not sent")
        done, chunks, i, what = asked[1]
        self.assertEqual((len(chunks), i, what), (3, 2, J.SHOWS["mlb"]))
        self.assertIn(">>> NEWEST: call now", J.prompt(chunks, i, what))
        self.assertEqual(s.src.extras_pending((J.FEATURE,), 30.0), 10.0, "the detector waits for the first answer")
        done(0.97)
        self.assertEqual(s.src.extras_pending((J.FEATURE,), 30.0), 10.0)
        self.assertAlmostEqual(s.src.image(J.FEATURE, 19), J.logit(0.97))
        self.assertTrue(math.isnan(s.src.image(J.FEATURE, 12)))
        asked[0][0](math.nan)                    # a failed call: nothing known, nothing waited for
        self.assertEqual(s.src.extras_pending((J.FEATURE,), 30.0), math.inf)
        self.assertTrue(math.isnan(s.src.image(J.FEATURE, 12)))

    def test_the_detectors_update_runs_under_the_sessions_lock(self):
        # 2026-10-07 20:26: extras_pending took the session's lock again inside tick() and the
        # sidecar hung on its first second.
        s, asked = self.session()
        s.heard(s.gen, 10.0, 14.0, words("buy now", 10.0))
        done = threading.Event()

        def update():
            with s.lock:
                s.src.extras_pending((J.FEATURE,), 30.0)
                s.src.image(J.FEATURE, 12)
            done.set()
        threading.Thread(target=update, daemon=True).start()
        self.assertTrue(done.wait(2), "deadlocked")

    def test_an_answer_for_an_earlier_timeline_is_dropped(self):
        s, asked = self.session()
        s.heard(s.gen, 10.0, 14.0, words("buy now", 10.0))
        s._reset()
        asked[0][0](0.9)
        self.assertEqual(s.judged, {})

    def test_never_asked_when_off_or_without_its_weight(self):
        for kw in ({"on": False}, {"with_judge": False}):
            s, asked = self.session(**kw)
            s.heard(s.gen, 10.0, 14.0, words("buy now", 10.0))
            self.assertEqual(asked, [], kw)


if __name__ == "__main__":
    unittest.main()
