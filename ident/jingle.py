"""Synthesize the VizelVision jingle and mix DJ Low Tide's lines over it.

Everything is made here from oscillators and noise: brass stabs, a DX-style
e-piano, FM bells, an orchestra hit, a formant "aah" choir and a drum machine
with gated-reverb snare. The four-note logo ("Viz-el-Vi-sion") is heard at the
first hit and again, up a step, at the button.

    python jingle.py OUT.wav              (needs numpy and scipy)
    python jingle.py --no-voice OUT.wav   the music alone, at the same level: the bed a
                                          continuity announcement is mixed over
"""
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy import ndimage, signal
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import timeline as T  # noqa: E402

SR = T.SAMPLE_RATE
N = int(T.DURATION * SR)
rng = np.random.default_rng(1990)


# ---------------------------------------------------------------- building blocks

def hz(midi):
    return 440.0 * 2 ** ((np.asarray(midi, float) - 69) / 12)


def cents(c):
    return 2 ** (c / 1200)


def times(n):
    return np.arange(n) / SR


def osc_phase(freq, n):
    step = np.broadcast_to(np.asarray(freq, float), (n,)) / SR
    return (np.cumsum(step) + rng.random()) % 1.0, step


def _blep(p, dt):
    y = np.zeros_like(p)
    m = p < dt
    t = p[m] / dt[m]
    y[m] = t + t - t * t - 1
    m = p > 1 - dt
    t = (p[m] - 1) / dt[m]
    y[m] = t * t + t + t + 1
    return y


def saw(freq, n):
    p, dt = osc_phase(freq, n)
    return 2 * p - 1 - _blep(p, dt)


def pulse(freq, n, width=0.5):
    p, dt = osc_phase(freq, n)
    return np.where(p < width, 1.0, -1.0) + _blep(p, dt) - _blep((p + 1 - width) % 1, dt)


def noise(n):
    return rng.standard_normal(n)


def adsr(gate, a, d, s, r, n):
    """Attack/decay/sustain while the gate is held, then an exponential release."""
    t = times(n)
    env = np.where(t < a, t / max(a, 1e-4), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-4)))
    held = t >= gate
    if held.any():
        start = env[max(0, int(gate * SR) - 1)]
        env[held] = start * np.exp(-(t[held] - gate) / max(r / 5, 1e-4))
    return env


def decay(n, tau, attack=0.002):
    t = times(n)
    env = np.exp(-t / tau)
    k = int(attack * SR)
    if k:
        env[:k] *= np.linspace(0, 1, k)
    return env


def butter(x, kind, freq, order=2):
    freq = np.clip(freq, 20, SR * 0.45)
    return signal.sosfilt(signal.butter(order, freq, kind, fs=SR, output='sos'), x)


def _biquad(kind, fc, q):
    w = 2 * np.pi * min(max(fc, 20), SR * 0.45) / SR
    c, alpha = np.cos(w), np.sin(w) / (2 * q)
    if kind == 'lp':
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    else:  # band-pass, 0 dB peak
        b = [alpha, 0, -alpha]
    a0 = 1 + alpha
    return np.array([[b[0] / a0, b[1] / a0, b[2] / a0, 1, -2 * c / a0, (1 - alpha) / a0]])


