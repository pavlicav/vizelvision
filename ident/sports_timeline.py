"""Shared timing for the VizelVision Sports ID: the station ID's own hit points
(timeline.py), so the two are one family and the master's 30-second rules hold for
both (the end card at 27.9 s, the iris at 28.2 s, black from 29.3 s), plus the
moments only the Sports ID has.

Plain Python, like timeline.py: the music and the picture both import it.
"""
import json
from pathlib import Path

from timeline import *  # noqa: F401,F403  The ID's marks: START, HIT, KEY_CHANGE, BUTTON, IRIS...
from timeline import beat

SCRIPT = json.loads((Path(__file__).resolve().parent / 'sports_script.json').read_text())
LINE = SCRIPT['lines'][0]

LIGHTS = tuple(beat(n) for n in (0, 2, 4, 6))  # The four floodlight banks switch on.
VOICE = LINE['at']                             # "The following... is a presentation of..."
# Each word's start and end, from the line's first sound (measured from the take).
WORDS = tuple((word, VOICE + start, VOICE + end) for word, start, end in SCRIPT['words'])
MARQUEE = VOICE - 0.6                          # The scoreboard panel slides up for the line.
BANNER = beat(34)                              # SPORTS slams in, just after the line ends.
CLAPS = (beat(16), beat(36))                   # The crowd claps the logo's rhythm.
