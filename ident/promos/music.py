"""The station promos' sound: the sonic identity's family (ident/sonic.py, jingle.py) in
short cues, with their voice lines (script.json, voiced by voice.py) mixed over them.

    python music.py ID OUT.wav [--no-voice]     (needs numpy and scipy)

Each cue keeps the rules: the four-note logo, open (C E G A) for "there's more" and
closed (D F# A D), up a whole step, for the answer; 120 BPM; a silent tail. The build
(build.py) levels the result to -20 LUFS, as the station ID is. --no-voice writes the music
alone: 'only-on' is voiced again over it for each programme (roku_stream/promos.py).
"""
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy import signal
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import beats  # noqa: E402  Hits the pictures share (the drum circle, the train).
import jingle as J  # noqa: E402
import sonic as S  # noqa: E402

SR = J.SR
BEAT = 0.5
OPEN, CLOSED = S.LOGO_OPEN, S.LOGO_CLOSED
RHYTHM = S.LOGO_RHYTHM
rng = np.random.default_rng(1979)


def hits(promo_id):
    """A picture's hit points: its module's top-level constants that are plain literals,
    read from its source, so the music follows the picture without importing pycairo."""
    tree = ast.parse((HERE / f"{promo_id.replace('-', '_')}.py").read_text())
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            continue
        if isinstance(target, ast.Name):
            found[target.id] = value
        elif isinstance(target, ast.Tuple) and all(isinstance(e, ast.Name) for e in target.elts):
            found.update({e.id: v for e, v in zip(target.elts, value)})
    return SimpleNamespace(**found)


def at_logo(start, step=1.0):
    """The logo's four note times from start (its rhythm: eighth, eighth, quarter, half)."""
    return [start + offset * BEAT * step for offset, _ in RHYTHM]


# ---------------------------------------------------------------- more instruments

def vibes(midi, length=1.8, vel=1.0):
    """A vibraphone: a bar's sine and its fourth partial, the motor's tremolo."""
    n = int(length * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = np.sin(2 * np.pi * f * t) + 0.18 * np.sin(2 * np.pi * f * 3.98 * t) * np.exp(-t / 0.08)
    x *= 1 + 0.28 * np.sin(2 * np.pi * 5.6 * t)
    return x * np.exp(-t / 1.1) * J.decay(n, 1e9, 0.002) * vel


def pizz(midi, vel=1.0, length=0.6):
    """A plucked string (Karplus-Strong), short and woody."""
    n = int(length * SR)
    period = max(2, int(round(SR / float(J.hz(midi)) - 0.5)))   # the averaging adds half a sample
    buf = rng.uniform(-1, 1, period)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = 0.5 * (buf[i % period] + buf[(i + 1) % period]) * 0.993
    out = J.butter(out, 'low', 3500)
    return out * J.decay(n, 0.22, 0.001) * vel


def square(midi, gate, duty=0.5, vel=1.0):
    """The chip's pulse channel: a naive square (its aliasing is the grit), a hard gate."""
    n = int(gate * SR)
    t = J.times(n)
    phase = (float(J.hz(midi)) * t) % 1
    x = np.where(phase < duty, 1.0, -1.0)
    env = np.clip(t / 0.003, 0, 1) * np.clip((gate - t) / 0.01, 0, 1) * (0.75 + 0.25 * np.exp(-t / 0.08))
    return x * env * vel * 0.3


def triangle(midi, gate, vel=1.0):
    n = int(gate * SR)
    t = J.times(n)
    phase = (float(J.hz(midi)) * t) % 1
    x = 4 * np.abs(phase - 0.5) - 1
    x = np.round(x * 8) / 8                      # the chip's 4-bit staircase
    return x * np.clip((gate - t) / 0.01, 0, 1) * vel * 0.45


def chip_noise(length=0.08, vel=1.0, bright=True):
    n = int(length * SR)
    x = np.repeat(rng.choice([-1.0, 1.0], n // (4 if bright else 24) + 1), 4 if bright else 24)[:n]
    return x * J.decay(n, length / 3, 0.0005) * vel * 0.25


def sweep_square(f0, f1, length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    f = f0 * (f1 / f0) ** (t / length)
    phase = np.cumsum(f) / SR % 1
    return np.where(phase < 0.5, 1.0, -1.0) * np.clip((length - t) / 0.01, 0, 1) * vel * 0.25


def glide(f0, f1, length, vel=1.0):
    """A slide whistle: a sine gliding from f0 to f1 with a little breath."""
    n = int(length * SR)
    t = J.times(n)
    f = f0 * (f1 / f0) ** (t / length) * (1 + 0.006 * np.sin(2 * np.pi * 6 * t))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.05 * J.butter(J.noise(n), 'band', [1500, 5000])
    return x * np.clip(t / 0.03, 0, 1) * np.clip((length - t) / 0.05, 0, 1) * vel * 0.5


def boing(length=0.6, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    f = 160 * (1 + 0.6 * np.exp(-t / 0.15) * np.sin(2 * np.pi * 9 * t)) * (1 + 0.8 * np.exp(-t / 0.05))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.25) * vel * 0.8


def ceramic(vel=1.0):
    """A mug smashing: bright inharmonic rings and a burst of shards."""
    n = int(1.2 * SR)
    t = J.times(n)
    x = np.zeros(n)
    for f, d in ((2210, 0.25), (3170, 0.18), (4420, 0.12), (5830, 0.1), (1630, 0.3)):
        x += np.sin(2 * np.pi * f * t + rng.random() * 6) * np.exp(-t / d)
    for _ in range(14):                          # shards landing
        start = int(rng.uniform(0.0, 0.35) * SR)
        burst = J.butter(J.noise(900), 'high', 3000) * np.exp(-J.times(900) / 0.006)
        x[start:start + 900] += burst * rng.uniform(0.3, 0.8)
    return x * 0.3 * vel


def clack():
    """A slide projector's change: the carriage clack and the lamp's thunk."""
    n = int(0.25 * SR)
    t = J.times(n)
    click = J.butter(J.noise(n), 'band', [1200, 6000]) * np.exp(-t / 0.006)
    thunk = np.sin(2 * np.pi * 95 * t) * np.exp(-t / 0.05)
    second = np.zeros(n)
    second[int(0.06 * SR):] = click[:n - int(0.06 * SR)] * 0.5
    return 0.6 * click + 0.5 * thunk + second


def rim(vel=1.0):
    n = int(0.06 * SR)
    t = J.times(n)
    return (np.sin(2 * np.pi * 1750 * t) + 0.5 * np.sin(2 * np.pi * 2900 * t)) * np.exp(-t / 0.01) * vel * 0.4


def brush(length=0.3, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [2000, 9000]) * np.sin(np.pi * t / length) ** 2 * vel * 0.15


def meow():
    """'Mrrp': a rolled r into a rising, falling vowel, through a cat-sized vocal tract."""
    length = 0.42
    n = int(length * SR)
    t = J.times(n)
    pitch = 520 + 260 * np.sin(np.pi * np.clip(t / length, 0, 1) * 0.9)
    x = J.saw(pitch, n)
    roll = 1 - 0.8 * (t < 0.12) * (0.5 + 0.5 * np.sin(2 * np.pi * 28 * t))
    vowel = J.sweep(x, 900 + 900 * np.sin(np.pi * t / length), 'bp', q=3) + 0.6 * J.sweep(x, 2600 + 400 * t / length, 'bp', q=4)
    env = np.clip(t / 0.02, 0, 1) * np.clip((length - t) / 0.12, 0, 1)
    return vowel * roll * env * 0.6


def zap():
    """The set coming on: a click and a rising whine that settles."""
    n = int(0.45 * SR)
    t = J.times(n)
    whine = np.sin(2 * np.pi * np.cumsum(300 + 3200 * (1 - np.exp(-t / 0.08))) / SR) * np.exp(-t / 0.15)
    return 0.3 * whine + 0.5 * J.butter(J.noise(n), 'high', 2000) * np.exp(-t / 0.004)


# ---------------------------------------------------------------- the neighbourhoods' sounds, and 2006's

def chime(midi, length=1.6, vel=1.0):
    """The Metro's door chime: a pure, slightly hollow tone."""
    n = int(length * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t) * np.exp(-t / 0.3) \
        + 0.08 * np.sin(6 * np.pi * f * t) * np.exp(-t / 0.12)
    return x * np.exp(-t / 0.75) * J.decay(n, 1e9, 0.004) * vel


def clack(vel=1.0):
    """A wheel over a rail joint: a thump and a tick."""
    n = int(0.12 * SR)
    t = J.times(n)
    thump = np.sin(2 * np.pi * np.cumsum(90 + 80 * np.exp(-t / 0.01)) / SR) * np.exp(-t / 0.03)
    tick = J.butter(J.noise(n), 'band', [1800, 6500]) * np.exp(-t / 0.006)
    return (0.8 * thump + 0.45 * tick) * vel


def squeal(length):
    """Brakes: a high, wavering ring that swells and stops dead."""
    n = int(length * SR)
    t = J.times(n)
    f = 2650 * (1 + 0.004 * np.sin(2 * np.pi * 7 * t))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.35 * np.sin(2 * np.pi * np.cumsum(f * 1.53) / SR)
    return x * np.clip(t / length, 0, 1) ** 1.5 * np.clip((length - t) / 0.02, 0, 1)


def hiss(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'high', 2500) * np.clip(t / 0.01, 0, 1) * np.exp(-t / (length / 3)) * vel


def slide(length, vel=1.0):
    """Doors sliding in their tracks, and the thunk as they meet their stops."""
    n = int((length + 0.2) * SR)
    t = J.times(n)
    run = J.butter(J.noise(n), 'band', [250, 1800]) * np.sin(np.pi * np.clip(t / length, 0, 1)) * 0.6
    stop = np.where(t >= length, np.sin(2 * np.pi * 110 * (t - length)) * np.exp(-(t - length) / 0.04), 0)
    return (run + stop) * vel


def cowbell(high=True, vel=1.0):
    n = int(0.25 * SR)
    t = J.times(n)
    f1, f2 = (587, 845) if high else (440, 634)
    x = np.sign(np.sin(2 * np.pi * f1 * t)) + np.sign(np.sin(2 * np.pi * f2 * t))
    return J.butter(x, 'band', [400, 3000]) * np.exp(-t / 0.07) * vel * 0.25


def water(length, level=1.0):
    """A fountain: splashing noise, breathing slowly."""
    n = int(length * SR)
    t = J.times(n)
    x = J.butter(J.noise(n), 'band', [450, 7000]) * (1 + 0.2 * np.sin(2 * np.pi * 0.31 * t))
    return x * level * np.clip(t / 0.4, 0, 1)


def plink(midi, vel=1.0):
    """A drop into water, tuned: the pitch bloops up into the note."""
    n = int(0.6 * SR)
    t = J.times(n)
    f = float(J.hz(midi)) * (1 - 0.35 * np.exp(-t / 0.012))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.18)
    return x * J.decay(n, 1e9, 0.002) * vel


def splash(vel=1.0):
    n = int(0.8 * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [700, 6500]) * np.clip(t / 0.03, 0, 1) * np.exp(-t / 0.22) * vel


def chirp(rand):
    """A sparrow: two or three quick upward whistles."""
    out = np.zeros(int(0.4 * SR))
    for k in range(rand.integers(2, 4)):
        n = int(0.05 * SR)
        t = J.times(n)
        f0 = rand.uniform(2800, 3600)
        x = np.sin(2 * np.pi * np.cumsum(f0 + 1600 * t / 0.05) / SR) * np.sin(np.pi * t / 0.05)
        start = int(k * 0.09 * SR)
        out[start:start + n] += x
    return out


def coo():
    """A pigeon: coo-COO, throaty."""
    out = np.zeros(int(0.8 * SR))
    for start, length, pitch in ((0.0, 0.18, 430), (0.24, 0.42, 470)):
        n = int(length * SR)
        t = J.times(n)
        f = pitch * (1 - 0.15 * t / length)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * (1 + 0.5 * np.sin(2 * np.pi * 28 * t)) * np.sin(np.pi * t / length)
        out[int(start * SR):int(start * SR) + n] += J.butter(x, 'low', 900)
    return out * 0.6


def flutter(length, rate=11.0):
    """Wings taking off: soft noise beaten in pulses that ease off."""
    n = int(length * SR)
    t = J.times(n)
    beatsx = np.abs(np.sin(np.pi * rate * t * (1 - 0.25 * t / length))) ** 3
    return J.butter(J.noise(n), 'band', [350, 3200]) * beatsx * np.exp(-t / (length / 2))


def click(vel=1.0):
    """A wooden chess piece set down."""
    n = int(0.08 * SR)
    t = J.times(n)
    return (np.sin(2 * np.pi * 1900 * t) * np.exp(-t / 0.008) + 0.6 * J.butter(J.noise(n), 'band', [1500, 5000])
            * np.exp(-t / 0.004)) * vel * 0.6


def membrane(f0, decay, bend=0.04, overtones=((1.5, 0.35, 0.5), (2.1, 0.2, 0.35))):
    n = int((decay * 5) * SR)
    t = J.times(n)
    f = f0 * (1 + bend * np.exp(-t / 0.02))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / decay)
    for ratio, gain, rel in overtones:
        x += gain * np.sin(2 * np.pi * np.cumsum(f * ratio) / SR) * np.exp(-t / (decay * rel))
    return x


def djembe(stroke, vel=1.0):
    """bass (the middle of the head), tone (the edge), slap (the edge, fingers cracking)."""
    if stroke == 'bass':
        n = int(0.6 * SR)
        x = membrane(78, 0.14, bend=0.5)[:n]
        x += 0.15 * J.butter(J.noise(n), 'low', 1200) * np.exp(-J.times(n) / 0.01)
        return x * vel
    if stroke == 'tone':
        x = membrane(330, 0.07)
        n = len(x)
        return (x + 0.25 * J.butter(J.noise(n), 'band', [800, 4000]) * np.exp(-J.times(n) / 0.006)) * vel * 0.8
    n = int(0.25 * SR)
    t = J.times(n)
    crack = J.butter(J.noise(n), 'band', [1500, 7000]) * np.exp(-t / 0.035)
    body = membrane(420, 0.03)
    return (crack + 0.4 * np.pad(body, (0, max(0, n - len(body))))[:n]) * vel * 0.8


def conga(midi, vel=1.0):
    x = membrane(float(J.hz(midi)), 0.16, bend=0.06, overtones=((1.59, 0.3, 0.6), (2.14, 0.15, 0.3)))
    n = len(x)
    return (x + 0.2 * J.butter(J.noise(n), 'band', [600, 3500]) * np.exp(-J.times(n) / 0.005)) * vel


def shaker(vel=1.0):
    n = int(0.07 * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'high', 4500) * np.sin(np.pi * t / 0.07) ** 2 * vel * 0.4


def steelpan(midi, vel=1.0, length=1.4):
    """A steel pan: its note, the octave and the twelfth above, a bright ping at the strike."""
    n = int(length * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = (np.sin(2 * np.pi * f * t) + 0.55 * np.sin(2 * np.pi * 2.005 * f * t) * np.exp(-t / 0.5)
         + 0.25 * np.sin(2 * np.pi * 3.01 * f * t) * np.exp(-t / 0.2))
    x *= 1 + 0.1 * np.sin(2 * np.pi * 6 * t)
    ping = np.sin(2 * np.pi * 4.2 * f * t) * np.exp(-t / 0.015) * 0.3
    return (x * np.exp(-t / 0.55) + ping) * J.decay(n, 1e9, 0.003) * vel


def whistle(vel=1.0):
    """Someone in the crowd: a quick two-note whistle, up."""
    n = int(0.55 * SR)
    t = J.times(n)
    f = np.where(t < 0.2, 1900, 2500) * (1 + 0.01 * np.sin(2 * np.pi * 6 * t))
    env = np.clip(t / 0.02, 0, 1) * np.clip((0.55 - t) / 0.1, 0, 1)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.04 * J.butter(J.noise(n), 'band', [1500, 4000])) * env * vel


def snap(vel=1.0):
    """A finger snap: two quick cracks, bright and dry."""
    n = int(0.12 * SR)
    t = J.times(n)
    second = np.where(t > 0.004, np.exp(-(t - 0.004) / 0.02), 0)
    x = J.butter(J.noise(n), 'band', [1700, 5200]) * (np.exp(-t / 0.009) + 0.5 * second)
    return x * vel


def kick808(vel=1.0, length=0.9):
    n = int(length * SR)
    t = J.times(n)
    body = np.sin(2 * np.pi * np.cumsum(46 + 70 * np.exp(-t / 0.045)) / SR) * np.exp(-t / (length * 0.45))
    return np.tanh(1.8 * body) * vel * 0.9


def sub(midi, gate, vel=1.0, glide_from=None):
    n = int((gate + 0.05) * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    if glide_from is not None:
        f = f + (float(J.hz(glide_from)) - f) * np.exp(-t / 0.06)
    x = np.sin(2 * np.pi * np.cumsum(np.broadcast_to(f, (n,))) / SR)
    return np.tanh(1.4 * x) * np.clip(t / 0.005, 0, 1) * np.clip((gate + 0.05 - t) / 0.05, 0, 1) * vel * 0.7


def pop(vel=1.0):
    """A bubble popping: a quick upward sweep."""
    n = int(0.12 * SR)
    t = J.times(n)
    return np.sin(2 * np.pi * np.cumsum(300 + 1400 * np.clip(t / 0.05, 0, 1)) / SR) * np.exp(-t / 0.04) * vel


def glass(midi, length=2.0, vel=1.0):
    """2006's glassy bell: the FM bell with a pure partial an octave up."""
    n = int(length * SR)
    t = J.times(n)
    return (J.bell(midi, length, 0.8) + 0.4 * np.sin(2 * np.pi * float(J.hz(midi + 12)) * t) * np.exp(-t / 0.5)) * vel


# ---------------------------------------------------------------- voice and mixdown

def load_line(line_id):
    path = HERE.parent / 'voice' / f'{line_id}.wav'
    if not path.exists():
        print(f'  voice: {line_id} is not rendered; the promo plays without it')
        return np.zeros(0)
    x = J.load_voice(path)
    fade = min(len(x), int(0.015 * SR))
    if fade:
        x[-fade:] *= np.linspace(1, 0, fade)
    return x


def voice_track(promo_id, length, voiced=True):
    track = np.zeros(int(length * SR))
    if not voiced:
        return track, {}
    script = json.loads((HERE / 'script.json').read_text()).get(promo_id, {'lines': []})
    lines = {}
    for line in script['lines']:
        x = load_line(line['id'])
        start = int(line['at'] * SR)
        end = min(len(track), start + len(x))
        track[start:end] += x[:end - start]
        lines[line['id']] = x
        print(f"  voice: {line['id']} {line['at']:.2f}-{end / SR:.2f} s")
    return track, lines


def mixdown(desk, voice, length, end, grit=1.0):
    """Music ducked under the voice, a touch of plate on the voice, a limiter, and silence
    from end on (faded over the last quarter second)."""
    music = desk.mix()
    if grit:
        music = S.grit(music, grit)
    music *= 10 ** (-19 / 20) / (np.sqrt(np.mean(music[:, :int(end * SR)] ** 2)) + 1e-9)
    if voice.any():
        music *= J.duck(voice, 7.0)
    plate = J.impulse(1.2, 0.7, 0.012, 6000)
    wet = np.array([signal.fftconvolve(voice * 0.12, plate[c])[:len(voice)] for c in range(2)])
    mix = music + np.array([voice, voice]) * 1.6 + wet
    mix = J.limiter(mix)
    t = J.times(mix.shape[1])
    fade = np.clip((end - t) / 0.25, 0, 1)
    return mix * np.sin(fade * np.pi / 2) ** 2


# ---------------------------------------------------------------- the five cues

def time_temp(voice):
    """Easy listening for the slide: e-piano bossa, brushes and a rim, vibes playing the
    logo as the numbers flip in, the lift to D for the closed logo, tape wow."""
    length, end = 10.0, 9.55
    desk = S.Desk(length)
    desk.add(clack(), 0.1, 0.8, hall=0.05)
    chords = (((60, 64, 67, 69, 74), 0.12, 2.0), ((57, 60, 64, 67, 71), 2.0, 2.0), ((53, 57, 60, 64, 67), 4.0, 2.0),
              ((55, 60, 62, 65, 67), 6.0, 1.0), ((62, 66, 69, 73, 76), 7.0, 2.3))
    for chord, start, beats in chords:
        for k, offset in enumerate((0, 0.75, 1.5) if beats > 1.5 else (0, 0.75)):   # bossa comping
            when = start + offset * BEAT * 2
            if when >= start + beats:
                continue
            for note in chord:
                desk.add(J.epiano(note, 0.55 if k < 2 else 1.2, 0.42), when, 0.06, 0.2, hall=0.25)
        root = chord[0] - 24 if chord[0] - 24 >= 36 else chord[0] - 12
        for offset, interval in ((0, 0), (0.75, 7), (1.0, 0), (1.75, 7)):
            if offset * BEAT * 2 < beats:
                desk.add(J.bass(root + interval, 0.32, 0.55), start + offset * BEAT * 2, 0.35)
    for k in range(int(9.0 / BEAT * 2)):                      # brushes, hats and the clave
        when = 0.12 + k * BEAT / 2
        if when >= 9.1:
            break
        desk.add(J.hat(0.25), when, 0.3, 0.3, hall=0.05)
        if k % 4 == 2:
            desk.add(brush(0.32, 1.0), when - 0.05, 0.9, -0.2, hall=0.1)
    for bar in range(4):
        for offset in (0, 0.75, 1.5, 2.5, 3.0):               # a 3-2 clave on the rim
            desk.add(rim(0.8), 0.12 + bar * 4 * BEAT + offset * BEAT, 0.6, 0.35, hall=0.1)
    for when, note in zip(at_logo(1.0, 0.5), OPEN):          # vibes: the open logo, the numbers flip in
        desk.add(vibes(note, 2.0, 0.9), when, 0.32, -0.25, hall=0.35)
        desk.add(vibes(note + 12, 1.2, 0.4), when, 0.08, 0.3, hall=0.4)
    for when, note in zip(at_logo(7.0, 0.5), CLOSED):        # and the closed logo after the lift
        desk.add(vibes(note, 2.4, 1.0), when, 0.34, -0.25, hall=0.4)
        desk.add(J.bell(note + 12, 2.0, 0.5), when, 0.08, 0.3, hall=0.45)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 73), 2.0, 0.6, 1.0), 7.0, 0.08)
    return mixdown(desk, voice, length, end, grit=1.1)


