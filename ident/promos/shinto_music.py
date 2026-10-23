"""VizelVision Jinja's sound: gagaku colour from the station's kit. Up the path: evening
cicadas (higurashi, kana-kana), gravel underfoot, a crow, the sho's reed cluster breathing in
and a hichiriki line sliding up into its notes, the kakko's roll into the shrine. The open
logo is the worshipper: the coin (C), the bell (E), clap (G), clap (A), each with a koto note
and a small bell; on the second clap the taiko and the sho swell as the TV wakes. The
omikuji: paper unrolling, then 大吉 is a festival: taiko, the atarigane's chiki-chiki and a
shinobue flourish. The ema rack: wind chimes, the plaques knocking, the koto. Dusk: the
cicadas again, the sho in D, and the closed logo on koto and temple bell as the lanterns
light, the station's bells under it, the sho's D major cluster to close.
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
rng = np.random.default_rng(39)


def sho(midis, length, vel=1.0, attack=0.6):
    """The sho: seventeen bamboo pipes with free reeds, a bright sustained cluster that
    breathes (it sounds on the in-breath and the out-breath alike)."""
    n = int(length * SR)
    t = J.times(n)
    x = np.zeros(n)
    for m in midis:
        f = float(J.hz(m))
        for c in (-3.0, 2.5):
            x += J.pulse(f * J.cents(c), n, 0.42) * 0.5
    x = J.butter(x, 'low', 5200) + 0.35 * J.formant(x, 2600, 3)
    breath = 0.85 + 0.15 * np.sin(2 * np.pi * 0.7 * t + 1.0)
    env = np.clip(t / attack, 0, 1) ** 1.5 * np.clip((length - t) / 0.45, 0, 1) * breath
    air = J.butter(J.noise(n), 'band', [3000, 8000]) * 0.04
    return (x / np.sqrt(len(midis) * 2) + air) * env * vel * 0.5


def hichiriki(notes, length, vel=1.0):
    """The hichiriki, a loud double reed: each note starts below and slides up into place
    (embai), a nasal tone, a slow swell on each note."""
    n = int(length * SR)
    t = J.times(n)
    f = np.full(n, float(J.hz(notes[0][1])))
    amp = np.zeros(n)
    for k, (at, midi) in enumerate(notes):
        end = notes[k + 1][0] if k + 1 < len(notes) else length
        seg = (t >= at) & (t < end)
        u = t[seg] - at
        f[seg] = float(J.hz(midi)) * 2 ** (-1.6 / 12 * np.exp(-u / 0.07))
        amp[seg] = np.clip(u / 0.05, 0, 1) * (0.75 + 0.25 * np.clip(u / (end - at), 0, 1))
    f *= 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t)
    x = J.saw(f, n)
    y = J.formant(x, 1150, 3.5) + 0.6 * J.formant(x, 2700, 5) + 0.15 * x
    return np.tanh(1.4 * y) * amp * np.clip((length - t) / 0.12, 0, 1) * vel * 0.45


def koto(midi, vel=1.0):
    """A koto string: a bright pluck with the plectrum's click."""
    x = M.pluck(midi, 1.8, vel, bright=0.85)
    n = int(0.03 * SR)
    x[:n] += J.butter(J.noise(n), 'band', [2000, 6000]) * np.exp(-J.times(n) / 0.004) * 0.3 * vel
    return x


def kakko(vel=1.0):
    """The kakko, a small two-headed drum struck with sticks: dry and high."""
    x = M.membrane(430, 0.035, bend=0.12)
    n = len(x)
    x += J.butter(J.noise(n), 'band', [1500, 5000]) * np.exp(-J.times(n) / 0.006) * 0.5
    return x * vel * 0.6


def taiko(vel=1.0):
    """A big drum: the low head, its bloom, the stick's slap."""
    x = M.membrane(64, 0.32, bend=0.18, overtones=((1.52, 0.3, 0.4), (2.2, 0.15, 0.25)))
    n = len(x)
    x += J.butter(J.noise(n), 'low', 400) * np.exp(-J.times(n) / 0.03) * 0.6
    return np.tanh(1.5 * x) * vel * 0.7


