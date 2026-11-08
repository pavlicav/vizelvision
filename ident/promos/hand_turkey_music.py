"""The Hand Turkey's sound (hand_turkey.py): a kindergarten classroom (a murmur of small
voices, a chair scraping) and a glockenspiel tune; the hand pats down on the paper; the crayon
drags round the thumb, then a finger on each note of the open logo, the glockenspiel and a
xylophone on the notes; the paper rustles as the hand lifts; four quick scribbles up the
xylophone, a boing for the googly eye, a pop for the beak; a little blink, two hops on a
spring, its gobble with a kazoo; the closed logo on glockenspiel, xylophone and kazoo as the
wordmark is scribbled a letter at a time; the gold star slapped down; a ding.
"""
import numpy as np

import harvest as K
import jingle as J
import music as M
import sonic as S

SR = M.SR
rng = np.random.default_rng(5)


def kazoo(midi, gate, vel=1.0):
    """A kazoo: a hummed tone buzzing a membrane, nasal and bright."""
    n = int((gate + 0.05) * SR)
    t = J.times(n)
    f = float(J.hz(midi)) * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * t) * np.clip(t / 0.15, 0, 1))
    x = J.saw(f, n)
    x = J.formant(x, 700, 200) + 0.8 * J.formant(x, 1700, 300) + 0.4 * J.formant(x, 3100, 500)
    x = np.tanh(3 * x) * (1 + 0.25 * J.butter(J.noise(n), 'band', [2000, 6000]))
    return x * np.clip(t / 0.02, 0, 1) * np.clip((gate + 0.05 - t) / 0.05, 0, 1) * vel * 0.35


def glock(midi, vel=1.0):
    return J.bell(midi + 24, 1.6, vel) * 0.7


