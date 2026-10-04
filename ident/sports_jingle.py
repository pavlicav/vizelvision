"""The VizelVision Sports ID's music, with its presentation line mixed over it.

The station ID's form and hit points (jingle.py), played the way the sonic identity
says sport sounds (sonic.py): the floodlights coming on bank by bank in a waiting
stadium, a drumline march, the ballpark organ, a crowd that claps the logo, the
stadium horn, and a little tape grit. The open logo (C E G A) lands on the first hit;
the line is read over the quiet middle; SPORTS stamps in with a roar; and the closed
logo (D F# A D), sung, lands on the key change, as in the ID.

    python sports_jingle.py OUT.wav     (needs numpy and scipy)
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jingle as J  # noqa: E402  The ID's instruments, voice handling and limiter.
import sonic as S  # noqa: E402  The ballpark instruments and the grit.
import sports_timeline as T  # noqa: E402

SR = J.SR
B = T.BEAT
at = J.at  # Seconds for a position in bars (1-based) and beats.


# ---------------------------------------------------------------- stadium sounds

def clunk(vel=1.0):
    """A floodlight bank switching on: the contactor's double clack, a thump through the
    steelwork, and the lamps' hum swelling and settling."""
    n = int(2.2 * SR)
    t = J.times(n)
    thump = np.sin(2 * np.pi * np.cumsum(36 + 70 * np.exp(-t / 0.03)) / SR) * np.exp(-t / 0.2)
    clack = np.zeros(n)
    m = int(0.03 * SR)
    for when, level in ((0.0, 1.0), (0.019, 0.55)):
        k = int(when * SR)
        clack[k:k + m] += J.butter(J.noise(m), 'band', [1400, 7000]) * np.exp(-J.times(m) / 0.004) * level
    hum = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((120, 1.0), (240, 0.5), (360, 0.3), (480, 0.15)))
    hum = np.tanh(2 * hum) * np.clip(t / 0.25, 0, 1) * np.exp(-np.maximum(t - 0.25, 0) / 0.6)
    return (0.9 * thump + 0.6 * clack + 0.06 * hum) * vel


def roar(length, rise=0.12, fall=1.2):
    """The crowd going up: a roar and its shouts, rising over `rise` and settling with `fall`."""
    n = int(length * SR)
    t = J.times(n)
    body = J.butter(J.noise(n), 'band', [220, 2800])
    shouts = J.butter(J.noise(n), 'band', [1200, 4800]) * (1 + 0.5 * np.sin(2 * np.pi * 3.1 * t))
    env = np.clip(t / rise, 0, 1) ** 1.5 * np.exp(-np.maximum(t - rise, 0) / fall)
    return (body + 0.45 * shouts) * env * np.clip((length - t) / 0.3, 0, 1)


def faded(x, fade_in=0.3, fade_out=0.6):
    """A crowd clip that comes and goes smoothly, without a click at either end."""
    t = J.times(len(x))
    return x * np.clip(t / fade_in, 0, 1) * np.clip((len(x) / SR - t) / fade_out, 0, 1)


def cadence(desk, bar, vel=1.0):
    """A drumline bar: sixteenths on the snare line, accents on the beat, flams on two and
    four, and the bass drums on one and three."""
    for k in range(16):
        b = k / 4
        accent = k % 4 == 0
        level = vel * (0.85 if accent else 0.32 + 0.12 * (k % 2 == 0))
        desk.add(J.snare(level), at(bar, b), 0.4, 0.15, hall=0.05, room=0.2)
        if accent and k // 4 in (1, 3):
            desk.add(J.snare(level * 0.6), at(bar, b) - 0.02, 0.35, -0.15, hall=0.05, room=0.2)
    for b in (0, 2):
        desk.add(J.kick(0.9 * vel), at(bar, b), 0.85, hall=0.08)
        desk.add(J.tom(38, 0.5 * vel), at(bar, b), 0.3, hall=0.15)


def march(desk, bar, root, chord, vel=1.0):
    """Oom-pah: root and fifth in the bass, the organ on the off-beats, brass on one."""
    for b, interval in ((0, 0), (1, 7), (2, 0), (3, 7)):
        desk.add(J.bass(root + interval, 0.42 * B, 0.95 * vel), at(bar, b), 0.5)
    for b in (0.5, 1.5, 2.5, 3.5):
        for note in chord:
            desk.add(S.organ(note, 0.32 * B, 0.7), at(bar, b), 0.06 * vel, 0.25, hall=0.15)
    for i, note in enumerate(chord):
        desk.add(J.brass(note, 0.9 * B, 0.85 * vel), at(bar, 0), 0.1, -0.4 + i * 0.4, hall=0.25)


