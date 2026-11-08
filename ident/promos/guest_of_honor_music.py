"""Guest of Honor's sound (guest_of_honor.py): a fingerpicked guitar in C under the dinner's
murmur and the clink of serving spoons; the open logo is the four candles, a match struck and
a bell for each; the door's creak, and the guest's footsteps on the floorboards with a few
contented putts; a flutter of wings up onto the chair and the cushion's poof; its gobble; four
glasses clink. The closed logo on bells, choir and strings as the tail lights up; a last putt.
"""
import numpy as np

import harvest as K
import jingle as J
import music as M
import sonic as S

SR = M.SR


def cue(voice):
    P = M.hits('guest-of-honor')
    length, end = P.DURATION, P.IRIS_CLOSE[1]
    desk = S.Desk(length)
    # the dinner: guitar, murmur, spoons
    for chord, start, stop in (((48, 55, 60, 64), 0.0, 2.0), ((45, 52, 57, 60), 2.0, 4.0),
                               ((41, 48, 53, 57), 4.0, 6.0), ((43, 50, 55, 59), 6.0, P.LOGO[0])):
        M.fingerpick(desk, chord, start, stop, gain=0.26)
    desk.wide(lambda: J.pad_voice((48, 55, 60, 64), 1.9, 0.6, 0.6), 0.05, 0.035, hall=0.4)
    murmur = J.butter(J.noise(int(P.TOAST[1] * SR)), 'band', [250, 1300]) * \
        (0.4 + 4 * J.butter(np.abs(J.noise(int(P.TOAST[1] * SR))), 'low', 6))
    murmur *= np.clip(J.times(len(murmur)) / 0.4, 0, 1) * np.clip((P.TOAST[1] - J.times(len(murmur))) / 0.6, 0, 1)
    desk.wide(lambda: murmur * 0.25, 0.0, 0.22, hall=0.3)
    for when, pan in ((0.9, -0.5), (1.55, 0.4), (4.6, 0.6)):
        desk.add(M.teacup(0.6), when, 0.18, pan, hall=0.25)
    # the open logo: a candle a note
    for k, (when, note) in enumerate(zip(P.CANDLES, M.OPEN)):
        desk.add(K.match(0.9), when - 0.07, 0.3, -0.3 + 0.2 * k, hall=0.2)
        desk.add(J.bell(note, 2.4, 0.9), when, 0.3, -0.3 + 0.2 * k, hall=0.5)
        desk.add(M.glass(note + 12, 1.6, 0.6), when, 0.12, 0.3 - 0.2 * k, hall=0.5)
        desk.add(M.pluck(note - 12, 1.6, 1.0, 0.7), when, 0.3, 0.0, hall=0.3)
    # the door, and the guest
    desk.add(M.creak(P.DOOR[1] - P.DOOR[0] + 0.25, 1.0), P.DOOR[0], 0.4, -0.75, hall=0.3)
    for k in range(P.STEPS):
        when = P.WALK[0] + (k + 0.5) * (P.WALK[1] - P.WALK[0]) / P.STEPS
        desk.add(K.claws(0.9), when, 0.32, -0.7 + 0.12 * k, hall=0.2)
    for when, pitch in ((P.WALK[0] + 0.3, 1.0), (P.WALK[0] + 0.85, 1.08), (P.WALK[0] + 1.25, 0.95)):
        desk.add(K.putt(0.8, pitch), when, 0.3, -0.5, hall=0.25)
    desk.add(M.flutter(P.HOP[1] - P.HOP[0] + 0.15, 13.0), P.HOP[0] - 0.05, 0.4, 0.0, hall=0.25)
    desk.add(M.poof(0.8), P.HOP[1], 0.35, 0.0, hall=0.2)
    desk.add(K.putt(0.7, 1.1), P.PLATE + 0.1, 0.28, 0.0, hall=0.25)
    desk.add(K.gobble(P.GOBBLE[1] - P.GOBBLE[0] + 0.05, 1.0), P.GOBBLE[0], 0.5, 0.0, hall=0.3)
    # the toast
    for k in range(4):
        desk.add(K.rustle(0.35, 0.5, seed=k), P.TOAST[0] + 0.06 * k, 0.12, -0.8 if k % 2 else 0.8, hall=0.1)
    for k, note in enumerate((96, 100, 103, 98)):
        desk.add(M.glass(note, 1.4, 0.7), P.CLINK + 0.012 * k, 0.12, -0.6 + 0.4 * k, hall=0.5)
    desk.add(M.teacup(1.0), P.CLINK, 0.25, 0.0, hall=0.4)
    # the closed logo: the tail lights a quarter a note
    S.logo(desk, P.LOGO[0], M.CLOSED, organ_=False, choir=True, gain=0.9)
    for when, note in zip(P.LOGO, M.CLOSED):
        desk.add(M.glass(note + 12, 2.0, 0.7), when, 0.14, 0.3, hall=0.6)
        desk.add(M.pluck(note - 24, 2.0, 1.0, 0.6), when, 0.3, -0.2, hall=0.3)
    desk.wide(lambda: J.pad_voice((50, 57, 62, 66, 69), 1.8, 0.4, 0.8), P.FAN[0], 0.07, hall=0.6)
    desk.add(J.riser(P.LOGO[0] - P.FAN[0] + 0.1, 5000), P.FAN[0] - 0.1, 0.06, 0.0, hall=0.3)
    desk.add(K.putt(0.6, 1.15), P.BLINK[0] - 0.1, 0.22, 0.0, hall=0.3)
    return M.mixdown(desk, voice, length, end, grit=0.6)