def suzu(length=0.45, vel=1.0, midi=100):
    """The shrine bell shaken: a cluster of small bells jingling, one partial on the note."""
    n = int(length * SR)
    t = J.times(n)
    x = np.zeros(n)
    for k in range(34):
        at = int(rng.uniform(0, length * 0.7) * SR)
        f = rng.uniform(3200, 7200)
        m = n - at
        tt = J.times(m)
        x[at:] += np.sin(2 * np.pi * f * tt + rng.random() * 6) * np.exp(-tt / rng.uniform(0.03, 0.08)) * rng.uniform(0.3, 1)
    x += 0.8 * np.sin(2 * np.pi * float(J.hz(midi)) * t) * np.exp(-t / 0.5)
    return x * vel * 0.25


def coin_clink(vel=1.0, midi=96):
    """A five-yen coin into the offering box: a bright clink tuned to the note, a second
    smaller one off the slats, and the wooden box."""
    n = int(0.6 * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = np.zeros(n)
    for ratio, gain, dec in ((1.0, 1.0, 0.25), (2.76, 0.45, 0.06), (5.4, 0.25, 0.03)):
        x += gain * np.sin(2 * np.pi * f * ratio * t) * np.exp(-t / dec)
    k = int(0.07 * SR)
    x[k:] += 0.4 * np.sin(2 * np.pi * f * 1.5 * t[:n - k]) * np.exp(-t[:n - k] / 0.04)
    k2 = int(0.11 * SR)
    box = M.click(0.8)[:n - k2]
    x[k2:k2 + len(box)] += box
    return x * vel * 0.35


def higurashi(length, vel=1.0, top=4900):
    """An evening cicada: kana-kana-kana, a pulsing call falling in pitch and fading."""
    n = int(length * SR)
    t = J.times(n)
    f = top - 600 * t / length
    am = (0.5 + 0.5 * np.sin(2 * np.pi * 9.5 * t)) ** 3
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(4 * np.pi * np.cumsum(f) / SR)
    env = np.clip(t / 0.25, 0, 1) * np.exp(-t / (length * 0.6))
    return x * am * env * vel * 0.12


def crow(vel=1.0):
    n = int(0.3 * SR)
    t = J.times(n)
    f = 640 - 140 * t / 0.3
    x = J.saw(f, n)
    y = J.formant(x, 1300, 3) + 0.7 * J.formant(x, 2400, 4)
    return np.tanh(2 * y) * np.sin(np.pi * t / 0.3) ** 0.6 * vel * 0.2


def gravel(vel=1.0):
    n = int(0.16 * SR)
    x = np.zeros(n)
    for k in range(14):
        at = int(rng.uniform(0, 0.11) * SR)
        m = int(0.012 * SR)
        x[at:at + m] += J.noise(m)[:len(x[at:at + m])] * rng.uniform(0.3, 1)
    return J.butter(x, 'band', [900, 5000]) * vel * 0.35


def paper(length, vel=1.0):
    n = int(length * SR)
    x = J.butter(J.noise(n), 'high', 2500)
    gate = (rng.random(n // 300 + 1) < 0.45).repeat(300)[:n] * rng.uniform(0.3, 1, n // 300 + 1).repeat(300)[:n]
    return x * gate * vel * 0.12


def atarigane(vel=1.0):
    """The festival's small hand gong: a hard metallic chik."""
    n = int(0.25 * SR)
    t = J.times(n)
    x = sum(g * np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, g, d in ((1530, 1.0, 0.05), (2410, 0.6, 0.03),
                                                                             (3720, 0.4, 0.02), (5100, 0.2, 0.015)))
    return x * vel * 0.25


def shinobue(notes, length, vel=1.0):
    """A bamboo festival flute: a breathy high line with flips between notes."""
    n = int(length * SR)
    t = J.times(n)
    f = np.full(n, float(J.hz(notes[0][1])))
    amp = np.zeros(n)
    for k, (at, midi) in enumerate(notes):
        end = notes[k + 1][0] if k + 1 < len(notes) else length
        seg = (t >= at) & (t < end)
        f[seg] = float(J.hz(midi))
        amp[seg] = np.clip((t[seg] - at) / 0.02, 0, 1)
    f *= 1 + 0.006 * np.sin(2 * np.pi * 6 * t) * np.clip((t - 0.15) / 0.3, 0, 1)
    phase = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(phase) + 0.12 * np.sin(2 * phase) + J.butter(J.noise(n), 'band', [2500, 7000]) * 0.08
    return x * amp * np.clip((length - t) / 0.1, 0, 1) * vel * 0.3


def cue(voice):
    P = M.hits('shinto')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)

    # Up the path, in the late afternoon.
    for at, top, pan in ((0.0, 4900, -0.6), (0.7, 4600, 0.5)):
        desk.add(higurashi(2.6, 1.0, top), at, 0.5, pan, hall=0.4)
    desk.add(crow(), 0.35, 0.25, 0.7, hall=0.6)
    desk.add(crow(0.8), 0.62, 0.2, 0.75, hall=0.6)
    for k, at in enumerate(P.FOOTSTEPS):
        desk.add(gravel(0.9), at, 0.4, -0.15 if k % 2 else 0.15, hall=0.1)
    desk.add(sho((64, 69, 71, 76, 81), 1.6, 0.9, attack=0.5), 0.0, 0.32, -0.2, hall=0.5)
    desk.add(hichiriki(((0.0, 69), (0.42, 71), (0.84, 76)), 1.3, 0.8), 0.25, 0.22, 0.25, hall=0.5)
    for k in range(10):                                              # the kakko rolls us into the shrine
        when = P.SHRINE_IN[0] - 0.1 + 0.35 * (1 - (1 - k / 10) ** 1.8)
        desk.add(kakko(0.4 + 0.06 * k), when, 0.35, 0.2, hall=0.3)

    # The open logo: coin, bell, clap, clap.
    when = M.at_logo(P.LOGO)
    desk.add(coin_clink(1.0, 96), P.COIN, 1.0, 0.0, hall=0.35)
    desk.add(suzu(0.5, 1.0, 100), P.BELL, 1.1, 0.35, hall=0.4)
    for k, at in enumerate(P.CLAPS):
        desk.add(J.clap(1.0), at, 1.15, 0.0, hall=0.7)
        desk.add(kakko(0.8), at, 0.3, -0.2, hall=0.3)
    for at, note in zip(when, M.OPEN):
        desk.add(koto(note - 12, 0.9), at, 0.5, -0.25, hall=0.4)
        desk.add(J.bell(note + 12, 1.4, 0.5), at, 0.15, 0.3, hall=0.5)
    desk.add(taiko(1.0), P.KAMI, 0.45, 0.0, hall=0.5)                 # the TV wakes
    desk.add(sho((69, 71, 76, 78, 81, 83), 1.6, 1.0, attack=0.25), P.KAMI, 0.3, 0.15, hall=0.6)
    for k in range(12):                                              # a shimmer of chimes as it lights
        desk.add(M.glass(88 + (0, 2, 4, 7, 9)[k % 5] + 12 * (k // 5), 1.0, 0.5), P.KAMI + 0.08 + k * 0.045,
                 0.05, -0.5 + k * 0.08, hall=0.6)
    desk.add(taiko(0.6), P.BOW[0] + 0.1, 0.3, 0.0, hall=0.6)          # the bow

    # The omikuji: paper, then the festival.
    desk.add(paper(P.UNROLL[1] - P.UNROLL[0] + 0.1, 1.0), P.UNROLL[0], 0.5, 0.0, hall=0.2)
    desk.add(J.riser(P.DAIKICHI - P.UNROLL[0], 6000), P.UNROLL[0], 0.08, 0.0, hall=0.3)
    beat = 0.25
    pattern = (1, 0, 1, 0, 1, 1, 0, 1)                               # don . don . don don . don
    for k in range(8):
        at = P.DAIKICHI + k * beat * 0.5
        if pattern[k]:
            desk.add(taiko(1.0 if k == 0 else 0.75), at, 0.55, 0.0, hall=0.35)
        desk.add(atarigane(0.9 if k % 2 == 0 else 0.6), at, 0.35, 0.4, hall=0.25)
    for k in range(4):
        desk.add(atarigane(0.5), P.DAIKICHI + 1.0 + k * 0.125, 0.25, 0.4, hall=0.25)
    flute = ((0.0, 88), (0.08, 91), (0.16, 93), (0.32, 96), (0.5, 93), (0.58, 91), (0.66, 88), (0.82, 91))
    desk.add(shinobue(flute, 1.05, 1.0), P.DAIKICHI + 0.02, 0.35, -0.3, hall=0.45)
    desk.add(J.crash(0.6, 1.4), P.DAIKICHI, 0.12, 0.3, hall=0.4)

    # The ema rack: wind chimes, the plaques knocking, a koto line.
    for k in range(7):
        desk.add(M.glass(91 + (0, 3, 5, 7, 10)[k % 5], 1.2, 0.45), P.EMA_IN[0] + 0.1 + k * 0.15 + 0.03 * (k % 3),
                 0.05, 0.6 - 0.2 * k, hall=0.5)
    for k in range(5):
        desk.add(M.click(0.6), P.PAN[0] + 0.25 + k * 0.21, 0.2, -0.3 + 0.15 * k, hall=0.2)
    for k, note in enumerate((64, 67, 69, 72, 74, 76)):
        desk.add(koto(note, 0.7), P.EMA_IN[0] + 0.2 + k * 0.16, 0.22, -0.2 + 0.08 * k, hall=0.4)

    # Dusk: cicadas, the sho in D, the closed logo on koto and temple bell, lanterns lighting.
    desk.add(higurashi(3.0, 0.8, 4700), P.DUSK_IN[0], 0.4, -0.5, hall=0.5)
    desk.add(higurashi(2.4, 0.6, 4400), P.DUSK_IN[0] + 0.9, 0.3, 0.6, hall=0.5)
    desk.add(sho((62, 64, 69, 71, 76), P.CLOSED - P.DUSK_IN[0] + 0.2, 0.9, attack=0.6), P.DUSK_IN[0], 0.36, 0.0,
             hall=0.6)
    S.logo(desk, P.CLOSED, M.CLOSED, organ_=False, choir=False, gain=0.5)
    for at, note in zip(M.at_logo(P.CLOSED), M.CLOSED):
        desk.add(koto(note - 12, 1.0), at, 0.35, -0.25, hall=0.45)
        desk.add(M.church_bell(note - 24, 2.8, 0.8), at, 0.22, 0.2, hall=0.6)
        desk.add(J.butter(J.noise(int(0.35 * SR)), 'low', 900) * np.hanning(int(0.35 * SR)), at - 0.05, 0.08, 0.0,
                 hall=0.3)                                           # the lantern catching
    desk.add(sho((74, 76, 78, 81, 83, 86), end - P.LANTERNS[-1] - 0.1, 1.0, attack=0.3), P.LANTERNS[-1], 0.3, 0.0,
             hall=0.6)
    desk.add(M.church_bell(38, 3.0, 1.0), P.LANTERNS[-1], 0.35, 0.0, hall=0.7)
    for k, note in enumerate((62, 66, 69, 74, 78)):
        desk.add(koto(note, 0.7), P.LANTERNS[-1] + 0.35 + k * 0.05, 0.2, -0.3 + 0.15 * k, hall=0.5)
    return M.mixdown(desk, voice, length, end, grit=0.5)
