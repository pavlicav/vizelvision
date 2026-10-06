"""Fit the per-second evidence model on labelled recordings.

  python -m admute.train            # leave-one-tape-out report, then fit on all and write model.json
  python -m admute.train --dry-run  # report only

Features are the live ones (admute.detector), computed by replaying each tape
causally with the current model, so the memories (which depend on the labels the
detector itself settled) look as they would live. Seconds before the programme
memory exists are left out, as the policy never mutes there.

With transcripts cached (python -m admute.speech TAPE), the text features join in.
Their word lexicon (ad/show log-odds per word) is learnt from labelled words, and
is cross-fitted: a tape's training rows use a lexicon learnt from the *other*
tapes, as a new programme's will live, so the model does not over-trust it.

With fingerprints cached (python -m admute.fingerprint TAPE), so do the fp_ features.
Their known-ads database is cross-fitted the same way: seeded with the labelled ads of
the other tapes only. Replays learn from their own confirmed breaks, as live does.

The overlay features (ov_*) are set by hand in model.json and never fitted: an overlay
only ever argues for the programme, which a fit on a few tapes (where the score bug is
never up in an ad) would turn into an unbounded weight. They are carried over as they are.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import collections
import time

import numpy as np

from . import detector, fingerprint, replay, speech, text

LEX_MIN = 3          # a word needs this many labelled uses to get a weight
HAND_SET = ("ov_",)  # features whose weights are set by hand, not fitted
LEX_ALPHA = 1.0


def labelled_words(path: str, truth: dict) -> list[tuple[str, int]]:
    """(token, 1 ad / 0 show) for every transcribed word with a clear label."""
    chunks = speech.words_for(path) or []
    spans = [(a, b, {"ad": 1, "next": -1, "ignore": -1}.get(lab, 0)) for a, b, lab in truth["spans"]]
    out = []
    for _, _, words in chunks:
        for start, end, word in words:
            tok, mid = text.token(word), (start + end) / 2
            if tok is None:
                continue
            lab = next((y for a, b, y in spans if a <= mid < b), 0)
            if lab >= 0:
                out.append((tok, lab))
    return out


def fit_lexicon(pairs) -> dict:
    count = {0: collections.Counter(), 1: collections.Counter()}
    for tok, lab in pairs:
        count[lab][tok] += 1
    vocab = set(count[0]) | set(count[1])
    n = {k: sum(c.values()) + LEX_ALPHA * len(vocab) for k, c in count.items()}
    lex = {}
    for tok in vocab:
        if count[0][tok] + count[1][tok] >= LEX_MIN:
            lex[tok] = round(math.log((count[1][tok] + LEX_ALPHA) / n[1]) - math.log((count[0][tok] + LEX_ALPHA) / n[0]), 3)
    return lex


def ad_wording(pairs) -> list[str]:
    """The ad library's seed: shingles of consecutive words all labelled ad."""
    out = set()
    for i in range(len(pairs) - text.REPEAT_N + 1):
        run = pairs[i:i + text.REPEAT_N]
        if all(lab == 1 for _, lab in run):
            out.add(" ".join(tok for tok, _ in run))
    return sorted(out)


SEED_TAG = "recordings"
SEED_FILE = "known_ads_seed.npz"


def ad_prints(path: str, truth: dict) -> list:
    """The kept landmarks of each labelled ad span: [(t, h)]."""
    lm = fingerprint.prints_for(path, compute=False)
    if lm is None:
        return []
    t, h = lm[:, 0], lm[:, 1].astype(np.uint32)
    k = fingerprint.keep(h)
    t, h = t[k], h[k]
    out = []
    for a, b, lab in truth["spans"]:
        if lab == "ad":
            i, j = np.searchsorted(t, a), np.searchsorted(t, b)
            out.append((t[i:j], h[i:j]))
    return out


def seed_db(spans) -> fingerprint.PrintDB:
    """A known-ads database of labelled ad spans (each counts at once: it was labelled)."""
    db = fingerprint.PrintDB()
    for t, h in spans:
        if len(h) >= 4 * fingerprint.MIN_LANDMARKS:
            db._insert("ad", t - t[0], h, {"seed": SEED_TAG, "dur": round(float(t[-1] - t[0]), 1)})
    return db


