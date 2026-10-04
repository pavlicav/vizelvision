"""MobileNetV2 (ONNX, frozen ImageNet) as a generic content embedding, as in the
offline stripper (~/scratch/ad_detection/features.py). CPU only, few threads."""
from __future__ import annotations

import os

import numpy as np

MODEL = os.environ.get("ADMUTE_MODEL", os.path.expanduser("~/scratch/ad_detection/models/mobilenetv2.onnx"))
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


class Embedder:
    def __init__(self, model: str = MODEL, threads: int = 1):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        arr = (rgb.astype(np.float32) / 255.0 - _MEAN) / _STD
        return self.session.run(None, {self.input: arr.transpose(2, 0, 1)[None]})[0][0].astype(np.float32)
