"""VizelVision Church's sound: worship pop at the big church. The countdown loop's pad and an
electric guitar's eighths through a dotted-eighth delay (that guitar), toms climbing to 00:00;
the open logo is four kicks with the CO2 hissing on each and the crowd's woo; then four on
the floor under the pastor (C G Am F, as worship songs go); a snare build; and the closed
logo up a whole step, as worship songs also go: D, the choir, the distorted guitars, the
jets again, a confetti pop and the room roaring, under "Come on, church!"
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
OPEN, CLOSED = M.OPEN, M.CLOSED
rng = np.random.default_rng(36)


def delayed(desk, sound, at, gain, pan, hall=0.3):
    """The worship guitar's dotted-eighth delay: the note, then two repeats a dotted eighth apart."""
    for k, (lag, g) in enumerate(((0.0, 1.0), (0.375, 0.42), (0.75, 0.18))):
        desk.add(sound, at + lag, gain * g, pan * (1 if k % 2 == 0 else -1), hall=hall + 0.1 * k)


def dist_chord(notes, length, vel=1.0):
    """A distorted electric guitar chord: detuned saws through a fuzz, a cab's low-pass."""
    n = int(length * SR)
    x = np.zeros(n)
    for m in notes:
        for c in (-7, 6):
            x += J.saw(float(J.hz(m)) * float(J.cents(c)), n)
    x = np.tanh(2.8 * J.butter(x, 'low', 3200) / len(notes))
    t = J.times(n)
    return x * np.clip(t / 0.01, 0, 1) * np.clip((length - t) / 0.15, 0, 1) * vel * 0.35


def co2(vel=1.0, length=0.8):
    """A CO2 jet: a hard hiss, opening and dying."""
    n = int(length * SR)
    t = J.times(n)
    x = J.butter(J.noise(n), 'high', 1700) + 0.4 * J.butter(J.noise(n), 'band', [400, 1200])
    return x * np.clip(t / 0.01, 0, 1) * np.exp(-t / 0.22) * vel * 0.5


def woo(length=1.4, seed=0):
    """A few people in the crowd going woo: voices gliding up and falling off."""
    n = int(length * SR)
    x = np.zeros(n)
    r = np.random.default_rng(seed)
    for _ in range(5):
        f0 = r.uniform(380, 620)
        start = r.uniform(0, 0.25)
        part = M.glide(f0, f0 * r.uniform(1.4, 1.8), r.uniform(0.6, 0.9), 0.6)
        part = J.formant(part, 900, 300) + 0.4 * part
        s = int(start * SR)
        x[s:s + len(part)] += part[:n - s]
    return x * 0.6


