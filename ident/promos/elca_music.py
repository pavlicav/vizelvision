"""Here I Stand's sound (elca.py): winter wind and boots on snow, the organ's prelude through
the walls; the four blows of the hammer are the open logo, each nail ringing its note with the
steeple's bell under it; then "A Mighty Fortress" (Luther, 1529) on the organ, a quarter note a
beat, heard through the oak doors, then through the floor of the fellowship hall (the urn
percolating, a fluorescent hum, a teaspoon), and clear as it lands on the closed logo: full
organ, choir and bells as the rose blooms. A quiet plagal Amen under "There's bars downstairs."
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
rng = np.random.default_rng(1529)

# "A mighty fortress is our God" in D, and the organ's chords under it
FORTRESS = (74, 74, 74, 69, 71, 73, 74, 71, 69)
CHORDS = ((50, 57, 62, 66), (50, 57, 62, 66), (47, 54, 59, 62), (50, 57, 62, 66), (43, 55, 59, 62),
          (45, 57, 61, 64), (50, 57, 62, 66), (43, 55, 59, 62), (45, 52, 57, 61))


def winter_wind(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    gust = 0.55 + 0.45 * np.sin(2 * np.pi * 0.31 * t) * np.sin(2 * np.pi * 0.13 * t + 1.3)
    x = J.butter(J.noise(n), 'band', [180, 700]) * gust + J.butter(J.noise(n), 'band', [1800, 4000]) * 0.15 * gust
    return x * np.clip(t / 0.4, 0, 1) * vel * 0.5


def crunch(vel=1.0):
    """A boot in dry snow: a short squeaky crush."""
    n = int(0.16 * SR)
    t = J.times(n)
    grains = J.butter(J.noise(n) * (rng.random(n) < 0.25), 'band', [900, 5000])
    return grains * np.exp(-t / 0.05) * vel * 0.8


def knock(vel=1.0):
    """The hammer on a nail in old oak: the wood's thud and the strike's crack."""
    n = int(0.4 * SR)
    t = J.times(n)
    thud = np.sin(2 * np.pi * np.cumsum(95 + 80 * np.exp(-t / 0.02)) / SR) * np.exp(-t / 0.09)
    crack = J.butter(J.noise(n), 'band', [1200, 6000]) * np.exp(-t / 0.006)
    body = sum(g * np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, g, d in ((410, 0.5, 0.05), (930, 0.3, 0.03)))
    return np.tanh(1.6 * (0.9 * thud + 0.8 * crack + body)) * vel


def nail_ring(midi, vel=1.0):
    """The nail's head rings the note: a steel ping, a little inharmonic, quickly gone."""
    n = int(0.9 * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = sum(g * np.sin(2 * np.pi * f * r * t + rng.random() * 6) * np.exp(-t / d)
            for r, g, d in ((1.0, 1.0, 0.35), (2.0, 0.35, 0.18), (2.76, 0.25, 0.1), (5.4, 0.12, 0.05)))
    return x * vel * 0.5


def rustle(length=0.3, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [1800, 7000]) * np.sin(np.pi * t / length) * (0.6 + 0.4 * (rng.random(n) < 0.3)) \
        * vel * 0.5


def snow_fall(vel=1.0):
    n = int(0.7 * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [2500, 8000]) * np.exp(-t / 0.25) * np.clip(t / 0.05, 0, 1) * vel * 0.25


def percolator(length, vel=1.0):
    """The big coffee urn: a burbling, bubbles popping at random pitches."""
    n = int(length * SR)
    out = J.butter(J.noise(n), 'band', [150, 600]) * 0.25
    pops = np.random.default_rng(19)
    for _ in range(int(length * 14)):
        at = pops.integers(0, n - int(0.05 * SR))
        m = int(0.04 * SR)
        tt = J.times(m)
        f = pops.uniform(300, 1100)
        out[at:at + m] += np.sin(2 * np.pi * np.cumsum(f * (1 + 0.8 * tt / 0.04)) / SR) * np.exp(-tt / 0.012) * 0.5
    return out * vel


def fluorescent(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    return (np.sin(2 * np.pi * 120 * t) + 0.3 * np.sin(2 * np.pi * 240 * t) + 0.1 * np.sin(2 * np.pi * 360 * t)) * vel * 0.05


def murmur(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    talk = J.butter(J.noise(n), 'band', [250, 1300])
    syllables = J.butter(np.abs(J.noise(n)), 'low', 6) * 4
    return talk * (0.4 + syllables) * np.clip(t / 0.3, 0, 1) * vel * 0.3


def cue(voice):
    P = M.hits('elca')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    # outside: the wind, boots on snow, the prelude through the walls
    desk.wide(lambda: winter_wind(P.HALL[0] + 0.3), 0.0, 0.5, hall=0.1)
    for k in range(4):
        desk.add(crunch(0.9), 0.25 + k * 0.35, 0.35, 0.5 - 0.2 * k, hall=0.1)
    for chord, at, gate in (((50, 57, 62, 66), 0.05, 0.6), ((55, 59, 62, 67), 0.65, 0.55)):
        for note in chord:
            desk.add(J.butter(M.pipe_organ(note, gate, 0.7), 'low', 380), at, 0.16, -0.1, hall=0.3)
    # the page goes up, four blows: the open logo, a nail and a bell a note
    desk.add(rustle(0.32), P.PAGE_UP[0], 0.45, -0.3, hall=0.15)
    for k, (when, note) in enumerate(zip(P.HAMMER, M.OPEN)):
        desk.add(knock(1.0 if k < 3 else 1.2), when, 0.5, 0.25 - 0.15 * (k % 2), hall=0.25)
        desk.add(nail_ring(note, 1.0), when + 0.003, 0.32, 0.15, hall=0.45)
        desk.add(M.church_bell(note - 12, 2.6, 0.8), when, 0.28, -0.3, hall=0.6)
        desk.add(snow_fall(0.8 + 0.4 * (k == 3)), when + 0.05, 0.4, 0.0, hall=0.2)
    # "A Mighty Fortress": through the doors, through the floor, then clear
    for k, (at, melody, chord) in enumerate(zip(P.HYMN, FORTRESS, CHORDS)):
        inside_hall = at >= P.HALL[0] - 0.1
        cutoff = 3000 if inside_hall else 700
        gain = 0.18 if inside_hall else 0.16
        for note in chord + (melody,):
            sound = M.pipe_organ(note, 0.47, 0.85 if note == melody else 0.7)
            desk.add(J.butter(sound, 'low', cutoff), at, gain * (1.25 if note == melody else 1.0), -0.25 + 0.08 * (note % 7),
                     hall=0.5)
    # the fellowship hall
    hall_len = P.SEAL_IN[1] - P.HALL[0]
    desk.add(fluorescent(hall_len), P.HALL[0], 0.5, 0.2, hall=0.05)
    desk.add(percolator(hall_len), P.HALL[0], 0.35, -0.55, hall=0.15)
    desk.wide(lambda: murmur(hall_len), P.HALL[0], 0.35, hall=0.3)
    desk.add(M.teacup(0.9), P.HALL[0] + 0.55, 0.3, 0.4, hall=0.2)
    desk.add(M.teacup(0.6), P.BAR[0] + 0.25, 0.25, 0.55, hall=0.2)
    # the closed logo: the rose, a part a note; full organ, choir, bells
    S.logo(desk, P.CLOSED, M.CLOSED, organ_=False, choir=True, gain=0.9)
    for when, note in zip(M.at_logo(P.CLOSED), M.CLOSED):
        desk.add(M.church_bell(note - 12, 2.6, 0.9), when, 0.3, 0.3, hall=0.6)
        desk.add(M.pipe_organ(note, 0.4, 0.9), when, 0.12, -0.2, hall=0.6)
    for note in (26, 38, 50, 57, 62, 66, 69):
        desk.add(M.pipe_organ(note, 1.4, 0.9), P.CLOSED, 0.1, -0.3 + 0.1 * (note % 7), hall=0.7)
    for at, chord, sung, gate in ((8.4, (43, 55, 59, 62), (67, 71), 0.45), (8.9, (38, 50, 57, 62), (66, 69), 0.4)):
        for note in chord:                                            # A-men
            desk.add(M.pipe_organ(note, gate, 0.6), at, 0.07, hall=0.7)
        for note in sung:
            desk.add(J.choir(note, gate, 0.5), at, 0.13, -0.3 + 0.3 * (note % 3), hall=0.6)
    desk.wide(lambda: winter_wind(length - P.SEAL_IN[0]), P.SEAL_IN[0], 0.18, hall=0.1)
    return M.mixdown(desk, voice, length, end, grit=0.6)
