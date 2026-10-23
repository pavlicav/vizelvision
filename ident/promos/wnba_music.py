"""The Tunnel Walk's sound (wnba.py). In the tunnel: its concrete hum, the arena DJ's groove
through the walls (muffled, the crowd beyond it), shutters clicking, her sneakers on the
concrete. The open logo is her four steps: a bell, a brass stab and an 808 on each, and a
volley of shutters and flash pops. She stops; the groove thins to the bass. The sunglasses
slide down on a falling run of vibes; the look, and the shutters go wild with a crowd's
"ooh". A whoosh as the purse goes up, a jingle of its chain. Two steps on, a whoosh into the
whip pan, and the arena at full size: the crowd up, the horn, the groove unmuffled. The
lights down on a riser and a roll, and the closed logo with the whole band and the horn.
"""
import numpy as np

import jingle as J
import music as M
import sonic as S

SR = M.SR
OPEN, CLOSED, BEAT = M.OPEN, M.CLOSED, M.BEAT


def step(vel=1.0):
    """A chunky sneaker coming down on concrete: a soft low thud and the sole's slap."""
    n = int(0.18 * SR)
    t = J.times(n)
    thud = np.sin(2 * np.pi * np.cumsum(70 + 60 * np.exp(-t / 0.012)) / SR) * np.exp(-t / 0.035)
    slap = J.butter(J.noise(n), 'band', [300, 2500]) * np.exp(-t / 0.012) * 0.5
    return np.tanh(1.6 * (thud + slap)) * vel * 0.6


def flash_pop(vel=1.0):
    """A speedlight firing: a bright tick, and its capacitor whining back up."""
    n = int(0.45 * SR)
    t = J.times(n)
    tick = J.butter(J.noise(n), 'high', 5000) * np.exp(-t / 0.002) * 0.8
    whine = np.sin(2 * np.pi * np.cumsum(2200 + 4200 * np.clip(t / 0.4, 0, 1)) / SR) * 0.05 * np.clip((0.45 - t) / 0.1, 0, 1)
    return (tick + whine * np.clip(t / 0.03, 0, 1)) * vel


def chain_jingle(vel=1.0):
    """The purse's gold chain settling: a few small bright clinks."""
    n = int(0.5 * SR)
    t = J.times(n)
    x = np.zeros(n)
    local = np.random.default_rng(34)
    for k in range(6):
        at = int((0.02 + k * 0.05 + local.uniform(0, 0.02)) * SR)
        f = local.uniform(3800, 6500)
        m = n - at
        tt = J.times(m)
        x[at:] += np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.03) * (0.8 - 0.1 * k)
    return x * vel * 0.3


def ooh(length, vel=1.0):
    """A crowd's "ooh": a filtered murmur swelling up and down, a vowel in it."""
    x = S.crowd(length, swell=(0.0, length * 0.4))
    x = J.formant(x, 500, 180) * 2 + J.butter(x, 'band', [250, 1200]) * 0.5
    t = J.times(len(x))
    return x * np.sin(np.pi * np.clip(t / length, 0, 1)) * vel


