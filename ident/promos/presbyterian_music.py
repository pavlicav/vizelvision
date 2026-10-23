"""Decently and in Order's sound. The parlour: the clock, the room, and through the window the
piper's drones; on the open logo the chanter plays it outside (a G gracenote before each note)
while the elders say aye, a card's swish a note; the gavel; a murmur of approval and the marker's
tick. The minutes: a page, a low organ waiting, and on PREDESTINED the stamp's thump with a
dark organ chord, timpani and a choir's ah. The tartan: the pipes strike in, the drums' roll-off,
and the closed logo on chanter, drones and organ together with the station's bells, a bass drum
on the first and last notes; the chord held under "Decently, and in order", the drones dying off.
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
P = M.hits('presbyterian')
LOW_A, HIGH_G, HIGH_A = 69, 79, 81


def reed(freq, n, bright=1.0, formants=((1150, 520, 1.0), (2600, 800, 0.7))):
    """A reed pipe by harmonics: a nasal, buzzy spectrum shaped by two resonances, the
    harmonics fading out below Nyquist. freq is per sample (a glide or a tune)."""
    freq = np.broadcast_to(np.asarray(freq, float), (n,))
    phase = 2 * np.pi * np.cumsum(freq) / SR
    x = np.zeros(n)
    for k in range(1, 28):
        fk = freq * k
        weight = (0.25 + sum(g * np.exp(-((fk - fc) / bw) ** 2) for fc, bw, g in formants)) / k ** (0.55 / bright)
        weight *= np.clip((13000 - fk) / 3000, 0, 1)
        x += weight * np.sin(k * phase + 0.7 * k)
    return x / 3.0


def drones(length, strike=0.4, die=0.0):
    """The three drones (a bass on A2, two tenors on A3 a hair apart): struck in with the
    bag's growl up to pitch, steady, and if die, sagging off at the end."""
    n = int(length * SR)
    t = J.times(n)
    bend = 1 - 0.18 * np.exp(-t / (strike * 0.35))
    sag = 1.0
    amp = np.clip(t / strike, 0, 1) ** 0.6
    if die:
        d = np.clip((t - (length - die)) / die, 0, 1)
        sag = 1 - 0.22 * d ** 1.5
        amp *= np.clip(1 - d, 0, 1) ** 0.8
    out = reed(110 * bend * sag, n, 1.3, ((450, 300, 0.8), (1300, 600, 0.5))) * 0.8
    for cents in (0, 3.5):
        out += reed(220 * float(J.cents(cents)) * bend * sag, n, 1.1, ((900, 400, 0.6), (2000, 700, 0.4))) * 0.45
    return out * amp * (1 + 0.02 * np.sin(2 * np.pi * 0.7 * t))


def chanter(tune, length, grace=0.032):
    """The chanter's tune, legato as the pipes are: (time, midi) pairs, each note with a
    gracenote just before it (a high G, or a high A over the high notes)."""
    n = int(length * SR)
    t = J.times(n)
    f = np.full(n, float(J.hz(tune[0][1])))
    for k, (at, note) in enumerate(tune):
        f[t >= at] = float(J.hz(note))
        if k:
            g = HIGH_A + 3 if note >= HIGH_G else HIGH_G
            f[(t >= at - grace) & (t < at)] = float(J.hz(g))
    f = J.butter(f, 'low', 400)                                      # the fingers aren't instant
    amp = np.clip(t / 0.05, 0, 1)
    return reed(f, n, 1.0) * amp + 0.05 * J.butter(J.noise(n), 'band', [2500, 6000]) * amp


def tick(vel=1.0):
    n = int(0.05 * SR)
    t = J.times(n)
    return (np.sin(2 * np.pi * 2300 * t) * np.exp(-t / 0.004) + J.butter(J.noise(n), 'high', 4000)
            * np.exp(-t / 0.002) * 0.4) * vel


def swish(vel=1.0):
    """A card going up."""
    n = int(0.16 * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [1500, 6000]) * np.sin(np.pi * t / 0.16) ** 2 * vel * 0.4


def page(vel=1.0):
    """An old page turned."""
    n = int(0.45 * SR)
    t = J.times(n)
    crackle = J.butter(J.noise(n), 'band', [800, 7000]) * (0.5 + 0.5 * np.sin(2 * np.pi * 23 * t) ** 8)
    return crackle * np.sin(np.pi * t / 0.45) ** 1.5 * vel * 0.5


def thump(vel=1.0):
    """A rubber stamp, hard on a book on oak."""
    n = int(0.35 * SR)
    t = J.times(n)
    body = np.sin(2 * np.pi * np.cumsum(70 + 90 * np.exp(-t / 0.02)) / SR) * np.exp(-t / 0.09)
    slap = J.butter(J.noise(n), 'band', [600, 3500]) * np.exp(-t / 0.012) * 0.6
    return np.tanh(1.5 * (body + slap)) * vel


def murmur(length, vel=1.0):
    """Five people in a parlour, agreeing quietly."""
    n = int(length * SR)
    t = J.times(n)
    x = J.butter(J.noise(n), 'band', [250, 1800]) * (0.6 + 0.4 * np.sin(2 * np.pi * 3.1 * t) * np.sin(2 * np.pi * 1.3 * t))
    return x * np.sin(np.pi * np.clip(t / length, 0, 1)) * vel * 0.3