def rows(path: str, truth: dict, model: dict, db=None, prints=True):
    sig = replay.extract(path)
    res = replay.run(sig, model=model, words=speech.words_for(path), db=db,
                     prints=fingerprint.prints_for(path, compute=False) if prints else None)
    n = len(res["logit"])
    y10 = replay.truth_steps(truth, n * 10).astype(float)
    y10[y10 < 0] = np.nan                              # the next programme: left out
    y = y10.reshape(n, 10).mean(1)
    names = model["features"]
    X = np.stack([res["feats"][k][:n] for k in names], 1)
    warm = ~np.isnan(res["feats"]["recurrence"][:n])
    keep = warm & ~np.isnan(y) & ((y < 0.05) | (y > 0.95))   # whole seconds only
    return X[keep], (y[keep] > 0.5).astype(int)


def fit(X: np.ndarray, y: np.ndarray, names: list[str], base: dict) -> dict:
    from sklearn.linear_model import LogisticRegression
    with np.errstate(all="ignore"):
        mean = np.nan_to_num(np.nanmean(X, 0))
        # A feature that never varied (say no show sound was learnt) keeps a usable scale.
        scale = np.maximum(np.nan_to_num(np.nanstd(X, 0)), 1e-3)
    Z = np.nan_to_num((X - mean) / scale)            # missing -> the mean (contributes 0)
    clf = LogisticRegression(C=0.1, class_weight="balanced", max_iter=1000).fit(Z, y)
    return {**base, "features": names, "mean": mean.round(4).tolist(), "scale": scale.round(4).tolist(),
            "coef": clf.coef_[0].round(4).tolist(), "intercept": round(float(clf.intercept_[0]), 4)}


