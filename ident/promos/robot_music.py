"""The Football Robot's sound (robot.py): an original pre-game theme in the big broadcast style,
built on the station's own logo notes. A brass section (bright trumpets, heavy low brass, all
synthesized here) with timpani, taiko, a marching snare and crashes, at the station's 120.

Cold open: two hard unison hits on D, then "Incoming." over a snare roll and the low brass
swelling on A as Unit 19 falls. The landing is the theme's downbeat, a D minor punch, and the
engine starts: low brass galloping in staccato 16ths (accents 3 + 3 + 2), the snare line on every
16th, timpani and taiko under it. The open logo is four brass stabs, one per robot move, C E G A on
top of F, A minor, C and D minor: the bass climbs with the tune. The gallop keeps going, low and
out of the way, under "Vizzle Vision... football..."; the punt is a B flat punch and the climb a C
stab and a swell. In orbit the band drops to a horn chorale (D minor, B flat, C) under
"...activated.", then A major swells into the return and the heroic climb, B flat and C, lands on D
major for the closed logo: D F# A D in the trumpets over the whole section, the last note ripped
up to as the meteor lands in its palm, held and swelling under a timpani roll, then one short
button with the cymbal choked.

The robot's own noises ride on top: the fall's jet scream, the landing's boom and sparks, servos
on every move, the flame cannons, the hatch, the punt, telemetry in orbit, the catch's clang.
The voice is Unit 19's: ring-modulated, crushed to a few bits, a metal comb on it.
"""
from functools import lru_cache

import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
OPEN, CLOSED, BEAT = M.OPEN, M.CLOSED, M.BEAT
STEP = BEAT / 4                # a 16th
DOWNBEAT = 1.0                 # the theme's bars start on the landing: 1, 3, 5, 7, 9