# ---------------------------------------------------------------- the arrangement

def compose(desk):
    # Channel change: the ID's click and static, under the picture's snow.
    desk.add(J.static_burst(T.STATIC_END + 0.05), 0.0, 0.7, hall=0.0)

    # Bars 1-2: a dark stadium. The floodlights come on bank by bank over a waiting
    # crowd, then the ID's own bVI - bVII swell, and the stadium horn, into the hit.
    desk.add(faded(S.crowd(T.HIT + 1.0, swell=(T.LIGHTS[0], T.HIT)), 0.6, 0.8), 0.0, 0.25, hall=0.15)
    for i, (when, pan) in enumerate(zip(T.LIGHTS, (-0.7, 0.7, -0.3, 0.3))):
        desk.add(clunk(0.65 + 0.12 * i), when, 0.5, pan, hall=0.5)
        desk.add(J.timpani((36, 36, 43, 43)[i], 0.55 + 0.15 * i), when, 0.4, hall=0.35)
    desk.add(S.organ(36, 2 * B * 3.8, 0.5), T.LIGHTS[0], 0.08, hall=0.4)
    for chord, b, vel in (((44, 56, 60, 63, 68, 72), 4, 0.7), ((46, 58, 62, 65, 70, 74), 6, 0.9)):
        for i, note in enumerate(chord):
            desk.add(J.brass(note, 1.9 * B, vel, attack=0.12), at(1, b), 0.14, -0.5 + i * 0.2, hall=0.3)
        desk.add(J.bass(chord[0] - 12, 1.9 * B), at(1, b), 0.55)
        desk.wide(lambda c=chord: J.pad_voice(c[1:], 1.9 * B, 0.3, 0.4), at(1, b), 0.1)
    desk.add(S.horn(1.3, 41), T.LIGHTS[3], 0.32, hall=0.35)
    J.snare_roll(desk, 4, 4, 0.15, 0.95)
    desk.add(J.whoosh(T.HIT - T.LOGO_FLIGHT), T.LOGO_FLIGHT, 0.45, hall=0.2)
    reverse = J.crash(1.0, 1.4)[::-1]
    desk.add(reverse, T.HIT - len(reverse) / SR, 0.5, hall=0.1)

    # The hit: the emblem lands, the crowd goes up, and the open logo.
    J.hit(desk, 60, T.HIT)
    desk.add(roar(3.2, 0.08, 1.3), T.HIT, 0.32, hall=0.3)
    S.logo(desk, T.HIT, S.LOGO_OPEN)

    # The wordmark types itself in: the ballpark organ runs up a note per letter.
    letters = sum(len(part) for part in T.WORDMARK)
    scale = (60, 62, 64, 67, 69, 72, 74, 76, 79, 81, 84)
    for i in range(letters):
        pan = -0.7 + 1.4 * i / (letters - 1)
        when = T.LETTERS + i * T.LETTER_STEP
        desk.add(S.organ(scale[i % len(scale)], 0.4 * B, 0.9), when, 0.11, pan, hall=0.2)
        desk.add(J.marimba(scale[i % len(scale)] + 12, 0.6), when, 0.1, pan, hall=0.2)

    # Bars 3-6: the march. I - vi - IV - V on the drumline, with the crowd clapping the
    # logo in bar 5 and the organ answering with it in bar 6.
    for i, (root, chord) in enumerate(((36, (60, 64, 67)), (33, (57, 60, 64)), (41, (57, 60, 65)),
                                       (43, (55, 59, 62))), 3):
        cadence(desk, i)
        march(desk, i, root, chord)
    desk.add(J.crash(0.8, 2.4), at(5), 0.3, 0.4, hall=0.3)
    desk.add(faded(S.crowd(5.0, claps=S.claps(0.2))), T.CLAPS[0] - 0.2, 0.35, hall=0.15)
    for (offset, length), note in zip(S.LOGO_RHYTHM, S.LOGO_OPEN):
        desk.add(S.organ(note, length * B * 0.8, 1.0), at(6) + offset * B, 0.16, 0.2, hall=0.2)
    for i, note in enumerate((84, 88, 91, 96)):
        desk.add(J.bell(note, 1.5, 0.7), T.SWEEP + i * B / 8, 0.1, 0.5 - i * 0.3, hall=0.5)

    # Bars 7-9: the line, read over a hush. Fmaj7 - Em7 - Dm7, the ID's chords under its
    # voice, with the crowd murmuring and the drumline on its rims.
    desk.add(faded(S.crowd(T.BANNER - T.RIBBON + 0.8), 0.8, 0.6), T.RIBBON, 0.18, hall=0.2)
    for i, (root, chord) in enumerate(((41, (57, 60, 64, 65)), (40, (55, 59, 62, 64)), (38, (53, 57, 60, 62)))):
        bar = 7 + i
        desk.wide(lambda c=chord: J.pad_voice(c, 3.9 * B, 0.4, 0.6), at(bar), 0.1)
        for note in chord[:2]:
            desk.add(S.organ(note - 12, 3.7 * B, 0.5), at(bar), 0.05, -0.2, hall=0.3)
        for b, interval, beats in ((0, 0, 1.4), (2, 7, 1.4)):
            desk.add(J.bass(root + interval, beats * B, 0.7), at(bar, b), 0.45)
        desk.add(J.kick(0.6), at(bar), 0.6, hall=0.03)
        for b in (1, 3):
            desk.add(J.clap(0.35), at(bar, b), 0.45, 0.2, hall=0.12)
        for k in range(8):
            desk.add(J.hat(0.3), at(bar, k / 2), 0.35, 0.35, hall=0.03)

    # SPORTS stamps in: a crack, the crowd, and the stadium horn.
    J.hit(desk, 55, T.BANNER)
    desk.add(J.snare(1.0), T.BANNER, 0.75, hall=0.05, room=0.9)
    desk.add(roar(3.0, 0.1, 1.1), T.BANNER, 0.36, hall=0.3)
    desk.add(S.horn(1.0, 43), T.BANNER, 0.28, hall=0.35)
    for k, note in enumerate((50, 48, 45, 43)):  # Tom pickup into bar 10.
        desk.add(J.tom(note, 0.8), at(9, 3 + k * 0.25), 0.6, 0.5 - k * 0.33, hall=0.2)

    # Bar 10: the clap. The crowd claps the logo, the organ plays it with them.
    cadence(desk, 10)
    march(desk, 10, 43, (55, 60, 62, 67))
    desk.add(faded(S.crowd(4.0, claps=S.claps(0.2))), T.CLAPS[1] - 0.2, 0.4, hall=0.15)
    for (offset, length), note in zip(S.LOGO_RHYTHM, S.LOGO_OPEN):
        desk.add(S.organ(note, length * B * 0.8, 1.0), T.CLAPS[1] + offset * B, 0.16, -0.2, hall=0.2)

    # Bars 11-12: the build, bVI - bVII of the new key, as in the ID, with the crowd rising.
    for i, (root, chord, vel) in enumerate(((46, (58, 62, 65, 70), 0.6), (48, (60, 64, 67, 72), 0.85))):
        bar = 11 + i
        desk.wide(lambda c=chord: J.pad_voice(c, 3.9 * B, 0.6, 0.3), at(bar), 0.12)
        for j, note in enumerate(chord):
            desk.add(J.brass(note, 3.8 * B, vel, attack=0.9), at(bar), 0.12, -0.4 + j * 0.27, hall=0.3)
        for k in range(8):
            desk.add(J.bass(root, 0.4 * B, 0.7 + 0.03 * k), at(bar, k * 0.5), 0.5)
        for b in range(4):
            desk.add(J.kick(0.75 + 0.05 * i), at(bar, b), 0.85, hall=0.02)
        for k in range(16):
            desk.add(J.hat(0.35 + 0.02 * k), at(bar, k * 0.25), 0.5, 0.35, hall=0.03)
    J.snare_roll(desk, 44, 4, 0.2, 1.0)
    desk.add(roar(4 * B * 2, 4 * B * 2, 9.0), at(11), 0.2, hall=0.3)
    desk.add(J.riser(4 * B, 8000), at(12), 0.35, hall=0.2)
    desk.add(reverse, T.KEY_CHANGE - len(reverse) / SR, 0.5, hall=0.1)

    # The key change: the closed logo, sung, with the horn and a roar.
    J.hit(desk, 62, T.KEY_CHANGE)
    S.logo(desk, T.KEY_CHANGE, S.LOGO_CLOSED, choir=True)
    for (offset, length), note in zip(S.LOGO_RHYTHM, (69, 74, 78, 81)):
        desk.add(J.choir(note, length * B * 0.95), T.KEY_CHANGE + offset * B, 0.35, 0.35, hall=0.45)
    desk.add(S.horn(1.7, 38), T.KEY_CHANGE, 0.3, hall=0.35)
    desk.add(roar(4.0, 0.1, 1.6), T.KEY_CHANGE, 0.34, hall=0.3)
    desk.wide(lambda: J.pad_voice((62, 66, 69, 74), 1.9 * B, 0.1, 0.3), at(13), 0.12)
    desk.wide(lambda: J.pad_voice((67, 69, 71, 74), 1.9 * B, 0.1, 0.3), at(13, 2), 0.12)
    for b, note in ((0, 38), (0.75, 50), (1.5, 38), (2, 45), (2.75, 57), (3, 45)):
        desk.add(J.bass(note, 0.45 * B, 1.0), at(13, b), 0.55)
    for b in (0, 1.5, 2):
        desk.add(J.kick(1.0), at(13, b), 0.9, hall=0.02)
    desk.add(J.snare(1.0), at(13, 1), 0.75, hall=0.05, room=0.9)
    for k in range(12):
        desk.add(J.hat(0.6), at(13, k * 0.25), 0.5, 0.35, hall=0.03)
    for k, note in enumerate((57, 55, 52, 50)):  # Tom fill into the button.
        desk.add(J.tom(note, 0.9), at(13, 3 + k * 0.25), 0.7, 0.5 - k * 0.33, hall=0.2)

    # The button: D major rings out over the crowd.
    J.hit(desk, 62, T.BUTTON, big=True)
    for i, note in enumerate((50, 57, 62, 66, 69, 74, 78)):
        desk.add(J.brass(note, 1.6, 1.0), T.BUTTON, 0.12, -0.6 + i * 0.2, hall=0.4)
    for note, pan in ((62, -0.5), (66, 0.5), (69, -0.2), (74, 0.2)):
        desk.add(J.choir(note, 1.9, 0.9), T.BUTTON, 0.32, pan, hall=0.5)
    desk.add(S.organ(50, 1.7, 0.8), T.BUTTON, 0.1, hall=0.3)
    desk.add(J.bass(38, 1.8, 1.0), T.BUTTON, 0.6)
    desk.add(roar(T.BLACK - T.BUTTON, 0.1, 1.0), T.BUTTON, 0.3, hall=0.3)
    for i, note in enumerate((86, 90, 93, 98)):
        desk.add(J.bell(note, 2.2, 0.8), T.BUTTON + 0.05 + i * B / 8, 0.13, -0.5 + i * 0.33, hall=0.55)
    desk.add(J.bell(98, 3.0, 0.5), T.IRIS, 0.08, 0.2, hall=0.6)  # A last glint as the iris closes.