def with_hand_set(m: dict, model: dict) -> dict:
    """``m`` plus the hand-set features of ``model`` (weights as they are)."""
    extra = [i for i, k in enumerate(model["features"]) if k.startswith(HAND_SET) and k not in m["features"]]
    return {**m, **{key: list(m[key]) + [model[key][i] for i in extra] for key in ("mean", "scale", "coef")},
            "features": list(m["features"]) + [model["features"][i] for i in extra]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.train")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--loo-replay", action="store_true", help="score each tape with a model fitted without it")
    ap.add_argument("--features", default=None, help="comma-separated feature names")
    ap.add_argument("--no-text", action="store_true", help="leave the transcripts out")
    ap.add_argument("--no-prints", action="store_true", help="leave the audio fingerprints out")
    ap.add_argument("--lookahead", type=float, default=3.0, help="for --loo-replay (5 with live captions on)")
    ap.add_argument("--out", default=detector.MODEL_JSON, help="where to write the model")
    args = ap.parse_args(argv)
    base = detector.load_model()
    model = base
    tapes = [(replay.find_tape(t["file"]), t) for _, t in replay.load_truths()]
    untranscribed = [os.path.basename(p) for p, _ in tapes if not speech.words_for(p)]
    use_text = not args.no_text and not untranscribed
    if untranscribed and not args.no_text:
        print(f"no text features: no {speech.MODEL} {speech.SCHEME} transcript for {', '.join(untranscribed)} "
              f"(python -m admute.speech TAPE)", file=sys.stderr)
    use_prints = not args.no_prints and all(fingerprint.prints_for(p, compute=False) is not None for p, _ in tapes)
    visual = [k for k in base["features"] if not k.startswith(("txt_", "fp_") + HAND_SET)]
    names = args.features.split(",") if args.features else (
        visual + (list(detector.TEXT_FEATURES) if use_text else []) + (list(detector.PRINT_FEATURES) if use_prints else []))
    base = {**base, "features": names, "mean": [base["mean"][base["features"].index(k)] if k in base["features"] else 0
                                                 for k in names],
            "scale": [base["scale"][base["features"].index(k)] if k in base["features"] else 1 for k in names],
            "coef": [base["coef"][base["features"].index(k)] if k in base["features"] else 0 for k in names]}
    # The base model never weighs text or prints (its labels drive the memories, as they did).
    base = {**base, "coef": [c if not k.startswith(("txt_", "fp_")) else 0 for k, c in zip(names, base["coef"])]}
    adp = {os.path.basename(p): ad_prints(p, t) if use_prints else [] for p, t in tapes}

    def db_for(without):
        """Known ads from every tape but ``without``: as a new programme meets them live."""
        return seed_db([sp for k, sps in adp.items() if k not in without for sp in sps]) if use_prints else None
    words = {os.path.basename(p): labelled_words(p, t) if use_text else [] for p, t in tapes}
    cache = {}

    def lexicon(without):
        return fit_lexicon([w for k, ws in words.items() if k not in without for w in ws]) if use_text else {}

    def text_model(without):
        """Words learnt from every tape but ``without``: as a new programme meets them live."""
        if not use_text:
            return {}
        return {"lexicon": lexicon(without), "ads": sorted({sh for k, ws in words.items() if k not in without
                                                             for sh in ad_wording(ws)})}

    def data_for(name, without):
        """Rows of one tape, its text judged by a lexicon learnt without ``without``."""
        key = (name, frozenset(without) if (use_text or use_prints) else None)
        if key not in cache:
            path, truth = next((p, t) for p, t in tapes if os.path.basename(p) == name)
            cache[key] = rows(path, truth, {**base, "text": text_model(without)}, db=db_for(without),
                              prints=use_prints)
        return cache[key]

    data = {os.path.basename(p): None for p, _ in tapes}
    print("leave-one-tape-out (per-second, warm seconds):")
    for name in data:
        train = [k for k in data if k != name]
        X = np.concatenate([data_for(k, {k, name})[0] for k in train])
        y = np.concatenate([data_for(k, {k, name})[1] for k in train])
        m = fit(X, y, names, base)
        Xt, yt = data_for(name, {name})
        z = np.full(len(Xt), m["intercept"])
        for i in range(len(names)):
            v = (Xt[:, i] - m["mean"][i]) / m["scale"][i]
            z += m["coef"][i] * np.nan_to_num(v)
        pred = z > 0
        print(f"  {name[:60]:60s} acc {np.mean(pred == yt):.3f}  show->ad {np.mean(pred[yt == 0]):.3f}  "
              f"ad->show {np.mean(~pred[yt == 1]):.3f}  n={len(yt)}")
    if args.loo_replay:
        # The honest number: fit without a tape, then run the whole live loop on it.
        print("leave-one-tape-out, full replay:")
        for path, truth in tapes:
            name = os.path.basename(path)
            train = [k for k in data if k != name]
            X = np.concatenate([data_for(k, {k, name})[0] for k in train])
            y = np.concatenate([data_for(k, {k, name})[1] for k in train])
            m = with_hand_set(fit(X, y, names, base), model)
            m["text"] = text_model({name})
            from .policy import PolicyConfig
            res = replay.run(replay.extract(path), model={**detector.load_model(), **m}, gate=replay.gate_for(truth),
                             words=speech.words_for(path) if use_text else None,
                             prints=fingerprint.prints_for(path, compute=False) if use_prints else None,
                             db=db_for({name}), cfg=PolicyConfig(lookahead=args.lookahead))
            sc = replay.score(res, truth)
            clipped = sum(b["clipped"] for b in sc["breaks"])
            print(f"  {name[:60]:60s} show muted {sc['program_muted']:6.1f}s ({sc['program_muted_per_hour']:5.1f}/h)"
                  f"  coverage {sc['coverage']:.1%}  spans {sc['spans']}  retracted {sc['retracted']}"
                  f"  late returns {clipped:.1f}s")
        return
    X = np.concatenate([data_for(k, {k})[0] for k in data])
    y = np.concatenate([data_for(k, {k})[1] for k in data])
    m = with_hand_set(fit(X, y, names, base), model)
    m["trained_on"] = sorted(data)
    m["text"] = {**text_model(set()), "model": speech.MODEL, "scheme": speech.SCHEME} if use_text else None
    print(json.dumps({k: m[k] for k in ("features", "coef", "intercept")}))
    if not args.dry_run:
        out = {k: m[k] for k in ("features", "mean", "scale", "coef", "intercept", "trained_on")}
        if model.get("notes"):
            out["notes"] = model["notes"]
        if m["text"]:
            out["text"] = m["text"]
        if use_prints:
            # Known ads seed the sidecar's database (admute-prints.npz): admute.seed's build of
            # every collected recording if there is one, else the labelled tapes' ads.
            extra = os.path.join(os.path.dirname(args.out), "known_ads_extra.npz")
            if os.path.exists(extra):
                out["prints"] = {"seed": os.path.basename(extra),
                                 "tag": "extra-" + time.strftime("%Y%m%d-%H%M%S", time.localtime(os.path.getmtime(extra)))}
            else:
                seed = db_for(set())
                seed.dirty = True
                seed.save(os.path.join(os.path.dirname(args.out), SEED_FILE))
                out["prints"] = {"seed": SEED_FILE, "tag": SEED_TAG + "-" + "-".join(sorted(k[:10] for k in data))}
        with open(args.out, "w") as f:
            json.dump(out, f, indent=1)
        print("wrote", args.out)


if __name__ == "__main__":
    main()
