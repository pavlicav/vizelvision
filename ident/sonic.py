"""The VizelVision sonic identity: what every promo, bumper and ID shares, and sketches
of the family, played on the station ID's own instruments (jingle.py) plus a stadium
organ, a crowd and a stadium horn, through a little tape grit.

    python sonic.py OUT_DIR        render the sketches (needs numpy and scipy; ffmpeg)

The rules live in the master sheet. In short:
- The logo: "Viz-el-Vi-sion", four notes in the rhythm eighth, eighth, quarter, half.
  Open (a question: there's more): C E G A, ending on the sixth.
  Closed (an answer: here it is, final): up a whole step, D F# A D, on the tonic.
- The lift: a change of key is always up a whole step, C to D.
- The clap: the logo's rhythm, clapped. Crowds and percussion carry it.
- Tempo 120 (a march, and the ballpark organ's tempo); late night 96.
- Delivery: -20 LUFS integrated, -2 dBTP, 48 kHz stereo; the last half second silent.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jingle as J  # noqa: E402  The ID's instruments.

SR = J.SR
BPM, LATE_NIGHT_BPM = 120, 96
BEAT = 60 / BPM
LOGO_RHYTHM = ((0, .5), (.5, .5), (1, 1), (2, 2))   # beats: offset, length
LOGO_OPEN = (72, 76, 79, 81)       # C E G A: the question
LOGO_CLOSED = (74, 78, 81, 86)     # D F# A D: the answer, up a step
HOME, LIFT = 60, 62                # C, and D a whole step up
LOUDNESS, TRUE_PEAK = -20.0, -2.0  # As the ID and the TV recordings
TAIL = 0.5                         # Silence at the end, so any cut is clean
rng = np.random.default_rng(1971)


# ---------------------------------------------------------------- new instruments

def organ(midi, gate, vel=1.0):
    """A ballpark tonewheel organ: drawbars 16' 8' 4' 2 2/3' 2', key click, a Leslie's
    swirl, and a little overdrive."""
    n = int((gate + 0.08) * SR)
    t = J.times(n)
    f = J.hz(midi) * (1 + 0.003 * np.sin(2 * np.pi * 6.3 * t))  # the Leslie horn's Doppler
    phase = 2 * np.pi * np.cumsum(np.broadcast_to(f, (n,))) / SR
    x = sum(w * np.sin(phase * h) for h, w in ((0.5, .55), (1, 1.0), (2, .7), (3, .35), (4, .45)))
    x *= 1 + 0.18 * np.sin(2 * np.pi * 6.3 * t + 1.1)          # and its tremolo
    x += 0.25 * J.noise(n) * np.exp(-t / 0.004)                  # key click
    env = np.clip(t / 0.006, 0, 1) * np.clip((gate + 0.06 - t) / 0.06, 0, 1)
    return np.tanh(1.6 * x * env * vel) * 0.5


def crowd(length, swell=None, claps=()):
    """A ballpark crowd: murmur, an optional swell to a roar, and claps at given times."""
    n = int(length * SR)
    t = J.times(n)
    murmur = J.butter(J.noise(n), 'band', [250, 2600]) * (1 + 0.25 * np.sin(2 * np.pi * 0.7 * t))
    level = np.full(n, 0.25)
    if swell:
        start, peak = swell
        level += 0.9 * np.clip((t - start) / max(peak - start, 1e-3), 0, 1) ** 2
    x = murmur * level
    for when in claps:  # Many hands, a little apart.
        for _ in range(40):
            at = int((when + rng.normal(0, 0.012)) * SR)
            if 0 <= at < n - 800:
                burst = J.butter(J.noise(800), 'band', [900, 4000]) * np.exp(-J.times(800) / 0.012)
                x[at:at + 800] += burst * 0.08
    return x


def horn(length, midi=41):
    """A stadium horn: detuned saws a fifth apart, dark, with a shove at the start."""
    n = int(length * SR)
    t = J.times(n)
    x = sum(J.saw(J.hz(m) * J.cents(c), n) for m in (midi, midi + 7, midi + 12) for c in (-9, 0, 8))
    x = J.butter(x, 'low', 1400)
    env = np.clip(t / 0.05, 0, 1) * (1 + 0.3 * np.exp(-t / 0.2)) * np.clip((length - t) / 0.4, 0, 1)
    return np.tanh(0.5 * x * env)


def logo(desk, at, notes, *, organ_=True, choir=False, gain=1.0):
    """The four-note logo, on bells and brass (the ID's voicing), optionally organ and choir."""
    for (offset, length), note in zip(LOGO_RHYTHM, notes):
        when = at + offset * BEAT
        desk.add(J.bell(note, 2.6), when, 0.34 * gain, -0.15, hall=0.35)
        desk.add(J.bell(note + 12, 1.4, 0.6), when, 0.1 * gain, 0.3, hall=0.4)
        desk.wide(lambda n=note, l=length: J.brass(n, l * BEAT * 0.95, 0.9), when, 0.13 * gain, 0.3, hall=0.25)
        if organ_:
            desk.add(organ(note - 12, length * BEAT * 0.9, 0.8), when, 0.16 * gain, 0.2, hall=0.2)
        if choir:
            desk.add(J.choir(note, length * BEAT * 0.95), when, 0.45 * gain, -0.35, hall=0.45)


def claps(at, times=1):
    """The clap: the logo's rhythm, as a crowd claps it."""
    return [at + i * 4 * BEAT + offset * BEAT for i in range(times) for offset, _ in LOGO_RHYTHM]


# ---------------------------------------------------------------- desk and grit

class Desk(J.Desk):
    """The ID's desk at any length."""

    def __init__(self, length):
        self.n = int(length * SR)
        self.dry, self.hall, self.room = (np.zeros((2, self.n)) for _ in range(3))

    def add(self, sound, at, gain=1.0, pan=0.0, hall=0.15, room=0.0):
        start = int(round(at * SR))
        if start >= self.n or len(sound) == 0:
            return
        sound = sound[:self.n - start]
        angle = (np.clip(pan, -1, 1) + 1) * np.pi / 4
        for bus, amount in ((self.dry, 1.0), (self.hall, hall), (self.room, room)):
            if amount:
                bus[0, start:start + len(sound)] += sound * gain * amount * np.cos(angle) * np.sqrt(2)
                bus[1, start:start + len(sound)] += sound * gain * amount * np.sin(angle) * np.sqrt(2)

    def mix(self):
        def verb(bus, ir):
            return np.array([signal.fftconvolve(bus[c], ir[c])[:self.n] for c in range(2)])
        music = self.dry + verb(self.hall, J.impulse(2.2, 1.6)) * 0.9 + verb(self.room, J.gated_room()) * 0.5
        return J.butter(music, 'high', 35)


def grit(x, amount=1.0):
    """Vintage, a little gritty: tape saturation, wow and flutter, a softened top, and dust."""
    n = x.shape[1]
    t = J.times(n)
    drive = 1 + 1.4 * amount
    x = np.tanh(x * drive) / np.tanh(drive)
    # Wow (0.5 Hz) and flutter (6.5 Hz) as a wandering read-head delay.
    delay = (0.0018 + 0.0012 * np.sin(2 * np.pi * 0.5 * t) + 0.00012 * np.sin(2 * np.pi * 6.5 * t)) * amount * SR
    index = np.arange(n) - delay
    x = np.array([np.interp(index, np.arange(n), channel) for channel in x])
    x = J.butter(x, 'low', 12500 - 3000 * amount)
    dust = np.zeros(n)
    hits = rng.integers(0, n, int(n / SR * 9 * amount))
    dust[hits] = rng.normal(0, 0.12, len(hits))
    dust = J.butter(dust, 'high', 1800) + 0.004 * amount * J.butter(J.noise(n), 'band', [2000, 8000])
    return x + np.array([dust, np.roll(dust, 37)])


def finish(desk, length, amount=1.0):
    mix = grit(desk.mix(), amount)
    mix *= 10 ** (-14 / 20) / (np.sqrt(np.mean(mix ** 2)) + 1e-9)
    mix = J.limiter(mix)
    t = J.times(mix.shape[1])
    fade = np.clip((length - TAIL - t) / 0.35, 0, 1)  # Ring out, then the silent tail.
    return mix * np.sin(fade * np.pi / 2) ** 2


# ---------------------------------------------------------------- the family

def logo_open():
    """The logo, open: C E G A. Into a break, a promo's middle, "there's more"."""
    desk = Desk(3.5)
    logo(desk, 0.1, LOGO_OPEN)
    desk.add(J.pad_voice((60, 64, 67, 69), 2.4, 0.2, 0.8), 0.1, 0.1, hall=0.3)
    return finish(desk, 3.5)


def logo_closed():
    """The logo, closed: up a step, D F# A D, sung. Finals, sign-offs, "here it is"."""
    desk = Desk(4.0)
    desk.add(J.timpani(38, 0.8), 0.05, 0.4, hall=0.3)
    logo(desk, 0.1, LOGO_CLOSED, choir=True)
    desk.add(J.pad_voice((62, 66, 69, 74), 2.6, 0.1, 0.9), 0.1, 0.12, hall=0.35)
    J.hit(desk, LIFT, 0.1 + 2 * BEAT, big=False)
    return finish(desk, 4.0)


def sting():
    """The sting: a hit, then the open logo. Back to the game, a score, a replay."""
    desk = Desk(4.5)
    J.hit(desk, HOME, 0.05, big=True)
    desk.add(J.crash(0.9, 2.2), 0.05, 0.35, 0.4, hall=0.2)
    logo(desk, 0.05 + BEAT, LOGO_OPEN, gain=0.9)
    desk.add(crowd(4.5, swell=(0.0, 0.6)), 0, 0.25, 0.0, hall=0.1)
    return finish(desk, 4.5)


def bumper():
    """The bumper, 10 s: drumline cadence and organ call over the crowd, the crowd claps
    the logo, and the open logo leaves it hanging. Into and out of breaks."""
    length = 10.0
    desk = Desk(length)
    for bar in range(4):  # Drumline: a march cadence with flams on the backbeat.
        start = 0.1 + bar * 4 * BEAT
        for k in range(8):
            desk.add(J.snare(0.55 + 0.35 * (k % 2)), start + k * BEAT / 2, 0.5, 0.15, hall=0.05, room=0.4)
        desk.add(J.kick(1.0), start, 0.8)
        desk.add(J.kick(0.8), start + 2 * BEAT, 0.7)
    for bar, notes in ((0, LOGO_OPEN), (1, tuple(n + 12 for n in LOGO_OPEN)), (2, LOGO_CLOSED)):
        for (offset, length_), note in zip(LOGO_RHYTHM, notes):  # The organ's call: the logo, climbing.
            desk.add(organ(note - 12, length_ * BEAT * 0.55, 1.0), 0.1 + (bar * 4 + offset) * BEAT, 0.2, 0.2, hall=0.2)
    for bar, root in enumerate((48, 45, 50, 43)):
        desk.add(J.bass(root, 4 * BEAT * 0.9, 0.9), 0.1 + bar * 4 * BEAT, 0.45)
    for when in (0.1 + 11 * BEAT, 0.1 + 11.5 * BEAT):  # Brass pickups into the lift.
        for i, note in enumerate((62, 66, 69, 74)):
            desk.add(J.brass(note, 0.4 * BEAT, 0.9), when, 0.12, -0.4 + i * 0.25, hall=0.25)
    desk.add(crowd(length, swell=(3.0, 6.1), claps=claps(0.1 + 8 * BEAT, 1)), 0, 0.3, hall=0.1)
    logo(desk, 0.1 + 12 * BEAT, LOGO_OPEN)
    return finish(desk, length)


def final():
    """The final: the stadium horn and a roar, then the closed logo, sung, and the button."""
    length = 7.0
    desk = Desk(length)
    desk.add(horn(1.8), 0.05, 0.5, hall=0.25)
    desk.add(crowd(length, swell=(0.0, 1.2)), 0, 0.35, hall=0.15)
    desk.add(J.snare(1.0), 1.8, 0.3, hall=0.05, room=0.9)
    logo(desk, 2.0, LOGO_CLOSED, choir=True)
    J.hit(desk, LIFT, 2.0 + 2 * BEAT, big=True)
    return finish(desk, length)


def bed():
    """The bed, 8 s and loopable: organ comping, brushes and bass under scores and slates.
    No logo: it sits under voices. Its end meets its start."""
    length = 16 * BEAT
    desk = Desk(length)
    chords = ((60, 64, 67, 69), (57, 60, 64, 67), (53, 57, 60, 65), (55, 59, 62, 67))
    for bar, chord in enumerate(chords):
        start = bar * 4 * BEAT
        for b in (0.5, 1.5, 2.5, 3.5):
            for note in chord:
                desk.add(organ(note, 0.35 * BEAT, 0.6), start + b * BEAT, 0.07, 0.25, hall=0.15)
        desk.add(J.bass(chord[0] - 24, 3.6 * BEAT, 0.8), start, 0.4)
        for k in range(8):
            desk.add(J.hat(0.3 + 0.1 * (k % 2)), start + k * BEAT / 2, 0.35, 0.3, hall=0.05)
    mix = grit(desk.mix(), 0.8)
    mix *= 10 ** (-17 / 20) / (np.sqrt(np.mean(mix ** 2)) + 1e-9)
    return J.limiter(mix)  # No tail and no fade: a loop.


SKETCHES = {'logo-open': logo_open, 'logo-closed': logo_closed, 'sting': sting, 'bumper': bumper,
            'final': final, 'bed': bed}


def master(raw, out):
    """Two-pass loudness to -20 LUFS / -2 dBTP, like the ID, then an MP3 for listening."""
    report = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(raw), '-af',
                             f'loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:print_format=json', '-f', 'null', '-'],
                            capture_output=True, text=True, check=True).stderr
    import json
    m = json.loads(report[report.rindex('{'):report.rindex('}') + 1])
    level = (f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
             f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
             'linear=true,aresample=48000')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(raw), '-af', level, '-c:a', 'pcm_s16le',
                    str(out.with_suffix('.wav'))], check=True)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(out.with_suffix('.wav')), '-c:a', 'libmp3lame',
                    '-b:a', '192k', str(out.with_suffix('.mp3'))], check=True)
    return m['input_i']


def main(argv):
    out = Path(argv[1]) if len(argv) > 1 else HERE / 'build' / 'sonic'
    out.mkdir(parents=True, exist_ok=True)
    for name, make in SKETCHES.items():
        mix = make()
        raw = out / f'{name}.raw.wav'
        wavfile.write(raw, SR, mix.T.astype(np.float32))
        before = master(raw, out / name)
        raw.unlink()
        print(f'  {name:12s} {mix.shape[1] / SR:5.2f} s  {before} LUFS -> {LOUDNESS:g}')


if __name__ == '__main__':
    main(sys.argv)
