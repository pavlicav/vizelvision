"""The MNBA's sound (promos/music.py's kit): a community-access bed, cheerful and modest
(an electric piano's chords, a marimba, a drum machine with its claps and hats, a synth
bass), the big empty gym's echo and its fluorescent hum. The open logo on four bounces of
the ball, a bell and a vibraphone a note; four squeaky steps and the whistle, and the bed
stops dead; a gentle chord after it (that's OK). A riser for the run, the rim's clang and
the backboard's rattle for the dunk, the ball bouncing away. While he hangs, the rim creaks
and a warm, sincere pad holds "Give them a chance"; then one man claps, once, and the gym
answers. The closed logo on bells and a modest synth brass, the bed back in D under the
tagline, and a marimba's D F# A D for WE SUPPORT MEN'S SPORTS.
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR


def drum_machine(desk, start, stop, gain=1.0):
    """A drum machine on its factory preset: kicks on one and three, a clap on two and
    four, closed hats on the eighths."""
    step = 0
    while start + step * M.BEAT / 2 < stop - 1e-9:
        when, k = start + step * M.BEAT / 2, step % 8
        if k in (0, 4):
            desk.add(J.kick(0.8), when, 0.35 * gain, hall=0.1)
        if k in (2, 6):
            desk.add(J.clap(0.6), when, 0.22 * gain, 0.1, hall=0.3)
        desk.add(J.hat(0.5 if k % 2 else 0.8), when, 0.1 * gain, 0.35, hall=0.1)
        step += 1


def chords(desk, plan, stop, gain=1.0):
    """The electric piano and the bass: (time, gate, (bass, notes...)) until stop."""
    for at, gate, (root, *notes) in plan:
        if at >= stop:
            break
        gate = min(gate, stop - at)
        for i, note in enumerate(notes):
            desk.add(J.epiano(note, gate, 0.55), at + 0.008 * i, 0.09 * gain, -0.3 + 0.2 * i, hall=0.3)
        desk.add(J.bass(root, gate * 0.9, 0.8), at, 0.22 * gain, hall=0.05)


def arpeggio(desk, plan, start, stop, gain=1.0):
    """The marimba, up and down the chord on the eighths."""
    step = 0
    while start + step * M.BEAT / 2 < stop - 1e-9:
        when = start + step * M.BEAT / 2
        current = [p for p in plan if p[0] <= when + 1e-9][-1]
        notes = current[2][1:]
        order = (0, 1, 2, 3, 2, 1)
        note = notes[order[step % 6] % len(notes)] + 12
        desk.add(J.marimba(note, 0.7), when, 0.07 * gain, 0.3 if step % 2 else -0.2, hall=0.3)
        step += 1


def cue(voice):
    P = M.hits('mnba')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    n = int(length * SR)
    t = J.times(n)
    room = J.butter(J.noise(n), 'band', [120, 700]) * 0.1                        # the empty gym
    hum = 0.035 * np.sin(2 * np.pi * 120 * t) + 0.015 * np.sin(2 * np.pi * 240 * t)   # its fluorescent lights
    desk.add(room + hum, 0.0, 0.3, hall=0.1)

    # The bed, until the whistle: C, Am, C6 under the logo (C E G A), F.
    plan = ((0.0, 1.0, (36, 60, 64, 67, 71)), (1.0, 0.5, (33, 57, 60, 64, 67)), (1.5, 1.0, (36, 60, 64, 67, 69)),
            (2.5, 0.75, (41, 57, 60, 65, 69)))
    chords(desk, plan, P.WHISTLE)
    arpeggio(desk, plan, 0.0, P.WHISTLE)
    drum_machine(desk, 0.0, P.WHISTLE)

    for when in P.DRIBBLES:                                          # the ball on the floor
        desk.add(M.dribble(0.9), when, 0.5, -0.15, hall=0.45)
    for (offset, beats), when, note in zip(S.LOGO_RHYTHM, P.LOGO_DRIBBLES, M.OPEN):   # the open logo, a note a bounce
        desk.add(J.bell(note, 1.8, 0.9), when, 0.26, 0.2, hall=0.4)
        desk.add(M.vibes(note - 12, 1.4), when, 0.32, -0.2, hall=0.35)
        desk.add(J.brass(note - 12, beats * M.BEAT * 0.9, 0.75), when, 0.09, 0.0, hall=0.3)

    for k, when in enumerate(P.STEPS):                               # four steps, no dribble
        desk.add(M.sneaker(0.13, 0.8, seed=k), when + 0.14, 0.28, 0.1, hall=0.4)
    desk.add(M.ref_whistle(0.6, 1.0), P.WHISTLE, 0.42, 0.45, hall=0.5)
    for i, note in enumerate((53, 57, 60, 64)):                      # that's OK
        desk.add(J.epiano(note, 0.6, 0.45), P.WHISTLE + 0.42 + 0.03 * i, 0.08, -0.2 + 0.15 * i, hall=0.45)

    for k in range(4):                                               # the run, the dunk
        desk.add(M.sneaker(0.1, 0.9, seed=10 + k), P.RUN[0] + 0.05 + k * 0.12, 0.26, 0.25, hall=0.4)
    desk.add(J.riser(P.DUNK - P.RUN[0], 6000), P.RUN[0], 0.16, hall=0.3)
    desk.add(M.pipe(79, 1.0), P.DUNK, 0.8, 0.4, hall=0.5)
    desk.add(J.kick(1.0), P.DUNK, 0.5, 0.3, hall=0.4)
    m = int(0.9 * SR)
    tm = J.times(m)
    rattle = J.butter(J.noise(m), 'band', [150, 900]) * np.exp(-tm / 0.25) * (1 + 0.6 * np.sin(2 * np.pi * 17 * tm))
    desk.add(rattle, P.DUNK, 0.75, 0.45, hall=0.45)
    desk.add(M.swish(0.8), P.DUNK + 0.05, 0.3, 0.35, hall=0.3)
    desk.add(J.crash(0.5, 1.4), P.DUNK, 0.15, 0.3, hall=0.4)
    for k, when in enumerate(P.BOUNCES):
        desk.add(M.dribble(0.8 - 0.17 * k), when, 0.45, 0.3, hall=0.5)

    desk.add(M.creak(0.6, 0.7), P.DUNK + 0.65, 0.28, 0.4, hall=0.45)  # he hangs there
    desk.wide(lambda: J.pad_voice((53, 60, 64, 69), 1.2, 0.45, 0.8), P.DUNK + 0.45, 0.05, hall=0.5)
    desk.wide(lambda: J.pad_voice((55, 62, 65, 67), 0.9, 0.3, 0.9), P.DUNK + 1.6, 0.05, hall=0.5)
    for i, note in enumerate((53, 57, 60, 64, 67)):                   # sincerely
        desk.add(J.epiano(note, 0.9, 0.5), P.DUNK + 0.5 + 0.06 * i, 0.07, -0.3 + 0.15 * i, hall=0.5)
    for i, note in enumerate((55, 60, 62, 65)):
        desk.add(J.epiano(note, 0.7, 0.45), P.DUNK + 1.2 + 0.05 * i, 0.06, -0.3 + 0.2 * i, hall=0.5)
    desk.add(J.clap(1.0), P.LONE_CLAP, 0.6, -0.4, hall=1.0)          # one man, once

    S.logo(desk, P.CLOSED, M.CLOSED, organ_=False, gain=0.85)        # the closed logo: the end card
    plan_d = ((P.CLOSED, 1.0, (38, 62, 66, 69, 73)), (P.CLOSED + 1.0, 1.0, (35, 59, 62, 66, 69)),
              (P.CLOSED + 2.0, 0.75, (43, 59, 62, 67, 71)), (P.CLOSED + 2.75, 0.5, (45, 61, 64, 69)),
              (P.CLOSED + 3.25, 0.6, (38, 62, 66, 69, 74)))
    chords(desk, plan_d, end - 0.2, gain=0.9)
    arpeggio(desk, plan_d, P.CLOSED + 1.0, end - 0.3, gain=0.8)
    drum_machine(desk, P.CLOSED + 1.0, end - 0.3, gain=0.75)
    desk.add(M.creak(0.8, 0.8), P.BEND[0] + 0.4, 0.2, 0.45, hall=0.45)
    for i, note in enumerate((74, 78, 81, 86)):                      # WE SUPPORT MEN'S SPORTS
        desk.add(J.marimba(note, 0.9), P.TAGLINE + 0.07 * i, 0.12, -0.3 + 0.2 * i, hall=0.35)
    return M.mixdown(desk, voice, length, end, grit=1.0)
