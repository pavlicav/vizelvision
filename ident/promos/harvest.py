"""The Thanksgiving idents' own sounds (guest-of-honor, cat-leaf-pile, hand-turkey), written
with music.py's kit: a wild turkey's gobble and its soft putts, its claws on a floor, a match
struck, dry leaves (a footstep, a rustle, a whole pile going up), and a crayon on paper.
"""
import numpy as np

import jingle as J

SR = J.SR
rng = np.random.default_rng(1621)


def gobble(length=0.6, vel=1.0, pitch=1.0):
    """A wild turkey's gobble: a fast gargling warble, a dozen syllables a second that run
    down in pitch, bright in the throat."""
    n = int(length * SR)
    t = J.times(n)
    rate = 21 * (1 - 0.18 * t / length)
    syll = np.sin(2 * np.pi * np.cumsum(rate) / SR)
    f = np.geomspace(620, 380, n) * pitch * (1 + 0.22 * syll)
    phase = 2 * np.pi * np.cumsum(f) / SR
    x = sum(np.sin(k * phase) / k ** 1.1 for k in range(1, 9))
    x = J.formant(x, 900 * pitch, 260) * 1.2 + J.formant(x, 2300 * pitch, 400) * 0.6 + 0.15 * x
    chop = np.clip(0.5 + 0.5 * syll, 0, 1) ** 1.4
    env = np.clip(t / 0.03, 0, 1) * np.clip((length - t) / 0.12, 0, 1)
    breath = J.butter(J.noise(n), 'band', [1200, 4000]) * 0.08
    return np.tanh(1.5 * (x * chop + breath) * env) * vel * 0.6


def putt(vel=1.0, pitch=1.0):
    """A soft, contented putt: a short pitched cluck."""
    n = int(0.09 * SR)
    t = J.times(n)
    f = 780 * pitch * (1 - 0.25 * t / 0.09)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(4 * np.pi * np.cumsum(f) / SR)
    return J.formant(x, 1100 * pitch, 300) * np.exp(-t / 0.025) * np.clip(t / 0.004, 0, 1) * vel * 1.4


def claws(vel=1.0):
    """A turkey's foot set down on a wooden floor: a soft tock and a tick of claws."""
    n = int(0.1 * SR)
    t = J.times(n)
    tock = np.sin(2 * np.pi * np.cumsum(260 + 160 * np.exp(-t / 0.01)) / SR) * np.exp(-t / 0.025)
    tick = J.butter(J.noise(n), 'band', [2500, 7000]) * (np.exp(-t / 0.003) + 0.6 * np.exp(-np.abs(t - 0.018) / 0.002))
    return (0.6 * tock + 0.5 * tick) * vel


def match(vel=1.0):
    """A match struck: the rasp along the box, then the head catching with a soft whoomph."""
    n = int(0.6 * SR)
    t = J.times(n)
    rasp = J.butter(J.noise(n), 'band', [1500, 6500]) * np.clip(t / 0.01, 0, 1) * np.exp(-t / 0.05) * \
        (0.6 + 0.4 * (rng.random(n) < 0.3))
    catch = J.butter(J.noise(n), 'band', [200, 1500]) * np.clip((t - 0.06) / 0.04, 0, 1) * np.exp(-np.clip(t - 0.06, 0, None) / 0.15)
    return (0.8 * rasp + 0.9 * catch) * vel


def crunch(length=0.18, vel=1.0, seed=0):
    """Dry leaves underfoot: a scatter of tiny crackles."""
    r = np.random.default_rng(seed)
    n = int(length * SR)
    t = J.times(n)
    grains = (r.random(n) < 0.06) * r.uniform(-1, 1, n)
    x = J.butter(grains, 'band', [1200, 9000]) * 3 + J.butter(J.noise(n), 'band', [600, 3000]) * 0.15
    return x * np.clip(t / 0.005, 0, 1) * np.exp(-t / (length * 0.45)) * vel


def rustle(length, vel=1.0, seed=1):
    """Leaves stirring: crackles riding a breath of noise, swelling and falling."""
    r = np.random.default_rng(seed)
    n = int(length * SR)
    t = J.times(n)
    grains = (r.random(n) < 0.02) * r.uniform(-1, 1, n)
    x = J.butter(grains, 'band', [1500, 9000]) * 2.5 + J.butter(J.noise(n), 'band', [800, 4000]) * 0.25
    return x * np.sin(np.pi * t / length) ** 0.7 * vel


def leaf_burst(vel=1.0):
    """A whole pile of leaves going up: a crash of crackle and a long settling hiss."""
    n = int(2.2 * SR)
    t = J.times(n)
    grains = (rng.random(n) < 0.12) * rng.uniform(-1, 1, n)
    crackle = J.butter(grains, 'band', [900, 9000]) * 3 * (np.exp(-t / 0.18) + 0.25 * np.exp(-t / 0.9))
    whoosh = J.butter(J.noise(n), 'band', [300, 2500]) * np.exp(-t / 0.25) * 0.6
    thump = np.sin(2 * np.pi * np.cumsum(80 + 60 * np.exp(-t / 0.02)) / SR) * np.exp(-t / 0.1) * 0.7
    return np.tanh((crackle + whoosh + thump) * vel)


def crayon(length, vel=1.0, seed=2, rate=7.0):
    """A wax crayon on construction paper: a soft, papery drag, pressing on each stroke."""
    r = np.random.default_rng(seed)
    n = int(length * SR)
    t = J.times(n)
    stroke = 0.35 + 0.65 * np.abs(np.sin(np.pi * rate * t + r.random() * 3)) ** 0.8
    grit = J.butter(J.noise(n), 'band', [500, 3800]) * (0.7 + 0.3 * (r.random(n) < 0.4))
    tooth = J.butter(J.noise(n), 'band', [140, 500]) * 0.4
    return (grit + tooth) * stroke * np.clip(t / 0.02, 0, 1) * np.clip((length - t) / 0.03, 0, 1) * vel * 0.7
