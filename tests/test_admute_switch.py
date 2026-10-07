"""The detector switch: classic or new (admute/model_new.json, CLIP picture scores)."""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from admute import clip, detector as D, features
from admute import service as S
from roku_stream.admute_settings import validate
from roku_stream.errors import ConfigError

ROOT = Path(__file__).resolve().parent.parent


class SettingTests(unittest.TestCase):
    def test_classic_by_default_and_only_the_two(self):
        self.assertEqual(validate({})["detector"], "classic")
        self.assertEqual(validate({"detector": "new"})["detector"], "new")
        with self.assertRaises(ConfigError):
            validate({"detector": "fancy"})


class ModelTests(unittest.TestCase):
    def test_hand_set_weights_are_the_classic_ones_scale_and_all(self):
        # Show sound and the overlays are set by hand. The lab's rows barely saw show sound,
        # so fitted scaling made a chance match weigh 45 times the classic's (2026-10-07: only
        # fingerprinted ads were muted on The View).
        classic, new = D.load_model(), D.load_model(str(S.NEW_MODEL_JSON))
        hand = {k: (mu, sc, c) for k, mu, sc, c in zip(classic["features"], classic["mean"], classic["scale"], classic["coef"])
                if k == "fp_show" or k.startswith("ov_")}
        for part in (new, new["warm"]):
            for k, want in hand.items():
                i = part["features"].index(k)
                self.assertEqual((part["mean"][i], part["scale"][i], part["coef"][i]), want, k)

    def test_the_new_model_scores_the_picture(self):
        new = D.load_model(str(S.NEW_MODEL_JSON))
        for k in clip.FEATURES:
            self.assertIn(k, new["features"])
            self.assertIn(k, new["warm"]["features"])
        self.assertEqual(new["policy"]["grace"], 5.0)


class SignalsTests(unittest.TestCase):
    def test_an_unscored_second_is_nan_and_the_rest_stay_aligned(self):
        scores = iter([{"img_zeroshot2": 0.1}, {}, {"img_zeroshot2": 0.3}])
        sig = features.Signals(scorer=lambda f: next(scores))
        for t in range(3):
            sig.push_rgb(np.array([float(t)]), np.zeros((1, 224, 224, 3), np.uint8))
        vals = sig.img["img_zeroshot2"]
        self.assertEqual(len(vals), len(sig.emb))
        self.assertEqual(vals[0], 0.1)
        self.assertTrue(math.isnan(vals[1]))
        self.assertAlmostEqual(vals[2], 0.3)
        sig.trim_seconds(2)
        self.assertEqual(S.Source(sig, []).image("img_zeroshot2", 2), vals[-1])
        self.assertTrue(math.isnan(S.Source(sig, []).image("img_zeroshot2", 0)), "trimmed: unknown")


class ReloadTests(unittest.TestCase):
    def test_new_weights_load_without_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "model_new.json"
            path.write_text(json.dumps({"intercept": -1.0}))
            svc = SimpleNamespace(models={}, new_model_at=None)
            with mock.patch.object(S, "NEW_MODEL_JSON", path):
                self.assertFalse(S.Service._load_new_model(svc), "the first load is not a change")
                self.assertEqual(svc.models["new"]["intercept"], -1.0)
                self.assertFalse(S.Service._load_new_model(svc), "unchanged")
                path.write_text(json.dumps({"intercept": -2.0}))
                os.utime(path, (svc.new_model_at + 5, svc.new_model_at + 5))
                self.assertTrue(S.Service._load_new_model(svc))
                self.assertEqual(svc.models["new"]["intercept"], -2.0)
                path.write_text("{half")
                os.utime(path, (svc.new_model_at + 10, svc.new_model_at + 10))
                self.assertFalse(S.Service._load_new_model(svc), "half written: keep the old")
                self.assertEqual(svc.models["new"]["intercept"], -2.0)


if __name__ == "__main__":
    unittest.main()
