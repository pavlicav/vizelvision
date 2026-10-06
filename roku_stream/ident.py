"""The VizelVision station ID: a 30-second bumper the master plays between programs.

The ID is an ordinary video file (built by ident/build.py). The master worker keeps
it decoded and parked at its start in its own input slot, so it can cut in at any
moment without disturbing what is on air or what is cued next:

- a program with another one waiting behind it loses its last 30 s to the ID, so
  the next program still starts when it would have;
- a program that ends with nothing waiting is followed by the ID, then fallback;
- 30 s before a timed queue entry, the ID replaces the end of whatever is on air.

Remove or rename the file to stop the ID; a rebuilt file is picked up on its own.
"""
from __future__ import annotations

import re
from pathlib import Path

from .library import FileLease

IDENT_SOURCE_ID = 'ident'
IDENT_SECONDS = 30.0
IDENT_SLOT = 3  # MasterMedia's third input, used only by the ID.
# The ID ends in black and silence, so a take this close to its end is invisible.
IDENT_TAIL_SECONDS = 0.5
# The end card, just before the iris closes (ident/timeline.py IRIS = 28.2). While the next
# source is still being prepared, the ID holds this frame, then irises out once it is ready.
IDENT_HOLD_AT = 27.9
# A held end card gives up after this long: the iris closes and master falls back.
IDENT_HOLD_LIMIT = 120
IDENT_PATH = Path(__file__).resolve().parent.parent / 'ident' / 'vizelvision-id.mp4'
# The VizelVision Sports ID (ident/build.py --sports), with the same 30-second form. The
# break before a game plays it instead of the ID, even from the test card: continuity
# cues a copy named sports-<hash>.mp4 from its announcements folder (continuity.py).
SPORTS_IDENT_PATH = IDENT_PATH.with_name('vizelvision-sports.mp4')
SPORTS_PREFIX = 'sports-'
# The two IDs as the web app serves them (Ads › Idents), each a video and its end card's
# still, which ident/build.py draws beside the video (vizelvision-id.png).
IDENT_FILES = {'station-id': IDENT_PATH, 'sports-id': SPORTS_IDENT_PATH}


def is_sports_ident(name):
    """Whether a cued ID file, by the name the worker reports, is the Sports ID."""
    return isinstance(name, str) and name.startswith(SPORTS_PREFIX) and name.endswith('.mp4')


def ident_file(name):
    """An ID's video or still by its published name (station-id.mp4, sports-id.png); None
    when the name is unknown or the file has not been built."""
    found = re.fullmatch(r'(station-id|sports-id)\.(mp4|png)', name) if isinstance(name, str) else None
    if not found:
        return None
    path = IDENT_FILES[found[1]].with_suffix('.' + found[2])
    return path if path.is_file() else None


def file_identity(path):
    stat = Path(path).stat()
    return f'{stat.st_size}:{stat.st_mtime_ns}'


class IdentLease(FileLease):
    """The station ID file. Like a library file it is only read, and it keeps playing
    if the file is replaced underneath it."""
    lane = 'ident'

    def __init__(self, path):
        self.path = Path(path)
        self.target = {'source_id': IDENT_SOURCE_ID, 'channel_id': 'station-id'}
        self.generation = file_identity(self.path)
        self.uri = self.path.resolve().as_uri()

    def current(self):
        """False once the file is removed or rebuilt, so a cued copy can be replaced."""
        try:
            return file_identity(self.path) == self.generation
        except OSError:
            return False
