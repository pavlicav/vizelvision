"""Orange Cat Behavior: The Remote, in five seconds. The cat hops onto the remote and
its weight presses Channel Up on each note of the open logo, 15 to 19; a cut to the
closed logo, VIZELVISION 19 wiping in, and Draco: "A fine choice." A mrrp, a slow blink.
"""
import cutdown

ID = 'cat-remote-5'
NAME = 'Orange Cat Behavior: The Remote (5 s)'
KIND = 'ident'
ORDER = 32
DESCRIPTION = ('Five seconds of The Remote: the orange cat lies on the remote and changes the channel on each '
               'note of the logo, 15 to VizelVision 19. "A fine choice." Draco.')
DURATION = 5.0
STILL_AT = 3.0
SOURCE = 'cat-remote'
PIECES = ((2.0, 4.5), (7.0, 9.5))            # the hop and the presses; the closed logo on
LINES = (('promo-cat-remote-3', 2.15),)      # "A fine choice." (after 19, as the banner comes)

OVERLAYS = cutdown.overlays(SOURCE, PIECES, DURATION)
draw = cutdown.drawer(SOURCE, PIECES, fade_in=0.12, fade_out=(4.75, 4.95))