def cue(voice):
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    # The parlour: the room, the clock, and through the window the drones.
    desk.add(J.butter(J.noise(int(P.CUT * SR)), 'low', 300) * 0.08, 0.0, 1.0, hall=0.05)
    for k in range(int(P.CUT / 0.5)):
        desk.add(tick(0.6 if k % 2 else 0.85), 0.25 + k * 0.5, 0.12, 0.45, hall=0.1)
    window = J.butter(drones(P.CUT + 0.3, strike=0.6), 'low', 1600)
    window *= np.clip((P.CUT + 0.3 - J.times(len(window))) / 0.3, 0, 1)
    desk.add(window, 0.0, 0.16, -0.55, hall=0.2)
    # The open logo: the chanter plays it outside, a high G before each note.
    tune = [(0.0, LOW_A)] + [(at - 1.05, note) for at, note in zip(P.CARDS, M.OPEN)] + [(3.0 - 1.05, LOW_A)]
    pipes = J.butter(chanter(tune, 2.4), 'low', 2400) * np.clip((2.4 - J.times(int(2.4 * SR))) / 0.15, 0, 1)
    desk.add(pipes, 1.05, 0.2, -0.5, hall=0.25)
    for at in P.CARDS:                                               # the cards go up
        desk.add(swish(), at - 0.1, 0.35, 0.1, hall=0.1)
    desk.add(M.gavel(1.0), P.GAVEL, 0.6, -0.05, hall=0.25)
    desk.add(murmur(0.9), P.GAVEL + 0.25, 0.5, 0.0, hall=0.2)
    desk.add(M.scribble(0.25), P.TICK[0], 0.25, 0.55, hall=0.1)
    desk.add(M.teacup(0.6), P.GAVEL + 0.04, 0.35, 0.2, hall=0.15)   # the cups jump
    # The minutes: a page, the organ waiting low, then PREDESTINED.
    desk.add(page(), P.CUT - 0.05, 0.5, 0.2, hall=0.2)
    for note in (38, 45, 50):
        desk.add(M.pipe_organ(note, P.STAMP - P.CUT - 0.1, 0.5), P.CUT + 0.05, 0.06, hall=0.6)
    desk.add(thump(1.0), P.STAMP, 0.7, 0.1, hall=0.3)
    for note in (26, 38, 50, 53, 57, 62):
        desk.add(M.pipe_organ(note, 0.95, 0.95), P.STAMP, 0.11, -0.2 + 0.08 * (note % 5), hall=0.8)
    desk.add(J.timpani(38, 1.0), P.STAMP, 0.4, hall=0.4)
    for note in (62, 65, 69):
        desk.add(J.choir(note, 0.8, 0.8), P.STAMP + 0.02, 0.18, -0.3 + 0.3 * (note % 3), hall=0.7)
    # The tartan: the pipes strike in, the drums roll off into the closed logo.
    desk.add(J.whoosh(P.WIPE[1] - P.WIPE[0]), P.WIPE[0], 0.12, 0.3, hall=0.3)
    strike_at, die_at = P.WIPE[0] + 0.05, 9.05
    desk.wide(lambda: drones(die_at + 0.4 - strike_at, strike=0.35, die=0.4), strike_at, 0.26, spread=0.4, hall=0.35)
    roll_start = P.WIPE[0] + 0.1
    for k in range(int((P.CLOSED - roll_start) / 0.04)):              # the roll-off
        at = roll_start + k * 0.04
        desk.add(J.snare(0.25 + 0.6 * (at - roll_start) / (P.CLOSED - roll_start)), at, 0.18, 0.15, hall=0.25)
    finale = [(P.WIPE[0] + 0.1 - strike_at, 76)] + [(at - strike_at, note) for at, note in
                                                     zip(M.at_logo(P.CLOSED), M.CLOSED)]
    desk.add(chanter(finale, die_at - strike_at) * np.clip((die_at - strike_at - J.times(int((die_at - strike_at) * SR)))
                                                          / 0.12, 0, 1), strike_at, 0.3, 0.1, hall=0.35)
    for at in (P.CLOSED, M.at_logo(P.CLOSED)[3]):
        desk.add(J.kick(0.9), at, 0.4, hall=0.3)
        desk.add(J.snare(0.9), at, 0.25, 0.15, hall=0.3)
    S.logo(desk, P.CLOSED, M.CLOSED, organ_=False, choir=False, gain=0.55)
    for when, note in zip(M.at_logo(P.CLOSED), M.CLOSED):
        desk.add(M.church_bell(note - 12, 2.5, 0.8), when, 0.22, 0.3, hall=0.6)
    for note in (38, 50, 57, 62, 66, 69, 74):                         # the organ, full, held under the motto
        desk.add(M.pipe_organ(note, die_at - P.CLOSED, 0.85), P.CLOSED, 0.09, -0.3 + 0.1 * (note % 7), hall=0.7)
    return M.mixdown(desk, voice, length, end, grit=0.5)