def classroom(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    talk = J.butter(J.noise(n), 'band', [400, 2200])
    syll = J.butter(np.abs(J.noise(n)), 'low', 9) * 4
    return talk * (0.3 + syll) * np.clip(t / 0.4, 0, 1) * vel * 0.25


def pat(vel=1.0):
    """A small hand pressed flat on paper on the table."""
    n = int(0.25 * SR)
    t = J.times(n)
    thump = np.sin(2 * np.pi * np.cumsum(120 + 80 * np.exp(-t / 0.01)) / SR) * np.exp(-t / 0.05)
    paper = J.butter(J.noise(n), 'band', [800, 5000]) * np.exp(-t / 0.03)
    return (0.8 * thump + 0.5 * paper) * vel


def slap(vel=1.0):
    """A sticker slapped down: a flat smack."""
    n = int(0.3 * SR)
    t = J.times(n)
    smack = J.butter(J.noise(n), 'band', [500, 6000]) * np.exp(-t / 0.012)
    body = np.sin(2 * np.pi * np.cumsum(180 + 120 * np.exp(-t / 0.01)) / SR) * np.exp(-t / 0.05)
    return np.tanh(2 * (smack + 0.7 * body)) * vel * 0.8


def cue(voice):
    P = M.hits('hand-turkey')
    length, end = P.DURATION, P.IRIS_CLOSE[1]
    desk = S.Desk(length)
    desk.wide(lambda: classroom(P.GOBBLE[0]), 0.0, 0.25, hall=0.3)
    desk.add(M.creak(0.35, 0.5), 1.9, 0.08, 0.8, hall=0.3)                 # a chair, somewhere
    tune = ((0.5, 72), (0.75, 76), (1.0, 79), (1.5, 76), (1.75, 74), (2.0, 72), (2.5, 74), (2.75, 76))
    for when, note in tune:                                              # the classroom's glockenspiel
        desk.add(glock(note, 0.5), when, 0.1, 0.3, hall=0.4)
    for when, note in ((0.5, 48), (1.5, 43), (2.5, 48)):
        desk.add(J.marimba(note, 0.8), when, 0.18, -0.2, hall=0.3)
    desk.add(pat(1.0), P.HAND_IN[1] - 0.04, 0.4, 0.0, hall=0.15)
    # the trace: round the thumb, then a finger a note
    desk.add(K.crayon(P.THUMB - P.TRACE, 0.9, seed=1, rate=3.0), P.TRACE, 0.35, -0.2, hall=0.1)
    prev = P.THUMB
    for k, (when, note) in enumerate(zip(P.FINGERS, M.OPEN)):
        desk.add(K.crayon(when - prev, 1.0, seed=10 + k, rate=6.0 + 2 * k), prev, 0.35, -0.1 + 0.1 * k, hall=0.1)
        desk.add(glock(note, 0.9), when, 0.3, 0.2, hall=0.4)
        desk.add(J.marimba(note, 1.0), when, 0.3, -0.2, hall=0.3)
        desk.add(J.marimba(note - 12, 0.8), when, 0.2, 0.0, hall=0.3)
        prev = when
    desk.add(K.crayon(P.TRACE_END - prev, 0.8, seed=20, rate=5.0), prev, 0.3, 0.2, hall=0.1)
    desk.add(K.rustle(P.HAND_OUT[1] - P.HAND_OUT[0] + 0.1, 0.6, seed=3), P.HAND_OUT[0], 0.18, 0.0, hall=0.15)
    # colouring in, the face, alive
    for k, (when, note) in enumerate(zip(P.COLOUR, (72, 76, 79, 84))):
        desk.add(K.crayon(0.16, 1.0, seed=30 + k, rate=18.0), when - 0.1, 0.3, -0.3 + 0.2 * k, hall=0.1)
        desk.add(J.marimba(note, 0.8), when, 0.22, -0.3 + 0.2 * k, hall=0.3)
    desk.add(K.crayon(0.2, 1.0, seed=40, rate=16.0), P.BODY - 0.12, 0.3, 0.0, hall=0.1)
    desk.add(M.boing(0.6, 0.9), P.FACE, 0.3, -0.3, hall=0.2)
    desk.add(M.pop(0.9), P.FACE + 0.05, 0.25, -0.35, hall=0.2)
    desk.add(J.bell(96, 0.6, 0.5), P.ALIVE + 0.1, 0.08, -0.3, hall=0.3)
    for when in P.HOPS:
        desk.add(M.boing(0.35, 0.8), when, 0.2, 0.0, hall=0.2)
        desk.add(pat(0.6), when + 0.3, 0.25, 0.1, hall=0.15)
        desk.add(K.putt(0.6, 1.3), when + 0.32, 0.18, 0.1, hall=0.2)
    gob = P.GOBBLE[1] - P.GOBBLE[0]
    desk.add(K.gobble(gob, 1.0, 1.25), P.GOBBLE[0], 0.45, -0.1, hall=0.25)
    for k, note in enumerate((79, 78, 77, 76, 75, 74, 73, 72)):             # and a kazoo gobbling along
        desk.add(kazoo(note, gob / 8 * 0.8, 0.8), P.GOBBLE[0] + k * gob / 8, 0.2, 0.2, hall=0.2)
    # the closed logo: the wordmark scribbled a letter at a time
    step = (P.LOGO[3] - P.LOGO[0]) / 10
    for i in range(11):
        desk.add(K.crayon(0.13, 0.8, seed=50 + i, rate=20.0), P.LOGO[0] + i * step - 0.03, 0.18, -0.6 + 0.12 * i,
                 hall=0.1)
    for k, (when, note) in enumerate(zip(P.LOGO, M.CLOSED)):
        gate = M.RHYTHM[k][1] * M.BEAT * 0.9
        desk.add(glock(note, 1.0), when, 0.3, 0.2, hall=0.4)
        desk.add(J.marimba(note, 1.0), when, 0.3, -0.2, hall=0.3)
        desk.add(J.marimba(note - 24, 0.9), when, 0.25, 0.0, hall=0.3)
        desk.add(kazoo(note - 12, gate, 0.9), when, 0.22, 0.1, hall=0.2)
    S.logo(desk, P.LOGO[0], M.CLOSED, organ_=False, choir=False, gain=0.5)
    desk.add(slap(1.0), P.STICKER, 0.4, 0.4, hall=0.15)
    desk.add(J.bell(98, 1.2, 0.7), P.STICKER + 0.06, 0.12, 0.5, hall=0.4)
    for i, note in enumerate((86, 90, 93, 98)):
        desk.add(M.glass(note, 1.0, 0.5), P.STICKER + 0.1 + i * 0.05, 0.06, 0.2 + 0.1 * i, hall=0.5)
    desk.add(J.bell(91, 0.5, 0.4), P.BLINK[0], 0.06, -0.2, hall=0.3)
    return M.mixdown(desk, voice, length, end, grit=0.5)