def cue(voice):
    P = M.hits('non-denom')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)

    # The countdown loop: the pad, the delayed guitar, the toms climbing to 00:00.
    desk.wide(lambda: J.pad_voice((48, 60, 64, 67, 74), P.HITS[0] - 0.05, 0.6, 0.4), 0.0, 0.15, hall=0.6)
    figure = (79, 76, 74, 76, 79, 76, 72, 76)
    for k in range(int(P.HITS[0] / 0.25)):
        delayed(desk, M.pluck(figure[k % 8], 0.8, 0.8, bright=0.85), k * 0.25, 0.21, 0.35)
    for k in range(8):
        when = 0.5 + k * 0.125
        desk.add(J.tom((43, 45, 47, 48)[k // 2], 0.35 + 0.08 * k), when, 0.3, -0.3 + 0.08 * k, hall=0.3)
    desk.add(J.riser(1.0, 6000), P.HITS[0] - 1.0, 0.25, hall=0.3)

    # The open logo: four kicks, the jets, the crowd's woo, the band in on the downbeat.
    S.logo(desk, P.HITS[0], OPEN, organ_=False, gain=0.8)
    for k, when in enumerate(P.HITS):
        desk.add(J.kick(1.0), when, 0.9)
        desk.add(M.kick808(0.9, 0.7), when, 0.5)
        desk.add(co2(0.9 if k < 2 else 1.1), when + 0.01, 0.35, (-0.6, 0.6, 0.0, 0.0)[k], hall=0.25)
        desk.add(dist_chord((48, 55, 60, 64), 0.22 if k < 3 else 0.45, 0.9), when, 0.35, -0.3, hall=0.2)
        desk.add(dist_chord((48, 55, 60, 67), 0.22 if k < 3 else 0.45, 0.9), when, 0.35, 0.3, hall=0.2)
    desk.add(J.crash(1.0, 2.2), P.HITS[0], 0.35, 0.3, hall=0.3)
    desk.add(J.crash(0.9, 2.0), P.HITS[3], 0.3, -0.3, hall=0.3)
    desk.add(woo(1.6, 1), P.HITS[0] + 0.1, 0.25, 0.2, hall=0.5)
    desk.add(J.butter(S.crowd(2.2, swell=(0.0, 0.25)), 'band', [300, 3000]), P.HITS[0], 0.2, hall=0.4)

    # Under the pastor: four on the floor, C G Am F, the pad, the guitar's delay.
    chords = (((48, 60, 64, 67), 36), ((43, 59, 62, 67), 31), ((45, 57, 60, 64), 33), ((41, 57, 60, 65), 29))
    start = P.HITS[3] + 0.5
    for bar in range(4):
        at = start + bar * 1.0
        if at >= P.BUILD[0]:
            break
        notes, root = chords[bar % 4]
        gate = min(1.0, P.BUILD[0] - at)
        desk.wide(lambda nn=notes, g=gate: J.pad_voice(nn, g, 0.15, 0.6), at, 0.08, hall=0.5)
        desk.add(J.bass(root, gate * 0.95, 0.8), at, 0.4)
        for k in range(4):
            when = at + k * 0.25
            if when >= P.BUILD[0]:
                break
            delayed(desk, M.pluck(notes[1 + k % 3] + 12, 0.7, 0.7, bright=0.85), when, 0.1, 0.4)
    beat = start
    while beat < P.BUILD[0] + 0.5:
        desk.add(J.kick(0.75), beat, 0.55)
        desk.add(J.hat(0.35), beat + 0.25, 0.25, 0.3, hall=0.1)
        beat += 0.5
    desk.add(J.pad_voice((41, 57, 60, 65), P.CLOSED - P.BUILD[0], 0.3, 0.3), P.BUILD[0], 0.08, hall=0.5)

    # The build: a snare roll, eighths then sixteenths, louder all the way; a riser.
    t = P.BUILD[0]
    while t < P.CLOSED - 0.02:
        k = (t - P.BUILD[0]) / (P.CLOSED - P.BUILD[0])
        desk.add(J.snare(0.3 + 0.7 * k), t, 0.35, 0.1, hall=0.15, room=0.4)
        t += 0.25 if k < 0.5 else 0.125
    desk.add(J.riser(P.CLOSED - P.BUILD[0], 8000), P.BUILD[0], 0.3, hall=0.3)

    # The closed logo, up a whole step: D A Bm G under it, the choir, the guitars, the jets, the roar.
    S.logo(desk, P.CLOSED, CLOSED, organ_=False, choir=True, gain=1.0)
    desk.add(J.crash(1.0, 2.6), P.CLOSED, 0.4, 0.3, hall=0.35)
    desk.add(J.crash(0.9, 2.6), P.CLOSED, 0.3, -0.3, hall=0.35)
    desk.add(M.kick808(1.0, 1.2), P.CLOSED, 0.6)
    desk.add(M.pop(1.0), P.CLOSED + 0.02, 0.3, 0.2, hall=0.3)               # the confetti cannon
    for when in P.JETS_CLOSED:
        desk.add(co2(1.2, 1.0), when + 0.01, 0.35, 0.0, hall=0.3)
    finale = (((50, 57, 62, 66), 38, 1.0), ((45, 57, 61, 64), 33, 0.5), ((47, 59, 62, 66), 35, 0.5),
              ((43, 55, 59, 62), 31, P.FADE[1] - P.CLOSED - 2.0))
    at = P.CLOSED
    for notes, root, gate in finale:
        desk.add(dist_chord(notes, gate, 1.0), at, 0.3, -0.35, hall=0.3)
        desk.add(dist_chord([n + 7 for n in notes[:2]] + list(notes[2:]), gate, 1.0), at, 0.25, 0.35, hall=0.3)
        desk.wide(lambda nn=notes, g=gate: J.pad_voice(tuple(n + 12 for n in nn), g, 0.05, 0.8), at, 0.09, hall=0.5)
        desk.add(J.bass(root, gate * 0.95, 0.9), at, 0.45)
        at += gate
    for note in (74, 78, 81):
        desk.add(J.choir(note, 2.0, 0.8), P.CLOSED + 0.5, 0.18, -0.3 + 0.3 * (note % 3), hall=0.6)
    beat = P.CLOSED
    while beat < P.FADE[0]:
        desk.add(J.kick(0.85), beat, 0.55)
        desk.add(J.hat(0.4, open_=True), beat + 0.25, 0.2, 0.3, hall=0.1)
        if int(round((beat - P.CLOSED) / 0.5)) % 2:
            desk.add(J.snare(0.8), beat, 0.3, 0.1, hall=0.2, room=0.5)
        beat += 0.5
    desk.add(J.butter(S.crowd(length - P.CLOSED, swell=(0.0, 0.5)), 'band', [300, 3500]), P.CLOSED, 0.3, hall=0.4)
    desk.add(woo(1.8, 2), P.CLOSED + 0.1, 0.3, -0.2, hall=0.5)
    desk.add(woo(1.4, 3), 8.9, 0.22, 0.3, hall=0.5)
    return M.mixdown(desk, voice, length, end, grit=0.5)
