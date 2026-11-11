"""The First Thanksgiving (Annotated)'s sound (thanksgiving_annotated.py): the projector's
whir and the filmstrip's earnest Americana (fife, strings and a horn) under the narrator,
until the red marker's cap pops and a record scratch stops it; the open logo is the four
footnotes, the marker squeaking each one in with a pizzicato and a bell on its note; the
filmstrip's beep and the next frame; a brass ta-da for THE END, scratched off too; the marker
writes STILL HERE. over a sincere swell, strings and choir, a bell for the Nation; the closed
logo on bells and choir; a last squeak for the dinner note.
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR

# the filmstrip's tune (original), on the fife: (when, midi, beats)
TUNE = ((0.4, 72, 1), (0.9, 74, 0.5), (1.15, 76, 0.5), (1.4, 79, 1), (1.9, 76, 0.5), (2.15, 74, 0.5),
        (2.4, 72, 1))
CHORDS = ((0.35, (48, 55, 60, 64)), (1.35, (41, 53, 57, 60)), (2.35, (43, 50, 55, 59)))


def beep(length=0.32, vel=1.0):
    """The filmstrip's advance tone."""
    n = int(length * SR)
    t = J.times(n)
    return np.sin(2 * np.pi * 1000 * t) * np.clip(t / 0.005, 0, 1) * np.clip((length - t) / 0.01, 0, 1) * vel * 0.5


def uncap(vel=1.0):
    """A marker's cap pulled off: a small hollow pop."""
    n = int(0.12 * SR)
    t = J.times(n)
    return np.sin(2 * np.pi * np.cumsum(900 - 500 * t / 0.12) / SR) * np.exp(-t / 0.02) * vel * 0.8


def cue(voice):
    P = M.hits('thanksgiving-annotated')
    length, end = P.DURATION, P.IRIS_CLOSE[1]
    desk = S.Desk(length)
    desk.wide(lambda: M.projector(length - 0.3) * 0.6, 0.0, 0.25, hall=0.1)
    stop = P.EDITS[0] - 0.12                                   # the scratch
    for at, chord in CHORDS:                                   # the filmstrip's Americana
        gate = min(1.0, stop - at)
        desk.wide(lambda c=chord, g=gate: J.pad_voice(c, g, 0.25, 0.2), at, 0.08, hall=0.4)
        desk.wide(lambda c=chord, g=gate: J.brass(c[0] + 12, g * 0.9, 0.6), at, 0.06, 0.2, hall=0.4)
    for at, note, beats in TUNE:
        if at < stop:
            desk.add(M.fife(note + 12, min(beats * M.BEAT * 0.9, stop - at), 0.7), at, 0.12, -0.2, hall=0.4)
    desk.add(uncap(1.0), P.MARKER_IN[0] + 0.15, 0.3, 0.6, hall=0.15)
    desk.add(M.scratch(0.4, 1.0), stop, 0.35, 0.0, hall=0.1)
    # the open logo: a footnote a note
    for k, (when, note, dur) in enumerate(zip(P.EDITS, M.OPEN, P.WRITE)):
        desk.add(M.squeak(dur, 0.9, seed=k), when, 0.3, -0.2 + 0.15 * k, hall=0.1)
        desk.add(M.pizz(note - 12, 1.0), when, 0.35, 0.0, hall=0.25)
        desk.add(J.bell(note + 12, 1.4, 0.7), when, 0.14, 0.3, hall=0.4)
    desk.add(J.timpani(43, 0.6), P.EDITS[3], 0.2, hall=0.3)
    # the next frame
    desk.add(beep(), P.ADVANCE - 0.05, 0.3, 0.0, hall=0.1)
    desk.add(M.clack(1.0), P.ADVANCE + 0.18, 0.4, 0.0, hall=0.1)
    for note in (60, 64, 67, 72):                              # THE END: ta-da
        desk.wide(lambda n=note: J.brass(n, 0.5, 0.8), P.ADVANCE + 0.55, 0.07, 0.0, hall=0.4)
    desk.add(M.scratch(0.35, 0.9), P.STRIKE_END - 0.03, 0.3, 0.1, hall=0.1)
    desk.add(M.squeak(0.18, 1.0, seed=7), P.STRIKE_END, 0.3, 0.1, hall=0.1)
    # STILL HERE.
    desk.add(M.squeak(P.STILL_HERE[1] - P.STILL_HERE[0], 1.0, seed=9), P.STILL_HERE[0], 0.32, 0.0, hall=0.1)
    desk.wide(lambda: J.pad_voice((50, 57, 62, 66), P.LOGO[0] - P.STILL_HERE[0] + 1.0, 0.5, 1.2), P.STILL_HERE[0],
              0.09, hall=0.6)
    desk.add(J.choir(66, 1.3, 0.6), P.STILL_HERE[0] + 0.2, 0.15, -0.3, hall=0.6)
    desk.add(J.choir(62, 1.3, 0.6), P.STILL_HERE[0] + 0.2, 0.13, 0.3, hall=0.6)
    desk.add(J.bell(74, 2.0, 0.8), P.NATION, 0.16, 0.0, hall=0.5)
    # the closed logo
    S.logo(desk, P.LOGO[0], M.CLOSED, organ_=False, choir=True, gain=0.85)
    for when, note in zip(P.LOGO, M.CLOSED):
        desk.add(M.pizz(note - 24, 1.0, 0.9), when, 0.3, 0.1, hall=0.25)
    desk.add(M.squeak(P.DINNER[1] - P.DINNER[0], 0.6, seed=11), P.DINNER[0], 0.2, 0.4, hall=0.1)
    desk.add(M.pizz(84, 0.6), P.DINNER[1], 0.18, 0.4, hall=0.3)
    return M.mixdown(desk, voice, length, end, grit=0.7)