def watching(voice, lines):
    """The ID's jingle remixed for hype: a stuttered build, the drop, four on the floor,
    brass stabs in the logo's rhythm, the wordmark's marimba, the horn and the crowd, the
    lift to D and the closed logo, sung."""
    length, end = 10.0, 9.55
    desk = S.Desk(length)
    chop = lines.get('promo-watching-1', np.zeros(0))[:int(0.17 * SR)].copy()
    if len(chop):
        chop[-int(0.012 * SR):] *= np.linspace(1, 0, int(0.012 * SR))
    stutter = np.zeros(int(length * SR))
    for k, when in enumerate((0.0, 0.5, 1.0, 1.25, 1.5, 1.625, 1.75, 1.875)):
        start = int(when * SR)
        stutter[start:start + len(chop)] += chop * (0.8 + 0.04 * k)
        desk.add(J.kick(0.6 + 0.05 * k), when, 0.7)
    voice = voice + stutter
    desk.add(J.riser(2.0, 9000), 0.0, 0.4, hall=0.2)
    for k in range(24):
        when = 0.5 + 1.5 * (1 - (1 - k / 24) ** 1.6)
        desk.add(J.snare(0.25 + 0.7 * k / 24), when, 0.55, rng.uniform(-0.2, 0.2), hall=0.1, room=0.4)
    reverse = J.crash(1.0, 1.2)[::-1]
    desk.add(reverse, 2.0 - len(reverse) / SR, 0.5, hall=0.1)
    J.hit(desk, 60, 2.0, big=True)
    for b in range(int((9.0 - 2.0) / BEAT)):                 # four on the floor
        when = 2.0 + b * BEAT
        if 6.75 <= when < 7.0:
            continue
        desk.add(J.kick(1.0), when, 0.95, hall=0.02)
        if b % 2:
            desk.add(J.clap(0.9), when, 0.7, 0.1, hall=0.12)
            desk.add(J.snare(0.8), when, 0.5, -0.05, hall=0.05, room=0.7)
        desk.add(J.hat(0.7, open_=True), when + BEAT / 2, 0.4, 0.35, hall=0.03)
        for s in (0.25, 0.75):
            desk.add(J.hat(0.45), when + s * BEAT, 0.4, -0.3, hall=0.02)
    for bar, (root, end_) in enumerate(((36, 5.0), (44, 6.0), (46, 7.0), (38, 9.0))):
        start = (2.0, 5.0, 6.0, 7.0)[bar]
        k = 0
        while start + k * BEAT / 2 < end_:
            desk.add(J.bass(root + (12 if k % 2 else 0), 0.2, 0.95), start + k * BEAT / 2, 0.5)
            k += 1
    for stab in (3.0, 4.0):                                   # brass stabs: the logo's rhythm
        for when, note in zip(at_logo(stab, 0.5), OPEN):
            for i, n in enumerate((note - 12, note - 5, note)):
                desk.add(J.brass(n, 0.18, 0.95), when, 0.11, -0.4 + 0.4 * i, hall=0.2)
    scale = (60, 62, 64, 67, 69, 72, 74, 76, 79, 81, 84)
    for i in range(11):                                       # the wordmark stomps in
        desk.add(J.marimba(scale[i], 0.9), 5.0 + i * 0.125, 0.24, -0.7 + 1.4 * i / 10, hall=0.2)
    desk.add(J.crash(1.0, 2.0), 5.0, 0.35, 0.3, hall=0.2)
    desk.add(S.horn(1.1), HORN_AT, 0.55, hall=0.25)
    desk.add(S.crowd(4.0, swell=(0.0, 0.8), claps=S.claps(1.0, 1)), 5.6, 0.32, hall=0.1)
    for k in range(8):
        desk.add(J.snare(0.4 + 0.08 * k), 6.5 + k * BEAT / 8, 0.6, hall=0.1, room=0.4)
    desk.add(J.riser(0.5, 8000), 6.5, 0.35, hall=0.2)
    J.hit(desk, 62, 7.0, big=True)
    S.logo(desk, 7.0, CLOSED, choir=True, gain=1.1)
    J.hit(desk, 62, 9.0, big=True)
    for i, note in enumerate((50, 57, 62, 66, 69, 74)):
        desk.add(J.brass(note, 0.5, 1.0), 9.0, 0.12, -0.5 + 0.2 * i, hall=0.4)
    return mixdown(desk, voice, length, end, grit=0.6)


HORN_AT = 6.0


def only_on(voice):
    """Whimsy: pizzicato tiptoes on the logo's notes as the mug is nudged, a marimba
    tremolo while it teeters, a slide whistle down and the crash, a boing for the leap,
    the set's zap, a light groove under the name, then the closed logo, sung, with bells;
    a mrrp, and a harp of bells for the slow blink."""
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    for i, note in enumerate((79, 83, 86, 91)):               # the iris opens: a sparkle
        desk.add(J.bell(note, 1.2, 0.6), 0.05 + i * 0.06, 0.08, -0.4 + 0.25 * i, hall=0.5)
    desk.add(J.bell(88, 0.8, 0.5), 0.6, 0.08, 0.3, hall=0.4)    # it looks at you
    for when, note in zip((1.0, 1.25, 1.5), OPEN[:3]):         # nudge, nudge, nudge
        desk.add(pizz(note, 1.0), when, 0.6, 0.2, hall=0.25)
        desk.add(pizz(note - 12, 0.8), when, 0.35, -0.2, hall=0.2)
        desk.add(J.butter(J.noise(int(0.08 * SR)), 'band', [800, 3000]) * np.hanning(int(0.08 * SR)), when, 0.06, 0.3)
    for k in range(16):                                        # A, held: it teeters
        desk.add(J.marimba(OPEN[3], 0.35 + 0.02 * k), 2.0 + k * BEAT / 8, 0.2, 0.2, hall=0.3)
    for when in (2.0, 2.5):
        desk.add(pizz(38, 1.0, 0.8), when, 0.6, -0.1, hall=0.2)
    for when in (2.55, 2.85):                                  # the glances
        desk.add(J.bell(93, 0.4, 0.5), when, 0.06, 0.4, hall=0.3)
    desk.add(J.marimba(96, 1.0), 3.0, 0.3, 0.3, hall=0.3)      # the last tap
    desk.add(glide(1700, 380, 0.45), 3.05, 0.35, 0.3, hall=0.2)
    desk.add(ceramic(1.0), 3.5, 0.75, 0.4, hall=0.25)
    desk.add(J.crash(0.9, 1.6), 3.5, 0.3, 0.4, hall=0.2)
    for i, note in enumerate((60, 64, 67, 72)):                # ta-da
        desk.add(pizz(note, 0.8), 3.75 + i * 0.03, 0.4, -0.3 + 0.2 * i, hall=0.3)
    desk.add(glide(300, 1400, 0.5), 4.4, 0.3, -0.2, hall=0.2)  # the leap
    desk.add(J.kick(0.7), 4.9, 0.6)
    desk.add(boing(0.6), 4.9, 0.5, hall=0.15)
    desk.add(zap(), 5.15, 0.4, 0.3, hall=0.1)
    groove = ((48, (64, 67, 71)), (45, (64, 67, 72)), (41, (64, 69, 72)), (43, (62, 65, 71)))
    for bar, (root, chord) in enumerate(groove[:3]):          # light, under the name
        start = 5.5 + bar * 0.5 * 2
        if start >= 7.0:
            break
        for b in (0, 0.5):
            desk.add(pizz(root - 12 + (7 if b else 0), 0.7), start + b, 0.45, -0.1, hall=0.2)
        for b in (0.25, 0.75):
            for note in chord:
                desk.add(J.marimba(note, 0.45), start + b, 0.08, 0.25, hall=0.25)
        for b in (0.25, 0.75):
            desk.add(brush(0.25, 0.8), start + b, 0.6, 0.2, hall=0.1)
    S.logo(desk, 7.0, CLOSED, organ_=False, choir=True)        # the closed logo, sung
    for when, note in zip(at_logo(7.0), CLOSED):
        desk.add(pizz(note - 12, 0.9), when, 0.4, -0.2, hall=0.25)
    desk.add(J.pad_voice((62, 66, 69, 74), 2.0, 0.2, 1.2), 7.0, 0.08, hall=0.4)
    desk.add(meow(), 8.0, 0.5, -0.1, hall=0.15)
    for i, note in enumerate((74, 78, 81, 86, 90, 93)):        # the slow blink: a harp of bells
        desk.add(J.bell(note, 1.6, 0.55), 8.3 + i * 0.05, 0.07, -0.4 + 0.15 * i, hall=0.5)
    desk.add(J.bell(98, 1.5, 0.5), 9.2, 0.08, 0.2, hall=0.6)
    return mixdown(desk, voice, length, end, grit=0.5)


def legal(voice):
    """Quiet and proper: a low brass and string chord under the line, and the closed logo
    on soft bells as the call letters fade up. No fanfare."""
    length, end = 5.0, 4.8
    desk = S.Desk(length)
    desk.add(J.timpani(38, 0.45), 0.05, 0.3, hall=0.35)
    for i, note in enumerate((50, 57, 62, 66)):
        desk.add(J.brass(note, 1.2, 0.55, attack=0.15), 0.05, 0.08, -0.4 + 0.25 * i, hall=0.4)
    for chord, start, gate in (((62, 66, 69), 0.05, 1.4), ((59, 62, 66), 1.45, 0.8), ((55, 59, 62), 2.25, 0.7),
                               ((57, 61, 64), 2.95, 0.3)):
        desk.wide(lambda c=chord, g=gate: J.pad_voice(c, g, 0.25, 0.5), start, 0.09, hall=0.35)
        desk.add(J.bass(chord[0] - 24, gate, 0.4), start, 0.22)
    for when, note in zip(at_logo(3.0, 0.5), CLOSED):
        desk.add(J.bell(note, 2.0, 0.6), when, 0.2, -0.15, hall=0.45)
        desk.add(vibes(note - 12, 1.8, 0.5), when, 0.12, 0.2, hall=0.4)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 1.6, 0.3, 0.6), 3.0, 0.08, hall=0.45)
    return mixdown(desk, voice, length, end, grit=0.6)


def press_start(voice):
    """Chiptune: a walking bass on the triangle and a bouncy lead, the jump, the bump and
    the coin, an arpeggio as the letters drop, the closed logo on two squares, a 1UP."""
    length, end = 5.0, 4.6
    desk = S.Desk(length)
    for k in range(7):                                         # the walk
        when = 0.15 + k * BEAT / 2 * 0.95
        desk.add(triangle((36, 43)[k % 2], 0.2), when, 0.7)
        desk.add(square((72, 76, 79, 76, 72, 76, 79)[k], 0.1, 0.25, 0.8), when, 0.5, 0.15)
        desk.add(chip_noise(0.05, 0.6), when + BEAT / 4, 0.5, -0.2)
    desk.add(sweep_square(300, 1200, 0.16), 1.0, 0.7)          # the jump
    desk.add(square(43, 0.08, 0.5, 1.0), 1.2, 0.6)             # the bump
    desk.add(chip_noise(0.08, 1.0, bright=False), 1.2, 0.5)
    desk.add(square(83, 0.07, 0.5, 0.9), 1.22, 0.6, 0.2)       # the coin: B, then E
    desk.add(square(88, 0.4, 0.5, 0.9) * np.exp(-J.times(int(0.4 * SR)) / 0.18), 1.29, 0.6, 0.2)
    scale = (60, 62, 64, 67, 69, 72, 74, 76, 79, 81, 84)
    for i, note in enumerate(scale):                           # the letters drop in
        desk.add(square(note, 0.08, 0.125, 0.8), 1.75 + i * 0.1, 0.45, -0.3 + 0.06 * i)
        desk.add(chip_noise(0.03, 0.5), 1.75 + i * 0.1, 0.25)
    for (offset, beats), note in zip(RHYTHM, CLOSED):          # the closed logo, in thirds
        when, gate = 3.0 + offset * BEAT, beats * BEAT * 0.92
        desk.add(square(note, gate, 0.5, 1.0), when, 0.55, -0.2)
        desk.add(square(note - 4 if note % 12 != 2 else note - 5, gate, 0.25, 0.8), when, 0.35, 0.25)
    for b in range(4):
        desk.add(triangle(38 if b % 2 == 0 else 45, 0.22), 3.0 + b * BEAT, 0.75)
        desk.add(chip_noise(0.06, 0.9), 3.0 + b * BEAT + BEAT / 2, 0.45)
    for i, note in enumerate((74, 78, 81, 86, 90)):           # 1UP
        desk.add(square(note, 0.06, 0.25, 0.8), 4.0 + i * 0.06, 0.5, 0.1)
    music = desk.mix()
    music = np.round(music * 48) / 48                          # a little more 8-bit
    desk.dry, desk.hall, desk.room = music, np.zeros_like(music), np.zeros_like(music)
    return mixdown(desk, voice, length, end, grit=0.0)


def go_go(desk, start, stop, root, gain=1.0):
    """The go-go pocket, Washington's own: kick, rim, the bells, congas into the one, a bass."""
    step = 0
    while start + step * BEAT / 4 < stop - 1e-9:
        when, k = start + step * BEAT / 4, step % 16
        if k in (0, 7, 10):
            desk.add(J.kick(0.8), when, 0.55 * gain)
        if k in (4, 12):
            desk.add(rim(1.0), when, 0.5 * gain, 0.1, hall=0.1, room=0.4)
            desk.add(J.snare(0.5), when, 0.25 * gain, 0.05, room=0.5)
        if k % 2 == 0:
            desk.add(J.hat(0.4, open_=k == 14), when, 0.22 * gain, 0.35, hall=0.03)
        if k in (0, 6, 11):
            desk.add(cowbell(True), when, 0.3 * gain, -0.3, hall=0.05)
        if k in (3, 8, 14):
            desk.add(cowbell(False), when, 0.3 * gain, -0.3, hall=0.05)
        if k in (10, 11, 13, 15):
            desk.add(conga(57 if k in (10, 15) else 62, 0.8), when, 0.3 * gain, 0.4, hall=0.08)
        if k in (0, 3, 6, 10, 12):
            desk.add(J.bass(root + (0, 0, 7, 9, 12)[(0, 3, 6, 10, 12).index(k)], 0.2, 0.8), when, 0.42 * gain)
        step += 1


def metro(voice):
    """The platform: the room's air, the train's roar and the motor's whine braking in from
    the right, the wheels over the joints, the brakes, the doors' sigh. The door chime plays
    the open logo; a go-go pocket under the operator; the closed logo on the chime as the
    doors close, the train whining away to the left, the lift to D and a last bell."""
    length, end = 10.0, 9.55
    desk = S.Desk(length)
    t = J.times(desk.n)
    (a0, a1), (d0, d1) = beats.TRAIN_ARRIVE, beats.TRAIN_DEPART
    desk.add(J.butter(J.noise(desk.n), 'band', [60, 380]), 0.0, 0.18, hall=0.1)
    arriving = np.clip((t - a0) / (a1 - a0), 0, 1)
    leaving = np.clip((t - d0) / (d1 - d0), 0, 1)
    roar = np.where(t < a0, 0.6 * (t / a0) ** 1.5, 0.0)
    roar += np.where((t >= a0) & (t < a1), 0.3 + 0.7 * (1 - arriving), 0.0)
    roar += np.where((t >= a1) & (t < d0), 0.12, 0.0)
    roar += np.where((t >= d0) & (t < d1), 0.25 + 0.75 * leaving, 0.0)
    roar += np.where(t >= d1, np.clip(1 - (t - d1) / 0.9, 0, 1), 0.0)
    noise = J.butter(J.noise(desk.n), 'low', 520) + 0.4 * J.butter(J.noise(desk.n), 'band', [520, 1600])
    right = np.where(t < d0, 1 - 0.7 * arriving, 0.0)                 # in from the right, out to the left
    desk.add(noise * roar * right, 0.0, 0.9, 0.75, hall=0.15, room=0.3)
    desk.add(noise * roar * (1 - right), 0.0, 0.9, -0.75, hall=0.15, room=0.3)
    f = np.where(t < a1, 1100 * (300 / 1100) ** arriving, 300 * (1350 / 300) ** leaving)
    whine_level = (np.where(t < a0, 0.3 * t / a0, 0.0) + np.where((t >= a0) & (t < a1), 0.3 + 0.5 * (1 - arriving), 0.0)
                   + np.where((t >= d0) & (t < d1), 0.2 + 0.6 * leaving, 0.0)
                   + np.where(t >= d1, 0.8 * np.clip(1 - (t - d1) / 0.7, 0, 1), 0.0))
    phase = 2 * np.pi * np.cumsum(f) / SR
    whine = (np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.15 * np.sin(3 * phase)) * whine_level
    desk.add(whine * right, 0.0, 0.11, 0.6, hall=0.2)
    desk.add(whine * (1 - right), 0.0, 0.11, -0.6, hall=0.2)
    for when, joint, speed in beats.clacks():
        desk.add(clack(float(np.clip(speed / 2600, 0.25, 1.0))), when, 0.5, joint / 640 - 1, hall=0.05, room=0.3)
    desk.add(squeal(0.62), a1 - 0.62, 0.05, 0.2, hall=0.2)
    desk.add(hiss(0.8), a1 + 0.02, 0.22, 0.1, hall=0.15)
    for when, note in zip(at_logo(2.5), OPEN):                       # the door chime: the open logo
        desk.add(chime(note), when, 0.4, -0.1, hall=0.3)
    desk.add(slide(0.35), 2.55, 0.35, hall=0.1, room=0.3)
    desk.add(boing(0.5, 0.7), 3.05, 0.4, hall=0.1)                   # the emblem hops off
    desk.add(J.tom(45, 0.7), 3.55, 0.45, room=0.3)
    go_go(desk, 3.0, 6.5, 36)
    for when, note in zip(at_logo(6.5), CLOSED):                     # and the closed logo as the doors close
        desk.add(chime(note, 2.0 if note == CLOSED[-1] else 1.6), when, 0.42, -0.1, hall=0.3)
    desk.add(slide(0.35), 6.75, 0.35, hall=0.1, room=0.3)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 1.6, 0.4, 0.8), 7.5, 0.1, hall=0.35)
    for note in (62, 66, 69, 73):
        desk.add(J.epiano(note, 1.2, 0.6), 7.5, 0.07, 0.2, hall=0.25)
    go_go(desk, 7.5, 9.0, 38, gain=0.7)
    for i, note in enumerate((74, 78, 81, 86)):                      # the sign lights up
        desk.add(J.bell(note + 12, 1.6, 0.6), 8.5 + i * 0.05, 0.08, -0.3 + 0.2 * i, hall=0.45)
    return mixdown(desk, voice, length, end, grit=0.5)


