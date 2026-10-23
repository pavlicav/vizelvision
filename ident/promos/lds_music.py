"""Have You Heard?'s sound (lds.py): a sunny Saturday. Strummed guitar and a shaker, birds, the
bikes' freewheels ticking; the two bike bells ring the open logo's first notes (C, E), the
doorbell's chime the other two (G... A). The door, then an earnest little pop bed under "Hi! Have
you heard about channel nineteen?", a pamphlet's rustle; the living room's TV murmur, the couch
springs as the elders squeeze on; and the closed logo as a tabernacle-sized swell: a big choir and
the full organ, bells, held under "We'll come back Tuesday!"
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
rng = np.random.default_rng(1830)


def bike_bell(midi, vel=1.0):
    """A thumb-flicked bike bell: a bright, inharmonic ring struck a few times fast (brrring)."""
    n = int(1.2 * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    tone = sum(g * np.sin(2 * np.pi * f * r * t + rng.random() * 6) * np.exp(-t / d)
               for r, g, d in ((1.0, 1.0, 0.5), (2.32, 0.5, 0.3), (4.1, 0.3, 0.15), (6.3, 0.15, 0.08)))
    strikes = np.zeros(n)
    for k in range(4):                                   # the hammer chatters against the dome
        at = int(k * 0.035 * SR)
        strikes[at:] += 0.7 ** k
    trem = 1 + 0.25 * np.sin(2 * np.pi * 28 * t) * np.exp(-t / 0.15)
    click = J.butter(J.noise(n), 'high', 4000) * np.exp(-t / 0.004)
    return (tone * trem * np.clip(strikes / 2.2, 0, 1) + 0.3 * click) * vel * 0.5


def freewheel(length, rate=14.0, vel=1.0):
    """A coasting bike's freewheel: a dry ticking, slowing as it stops."""
    n = int(length * SR)
    out = np.zeros(n)
    t, k = 0.0, 0
    while t < length - 0.02:
        m = int(0.012 * SR)
        at = int(t * SR)
        tt = J.times(m)
        out[at:at + m] += J.butter(J.noise(m), 'band', [2500, 7000]) * np.exp(-tt / 0.002) * (0.8 + 0.2 * rng.random())
        r = rate * max(0.25, 1 - t / length)
        t += 1 / r
        k += 1
    return out * vel * 0.4


def tires(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [120, 600]) * np.clip(1 - t / length, 0, 1) ** 0.6 * vel * 0.35


def springs(vel=1.0):
    """Couch springs: a few detuned boings under a cushion's thump."""
    n = int(0.6 * SR)
    t = J.times(n)
    thump = np.sin(2 * np.pi * np.cumsum(70 + 40 * np.exp(-t / 0.03)) / SR) * np.exp(-t / 0.08)
    boing = sum(np.sin(2 * np.pi * np.cumsum(f * (1 + 0.15 * np.exp(-t / 0.05) * np.sin(2 * np.pi * 9 * t))) / SR)
                * np.exp(-t / 0.18) * 0.25 for f in (240, 310, 385))
    return (thump + boing) * vel * 0.6


def rustle(length=0.3, vel=1.0):
    """A pamphlet coming out of a shirt pocket: paper, quick."""
    n = int(length * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [1800, 7000]) * np.sin(np.pi * t / length) * (0.6 + 0.4 * (rng.random(n) < 0.3)) \
        * vel * 0.5


