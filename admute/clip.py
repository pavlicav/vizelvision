"""CLIP ViT-B/32 (LAION-2B, ONNX) zero-shot picture scores for the new detector.

Once a second, the tap's 224x224 colour frame is compared with fixed descriptions
(clip_prompts.npz, made by lab.export_clip) of ads and of programmes:

  img_zeroshot3  the closest ad description minus the closest programme one (sports,
                 studio, game-show, news and talk-show descriptions): above 0 looks like
                 an ad. (zeroshot2, without news and talk shows, muted the noon news on
                 2026-10-07: its open, teases and weather read as ads.)
  img_split      the closest split-screen description (a sponsor panel beside the game
                 in a box) minus the closest ad one: a split-screen counts as the show

Nothing is learnt on the box: the descriptions are fixed, so it works on ads it has never
seen. CPU only, one thread, int8 (89 MB, lab.export_clip then onnxruntime's dynamic
quantisation): about 50 ms a frame on an M1; the Ad mute page shows the box's time.
"""
from __future__ import annotations

import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("ADMUTE_CLIP", os.path.join(HERE, "..", "state", "models", "clip-vit-b32-laion2b.int8.onnx"))
PROMPTS = os.path.join(HERE, "clip_prompts.npz")
FEATURES = ("img_zeroshot3", "img_split")
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


def available(model: str = MODEL) -> bool:
    return os.path.exists(model) and os.path.exists(PROMPTS)


class Scorer:
    def __init__(self, model: str = MODEL, threads: int = 1):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        p = np.load(PROMPTS)
        self.ad = p["ad"]
        self.show = np.concatenate([p["show"], p["game"], p["news"], p["talk"]])
        self.split = p["split"]

    def embed(self, rgb: np.ndarray) -> np.ndarray:
        """rgb: uint8 [224, 224, 3] -> L2-normalised [512]."""
        arr = (rgb.astype(np.float32) / 255.0 - _MEAN) / _STD
        return self.session.run(None, {self.input: arr.transpose(2, 0, 1)[None]})[0][0].astype(np.float32)

    def scores_of(self, e: np.ndarray) -> dict:
        ad = float((self.ad @ e).max())
        return {"img_zeroshot3": ad - float((self.show @ e).max()), "img_split": float((self.split @ e).max()) - ad}

    def __call__(self, rgb: np.ndarray) -> dict:
        return self.scores_of(self.embed(rgb))