def sweep(x, fc, kind='lp', q=0.707, block=64):
    """A filter whose cutoff follows fc (one value per sample), for envelopes and risers."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    y, zi = np.empty_like(x), np.zeros((1, 2))
    for i in range(0, len(x), block):
        y[i:i + block], zi = signal.sosfilt(_biquad(kind, fc[i], q), x[i:i + block], zi=zi)
    return y


def formant(x, fc, bw):
    return signal.sosfilt(_biquad('bp', fc, fc / bw), x)


# ---------------------------------------------------------------- instruments

def brass(midi, gate, vel=1.0, attack=0.018):
    r = 0.14
    n = int((gate + r) * SR)
    t = times(n)
    scoop = 1 - 0.02 * np.exp(-t / 0.04)
    vibrato = 1 + 0.003 * np.sin(2 * np.pi * 5.4 * t) * np.clip((t - 0.3) / 0.3, 0, 1)
    f = hz(midi) * scoop * vibrato
    x = (saw(f * cents(-9), n) + saw(f, n) + saw(f * cents(9), n)) / 3
    brightness = adsr(gate, attack * 1.8, 0.2, 0.35, r, n)
    y = sweep(x, 500 + 5500 * vel * brightness + hz(midi) * 1.5, q=1.1)
    return y * adsr(gate, attack, 0.25, 0.72, r, n) * vel


def epiano(midi, gate, vel=0.7):
    n = int((gate + 0.35) * SR)
    t = times(n)
    f = float(hz(midi))
    phase = 2 * np.pi * f * t + rng.random() * 6
    index = 1.9 * vel * np.exp(-t / 0.3) + 0.25
    y = np.sin(phase + index * np.sin(phase))
    if f * 14 < 16000:
        y += 0.2 * vel * np.sin(14 * phase) * np.exp(-t / 0.02)
    return y * np.exp(-t / 1.4) * adsr(gate, 0.003, 1, 1, 0.35, n) * vel


def bell(midi, length=2.4, vel=1.0):
    n = int(length * SR)
    t = times(n)
    phase = 2 * np.pi * float(hz(midi)) * t
    index = 3.2 * np.exp(-t / 0.22) + 0.5
    y = np.sin(phase + index * np.sin(3.5 * phase)) * np.exp(-t / 1.1)
    y += 0.3 * np.sin(2 * phase) * np.exp(-t / 0.45)
    return y * decay(n, 1e9, 0.003) * vel


def marimba(midi, vel=1.0):
    n = int(0.7 * SR)
    t = times(n)
    phase = 2 * np.pi * float(hz(midi)) * t
    y = np.sin(phase + 1.6 * np.exp(-t / 0.012) * np.sin(4 * phase)) * np.exp(-t / 0.2)
    y += 0.25 * np.sin(3.93 * phase) * np.exp(-t / 0.04)
    return y * decay(n, 1e9, 0.001) * vel


def pad_voice(midis, gate, attack=0.5, release=1.2):
    n = int((gate + release) * SR)
    x = np.zeros(n)
    for m in midis:
        for c in (-16, -6, 0, 7, 15):
            x += saw(hz(m) * cents(c), n)
    y = butter(x, 'low', 2400) / np.sqrt(len(midis) * 5)
    return y * adsr(gate, attack, 1, 1, release, n)


AH = ((730, 80, 1.0), (1090, 90, 0.5), (2440, 120, 0.28), (3300, 160, 0.12))


def choir(midi, gate, vel=1.0):
    r = 0.4
    n = int((gate + r) * SR)
    t = times(n)
    x = np.zeros(n)
    for c in (-8, 0, 8):
        wobble = 1 + 0.0045 * np.sin(2 * np.pi * rng.uniform(4.8, 5.6) * t + rng.random() * 6) \
            * np.clip((t - 0.12) / 0.3, 0, 1)
        x += saw(hz(midi) * cents(c) * wobble, n)
    y = sum(g * formant(x, fc, bw) for fc, bw, g in AH)
    return y * adsr(gate, 0.07, 0.3, 0.85, r, n) * vel


def bass(midi, gate, vel=1.0):
    r = 0.05
    n = int((gate + r) * SR)
    t = times(n)
    f = float(hz(midi))
    x = 0.6 * saw(f, n) + 0.45 * pulse(f, n, 0.35) + 0.6 * np.sin(2 * np.pi * f * t)
    y = sweep(x, 170 + 2400 * vel * np.exp(-t / 0.07), q=1.4)
    return np.tanh(1.6 * y * adsr(gate, 0.004, 0.16, 0.7, r, n)) * 0.8 * vel


def orch_hit(root, detune_seed=0.0):
    n = int(1.6 * SR)
    t = times(n)
    x = np.zeros(n)
    for interval in (-24, -12, -5, 0, 4, 7, 12, 16, 19):
        x += saw(hz(root + interval) * cents(rng.uniform(-14, 14) + detune_seed), n)
        x += 0.4 * pulse(hz(root + interval) * cents(rng.uniform(-10, 10)), n, 0.3)
    x = x / 9 + 0.7 * noise(n) * np.exp(-t / 0.04)
    y = sweep(x, 250 + 9500 * np.exp(-t / 0.11), q=0.9)
    y *= decay(n, 0.2, 0.002) + 0.08 * decay(n, 0.9, 0.002)
    thump = np.sin(2 * np.pi * np.cumsum(42 + 95 * np.exp(-t / 0.05)) / SR) * np.exp(-t / 0.35)
    return 1.3 * y + 0.8 * thump


def kick(vel=1.0):
    n = int(0.5 * SR)
    t = times(n)
    body = np.sin(2 * np.pi * np.cumsum(47 + 125 * np.exp(-t / 0.028)) / SR) * np.exp(-t / 0.26)
    click = butter(noise(n), 'high', 2500) * np.exp(-t / 0.004) * 0.3
    return np.tanh(1.7 * (body + click)) * 0.9 * vel


def snare(vel=1.0):
    n = int(0.4 * SR)
    t = times(n)
    tone = (np.sin(2 * np.pi * 185 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)) * np.exp(-t / 0.055) * 0.55
    rattle = butter(noise(n), 'band', [1200, 9500]) * np.exp(-t / 0.12)
    return (tone + rattle) * vel * 0.75


def clap(vel=1.0):
    n = int(0.35 * SR)
    t = times(n)
    env = np.exp(-t / 0.085) * 0.6
    for at in (0, 0.011, 0.023):
        env += np.where(t >= at, np.exp(-(t - at) / 0.005), 0)
    return butter(noise(n), 'band', [900, 4000]) * env * vel * 0.55


METAL = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)  # The 808's cymbal oscillators.


def metal(n):
    return sum(pulse(f, n) for f in METAL) / len(METAL)


def hat(vel=1.0, open_=False):
    n = int((0.35 if open_ else 0.09) * SR)
    x = butter(0.6 * noise(n) + metal(n), 'high', 7000)
    return x * decay(n, 0.2 if open_ else 0.03, 0.0005) * vel * 0.45


def crash(vel=1.0, length=2.6):
    n = int(length * SR)
    x = butter(noise(n) + 0.8 * metal(n), 'high', 3800)
    return x * decay(n, 0.8, 0.001) * vel * 0.5


def tom(midi, vel=1.0):
    n = int(0.45 * SR)
    t = times(n)
    f = float(hz(midi)) * (1 + 0.5 * np.exp(-t / 0.05))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.22)
    return (y + 0.2 * butter(noise(n), 'low', 3000) * np.exp(-t / 0.02)) * vel * 0.8


def timpani(midi, vel=1.0):
    n = int(1.4 * SR)
    t = times(n)
    f = float(hz(midi)) * (1 + 0.03 * np.exp(-t / 0.1))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.55)
    y += 0.35 * np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * np.exp(-t / 0.3)
    return (y + 0.4 * butter(noise(n), 'band', [60, 500]) * np.exp(-t / 0.03)) * vel


def riser(length, top=7000):
    n = int(length * SR)
    t = times(n)
    y = sweep(noise(n), 220 * (top / 220) ** (t / length), 'bp', q=2.2)
    return y * (t / length) ** 2.2


def whoosh(length):
    """The emblem's spinning flight: rising air with a flutter that speeds up with the spin."""
    n = int(length * SR)
    t = times(n)
    flutter = 0.55 + 0.45 * np.abs(np.cos(np.pi * np.cumsum(3 + 12 * (t / length) ** 2) / SR))
    return riser(length, 4000) * flutter


