"""VizelVision Shaadi's sound (shaadi.py): a wedding, from the station's kit. The baraat: the dhol's
bhangra chaal (the dagga's boom, the tilli's crack, three-three-two), a shehnai over it, the brass
band's stabs and the crowd's hoi!; the open logo is four dhol strokes, a firework each, the shehnai
and the station's bells on C E G A, and a shower of ghungroo as the sehra parts. The mandap: a
shankh, a harmonium's drone, a santoor run under the title, a soft tabla theka, and the temple bell
and the guests' claps as the knot is tied. The auntie: tabla and a cheeky harmonium, the cousins'
feet running off, and a ting on the wink. The send-off: a dhol roll into the closed logo, D F# A D,
four fireworks with the shehnai and the bells, and the bhangra back on under "Shaadi Mubarak!"
with the crowd.
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
rng = np.random.default_rng(1919)


def dagga(vel=1.0):
    """The dhol's bass head, struck with the curved stick: a deep boom that bends down, and the slap."""
    x = M.membrane(78, 0.22, bend=0.35, overtones=((1.6, 0.35, 0.4), (2.3, 0.15, 0.25)))
    n = len(x)
    x += J.butter(J.noise(n), 'band', [150, 1200]) * np.exp(-J.times(n) / 0.012) * 0.6
    return np.tanh(1.6 * x) * vel * 0.75


def tilli(vel=1.0):
    """The treble head, cracked with the cane: high, dry, ringing a little."""
    x = M.membrane(410, 0.045, bend=0.08, overtones=((2.3, 0.4, 0.5), (3.1, 0.2, 0.3)))
    n = len(x)
    x += J.butter(J.noise(n), 'band', [1800, 7000]) * np.exp(-J.times(n) / 0.006) * 0.7
    return x * vel * 0.5


def chaal(desk, start, stop, gain=1.0, bar=1.0):
    """Bhangra's chaal on the dhol, three-three-two: boom at 0, 3/8 and 3/4 of a bar, crack between."""
    at = start
    k = 0
    while at < stop - 0.01:
        for offset, drum, vel in ((0.0, dagga, 1.0), (0.25, tilli, 0.7), (0.375, dagga, 0.75), (0.5, tilli, 0.6),
                                  (0.75, dagga, 0.85), (0.875, tilli, 0.8)):
            when = at + offset * bar
            if when < stop:
                desk.add(drum(vel), when, (0.5 if drum is dagga else 0.38) * gain, -0.1 if drum is dagga else 0.15,
                         hall=0.18)
        at += bar
        k += 1


def shehnai(notes, length, vel=1.0):
    """The shehnai: a loud, nasal double reed. Each note scoops up from below with a grace from
    above (kan), and a wide, singing vibrato blooms on held notes."""
    n = int(length * SR)
    t = J.times(n)
    f = np.full(n, float(J.hz(notes[0][1])))
    amp = np.zeros(n)
    for k, (at, midi) in enumerate(notes):
        end = notes[k + 1][0] if k + 1 < len(notes) else length
        seg = (t >= at) & (t < end)
        u = t[seg] - at
        target = float(J.hz(midi))
        grace = 2 ** (2 / 12) * np.exp(-u / 0.018) + 1 - np.exp(-u / 0.018)       # from a tone above
        scoop = 2 ** (-0.7 / 12 * np.exp(-u / 0.05))
        f[seg] = target * np.where(u < 0.03, grace, scoop)
        bloom = np.clip((u - 0.12) / 0.2, 0, 1)
        f[seg] *= 1 + 0.012 * bloom * np.sin(2 * np.pi * 6.0 * u)
        amp[seg] = np.clip(u / 0.02, 0, 1) * (0.8 + 0.2 * np.clip(u / max(end - at, 0.05), 0, 1))
    x = J.saw(f, n) + 0.3 * J.pulse(f * 1.002, n, 0.35)
    y = J.formant(x, 1150, 260) + 0.8 * J.formant(x, 2500, 420) + 0.4 * J.formant(x, 3600, 600) + 0.1 * x
    breath = J.butter(J.noise(n), 'band', [2000, 6000]) * 0.04
    return (np.tanh(2.2 * y) + breath) * amp * np.clip((length - t) / 0.08, 0, 1) * vel * 0.4


