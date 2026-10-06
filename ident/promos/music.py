"""The station promos' sound: the sonic identity's family (ident/sonic.py, jingle.py) in
five short cues, with their voice lines (script.json, voiced by voice.py) mixed over them.

    python music.py ID OUT.wav [--no-voice]     (needs numpy and scipy)

Each cue keeps the rules: the four-note logo, open (C E G A) for "there's more" and
closed (D F# A D), up a whole step, for the answer; 120 BPM; a silent tail. The build
(build.py) levels the result to -20 LUFS, as the station ID is. --no-voice writes the music
alone: 'only-on' is voiced again over it for each programme (roku_stream/promos.py).
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import jingle as J  # noqa: E402
import sonic as S  # noqa: E402

SR = J.SR
BEAT = 0.5
OPEN, CLOSED = S.LOGO_OPEN, S.LOGO_CLOSED
RHYTHM = S.LOGO_RHYTHM
rng = np.random.default_rng(1979)


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
    period = max(2, int(round(SR / float(J.hz(midi)))))
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


CUES = {'time-temp': (10.0, time_temp), 'watching': (10.0, watching), 'only-on': (10.0, only_on),
        'legal': (5.0, legal), 'press-start': (5.0, press_start)}


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