def strum(desk, chord, when, up=False, gain=1.0, vel=0.7):
    for i, note in enumerate(reversed(chord) if up else chord):
        desk.add(pizz(note, vel * (0.85 if up else 1.0), 0.5), when + i * 0.012, 0.16 * gain, -0.2 + 0.12 * i, hall=0.18)


def dupont(voice):
    """A summer afternoon: the fountain, sparrows, a ukulele strumming under it, the open
    logo plinked into the water, a chess piece, a pigeon's coo; the closed logo on vibes and
    plinks as the jet climbs and the pigeons take off, D major, bells."""
    length, end = 10.0, 9.55
    desk = S.Desk(length)
    desk.add(water(length, 1.0), 0.0, 0.08, 0.0, hall=0.2)
    desk.add(J.butter(J.noise(desk.n), 'low', 180), 0.0, 0.05, hall=0.05)
    birds = np.random.default_rng(1871)
    for when in sorted(birds.uniform(0.3, 9.0, 9)):
        desk.add(chirp(birds), float(when), 0.06, float(birds.uniform(-0.8, 0.8)), hall=0.3)
    chords = (((67, 60, 64, 72), 0.5, 2.5), ((69, 60, 64, 69), 2.5, 4.5), ((69, 60, 65, 69), 4.5, 6.5),
              ((67, 62, 67, 71), 6.5, 7.0), ((69, 62, 66, 69), 7.0, 9.0))
    for chord, a, b in chords:                                        # D DU UDU, in eighths
        for eighth, up in ((0, False), (2, False), (3, True), (5, True), (6, False), (7, True)):
            when = a + eighth * BEAT / 2
            if when < b:
                strum(desk, chord, when, up)
        root = chord[1] - 24
        for beat_, interval in ((0, 0), (2, 7)):
            if a + beat_ * BEAT < b:
                desk.add(pizz(root + interval, 0.9, 0.6), a + beat_ * BEAT, 0.4, -0.1, hall=0.15)
    for k in range(34):
        desk.add(shaker(0.8 if k % 2 else 0.5), 0.5 + k * BEAT / 2, 0.5, 0.35, hall=0.05)
    for when, note in zip(at_logo(1.0), OPEN):                       # the jet's open logo
        desk.add(plink(note), when, 0.32, 0.0, hall=0.4)
        desk.add(J.bell(note + 12, 1.0, 0.4), when, 0.05, 0.2, hall=0.4)
        desk.add(splash(0.5), when, 0.06, hall=0.2)
    desk.add(glide(500, 900, 0.3), 2.6, 0.06, -0.6, hall=0.1)        # the knight's hop, and its click
    desk.add(click(), 2.95, 0.35, -0.6, hall=0.05, room=0.3)
    desk.add(coo(), 1.3, 0.22, 0.5, hall=0.1)
    desk.add(coo(), 5.9, 0.18, -0.3, hall=0.1)
    for when, note in zip(at_logo(7.0), CLOSED):                     # the closed logo: the jet climbs
        desk.add(plink(note), when, 0.32, 0.0, hall=0.4)
        desk.add(vibes(note, 2.0, 0.9), when, 0.3, -0.2, hall=0.35)
        desk.add(J.bell(note + 12, 1.6, 0.5), when, 0.08, 0.25, hall=0.45)
        desk.add(splash(0.8), when, 0.1, hall=0.2)
    for i in range(6):                                                # the pigeons take off
        desk.add(flutter(1.2, 10 + i), 7.0 + 0.07 * i, 0.16, -0.7 + 0.28 * i, hall=0.1)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.3, 1.0), 7.0, 0.08, hall=0.4)
    strum(desk, (69, 62, 66, 69), 9.0, gain=1.2)
    for i, note in enumerate((86, 90, 93, 98)):
        desk.add(J.bell(note, 1.2, 0.5), 9.0 + i * 0.05, 0.06, -0.3 + 0.2 * i, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.4)


MERIDIAN_PAN = (-0.78, -0.43, -0.14, 0.14, 0.43, 0.78)


def drum_hit(drum, vel, together):
    kind = beats.DRUMS[drum]
    if kind == 'conga':
        return conga(53 if drum == 1 else 58, vel)
    if drum == 0 or (drum == 5 and (vel > 0.9 or together)):
        return djembe('bass', vel)
    if drum == 2 and vel > 0.9:
        return djembe('slap', vel)
    return djembe('tone', vel)


def meridian_hill(voice):
    """The drum circle: a roll as the cascade fills, the open logo's clap on every drum with
    the steel pan, a groove with shakers and bass under the voice, the closed logo all
    together, the lift to D, the last hit, a whistle and a cheer. The water throughout."""
    length, end = 10.0, 9.55
    desk = S.Desk(length)
    t = J.times(desk.n)
    fills = beats.fill_times()
    flow = np.clip((t - fills[0]) / (fills[-1] - fills[0] + 0.3), 0, 1)
    desk.add(J.butter(J.noise(desk.n), 'band', [300, 6000]) * (0.3 + 0.7 * flow), 0.0, 0.11, hall=0.25)
    desk.add(S.crowd(length), 0.0, 0.07, hall=0.2)
    for at, drum, hand, vel in beats.meridian_hits():
        together = hand == beats.BOTH
        desk.add(drum_hit(drum, vel, together), at, (0.62 if together else 0.5) * vel, MERIDIAN_PAN[drum],
                 hall=0.12, room=0.35)
    for a, b in (beats.GROOVE, beats.TAIL):
        k = 0
        while a + k * BEAT / 4 < b - 1e-9:
            desk.add(shaker(1.0 if k % 2 else 0.55), a + k * BEAT / 4, 0.45, 0.5, hall=0.05)
            k += 1
    for start, stop, root in ((3.5, 5.5, 36), (5.5, 6.75, 41)):       # a bass, low under the voice
        k = 0
        while start + k * BEAT < stop - 1e-9:
            when = start + k * BEAT
            desk.add(J.bass(root + (0, 7, 12, 7)[k % 4], 0.35, 0.7), when, 0.35)
            k += 1
    for start, notes in ((beats.CLAP, OPEN), (beats.CLOSED, CLOSED)):  # the steel pan carries the logo
        for when, note in zip(at_logo(start), notes):
            desk.add(steelpan(note), when, 0.3, 0.15, hall=0.3)
            desk.add(steelpan(note - 4 if note % 12 != 2 else note - 5, 0.6), when, 0.18, -0.2, hall=0.3)
    for when, chord in ((3.5, (60, 64, 67)), (4.5, (60, 64, 69)), (5.5, (60, 65, 69)), (6.25, (62, 65, 71))):
        for note in chord:
            desk.add(steelpan(note, 0.45, 0.9), when, 0.1, 0.3, hall=0.3)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.3, 1.0), beats.CLOSED, 0.08, hall=0.4)
    desk.add(whistle(0.8), beats.BUTTON + 0.08, 0.1, 0.5, hall=0.25)
    desk.add(S.crowd(1.0, swell=(0.0, 0.3)), beats.BUTTON, 0.1, hall=0.2)
    return mixdown(desk, voice, length, end, grit=0.4)


def now_in_hd(voice):
    """2006: a shimmering pad and a sparkle for the light streak, a swish as the panel turns,
    the sub drop and the open logo on glass as it powers on, then a snap beat (808s, finger
    snaps on two and four, ticking hats, a sub bass) under the promo voice; bubbles for the
    pill and the starburst, a reverse cymbal into the lift, the closed logo on glass with
    an 'ooh', a twinkle as the swirls grow."""
    length, end = 10.0, 9.55
    desk = S.Desk(length)
    desk.wide(lambda: J.pad_voice((60, 64, 67, 71, 74, 79), 2.4, 1.4, 0.8), 0.0, 0.15, hall=0.5)
    for i, note in enumerate((84, 88, 91, 95, 98, 100)):              # the light streak's sparkle
        desk.add(glass(note, 1.2, 0.6), 0.3 + i * 0.05, 0.06, -0.7 + 0.28 * i, hall=0.5)
    desk.add(J.riser(0.7, 9000), 0.3, 0.2, 0.3, hall=0.3)
    desk.add(J.whoosh(1.2), 0.6, 0.2, -0.2, hall=0.3)
    desk.add(sub(36, 0.8, 1.0, glide_from=48), 2.0, 0.4)              # power on
    desk.add(glass(96, 1.5, 0.7), 2.0, 0.06, 0.3, hall=0.5)
    for when, note in zip(at_logo(2.0), OPEN):
        desk.add(glass(note, 2.0, 0.9), when, 0.22, -0.1, hall=0.4)
    bars = ((2.0, 36, (60, 64, 67, 71, 74)), (4.0, 33, (57, 60, 64, 67, 71)), (6.0, 29, (53, 57, 60, 64, 67)),
            (7.0, 38, (62, 66, 69, 73, 76)))
    for i, (start, root, chord) in enumerate(bars):
        stop = bars[i + 1][0] if i + 1 < len(bars) else 9.0
        desk.wide(lambda c=chord, g=stop - start: J.pad_voice(c, g, 0.15, 0.5), start, 0.06, hall=0.35)
        for offset in (0.0, 0.75, 1.25):
            if start + offset < stop:
                desk.add(kick808(1.0), start + offset, 0.7)
                desk.add(sub(root, 0.4 if offset else 0.6, 0.9), start + offset, 0.3)
        for offset in (0.5, 1.5):
            if start + offset < stop:
                desk.add(snap(1.0), start + offset, 0.55, 0.15, hall=0.12, room=0.6)
                desk.add(J.clap(0.5), start + offset, 0.12, -0.1, room=0.5)
        k = 0
        while start + k * BEAT / 2 < stop - 1e-9:
            desk.add(J.hat(0.35 if k % 2 else 0.5), start + k * BEAT / 2, 0.25, 0.4, hall=0.03)
            k += 1
    for i, note in enumerate((96, 100, 103, 108)):                    # the shine across the wordmark
        desk.add(glass(note, 0.9, 0.5), 3.0 + i * 0.06, 0.05, -0.2 + 0.2 * i, hall=0.5)
    desk.add(pop(1.0), 4.5, 0.25, 0.4, hall=0.15)                     # the pill
    desk.add(glass(91, 1.0, 0.6), 4.55, 0.07, 0.4, hall=0.4)
    desk.add(pop(1.0), 5.0, 0.25, -0.2, hall=0.15)                    # the starburst
    desk.add(boing(0.4, 0.5), 5.0, 0.12, -0.2, hall=0.1)
    reverse = J.crash(1.0, 1.2)[::-1]
    desk.add(reverse, 7.0 - len(reverse) / SR, 0.25, hall=0.2)
    desk.add(J.whoosh(1.1), 7.0, 0.1, 0.4, hall=0.3)
    for when, note in zip(at_logo(7.0), CLOSED):
        desk.add(glass(note, 2.2, 1.0), when, 0.24, -0.1, hall=0.45)
        desk.add(J.choir(note - 12, 0.4, 0.8), when, 0.1, 0.3, hall=0.5)
    for i, note in enumerate((86, 90, 93, 98, 102, 105, 110)):        # the swirls grow
        desk.add(glass(note, 0.8, 0.4), 7.4 + i * 0.11, 0.035, -0.6 + 0.2 * i, hall=0.55)
    desk.add(kick808(1.0), 9.0, 0.6)
    desk.add(snap(1.0), 9.0, 0.4, room=0.6)
    for i, note in enumerate((74, 78, 81, 86)):
        desk.add(glass(note, 1.0, 0.7), 9.0 + i * 0.03, 0.1, -0.3 + 0.2 * i, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.0)


# ---------------------------------------------------------------- Orange Cat Behavior

def beep(midi, length=0.09, vel=1.0):
    """A remote control's beep: a pure tone, a hard start, a quick end."""
    n = int(length * SR)
    t = J.times(n)
    x = np.sin(2 * np.pi * float(J.hz(midi)) * t) + 0.2 * np.sin(6 * np.pi * float(J.hz(midi)) * t)
    return x * np.clip(t / 0.002, 0, 1) * np.clip((length - t) / 0.01, 0, 1) * vel * 0.5


def purr(length, vel=1.0):
    """A purr: a low rattle at 25 a second, breathing in and out."""
    n = int(length * SR)
    t = J.times(n)
    rattle = 0.5 + 0.5 * np.sin(2 * np.pi * 25 * t)
    breath = 0.55 + 0.45 * np.abs(np.sin(np.pi * 0.8 * t))
    x = J.butter(J.noise(n), 'band', [60, 420]) * rattle ** 2 * breath
    return x * np.clip(t / 0.3, 0, 1) * np.clip((length - t) / 0.4, 0, 1) * vel


def poof(vel=1.0):
    """Landing on a cushion: a soft thump and a sigh of air."""
    n = int(0.4 * SR)
    t = J.times(n)
    thump = np.sin(2 * np.pi * np.cumsum(70 + 40 * np.exp(-t / 0.02)) / SR) * np.exp(-t / 0.08)
    air = J.butter(J.noise(n), 'band', [300, 2500]) * np.exp(-t / 0.12) * 0.4
    return (thump + air) * vel


def tiptoe(desk, start, stop, notes=(48, 55, 52, 55), step=0.25, gain=0.35):
    """The documentary's sneaking pizzicato: a low walk on the eighths."""
    k = 0
    while start + k * step < stop - 1e-9:
        desk.add(pizz(notes[k % len(notes)], 0.8), start + k * step, gain, -0.15 + 0.1 * (k % 2), hall=0.25)
        k += 1


def cat_remote(voice):
    """The nature documentary: a hushed string pad and a sneaking pizzicato; a slide whistle
    and a cushion's poof for the hop. Each press of Channel Up beeps a note of the open
    logo, with vibes, a CRT's thunk and the channels' noise between them; a sparkle for
    VizelVision, a purr, the closed logo with a soft choir, a mrrp and a harp of bells."""
    P = hits('cat-remote')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.wide(lambda: J.pad_voice((48, 55, 64, 71), 3.0, 1.0, 1.0), 0.0, 0.06, hall=0.4)
    tiptoe(desk, 0.25, 1.9)
    for (when, look), note in zip(P.LOOKS, (88, 84, 88)):          # its glances
        desk.add(vibes(note, 0.8, 0.6), when, 0.1, 0.3, hall=0.35)
    desk.add(glide(520, 980, 0.35), P.HOP[0], 0.25, -0.1, hall=0.2)
    desk.add(poof(1.0), P.HOP[1], 0.6, hall=0.1)
    desk.wide(lambda: J.pad_voice((50, 57, 62, 69), 1.5, 0.4, 0.8), 2.5, 0.05, hall=0.4)
    for when, note in zip(P.PRESSES, OPEN):                          # Channel Up on the open logo
        desk.add(beep(note + 12, 0.1, 1.0), when, 0.35, 0.35, hall=0.15)
        desk.add(vibes(note, 1.6, 0.9), when, 0.3, -0.2, hall=0.35)
        desk.add(J.tom(40, 0.5), when, 0.25, 0.4, room=0.3)       # the set's thunk
    for start, stop in ((P.PRESSES[0], P.PRESSES[1]), (P.PRESSES[2], P.PRESSES[3])):
        desk.add(J.static_burst(stop - start)[:int((stop - start) * SR)], start + 0.04, 0.12, 0.4, hall=0.05)
    for i, note in enumerate((84, 88)):                              # the shopping channel's ding-dong
        desk.add(J.bell(note, 0.5, 0.6), P.PRESSES[1] + 0.06 + i * 0.1, 0.08, 0.4, hall=0.2)
    for i, note in enumerate((79, 84, 88, 91, 96)):                 # VizelVision: a sparkle
        desk.add(J.bell(note, 1.2, 0.6), P.PRESSES[3] + 0.05 + i * 0.05, 0.08, 0.2 + 0.1 * i, hall=0.5)
    desk.add(purr(P.PLEASED[1] - P.PLEASED[0] + 2.4), P.PLEASED[0], 0.35, -0.1, hall=0.05)
    desk.wide(lambda: J.pad_voice((48, 55, 64, 67), 2.6, 0.6, 0.8), 4.2, 0.05, hall=0.4)
    tiptoe(desk, 4.5, 6.9, notes=(48, 52, 55, 52), step=0.5, gain=0.25)
    S.logo(desk, P.BANNER, CLOSED, organ_=False, choir=True, gain=0.85)
    for when, note in zip(at_logo(P.BANNER), CLOSED):
        desk.add(vibes(note, 2.0, 0.8), when, 0.25, -0.2, hall=0.35)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.3, 1.2), P.BANNER, 0.07, hall=0.4)
    desk.add(meow(), P.MRRP, 0.5, -0.1, hall=0.15)
    for i, note in enumerate((74, 78, 81, 86, 90, 93)):
        desk.add(J.bell(note, 1.6, 0.55), P.BLINK[0] + i * 0.05, 0.07, -0.4 + 0.15 * i, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.5)


def laser(path_x, length, vel=1.0):
    """The pointer writing: a thin sine whine with a fast shimmer, gliding with the dot."""
    n = int(length * SR)
    t = J.times(n)
    f = 1500 + 900 * np.interp(t, np.linspace(0, length, len(path_x)), path_x)
    x = np.sin(2 * np.pi * np.cumsum(f * (1 + 0.01 * np.sin(2 * np.pi * 31 * t))) / SR)
    return x * np.clip(t / 0.05, 0, 1) * np.clip((length - t) / 0.08, 0, 1) * vel * 0.25