def static_burst(length):
    n = int(length * SR)
    t = times(n)
    crackle = 1 + 3 * (rng.random(n) < 0.004)
    x = butter(noise(n) * crackle, 'band', [250, 7500])
    env = np.clip(1 - (t - 0.28) / (length - 0.28), 0, 1)
    click = np.sin(2 * np.pi * 1700 * t) * np.exp(-t / 0.003) + np.sin(2 * np.pi * 90 * t) * np.exp(-t / 0.03)
    return 0.35 * x * env + 0.6 * click


# ---------------------------------------------------------------- mixing desk

class Desk:
    """Stereo buses: dry, a hall send and the gated-snare room."""

    def __init__(self):
        self.dry, self.hall, self.room = (np.zeros((2, N)) for _ in range(3))

    def add(self, sound, at, gain=1.0, pan=0.0, hall=0.15, room=0.0):
        start = int(round(at * SR))
        if start >= N or len(sound) == 0:
            return
        sound = sound[:N - start]
        angle = (np.clip(pan, -1, 1) + 1) * np.pi / 4
        for bus, amount in ((self.dry, 1.0), (self.hall, hall), (self.room, room)):
            if amount:
                bus[0, start:start + len(sound)] += sound * gain * amount * np.cos(angle) * np.sqrt(2)
                bus[1, start:start + len(sound)] += sound * gain * amount * np.sin(angle) * np.sqrt(2)

    def wide(self, make, at, gain=1.0, spread=0.8, hall=0.2):
        """Render a sound twice with fresh phases and pan the copies apart."""
        self.add(make(), at, gain * 0.75, -spread, hall)
        self.add(make(), at, gain * 0.75, spread, hall)


