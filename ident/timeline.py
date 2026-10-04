"""Shared timing for the VizelVision station ID. Picture and music both read these
marks, so a hit on screen always lands on a hit in the jingle.

Plain Python: the jingle runs under an interpreter with numpy, the picture under
one with pycairo, and both import this file.
"""

WIDTH, HEIGHT, FPS = 1280, 720, 60
DURATION = 30.0
SAMPLE_RATE = 48000

BPM = 120
BEAT = 60 / BPM
START = 0.5  # Downbeat of bar 1, after the channel-change static.


def beat(n):
    return START + n * BEAT


STATIC_END = START
LOGO_FLIGHT = beat(4)     # The emblem starts its spinning flight in.
HIT = beat(8)             # It lands: orchestra hit, flash.
LETTERS = beat(9)         # First wordmark letter; then one every eighth note.
LETTER_STEP = BEAT / 2
SWEEP = beat(18)          # Light sweep across the chrome.
RIBBON = beat(24)         # Quieter middle section under the voice.
TAGLINE = beat(34)
BUILD = beat(40)          # Snare roll and colour shift into the key change.
KEY_CHANGE = beat(48)     # The four-note logo, up a step, with the choir.
BUTTON = beat(52)         # Final hit.
IRIS = 28.2               # Iris closes on the emblem.
BLACK = 29.3              # Black and silent to the end, so any cut is clean.

WORDMARK = ('VIZEL', 'VISION')