def cat_laser(voice):
    """The documentary, at dusk: a sneaking pizzicato and a vibes note for each of the dot's
    darts; a timpani roll under the crouch, the open logo on marimba for the four wiggles,
    a slide whistle for the pounce and a thud; a ting for the dot on its head and a
    question; a zip up the wall; the laser's whine writing the wordmark on the closed logo,
    sung, a shimmer, a mrrp, a harp of bells."""
    P = hits('cat-laser')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.wide(lambda: J.pad_voice((45, 52, 60, 67), 2.8, 1.0, 1.0), 0.0, 0.06, hall=0.4)
    tiptoe(desk, 0.25, 2.7, notes=(45, 52, 48, 52))
    pentatonic = (84, 86, 88, 91, 93, 96)
    for k, (when, x, _) in enumerate(P.DARTS):                       # each dart lands
        desk.add(vibes(pentatonic[(k * 4) % len(pentatonic)], 0.6, 0.55), when, 0.1, x / 640 - 1, hall=0.3)
        desk.add(glide(900 + 60 * k, 1500 + 40 * k, 0.12), when - 0.12, 0.05, x / 640 - 1, hall=0.1)
    for k in range(24):                                              # the crouch: a soft roll, building
        when = P.CROUCH + k * (P.POUNCE[0] - P.CROUCH) / 24
        desk.add(J.timpani(40, 0.15 + 0.35 * k / 24), when, 0.25, hall=0.3)
    for when, note in zip(P.WIGGLES, OPEN):                          # the open logo: a wiggle each
        desk.add(J.marimba(note, 1.0), when, 0.3, -0.2, hall=0.3)
        desk.add(J.marimba(note - 12, 0.8), when, 0.2, 0.2, hall=0.25)
        desk.add(shaker(1.0), when, 0.5, 0.3)
        desk.add(shaker(0.7), when + 0.11, 0.4, -0.3)
    desk.add(glide(380, 1500, P.POUNCE[1] - P.POUNCE[0]), P.POUNCE[0], 0.35, 0.2, hall=0.2)
    desk.add(J.kick(0.8), P.POUNCE[1], 0.6)
    desk.add(poof(1.0), P.POUNCE[1], 0.5, 0.3)
    desk.add(J.crash(0.6, 1.2), P.POUNCE[1], 0.15, 0.4, hall=0.2)
    desk.add(J.bell(98, 1.0, 0.7), P.ON_HEAD, 0.12, 0.3, hall=0.4)  # ting: the dot, on its head
    desk.add(glide(620, 880, 0.3), P.PUZZLED, 0.25, 0.4, hall=0.2)   # ?
    tiptoe(desk, 5.4, 6.4, notes=(45, 44, 43, 42), step=0.25, gain=0.25)
    desk.add(glide(300, 2200, P.CLIMB[1] - P.CLIMB[0]), P.CLIMB[0], 0.18, -0.2, hall=0.25)
    letters = 11                                                     # the dot runs round each letter in turn
    track = [(P.WORD_X + P.WORD_W * (k / 200) + 30 * np.sin(np.pi * letters * k / 200)) / 1280 for k in range(201)]
    desk.add(laser(track, P.WRITE[1] - P.WRITE[0]), P.WRITE[0], 0.3, 0.0, hall=0.3)
    S.logo(desk, P.WRITE[0], CLOSED, organ_=False, choir=True, gain=0.85)
    for when, note in zip(at_logo(P.WRITE[0]), CLOSED):
        desk.add(vibes(note, 2.0, 0.8), when, 0.25, -0.2, hall=0.35)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.3, 1.2), P.WRITE[0], 0.07, hall=0.4)
    for i, note in enumerate((86, 90, 93, 98)):                      # the wordmark glows
        desk.add(glass(note, 1.0, 0.5), P.GLOW + i * 0.04, 0.06, -0.3 + 0.2 * i, hall=0.5)
    desk.add(meow(), P.MRRP, 0.5, 0.2, hall=0.15)
    for i, note in enumerate((74, 78, 81, 86, 90, 93)):
        desk.add(J.bell(note, 1.4, 0.5), P.BLINK[0] + i * 0.05, 0.06, -0.4 + 0.15 * i, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.5)


# ---------------------------------------------------------------- the ballpark and the chalkboard

def clunk(vel=1.0):
    """A bank of stadium lights switching on: the contactor's heavy click, a thump, and the
    ballasts' hum starting up."""
    n = int(0.9 * SR)
    t = J.times(n)
    click = J.butter(J.noise(n), 'band', [1500, 7000]) * np.exp(-t / 0.004)
    thump = np.sin(2 * np.pi * np.cumsum(60 + 50 * np.exp(-t / 0.03)) / SR) * np.exp(-t / 0.12)
    hum = (np.sin(2 * np.pi * 120 * t) + 0.4 * np.sin(2 * np.pi * 240 * t)) * np.clip(t / 0.1, 0, 1) * np.exp(-t / 0.5)
    return (0.7 * click + 0.9 * thump + 0.12 * hum) * vel


def crack(vel=1.0):
    """The bat: a sharp woody crack, ringing for a moment."""
    n = int(0.3 * SR)
    t = J.times(n)
    snap_ = J.butter(J.noise(n), 'band', [900, 8000]) * np.exp(-t / 0.006)
    wood = sum(g * np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, g, d in ((640, 0.7, 0.04), (1180, 0.5, 0.025),
                                                                               (2300, 0.3, 0.012)))
    return np.tanh(2.2 * (snap_ + wood)) * vel


def boom(vel=1.0):
    """A firework: the deep burst, then crackle falling away."""
    n = int(1.6 * SR)
    t = J.times(n)
    body = np.sin(2 * np.pi * np.cumsum(45 + 60 * np.exp(-t / 0.05)) / SR) * np.exp(-t / 0.35)
    burst = J.butter(J.noise(n), 'low', 1800) * np.exp(-t / 0.15) * 0.6
    crackle = J.butter(J.noise(n), 'high', 2500) * (rng.random(n) < 0.012) * np.clip((t - 0.25) / 0.2, 0, 1) \
        * np.exp(-t / 0.6) * 3
    return (body + burst + crackle) * vel


def pa(voice):
    """A ballpark PA: the voice through horn speakers, and the stands' slapback echo."""
    horn_ = np.tanh(1.5 * J.butter(voice, 'band', [280, 4200]))
    out = horn_.copy()
    for delay, gain in ((0.23, 0.42), (0.46, 0.2), (0.69, 0.09)):
        k = int(delay * SR)
        out[k:] += J.butter(horn_[:-k], 'band', [400, 2800]) * gain
    return out * 0.9


def baseball(voice):
    """The ballpark at night: the light banks clunking on, the crowd, the organ playing the
    open logo; the PA announcing No. 19 with the stands' echo; the crack of the bat, an
    organ run up as the ball carries, the crowd rising; into the scoreboard on the closed
    logo with the horn and the band's hit, fireworks, the crowd on its feet."""
    P = hits('baseball')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    voice = pa(voice)
    desk.add(S.crowd(length, swell=(P.CONTACT, P.HOME_RUN)), 0.0, 0.22, hall=0.15)
    for k, when in enumerate(P.BANKS_ON):
        desk.add(clunk(1.0), when, 0.45, (-0.7, -0.4, 0.7, 0.4)[k], hall=0.25)
    for (offset, beats_), note in zip(RHYTHM, OPEN):                 # the organ: the open logo
        when, gate = P.ORGAN + offset * BEAT, beats_ * BEAT * 0.92
        desk.add(S.organ(note, gate, 1.0), when, 0.42, -0.2, hall=0.3)
        desk.add(S.organ(note - 12, gate, 0.8), when, 0.25, 0.2, hall=0.3)
    for note in (48, 55, 64, 72):
        desk.add(S.organ(note, 0.9, 0.7), P.ORGAN + 2 * BEAT, 0.12, 0.1, hall=0.35)
    desk.add(S.organ(36, 3.0, 0.5), P.NOW_BATTING, 0.12, hall=0.3)  # a low pedal under the PA
    desk.add(crack(1.0), P.CONTACT, 0.9, -0.1, hall=0.3)
    desk.add(J.whoosh(1.2), P.CONTACT + 0.05, 0.25, 0.1, hall=0.3)
    run = (60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84, 86)
    for k, note in enumerate(run):                                   # the organ, as the ball carries
        desk.add(S.organ(note, 0.1, 0.8), P.FLIGHT[0] + 0.1 + k * 0.085, 0.22, -0.3 + 0.04 * k, hall=0.3)
    desk.add(J.riser(1.3, 8000), P.FLIGHT[0] + 0.15, 0.2, hall=0.3)
    J.hit(desk, 62, P.HOME_RUN, big=True)
    S.logo(desk, P.HOME_RUN, CLOSED, organ_=True, gain=1.0)
    desk.add(S.horn(1.8), P.HOME_RUN, 0.5, hall=0.3)
    desk.add(J.static_burst(0.35), P.HOME_RUN, 0.15, 0.1, hall=0.1)   # the board's lamps, all at once
    for k, when in enumerate(P.FIREWORKS):
        desk.add(boom(1.0), when, 0.5, (-0.6, 0.6, -0.4, 0.4)[k], hall=0.4)
    for note in (50, 57, 62, 66, 69, 74):
        desk.add(S.organ(note, 1.1, 0.8), P.SIGN_OFF, 0.12, -0.2 + 0.08 * (note % 5), hall=0.35)
    desk.add(S.crowd(2.0, claps=S.claps(0.1, 1)), P.SIGN_OFF - 0.2, 0.3, hall=0.15)
    return mixdown(desk, voice, length, end, grit=0.5)


def squeak(length, vel=1.0, seed=0):
    """Chalk squeaking on slate: a high, wavering whistle in fits."""
    n = int(length * SR)
    t = J.times(n)
    local = np.random.default_rng(seed)
    f = 2600 + 500 * np.sin(2 * np.pi * local.uniform(5, 9) * t) + local.normal(0, 60, n).cumsum() / 200
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * J.butter(J.noise(n), 'band', [2000, 7000])
    fits = 0.6 + 0.4 * np.sin(2 * np.pi * local.uniform(11, 17) * t) ** 2
    return x * fits * np.clip(t / 0.01, 0, 1) * np.clip((length - t) / 0.03, 0, 1) * vel * 0.4


def scribble(length, vel=1.0):
    """Chalk writing: scratchy noise in short strokes."""
    n = int(length * SR)
    t = J.times(n)
    strokes = np.clip(np.sin(2 * np.pi * 7.5 * t + 2 * np.sin(2 * np.pi * 2.1 * t)), 0, 1) ** 0.5
    return J.butter(J.noise(n), 'band', [1500, 7500]) * strokes * np.clip((length - t) / 0.03, 0, 1) * vel * 0.5


def tap(vel=1.0):
    """A stick of chalk tapped on the board."""
    n = int(0.05 * SR)
    t = J.times(n)
    return (np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.004) + J.butter(J.noise(n), 'band', [2000, 8000])
            * np.exp(-t / 0.003)) * vel * 0.5


def ref_whistle(length=0.55, vel=1.0):
    """A referee's pea whistle: a shrill tone with the pea's trill."""
    n = int(length * SR)
    t = J.times(n)
    f = 2950 * (1 + 0.025 * np.sin(2 * np.pi * 38 * t))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * (0.7 + 0.3 * np.sin(2 * np.pi * 38 * t))
    x += 0.15 * J.butter(J.noise(n), 'band', [2500, 5000])
    return x * np.clip(t / 0.015, 0, 1) * np.clip((length - t) / 0.05, 0, 1) * vel * 0.5


def drumline(desk, start, stop, gain=1.0):
    """A marching drumline's cadence: snares on sixteenths with accents, the quads answering,
    the bass drums splitting the beat between them."""
    step = 0
    while start + step * BEAT / 4 < stop - 1e-9:
        when, k = start + step * BEAT / 4, step % 16
        accent = k in (0, 3, 6, 8, 12, 14)
        desk.add(J.snare(0.75 if accent else 0.35), when, 0.4 * gain, -0.15, hall=0.1, room=0.4)
        if k in (2, 5, 10, 13):
            desk.add(J.tom((50, 45, 52, 47)[(2, 5, 10, 13).index(k)], 0.7), when, 0.3 * gain, 0.35, hall=0.15)
        if k in (0, 4, 8, 11, 12):
            desk.add(J.tom((33, 36, 38, 40, 31)[(0, 4, 8, 11, 12).index(k)], 1.0), when, 0.45 * gain, 0.0, hall=0.2)
        step += 1


def football(voice):
    """The chalkboard: chalk writing PLAY 19, a tap for each O and X over the drumline, the
    open logo on glockenspiel and brass as each route squeaks on; a snare roll under the
    pass, the whistle and the crowd for TD!; the cadence under the line; the eraser; the
    closed logo with the whole band, the horn and the crowd."""
    P = hits('football')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.add(scribble(P.TITLE[1] - P.TITLE[0]), P.TITLE[0], 0.25, -0.4, hall=0.1)
    desk.add(scribble(0.4, 0.6), 0.3, 0.15, 0.2, hall=0.1)
    for k in range(len(P.O_SPOTS)):
        desk.add(tap(1.0), P.OFFENSE[0] + k * (P.OFFENSE[1] - P.OFFENSE[0]) / len(P.O_SPOTS), 0.5,
                 P.O_SPOTS[k][0] / 640 - 1, hall=0.1)
    for k in range(len(P.X_SPOTS)):
        desk.add(tap(0.9), P.DEFENSE[0] + k * (P.DEFENSE[1] - P.DEFENSE[0]) / len(P.X_SPOTS), 0.5,
                 P.X_SPOTS[k][0] / 640 - 1, hall=0.1)
    drumline(desk, 0.5, 2.0, gain=0.7)
    for k, (when, note) in enumerate(zip(P.ROUTES, OPEN)):           # the open logo: a route each
        desk.add(squeak(P.ROUTE_DRAW + 0.05, 1.0, seed=k), when, 0.12, P.ROUTE_POINTS[k][2][0] / 640 - 1, hall=0.1)
        desk.add(J.bell(note + 12, 1.6, 0.9), when, 0.25, -0.2, hall=0.35)
        for i, n in enumerate((note - 24, note - 12, note - 5)):
            desk.add(J.brass(n, 0.2 if note != OPEN[-1] else 0.8, 0.95), when, 0.1, -0.4 + 0.4 * i, hall=0.25)
        desk.add(J.tom(33, 1.0), when, 0.45, hall=0.2)
    for k in range(16):                                              # the pass: a roll, building
        desk.add(J.snare(0.25 + 0.6 * k / 16), P.PASS[0] - 0.2 + k * (P.TD - P.PASS[0] + 0.2) / 16, 0.45,
                 hall=0.1, room=0.4)
    desk.add(J.whoosh(P.PASS[1] - P.PASS[0]), P.PASS[0], 0.2, -0.3, hall=0.25)
    desk.add(ref_whistle(), P.TD, 0.35, 0.3, hall=0.3)
    desk.add(J.crash(1.0, 2.0), P.TD, 0.3, 0.2, hall=0.25)
    desk.add(S.crowd(3.0, swell=(0.0, 0.3)), P.TD, 0.25, hall=0.15)
    desk.add(scribble(P.CIRCLE[1] - P.CIRCLE[0]), P.CIRCLE[0], 0.2, -0.2, hall=0.1)
    drumline(desk, 4.5, 6.5, gain=0.45)
    n = int((P.ERASE[1] - P.ERASE[0]) * SR)
    rub = J.butter(J.noise(n), 'band', [200, 2500]) * np.abs(np.sin(np.pi * 9 * J.times(n)))
    desk.add(rub, P.ERASE[0], 0.3, hall=0.1)
    for k in range(8):
        desk.add(J.snare(0.4 + 0.07 * k), P.ERASE[0] + k * 0.0625, 0.4, hall=0.1, room=0.4)
    J.hit(desk, 62, P.WORDMARK, big=True)
    S.logo(desk, P.WORDMARK, CLOSED, organ_=False, gain=1.1)
    for when, note in zip(at_logo(P.WORDMARK), CLOSED):
        for i, n in enumerate((note - 24, note - 12, note - 5)):
            desk.add(J.brass(n, 0.3, 1.0), when, 0.12, -0.4 + 0.4 * i, hall=0.25)
    desk.add(S.horn(1.6), P.WORDMARK, 0.45, hall=0.3)
    drumline(desk, P.WORDMARK, 9.0)
    desk.add(scribble(P.FOOTBALL[1] - P.FOOTBALL[0]), P.FOOTBALL[0], 0.15, 0.2, hall=0.1)
    desk.add(S.crowd(2.5, swell=(0.0, 0.4)), P.WORDMARK, 0.25, hall=0.15)
    J.hit(desk, 62, 9.0)
    return mixdown(desk, voice, length, end, grit=0.5)


# ---------------------------------------------------------------- the decades

def pew(f0=2400, f1=180, length=0.35, vel=1.0):
    """A laser: a square wave diving in pitch, with a sine underneath."""
    n = int(length * SR)
    t = J.times(n)
    f = f0 * (f1 / f0) ** (t / length)
    phase = np.cumsum(f) / SR
    x = 0.5 * np.where(phase % 1 < 0.5, 1.0, -1.0) + np.sin(2 * np.pi * phase)
    return J.butter(x, 'low', 6000) * np.exp(-t / (length / 2.5)) * vel * 0.35


def buzz(length, vel=1.0):
    """A neon tube striking: mains hum with crackle, settling."""
    n = int(length * SR)
    t = J.times(n)
    hum = np.sign(np.sin(2 * np.pi * 120 * t)) * 0.3 + np.sin(2 * np.pi * 240 * t) * 0.2
    crackle = J.butter(J.noise(n), 'high', 3000) * (rng.random(n) < 0.02) * np.exp(-t / 0.25) * 2
    return J.butter(hum, 'low', 2000) * np.exp(-t / 0.6) * vel + crackle * vel


def eighties_groove(desk, start, stop, root, chord, gain=1.0):
    """A 1986 pop groove: kick on one and three, the gated snare on two and four, eighth-note
    synth bass bouncing its octave, sixteenth hats, FM bells on the offbeats."""
    k = 0
    while start + k * BEAT / 2 < stop - 1e-9:
        when = start + k * BEAT / 2
        if k % 4 == 0:
            desk.add(J.kick(1.0), when, 0.8 * gain, hall=0.02)
        if k % 4 == 2:
            desk.add(J.snare(1.0), when, 0.5 * gain, 0.05, hall=0.05, room=1.2)
        desk.add(J.bass(root + (12 if k % 2 else 0), 0.2, 0.9), when, 0.45 * gain)
        for s in (0, 0.25):
            desk.add(J.hat(0.4 if s else 0.55), when + s * BEAT, 0.22 * gain, 0.35, hall=0.03)
        if k % 2:
            desk.add(J.bell(chord[k % len(chord)] + 12, 0.8, 0.45), when, 0.07 * gain, -0.3, hall=0.3)
        k += 1


def eighty_six(voice):
    """1986: a pad swelling with the sun and an FM-bell arpeggio; the open logo as four
    lasers, each a zap and a synth-brass stab; a whoosh, gated toms and a reversed cymbal
    into the chrome's orchestra hit; the groove under the promo voice, a neon buzz, the
    closed logo on bells, brass and choir, and the last hit."""
    P = hits('eighty-six')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.wide(lambda: J.pad_voice((48, 55, 60, 64, 67), 2.2, 1.0, 0.6), 0.0, 0.12, hall=0.5)
    for k in range(8):                                               # the sun rises: an arpeggio
        desk.add(J.bell((72, 76, 79, 84, 88, 84, 79, 76)[k], 1.0, 0.55), 0.1 + k * 0.11, 0.08, -0.5 + 0.13 * k, hall=0.45)
    desk.add(J.riser(0.9, 7000), 0.1, 0.15, hall=0.3)
    for k, (when, note) in enumerate(zip(P.LASERS, OPEN)):           # the open logo: the lasers
        desk.add(pew(2600 - 200 * k, 160, 0.4), when, 0.5, (-0.6, 0.6, -0.3, 0.3)[k], hall=0.3)
        desk.add(J.bell(note, 1.8, 0.9), when, 0.25, -0.15, hall=0.4)
        for i, n in enumerate((note - 12, note - 5, note)):
            desk.add(J.brass(n, 0.18 if note != OPEN[-1] else 0.7, 0.95), when, 0.1, -0.4 + 0.4 * i, hall=0.3)
    desk.add(J.whoosh(1.0), P.FLY[0], 0.3, -0.3, hall=0.3)
    for k, note in enumerate((45, 43, 40, 38, 36, 33)):              # gated toms into the hit
        desk.add(J.tom(note, 1.0), P.FLY[0] + 0.45 + k * 0.09, 0.5, -0.5 + 0.2 * k, hall=0.05, room=1.0)
    reverse = J.crash(1.0, 1.0)[::-1]
    desk.add(reverse, P.CHROME - len(reverse) / SR, 0.35, hall=0.2)
    J.hit(desk, 60, P.CHROME, big=True)
    for start, stop, root, chord in ((P.CHROME, 5.0, 36, (60, 64, 67, 72)), (5.0, 6.0, 33, (57, 60, 64, 69)),
                                     (6.0, P.LIFT - 0.5, 29, (53, 57, 60, 65))):
        eighties_groove(desk, start, stop, root, chord, gain=0.85)
        desk.wide(lambda c=chord, g=stop - start: J.pad_voice(c, g, 0.05, 0.4), start, 0.06, hall=0.4)
    desk.add(pew(1800, 600, 0.3, 0.7), P.TAGLINE[0], 0.25, 0.4, hall=0.3)
    desk.add(buzz(0.9), P.NEON, 0.25, 0.6, hall=0.1)
    for k, note in enumerate((43, 41, 40, 38)):                      # a fill into the lift
        desk.add(J.tom(note, 1.0), P.LIFT - 0.5 + k * 0.125, 0.5, -0.4 + 0.25 * k, room=1.0)
    J.hit(desk, 62, P.LIFT, big=True)
    S.logo(desk, P.LIFT, CLOSED, organ_=False, choir=True, gain=1.0)
    eighties_groove(desk, P.LIFT + 0.0, 9.0, 38, (62, 66, 69, 74), gain=0.7)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.1, 0.8), P.LIFT, 0.07, hall=0.45)
    J.hit(desk, 62, 9.0, big=True)
    return mixdown(desk, voice, length, end, grit=0.7)