def impulse(length, rt60, predelay=0.02, dark=4500):
    n = int(length * SR)
    t = times(n)
    tail = []
    for _ in range(2):
        x = noise(n) * np.exp(-6.9 * t / rt60)
        x = butter(x, 'low', dark) * 0.6 + x * 0.4 * np.exp(-t / 0.15)
        x[:int(predelay * SR)] = 0
        tail.append(x / np.sqrt(np.sum(x ** 2)))
    return np.array(tail)


def gated_room():
    """The eighties-into-nineties gated snare: a dense burst of room, cut off hard."""
    n = int(0.3 * SR)
    t = times(n)
    tail = []
    for _ in range(2):
        x = noise(n) * np.where(t < 0.24, 1.0, np.exp(-(t - 0.24) / 0.008)) * np.exp(-t / 0.4)
        tail.append(x / np.sqrt(np.sum(x ** 2)))
    return np.array(tail)


def convolve(bus, ir):
    return np.array([signal.fftconvolve(bus[c], ir[c])[:N] for c in range(2)])


# ---------------------------------------------------------------- the arrangement

def at(bar, beat=0.0):
    """Seconds for a position in bars (1-based) and beats."""
    return T.beat((bar - 1) * 4 + beat)


B = T.BEAT
MOTIF_C = (72, 76, 79, 81)   # Viz-el-Vi-sion, first time: ends open, on the sixth.
MOTIF_D = (74, 78, 81, 86)   # At the button, up a step: lands on the tonic.
MOTIF_RHYTHM = ((0, 0.5), (0.5, 0.5), (1, 1), (2, 2))   # beats: offset, length


def drums_groove(desk, bar, light=False):
    kicks = (0, 2.5) if light else (0, 0.75, 2, 2.5)
    for b in kicks:
        desk.add(kick(0.8 if light else 1.0), at(bar, b), 0.9, hall=0.02)
    for b in (1, 3):
        if light:
            desk.add(clap(0.55), at(bar, b), 0.8, 0.1, hall=0.1)
        else:
            desk.add(snare(1.0), at(bar, b), 0.75, 0.05, hall=0.05, room=0.9)
            desk.add(clap(0.8), at(bar, b), 0.6, -0.1, hall=0.1)
    steps = 8 if light else 16
    for i in range(steps):
        b = i * 4 / steps
        is_open = not light and b == 3.5
        desk.add(hat(0.5 if light else (0.8 if i % 2 == 0 else 0.45), is_open), at(bar, b),
                 0.55, 0.35, hall=0.03)


