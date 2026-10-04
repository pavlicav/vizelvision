"""What follows a game: a game already under way, then recordings from Up next until the
next live show, then the regular schedule. Recordings fill time around the timed rundown."""
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from roku_stream.programming import OFF_AIR
from roku_stream.scheduler import utc_now
from roku_stream.source_queue import SourceQueue

MLB = {'source_id': 'mlb', 'channel_id': '1', 'date': '2026-09-30'}
ESPN = {'source_id': 'youtube-tv', 'channel_id': 'ESPN'}
NBC = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
TBS = {'source_id': 'youtube-tv', 'channel_id': 'TBS'}
GAME = {'league': 'mlb', 'game_pk': 1, 'game_date': '2026-09-30', 'title': 'Phillies at Braves'}


class Station:
    """Master as the queue sees it: what each take put on air, and whether a file has ended."""

    def __init__(self):
        self.on_air, self.aired, self.file_done = None, [], False
        self.game = {'finished': False, 'status': 'In Progress', 'title': GAME['title'],
                     'summary': 'Phillies 4, Braves 2 · Top 8th'}

    def take(self, item):
        self.aired.append(item.title or item.target['channel_id'])
        self.on_air = None if item.target['source_id'] == 'off-air' else dict(item.target)
        self.file_done = False
        return {'on_air': self.on_air}

    def media_gate(self, item):
        playing = (self.on_air or {}).get('source_id') == 'library' and not self.file_done
        return {'finished': not playing, 'status': 'Plays when the file ends'}


class AfterTheGameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.station = Station()
        self.on_hold_end = Mock()
        self.ident = Mock()
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', self.station.take,
                                 lambda *_: dict(self.station.game), poll_seconds=.01, hold_poll_seconds=.01,
                                 media_gate=self.station.media_gate, on_air=lambda: self.station.on_air,
                                 game_on=lambda item: dict(GAME) if item.target == TBS else None,
                                 on_hold_end=self.on_hold_end, ident=self.ident, ident_seconds=.3,
                                 final_buffer_seconds=0)
        self.addCleanup(self.queue.close)
        # Tests cannot wait a minute: a schedule entry 0.1 s past its start is joined late.
        late = patch('roku_stream.source_queue.LATE', timedelta(seconds=.1))
        late.start()
        self.addCleanup(late.stop)

    def schedule(self, title, target, kind, *, run_in, skip_in=None, game=False, ref=None):
        now = utc_now()
        run_at = (now + timedelta(seconds=run_in)).isoformat()
        return self.queue.add_scheduled({
            'key': '|'.join((run_at, kind, ref or title, json.dumps(target, sort_keys=True))),
            'run_at': run_at, 'target': target, 'title': title, 'kind': kind,
            'skip_after': (now + timedelta(seconds=skip_in)).isoformat() if skip_in is not None else None,
            **({'after_game': dict(GAME)} if game else {})})

    def record(self, name):
        return self.queue.add_target({'source_id': 'library', 'channel_id': name}, 'after_current')

    def wait(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(f'{self.station.aired} {self.queue.status()}')

    def test_recordings_fill_after_the_game_until_the_next_live_show(self):
        self.schedule('Game', MLB, 'game', run_in=.05)
        back = self.schedule('News', NBC, 'backup', run_in=.05, skip_in=30, game=True, ref='g:news')
        first, second = self.record('r1'), self.record('r2')
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['Game'])
        time.sleep(.3)  # A live game owns master: the recordings wait.
        self.assertEqual(self.station.aired, ['Game'])
        self.assertIn('what is on air ends', self.queue.get(first.id).gate_detail)
        self.assertEqual(self.queue.status()['games']['mlb:1']['summary'], 'Phillies 4, Braves 2 · Top 8th')
        self.station.game['finished'] = True
        # The schedule's block already under way gives way to the recordings.
        self.wait(lambda: self.station.aired == ['Game', 'r1'])
        self.assertEqual((self.queue.get(back.id).status, self.queue.get(back.id).gate_status,
                          self.queue.get(back.id).gate_detail),
                         ('skipped', 'gave_way', 'Recordings from Up next play instead'))
        # A live show starting now cuts in, although r2 was queued before it.
        self.schedule('Late news', NBC, 'block', run_in=.2, skip_in=30)
        self.wait(lambda: self.station.aired == ['Game', 'r1', 'Late news'])
        time.sleep(.1)
        self.assertEqual(self.queue.get(second.id).status, 'queued')
        # The schedule's next gap: OFF AIR gives way and the recordings pick up again.
        gap = self.schedule('OFF AIR', OFF_AIR, 'off_air', run_in=.2, skip_in=30)
        self.wait(lambda: self.station.aired == ['Game', 'r1', 'Late news', 'r2'])
        self.assertEqual(self.queue.get(gap.id).gate_status, 'gave_way')

    def test_recordings_chain_until_a_later_part_of_the_schedule_starts(self):
        self.schedule('Game', MLB, 'game', run_in=.05)
        self.schedule('News', NBC, 'backup', run_in=.05, skip_in=30, game=True, ref='g:news')
        self.schedule('Sports', ESPN, 'backup', run_in=2.8, skip_in=30, game=True, ref='g:sports')
        self.record('r1'), self.record('r2')
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['Game'])
        time.sleep(.3)  # The news block is under way when the game ends.
        self.station.game['finished'] = True
        self.wait(lambda: self.station.aired == ['Game', 'r1'])
        self.station.file_done = True  # r2 follows r1 although the next block is waiting.
        self.wait(lambda: self.station.aired == ['Game', 'r1', 'r2'])
        self.wait(lambda: self.station.aired == ['Game', 'r1', 'r2', 'Sports'])

    def test_an_entry_after_a_game_does_not_stop_recordings_but_cuts_in_at_the_final(self):
        self.station.on_air = {'source_id': 'library', 'channel_id': 'playing'}
        after = self.queue.add_target(NBC, 'after_game', after_game=dict(GAME))
        self.record('r1')
        self.queue.resume()
        time.sleep(.2)
        self.station.file_done = True
        self.wait(lambda: self.station.aired == ['r1'])
        self.station.game['finished'] = True
        self.wait(lambda: self.station.aired == ['r1', 'NBC'])
        self.assertEqual(self.queue.get(after.id).status, 'succeeded')

    def test_a_game_already_under_way_follows_the_game(self):
        self.schedule('Game 1', MLB, 'game', run_in=.05)
        back = self.schedule('News', NBC, 'backup', run_in=.05, skip_in=30, game=True, ref='g1:news')
        self.schedule('Game 2', ESPN, 'game', run_in=.15)
        self.record('r1')
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['Game 1'])
        time.sleep(.3)  # Game 2 has started but waits for game 1's final.
        self.assertEqual(self.station.aired, ['Game 1'])
        self.station.game['finished'] = True
        self.wait(lambda: self.station.aired == ['Game 1', 'Game 2'])
        self.assertEqual(self.queue.get(back.id).gate_detail, 'The game already under way airs instead')

    def test_the_schedule_follows_when_nothing_else_waits(self):
        self.schedule('Game', MLB, 'game', run_in=.05)
        self.schedule('News', NBC, 'backup', run_in=.05, skip_in=30, game=True, ref='g:news')
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['Game'])
        self.station.game['finished'] = True
        self.wait(lambda: self.station.aired == ['Game', 'News'])

    def test_the_schedule_waits_for_the_final_score_to_air(self):
        self.queue.final_buffer_seconds = .5
        self.schedule('Game', MLB, 'game', run_in=.05)
        back = self.schedule('News', NBC, 'backup', run_in=.05, skip_in=30, game=True, ref='g:news')
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['Game'])
        self.station.game.update(finished=True, summary='Final · Phillies 5, Braves 3')
        self.wait(lambda: 'final score' in (self.queue.get(back.id).gate_detail or ''))
        final = time.monotonic()
        self.assertEqual(self.station.aired, ['Game'])
        self.wait(lambda: self.station.aired == ['Game', 'News'])
        self.assertGreater(time.monotonic() - final, .3)

    def test_a_game_queued_by_hand_holds_master_until_final(self):
        self.queue.add_target(TBS, 'now')
        later = self.queue.add_target(NBC, 'at_time', run_at=(utc_now() + timedelta(seconds=.4)).isoformat())
        self.record('r1')
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['TBS'])
        self.wait(lambda: (self.queue.status()['hold'] or {}).get('detail') == 'Phillies 4, Braves 2 · Top 8th')
        self.assertEqual(self.queue.status()['hold']['game']['title'], GAME['title'])
        time.sleep(.6)  # NBC is due, but the game holds master.
        self.assertEqual((self.station.aired, self.queue.get(later.id).status), (['TBS'], 'queued'))
        self.queue.remove(later.id)
        self.station.game['finished'] = True
        # The final ends the hold; the recording follows although the game's channel is still on.
        self.wait(lambda: self.station.aired == ['TBS', 'r1'])
        self.on_hold_end.assert_called_once()
        self.assertIsNone(self.queue.status()['hold'])

    def test_a_recording_waits_while_a_live_channel_owns_master(self):
        self.station.on_air = dict(NBC)
        # The queue reads master before it takes its lock: let a paused pass see NBC first,
        # or a pass that read the test card a moment earlier may release the recording.
        time.sleep(.05)
        item = self.record('r1')
        self.queue.resume()
        time.sleep(.2)
        self.assertEqual((self.station.aired, self.queue.get(item.id).status), ([], 'queued'))
        self.station.on_air = None  # The test card: master is free.
        self.wait(lambda: self.station.aired == ['r1'])

    def test_off_air_gives_way_to_a_recording_on_air_without_a_station_id(self):
        self.station.on_air = {'source_id': 'library', 'channel_id': 'playing'}
        gap = self.schedule('OFF AIR', OFF_AIR, 'off_air', run_in=.5, skip_in=30)
        self.queue.resume()
        self.wait(lambda: self.queue.get(gap.id).status == 'skipped')
        self.assertEqual((self.queue.get(gap.id).gate_status, self.station.aired), ('gave_way', []))
        self.ident.assert_not_called()

    def test_a_live_show_on_time_does_not_give_way(self):
        self.station.on_air = {'source_id': 'library', 'channel_id': 'playing'}
        self.record('r1')
        self.schedule('News', NBC, 'block', run_in=.5, skip_in=30)
        self.queue.resume()
        self.wait(lambda: self.station.aired == ['News'])
        self.ident.assert_called_once()


if __name__ == '__main__':
    unittest.main()