def fife(midi, gate, vel=1.0):
    """A fife: a breathy, nearly pure tone with a late vibrato."""
    n = int((gate + 0.06) * SR)
    t = J.times(n)
    f = float(J.hz(midi)) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.12) / 0.2, 0, 1))
    phase = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(phase) + 0.18 * np.sin(2 * phase) + 0.08 * np.sin(3 * phase)
    x += 0.12 * J.butter(J.noise(n), 'band', [float(J.hz(midi)) * 0.8, float(J.hz(midi)) * 3])
    return x * np.clip(t / 0.025, 0, 1) * np.clip((gate + 0.06 - t) / 0.06, 0, 1) * vel * 0.5


def field_roll(desk, start, length, v0=0.3, v1=0.9, gain=0.45):
    """A field drum's roll: thirty-second notes, swelling."""
    count = int(length / (BEAT / 8))
    for k in range(count):
        vel = v0 + (v1 - v0) * k / max(1, count - 1)
        desk.add(J.snare(vel * (0.85 + 0.15 * (k % 2))), start + k * BEAT / 8, gain, rng.uniform(-0.15, 0.15),
                 hall=0.15, room=0.3)


def seventy_six(voice):
    """1976: a synth sweep through the slit-scan; the fife and drum play the open logo as the
    fireworks burst; strings sweep with the ribbon into a brass fanfare; a seventies TV
    groove (wah guitar, funky bass, brass stabs, strings) under the announcer; the closed
    logo with the whole band, the fife on top, the finale's booms."""
    P = hits('seventy-six')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.add(J.riser(0.9, 6000)[::-1] * 0.8, 0.0, 0.25, hall=0.3)
    desk.wide(lambda: J.pad_voice((60, 64, 67, 72), 1.0, 0.3, 0.6), 0.0, 0.06, hall=0.4)
    for k, (when, note) in enumerate(zip(P.BURSTS, OPEN)):            # the open logo: fife, drum, a burst each
        gate = (RHYTHM[k][1] * BEAT) * 0.92
        desk.add(fife(note + 12, gate, 1.0), when, 0.35, -0.2, hall=0.35)
        desk.add(J.timpani(36, 0.7), when, 0.35, hall=0.3)
        desk.add(boom(0.8), when + 0.12, 0.3, (-0.4, 0.4, 0.0, 0.5)[k], hall=0.4)
    field_roll(desk, 0.9, 0.1, 0.2, 0.5)
    for k in range(6):                                                # the drum between the notes
        desk.add(J.snare(0.6 if k % 3 == 0 else 0.35), 1.0 + k * BEAT / 4, 0.35, -0.1, hall=0.15, room=0.3)
    field_roll(desk, 2.0, 0.4, 0.2, 0.8)
    desk.wide(lambda: J.pad_voice((60, 64, 67, 72, 76), 1.0, 0.6, 0.6), P.RIBBON[0], 0.1, hall=0.45)
    for k in range(12):                                               # strings sweep up with the ribbon
        desk.add(J.epiano(60 + (0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19)[k], 0.2, 0.4), P.RIBBON[0] + k * 0.05,
                 0.05, -0.4 + 0.07 * k, hall=0.4)
    for i, note in enumerate((48, 55, 60, 64, 67, 72)):              # the fanfare as the wordmark rides in
        desk.add(J.brass(note, 0.6, 1.0), 3.0, 0.11, -0.5 + 0.2 * i, hall=0.3)
    desk.add(J.timpani(36, 1.0), 3.0, 0.5, hall=0.3)
    desk.add(J.crash(0.9, 2.0), 3.0, 0.3, 0.3, hall=0.3)
    for start, stop, root, chord in ((3.5, 5.0, 36, (60, 64, 67, 71)), (5.0, 6.0, 41, (57, 60, 65, 69)),
                                     (6.0, 6.75, 43, (55, 59, 62, 65))):
        k = 0
        while start + k * BEAT / 4 < stop - 1e-9:                     # the seventies TV groove
            when, step = start + k * BEAT / 4, k % 8
            if step in (0, 3, 6):
                desk.add(J.bass(root + (0, 12, 7)[(0, 3, 6).index(step)], 0.16, 0.85), when, 0.45)
            if step == 0:
                desk.add(J.kick(0.9), when, 0.6)
            if step == 4:
                desk.add(J.snare(0.8), when, 0.35, 0.05, hall=0.1)
            desk.add(J.hat(0.35 if step % 2 else 0.5), when, 0.2, 0.35, hall=0.03)
            if step in (2, 6):                                        # the wah guitar's scratch
                wah = J.sweep(J.saw(float(J.hz(chord[0])), int(0.12 * SR)),
                              500 + 1800 * np.sin(np.pi * np.linspace(0, 1, int(0.12 * SR))), 'bp', q=3)
                desk.add(wah * 0.6, when, 0.18, -0.35, hall=0.1)
            k += 1
        desk.wide(lambda c=chord, g=stop - start: J.pad_voice(c, g, 0.2, 0.5), start, 0.05, hall=0.4)
    for when in (4.75, 5.75):                                         # brass stabs between the lines
        for i, note in enumerate((60, 64, 67)):
            desk.add(J.brass(note + (5 if when > 5 else 0), 0.14, 0.9), when, 0.08, -0.3 + 0.3 * i, hall=0.25)
    field_roll(desk, 6.75, 0.25, 0.3, 1.0)
    J.hit(desk, 62, P.FINALE[0], big=True)
    S.logo(desk, P.FINALE[0], CLOSED, organ_=False, gain=1.0)
    for when, (offset, beats_), note in zip(P.FINALE, RHYTHM, CLOSED):
        desk.add(fife(note + 12, beats_ * BEAT * 0.92, 1.0), when, 0.3, 0.25, hall=0.35)
        desk.add(boom(1.0), when + 0.1, 0.35, rng.uniform(-0.6, 0.6), hall=0.4)
    for i, note in enumerate((50, 57, 62, 66, 69, 74)):
        desk.add(J.brass(note, 1.4, 1.0), P.FINALE[0], 0.09, -0.5 + 0.2 * i, hall=0.35)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.1, 1.0), P.FINALE[0], 0.07, hall=0.45)
    field_roll(desk, 8.5, 0.5, 0.3, 0.9, gain=0.35)
    J.hit(desk, 62, 9.0)
    return mixdown(desk, voice, length, end, grit=1.0)


DTMF = {'0': (941, 1336), '1': (697, 1209), '5': (770, 1336), '9': (852, 1477)}


def phone_line(x):
    """Through the telephone: 300 to 3400 Hz, a little speaker grit."""
    return np.tanh(1.3 * J.butter(x, 'band', [300, 3400]))


def dial(number, tone=0.07, gap=0.03):
    """Touch-tone digits, as a modem dials them."""
    out = np.zeros(int(len(number) * (tone + gap) * SR) + 1)
    n = int(tone * SR)
    t = J.times(n)
    for k, digit in enumerate(number):
        low, high = DTMF[digit]
        start = int(k * (tone + gap) * SR)
        out[start:start + n] += (np.sin(2 * np.pi * low * t) + np.sin(2 * np.pi * high * t)) * 0.4
    return out


def handshake(length):
    """A dial-up modem's handshake: the answer tone, warbling tones, chirps, then the hiss
    of data."""
    n = int(length * SR)
    t = J.times(n)
    x = np.zeros(n)
    answer = t < 0.2 * length / 0.7
    x += np.where(answer, np.sin(2 * np.pi * 2100 * t) * np.sign(np.sin(2 * np.pi * 2.2 * t) + 0.9), 0) * 0.6
    warble = (t >= 0.2 * length / 0.7) & (t < 0.36 * length / 0.7)
    f = np.where(np.sin(2 * np.pi * 50 * t) > 0, 980, 1180)
    x += np.where(warble, np.sin(2 * np.pi * np.cumsum(f) / SR), 0) * 0.5
    chirp = (t >= 0.36 * length / 0.7) & (t < 0.5 * length / 0.7)
    fc = 600 + 2600 * ((t * 9) % 1)
    x += np.where(chirp, np.sin(2 * np.pi * np.cumsum(fc) / SR), 0) * 0.45
    data = t >= 0.5 * length / 0.7
    x += np.where(data, J.butter(J.noise(n), 'band', [700, 3000]) * (1 + 0.3 * np.sin(2 * np.pi * 17 * t)), 0) * 0.55
    return x * np.clip((length - t) / 0.01, 0, 1)


def scratch(length=0.4, vel=1.0):
    """A record scratched back and forth: a voice-like buzz bending with the hand."""
    n = int(length * SR)
    t = J.times(n)
    speed = np.sin(2 * np.pi * (1 / length) * 2 * t)
    f = 220 * (1 + 0.9 * speed)
    x = J.sweep(J.saw(f, n), 900 + 700 * np.abs(speed), 'bp', q=2)
    return x * np.abs(speed) ** 0.7 * vel * 0.5


def mouse_click(vel=1.0):
    n = int(0.05 * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [2500, 9000]) * np.exp(-t / 0.002) * vel


def breakbeat(desk, start, stop, gain=1.0):
    """A nineties break: the kick on one and the and of two, the snare on two and four with
    ghost notes, sixteenth hats, swung a hair."""
    step = 0
    while start + step * BEAT / 4 < stop - 1e-9:
        k = step % 16
        when = start + step * BEAT / 4 + (0.012 if k % 2 else 0.0)
        if k in (0, 6, 10):
            desk.add(J.kick(0.95), when, 0.75 * gain, hall=0.02)
        if k in (4, 12):
            desk.add(J.snare(1.0), when, 0.5 * gain, 0.05, hall=0.08, room=0.4)
        if k in (7, 9, 15):
            desk.add(J.snare(0.25), when, 0.3 * gain, 0.1, hall=0.05)
        desk.add(J.hat(0.5 if k % 4 == 2 else 0.3, open_=k == 14), when, 0.24 * gain, 0.35, hall=0.03)
        step += 1


def ninety_six(voice):
    """1996: the modem dials 555-0119 and shrieks through its handshake down the phone
    line, a click as it connects; the page loads on the open logo (a MIDI piano and a
    stab for each piece); a scratch into the break, the bass and a string pad under the
    promo voice; the mouse click, and the closed logo with piano, brass, bells and choir."""
    P = hits('ninety-six')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.add(phone_line(np.sin(2 * np.pi * 350 * J.times(int(0.12 * SR))) + np.sin(2 * np.pi * 440 * J.times(int(0.12 * SR)))) * 0.25,
             0.0, 0.25, hall=0.02)                                   # the dial tone
    desk.add(phone_line(dial('5550119')), P.DIALING, 0.45, 0.2, hall=0.02)
    desk.add(phone_line(handshake(P.CONNECTED - P.VERIFYING - 0.05)), P.VERIFYING, 0.4, 0.2, hall=0.03)
    desk.add(mouse_click(1.0) * 0.6, P.CONNECTED, 0.4, 0.2)
    desk.add(J.riser(0.4, 6000), P.BROWSER - 0.2, 0.12, hall=0.3)
    for k, (when, note) in enumerate(zip(P.LOADS, OPEN)):            # the page loads on the open logo
        desk.add(J.epiano(note, 0.4 if k < 3 else 0.9, 0.9), when, 0.32, -0.15, hall=0.3)
        desk.add(J.epiano(note - 12, 0.4 if k < 3 else 0.9, 0.7), when, 0.2, 0.15, hall=0.3)
        for i, n in enumerate((note - 12, note - 5)):
            desk.add(J.brass(n, 0.14 if k < 3 else 0.6, 0.9), when, 0.08, -0.3 + 0.6 * i, hall=0.25)
        desk.add(J.kick(0.8), when, 0.5)
    desk.add(scratch(0.45), P.LOADS[3] + 0.5, 0.35, 0.2, hall=0.05)
    for start, stop, root, chord in ((3.5, 5.0, 36, (60, 64, 67, 70)), (5.0, 6.0, 41, (60, 65, 69, 72)),
                                     (6.0, P.WORDART, 43, (59, 62, 65, 67))):
        breakbeat(desk, start, stop, gain=0.85)
        k = 0
        while start + k * BEAT / 2 < stop - 1e-9:
            if k % 4 in (0, 3):
                desk.add(J.bass(root + (0, 0, 0, 10)[k % 4], 0.3, 0.85), start + k * BEAT / 2, 0.45)
            k += 1
        desk.wide(lambda c=chord, g=stop - start: J.pad_voice(c, g, 0.15, 0.4), start, 0.06, hall=0.4)
    desk.add(mouse_click(1.0), P.CLICK, 0.6, 0.3, hall=0.02)
    J.hit(desk, 62, P.WORDART, big=True)
    S.logo(desk, P.WORDART, CLOSED, organ_=False, choir=True, gain=1.0)
    for when, note in zip(at_logo(P.WORDART), CLOSED):
        desk.add(J.epiano(note, 0.6, 1.0), when, 0.3, -0.2, hall=0.3)
    for i, when in enumerate(P.NEW_BURSTS):
        desk.add(pop(1.0), when, 0.3, (-0.5, 0.5, 0.0)[i], hall=0.15)
    breakbeat(desk, P.WORDART, 9.0, gain=0.7)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.1, 1.0), P.WORDART, 0.07, hall=0.45)
    J.hit(desk, 62, 9.0)
    return mixdown(desk, voice, length, end, grit=0.6)


def chop(midi, length=0.18, vel=1.0):
    """A vocal chop: a sung 'oh', cut short and pitched, with a breathy pan-flute edge."""
    n = int(length * SR)
    t = J.times(n)
    f = float(J.hz(midi)) * (1 + 0.02 * np.exp(-t / 0.02))
    x = J.saw(f, n)
    y = sum(g * J.formant(x, fc, bw) for fc, bw, g in ((500, 90, 1.0), (850, 100, 0.5), (2600, 160, 0.15)))
    y += 0.25 * np.sin(2 * np.pi * np.cumsum(np.broadcast_to(f, (n,))) / SR)
    y += 0.06 * J.butter(J.noise(n), 'band', [float(J.hz(midi)), float(J.hz(midi)) * 4])
    return y * np.clip(t / 0.008, 0, 1) * np.clip((length - t) / 0.04, 0, 1) * vel * 0.6


