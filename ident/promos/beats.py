"""Hits that a promo's picture and its music share. Plain Python, so that both the
picture (pycairo, the system Python) and the music (numpy, miniconda's) can import it.
"""

BEAT = 0.5
SIXTEENTH = BEAT / 4
LOGO = (0, 0.5, 1, 2)          # the logo's rhythm, in beats: eighth, eighth, quarter, half

# ---------------------------------------------------------------- Meridian Hill's drum circle

# The six drums, left to right along the bottom of the frame.
DRUMS = ('djembe', 'conga', 'djembe', 'djembe', 'conga', 'djembe')
BASINS = 13
FILL = 0.3                     # the build: a hit a sixteenth, one for each basin of the cascade as it fills
CLAP = 2.0                     # the open logo's rhythm, all together: the clap
GROOVE = (3.5, 6.75)
CLOSED = 7.0                   # the closed logo's rhythm, all together
TAIL = (8.25, 8.875)
BUTTON = 9.0

# Each drum's part through the groove: two beats in sixteenths, repeated.
#   x: a full stroke, o: a light one.
PARTS = ('x.....x.',           # the low djembe: bass tones on the one
         '..x.x..x',           # conga
         'o...x...',           # djembe: the slap on the backbeat
         'x.o...x.',           # djembe: tones
         '.o.x.o.x',           # the high conga: the offbeats
         'x...o.o.')           # the big djembe
TAIL_PARTS = {1: '..x.x..x', 4: '.o.x.o.x'}

BOTH = 2                       # a hand: 0 left, 1 right, 2 both together


def fill_times():
    """When each basin of the cascade fills, top to bottom (the build's hits)."""
    return [FILL + k * SIXTEENTH for k in range(BASINS)]


def meridian_hits():
    """Every hit, in time order: (time, drum, hand, velocity). Each drum's hands take
    turns; the all-together hits use both."""
    hits = []
    for k, at in enumerate(fill_times()):
        hits.append((at, k % len(DRUMS), None, 0.45 + 0.55 * k / (BASINS - 1)))
    for start in (CLAP, CLOSED):
        for beats in LOGO:
            for drum in range(len(DRUMS)):
                hits.append((start + beats * BEAT, drum, BOTH, 1.0))
    for (a, b), parts in ((GROOVE, dict(enumerate(PARTS))), (TAIL, TAIL_PARTS)):
        step = 0
        while a + step * SIXTEENTH < b - 1e-9:
            for drum, part in parts.items():
                stroke = part[step % len(part)]
                if stroke != '.':
                    hits.append((a + step * SIXTEENTH, drum, None, 1.0 if stroke == 'x' else 0.55))
            step += 1
    for drum in range(len(DRUMS)):
        hits.append((BUTTON, drum, BOTH, 1.0))
    hits.sort(key=lambda h: (h[0], h[1]))
    turn = {}
    placed = []
    for at, drum, hand, vel in hits:
        if hand is None:
            hand = turn.get(drum, 1)
            turn[drum] = 1 - hand
        placed.append((round(at, 6), drum, hand, vel))
    return placed


# ---------------------------------------------------------------- the Metro's train

TRAIN_ARRIVE = (0.4, 2.4)      # it pulls in, braking all the way
TRAIN_DEPART = (7.15, 8.25)    # and pulls out, speeding up
FRAME_W = 1280
CAR, GAP = 1500, 24            # a car's length and the gap between cars, in pixels
DOORS = (300, 750, 1200)       # the door centres along a car
STOP_X = FRAME_W / 2 - (CAR + GAP + DOORS[1])     # the second car's middle door stops at the centre
ENTER_X = FRAME_W + 40
GONE_X = -(2 * CAR + GAP) - 60
AXLES = tuple(k * (CAR + GAP) + a for k in range(2) for a in (105, 195, 1305, 1395))
JOINTS = (330, 950)            # rail joints the wheels clack over, across the frame


def train_x(t):
    """The front of the train (its left end) at t, or None when it is not in the station."""
    a0, a1 = TRAIN_ARRIVE
    d0, d1 = TRAIN_DEPART
    if a0 <= t < a1:
        p = (t - a0) / (a1 - a0)
        return ENTER_X + (STOP_X - ENTER_X) * (1 - (1 - p) ** 2)
    if a1 <= t < d0:
        return STOP_X
    if d0 <= t < d1:
        p = (t - d0) / (d1 - d0)
        return STOP_X + (GONE_X - STOP_X) * p ** 2
    return None


def clacks(step=0.0005):
    """(time, joint x, speed in px/s) for every axle crossing a rail joint."""
    hits = []
    for a, b in (TRAIN_ARRIVE, TRAIN_DEPART):
        t, previous = a, train_x(a)
        while t + step < b:
            t += step
            x = train_x(t)
            for axle in AXLES:
                for joint in JOINTS:
                    if (previous + axle - joint) * (x + axle - joint) <= 0 and previous != x:
                        hits.append((t, joint, abs(x - previous) / step))
            previous = x
    return sorted(hits)