def tv_murmur(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    talk = J.butter(J.noise(n), 'band', [400, 2200])
    syllables = J.butter(np.abs(J.noise(n)), 'low', 7) * 4
    return talk * (0.3 + syllables) * np.clip(t / 0.2, 0, 1) * vel * 0.18


def cue(voice):
    P = M.hits('lds')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    # the street: guitar, shaker, birds, the bikes coasting up
    birds = np.random.default_rng(3)
    for k in range(5):
        desk.add(M.chirp(birds), 0.15 + k * 0.33 + birds.uniform(0, 0.1), 0.05, birds.uniform(-0.8, 0.8), hall=0.2)
    for at, chord in ((0.0, (48, 55, 60, 64, 67)), (0.5, (48, 55, 60, 64, 67)), (1.0, (53, 57, 60, 65, 69))):
        for i, note in enumerate(chord):
            desk.add(M.pluck(note, 1.0, 0.65, bright=0.7), at + 0.05 + i * 0.022, 0.2, -0.3 + 0.12 * i, hall=0.25)
    for k in range(8):
        desk.add(M.shaker(0.8 if k % 2 == 0 else 0.5), 0.25 * k, 0.3, 0.35, hall=0.1)
    desk.add(tires(P.RIDE[1]), 0.0, 0.5, -0.2, hall=0.05)
    desk.add(freewheel(P.RIDE[1] - 0.5), 0.5, 0.45, 0.1, hall=0.05)
    # the open logo: bike bells (C, E), then the doorbell (G... A)
    notes = M.at_logo(P.BELLS[0])
    for when, note, pan in zip(notes[:2], M.OPEN[:2], (-0.35, 0.35)):
        desk.add(bike_bell(note, 1.0), when, 0.55, pan, hall=0.3)
    desk.add(M.click(0.8), P.PRESS, 0.3, 0.4, hall=0.1)
    for when, note in zip(notes[2:], M.OPEN[2:]):
        desk.add(M.chime(note, 2.0, 1.0), when, 0.5, 0.1, hall=0.6)
        desk.add(M.chime(note - 12, 1.6, 0.6), when, 0.25, -0.1, hall=0.6)
    # the door, the doorway: an earnest little pop bed
    desk.add(M.creak(0.4), P.DOOR_OPEN[0], 0.3, -0.2, hall=0.3)
    beat = 0.5
    chords = ((48, 55, 60, 64), (45, 52, 57, 60), (41, 53, 57, 60), (43, 55, 59, 62))
    for k in range(int((P.ROOM_CUT - P.INSIDE_CUT) / beat) + 1):
        at = P.INSIDE_CUT + k * beat
        chord = chords[(k // 2) % 4]
        if k % 2 == 0:
            desk.add(M.sub(chord[0] - 12, 0.45, 0.8), at, 0.3, 0.0, hall=0.05)
        for i, note in enumerate(chord[1:]):
            desk.add(M.pluck(note + 12, 0.45, 0.5, bright=0.6), at + 0.02 * i, 0.14, -0.25 + 0.25 * i, hall=0.25)
        desk.add(M.shaker(0.5), at + 0.25, 0.22, 0.4, hall=0.1)
    for k, note in enumerate((72, 76, 79, 76, 84)):                  # a glockenspiel under the line
        desk.add(M.vibes(note, 1.0, 0.5), P.HI + 0.15 + k * 0.5, 0.12, 0.3, hall=0.4)
    desk.add(rustle(0.35), P.PAMPHLET[0], 0.4, 0.4, hall=0.15)
    # the living room: the TV, the springs as they squeeze on
    desk.add(tv_murmur(P.CLOSED - P.ROOM_CUT), P.ROOM_CUT, 0.4, 0.0, hall=0.2)
    for k, at in enumerate((P.SQUEEZE[0] + 0.55, P.SQUEEZE[0] + 0.75, P.SQUEEZE[1] - 0.15)):
        desk.add(springs(0.9 - 0.15 * k), at, 0.35, -0.5 + 0.5 * k, hall=0.2)
    for at, chord in ((P.ROOM_CUT, (60, 64, 67, 72)), (P.ROOM_CUT + 0.8, (57, 60, 64, 69)), (6.15, (53, 57, 60, 65)),
                      (6.55, (55, 59, 62, 67))):
        for note in chord:                                            # the organ creeping in
            desk.add(M.pipe_organ(note, 0.75, 0.55), at, 0.07 + 0.04 * (at > 6), -0.2 + 0.1 * (note % 5), hall=0.6)
    for note in (62, 66, 69):                                         # the choir's breath before
        desk.add(J.choir(note, 0.6, 0.4), 6.4, 0.12, -0.3 + 0.3 * (note % 3), hall=0.6)
    desk.add(J.timpani(38, 0.7), 6.6, 0.25, hall=0.5)
    # the closed logo: the full choir and organ, the bells
    S.logo(desk, P.CLOSED, M.CLOSED, organ_=False, choir=True, gain=1.0)
    for when, note in zip(M.at_logo(P.CLOSED), M.CLOSED):
        desk.add(M.church_bell(note - 12, 2.6, 0.8), when, 0.22, 0.3, hall=0.7)
        desk.add(M.pipe_organ(note, 0.45, 0.9), when, 0.12, -0.2, hall=0.6)
    for note in (26, 38, 50, 57, 62, 66, 69, 74):
        desk.add(M.pipe_organ(note, 2.0, 0.95), P.CLOSED, 0.1, -0.35 + 0.1 * (note % 8), hall=0.8)
    for k, note in enumerate((62, 66, 69, 74, 78, 81)):
        desk.add(J.choir(note, 2.2, 0.85), P.CLOSED + 0.02 * k, 0.24, -0.5 + 0.2 * k, hall=0.7)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74, 78), 2.2, 0.4, 1.0), P.CLOSED, 0.08, hall=0.6)
    desk.add(J.crash(0.7, 2.4), P.CLOSED, 0.2, 0.3, hall=0.6)
    desk.add(J.timpani(38, 1.0), P.CLOSED, 0.4, hall=0.5)
    return M.mixdown(desk, voice, length, end, grit=0.6)
