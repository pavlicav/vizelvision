"""Live ad muting: the detector side.

The master worker taps every live input's decoded media (``tap``) and streams it
here. ``features`` turns it into per-step signals, ``detector`` finds seams and ad
evidence, and ``policy`` decides when the program audio goes quiet. ``replay``
runs recordings through exactly the same code, causally, to measure it.

This package needs numpy (and onnxruntime for embeddings). It never imports gi,
so it runs under the conda Python, apart from the master worker.
"""