def tropical(desk, start, stop, root, chord, gain=1.0):
    """2016's tropical house: a soft four-on-the-floor, claps on two and four, a shaker, a
    marimba line, the sub, and a pad pumping against the kick."""
    k = 0
    while start + k * BEAT / 4 < stop - 1e-9:
        when, step = start + k * BEAT / 4, k % 8
        if step % 2 == 0:
            desk.add(shaker(0.8 if step % 4 == 2 else 0.5), when, 0.35 * gain, 0.3)
        if step == 0:
            desk.add(J.kick(0.75), when, 0.6 * gain)
            desk.add(sub(root, 0.4, 0.8), when + BEAT / 2, 0.3 * gain)
        if step == 4 and (k // 8) % 2 == 1:
            desk.add(J.clap(0.8), when, 0.35 * gain, 0.05, hall=0.15)
        if step in (0, 3, 6):
            desk.add(J.marimba(chord[(k // 2) % len(chord)] + 12, 0.8), when, 0.18 * gain, -0.25, hall=0.25)
        k += 1
    length = stop - start
    pad = J.pad_voice(chord, length, 0.05, 0.3)
    t = J.times(len(pad))
    pump = 1 - 0.65 * np.exp(-((t % BEAT) / 0.12))
    desk.wide(lambda: pad * pump, start, 0.07 * gain, hall=0.35)


def twenty_sixteen(voice):
    """2016: an airy pad and a vocal chop as the phone rises; the open logo as notification
    sounds on marimba (the drop, the tap, the swoosh, the drop); tropical house under the
    promo voice with a pan-flute chop hook; the closed logo on marimba, chops and bells,
    pops for the hearts."""
    P = hits('twenty-sixteen')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.wide(lambda: J.pad_voice((60, 64, 67, 71), 1.2, 0.5, 0.5), 0.0, 0.13, hall=0.5)
    desk.add(chop(79, 0.3, 0.8), 0.25, 0.2, -0.3, hall=0.45)
    desk.add(J.whoosh(0.6), P.PHONE_UP[0], 0.15, 0.4, hall=0.3)
    for when, note in zip((P.NOTIFY, P.TAP, P.OPEN_APP, P.LIVE), OPEN):   # the open logo
        desk.add(J.marimba(note, 1.0), when, 0.35, 0.1, hall=0.3)
        desk.add(J.marimba(note + 12, 0.6), when, 0.12, 0.3, hall=0.3)
    desk.add(pop(1.0), P.NOTIFY, 0.25, 0.4, hall=0.1)
    desk.add(click(1.0), P.TAP, 0.6, 0.4)
    desk.add(J.whoosh(0.5), P.OPEN_APP, 0.2, 0.3, hall=0.3)
    desk.add(J.riser(0.5, 8000), P.OPEN_APP, 0.12, hall=0.3)
    desk.add(chop(OPEN[-1] + 12, 0.5, 1.0), P.LIVE, 0.2, -0.2, hall=0.4)
    for start, stop, root, chord in ((P.LIVE, 4.0, 36, (60, 64, 67, 71)), (4.0, 5.0, 33, (57, 60, 64, 67)),
                                     (5.0, 6.0, 29, (53, 57, 60, 64)), (6.0, P.HASHTAG, 31, (55, 59, 62, 65))):
        tropical(desk, start, stop, root, chord, gain=0.9)
    hook = ((5.0, 76), (5.25, 79), (5.5, 81), (5.75, 79), (6.0, 76), (6.25, 74), (6.5, 72))
    for when, note in hook:                                           # the chop hook, after the line
        desk.add(chop(note, 0.17, 0.9), when, 0.14, 0.2, hall=0.35)
    desk.add(J.crash(0.8, 2.0), P.HASHTAG, 0.25, 0.3, hall=0.3)
    desk.add(J.kick(0.9), P.HASHTAG, 0.6)
    S.logo(desk, P.HASHTAG, CLOSED, organ_=False, gain=0.55)
    for when, note in zip(at_logo(P.HASHTAG), CLOSED):
        desk.add(J.marimba(note, 1.0), when, 0.25, -0.1, hall=0.3)
        desk.add(chop(note, 0.22 if note != CLOSED[-1] else 0.8, 1.0), when, 0.09, 0.25, hall=0.4)
    tropical(desk, P.HASHTAG, 9.0, 38, (62, 66, 69, 73), gain=0.75)
    for k in range(10):                                               # the hearts burst out
        desk.add(pop(0.7 + 0.03 * k), P.BURST + 0.05 + k * 0.09, 0.12, rng.uniform(-0.7, 0.7), hall=0.15)
    desk.add(J.bell(98, 1.4, 0.6), 9.0, 0.08, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.0)


# ---------------------------------------------------------------- The Cairo

def trumpet(midi, gate, vel=1.0):
    """A stone elephant trumpeting: a brassy blare that scoops up into the note, nasal and
    rough, with a wobble."""
    n = int((gate + 0.1) * SR)
    t = J.times(n)
    f = float(J.hz(midi)) * (1 - 0.18 * np.exp(-t / 0.05)) * (1 + 0.012 * np.sin(2 * np.pi * 7 * t))
    x = J.saw(f, n) + 0.4 * J.pulse(f * 1.003, n, 0.3)
    y = J.formant(x, 1300, 300) + 0.6 * J.formant(x, 2600, 400) + 0.3 * J.butter(x, 'low', 700)
    rough = 1 + 0.25 * np.sin(2 * np.pi * 31 * t)
    env = np.clip(t / 0.03, 0, 1) * np.clip((gate + 0.1 - t) / 0.1, 0, 1)
    return np.tanh(2.0 * y * rough * env) * vel * 0.5


def gavel(vel=1.0):
    """A judge's gavel: two hard knocks of wood on wood."""
    out = np.zeros(int(0.4 * SR))
    for at, v in ((0.0, 1.0), (0.16, 0.8)):
        n = int(0.08 * SR)
        t = J.times(n)
        knock = (np.sin(2 * np.pi * 520 * t) * np.exp(-t / 0.012) + 0.5 * J.butter(J.noise(n), 'band', [800, 4000])
                 * np.exp(-t / 0.006))
        out[int(at * SR):int(at * SR) + n] += knock * v
    return out * vel


def beacon(midi, vel=1.0):
    """The mast's signal: a pure ping that rings away."""
    n = int(1.4 * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) * np.exp(-t / 0.2)) * np.exp(-t / 0.45) * vel


def the_cairo(voice):
    """Q Street at dusk: the city's murmur and a warm string pad; the elephants lift their
    trunks with a stony creak and trumpet the open logo, left, right, left, both; then a
    harp up the twelve floors, the strings swelling, a gavel as the 90-foot line goes by;
    wind on the roof; on the closed logo the mast's beacon pings with each note under
    bells, brass and choir."""
    P = hits('the-cairo')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    t = J.times(desk.n)
    desk.add(J.butter(J.noise(desk.n), 'low', 400) * (0.5 + 0.2 * np.sin(2 * np.pi * 0.2 * t)), 0.0, 0.08, hall=0.2)
    desk.wide(lambda: J.pad_voice((48, 55, 60, 64), 2.4, 0.8, 0.8), 0.0, 0.08, hall=0.45)
    n = int((P.TRUNKS_UP[1] - P.TRUNKS_UP[0]) * SR)
    creak = J.butter(J.noise(n), 'band', [150, 900]) * np.abs(np.sin(np.pi * 23 * J.times(n))) ** 4
    desk.add(creak, P.TRUNKS_UP[0], 0.3, hall=0.2)
    for k, (when, note) in enumerate(zip(P.TRUMPETS, OPEN)):           # the open logo, trumpeted
        gate = RHYTHM[k][1] * BEAT * 0.9
        if k < 3:
            desk.add(trumpet(note - 12, gate), when, 0.4, -0.6 if k % 2 == 0 else 0.6, hall=0.35)
        else:
            for side in (-0.6, 0.6):
                desk.add(trumpet(note - 12, gate), when, 0.3, side, hall=0.35)
        desk.add(J.bell(note, 1.6, 0.6), when, 0.1, 0.0, hall=0.4)
    floors = (48, 50, 52, 55, 57, 60, 62, 64, 67, 69, 72, 74)
    for k, note in enumerate(floors):                                   # a floor a note, up to the roof
        when = P.RISE[0] + (P.RISE[1] - P.RISE[0]) * (k + 0.5) / len(floors)
        desk.add(pizz(note + 12, 0.8), when, 0.3, -0.4 + 0.07 * k, hall=0.4)
        desk.add(vibes(note + 12, 1.2, 0.5), when, 0.08, 0.3, hall=0.45)
    desk.wide(lambda: J.pad_voice((48, 55, 60, 64, 69), P.RISE[1] - P.RISE[0], 1.5, 1.0), P.RISE[0], 0.08, hall=0.45)
    desk.add(J.riser(P.RISE[1] - P.RISE[0], 6000), P.RISE[0], 0.08, hall=0.35)
    desk.add(gavel(1.0), P.LIMIT_PASSES, 0.35, 0.5, hall=0.25)
    desk.add(J.whoosh(1.4), P.RISE[1] - 0.2, 0.12, 0.2, hall=0.4)      # wind on the roof
    for i, note in enumerate((84, 88, 91)):                             # the place tag
        desk.add(J.bell(note, 1.0, 0.5), P.TAG[0] + i * 0.05, 0.06, -0.4 + 0.2 * i, hall=0.5)
    S.logo(desk, P.LIFT, CLOSED, organ_=False, choir=True, gain=1.0)
    for when, note in zip(P.RINGS, CLOSED):
        desk.add(beacon(note + 12, 0.8), when, 0.18, 0.0, hall=0.5)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.2, 0.2, 1.2), P.LIFT, 0.08, hall=0.45)
    desk.add(J.timpani(38, 0.8), P.LIFT, 0.35, hall=0.35)
    desk.add(J.crash(0.7, 2.4), P.LIFT, 0.2, 0.3, hall=0.35)
    return mixdown(desk, voice, length, end, grit=0.5)


def upright(midi, gate, vel=1.0):
    """An old upright, out of tune in the honky-tonk way: two strings a little apart, the
    hammer's knock, a quick decay."""
    n = int((gate + 0.25) * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = np.zeros(n)
    for detune in (-7, 7):
        g = f * 2 ** (detune / 1200)
        for h, amp in ((1, 1.0), (2, 0.5), (3, 0.28), (4, 0.15), (5, 0.08)):
            x += amp * np.sin(2 * np.pi * g * h * (1 + 0.0004 * h * h) * t) * np.exp(-t * (1.6 + 0.9 * h))
    knock = J.butter(J.noise(n), 'band', [600, 3000]) * np.exp(-t / 0.008) * 0.3
    damp = np.clip((gate + 0.25 - t) / 0.25, 0, 1)
    return (x * 0.35 + knock) * damp * vel


def projector(length):
    """A silent-film projector: the shutter's clatter sixteen times a second, its motor."""
    n = int(length * SR)
    t = J.times(n)
    clatter = J.butter(J.noise(n), 'band', [1200, 6000]) * np.exp(-((t * 16) % 1) / 0.08) * 0.5
    motor = np.sin(2 * np.pi * 96 * t) * 0.15 + J.butter(J.noise(n), 'low', 300) * 0.3
    return clatter + motor


def fire_bell(vel=1.0):
    """A fire wagon's brass bell, rung: an inharmonic clang."""
    n = int(0.9 * SR)
    t = J.times(n)
    x = sum(g * np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, g, d in ((1180, 1.0, 0.4), (2950, 0.5, 0.2),
                                                                          (4410, 0.3, 0.1), (1770, 0.4, 0.3)))
    return x * vel * 0.3


def stride(desk, start, stop, root, chord, gain=1.0):
    """Ragtime's left hand: the bass note on one and three, the chord on two and four."""
    k = 0
    while start + k * BEAT < stop - 1e-9:
        when = start + k * BEAT
        if k % 2 == 0:
            desk.add(upright(root - 12 + (0 if k % 4 == 0 else 7), 0.25, 0.9), when, 0.4 * gain, -0.2, hall=0.15)
        else:
            for note in chord:
                desk.add(upright(note, 0.2, 0.7), when, 0.14 * gain, 0.1, hall=0.15)
        k += 1


def cairo_1894(voice):
    """A silent film: the projector throughout; the fire wagon's bell and hooves as a
    ragtime piano strikes up; the open logo on the piano as the ladder runs up, a ratchet
    for each section; a run up for the climb, a sorry three notes down for the shrug; the
    villain's tremolo under "TOO TALL!"; a jaunty stride under Congress; a glissando and a
    spark for the mast; the closed logo in octaves, and the tag."""
    P = hits('cairo-1894')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.add(projector(length), 0.0, 0.07, 0.3, hall=0.05)
    for k in range(4):                                                  # the leader's clicks
        desk.add(click(1.0), 0.03 + k * 0.08, 0.3, 0.3)
    for k in range(6):                                                  # the wagon: bell and hooves
        desk.add(fire_bell(0.9 - 0.1 * k), P.WAGON[0] + k * 0.17, 0.25, -0.5 + 0.1 * k, hall=0.2)
    for k in range(10):
        desk.add(rim(0.7 if k % 2 else 1.0), P.WAGON[0] + k * 0.0625 * (2 if k % 2 == 0 else 1.6), 0.25, -0.4, hall=0.1)
    stride(desk, P.WAGON[0], P.LADDER[0], 48, (64, 67, 72), gain=0.8)
    for k, (when, note) in enumerate(zip(P.LADDER, OPEN)):              # the ladder runs up on the open logo
        gate = RHYTHM[k][1] * BEAT * 0.9
        desk.add(upright(note, gate, 1.0), when, 0.45, 0.1, hall=0.2)
        desk.add(upright(note + 12, gate, 0.7), when, 0.2, 0.2, hall=0.2)
        n = int(0.12 * SR)
        ratchet = J.butter(J.noise(n), 'band', [1500, 5000]) * (np.sin(2 * np.pi * 60 * J.times(n)) > 0.6)
        desk.add(ratchet, when, 0.18, -0.2, hall=0.1)
    stride(desk, P.LADDER[0], 2.0, 48, (64, 67, 72), gain=0.7)
    for k, note in enumerate((72, 74, 76, 77, 79, 81, 83, 84)):        # the climb
        desk.add(upright(note, 0.08, 0.7), P.CLIMB[0] + k * (P.CLIMB[1] - P.CLIMB[0]) / 8, 0.3, 0.1, hall=0.15)
    for k, note in enumerate((67, 66, 65)):                             # the shrug
        desk.add(upright(note, 0.2 if k < 2 else 0.45, 0.8), P.SHRUG[0] + k * 0.16, 0.35, 0.0, hall=0.2)
    for k in range(int((P.CARD_1[1] - P.CARD_1[0]) / 0.0625)):          # "TOO TALL!": the villain's tremolo
        chord = (47, 50, 53, 56) if k % 2 else (59, 62, 65, 68)
        for note in chord:
            desk.add(upright(note, 0.06, 0.45 + 0.2 * (k < 4)), P.CARD_1[0] + k * 0.0625, 0.07, -0.1, hall=0.2)
    stride(desk, P.CARD_2[0], P.CARD_2[1] - 0.15, 48, (64, 67, 72), gain=0.9)
    tune = ((0.0, 76), (0.5, 79), (0.75, 76), (1.0, 72), (1.5, 74), (2.0, 76), (2.25, 77), (2.5, 79))
    for at, note in tune:                                               # a jaunty tune over it
        desk.add(upright(note, 0.2, 0.8), P.CARD_2[0] + at * BEAT * 1.25, 0.3, 0.15, hall=0.2)
    for k, note in enumerate(range(60, 86, 2)):                         # the mast: a glissando and a spark
        desk.add(upright(note, 0.05, 0.6), P.CARD_2[1] + k * 0.012, 0.2, 0.0, hall=0.2)
    desk.add(J.static_burst(0.25), P.MAST + 0.1, 0.12, 0.3, hall=0.1)
    for (offset, beats_), note in zip(RHYTHM, CLOSED):                  # the closed logo, in octaves
        when, gate = P.FINAL + offset * BEAT, beats_ * BEAT * 0.9
        for octave in (-12, 0, 12):
            desk.add(upright(note + octave, gate, 1.0), when, 0.3, -0.1 + 0.1 * (octave > 0), hall=0.25)
    stride(desk, P.FINAL, 8.75, 50, (66, 69, 74), gain=0.8)
    for at, note in ((8.75, 74), (8.875, 69), (9.0, 69), (9.0, 62)):    # the tag
        desk.add(upright(note, 0.3, 1.0), at, 0.4, 0.0, hall=0.25)
    return mixdown(desk, voice, length, end, grit=1.3)


# ---------------------------------------------------------------- 18 October: the church, the band, the painter...

def cat_field_goal(voice):
    """The documentary goes to the game: the hushed pad and the sneaking pizzicato; a tap
    on each of the open logo's first three notes (a knock on the leather, vibes); the swat
    on the fourth with a kick drum and brass, a slide whistle up as the ball tumbles across
    the room, a swish of bells through the rabbit ears, the referee's whistle and the set's
    crowd for IT'S GOOD!; a purr; behind the set, the mug's KRSSH; then the closed logo with
    a soft choir, a mrrp and a harp of bells."""
    P = hits('cat-field-goal')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.wide(lambda: J.pad_voice((48, 55, 64, 71), 3.0, 1.0, 1.0), 0.0, 0.06, hall=0.4)
    tiptoe(desk, 0.25, 2.9)
    for (when, look), note in zip(P.LOOKS, (88, 84, 91)):          # its glances
        desk.add(vibes(note, 0.8, 0.6), when, 0.1, 0.3, hall=0.35)
    desk.wide(lambda: J.pad_voice((50, 57, 62, 69), 1.5, 0.4, 0.8), 2.5, 0.05, hall=0.4)
    for when, note in zip(P.TAPS, OPEN):                             # tap, tap, tap
        desk.add(J.tom(50, 0.55), when, 0.3, -0.1, room=0.3)
        desk.add(vibes(note, 1.6, 0.9), when, 0.3, -0.2, hall=0.35)
        desk.add(pizz(note - 12, 0.8), when, 0.3, 0.1, hall=0.2)
    desk.add(J.kick(1.0), P.KICK, 0.8, hall=0.1)                     # and the kick, on the A
    desk.add(J.tom(43, 1.0), P.KICK, 0.45, room=0.4)
    desk.add(vibes(OPEN[3], 2.0, 1.0), P.KICK, 0.3, -0.2, hall=0.4)
    for i, note in enumerate((OPEN[3] - 24, OPEN[3] - 12, OPEN[3] - 5)):
        desk.add(J.brass(note, 0.45, 0.9), P.KICK, 0.1, -0.4 + 0.4 * i, hall=0.25)
    desk.add(glide(420, 1500, P.FLIGHT[1] - P.FLIGHT[0]), P.FLIGHT[0], 0.3, 0.3, hall=0.25)
    desk.add(J.whoosh(0.7), P.FLIGHT[0], 0.15, 0.4, hall=0.2)
    for i, note in enumerate((84, 88, 91, 96, 100)):                # through the ears
        desk.add(J.bell(note, 1.2, 0.7), P.THROUGH + i * 0.04, 0.08, 0.6, hall=0.5)
    desk.add(ref_whistle(), P.GOOD + 0.05, 0.22, 0.5, hall=0.3)
    desk.add(J.butter(S.crowd(2.4, swell=(0.0, 0.2)), 'band', [400, 3500]), P.GOOD, 0.3, 0.55, hall=0.1)
    for i, note in enumerate((60, 64, 67, 72)):                      # ta-da, paws up
        desk.add(pizz(note, 0.8), P.ARMS[0] + i * 0.03, 0.4, -0.3 + 0.2 * i, hall=0.3)
    desk.add(purr(P.CRASH - P.ARMS[0] + 0.3), P.ARMS[0], 0.3, -0.2, hall=0.05)
    desk.add(ceramic(0.9), P.CRASH, 0.4, 0.75, hall=0.35)
    desk.add(J.bell(93, 0.4, 0.5), P.GLANCE[0], 0.06, 0.4, hall=0.3)
    tiptoe(desk, 6.0, 6.9, notes=(48, 52, 55, 52), step=0.25, gain=0.25)
    S.logo(desk, P.BANNER, CLOSED, organ_=False, choir=True, gain=0.85)
    for when, note in zip(at_logo(P.BANNER), CLOSED):
        desk.add(vibes(note, 2.0, 0.8), when, 0.25, -0.2, hall=0.35)
        for i, n in enumerate((note - 24, note - 12)):
            desk.add(J.brass(n, 0.3, 0.8), when, 0.06, -0.3 + 0.6 * i, hall=0.3)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.0, 0.3, 1.2), P.BANNER, 0.07, hall=0.4)
    desk.add(meow(), P.MRRP, 0.5, -0.1, hall=0.15)
    for i, note in enumerate((74, 78, 81, 86, 90, 93)):
        desk.add(J.bell(note, 1.6, 0.55), P.BLINK[0] + i * 0.05, 0.07, -0.4 + 0.15 * i, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.5)


def pluck(midi, length=1.6, vel=1.0, bright=0.5):
    """A nylon string, plucked (Karplus-Strong, a period at a time)."""
    period = max(2, int(round(SR / float(J.hz(midi)) - 0.5)))   # the averaging adds half a sample
    n = int(length * SR)
    y = np.zeros(n + period + 1)
    burst = rng.uniform(-1, 1, period)
    width = max(2, int(period * (1 - bright) / 3))     # a softer pluck: a smoother burst (a fingertip)
    window = np.hanning(width + 2)[1:-1]
    burst = np.convolve(np.concatenate([burst, burst]), window / window.sum(), 'same')[period // 2:period // 2 + period]
    y[1:period + 1] = burst - burst.mean()
    decay = 0.996 ** (440 / float(J.hz(midi)))
    for start in range(period + 1, len(y), period):
        stop = min(start + period, len(y))
        y[start:stop] = decay * 0.5 * (y[start - period:stop - period] + y[start - period - 1:stop - period - 1])
    x = J.butter(y[1:n + 1], 'high', 60)
    t = J.times(n)
    return x * np.clip((length - t) / 0.08, 0, 1) * vel * 0.6


def dab(vel=1.0):
    """A fan brush tapped on canvas: a soft, papery tick."""
    n = int(0.06 * SR)
    t = J.times(n)
    return J.butter(J.noise(n), 'band', [400, 3000]) * np.exp(-t / 0.012) * vel * 0.6


def stroke(length, vel=1.0):
    """A brush drawn across canvas: a breathy swish, swelling and fading."""
    n = int(length * SR)
    t = J.times(n)
    x = J.butter(J.noise(n), 'band', [700, 5000]) * np.sin(np.pi * t / length) ** 1.5
    return x * vel * 0.4


def thwack(vel=1.0):
    """A wet brush beaten against an easel's leg: a wooden knock, a slap, a spray."""
    n = int(0.45 * SR)
    t = J.times(n)
    knock = np.sin(2 * np.pi * np.cumsum(170 + 140 * np.exp(-t / 0.008)) / SR) * np.exp(-t / 0.07)
    slap = J.butter(J.noise(n), 'band', [500, 3500]) * np.exp(-t / 0.02)
    spray = J.butter(J.noise(n), 'band', [2000, 8000]) * np.exp(-np.clip(t - 0.025, 0, None) / 0.09) * (t > 0.02)
    return (knock + 0.7 * slap + 0.3 * spray) * vel * 0.8


def fingerpick(desk, chord, start, stop, gain=0.35):
    """The guitar under the painter: a gentle arpeggio on the eighths (bass, then up and down)."""
    order = (0, 2, 1, 3, 2, 1, 3, 2)
    k = 0
    while start + k * 0.25 < stop - 1e-9:
        desk.add(pluck(chord[order[k % 8]], 1.4, 0.9 if k % 8 == 0 else 0.6), start + k * 0.25, gain,
                 -0.25 + 0.15 * (order[k % 8]), hall=0.3)
        k += 1


def happy_little(voice):
    """The painting show: a fingerpicked nylon guitar under a warm pad; the open logo on
    vibes as each happy little tree is tapped in (a flurry of fan-brush dabs); little
    swishes as the friend is painted, a boing for its hop and a sparkle; then the closed
    logo, a thwack of the brush on the easel's leg on each note, with vibes and the guitar
    strummed in D; one long stroke for the signature."""
    P = hits('happy-little')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    for i, (chord, start) in enumerate((((48, 55, 60, 64), 0.0), ((45, 52, 57, 60), 2.0), ((41, 48, 53, 57), 4.0),
                                        ((43, 50, 55, 59), 6.0))):
        fingerpick(desk, chord, start, min(start + 2.0, 7.0))
        desk.wide(lambda c=chord: J.pad_voice(tuple(n + 12 for n in c), 2.1, 0.6, 0.9), start, 0.04, hall=0.45)
    for when, grow, note in zip(P.TREES, P.GROW, OPEN):            # happy little trees
        desk.add(vibes(note, 1.8, 0.9), when, 0.3, -0.15, hall=0.4)
        for k in range(int(grow / 0.035)):
            desk.add(dab(0.7 + 0.3 * rng.random()), when + k * 0.035, 0.35, 0.2, hall=0.05)
    for k in range(9):                                              # the friend, painted
        desk.add(stroke(0.2, 0.8), P.FRIEND[0] + k * (P.FRIEND[1] - P.FRIEND[0]) / 9, 0.4, -0.1 + 0.03 * k, hall=0.05)
    desk.add(boing(0.5, 0.8), P.HOP, 0.3, hall=0.15)
    for i, note in enumerate((84, 88, 91, 96)):
        desk.add(J.bell(note, 1.2, 0.6), P.HOP + 0.4 + i * 0.05, 0.07, 0.3, hall=0.5)
    desk.add(J.whoosh(0.5), P.BRUSH_OUT[0], 0.08, 0.5, hall=0.2)
    for when, note in zip(P.WHACKS, CLOSED):                        # beat the devil out of it
        desk.add(thwack(1.0), when, 0.55, 0.0, hall=0.15)
        desk.add(vibes(note, 2.0, 0.9), when, 0.28, -0.2, hall=0.4)
    for when in (P.WHACKS[0], P.WHACKS[3]):                         # the guitar, strummed in D
        for i, note in enumerate((50, 57, 62, 66, 69, 74)):
            desk.add(pluck(note, 2.0, 0.8, bright=0.7), when + i * 0.018, 0.3, -0.3 + 0.12 * i, hall=0.35)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.2, 0.4, 1.0), P.WHACKS[0], 0.05, hall=0.45)
    desk.add(stroke(P.SIGN[1] - P.SIGN[0], 1.0), P.SIGN[0], 0.4, -0.2, hall=0.1)
    desk.add(pluck(86, 1.2, 0.7, bright=0.9), P.SIGN[1], 0.3, 0.2, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.4)


