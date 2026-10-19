"""Baseball on VizelVision, in five seconds: the board already reads No. 19, VIZELVISION;
the windup, the pitch, the crack, and the long fly into the scoreboard on the closed logo:
HOME RUN!, fireworks and the crowd. The ribbon board carries the game on air (live text).
Only during an MLB game. No voice: the PA's line is in the part cut out.
"""
import cutdown

ID = 'baseball-5'
NAME = 'Baseball on VizelVision (5 s)'
KIND = 'ident'
ORDER = 31
DESCRIPTION = ('Only during baseball, five seconds: the pitch, the crack, and a home run into the scoreboard on '
               'the closed logo, with fireworks. The ribbon board shows the game on air.')
DURATION = 5.0
STILL_AT = 3.9
LEAGUES = ('mlb',)
SOURCE = 'baseball'
PIECES = ((4.6, 9.6),)
LINES = ()

OVERLAYS = cutdown.overlays(SOURCE, PIECES, DURATION)
draw = cutdown.drawer(SOURCE, PIECES, fade_in=0.15)