def harmonium(midis, length, vel=1.0, attack=0.05):
    """A harmonium: free reeds pumped by hand, two sets a few cents apart (it beats), the bellows' swell."""
    n = int(length * SR)
    t = J.times(n)
    x = np.zeros(n)
    for m in midis:
        f = float(J.hz(m))
        for c in (-6.0, 5.0):
            x += J.pulse(f * J.cents(c), n, 0.38)
    x = J.butter(x, 'low', 3200) + 0.3 * J.formant(x, 1400, 500)
    bellows = 0.9 + 0.1 * np.sin(2 * np.pi * 1.1 * t)
    env = np.clip(t / attack, 0, 1) * np.clip((length - t) / 0.08, 0, 1) * bellows
    return x / np.sqrt(2 * len(midis)) * env * vel * 0.35


def santoor(midi, vel=1.0):
    """A santoor string struck by its walnut hammer: bright, a quick double strike."""
    x = M.pluck(midi, 1.4, vel, bright=0.92)
    k = int(0.045 * SR)
    x[k:] += 0.45 * M.pluck(midi, 1.4, vel, bright=0.92)[:len(x) - k]
    return x


def tabla(stroke, vel=1.0):
    """A tabla: dha (both drums), dhin, tin, na/ta (the dayan's rim, ringing on its note), ge (the
    bayan, bending up)."""
    def dayan(ring):
        n = int(0.6 * SR)
        t = J.times(n)
        f = float(J.hz(72))
        x = sum(g * np.sin(2 * np.pi * f * h * t) * np.exp(-t / (ring * d)) for h, g, d in
                ((1, 1.0, 1.0), (2, 0.5, 0.7), (3, 0.3, 0.5), (4, 0.15, 0.35)))
        x += J.butter(J.noise(n), 'band', [2500, 7000]) * np.exp(-t / 0.004) * 0.4
        return x

    def bayan():
        n = int(0.5 * SR)
        t = J.times(n)
        f = 82 * (1 + 0.5 * (1 - np.exp(-t / 0.06)))
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.16)

    if stroke in ('na', 'ta'):
        x = dayan(0.22)
    elif stroke == 'tin':
        x = dayan(0.12) * 0.8
    elif stroke == 'ge':
        x = bayan()
    elif stroke == 'dhin':
        x = dayan(0.25) * 0.8
        x[:len(bayan())] += bayan() * 0.9
    else:                                                            # dha
        x = dayan(0.2)
        x[:len(bayan())] += bayan()
    return x * vel * 0.35


def theka(desk, start, stop, gain=1.0, step=0.125, bols=('dha', 'dhin', 'dhin', 'dha', 'dha', 'dhin', 'dhin', 'dha',
                                                           'dha', 'tin', 'tin', 'ta', 'ta', 'dhin', 'dhin', 'dha')):
    k = 0
    at = start
    while at < stop - 0.01:
        desk.add(tabla(bols[k % len(bols)], 1.0 if k % 4 == 0 else 0.7), at, 0.4 * gain, 0.2, hall=0.2)
        at += step
        k += 1


def bang(vel=1.0):
    """A firework: the shell's thump and crack, then the stars crackling as they fall."""
    n = int(1.4 * SR)
    t = J.times(n)
    thump = np.sin(2 * np.pi * np.cumsum(55 + 60 * np.exp(-t / 0.03)) / SR) * np.exp(-t / 0.18)
    crack = J.butter(J.noise(n), 'band', [300, 5000]) * np.exp(-t / 0.05)
    x = 0.9 * thump + 0.8 * crack
    for _ in range(60):                                              # the crackle
        at = int(rng.uniform(0.18, 1.2) * SR)
        m = int(0.006 * SR)
        x[at:at + m] += J.butter(J.noise(m), 'high', 2500)[:len(x[at:at + m])] * rng.uniform(0.1, 0.4)
    return np.tanh(1.4 * x) * vel * 0.5


def whistle_up(length=0.35, vel=1.0):
    """A rocket going up: a thin whistle rising."""
    n = int(length * SR)
    t = J.times(n)
    f = 1600 + 1800 * t / length
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.clip(t / 0.05, 0, 1) * (1 - t / length) * vel * 0.15


def ghungroo(length=0.6, vel=1.0):
    """Anklet bells shaken: a dense, bright jingle."""
    n = int(length * SR)
    x = np.zeros(n)
    for _ in range(50):
        at = int(rng.uniform(0, length * 0.75) * SR)
        m = n - at
        tt = J.times(m)
        f = rng.uniform(4200, 8500)
        x[at:] += np.sin(2 * np.pi * f * tt + rng.random() * 6) * np.exp(-tt / rng.uniform(0.02, 0.06)) * rng.uniform(0.3, 1)
    return x * vel * 0.2