# ---------------------------------------------------------------- voice and master

def master(desk, voice):
    """The music through the grit, ducked under the line; levelled like the ID."""
    music = S.grit(desk.mix(), 0.6)
    music *= J.duck(voice, 6.0)
    plate = J.convolve(np.array([voice, voice]) * 0.12, J.impulse(1.2, 0.7, 0.012, 6000))
    mix = music * 0.6 + np.array([voice, voice]) * 1.25 + plate
    # Set the march at a healthy level, as the ID sets its groove, and let the limiter take the hits.
    groove = mix[:, int(T.HIT * SR) + SR // 4:int(T.RIBBON * SR)]
    mix *= 10 ** (-13 / 20) / np.sqrt(np.mean(groove ** 2))
    mix = J.limiter(mix)
    t = J.times(J.N)
    fade = np.clip((T.BLACK - t) / (T.BLACK - 28.4), 0, 1)
    return mix * np.sin(fade * np.pi / 2) ** 2


def report(mix):
    """Levels by section: the line should sit well above the music around it."""
    for name, a, b in (('lights', 0.5, 4.5), ('march', 4.6, 12.4), ('line', T.WORDS[0][1], T.WORDS[-1][2]),
                       ('banner', T.BANNER, T.BANNER + 1.0), ('build', 20.5, 24.4), ('button', 24.5, 27.5)):
        seg = mix[:, int(a * SR):int(b * SR)]
        rms = 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        print(f'  level {name:8s} {rms:6.1f} dBFS rms')


def main(argv):
    paths = [a for a in argv[1:] if not a.startswith('--')]
    out = Path(paths[0]) if paths else HERE / 'build' / 'sports-audio.wav'
    script = {'lines': []} if '--no-voice' in argv else json.loads((HERE / 'sports_script.json').read_text())
    desk = S.Desk(T.DURATION)
    compose(desk)
    voice = J.voice_track(script)
    mix = master(desk, voice)
    out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out, SR, mix.T.astype(np.float32))
    report(mix)
    print(f'  audio: {out}')


if __name__ == '__main__':
    main(sys.argv)
