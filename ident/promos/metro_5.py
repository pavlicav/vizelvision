"""The VizelVision Line, in five seconds: the train at the platform with its doors open and
the emblem already off. "Step back, doors closing." The closed logo on the door chime, the
doors shut, the train pulls out and leaves the station's name on the wall.
"""
import cutdown

ID = 'metro-5'
NAME = 'The VizelVision Line (5 s)'
KIND = 'ident'
ORDER = 30
DESCRIPTION = ('Five seconds of The VizelVision Line: "Step back, doors closing," the closed logo on the door '
               "chime, and the train pulls out to leave the station's name on the wall. Mars.")
DURATION = 5.0
STILL_AT = 4.0
SOURCE = 'metro'
PIECES = ((4.55, 9.55),)
LINES = (('promo-metro-2', 0.2),)            # "Step back, doors closing." (4.75 in the source)

OVERLAYS = cutdown.overlays(SOURCE, PIECES, DURATION)
draw = cutdown.drawer(SOURCE, PIECES, fade_in=0.2)