def shankh(length=1.2, vel=1.0):
    """The conch, blown to begin: a hollow horn tone with breath, rising at the end."""
    n = int(length * SR)
    t = J.times(n)
    f = float(J.hz(57)) * (1 + 0.04 * np.clip((t - length * 0.6) / (length * 0.4), 0, 1)) \
        * (1 + 0.004 * np.sin(2 * np.pi * 5 * t))
    x = J.saw(f, n)
    y = J.formant(x, 700, 200) + 0.6 * J.formant(x, 1250, 260) + 0.25 * J.butter(x, 'low', 500)
    breath = J.butter(J.noise(n), 'band', [800, 3000]) * 0.2
    env = np.clip(t / 0.25, 0, 1) ** 1.5 * np.clip((length - t) / 0.2, 0, 1)
    return np.tanh(1.8 * (y + breath)) * env * vel * 0.35


def temple_bell(midi=88, vel=1.0):
    """The ghanti: a small brass hand bell, rung a few times."""
    out = np.zeros(int(1.6 * SR))
    for k in range(3):
        b = J.bell(midi, 1.2, 0.9 - 0.2 * k)
        at = int(k * 0.11 * SR)
        out[at:at + len(b)] += b[:len(out) - at]
    return out * vel * 0.4


def steps(length, rate=9.0, vel=1.0):
    """Small feet running on a hall floor."""
    n = int(length * SR)
    out = np.zeros(n)
    at = 0.0
    while at < length - 0.03:
        m = int(0.03 * SR)
        k = int(at * SR)
        out[k:k + m] += J.butter(J.noise(m), 'band', [400, 2500])[:len(out[k:k + m])] * np.exp(-J.times(m) / 0.008)
        at += 1 / rate * rng.uniform(0.9, 1.1)
    return out * vel * 0.35