def snare_roll(desk, start_beat, beats, v0=0.2, v1=1.0):
    hits = []
    b = 0.0
    while b < beats:
        hits.append(b)
        b += 0.25 if b < beats - 1 else 0.125
    for i, b in enumerate(hits):
        vel = v0 + (v1 - v0) * (i / max(1, len(hits) - 1)) ** 1.5
        desk.add(snare(vel), T.beat(start_beat + b), 0.7, rng.uniform(-0.2, 0.2), hall=0.12, room=0.4)


def hit(desk, root, when, big=False):
    desk.wide(lambda: orch_hit(root), when, 0.55 if big else 0.45, 0.6, hall=0.45)
    desk.add(crash(1.0, 3.0 if big else 2.6), when, 0.45, 0.3, hall=0.3)
    desk.add(crash(0.8, 2.4), when + 0.004, 0.3, -0.4, hall=0.3)
    desk.add(kick(1.0), when, 1.0, hall=0.05)
    desk.add(timpani(root - 24, 1.0), when, 0.6, hall=0.35)


def compose(desk):
    # Channel change: click and a burst of static under the picture's snow.
    desk.add(static_burst(T.STATIC_END + 0.05), 0.0, 0.7, hall=0.0)

    # Bars 1-2: brass fanfare, bVI - bVII into the hit.
    fanfare = (((48, 55, 60, 64, 67), 0, 0.35), ((52, 55, 60, 64, 72), 1.5, 0.2),
               ((55, 60, 64, 67, 76), 2, 0.2), ((60, 64, 67, 72, 79), 3, 0.9))
    for chord, b, beats in fanfare:
        for i, note in enumerate(chord):
            desk.add(brass(note, beats * B, 0.95), at(1, b), 0.16, -0.5 + i * 0.25, hall=0.25)
    desk.add(timpani(36, 1.0), at(1), 0.5, hall=0.3)
    desk.add(bass(36, 1.9 * B), at(1), 0.5)
    for chord, b, vel in (((44, 56, 60, 63, 68, 72), 4, 0.7), ((46, 58, 62, 65, 70, 74), 6, 0.9)):
        for i, note in enumerate(chord):
            desk.add(brass(note, 1.9 * B, vel, attack=0.12), at(1, b), 0.15, -0.5 + i * 0.2, hall=0.3)
        desk.add(bass(chord[0] - 12, 1.9 * B), at(1, b), 0.55)
        desk.wide(lambda c=chord: pad_voice(c[1:], 1.9 * B, 0.3, 0.4), at(1, b), 0.12)
        desk.add(timpani(chord[0] - 12, 0.8), at(1, b), 0.4, hall=0.3)
    snare_roll(desk, 4, 4, 0.15, 0.95)
    desk.add(whoosh(T.HIT - T.LOGO_FLIGHT), T.LOGO_FLIGHT, 0.5, hall=0.2)
    reverse = crash(1.0, 1.4)[::-1]
    desk.add(reverse, T.HIT - len(reverse) / SR, 0.5, hall=0.1)

    # Bar 3: the hit, and the logo sounded for the first time.
    hit(desk, 60, T.HIT)
    for (offset, length), note in zip(MOTIF_RHYTHM, MOTIF_C):
        when = T.beat(8 + offset)
        desk.add(bell(note, 2.8), when, 0.34, -0.15, hall=0.35)
        desk.add(bell(note + 12, 1.6, 0.6), when, 0.1, 0.3, hall=0.4)
        desk.wide(lambda n=note, l=length: brass(n, l * B * 0.95, 0.9), when, 0.14, 0.3, hall=0.25)

    # The wordmark types itself in: one marimba note per letter, travelling left to right.
    letters = sum(len(part) for part in T.WORDMARK)
    scale = (60, 62, 64, 67, 69, 72, 74, 76, 79, 81, 84)
    for i in range(letters):
        pan = -0.7 + 1.4 * i / (letters - 1)
        desk.add(marimba(scale[i % len(scale)], 0.8), T.LETTERS + i * T.LETTER_STEP, 0.2, pan, hall=0.2)

    # Bars 3-6: I - vi - IV - V groove.
    groove = ((36, (60, 64, 67, 74), 12), (33, (57, 60, 64, 67), 10),
              (41, (57, 60, 64, 65), 12), (43, (55, 59, 62, 67), 10))
    for i, (root, chord, seventh) in enumerate(groove):
        bar = 3 + i
        drums_groove(desk, bar)
        desk.wide(lambda c=chord: pad_voice(c, 3.9 * B, 0.25, 0.5), at(bar), 0.13)
        for b, interval, beats in ((0, 0, 0.7), (0.75, 12, 0.2), (1.5, 0, 0.4), (2, 7, 0.45),
                                   (2.75, 12, 0.2), (3, 0, 0.4), (3.5, seventh, 0.4)):
            desk.add(bass(root + interval, beats * B, 0.95), at(bar, b), 0.55)
        for b in (0.5, 1.5, 2.75, 3.5):
            for note in chord:
                desk.add(epiano(note + 12, 0.3 * B, 0.55), at(bar, b), 0.07, 0.25, hall=0.2)
    for b, beats in ((0.5, 0.3), (1.5, 0.3), (3, 0.9)):
        for i, note in enumerate((55, 59, 62, 67, 71)):
            desk.add(brass(note, beats * B, 0.85), at(6, b), 0.12, -0.4 + i * 0.2, hall=0.25)
    for i, note in enumerate((84, 88, 91, 96)):
        desk.add(bell(note, 1.5, 0.7), T.SWEEP + i * B / 8, 0.1, 0.5 - i * 0.3, hall=0.5)

    # Bars 7-10: under the voice. Fmaj7 - Em7 - Dm7 - G7sus4 / G.
    quiet = ((41, (57, 60, 64, 65)), (40, (55, 59, 62, 64)), (38, (53, 57, 60, 62)), (43, (53, 55, 60, 62)))
    for i, (root, chord) in enumerate(quiet):
        bar = 7 + i
        drums_groove(desk, bar, light=True)
        desk.wide(lambda c=chord: pad_voice(c, 3.9 * B, 0.4, 0.6), at(bar), 0.11)
        for b in (0, 2.5):
            for note in chord:
                desk.add(epiano(note + 12, 1.2 * B, 0.45), at(bar, b), 0.07, -0.2, hall=0.3)
        for b, interval, beats in ((0, 0, 1.4), (1.5, 0, 0.45), (2, 7, 1.4), (3.5, 12, 0.4)):
            desk.add(bass(root + interval, beats * B, 0.75), at(bar, b), 0.5)
    for note, b in ((71, 3), (74, 3.25), (79, 3.5)):
        desk.add(bell(note, 1.8, 0.6), at(8, b), 0.14, 0.35, hall=0.45)
    desk.add(bell(72, 2.0, 0.6), at(10, 2), 0.14, -0.3, hall=0.45)  # G turns to G7sus: a lift.

    # Bars 11-12: bVI - bVII of the new key, building.
    for i, (root, chord, vel) in enumerate(((46, (58, 62, 65, 70), 0.6), (48, (60, 64, 67, 72), 0.85))):
        bar = 11 + i
        desk.wide(lambda c=chord: pad_voice(c, 3.9 * B, 0.6, 0.3), at(bar), 0.13)
        for j, note in enumerate(chord):
            desk.add(brass(note, 3.8 * B, vel, attack=0.9), at(bar), 0.12, -0.4 + j * 0.27, hall=0.3)
        for k in range(8):
            desk.add(bass(root, 0.4 * B, 0.7 + 0.03 * k), at(bar, k * 0.5), 0.5)
        for b in range(4):
            desk.add(kick(0.75 + 0.05 * i), at(bar, b), 0.85, hall=0.02)
        for k in range(16):
            desk.add(hat(0.35 + 0.02 * k), at(bar, k * 0.25), 0.5, 0.35, hall=0.03)
        if i == 0:
            for b in (1, 3):
                desk.add(clap(0.6), at(bar, b), 0.7, hall=0.1)
    snare_roll(desk, 46, 2, 0.3, 1.0)
    desk.add(riser(4 * B, 8000), at(12), 0.35, hall=0.2)
    desk.add(reverse, T.KEY_CHANGE - len(reverse) / SR, 0.5, hall=0.1)

    # Bar 13: the key change. The logo again, up a step, sung.
    hit(desk, 62, T.KEY_CHANGE)
    harmony = (69, 74, 78, 81)
    for (offset, length), note, under in zip(MOTIF_RHYTHM, MOTIF_D, harmony):
        when = T.beat(48 + offset)
        gate = length * B * 0.95
        desk.add(bell(note, 2.8), when, 0.3, -0.15, hall=0.35)
        desk.add(bell(note + 12, 1.6, 0.6), when, 0.1, 0.3, hall=0.4)
        desk.wide(lambda n=note: brass(n, gate, 0.95), when, 0.14, 0.3, hall=0.25)
        desk.add(choir(note, gate), when, 0.5, -0.35, hall=0.45)
        desk.add(choir(under, gate), when, 0.4, 0.35, hall=0.45)
    desk.wide(lambda: pad_voice((62, 66, 69, 74), 1.9 * B, 0.1, 0.3), at(13), 0.13)
    desk.wide(lambda: pad_voice((67, 69, 71, 74), 1.9 * B, 0.1, 0.3), at(13, 2), 0.13)
    for b, note in ((0, 38), (0.75, 50), (1.5, 38), (2, 45), (2.75, 57), (3, 45)):
        desk.add(bass(note, 0.45 * B, 1.0), at(13, b), 0.55)
    for b in (0, 1.5, 2):
        desk.add(kick(1.0), at(13, b), 0.9, hall=0.02)
    desk.add(snare(1.0), at(13, 1), 0.75, hall=0.05, room=0.9)
    for k in range(12):
        desk.add(hat(0.6), at(13, k * 0.25), 0.5, 0.35, hall=0.03)
    for k, note in enumerate((57, 55, 52, 50)):  # Tom fill into the button.
        desk.add(tom(note, 0.9), at(13, 3 + k * 0.25), 0.7, 0.5 - k * 0.33, hall=0.2)

    # Bar 14: the button. D major, everything rings out.
    hit(desk, 62, T.BUTTON, big=True)
    for i, note in enumerate((50, 57, 62, 66, 69, 74, 78)):
        desk.add(brass(note, 1.6, 1.0), T.BUTTON, 0.13, -0.6 + i * 0.2, hall=0.4)
    for note, pan in ((62, -0.5), (66, 0.5), (69, -0.2), (74, 0.2)):
        desk.add(choir(note, 1.9, 0.9), T.BUTTON, 0.35, pan, hall=0.5)
    desk.wide(lambda: pad_voice((62, 66, 69, 74, 78), 2.2, 0.05, 1.0), T.BUTTON, 0.14)
    desk.add(bass(38, 1.8, 1.0), T.BUTTON, 0.6)
    for i, note in enumerate((86, 90, 93, 98)):
        desk.add(bell(note, 2.2, 0.8), T.BUTTON + 0.05 + i * B / 8, 0.13, -0.5 + i * 0.33, hall=0.55)
    desk.add(bell(98, 3.0, 0.5), T.IRIS, 0.08, 0.2, hall=0.6)  # A last glint as the iris closes.


