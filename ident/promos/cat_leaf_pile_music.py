"""The Leaf Pile's sound (cat_leaf_pile.py): the documentary's sneaking pizzicato on a gold
afternoon, a breeze in the maple and leaves ticking down; the open logo on vibes and pizzicato
as each leaf lands on the pile with a crisp rustle; the wiggle's shaker, a slide whistle for the
pounce and the whole pile going up; leaves pattering back; the turkey's footsteps in the grass
and its putt; a boing and a mrrp as the head pops out; the turkey's strut (a puff and a drum)
and the closed logo on vibes, bells and choir with a gust swirling the leaves; a purr.
"""
import numpy as np

import harvest as K
import jingle as J
import music as M
import sonic as S

SR = M.SR


def breeze(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    gust = 0.6 + 0.4 * np.sin(2 * np.pi * 0.27 * t + 0.5) * np.sin(2 * np.pi * 0.13 * t)
    return J.butter(J.noise(n), 'band', [300, 1600]) * gust * np.clip(t / 0.5, 0, 1) * vel * 0.4


def strut(vel=1.0):
    """A strutting tom's 'pfft... dummm': a puff of air and a low drum from the chest."""
    n = int(1.0 * SR)
    t = J.times(n)
    puff = J.butter(J.noise(n), 'band', [600, 3000]) * np.exp(-t / 0.04)
    hum = np.sin(2 * np.pi * np.cumsum(70 - 12 * t) / SR) * np.clip((t - 0.12) / 0.08, 0, 1) * np.exp(-np.clip(t - 0.12, 0, None) / 0.35)
    return (0.6 * puff + 0.9 * hum) * vel


def cue(voice):
    P = M.hits('cat-leaf-pile')
    length, end = P.DURATION, P.IRIS_CLOSE[1]
    desk = S.Desk(length)
    desk.wide(lambda: breeze(length - 0.3), 0.0, 0.35, hall=0.2)
    desk.wide(lambda: J.pad_voice((48, 55, 60, 64), 2.6, 1.0, 1.0), 0.0, 0.05, hall=0.4)
    M.tiptoe(desk, 0.3, P.LEAVES[0] - 0.25, notes=(48, 55, 52, 55))
    for k in range(9):                                               # leaves ticking down here and there
        desk.add(K.crunch(0.08, 0.35, seed=40 + k), 0.6 + k * 0.71, 0.12, -0.8 + 0.2 * k, hall=0.2)
    # the open logo: a leaf lands on the pile on each note
    for k, (when, note) in enumerate(zip(P.LEAVES, M.OPEN)):
        desk.add(M.vibes(note, 1.6, 0.8), when, 0.28, 0.1 + 0.08 * k, hall=0.35)
        desk.add(M.pizz(note - 12, 0.9), when, 0.32, -0.1, hall=0.25)
        desk.add(K.crunch(0.14, 0.9, seed=k), when, 0.3, 0.2 + 0.08 * k, hall=0.15)
        desk.add(M.glide(1400 - 80 * k, 900 - 60 * k, 0.5), when - 0.55, 0.04, 0.2, hall=0.3)
    for k in range(4):                                               # the wiggle
        desk.add(M.shaker(1.0), P.WIGGLE[0] + k * (P.WIGGLE[1] - P.WIGGLE[0]) / 4, 0.5, 0.3 * (-1) ** k)
    desk.add(J.timpani(43, 0.5), P.WIGGLE[0], 0.2, hall=0.3)
    # the pounce, and the pile going up
    desk.add(M.glide(380, 1600, P.POUNCE[1] - P.POUNCE[0]), P.POUNCE[0], 0.35, 0.2, hall=0.2)
    desk.add(K.leaf_burst(1.0), P.BURST, 0.6, 0.25, hall=0.25)
    desk.add(J.kick(0.6), P.BURST, 0.4)
    desk.add(J.crash(0.5, 1.4), P.BURST, 0.1, 0.4, hall=0.2)
    for k in range(12):                                              # leaves pattering back down
        desk.add(K.crunch(0.07, 0.5, seed=60 + k), P.BURST + 0.45 + k * 0.1, 0.13, -0.5 + 0.1 * k, hall=0.2)
    desk.add(K.rustle(P.SETTLE[1] - P.SETTLE[0], 0.7), P.SETTLE[0] + 0.2, 0.2, 0.2, hall=0.2)
    # only the tail: the sneaking walk, sheepish
    M.tiptoe(desk, P.TAIL[0], P.TAIL[1] - 0.05, notes=(48, 47, 46, 45), gain=0.25)
    # the turkey: footsteps in the grass, a putt
    for k in range(P.TURKEY_STEPS):
        when = P.TURKEY_WALK[0] + (k + 0.5) * (P.TURKEY_WALK[1] - P.TURKEY_WALK[0]) / P.TURKEY_STEPS
        desk.add(K.crunch(0.12, 0.6, seed=80 + k), when, 0.22, 0.85, hall=0.15)
    desk.add(K.putt(0.8, 1.0), P.TURKEY_WALK[0] + 0.5, 0.25, 0.8, hall=0.2)
    desk.add(M.boing(0.5, 0.7), P.POP_OUT, 0.22, 0.2, hall=0.2)
    desk.add(M.meow(), P.POP_OUT + 0.3, 0.4, 0.15, hall=0.15)
    desk.add(K.putt(0.9, 1.1), P.PUTT, 0.32, 0.7, hall=0.2)
    desk.add(K.putt(0.7, 1.15), P.PUTT + 0.14, 0.25, 0.7, hall=0.2)
    # the closed logo: the strut, a gust, the wordmark
    desk.add(strut(1.0), P.FAN[0] - 0.12, 0.45, 0.7, hall=0.25)
    desk.wide(lambda: K.rustle(1.6, 1.0, seed=7), P.LOGO[0] - 0.1, 0.25, hall=0.25)
    desk.add(J.whoosh(0.8), P.LOGO[0] - 0.2, 0.15, -0.2, hall=0.3)
    S.logo(desk, P.LOGO[0], M.CLOSED, organ_=False, choir=True, gain=0.85)
    for when, note in zip(P.LOGO, M.CLOSED):
        desk.add(M.vibes(note, 2.0, 0.8), when, 0.25, -0.2, hall=0.35)
        desk.add(M.pizz(note - 24, 1.0, 0.9), when, 0.3, 0.1, hall=0.25)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 1.9, 0.3, 1.0), P.LOGO[0], 0.07, hall=0.4)
    desk.add(M.purr(1.2, 0.9), P.BLINK[0] - 0.2, 0.35, 0.0, hall=0.1)
    for i, note in enumerate((74, 78, 81, 86, 90, 93)):
        desk.add(J.bell(note, 1.4, 0.5), P.BLINK[0] + i * 0.05, 0.06, -0.4 + 0.15 * i, hall=0.5)
    return M.mixdown(desk, voice, length, end, grit=0.5)
