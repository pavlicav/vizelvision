"""Makes the Schedule page's fixtures from the real engine: programming.json (the lineup as
slots, with its airings), playback.json's schedule keys, and the sports slots, ideas, library
folders and programme search the page reads.

    python3 tests/fixtures/ui/make_schedule.py

programming_v1.json is the live station's schedule of 2026-10-01 (a painted grid), which the
engine converts as it would on its first start. Slots get fixed ids so the fixtures are the
same every time: three of them are made to follow the listings, air a library folder and
have nothing listed, as examples of each.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from roku_stream import programming as programming_module  # noqa: E402
from roku_stream.guide_index import GuideIndex  # noqa: E402
from roku_stream.programming import Programming  # noqa: E402
from roku_stream.source_queue import SourceQueue  # noqa: E402
from roku_stream.sports_slots import PRESETS  # noqa: E402

ZONE = ZoneInfo('US/Eastern')
WJLA = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=ZONE).astimezone(timezone.utc)


def write(name, value):
    (HERE / name).write_text(json.dumps(value, indent=1, sort_keys=True) + '\n')


def main():
    old = json.loads((HERE / 'programming_v1.json').read_text())
    now = datetime.fromisoformat(old['now'])
    programming_module.utc_now = lambda: now   # Airings are settled as of the fixtures' moment.
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / 'programming.json').write_text(json.dumps({'version': 1, **old['settings']}))
        queue = SourceQueue(folder / 'queue.json', lambda item: {}, lambda *_: {}, start_worker=False)
        programming = Programming(folder / 'programming.json', queue, zone=ZONE, start_worker=False)
        # Friday's and Monday's listings: Jeopardy! is on WJLA on Friday (a new one), and
        # nothing by the name of the Sunday film is listed at all.
        rows = {'7.1': {'kind': 'digital', 'id': 'wjla_7_1', 'number': '7.1', 'name': 'WJLA', 'events': [
            {'title': 'Jeopardy!', 'start': at(2, 19, 30).timestamp(), 'duration': 1800, 'new': True, 'episode_title': 'Tournament of Champions'},
            {'title': 'The View', 'start': at(2, 11).timestamp(), 'duration': 3600, 'new': True},
            {'title': 'Wheel of Fortune', 'start': at(2, 19).timestamp(), 'duration': 1800},
            {'title': '7News at 11', 'start': at(4, 23).timestamp(), 'duration': 2100}]}}
        guide = GuideIndex(lambda: {'generated_at': 1, 'channels': rows}, zone=ZONE, wall=now.timestamp)
        programming.guide = guide
        files = [{'id': f"jellyfin-tv/How It's Made/Season 1/S01E{n:02d}.mkv", 'root': 'jellyfin-tv',
                  'path': f"How It's Made/Season 1/S01E{n:02d}.mkv", 'title': f"How It's Made S01E{n:02d}", 'duration': 1281,
                  'playable': True, 'ad_breaks': {'state': 'ok', 'at': [348, 660, 995]}} for n in range(1, 9)]
        programming.library = lambda: {'items': files, 'roots': [{'id': 'jellyfin-tv', 'name': 'Jellyfin TV'}]}
        with programming.lock:
            for number, slot in enumerate(programming.data['slots'], 1):
                slot['id'] = f'slot{number:02d}'
        jeopardy = next(s for s in programming.slots() if s['title'] == 'Jeopardy')
        programming.update_slot(jeopardy['id'], {'title': 'Jeopardy!', 'what': {'kind': 'program', 'title': 'Jeopardy!', 'target': WJLA}})
        programming.add_slot({'id': 'slotmade', 'title': "How It's Made", 'color': '#5a6f2f', 'days': ['sat', 'sun'], 'start': '20:00',
                              'minutes': 30, 'what': {'kind': 'library', 'root': 'jellyfin-tv', 'path': "How It's Made/", 'order': 'next',
                                                      'ad_breaks': 120}})
        programming.add_slot({'id': 'slotfilm', 'title': 'Sunday Film', 'color': '#8f3a4f', 'days': ['sun'], 'start': '14:00',
                              'minutes': 120, 'what': {'kind': 'program', 'title': 'The Sunday Film'}})
        mnf = {k: v for k, v in PRESETS[0].items() if k != 'blurb'}
        programming.add_sports_slot({**mnf, 'id': 'sportmnf'})
        lions = next(s for s in programming.shows() if s['title'].startswith('Atlanta Falcons'))
        programming.tag_show(lions['id'], slot='sportmnf', slot_priority='high', own_priority='normal', priority='high')
        described = programming.describe(now)
        described['last_sync'] = described['games_checked_at'] = old['last_sync']
        write('programming.json', described)

        # The projection as it was, with the keys the engine now gives each segment.
        playback = json.loads((HERE / 'playback.json').read_text())
        slots = {slot['title']: slot['id'] for slot in described['settings']['slots']}
        slots['Jeopardy'] = slots['Jeopardy!']
        shows = {show['title']: show['id'] for show in described['settings']['shows']}
        for part in playback['segments'] + playback.get('dropped', []):
            ref = slots.get(part['title']) if part['kind'] == 'block' else shows.get(part['title']) if part['kind'] in ('game', 'show') else None
            part['key'] = f"{part.get('start') or part.get('due')}|{part['kind']}|{ref}|" if ref else part.get('key') if 'due' in part else None
        write('playback.json', playback)

        sports = {'slots': programming.sports_slots(), 'presets': [dict(p) for p in PRESETS[1:4]], 'checked_at': old['last_sync'],
                  'errors': {}, 'days': 8, 'check_minutes': 10,
                  'games': [{'slot': 'sportmnf', 'slot_title': 'Monday Night Football', 'league': 'nfl', 'game_pk': 401772816,
                             'game_date': '2026-10-05', 'title': lions['title'], 'start_time': lions['start'], 'networks': ['ESPN'],
                             'target': lions['target'], 'favorites': [], 'status': 'shared', 'show_id': lions['id'],
                             'start': lions['start'], 'priority': 'high'}]}
        write('programming_sports.json', sports)
        write('programming_library.json', {'folders': programming.library_folders()})
        write('programming_search.json', {'programmes': guide.search('jeopardy')})
        strip = {'title': 'Wheel of Fortune', 'days': ['mon', 'tue', 'wed', 'thu', 'fri'], 'start': '19:00', 'minutes': 30,
                 'what': {'kind': 'program', 'title': 'Wheel of Fortune', 'target': WJLA, 'follow': True}}
        made = {'title': 'Cab Rides', 'days': ['sat', 'sun'], 'start': '13:00', 'minutes': 120,
                'what': {'kind': 'library', 'root': 'cab-rides', 'order': 'shuffle'}}
        view = next(s for s in described['settings']['slots'] if s['title'] == 'The View')
        ideas = {'generated_at': old['now'], 'seconds': .4, 'count': 5, 'guide': guide.status(),
                 'draft': [{'id': 'strip:wheel', 'days': ['mon', 'tue', 'wed', 'thu']}, {'id': 'library:cab-rides', 'days': ['sat', 'sun']}],
                 'groups': [
                     {'id': 'sports', 'title': 'Sports slots', 'blurb': 'Standing appointments: every game the rule finds goes on by itself.', 'ideas': [
                         {'id': 'sports:nfl-snf', 'group': 'sports', 'title': 'Sunday Night Football', 'why': PRESETS[2]['blurb'], 'score': 48,
                          'detail': 'Kansas City Chiefs at Buffalo Bills · NBC', 'when': at(4, 20, 20).isoformat(), 'count': 1,
                          'games': [{'title': 'Kansas City Chiefs at Buffalo Bills', 'start_time': at(4, 20, 20).isoformat(), 'networks': ['NBC']}],
                          'apply': {'method': 'POST', 'path': 'v1/programming/sports', 'body': {k: v for k, v in PRESETS[2].items() if k != 'blurb'}}}]},
                     {'id': 'fixups', 'title': 'Let these follow the listings', 'blurb': 'Slots tied to one channel whose programme the listings know.', 'ideas': [
                         {'id': 'fix:' + view['id'], 'group': 'fixups', 'slot': view['id'], 'title': 'The View', 'score': 24,
                          'why': 'It is in the listings: follow it, and its channel and times look after themselves.',
                          'detail': 'Weekdays · 11:00 AM · 7.1 WJLA',
                          'apply': {'method': 'POST', 'path': 'v1/programming/slots/' + view['id'], 'body': {
                              'what': {'kind': 'program', 'title': 'The View', 'target': view['what']['target'], 'follow': True}}}}]},
                     {'id': 'strips', 'title': 'On at the same time every day', 'blurb': 'From the listings, and what the atlas has seen so far.', 'ideas': [
                         {'id': 'strip:wheel', 'group': 'strips', 'title': 'Wheel of Fortune', 'score': 22, 'free': True, 'part': 3,
                          'why': 'Weekdays at 7:00 PM on 7.1 WJLA · new episodes', 'detail': '30 min · seen on 4 days',
                          'when': at(2, 19).isoformat(), 'days': strip['days'], 'start': '19:00', 'minutes': 30,
                          'apply': {'method': 'POST', 'path': 'v1/programming/slots', 'body': strip}}]},
                     {'id': 'soon', 'title': 'Coming up once', 'blurb': 'Live events, premieres and new episodes in the next day or two.', 'ideas': [
                         {'id': 'soon:wjla_7_1:1', 'group': 'soon', 'title': 'Dancing With the Stars', 'score': 13, 'why': 'live · new',
                          'detail': '7.1 WJLA · 120 min', 'when': at(2, 20).isoformat(),
                          'apply': {'method': 'POST', 'path': 'v1/programming/shows', 'body': {
                              'mode': 'program', 'title': 'Dancing With the Stars', 'target': WJLA, 'start': at(2, 20).isoformat(),
                              'end': at(2, 22).isoformat(), 'priority': 'normal'}}}]},
                     {'id': 'library', 'title': 'From the library', 'blurb': 'Folders with enough to fill a slot every day.', 'ideas': [
                         {'id': 'library:cab-rides', 'group': 'library', 'title': 'Cab Rides', 'score': 20, 'free': True,
                          'why': 'One at random each time.', 'detail': '144 files · about 101 min each', 'days': made['days'],
                          'start': '13:00', 'minutes': 120, 'apply': {'method': 'POST', 'path': 'v1/programming/slots', 'body': made}}]}]}
        write('programming_ideas.json', ideas)
        queue.close()
    print('Wrote the Schedule fixtures:', len(described['settings']['slots']), 'slots,', len(described['airings']), 'airings')


if __name__ == '__main__':
    main()