# ---------------------------------------------------------------- voice and master

def load_voice(path):
    rate, data = wavfile.read(path)
    if rate != SR:
        raise SystemExit(f'{path}: expected {SR} Hz, got {rate}')
    x = data.astype(float) / 32768.0
    if x.ndim > 1:
        x = x.mean(axis=1)
    # Start on the first word: trim the lead-in and tail silence.
    loud = np.flatnonzero(np.abs(x) > 10 ** (-42 / 20))
    if not len(loud):
        return np.zeros(0)
    x = x[max(0, loud[0] - int(0.015 * SR)):loud[-1] + int(0.12 * SR)]
    x = butter(x, 'high', 85)
    # Gentle broadcast polish: a little presence and even level.
    x = x + 0.25 * butter(x, 'band', [2500, 5000])
    return x / (np.sqrt(np.mean(x ** 2)) + 1e-9) * 0.1


def voice_track(script):
    track = np.zeros(N)
    placed = []
    for line in script['lines']:
        path = HERE / 'voice' / f"{line['id']}.wav"
        if not path.exists():
            print(f"  voice: {line['id']} is not rendered; the ID will play without it")
            continue
        x = load_voice(path)
        start = int(line['at'] * SR)
        end = min(N, start + len(x))
        if placed and start < placed[-1]:
            print(f"  voice: {line['id']} overlaps the previous line")
        if end > int(T.BLACK * SR):
            print(f"  voice: {line['id']} runs past the end of the picture")
        track[start:end] += x[:end - start]
        placed.append(end)
        print(f"  voice: {line['id']} {line['at']:.2f}-{end / SR:.2f} s")
    return track


