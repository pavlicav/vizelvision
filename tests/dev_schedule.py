"""A schedule to try things on: the real listings, library and sports feeds, none of the station.

Builds a Programming (with the guide index, sports slots and discovery) over a state folder
of its own, seeded with the live station's schedule read from its API. The queue never
runs anything: its worker is not started and its executor does nothing. Used by
tests/dev_schedule_server.py and for dry runs:

    python3 -m tests.dev_schedule /tmp/vv-dev-state
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.request import urlopen

from roku_stream.config import load_config
from roku_stream.baseball import BaseballCatalog
from roku_stream.discover import Discovery
from roku_stream.favorites import Favorites
from roku_stream.guide_index import GuideIndex
from roku_stream.programming import Programming
from roku_stream.source_queue import SourceQueue
from roku_stream.sports import SportsCatalog
from roku_stream.sports_slots import SportsSlots

LIVE = 'http://127.0.0.1:6970/'
TV_THING = 'http://127.0.0.1:8080/'


def get(url, timeout=60):
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def build(folder, config_path='/home/vivian/vizelVision/config.master.json', seed=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    state = folder / 'programming.json'
    if seed and not state.exists():
        live = get(LIVE + 'v1/programming')['settings']
        # The live station may still keep the painted grid (version 1) or already slots.
        version = 2 if 'slots' in live else 1
        state.write_text(json.dumps({'version': version, **live}))
        (folder / 'favorites.json').write_text(json.dumps(
            {'version': 1, 'favorites': get(LIVE + 'v1/favorites')['favorites'], 'air': False, 'planned': {}}))
    config = load_config(config_path)
    baseball = BaseballCatalog(config)
    sports = SportsCatalog(config, baseball)
    sports.antenna_only = lambda name: None
    queue = SourceQueue(folder / 'queue.json', lambda item: {}, sports.game_status, start_worker=False)
    programming = Programming(state, queue, game=sports.game, locate=sports.locate, start_worker=False)
    guide = GuideIndex(lambda: get(TV_THING + 'api/v1/guide?hours=168'), folder / 'guide-atlas.json', zone=programming.zone)
    programming.guide = guide
    sports.listings = lambda: get(TV_THING + 'api/v1/guide?hours=24')['channels']
    library = {'at': None}

    def files():
        if library['at'] is None:
            library['listing'] = get(LIVE + 'v1/sources/library/programs')
            library['at'] = True
        return library['listing']
    programming.library = files
    favorites = Favorites(folder / 'favorites.json')
    programming.favorites = favorites.order
    slots = SportsSlots(programming, sports, favorites=favorites.order)
    discovery = Discovery(programming, guide, sports_slots=slots, library=files, queue=queue)
    return {'config': config, 'programming': programming, 'queue': queue, 'guide': guide, 'sports': sports,
            'sports_slots': slots, 'discovery': discovery, 'favorites': favorites}


if __name__ == '__main__':
    built = build(sys.argv[1] if len(sys.argv) > 1 else '/tmp/vv-dev-state')
    programming, discovery = built['programming'], built['discovery']
    print('slots:')
    for slot in programming.slots():
        print('  ', slot['days'], slot['start'], slot['minutes'], slot['title'], slot['what'])
    print('guide:', built['guide'].status())
    ideas = discovery.ideas()
    print('ideas in', ideas['seconds'], 's')
    for group in ideas['groups']:
        print('==', group['title'])
        for idea in group['ideas']:
            print('  %5.1f  %s | %s | %s' % (idea['score'], idea['title'], idea['why'], idea.get('detail')))
    print('draft:', ideas['draft'])