def cue(voice):
    P = M.hits('wnba')
    length, end = P.DURATION, P.FADE[1]
    desk = S.Desk(length)
    rng = np.random.default_rng(34)
    # The tunnel: its hum, and the arena through the walls (the DJ and the crowd, muffled).
    n_tunnel = int(P.WHIP[0] * SR)
    hum = J.butter(J.noise(n_tunnel), 'low', 140) * 0.6 + 0.05 * np.sin(2 * np.pi * 60 * J.times(n_tunnel))
    desk.add(hum * np.clip((P.WHIP[0] - J.times(n_tunnel)) / 0.1, 0, 1), 0.0, 0.25, hall=0.05)
    beyond = S.Desk(length)
    M.arena_groove(beyond, 0.0, P.WHIP[1], OPEN[0], gain=0.9)
    beyond.add(S.crowd(P.WHIP[1] + 0.2, swell=(P.ONWARD[0], P.WHIP[1])), 0.0, 0.5, hall=0.1)
    muffled = J.butter(beyond.mix(), 'low', 380)
    fade = np.clip((P.WHIP[1] - J.times(muffled.shape[1])) / 0.15, 0, 1)
    desk.dry += muffled * fade * 0.55
    # Her steps; the open logo is the last four.
    for k, when in enumerate(P.FOOTFALLS):
        desk.add(step(0.9), when, 0.5, -0.1 + 0.2 * (k % 2), hall=0.25)
    for when in (P.ONWARD[0] - 0.25, P.ONWARD[0], P.ONWARD[1]):
        desk.add(step(1.0), when, 0.55, 0.1, hall=0.25)
    for k, (when, note) in enumerate(zip(P.LOGO_STEPS, OPEN)):
        desk.add(J.bell(note + 12, 1.8, 0.9), when, 0.3, -0.2, hall=0.4)
        desk.add(J.bell(note, 2.4, 0.8), when, 0.22, 0.2, hall=0.35)
        for i, m in enumerate((note - 24, note - 12, note - 5)):
            desk.add(J.brass(m, 0.18 if k < 3 else 0.5, 0.95), when, 0.1, -0.4 + 0.4 * i, hall=0.25)
        desk.add(M.kick808(1.0, 0.5), when, 0.4, hall=0.05)
        for i in range(5):                                           # a volley of shutters and pops
            at = when + rng.uniform(0.0, 0.06)
            desk.add(M.shutter(rng.uniform(0.6, 1.0)), at, 0.3, rng.uniform(-0.9, 0.9), hall=0.35)
        desk.add(flash_pop(0.9), when + 0.01, 0.25, rng.uniform(-0.6, 0.6), hall=0.3)
    # A scatter of shutters while she walks, a storm for the look.
    t = 0.3
    while t < P.ONWARD[1]:
        if not P.FRENZY[0] - 0.1 < t < P.FRENZY[1]:
            desk.add(M.shutter(rng.uniform(0.4, 0.8)), t, 0.22, rng.uniform(-0.9, 0.9), hall=0.35)
        t += rng.uniform(0.09, 0.22)
    t = P.FRENZY[0]
    while t < P.FRENZY[1]:
        for _ in range(rng.integers(1, 4)):
            desk.add(M.shutter(rng.uniform(0.5, 1.0)), t + rng.uniform(0, 0.03), 0.22, rng.uniform(-1, 1), hall=0.35)
        if rng.random() < 0.3:
            desk.add(flash_pop(0.6), t, 0.15, rng.uniform(-0.8, 0.8), hall=0.3)
        t += 1 / 30
    # She stops: the bass holds; the sunglasses slide down on a falling run; the look.
    desk.add(M.sub(OPEN[-1] - 36, P.FRENZY[0] - P.STOP, 0.8), P.STOP, 0.3, hall=0.0)
    for k, note in enumerate((93, 91, 88, 86, 84, 81)):
        desk.add(M.vibes(note, 1.2, 0.7), P.GLASSES[0] + 0.12 + k * 0.045, 0.08, 0.3 - 0.1 * k, hall=0.5)
    desk.add(M.kick808(1.0, 0.9), P.FRENZY[0], 0.55, hall=0.05)
    desk.add(J.clap(1.0), P.FRENZY[0], 0.4, 0.1, hall=0.3)
    desk.add(ooh(1.4), P.FRENZY[0] + 0.05, 0.6, 0.0, hall=0.3)
    for i, m in enumerate((57, 64, 69, 73)):                          # a sly chord under the look
        desk.add(J.epiano(m, 0.9, 0.7), P.FRENZY[0], 0.12, -0.3 + 0.2 * i, hall=0.4)
    # The flip: a whoosh up, the chain's clinks as it lands.
    desk.add(J.whoosh(P.FLIP[1] - P.FLIP[0] + 0.1), P.FLIP[0], 0.18, 0.4, hall=0.3)
    desk.add(chain_jingle(1.0), P.FLIP[1] - 0.03, 0.5, 0.4, hall=0.3)
    desk.add(step(0.6), P.FLIP[1], 0.3, 0.4, hall=0.2)
    # Into the lens and the whip pan.
    desk.add(J.riser(P.WHIP[0] - P.ONWARD[0] + 0.1, 7000), P.ONWARD[0], 0.15, hall=0.3)
    desk.add(J.whoosh(0.5), P.WHIP[0] - 0.05, 0.4, -0.5, hall=0.3)
    # The arena, full size: the crowd up, the horn, the DJ.
    desk.add(S.crowd(length - P.COURT, swell=(0.0, 0.4)), P.COURT, 0.3, hall=0.15)
    desk.add(S.horn(1.4), P.COURT + 0.02, 0.35, hall=0.3)
    desk.add(M.kick808(1.0, 1.0), P.COURT, 0.55, hall=0.05)
    desk.add(J.crash(1.0, 2.2), P.COURT, 0.25, 0.2, hall=0.25)
    M.arena_groove(desk, P.COURT, P.DIM[0], OPEN[0])
    for k in range(10):                                             # courtside photographers
        when = P.COURT + rng.uniform(0.1, P.DIM[1] - P.COURT)
        desk.add(M.shutter(rng.uniform(0.4, 0.9)), when, 0.18, rng.uniform(-0.8, 0.8), hall=0.3)
    desk.add(M.whistle(0.8), P.WAVE[0] + 0.1, 0.12, 0.6, hall=0.4)
    # The lights down, and the closed logo.
    desk.add(J.riser(P.WORDMARK - P.DIM[0], 8000), P.DIM[0], 0.25, hall=0.3)
    for k in range(8):
        desk.add(J.snare(0.4 + 0.07 * k), P.DIM[0] + 0.05 + k * 0.0625, 0.35, hall=0.1, room=0.4)
    J.hit(desk, 62, P.WORDMARK, big=True)
    S.logo(desk, P.WORDMARK, CLOSED, organ_=False, gain=1.1)
    for when, note in zip(M.at_logo(P.WORDMARK), CLOSED):
        for i, m in enumerate((note - 24, note - 12, note - 5)):
            desk.add(J.brass(m, 0.3, 1.0), when, 0.12, -0.4 + 0.4 * i, hall=0.25)
        desk.add(M.shutter(0.8), when + 0.02, 0.2, 0.5, hall=0.3)
    desk.add(S.horn(1.6), P.WORDMARK, 0.4, hall=0.3)
    M.arena_groove(desk, P.WORDMARK + 2 * BEAT, 9.0, CLOSED[0], gain=0.9)
    J.hit(desk, 62, 9.0)
    return M.mixdown(desk, voice, length, end, grit=0.5)