def duck(voice, depth_db=7.0):
    """Lower the music under the voice, easing in just before each line."""
    active = butter(np.abs(voice), 'low', 8) > 0.01
    window = np.hanning(int(0.35 * SR))
    amount = np.clip(signal.fftconvolve(active.astype(float), window / window.max(), 'same'), 0, 1)
    return 10 ** (-depth_db * amount / 20)


def limiter(mix, ceiling_db=-1.0, attack=0.004, release=0.15, step=32):
    """Look-ahead peak limiter: the gain is down before each hit arrives, then recovers."""
    ceiling = 10 ** (ceiling_db / 20)
    k = int(attack * SR)
    peak = ndimage.maximum_filter1d(np.abs(mix).max(axis=0), 2 * k + 1)
    need = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    coarse = need[:len(need) // step * step].reshape(-1, step).min(axis=1)
    alpha = 1 - np.exp(-step / (release * SR))
    gain, current = np.empty_like(coarse), 1.0
    for i, value in enumerate(coarse):
        current = min(value, current + (1 - current) * alpha)
        gain[i] = current
    gain = np.repeat(ndimage.minimum_filter1d(gain, 3), step)
    gain = np.convolve(gain, np.ones(step) / step, 'same')  # Smooth the steps; still under need.
    gain = np.concatenate([gain, np.full(len(need) - len(gain), gain[-1])])
    return mix * gain


def master(desk, voice):
    music = desk.dry + convolve(desk.hall, impulse(2.6, 1.9)) * 0.9 + convolve(desk.room, gated_room()) * 0.5
    music = butter(music, 'high', 30)
    music *= duck(voice)
    plate = convolve(np.array([voice, voice]) * 0.12, impulse(1.2, 0.7, 0.012, 6000))
    mix = music * 0.6 + np.array([voice, voice]) * 1.25 + plate
    # Set the groove at a healthy level and let the limiter take the hits.
    groove = mix[:, int(T.HIT * SR) + SR // 4:int(T.RIBBON * SR)]
    mix *= 10 ** (-13 / 20) / np.sqrt(np.mean(groove ** 2))
    mix = limiter(mix)
    t = times(N)
    fade = np.clip((T.BLACK - t) / (T.BLACK - 28.4), 0, 1)
    return mix * np.sin(fade * np.pi / 2) ** 2


def main(argv):
    paths = [a for a in argv[1:] if not a.startswith('--')]
    out = Path(paths[0]) if paths else HERE / 'build' / 'audio.wav'
    script = {'lines': []} if '--no-voice' in argv else json.loads((HERE / 'script.json').read_text())
    desk = Desk()
    compose(desk)
    voice = voice_track(script)
    mix = master(desk, voice)
    out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out, SR, mix.T.astype(np.float32))
    report(mix, voice)
    print(f'  audio: {out}')


def report(mix, voice):
    """Levels by section: the voice should sit well above the music around it."""
    for name, a, b in (('fanfare', 0.5, 4.5), ('groove', 4.6, 7.7), ('voice 1', 7.8, 9.6),
                       ('voice 2', 12.9, 15.9), ('build', 23.2, 24.4), ('button', 24.5, 27.5)):
        seg = mix[:, int(a * SR):int(b * SR)]
        rms = 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        print(f'  level {name:8s} {rms:6.1f} dBFS rms')


if __name__ == '__main__':
    main(sys.argv)