def cue(voice):
    P = M.hits('shaadi')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)

    # The baraat: the chaal, the shehnai, the band, the crowd.
    chaal(desk, P.GROOVE[0], P.LOGO, 1.0)
    desk.add(S.crowd(P.MANDAP_IN[1], swell=(1.2, 2.8), claps=[P.GROOVE[0] + 0.5 * k for k in range(4)]), 0.0, 0.35,
             0.0, hall=0.4)
    tune = ((0.0, 76), (0.2, 79), (0.4, 81), (0.6, 79), (0.75, 76), (0.95, 74), (1.15, 76), (1.35, 72))
    desk.add(shehnai(tune, 1.6, 0.85), 0.1, 0.3, 0.25, hall=0.35)
    for at in (0.0, 1.0):                                            # the brass band's stabs
        for note in (60, 64, 67):
            desk.wide(lambda n=note: J.brass(n, 0.22, 0.8), at, 0.08, 0.3, hall=0.25)
    for at in (0.6, 1.25):                                           # a couple of rockets go up
        desk.add(whistle_up(0.4), at, 0.25, -0.4 + 0.6 * (at > 1), hall=0.4)

    # The open logo: four dhol strokes, a firework each, the shehnai and the bells.
    when = M.at_logo(P.LOGO)
    for k, (at, note) in enumerate(zip(when, M.OPEN)):
        desk.add(dagga(1.0), at, 0.75, 0.0, hall=0.3)
        desk.add(tilli(1.0), at + 0.01, 0.4, 0.2, hall=0.2)
        desk.add(bang(1.0 if k == 3 else 0.8), at, 0.45, (-0.5, 0.3, -0.2, 0.4)[k], hall=0.6)
    gates = (0.24, 0.24, 0.48, 0.9)
    desk.add(shehnai([(at - P.LOGO, note) for at, note in zip(when, M.OPEN)], when[-1] - P.LOGO + gates[-1], 1.0),
             P.LOGO, 0.32, 0.2, hall=0.4)
    S.logo(desk, P.LOGO, M.OPEN, organ_=False, gain=0.5)
    desk.add(ghungroo(0.7, 1.0), P.SEHRA[0], 0.35, 0.3, hall=0.4)   # the sehra parts
    for k in range(9):
        desk.add(M.glass(84 + (0, 4, 7, 9, 12, 16, 19, 21, 24)[k], 1.0, 0.5), P.SEHRA[0] + 0.05 + k * 0.03, 0.05,
                 -0.4 + k * 0.1, hall=0.6)
    desk.add(S.crowd(1.0, swell=(0.0, 0.25)), P.DHOL[3], 0.3, 0.0, hall=0.5)

    # The mandap: the conch, the drone, the santoor, the theka, the bell and the claps.
    desk.add(shankh(1.1), P.MANDAP_IN[0], 0.4, -0.1, hall=0.7)
    desk.add(harmonium((48, 55, 60), P.AUNTIE_IN[0] - P.MANDAP_IN[0] + 0.15, 0.8, attack=0.3), P.MANDAP_IN[0], 0.28,
             0.0, hall=0.5)
    for k, note in enumerate((72, 74, 76, 79, 81, 84, 86, 88)):
        desk.add(santoor(note, 0.8), P.TITLE[0] + k * 0.055, 0.22, -0.4 + 0.1 * k, hall=0.5)
    theka(desk, P.TITLE[0] + 0.25, P.AUNTIE_IN[0], 0.7)
    desk.add(temple_bell(88, 1.0), P.KNOT[1], 0.45, 0.35, hall=0.6)
    for k in range(9):
        desk.add(M.glass(91 + (0, 2, 4, 7, 9)[k % 5] + 12 * (k // 5), 1.0, 0.5), P.KNOT[1] + 0.04 + k * 0.04, 0.05,
                 0.4 - k * 0.08, hall=0.6)
    desk.add(S.crowd(0.9, claps=[0.05 + 0.13 * k for k in range(6)]), P.KNOT[1] + 0.1, 0.3, 0.0, hall=0.5)

    # The auntie: tabla, a cheeky harmonium, the cousins' feet, a ting on the wink.
    theka(desk, P.AUNTIE_IN[0], P.FINALE_IN[0], 0.8, step=0.125,
          bols=('dha', 'ge', 'na', 'dha', 'tin', 'na', 'ge', 'na'))
    for k, (at, chord) in enumerate(((0.0, (53, 57, 60)), (0.5, (55, 59, 62)), (1.0, (53, 57, 60)))):
        desk.add(harmonium(chord, 0.16, 0.8, attack=0.01), P.AUNTIE_IN[0] + 0.1 + at, 0.22, -0.2, hall=0.3)
        desk.add(harmonium(chord, 0.12, 0.6, attack=0.01), P.AUNTIE_IN[0] + 0.35 + at, 0.16, -0.2, hall=0.3)
    desk.add(steps(P.RANSOM[1] - P.RANSOM[0], 9.0), P.RANSOM[0], 0.4, 0.5, hall=0.2)
    desk.add(M.glass(96, 1.0, 0.8), P.WINK, 0.14, 0.0, hall=0.5)

    # The send-off: a dhol roll into the closed logo; four fireworks, the shehnai, the bells; the
    # bhangra back on in D, the crowd, two more fireworks.
    for k in range(14):
        at = P.FINALE_IN[0] + 0.55 * (1 - (1 - k / 14) ** 1.6)
        desk.add((dagga if k % 2 else tilli)(0.35 + 0.045 * k), at, 0.45, 0.0, hall=0.25)
    desk.add(J.riser(P.CLOSED - P.FINALE_IN[0], 5000), P.FINALE_IN[0], 0.06, 0.0, hall=0.3)
    when = M.at_logo(P.CLOSED)
    for k, at in enumerate(when):
        desk.add(dagga(1.0), at, 0.75, 0.0, hall=0.3)
        desk.add(tilli(1.0), at + 0.01, 0.4, 0.2, hall=0.2)
        desk.add(whistle_up(0.25, 0.7), at - 0.25, 0.15, (-0.5, 0.5, -0.2, 0.2)[k], hall=0.4)
        desk.add(bang(1.0 if k == 3 else 0.8), at, 0.45, (-0.5, 0.5, -0.2, 0.2)[k], hall=0.6)
    desk.add(shehnai([(at - P.CLOSED, note) for at, note in zip(when, M.CLOSED)], when[-1] - P.CLOSED + 0.9, 1.0),
             P.CLOSED, 0.32, 0.2, hall=0.4)
    S.logo(desk, P.CLOSED, M.CLOSED, organ_=False, gain=0.6)
    desk.add(harmonium((50, 57, 62, 66), end - when[-1], 0.9, attack=0.1), when[-1], 0.22, -0.1, hall=0.5)
    chaal(desk, when[-1] + 0.5, end, 0.85)
    desk.add(S.crowd(end - P.CLOSED, swell=(0.0, 1.1), claps=[1.5 + 0.5 * k for k in range(4)]), P.CLOSED, 0.3,
             0.0, hall=0.5)
    flourish = ((0.0, 86), (0.12, 88), (0.24, 90), (0.36, 93), (0.6, 90), (0.72, 88), (0.84, 86))
    desk.add(shehnai(flourish, 1.1, 0.8), when[-1] + 0.55, 0.22, 0.25, hall=0.45)
    for at in P.AFTER:
        desk.add(bang(0.6), at, 0.3, 0.6 if at == P.AFTER[0] else -0.6, hall=0.6)
    return M.mixdown(desk, voice, length, end, grit=0.5)