def kernel_pop(midi=None, vel=1.0):
    """A kernel popping: a dry crack in the bag, and, for the first four, a note in it."""
    n = int(0.16 * SR)
    t = J.times(n)
    crack = J.butter(J.noise(n), 'band', [700, 5000]) * np.exp(-t / 0.006)
    body = np.sin(2 * np.pi * np.cumsum(220 + 500 * np.exp(-t / 0.01)) / SR) * np.exp(-t / 0.03) * 0.5
    x = crack + body
    if midi is not None:
        x += np.sin(2 * np.pi * float(J.hz(midi)) * t) * np.exp(-t / 0.08) * 0.6
    return x * vel


def hum(length, vel=1.0):
    """A microwave running: the transformer's hum, the fan, the turntable's rattle."""
    n = int(length * SR)
    t = J.times(n)
    x = 0.5 * np.sin(2 * np.pi * 120 * t) + 0.25 * np.sin(2 * np.pi * 240 * t) + 0.1 * np.sin(2 * np.pi * 360 * t)
    x += 0.6 * J.butter(J.noise(n), 'band', [200, 1500])
    x *= 1 + 0.08 * np.sin(2 * np.pi * 1.4 * t)
    return x * np.clip(t / 0.05, 0, 1) * np.clip((length - t) / 0.03, 0, 1) * vel * 0.4


def popcorn(voice):
    """The microwave: its hum, a lounge groove (walking bass, brushes, vibes) as the
    display counts down; the first four kernels pop the open logo; the frenzy, every pop
    as the picture has it, over a snare roll and a riser; the hum stops and the beeper
    plays the closed logo, BEEP BEEP BEEP BEEEP; the door bangs, the bag bursts, the
    popcorn patters down and the band says ta-da."""
    P = hits('popcorn')
    length, end = 10.0, 9.65
    desk = S.Desk(length)
    desk.add(J.butter(hum(P.DONE), 'low', 2000), 0.0, 0.25, hall=0.05)
    bass = (36, 40, 43, 45, 33, 36, 40, 43, 41, 45, 48, 50, 43, 47, 50, 53)
    for k in range(int(P.DONE / BEAT)):                                  # walking bass and brushes
        desk.add(pizz(bass[k % len(bass)], 0.8), k * BEAT, 0.4, -0.15, hall=0.15)
        desk.add(brush(0.25, 0.6 if k % 2 else 0.4), k * BEAT + BEAT / 2, 0.4, 0.2, hall=0.1)
    for (at, chord) in ((0.0, (64, 67, 71, 74)), (2.0, (60, 64, 67, 71)), (4.0, (65, 69, 72, 76)),
                        (6.0, (67, 71, 74, 77))):
        desk.wide(lambda c=chord: J.pad_voice(c, 2.0, 0.3, 0.6), at, 0.035, hall=0.4)
    pops = beats.popcorn_pops()
    for when, note in zip(pops[:4], OPEN):                              # the first four: the open logo
        desk.add(kernel_pop(note + 12, 1.0), when, 0.5, 0.1, hall=0.15)
        desk.add(vibes(note, 1.6, 0.9), when, 0.25, -0.2, hall=0.35)
    for k, when in enumerate(pops[4:]):                                 # the frenzy
        desk.add(kernel_pop(None, 0.5 + 0.5 * rng.random()), when, 0.3, rng.uniform(-0.5, 0.5), hall=0.1)
    for k in range(int((beats.POPCORN_FRENZY[1] - 4.5) / 0.0625)):         # a roll as it peaks
        desk.add(J.snare(0.15 + 0.5 * k / 32), 4.5 + k * 0.0625, 0.25, hall=0.1, room=0.3)
    desk.add(J.riser(P.DONE - 4.5, 6000), 4.5, 0.12, hall=0.3)
    for when, note in zip(P.BEEPS, CLOSED):                             # 0:00: the beeper
        gate = 0.5 if when == P.BEEPS[-1] else 0.18
        desk.add(square(note + 12, gate, 0.5, 1.0), when, 0.2, 0.1, hall=0.1)
        desk.add(vibes(note, 1.4, 0.7), when, 0.12, -0.2, hall=0.35)
    desk.add(clunk(1.0), P.DOOR, 0.45, -0.3, hall=0.2)
    desk.add(J.kick(1.0), P.BURST, 0.7, hall=0.2)
    desk.add(J.crash(1.0, 2.0), P.BURST, 0.35, hall=0.3)
    desk.add(J.whoosh(0.6), P.BURST, 0.25, hall=0.3)
    for k in range(40):                                                 # the popcorn landing
        when = P.LAND[0] + 0.3 + rng.uniform(0, P.LAND[1] - P.LAND[0])
        desk.add(dab(0.6 + 0.4 * rng.random()), when, 0.25, rng.uniform(-0.8, 0.8), hall=0.1)
    for i, note in enumerate((50, 57, 62, 66, 69, 74)):                 # ta-da
        desk.add(J.brass(note, 0.9, 0.9), P.BURST + 0.02, 0.07, -0.4 + 0.16 * i, hall=0.3)
    for when, note in ((P.BURST + 0.02, 38), (P.BURST + 0.02, 50)):
        desk.add(pizz(note, 1.0), when, 0.5, 0.0, hall=0.2)
    for i, note in enumerate((86, 90, 93, 98)):
        desk.add(J.bell(note, 1.4, 0.6), P.LAND[1] + i * 0.05, 0.07, -0.2 + 0.15 * i, hall=0.5)
    return mixdown(desk, voice, length, end, grit=0.4)


def sonar(vel=1.0):
    """The Doppler's ping: a pure tone with a long, watery tail."""
    n = int(1.4 * SR)
    t = J.times(n)
    x = np.sin(2 * np.pi * 1320 * t) * np.exp(-t / 0.35) * (1 + 0.3 * np.sin(2 * np.pi * 7 * t))
    return x * np.clip(t / 0.004, 0, 1) * vel * 0.5


def smooth_jazz(desk, start, stop, gain=1.0):
    """The weather's bed: e-piano on a slow two-chord vamp, a fretless-ish bass, a soft
    kick, a rim on the backbeat and a shaker on the sixteenths."""
    vamp = (((64, 67, 71, 74), 40), ((65, 69, 72, 76), 41))       # Em9-ish, Fmaj9-ish over E, F
    bar = 2.0
    k = 0
    while start + k * bar < stop - 1e-9:
        at = start + k * bar
        chord, root = vamp[k % 2]
        for i, n in enumerate(chord):
            desk.add(J.epiano(n, min(bar, stop - at) * 0.95, 0.5), at + 0.02 * i, 0.12 * gain, -0.2 + 0.13 * i,
                     hall=0.35)
        desk.add(J.bass(root, 0.9, 0.7), at, 0.3 * gain, hall=0.1)
        desk.add(J.bass(root + 7, 0.4, 0.6), at + 1.25, 0.25 * gain, hall=0.1)
        for b in range(4):
            when = at + b * BEAT
            if when >= stop:
                break
            if b in (0, 2):
                desk.add(J.kick(0.5), when, 0.3 * gain, hall=0.05)
            else:
                desk.add(rim(0.6), when, 0.15 * gain, 0.2, hall=0.2)
            for s in range(4):
                desk.add(shaker(0.4 + 0.3 * (s % 2)), when + s * BEAT / 4, 0.12 * gain, 0.35, hall=0.1)
        k += 1


def forecast(voice):
    """Local on the eights: a smooth-jazz bed under the forecaster; the icons arrive on the
    open logo, a bloop and a glass bell each; the sports rain bounces in; the Doppler pings
    and sweeps round; a stab for 100%; the extended forecast's tiles, one on each note of
    the closed logo, on bells and the e-piano, the band resolving to D."""
    P = hits('forecast')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    desk.add(J.whoosh(0.5), P.TITLE[0], 0.15, -0.3, hall=0.2)
    smooth_jazz(desk, 0.0, P.TILES[0])
    for when, note in zip(P.ICONS, OPEN):
        desk.add(pop(0.9), when, 0.22, 0.2, hall=0.2)
        desk.add(glass(note + 12, 1.6, 0.9), when, 0.2, -0.2, hall=0.4)
        desk.add(vibes(note, 1.4, 0.7), when, 0.15, 0.1, hall=0.3)
    for k in range(22):                                              # scattered sports
        when = P.RAIN[0] + 0.6 + (P.RAIN[1] - P.RAIN[0]) * k / 22 + rng.uniform(0, 0.05)
        desk.add(tap(0.4 + 0.3 * rng.random()), when, 0.2, 0.6, hall=0.15)
    desk.add(sonar(1.0), P.SWEEP[0], 0.3, -0.1, hall=0.4)
    desk.add(sonar(0.7), P.SWEEP[0] + (P.SWEEP[1] - P.SWEEP[0]) * 0.67, 0.25, 0.1, hall=0.4)
    n = int((P.SWEEP[1] - P.SWEEP[0]) * SR)
    swish = J.sweep(J.noise(n), 600 + 2400 * (0.5 + 0.5 * np.sin(2 * np.pi * J.times(n) / ((P.SWEEP[1] - P.SWEEP[0]) / 1.5))),
                    'bp', q=4)
    desk.add(swish * 0.15, P.SWEEP[0], 0.3, hall=0.3)
    for i, note in enumerate((62, 66, 69, 73)):                     # 100%
        desk.add(J.brass(note, 0.3, 0.9), P.HUNDRED, 0.08, -0.3 + 0.2 * i, hall=0.3)
    desk.add(J.crash(0.6, 1.5), P.HUNDRED, 0.15, 0.3, hall=0.3)
    for when, note in zip(P.TILES, CLOSED):                         # the extended forecast
        desk.add(glass(note + 12, 2.0, 0.9), when, 0.22, -0.2, hall=0.4)
        desk.add(J.epiano(note - 12, 0.4, 0.8), when, 0.18, 0.2, hall=0.3)
        desk.add(pop(0.7), when, 0.12, 0.3, hall=0.2)
    for i, n_ in enumerate((50, 57, 62, 66, 69, 73, 76)):          # D, resolved, smooth
        desk.add(J.epiano(n_, 2.2, 0.55), P.TILES[0] + 0.02 * i, 0.12, -0.3 + 0.1 * i, hall=0.4)
    desk.add(J.bass(38, 2.0, 0.8), P.TILES[0], 0.3, hall=0.1)
    desk.add(J.bass(38, 1.0, 0.7), P.TILES[3], 0.3, hall=0.1)
    desk.add(J.kick(0.6), P.TILES[0], 0.3, hall=0.05)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 2.2, 0.3, 1.0), P.TILES[0], 0.06, hall=0.45)
    return mixdown(desk, voice, length, end, grit=0.4)


def sousaphone(midi, gate, vel=1.0):
    """The marching tuba: dark brass, a puff of breath on the attack."""
    x = J.butter(J.brass(midi, gate, vel, attack=0.03), 'low', 900)
    n = len(x)
    t = J.times(n)
    return x * 1.6 + J.butter(J.noise(n), 'band', [150, 700]) * np.exp(-t / 0.04) * 0.2 * vel


# The fight song, between the hits and the closed logo: the logo, worked into a march in C
# that climbs to D for the closed logo. (when, midi, length in seconds)
FIGHT_SONG = ((2.5, 72, 0.25), (2.75, 76, 0.25), (3.0, 79, 0.5), (3.5, 81, 0.5), (4.0, 79, 0.25), (4.25, 76, 0.25),
              (4.5, 72, 0.5), (5.0, 74, 0.25), (5.25, 77, 0.25), (5.5, 81, 0.5), (6.0, 79, 0.25), (6.25, 77, 0.25),
              (6.5, 76, 0.25), (6.75, 73, 0.25))
PA_CLEAR = 3.4                       # the band waits for "...marching band!" to finish
FIGHT_BASS = ((2.5, 36), (3.0, 43), (3.5, 36), (4.0, 43), (4.5, 36), (5.0, 43), (5.5, 38), (6.0, 43), (6.5, 45),
              (6.75, 45))


def halftime(voice):
    """The band from the blimp: the crowd, a drumline roll-off as the band comes on, the PA
    with the stadium's echo; the whole band hits the open logo, cymbals on each; the fight
    song (the logo worked into a march) over the cadence as the word is written, the tubas
    oom-pahing; then the closed logo, a sousaphone's oom and the crowd's roar for each i as
    it is dotted, and the band, the horn and the crowd on the bow."""
    P = hits('halftime')
    length, end = 10.0, 9.6
    desk = S.Desk(length)
    voice = pa(voice)
    desk.add(S.crowd(length, swell=(P.DOTS[0] - 0.3, P.BOW)), 0.0, 0.2, hall=0.2)
    for k in range(12):                                              # the roll-off
        desk.add(J.snare(0.3 + 0.5 * k / 12), 0.2 + k * 0.0625, 0.35, -0.1, hall=0.1, room=0.4)
    drumline(desk, 0.95, P.HITS[0], gain=0.6)
    for when, note in zip(P.HITS, OPEN):                             # the band hits the open logo
        for i, n in enumerate((note - 24, note - 12, note - 5, note)):    # short, so the PA comes through
            desk.add(J.brass(n, 0.3, 1.0), when, 0.11, -0.45 + 0.3 * i, hall=0.2)
        desk.add(sousaphone(note - 36, 0.3, 1.0), when, 0.35, hall=0.2)
        desk.add(J.crash(0.7, 0.6), when, 0.14, 0.3, hall=0.15)
        desk.add(J.tom(33, 1.0), when, 0.4, hall=0.25)
    drumline(desk, PA_CLEAR, 7.0, gain=0.55)
    for when, note, gate in FIGHT_SONG:                              # the fight song, once the PA is done
        if when < PA_CLEAR:
            continue
        for i, n in enumerate((note, note - 12, note - 5 if note % 12 in (0, 5, 7) else note - 4)):
            desk.add(J.brass(n, gate * 0.9, 0.85), when, 0.09 - 0.02 * i, -0.3 + 0.3 * i, hall=0.3)
        desk.add(glass(note + 12, 0.3, 0.6), when, 0.04, 0.4, hall=0.3)  # the glockenspiel
    for when, root in FIGHT_BASS:                                    # oom-pah
        if when < PA_CLEAR:
            continue
        desk.add(sousaphone(root - 12, 0.22, 0.9), when, 0.3, hall=0.15)
        desk.add(J.brass(root + 16, 0.12, 0.6), when + 0.25, 0.05, 0.3, hall=0.2)
    for when, note in zip(P.DOTS, CLOSED[:3]):                       # each i, dotted
        desk.add(sousaphone(note - 36, 0.22, 1.0), when, 0.5, hall=0.25)
        desk.add(J.bell(note + 12, 1.4, 0.9), when, 0.15, 0.2, hall=0.4)
        desk.add(J.crash(0.6, 1.4), when, 0.12, -0.3, hall=0.3)
    J.hit(desk, 62, P.BOW, big=True)                                 # and the bow
    S.logo(desk, P.DOTS[0], CLOSED, organ_=False, gain=0.9)
    for i, n in enumerate((50, 57, 62, 66, 69, 74)):
        desk.add(J.brass(n, 1.2, 0.95), P.BOW, 0.08, -0.4 + 0.16 * i, hall=0.35)
    desk.add(sousaphone(26, 1.0, 1.0), P.BOW, 0.5, hall=0.2)
    desk.add(S.horn(1.4), P.BOW, 0.35, hall=0.3)
    for k in range(8):
        desk.add(J.snare(0.5 + 0.06 * k), P.BOW - 0.5 + k * 0.0625, 0.3, hall=0.1, room=0.4)
    desk.add(S.crowd(1.8, claps=S.claps(0.2, 1)), P.BOW, 0.3, hall=0.2)
    return mixdown(desk, voice, length, end, grit=0.5)


def church_bell(midi, length=3.5, vel=1.0):
    """A cast bronze bell: the hum an octave down, the prime, the minor-third tierce, the
    quint and the nominal, each dying away at its own rate, and the clapper's strike."""
    n = int(length * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = np.zeros(n)
    for ratio, gain, decay in ((0.5, 0.7, 3.2), (1.0, 0.8, 2.4), (1.19, 0.55, 1.8), (1.5, 0.35, 1.4), (2.0, 0.6, 1.2),
                               (2.52, 0.25, 0.8), (3.0, 0.2, 0.6), (4.07, 0.12, 0.4)):
        x += gain * np.sin(2 * np.pi * f * ratio * t + rng.random() * 6) * np.exp(-t / decay)
    x += J.butter(J.noise(n), 'high', 2500) * np.exp(-t / 0.008) * 0.5
    return x * np.clip((length - t) / 0.2, 0, 1) * vel * 0.35


def pipe_organ(midi, gate, vel=1.0):
    """A church's pipe organ: principals at 8', 4', 2 2/3' and 2' with a quiet mixture,
    the ranks a hair apart, a breath of chiff as the pipes speak, the room's long release."""
    n = int((gate + 0.35) * SR)
    t = J.times(n)
    f = float(J.hz(midi))
    x = np.zeros(n)
    for harmonic, gain, cents in ((1, 1.0, 0), (2, 0.6, 1.5), (3, 0.25, -1), (4, 0.3, 2), (6, 0.12, -2), (8, 0.08, 3)):
        x += gain * np.sin(2 * np.pi * f * harmonic * float(J.cents(cents)) * t + rng.random() * 6)
    x += J.butter(J.noise(n), 'band', [1500, 5000]) * np.exp(-t / 0.025) * 0.25            # the chiff
    env = np.clip(t / 0.05, 0, 1) * np.clip((gate + 0.3 - t) / 0.3, 0, 1)
    return np.tanh(0.7 * x * env * vel) * 0.45


def hail_mary(voice):
    """The beer ad, sent up and played straight. Outside: a strummed guitar and strings at
    golden hour, birdsong, and the church bell ringing the open logo, the swallows taking
    off. Inside: the pipe organ's hymn under "Some say football is a religion"; as the pastor winds up, a timpani roll and the
    choir rising; the throw, an organ run up; the catch, the full organ, the choir's AH!
    and the congregation; then the closed logo: the choir, the organ, the bells, and the
    strings under the slogan."""
    P = hits('hail-mary')
    length, end = 10.0, 9.65
    desk = S.Desk(length)
    birds = np.random.default_rng(7)
    for k in range(7):                                               # outside: the birds
        desk.add(chirp(birds), 0.2 + k * 0.33 + birds.uniform(0, 0.1), 0.06, birds.uniform(-0.8, 0.8), hall=0.2)
    desk.add(flutter(1.2), P.BIRDS + 0.05, 0.25, 0.3, hall=0.2)
    for k, (chord, at) in enumerate((((48, 55, 60, 64, 67), 0.0), ((53, 57, 60, 65, 69), 1.5))):   # the guitar
        for i, note in enumerate(chord):
            desk.add(pluck(note, 2.0, 0.7, bright=0.6), at + 0.25 + i * 0.03, 0.22, -0.3 + 0.12 * i, hall=0.35)
    desk.wide(lambda: J.pad_voice((60, 64, 67, 72), 2.8, 0.8, 1.0), 0.0, 0.06, hall=0.5)
    for when, note in zip(P.BELL, OPEN):                             # the bell rings the open logo
        desk.add(church_bell(note - 12, 3.0, 1.0), when, 0.55, -0.1, hall=0.6)
    chords = (((48, 60, 64, 67, 72), 2.75, 1.0), ((53, 60, 65, 69, 72), 3.75, 0.5), ((55, 59, 62, 67, 71), 4.25, 1.05))
    for chord, at, gate in chords:                                   # inside: the organ's hymn
        for note in chord:
            desk.add(pipe_organ(note, gate, 0.9), at, 0.13, -0.2 + 0.1 * (note % 5), hall=0.7)
    for k in range(int((P.CATCH - P.WIND_UP[0]) / 0.0625)):          # the wind-up and the flight
        desk.add(J.timpani(43, 0.3 + 0.6 * k / 22), P.WIND_UP[0] + k * 0.0625, 0.18, hall=0.4)
    desk.add(J.choir(67, P.CATCH - P.WIND_UP[0], 0.6), P.WIND_UP[0], 0.25, -0.3, hall=0.6)
    desk.add(J.choir(71, P.CATCH - P.WIND_UP[0], 0.5), P.WIND_UP[0] + 0.2, 0.2, 0.3, hall=0.6)
    for k, note in enumerate((60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79)):    # the throw: a run up
        desk.add(pipe_organ(note, 0.12, 0.8), P.THROW + k * 0.05, 0.12, -0.3 + 0.05 * k, hall=0.6)
    desk.add(J.whoosh(P.FLIGHT[1] - P.FLIGHT[0]), P.FLIGHT[0], 0.15, 0.2, hall=0.4)
    for note in (48, 55, 60, 64, 67, 72, 76, 79):                    # the catch: everything
        desk.add(pipe_organ(note, 1.4, 1.0), P.CATCH, 0.12, -0.25 + 0.06 * (note % 9), hall=0.7)
    for note in (72, 76, 79):
        desk.add(J.choir(note, 1.1, 1.0), P.CATCH, 0.3, -0.3 + 0.3 * (note % 3), hall=0.6)
    desk.add(J.crash(1.0, 2.2), P.CATCH, 0.3, 0.2, hall=0.5)
    desk.add(J.timpani(36, 1.0), P.CATCH, 0.5, hall=0.4)
    desk.add(J.butter(S.crowd(1.6, swell=(0.0, 0.15), claps=(0.5, 0.75, 1.0, 1.25)), 'band', [300, 3000]),
             P.CATCH + 0.02, 0.35, 0.3, hall=0.5)
    for chord, at, gate in (((53, 60, 65, 69), 6.0, 0.5), ((55, 62, 67, 71), 6.5, 0.45)):   # back to the hymn
        for note in chord:
            desk.add(pipe_organ(note, gate, 0.8), at, 0.1, hall=0.7)
    S.logo(desk, P.CLOSED, CLOSED, organ_=False, choir=True, gain=0.9)   # the closed logo
    for when, note in zip(at_logo(P.CLOSED), CLOSED):
        desk.add(church_bell(note - 12, 2.5, 0.9), when, 0.35, 0.2, hall=0.6)
        desk.add(pipe_organ(note - 12, 0.4, 0.8), when, 0.12, -0.2, hall=0.6)
    for note in (38, 50, 57, 62, 66, 69):
        desk.add(pipe_organ(note, 2.2, 0.85), P.CLOSED, 0.09, -0.3 + 0.1 * (note % 7), hall=0.7)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74, 78), 2.6, 0.5, 1.0), P.CLOSED, 0.07, hall=0.5)
    for i, note in enumerate((50, 57, 62, 66, 69)):
        desk.add(pluck(note, 2.0, 0.7, bright=0.6), P.TAGLINE + 0.5 + i * 0.03, 0.2, -0.3 + 0.12 * i, hall=0.4)
    return mixdown(desk, voice, length, end, grit=0.6)