def hz(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def robotize(voice):
    """A robot's throat: a ring modulator at 62 Hz, crushed to 5 bits held over 3 samples, a
    short comb for the metal, brought back to the line's own level."""
    if not voice.any():
        return voice
    t = J.times(len(voice))
    rms = np.sqrt(np.mean(voice ** 2) + 1e-12)
    ring = voice * (0.55 + 0.45 * np.sin(2 * np.pi * 62 * t))
    held = np.repeat(ring[::3], 3)[:len(voice)]
    crushed = np.round(held * 16) / 16
    comb = crushed.copy()
    for delay, gain in ((int(0.0065 * SR), 0.45), (int(0.011 * SR), 0.3)):
        comb[delay:] += crushed[:-delay] * gain
    out = 0.65 * J.butter(comb, 'band', [140, 6200]) + 0.35 * voice
    return out * rms / (np.sqrt(np.mean(out ** 2) + 1e-12))


# ------------------------------------------------------------------ the band

@lru_cache(maxsize=None)
def horn(note, length, vel=1.0, shape='stab', player=0):
    """One brass player, additive: the upper harmonics come in as the note gets louder, the way a
    horn's do, so a stab blats on its attack and a swell brightens as it grows. A little scoop up
    to the pitch, breath on the attack, vibrato when held. ``shape``: 'stab' (short, accented),
    'hold', 'swell' (soft to full), 'sfz' (hit, drop back, crescendo), 'rip' (a smear up into it)."""
    rel = 0.12 if shape == 'hold' else 0.05
    n = int((length + rel) * SR)
    t = J.times(n)
    low = note < 50
    if shape == 'stab':
        body, att = 0.62 + 0.6 * np.exp(-t / 0.045), 0.006
    elif shape == 'sfz':
        grow = np.clip((t - 0.12) / max(length - 0.12, 0.01), 0, 1)
        body, att = 1.1 * np.exp(-t / 0.05) + 0.28 + 0.8 * grow ** 2, 0.006
    elif shape == 'swell':
        body, att = 0.2 + 0.85 * np.clip(t / length, 0, 1) ** 2, 0.03
    elif shape == 'rip':
        up = np.clip(t / 0.13, 0, 1)
        body, att = 0.35 + 0.65 * up + 0.3 * np.exp(-np.maximum(t - 0.13, 0) / 0.06) * (t > 0.13), 0.01
    else:
        body, att = 0.8 + 0.3 * np.exp(-t / 0.08), 0.03
    env = np.clip(t / att, 0, 1) * body * np.clip((length + rel - t) / rel, 0, 1) * vel
    bright = np.clip(body, 0, 1) * (0.5 + 0.5 * vel)
    semis = (-0.5 if low else -0.3) * np.exp(-t / (0.035 if low else 0.02)) + (0, 0.07, -0.06, 0.03)[player % 4]
    if shape == 'rip':
        semis = semis - 9 * (1 - up) ** 2
    if length > 0.4:
        semis = semis + 0.13 * np.sin(2 * np.pi * (5.2 + 0.3 * player) * t + player) * np.clip((t - 0.3) / 0.3, 0, 1)
    phase = 2 * np.pi * np.cumsum(hz(note) * 2 ** (semis / 12)) / SR + 1.7 * player
    # each harmonic falls by ``tilt`` on the last: dark when soft, nearly flat at full cry; a bump
    # where the instrument's bell sings (a trumpet's around 1.3 kHz, a trombone's lower)
    top, formant = (0.93, 1300) if note >= 67 else (0.88, 750) if not low else (0.84, 480)
    tilt = top - 0.55 + 0.55 * bright
    x, norm = np.zeros(n), 0.0
    for k in range(1, max(1, min(40, int(7500 / hz(note)))) + 1):
        w = 1.0 + 1.2 * np.exp(-((k * hz(note) - formant) / (0.6 * formant)) ** 2)
        x += w * tilt ** (k - 1) * np.sin(k * phase + 0.9 * k * player)
        norm += w * top ** (k - 1)
    x = np.tanh(1.8 * x / norm * env) / np.tanh(1.8)
    if shape in ('stab', 'sfz', 'rip'):
        hiss = np.random.default_rng(note * 7 + player).uniform(-1, 1, n)
        x += J.butter(hiss, 'band', [1200, 5000]) * np.exp(-t / 0.025) * 0.05 * vel
    x = x * 0.5
    x.setflags(write=False)
    return x


def section(desk, when, notes, length, vel=1.0, shape='stab', gain=0.35, trumpets=1.0, hall=0.3):
    """The brass section on ``notes``, two players a hair apart on each: trumpets bright and to
    the right, low brass heavy and to the left."""
    for note in notes:
        g = gain * (1.2 * trumpets if note >= 67 else 1.0 if note >= 52 else 0.7)
        pan = float(np.clip((note - 58) / 36, -0.5, 0.5))
        for p in range(2):
            desk.add(horn(note, length, vel, shape, p), when + 0.005 * p, g * 0.7, pan + (0.15 if p else -0.15),
                     hall=hall)


@lru_cache(maxsize=None)
def strings(notes, length):
    """The orchestra's half of a hit: strings bowed hard and short, band-limited saws a few cents
    apart, for the synth-orchestra punch."""
    n = int((length + 0.1) * SR)
    t = J.times(n)
    x = np.zeros(n)
    for note in notes:
        for det in (-0.08, 0.0, 0.09):
            f = hz(note) * 2 ** (det / 12)
            ph = 2 * np.pi * f * t + note + det
            for k in range(1, int(min(20, 8000 / f)) + 1):
                x += np.sin(k * ph) / k
    env = np.clip(t / 0.005, 0, 1) * (0.35 + 0.65 * np.exp(-t / 0.08)) * np.clip((length + 0.1 - t) / 0.1, 0, 1)
    x = J.butter(x / (3 * len(notes)) * env, 'low', 6000) * 0.6
    x.setflags(write=False)
    return x


@lru_cache(maxsize=None)
def taiko():
    """A big drum: a low skin dropping in pitch, the slap of the stick on top."""
    n = int(1.1 * SR)
    t = J.times(n)
    body = np.sin(2 * np.pi * np.cumsum(56 + 46 * np.exp(-t / 0.025)) / SR) * np.exp(-t / 0.32)
    rng = np.random.default_rng(19)
    skin = J.butter(rng.uniform(-1, 1, n), 'band', [70, 700]) * np.exp(-t / 0.045)
    slap = J.butter(rng.uniform(-1, 1, n), 'band', [900, 3500]) * np.exp(-t / 0.007)
    x = np.tanh(1.6 * (body + 0.8 * skin + 0.35 * slap)) * 0.8
    x.setflags(write=False)
    return x


@lru_cache(maxsize=None)
def snare(stick=0):
    """A marching snare: tight, high and dry, the wires a short hiss behind the crack."""
    n = int(0.3 * SR)
    t = J.times(n)
    hiss = np.random.default_rng(30 + stick).uniform(-1, 1, n)
    wires = J.butter(hiss, 'band', [3000, 10000]) * np.exp(-t / 0.06)
    crack = J.butter(hiss, 'band', [800, 3200]) * np.exp(-t / 0.01)
    head = (np.sin(2 * np.pi * (410 + 12 * stick) * t) + 0.5 * np.sin(2 * np.pi * 660 * t)) * np.exp(-t / 0.025)
    x = np.tanh(2.2 * (0.6 * wires + 1.1 * crack + 0.5 * head)) / np.tanh(2.2) * 0.45
    x.setflags(write=False)
    return x


@lru_cache(maxsize=None)
def tymp(note):
    x = J.timpani(note, 1.0)
    x.setflags(write=False)
    return x


def timp_note(root):
    while root < 36:
        root += 12
    while root > 47:
        root -= 12
    return root


def choked(length=0.18):
    """A crash grabbed by the hand: full, then gone."""
    x = J.crash(1.0, 1.5)
    t = J.times(len(x))
    return x * np.clip((length + 0.03 - t) / 0.03, 0, 1)


def cymbal_swell(length):
    """A suspended cymbal rolled on soft mallets, growing into the next hit."""
    n = int(length * SR)
    t = J.times(n)
    x = J.butter(np.random.default_rng(int(length * 1000)).uniform(-1, 1, n), 'band', [3000, 14000])
    x += sum(np.sin(2 * np.pi * f * t + i) for i, f in enumerate((3150, 4720, 6310, 8180))) * 0.05
    return x * (t / length) ** 2.5 * 0.5


def roll(desk, start, end, v0, v1, gain=0.5, every=0.042):
    """A snare roll, two sticks, from ``v0`` to ``v1``."""
    k = 0
    while start + k * every < end - 1e-6:
        u = k * every / (end - start)
        desk.add(snare(k % 2), start + k * every, gain * (v0 + (v1 - v0) * u ** 1.6) * (1.0 if k % 2 else 0.88),
                 0.05 if k % 2 else -0.05, hall=0.15, room=0.3)
        k += 1


def timp_roll(desk, start, end, note, v0, v1, gain=0.35):
    k = 0
    while start + k * 0.055 < end - 1e-6:
        u = k * 0.055 / (end - start)
        desk.add(tymp(note), start + k * 0.055, gain * (v0 + (v1 - v0) * u ** 1.5) * (0.9 if k % 2 else 1.0),
                 -0.1 if k % 2 else 0.1, hall=0.3)
        k += 1


def punch(desk, when, notes, length=0.3, vel=1.0, shape='stab', gain=0.35, trumpets=1.0, crash=0.3):
    """A big hit: the whole section, the strings, taiko, timpani on the root, a crash."""
    section(desk, when, notes, length, vel, shape, gain, trumpets)
    desk.add(strings(tuple(n for n in notes if 50 <= n <= 81), min(length, 0.35)), when, 0.9 * gain, hall=0.35)
    desk.add(taiko(), when, 0.4, hall=0.3)
    desk.add(tymp(timp_note(notes[0])), when, 0.35, hall=0.3)
    if crash:
        desk.add(J.crash(1.0, 2.2), when, crash, 0.25, hall=0.3)


# the engine: low brass galloping in staccato 16ths, accents falling 3 + 3 + 2
GALLOP = {0: 1.0, 2: 0.5, 3: 0.8, 4: 0.5, 6: 0.95, 8: 1.0, 10: 0.5, 11: 0.8, 12: 0.5, 14: 0.95}
ACCENT = (0, 3, 6, 8, 11, 14)


def drive(desk, start, end, roots, skip=(), brass=1.0, drums=1.0):
    """The theme's engine from ``start`` to ``end``: low brass galloping on the root (``roots``:
    (from, MIDI root) pairs), the snare on every 16th with a diddle here and there, timpani on the
    accents of the bar, taiko on the beat. Steps in ``skip`` belong to a bigger hit."""
    k = round((start - DOWNBEAT) / STEP)
    while DOWNBEAT + k * STEP < end - 1e-6:
        when = DOWNBEAT + k * STEP
        s = k % 16
        root = [r for at, r in roots if at <= when + 1e-6][-1]
        hit = any(abs(when - x) < 1e-3 for x in skip)
        if s in GALLOP and not hit and brass:
            for note, g in ((root, 0.18), (root + 12, 0.36)):
                desk.add(horn(note, 0.09, GALLOP[s], 'stab', 0), when, g * brass, -0.25, hall=0.25)
        if drums:
            accent = s in ACCENT
            desk.add(snare(k % 2), when, drums * (0.42 if accent else 0.16 + 0.03 * (k % 2)), 0.05, hall=0.15, room=0.3)
            if s in (5, 13):
                desk.add(snare(1 - k % 2), when + STEP / 2, drums * 0.13, 0.05, hall=0.15, room=0.3)
            if s in (0, 8) and not hit:
                desk.add(tymp(timp_note(root)), when, 0.16 * drums, hall=0.3)
            if s in (0, 8) and not hit:
                desk.add(taiko(), when, drums * 0.14, hall=0.25)
        k += 1


# ------------------------------------------------------------------ the robot

def servo(f0, f1, length, vel=1.0):
    """A servo's whine: a square-ish tone gliding, a motor's grit under it."""
    n = int(length * SR)
    t = J.times(n)
    f = f0 * (f1 / f0) ** np.clip(t / length, 0, 1)
    phase = 2 * np.pi * np.cumsum(f) / SR
    x = np.tanh(3 * np.sin(phase)) * 0.4 + 0.2 * np.sin(2 * phase)
    x += J.butter(J.noise(n), 'band', [1500, 4000]) * 0.15
    return x * np.clip(t / 0.02, 0, 1) * np.clip((length - t) / 0.05, 0, 1) * vel * 0.35


def clank(vel=1.0):
    """Armour plates meeting: a few inharmonic partials, ringing short."""
    n = int(0.6 * SR)
    t = J.times(n)
    x = np.zeros(n)
    for f, g, d in ((410, 1.0, 0.18), (1130, 0.7, 0.12), (2470, 0.5, 0.08), (3890, 0.35, 0.05)):
        x += g * np.sin(2 * np.pi * f * t) * np.exp(-t / d)
    x += J.butter(J.noise(n), 'high', 3000) * np.exp(-t / 0.01) * 0.6
    return x * vel * 0.4


def sparks(length, vel=1.0, seed=1):
    """Crackling: little bright ticks, thinning out."""
    n = int(length * SR)
    x = np.zeros(n)
    rng = np.random.default_rng(seed)
    t = 0.0
    while t < length:
        at = int(t * SR)
        m = min(n - at, int(0.006 * SR))
        x[at:at + m] += rng.uniform(-1, 1, m) * rng.uniform(0.3, 1.0) * (1 - t / length)
        t += rng.exponential(0.012 + 0.05 * t / length)
    return J.butter(x, 'high', 2500) * vel * 0.5


def flame(vel=1.0):
    """A flame cannon: a whoomp of low air and a roar that fades."""
    n = int(0.9 * SR)
    t = J.times(n)
    roar = J.butter(J.noise(n), 'band', [120, 1800]) * np.exp(-t / 0.3) * np.clip(t / 0.02, 0, 1)
    thump = np.sin(2 * np.pi * np.cumsum(55 + 50 * np.exp(-t / 0.04)) / SR) * np.exp(-t / 0.15)
    return (roar * 0.8 + thump * 0.7) * vel * 0.6


def jet_fall(length):
    """The fall: a scream that drops in pitch and swells into the landing."""
    n = int(length * SR)
    t = J.times(n)
    u = t / length
    x = J.sweep(J.noise(n), 6000 * (1 - u) + 400, 'bp', 3.0)
    tone = np.sin(2 * np.pi * np.cumsum(1800 * (1 - 0.75 * u)) / SR) * 0.15
    return (x + tone) * (0.15 + 0.85 * u ** 1.5)


def telemetry(vel=1.0):
    n = int(0.09 * SR)
    t = J.times(n)
    return np.sin(2 * np.pi * 1760 * t) * np.exp(-t / 0.04) * vel * 0.3


# ------------------------------------------------------------------ the cue

# MIDI: C4 = 60. The open logo is C5 E5 G5 A5 (72 76 79 81), the closed D5 F#5 A5 D6 (74 78 81 86).
UNISON_D = (38, 50, 62, 74)
D_MINOR = (38, 50, 57, 62, 65, 69, 74)
MOVES = (                              # (root, the section, the open logo's note on top)
    (41, (41, 48, 53, 60, 65, 69, 72)),            # F, C on top
    (45, (45, 52, 57, 64, 69, 72, 76)),            # A minor, E
    (36, (36, 48, 55, 60, 64, 67, 72, 76, 79)),    # C, G
    (38, (38, 50, 57, 62, 65, 69, 74, 77, 81)),    # D minor, A
)
B_FLAT = (34, 46, 53, 58, 62, 65, 70, 74)
C_MAJOR = (36, 48, 55, 60, 64, 67, 72, 76)
A_MAJOR = (33, 45, 52, 57, 61, 64, 69)
D_MAJOR = (38, 50, 57, 62, 66, 69, 74)
D_MAJOR_FULL = (38, 50, 57, 62, 66, 69, 74, 78, 81, 86)


def cue(voice):
    P = M.hits('robot')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    space_in, space_out = P.SPACE[0], P.RETURN[1]
    pans = (-0.6, 0.0, 0.25, 0.6)
    # the stadium's roar, out while in orbit
    crowd = J.butter(S.crowd(length, swell=(P.LAND, P.LAND + 0.5)), 'high', 300)
    tt = J.times(len(crowd))
    gate = np.clip(1 - (np.clip((tt - space_in + 0.25) / 0.25, 0, 1) * np.clip((space_out - tt) / 0.05, 0, 1)), 0, 1)
    desk.add(crowd * gate * (0.55 + 0.45 * np.clip((tt - P.LAND) / 0.4, 0, 1)), 0.0, 0.2, hall=0.2)

    # cold open: two hard unison hits, then the fall under a roll and the low brass swelling on A
    for when, vel in ((0.0, 1.0), (0.25, 0.9)):
        section(desk, when, UNISON_D, 0.14, vel, 'stab', 0.42)
        desk.add(taiko(), when, 0.6 * vel, hall=0.3)
        desk.add(tymp(38), when, 0.5 * vel, hall=0.3)
    desk.add(strings((50, 62, 74), 0.14), 0.0, 0.35, hall=0.3)
    desk.add(J.crash(1.0, 1.6), 0.0, 0.28, 0.2, hall=0.3)
    section(desk, 0.5, (33, 45, 52, 57), P.LAND - 0.5, 0.9, 'swell', 0.3)
    roll(desk, 0.5, P.LAND, 0.12, 0.85, 0.45)
    timp_roll(desk, 0.55, P.LAND, 45, 0.1, 0.6, 0.3)
    desk.add(jet_fall(P.LAND - 0.05), 0.05, 0.28, 0.0, hall=0.3)
    desk.add(M.sub(31, P.LAND - 0.2, 0.9, glide_from=43), 0.2, 0.2, hall=0.0)

    # the landing: the theme's downbeat
    punch(desk, P.LAND, D_MINOR, 0.32, 1.0, 'stab', 0.4, crash=0.35)
    desk.add(M.boom(1.0), P.LAND, 0.45, hall=0.4)
    desk.add(clank(1.0), P.LAND, 0.45, -0.1, hall=0.3)
    desk.add(sparks(1.2, 1.0, 3), P.LAND + 0.02, 0.3, 0.3, hall=0.3)
    for k, x in enumerate((-0.8, -0.4, 0.4, 0.8)):
        desk.add(flame(0.9), P.LAND + 0.01 * k, 0.25, x, hall=0.3)
    desk.add(servo(220, 640, P.RISE[1] - P.RISE[0] + 0.05, 1.0), P.RISE[0], 0.35, 0.1, hall=0.2)

    # the open logo: a stab per move, the gallop and the snare under it all
    roots = [(P.LAND, 38)] + [(when, root) for when, (root, _) in zip(P.MOVES, MOVES)]
    drive(desk, P.LAND, 2.75, roots, skip=(P.LAND,) + tuple(P.MOVES))
    for k, (when, note, (root, chord)) in enumerate(zip(P.MOVES, OPEN, MOVES)):
        held = (0.16, 0.16, 0.3, 0.24)[k]
        section(desk, when, chord, held, 1.0, 'stab', 0.36)
        desk.add(strings(tuple(n for n in chord if 50 <= n <= 81), held), when, 0.3, hall=0.35)
        desk.add(J.bell(note + 12, 1.4, 0.8), when, 0.12, pans[k], hall=0.4)
        desk.add(tymp(timp_note(root)), when, 0.3, hall=0.3)
        desk.add(taiko(), when, 0.3, hall=0.3)
        desk.add(clank(0.9), when, 0.25, pans[k] * 0.5, hall=0.25)
        desk.add(servo(500 + 120 * k, 1300 + 200 * k, 0.09, 1.0), when - 0.07, 0.3, pans[k] * 0.4, hall=0.15)
        desk.add(flame(0.8), when + 0.02, 0.18, pans[k], hall=0.3)
    desk.add(J.crash(0.8, 1.6), P.MOVES[0], 0.2, -0.3, hall=0.3)
    desk.add(J.crash(1.0, 2.0), P.MOVES[-1], 0.3, 0.3, hall=0.3)
    roll(desk, 2.25, P.MOVES[-1], 0.3, 0.8, 0.4, every=0.0625)

    # "Vizzle Vision... football...": the gallop, low and out of the way; the hatch; the punt
    drive(desk, 2.75, P.PUNT, [(2.75, 38)], brass=0.8, drums=0.6)
    desk.add(J.butter(J.noise(int(0.4 * SR)), 'band', [2000, 9000]) * np.exp(-J.times(int(0.4 * SR)) / 0.12) * 0.6,
             P.HATCH[0], 0.3, hall=0.2)
    desk.add(servo(300, 180, 0.25, 0.8), P.HATCH[0] + 0.05, 0.25, hall=0.15)
    desk.add(M.clunk(0.8), P.HATCH[1], 0.3, -0.3, hall=0.2)
    punch(desk, P.PUNT, B_FLAT, 0.28, 1.0, 'stab', 0.36, trumpets=0.5, crash=0.25)
    desk.add(M.boom(0.8), P.PUNT, 0.4, hall=0.3)
    desk.add(M.crack(0.9), P.PUNT, 0.35, 0.1, hall=0.3)
    # the climb: the gallop on B flat, a C stab in the gap between the words, a swell into orbit
    drive(desk, P.PUNT, 4.5, [(P.PUNT, 34), (4.0, 36)], skip=(P.PUNT, 4.0), brass=0.85, drums=0.65)
    punch(desk, 4.0, C_MAJOR, 0.16, 1.0, 'stab', 0.34, crash=0.0)
    section(desk, 4.1, (38, 50, 57, 62, 65), space_in - 4.1, 0.85, 'swell', 0.3)
    desk.add(cymbal_swell(space_in - 4.0), 4.0, 0.3, 0.2, hall=0.3)
    desk.add(J.riser(P.TILT[1] - P.PUNT, 9000), P.PUNT, 0.2, hall=0.3)
    n = int((P.TILT[1] - P.PUNT) * SR)
    t = J.times(n)
    whistle = np.sin(2 * np.pi * np.cumsum(500 * (5.0 ** (t / (n / SR)))) / SR) * np.clip(t / 0.1, 0, 1)
    desk.add(whistle * np.clip((n / SR - t) / 0.15, 0, 1) * 0.18, P.PUNT + 0.05, 0.35, 0.2, hall=0.4)

    # orbit: the band drops to a horn chorale; the pad, telemetry, "...activated."
    for at, until, chord in ((space_in, 5.25, (50, 57, 62, 65, 69)), (5.25, 5.75, (46, 58, 62, 65, 70)),
                             (5.75, 6.15, (48, 60, 64, 67, 72))):
        section(desk, at, chord, until - at + 0.05, 0.6, 'hold', 0.34, hall=0.6)
    desk.add(tymp(38), space_in, 0.25, hall=0.5)
    desk.wide(lambda: J.pad_voice((79, 83, 86, 90, 95), P.RETURN[0] - space_in + 0.3, 0.6, 0.8), space_in, 0.05, hall=0.6)
    for k in range(9):
        desk.add(telemetry(0.8 if k % 3 else 1.0), space_in + 0.4 + k * 0.17 + (0.08 if k % 2 else 0), 0.3,
                 -0.5 + 0.12 * k, hall=0.4)

    # home: A major swells under the re-entry; then B flat, C, and the lights go down
    section(desk, P.RETURN[0], A_MAJOR, 6.5 - P.RETURN[0], 1.0, 'swell', 0.34)
    roll(desk, P.RETURN[0], 6.5, 0.1, 0.9, 0.45)
    desk.add(cymbal_swell(0.5), 6.0, 0.3, -0.2, hall=0.3)
    desk.add(J.sweep(J.noise(int(0.5 * SR)), 300, 'bp', 1.2) * np.linspace(0, 1, int(0.5 * SR)), P.RETURN[0] - 0.05, 0.35,
             hall=0.3)
    desk.add(M.boom(1.0), P.RETURN[1], 0.45, hall=0.4)
    punch(desk, 6.5, B_FLAT, 0.24, 1.0, 'sfz', 0.34, crash=0.25)
    punch(desk, 6.75, C_MAJOR, 0.24, 1.0, 'sfz', 0.36, crash=0.0)
    drive(desk, 6.5, P.WORDMARK, [(6.5, 34), (6.75, 36)], skip=(6.5, 6.75), brass=0.9, drums=0.9)
    roll(desk, 6.875, P.WORDMARK, 0.5, 1.0, 0.45)

    # the closed logo: D major at last. The tune in the trumpets, the section holding and growing
    closed = M.at_logo(P.WORDMARK)
    punch(desk, P.WORDMARK, D_MAJOR, 0.22, 1.0, 'stab', 0.38, crash=0.35)
    section(desk, P.WORDMARK + 0.02, (50, 54, 57, 62, 66), P.CATCH - P.WORDMARK - 0.02, 0.7, 'sfz', 0.26)
    S.logo(desk, P.WORDMARK, CLOSED, organ_=False, choir=True, gain=0.55)
    for k, (when, note) in enumerate(zip(closed, CLOSED)):
        if k < 3:
            section(desk, when, (note - 12, note), (0.2, 0.2, 0.4)[k], 1.0, 'stab' if k < 2 else 'hold', 0.4)
            desk.add(tymp((38, 42, 45)[k]), when, 0.45, hall=0.3)
        desk.add(J.bell(note + 12, 2.0, 0.8), when, 0.12, pans[k], hall=0.4)
        desk.add(flame(0.7), when + 0.02, 0.18, pans[k], hall=0.3)
    drive(desk, P.WORDMARK, P.CATCH - 0.25, [(P.WORDMARK, 38)], skip=tuple(closed), brass=0.9, drums=1.0)
    roll(desk, P.CATCH - 0.25, P.CATCH, 0.4, 1.0, 0.45, every=0.0625)

    # the catch on the last note: the top D ripped up to, the whole band, held and growing to the button
    section(desk, P.CATCH - 0.12, (74, 86), 0.4, 1.0, 'rip', 0.42)
    punch(desk, P.CATCH, D_MAJOR_FULL, 9.0 - P.CATCH, 1.0, 'sfz', 0.36, crash=0.4)
    desk.add(M.boom(0.7), P.CATCH, 0.4, hall=0.4)
    desk.add(clank(1.0), P.CATCH, 0.5, -0.1, hall=0.3)
    desk.add(sparks(0.9, 1.0, 9), P.CATCH, 0.3, -0.2, hall=0.3)
    desk.add(J.butter(S.crowd(length - P.CATCH, swell=(0.0, 0.3)), 'high', 300), P.CATCH, 0.25, hall=0.25)
    timp_roll(desk, 8.3, 9.0, 38, 0.15, 0.8, 0.35)
    roll(desk, 8.5, 9.0, 0.1, 0.9, 0.4)
    desk.add(cymbal_swell(0.6), 8.4, 0.3, 0.2, hall=0.3)
    # the button, the cymbal choked
    section(desk, 9.0, UNISON_D + (57, 86), 0.12, 1.0, 'stab', 0.45)
    desk.add(strings((50, 57, 62, 74), 0.12), 9.0, 0.35, hall=0.3)
    desk.add(taiko(), 9.0, 0.7, hall=0.3)
    desk.add(tymp(38), 9.0, 0.55, hall=0.3)
    desk.add(choked(), 9.0, 0.4, 0.2, hall=0.2)
    desk.add(M.boom(0.6), 9.0, 0.35, hall=0.3)
    return M.mixdown(desk, robotize(voice) * 0.7, length, end, grit=0.5)