# ---------------------------------------------------------------- the cutdowns

# ---------------------------------------------------------------- the République

def harpsichord(midi, length=0.9, vel=1.0):
    """Two plucked choirs an octave apart, bright and quick to die."""
    low, high = pluck(midi, length, vel, 0.95), pluck(midi + 12, length, vel, 1.0)
    n = min(len(low), len(high))
    return (low[:n] + 0.5 * high[:n]) * 0.8


def heure_decimale(voice):
    """A tricolour whoosh and a drum flam; a clock
that ticks every decimal second (0.864 s), never quite with the band; the open logo on
harpsichord, vibes and bells as the labels and numbers flip in, its A the first "Al-" of La
Marseillaise, which brass and fife carry on in D over a field drum, under DJ Low Tide ("...lons
en-fants de la Pa-tri-e"); the bells answer with the logo under "tri-"; "Le jour de" runs into
the closed logo, which ends the anthem's line over its own cadence, with a fife, church bells
and a choir; silence."""
    P = hits('heure-decimale')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    desk.add(J.whoosh(P.WIPE[1]), 0.0, 0.3, 0.4, hall=0.3)
    desk.add(J.snare(0.4), 0.02, 0.25, room=0.3)
    desk.add(J.snare(0.8), 0.06, 0.35, room=0.3)
    desk.add(J.crash(0.5, 1.6), 0.06, 0.15, -0.3, hall=0.3)
    desk.wide(lambda: J.pad_voice((48, 55, 60, 64), 7.0, 1.0, 1.0), 0.2, 0.05, hall=0.45)
    k = 0
    while 0.6 + k * 0.864 < P.FADE[0]:                              # the decimal second
        desk.add(clack(0.45 if k % 2 == 0 else 0.3), 0.6 + k * 0.864, 0.14, 0.5, hall=0.1)
        k += 1
    # The logo and La Marseillaise, one tune: the open logo (C E G A) on harpsichord, vibes and bells;
    # its A is the anthem's first "Al-", where brass and fife take over in D: "...lons en-fants de
    # la Pa-tri-e". While "tri-" is held the bells answer with the logo, in D. "Le jour de" runs
    # straight into the closed logo, which ends the line in the anthem's place ("...est ar-ri-ve!"),
    # over its own cadence: D, D, A7, D.
    notes = (P.LABELS[0], P.LABELS[1], P.TIME_IN, P.TEMP_IN)
    for when, note in zip(notes, OPEN):
        desk.add(harpsichord(note, 1.2, 1.0), when, 0.28, -0.2, hall=0.3)
        desk.add(vibes(note + 12, 1.6, 0.8), when, 0.18, 0.25, hall=0.35)
        desk.add(J.bell(note + 24, 1.2, 0.5), when, 0.06, 0.1, hall=0.4)
    for when in (P.TIME_IN, P.TEMP_IN):                              # the flips
        desk.add(glide(700, 1600, 0.12), when - 0.1, 0.06, 0.0)
        desk.add(clack(0.9), when, 0.2, 0.0)
    al = P.TEMP_IN                                                   # the logo's A is "Al-"
    anthem = ((57, 0, 0.75), (57, 0.75, 0.25), (57, 1, 1), (62, 2, 1), (62, 3, 1), (64, 4, 1), (64, 5, 1),
              (69, 6, 1.5), (66, 7.5, 0.5), (62, 8, 1),            # Al-lons en-fants de la Pa-tri-e
              (62, 9.5, 0.75), (66, 10.25, 0.25), (62, 10.5, 0.5))  # Le jour de... (the closed logo)
    for note, beat, beats in anthem:
        when, gate = al + beat * BEAT, beats * BEAT * 0.9
        desk.wide(lambda n=note, g=gate: J.brass(n, g, 1.0), when, 0.17, 0.25, hall=0.3)
        desk.add(fife(note + 12, gate, 0.9), when, 0.18 if beat else 0.1, -0.3, hall=0.35)
    for k, note in enumerate((74, 78, 81, 83)):                      # the bells answer under "tri-"
        desk.add(J.bell(note + 12, 0.9, 0.6), al + (6.25 + 0.25 * k) * BEAT, 0.09, 0.4 - 0.2 * k, hall=0.45)
        desk.add(vibes(note, 0.8, 0.6), al + (6.25 + 0.25 * k) * BEAT, 0.1, 0.4 - 0.2 * k, hall=0.35)
    harmony = ((1, 3, (50, 57, 62, 66)), (3, 4, (50, 57, 62, 66)), (4, 6, (45, 57, 61, 64)),
               (6, 8, (45, 55, 61, 64)), (8, 9, (50, 57, 62, 66)), (9, 11, (43, 55, 59, 62)))
    for b0, b1, chord in harmony:
        when = al + b0 * BEAT
        for i, note in enumerate(chord[1:]):
            desk.add(harpsichord(note, (b1 - b0) * BEAT, 0.6), when + 0.02 * i, 0.1, 0.35 - 0.2 * i, hall=0.3)
        desk.add(pizz(chord[0] - 12, 0.9), when, 0.26, -0.1, hall=0.25)
    for beat in range(1, 11):                                        # the drum, the anthem's march
        when = al + beat * BEAT
        desk.add(J.snare(0.6 if beat % 2 else 0.4), when, 0.26, 0.1, hall=0.15, room=0.3)
        desk.add(J.snare(0.3), when + BEAT * 0.75, 0.2, 0.1, room=0.3)
        if beat % 2:
            desk.add(J.timpani(38 if beat % 4 == 1 else 33, 0.7), when, 0.3, hall=0.35)
    field_roll(desk, P.LOGO[0] - 0.5, 0.48, 0.3, 0.9, gain=0.3)
    desk.wide(lambda: J.pad_voice((50, 57, 62, 66), 2.0, 0.4, 1.0), P.LOGO[0], 0.07, hall=0.45)
    S.logo(desk, P.LOGO[0], CLOSED, organ_=False, choir=True, gain=0.8)
    cadence = ((50, 57, 62, 66), (50, 57, 62, 66), (45, 55, 61, 64), (38, 57, 62, 66))   # D, D, A7, D
    for i, (when, note) in enumerate(zip(at_logo(P.LOGO[0]), CLOSED)):
        gate = RHYTHM[i][1] * BEAT * 0.92
        desk.add(fife(note + 12, gate, 0.9), when, 0.2, -0.3, hall=0.4)
        desk.add(church_bell(note, 2.0, 0.7), when, 0.15, 0.3, hall=0.5)
        for k, chord_note in enumerate(cadence[i]):
            desk.wide(lambda n=chord_note, g=gate: J.brass(n, g, 0.9), when, 0.07, hall=0.3)
    desk.add(J.timpani(38, 0.9), P.LOGO[3], 0.35, hall=0.4)
    return mixdown(desk, voice, length, end, grit=0.5)



# ---------------------------------------------------------------- Halloween

def theremin(f0, f1, length, vel=1.0):
    """A theremin: a pure tone sliding between pitches with a slow, wide vibrato."""
    n = int(length * SR)
    t = J.times(n)
    f = np.geomspace(f0, f1, n) * (1 + 0.012 * np.sin(2 * np.pi * 5.2 * t) * np.clip(t / 0.3, 0, 1))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.08 * np.sin(4 * np.pi * np.cumsum(f) / SR)
    return x * np.clip(t / 0.25, 0, 1) * np.clip((length - t) / 0.4, 0, 1) * vel * 0.4


def thunder(length=2.6, vel=1.0):
    """A crack and a long low rumble that rolls about."""
    n = int(length * SR)
    t = J.times(n)
    crack = J.butter(J.noise(n), 'high', 1500) * np.exp(-t / 0.05)
    rumble = J.butter(J.noise(n), 'low', 160) * np.exp(-t / 0.9) * (1 + 0.6 * np.sin(2 * np.pi * 3.1 * t) * np.sin(2 * np.pi * 0.7 * t))
    return np.tanh((0.5 * crack + 3.0 * rumble) * vel) * 0.7


def music_box(midi, vel=1.0):
    """A music box's comb: a bright, short tine, detuned a hair against itself."""
    return (J.bell(midi, 1.6, vel) + 0.6 * J.bell(midi + 0.18, 1.6, vel * 0.8)) * 0.6


def wind(length, vel=1.0):
    n = int(length * SR)
    t = J.times(n)
    x = J.butter(J.noise(n), 'band', [250, 900]) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.23 * t) * np.sin(2 * np.pi * 0.11 * t + 1))
    rain = J.butter(J.noise(n), 'high', 3500) * 0.35
    return (x + rain) * np.clip(t / 0.8, 0, 1) * vel * 0.5



def cat_witching_hour(voice):
    """Halloween, after dark: wind and rain at the window, a low drone,
a heartbeat; a glassy shiver and a theremin when the eyes open in the corner; the open logo
on a music box, a little out of tune, with a flare, thunder on the second note, a deep swell
when the shadow opens its eyes and a floorboard's creak as the cat turns; the closed logo on a
haunted pipe organ and choir with a tolling bell and thunder on the last note; silence."""
    P = hits('cat-witching-hour')
    length, end = P.DURATION, P.IRIS_CLOSE[1]
    desk = S.Desk(length)
    desk.wide(lambda: wind(length - 0.2, 1.0), 0.0, 0.18, hall=0.2)
    desk.wide(lambda: J.pad_voice((38, 45, 50, 53), P.LOGO[0] - 0.2, 1.5, 1.2), 0.0, 0.07, hall=0.5)   # D minor, low
    for k in range(9):                                               # a heartbeat
        when = 1.2 + k * 0.92
        if when > P.LOGO[0] - 0.3:
            break
        desk.add(J.kick(0.5), when, 0.25, hall=0.2)
        desk.add(J.kick(0.35), when + 0.22, 0.2, hall=0.2)
    for i, note in enumerate((93, 94, 99)):                          # the eyes in the corner
        desk.add(glass(note, 1.6, 0.4), P.CORNER_EYES[0] + 0.05 * i, 0.05, -0.8, hall=0.6)
    desk.add(theremin(440, 330, 1.4), P.CORNER_EYES[0] + 0.2, 0.12, -0.6, hall=0.5)
    desk.add(click(0.6), 2.85, 0.1, -0.8, hall=0.4)                # it blinks
    for when, note in zip(P.NOTES, OPEN):                            # the open logo, on a music box
        desk.add(music_box(note + 24, 0.9), when, 0.22, 0.2, hall=0.6)
        desk.add(vibes(note + 12, 1.8, 0.5), when, 0.08, -0.2, hall=0.5)
    desk.add(J.whoosh(0.4), P.FLARE - 0.1, 0.12, 0.6, hall=0.3)
    desk.wide(lambda: thunder(2.6, 1.0), P.LIGHTNING[0], 0.55, hall=0.3)
    desk.add(sub(38, 1.6, 0.8), P.SHADOW_EYES, 0.3, hall=0.3)      # the shadow opens its eyes
    desk.wide(lambda: J.pad_voice((37, 44, 49), 1.4, 0.3, 0.8), P.SHADOW_EYES, 0.1, hall=0.5)
    desk.add(squeak(P.TURN[1] - P.TURN[0] + 0.2, 0.6, seed=3), P.TURN[0], 0.18, 0.1, hall=0.4)   # the floorboard
    desk.add(theremin(330, 523, 1.6), P.TURN[0], 0.12, 0.3, hall=0.5)
    desk.wide(lambda: J.pad_voice((38, 45, 50, 53, 57), P.LOGO[0] - P.TURN[1], 0.8, 0.8), P.TURN[1], 0.06, hall=0.5)
    for k, when in enumerate(at_logo(P.LOGO[0])):                    # the closed logo, a haunted organ
        note = CLOSED[k]
        gate = RHYTHM[k][1] * BEAT * 0.95
        desk.add(pipe_organ(note, gate + 0.2, 0.9), when, 0.3, -0.2, hall=0.6)
        desk.add(pipe_organ(note - 12, gate + 0.2, 0.8), when, 0.22, 0.2, hall=0.6)
        desk.add(J.choir(note, gate, 0.9), when, 0.35, 0.3, hall=0.6)
        desk.add(music_box(note + 24, 0.7), when, 0.1, 0.4, hall=0.6)
    desk.add(church_bell(50, 3.5, 1.0), P.LOGO[0], 0.35, -0.3, hall=0.6)
    desk.add(church_bell(50, 3.0, 0.8), P.LOGO[3], 0.3, -0.3, hall=0.6)
    desk.wide(lambda: thunder(2.0, 0.9), P.LOGO[3], 0.45, hall=0.3)
    desk.wide(lambda: J.pad_voice((50, 54, 57, 62), 1.6, 0.3, 0.6), P.LOGO[3], 0.07, hall=0.5)
    desk.add(theremin(587, 440, 1.0), P.BLINK[0], 0.08, 0.4, hall=0.6)
    return mixdown(desk, voice, length, end, grit=0.6)



def excerpt(cut):
    """A 5-second cutdown's sound (promos/cutdown.py): its source's music without the voice,
    cut into the same pieces as the picture (a short fade at each splice, and in, when the
    cut starts mid-cue), the lines it keeps laid back over it, and silence by the end."""
    P = hits(cut)
    music = render(P.SOURCE, voiced=False)
    length = sum(b - a for a, b in P.PIECES)
    out = np.zeros((2, int(round(length * SR))))
    edge = int(0.008 * SR)
    at = 0
    for k, (a, b) in enumerate(P.PIECES):
        piece = music[:, int(round(a * SR)):int(round(b * SR))].copy()
        piece = piece[:, :out.shape[1] - at]
        fade_in = int(0.06 * SR) if k == 0 and a > 0 else edge if k else 0
        if fade_in:
            piece[:, :fade_in] *= np.sin(np.linspace(0, np.pi / 2, fade_in)) ** 2
        if k < len(P.PIECES) - 1:
            piece[:, -edge:] *= np.cos(np.linspace(0, np.pi / 2, edge)) ** 2
        out[:, at:at + piece.shape[1]] += piece
        at += piece.shape[1]
    voice = np.zeros(out.shape[1])
    for line_id, when in P.LINES:
        x = load_line(line_id)
        start = int(when * SR)
        end = min(len(voice), start + len(x))
        voice[start:end] += x[:end - start]
        print(f'  voice: {line_id} {when:.2f}-{end / SR:.2f} s')
    if voice.any():
        out *= J.duck(voice, 7.0)
        plate = J.impulse(1.2, 0.7, 0.012, 6000)
        wet = np.array([signal.fftconvolve(voice * 0.12, plate[c])[:len(voice)] for c in range(2)])
        out = J.limiter(out + np.array([voice, voice]) * 1.6 + wet)
    t = J.times(out.shape[1])
    return out * np.sin(np.clip((length - 0.06 - t) / 0.15, 0, 1) * np.pi / 2) ** 2


CUES = {'time-temp': (10.0, time_temp), 'watching': (10.0, watching), 'only-on': (10.0, only_on),
        'legal': (5.0, legal), 'press-start': (5.0, press_start), 'metro': (10.0, metro), 'dupont': (10.0, dupont),
        'meridian-hill': (10.0, meridian_hill), 'now-in-hd': (10.0, now_in_hd), 'cat-remote': (10.0, cat_remote),
        'cat-laser': (10.0, cat_laser), 'baseball': (10.0, baseball), 'football': (10.0, football),
        'eighty-six': (10.0, eighty_six), 'seventy-six': (10.0, seventy_six),
        'ninety-six': (10.0, ninety_six), 'twenty-sixteen': (10.0, twenty_sixteen),
        'the-cairo': (10.0, the_cairo), 'cairo-1894': (10.0, cairo_1894),
        'cat-field-goal': (10.0, cat_field_goal), 'happy-little': (10.0, happy_little), 'popcorn': (10.0, popcorn),
        'forecast': (10.0, forecast), 'halftime': (10.0, halftime), 'hail-mary': (10.0, hail_mary),
        'metro-5': (5.0, lambda voice: excerpt('metro-5')), 'baseball-5': (5.0, lambda voice: excerpt('baseball-5')),
        'cat-remote-5': (5.0, lambda voice: excerpt('cat-remote-5')),
        'heure-decimale': (10.0, heure_decimale), 'cat-witching-hour': (10.0, cat_witching_hour)}


def render(promo_id, voiced=True):
    length, make = CUES[promo_id]
    voice, lines = voice_track(promo_id, length, voiced)
    return make(voice, lines) if promo_id == 'watching' else make(voice)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    promo_id, out = args[0], Path(args[1])
    mix = render(promo_id, voiced='--no-voice' not in argv)
    out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out, SR, mix.T.astype(np.float32))
    peak = 20 * np.log10(np.abs(mix).max() + 1e-12)
    print(f'  {promo_id}: {mix.shape[1] / SR:.2f} s, peak {peak:.1f} dBFS -> {out}')


if __name__ == '__main__':
    main(sys.argv)
