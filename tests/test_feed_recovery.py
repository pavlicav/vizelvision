"""Feed recovery: a live program whose input fails on air goes back on by itself.

On 1 October 2026 two TV-Thing feeds failed on air: NHK's audio timestamps jumped
backwards at 15:03 (a take held to an end time that had aired under two minutes, so it
was not put back), and Judy Justice stalled at 15:48 while TV-Thing restarted its stream
on the same channel (a scheduled show, which nothing put back): master sat on the test
card until the next entry.
"""
from datetime import timedelta
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from roku_stream.scheduler import utc_now
from roku_stream.source_queue import PREPARE_FAILED, RECOVERY_LIMIT, SourceQueue

TV = {'source_id': 'tv-thing-digital', 'channel_id': 'wdvm_sd_25_1'}
NFLN = {'source_id': 'youtube-tv', 'channel_id': 'NFL Network'}
FOX5 = {'source_id': 'tv-thing-digital', 'channel_id': 'wttg_dt_5_1'}
COLTS = {'league': 'nfl', 'game_pk': 401872965, 'game_date': '2026-10-04',
         'title': 'Indianapolis Colts at Washington Commanders'}
NEWS = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla'}
FILE = {'source_id': 'library', 'channel_id': 'rec/a.mp4'}
OFF_AIR = {'source_id': 'off-air', 'channel_id': 'off-air'}


def soon(seconds):
    return (utc_now() + timedelta(seconds=seconds)).isoformat()


class PrepareFailed(Exception):
    code = PREPARE_FAILED


class FakeMaster:
    """What the queue reads from master: the input on air, and the last input failure."""

    def __init__(self):
        self.on_air, self.failure, self.aired, self.refuse = None, None, [], 0

    def take(self, item):
        if self.refuse:
            self.refuse -= 1
            raise PrepareFailed('TV-Thing is restarting its stream')
        self.on_air = None if item.target['source_id'] == 'off-air' else {'id': uuid.uuid4().hex, **item.target}
        # Waiters treat the history entry as a completed take, including its state.
        self.aired.append(dict(item.target))
        return {'on_air': self.on_air}

    def fail(self, error='TV-Thing stream generation changed; prepare the source again', on_air=True):
        """The input on air fails: master falls back to the test card."""
        self.failure = {'target': dict(self.on_air), 'error': error, 'was_on_air': on_air, 'at': time.time()}
        self.on_air = None


class FeedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master = FakeMaster()
        self.game = {'finished': False, 'status': 'Top 7th'}
        self.ended = []
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', self.master.take, lambda *_: dict(self.game),
                                 poll_seconds=.01, hold_poll_seconds=.01, retry_seconds=.05,
                                 on_air=lambda: self.master.on_air, input_failure=lambda: self.master.failure,
                                 on_hold_end=self.ended.append)
        self.addCleanup(self.queue.close)

    def wait(self, check, message=None):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(message or repr([(i.title, i.status, i.gate_detail) for i in self.queue.list()]))

    def scheduled(self, target=TV, title='Judy Justice', ends_in=3600, kind='show', game=None):
        """A programming entry, as the schedule queues it, on air."""
        item = self.queue.add_scheduled({'target': target, 'title': title, 'kind': kind, 'game': game,
                                         'run_at': soon(.02), 'skip_after': soon(ends_in),
                                         'key': f'{soon(0)}|{kind}|show-1|{target["channel_id"]}'})
        self.queue.resume()
        count = len(self.master.aired) + 1
        self.wait(lambda: len(self.master.aired) == count)
        return item

    def settle(self):
        time.sleep(.15)

    def test_a_scheduled_show_whose_feed_fails_goes_back_on_as_itself(self):
        original = self.scheduled()
        self.master.fail()
        self.wait(lambda: self.master.aired == [TV, TV])
        again = next(i for i in self.queue.list() if i.id != original.id)
        self.assertEqual((again.origin, again.schedule_key, again.skip_after, again.title, again.kind),
                         (original.origin, original.schedule_key, original.skip_after, 'Judy Justice', 'show'))
        self.assertTrue(again.recovery)
        self.assertIn('TV-Thing stream generation changed', again.gate_detail)
        self.assertFalse(self.queue.status()['paused'])

    def test_a_scheduled_game_goes_back_on_until_it_is_final(self):
        game = {'league': 'mlb', 'game_pk': 1, 'game_date': '2026-10-01', 'title': 'Phillies at Braves'}
        self.scheduled(title='Phillies at Braves', kind='game', game=game)
        self.master.fail('Input audio/video stopped arriving')
        self.wait(lambda: len(self.master.aired) == 2)
        self.game.update(finished=True, status='Final')
        self.master.fail()
        self.settle()
        self.assertEqual(len(self.master.aired), 2, 'a game already final is not put back')

    def test_only_a_failure_of_the_input_on_air_counts(self):
        self.scheduled()
        self.master.on_air = None  # The operator's fallback: no failure.
        self.settle()
        self.master.failure = {'target': {'id': 'something-else'}, 'error': 'x', 'was_on_air': True}
        self.settle()
        self.assertEqual(self.master.aired, [TV])

    def test_a_failure_while_prepared_is_not_one_on_air(self):
        self.scheduled()
        self.master.fail(on_air=False)
        self.settle()
        self.assertEqual(self.master.aired, [TV])

    def test_a_show_at_the_end_of_its_slot_is_left_to_what_follows(self):
        self.scheduled(ends_in=30)
        self.master.fail()
        self.settle()
        self.assertEqual(self.master.aired, [TV])

    def test_a_feed_that_keeps_failing_goes_back_on_a_few_times_then_is_left(self):
        self.scheduled()
        for attempt in range(1, RECOVERY_LIMIT + 1):
            self.master.fail()
            self.wait(lambda: len(self.master.aired) == attempt + 1)
        self.master.fail()
        self.settle()
        self.assertEqual(len(self.master.aired), RECOVERY_LIMIT + 1)
        self.assertIsNone(self.master.on_air, 'left on the test card for the operator')

    def with_alternates(self):
        """The coordinator's answer for the Colts game: FOX 5 over the antenna, or YouTube TV."""
        def alternates(target, game):
            self.asked.append((dict(target), game))
            if target['source_id'] == 'youtube-tv':
                return {'antenna': FOX5, 'roku': {**NFLN, 'antenna': False}}
            return {'antenna': target, 'roku': {'source_id': 'youtube-tv', 'channel_id': 'FOX', 'antenna': False}}
        self.asked = []
        self.queue.alternates = alternates

    def test_a_game_goes_back_on_from_the_antenna_then_youtube_tv_when_the_antenna_keeps_failing(self):
        # 2026-10-04: Colts at Commanders failed on YouTube TV's NFL Network; FOX 5 over the
        # antenna carried it too, and when that failed it was never tried the other way.
        self.with_alternates()
        self.scheduled(target=NFLN, title=COLTS['title'], kind='game', game=COLTS)
        for attempt in range(1, RECOVERY_LIMIT + 1):
            self.master.fail('Input audio/video stopped arriving')
            self.wait(lambda: len(self.master.aired) == attempt + 1)
        self.assertEqual(self.master.aired, [NFLN] + [FOX5] * RECOVERY_LIMIT)
        again = self.queue.list()[0]
        self.assertEqual((again.program_target, again.title, again.game), (NFLN, COLTS['title'], COLTS))
        self.assertIn('from the antenna', [i for i in self.queue.list() if i.target == FOX5][-1].gate_detail)
        self.assertTrue(all(target == NFLN for target, _ in self.asked), 'chosen from the program each time')
        self.master.fail('Input audio/video stopped arriving')
        self.wait(lambda: len(self.master.aired) == RECOVERY_LIMIT + 2)
        self.assertEqual(self.master.aired[-1], {**NFLN, 'antenna': False})
        self.assertIn('from YouTube TV', self.queue.list()[0].gate_detail)

    def test_a_roku_still_playing_goes_back_on_before_the_antenna_until_its_budget_is_spent(self):
        # A failed Roku feed is nearly always a blip in the capture card: its feed goes back on
        # without navigating, as fast as the antenna and in the better picture.
        self.with_alternates()
        asked = []
        self.queue.roku_playing = lambda target: asked.append(dict(target)) or True
        self.scheduled(target=NFLN, title=COLTS['title'], kind='game', game=COLTS)
        for attempt in range(1, RECOVERY_LIMIT + 2):
            self.master.fail('Input video is over a second behind its audio; prepare the source again')
            self.wait(lambda: len(self.master.aired) == attempt + 1)
        self.assertEqual(self.master.aired, [NFLN] + [{**NFLN, 'antenna': False}] * RECOVERY_LIMIT + [FOX5])
        self.assertEqual(asked[0], NFLN, 'asked about the program')

    def test_a_roku_that_no_longer_plays_leaves_the_antenna_first(self):
        self.with_alternates()
        self.queue.roku_playing = lambda target: False
        self.scheduled(target=NFLN, title=COLTS['title'], kind='game', game=COLTS)
        self.master.fail('Input audio/video stopped arriving')
        self.wait(lambda: len(self.master.aired) == 2)
        self.assertEqual(self.master.aired[-1], FOX5)

    def test_a_failing_check_leaves_the_antenna_first(self):
        self.with_alternates()
        def broken(target):
            raise OSError('No route to host')
        self.queue.roku_playing = broken
        self.scheduled(target=NFLN, title=COLTS['title'], kind='game', game=COLTS)
        with self.assertLogs('roku_stream.source_queue', 'WARNING') as logs:
            self.master.fail('Input audio/video stopped arriving')
            self.wait(lambda: len(self.master.aired) == 2)
        self.assertEqual(self.master.aired[-1], FOX5)
        self.assertTrue(any('Could not check what the Roku plays' in line for line in logs.output), logs.output)

    def test_every_source_used_up_leaves_the_program_to_the_operator(self):
        self.with_alternates()
        self.scheduled(target=NFLN, title=COLTS['title'], kind='game', game=COLTS)
        for attempt in range(1, 2 * RECOVERY_LIMIT + 1):
            self.master.fail('Input audio/video stopped arriving')
            self.wait(lambda: len(self.master.aired) == attempt + 1)
        with self.assertLogs('roku_stream.source_queue', 'WARNING') as logs:
            self.master.fail()
            self.settle()
        self.assertEqual(len(self.master.aired), 2 * RECOVERY_LIMIT + 1)
        self.assertTrue(any('every source carrying it' in line for line in logs.output), logs.output)

    def test_an_antenna_station_falls_back_to_its_network_on_youtube_tv(self):
        self.with_alternates()
        self.scheduled(target=FOX5)
        for attempt in range(1, RECOVERY_LIMIT + 2):
            self.master.fail('Input audio/video stopped arriving')
            self.wait(lambda: len(self.master.aired) == attempt + 1)
        self.assertEqual(self.master.aired, [FOX5] * (RECOVERY_LIMIT + 1)
                         + [{'source_id': 'youtube-tv', 'channel_id': 'FOX', 'antenna': False}])

    def test_why_a_feed_is_not_put_back_is_logged(self):
        self.scheduled(ends_in=30)
        with self.assertLogs('roku_stream.source_queue', 'WARNING') as logs:
            self.master.fail()
            self.settle()
        self.assertTrue(any('its slot ends' in line for line in logs.output), logs.output)

    def test_a_tuner_still_restarting_is_tried_again(self):
        self.scheduled()
        self.master.refuse = 1
        self.master.fail()
        self.wait(lambda: self.master.aired == [TV, TV])
        again = self.queue.list()[0]
        self.assertEqual((again.status, again.prepare_attempts), ('succeeded', 1))

    def test_a_paused_queue_leaves_it_to_the_operator(self):
        self.scheduled()
        self.queue.pause()
        self.master.fail()
        self.settle()
        self.assertEqual(self.master.aired, [TV])

    def test_files_and_the_test_card_are_not_feeds(self):
        self.scheduled(target=FILE, title='A recording')
        self.master.fail('File ended before it was taken')
        self.settle()
        self.assertEqual(self.master.aired, [FILE])

    def test_a_new_program_replaces_the_one_watched(self):
        self.scheduled()
        failed = dict(self.master.on_air)
        self.scheduled(target=NEWS, title='News')
        self.master.failure = {'target': failed, 'error': 'late news of the old feed', 'was_on_air': True}
        self.master.on_air = None
        self.settle()
        self.assertEqual(self.master.aired, [TV, NEWS])

    def test_a_restart_keeps_watching_the_program_on_air(self):
        self.scheduled()
        self.queue.close()
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', self.master.take, lambda *_: dict(self.game),
                                 poll_seconds=.01, on_air=lambda: self.master.on_air,
                                 input_failure=lambda: self.master.failure)
        self.addCleanup(self.queue.close)
        self.queue.resume()  # A restart starts paused for review.
        self.settle()
        self.master.fail()
        self.wait(lambda: self.master.aired == [TV, TV])
        self.assertTrue(self.queue.list()[0].recovery)

    def test_a_held_take_goes_back_on_once_through_its_hold_even_if_it_had_barely_aired(self):
        self.queue.hold_lost_seconds = .05
        self.queue.add_target(TV, 'now', hold_end={'until': soon(3600)})
        self.queue.resume()
        self.wait(lambda: self.queue.status()['hold'])
        self.master.fail('Input audio timestamps changed (delta_ms=-21.3)')
        self.wait(lambda: len(self.master.aired) == 2)
        self.settle()
        self.assertEqual(len(self.master.aired), 2, 'put back once, not by both paths')
        self.assertTrue(self.queue.list()[0].recovery)

    def test_a_held_take_whose_input_master_failed_goes_back_on_at_once(self):
        # 2026-10-04 12:11:01 master failed the held NFL Network input; the queue waited out
        # its 20 s on the test card before putting the game back on from the antenna.
        self.queue.hold_lost_seconds = 60
        self.queue.add_target(TV, 'now', hold_end={'until': soon(3600)})
        self.queue.resume()
        self.wait(lambda: self.queue.status()['hold'])
        self.master.fail('Input video is over a second behind its audio; prepare the source again')
        self.wait(lambda: len(self.master.aired) == 2)
        self.assertTrue(self.queue.list()[0].recovery)

    def test_a_held_take_waits_while_master_recovers_its_input(self):
        self.queue.hold_lost_seconds = 60
        self.queue.add_target(TV, 'now', hold_end={'until': soon(3600)})
        self.queue.resume()
        self.wait(lambda: self.queue.status()['hold'])
        self.master.fail('Input audio/video stopped arriving')
        self.master.failure['recovering'] = True  # master waits for it on the test card
        self.settle()
        self.assertEqual(len(self.master.aired), 1)
        self.master.failure = {**self.master.failure, 'recovering': False,
                               'error': 'Input did not recover within 8 seconds; prepare the source again'}
        self.wait(lambda: len(self.master.aired) == 2)

    def test_a_held_take_shares_the_budget(self):
        self.queue.hold_lost_seconds = .05
        with self.queue._condition:
            self.queue._recoveries[(TV['source_id'], TV['channel_id'])] = [time.monotonic()] * RECOVERY_LIMIT
        self.queue.add_target(TV, 'now', hold_end={'until': soon(3600)})
        self.queue.resume()
        self.wait(lambda: self.queue.status()['hold'])
        self.master.fail()
        self.wait(lambda: self.ended)
        self.settle()
        self.assertEqual(self.master.aired, [TV])


class RokuWatchTests(unittest.TestCase):
    """A Roku on air whose player stops while its capture runs on fails like a feed.

    2026-10-12: after Dodgers–Brewers went back to YouTube TV at 20:04, YouTube TV stopped
    and the Roku City screensaver aired as the game until 20:21, under ad mute's My ads:
    master saw a healthy capture, so nothing put the game back on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master = FakeMaster()
        self.reading = {'playing': True, 'reason': None}
        self.still_playing = False
        self.checks = []
        self.queue = SourceQueue(Path(self.tmp.name) / 'queue.json', self.master.take,
                                 lambda *_: {'finished': False, 'status': 'Top 9th'},
                                 poll_seconds=.01, hold_poll_seconds=.01, start_worker=False,
                                 on_air=lambda: self.master.on_air, input_failure=lambda: self.master.failure,
                                 alternates=lambda *_: {'antenna': FOX5},
                                 roku_player=lambda: self.reading, roku_playing=self.check)
        self.queue.roku_watch_seconds, self.queue.roku_stopped_seconds = .02, .1
        self.queue.start()
        self.addCleanup(self.queue.close)

    def check(self, target):
        self.checks.append(dict(target))
        return self.still_playing

    def wait(self, check):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.01)
        self.fail(repr([(i.title, i.status, i.gate_detail) for i in self.queue.list()]))

    def on_air(self, **kwargs):
        self.queue.add_target(NFLN, 'now', **kwargs)
        self.queue.resume()
        self.wait(lambda: self.master.aired == [NFLN])

    def test_a_held_game_whose_roku_stopped_goes_back_on_from_the_antenna(self):
        self.on_air(hold_end={'until': soon(3600)})
        self.wait(lambda: self.queue.status()['hold'])
        self.reading = {'playing': False, 'reason': 'its player is close'}
        self.wait(lambda: self.master.aired == [NFLN, FOX5])
        again = self.queue.list()[0]
        self.assertTrue(again.recovery)
        self.assertIn('from the antenna', again.gate_detail)
        self.assertEqual(self.queue.status()['hold']['until'], again.hold_end['until'])

    def test_a_scheduled_program_whose_roku_stopped_goes_back_on(self):
        self.queue.add_scheduled({'target': NFLN, 'title': 'Colts at Commanders', 'kind': 'show',
                                  'run_at': soon(.02), 'skip_after': soon(3600), 'key': f'{soon(0)}|show|s|NFLN'})
        self.queue.resume()
        self.wait(lambda: self.master.aired == [NFLN])
        self.reading = {'playing': False, 'reason': 'the Roku is in Roku Dynamic Menu'}
        self.wait(lambda: self.master.aired == [NFLN, FOX5])
        self.assertIn('The Roku stopped playing (the Roku is in Roku Dynamic Menu)', self.queue.list()[0].gate_detail)

    def test_a_brief_stop_is_ridden_out(self):
        self.on_air(hold_end={'until': soon(3600)})
        self.queue.roku_stopped_seconds = 60
        self.reading = {'playing': False, 'reason': 'its player is buffer'}
        time.sleep(.2)
        self.reading = {'playing': True, 'reason': None}
        time.sleep(.1)
        self.assertEqual(self.master.aired, [NFLN])
        self.assertEqual(self.checks, [])

    def test_a_roku_the_full_check_finds_playing_stays_on(self):
        self.on_air(hold_end={'until': soon(3600)})
        self.still_playing = True
        self.reading = {'playing': False, 'reason': 'its player is pause'}
        self.wait(lambda: self.checks)
        time.sleep(.1)
        self.assertEqual(self.master.aired, [NFLN])
        self.assertEqual(self.checks[0], NFLN)

    def test_an_unknown_reading_and_other_sources_are_left_alone(self):
        self.on_air()
        self.reading = None  # A navigation running, the Roku moved by hand, no fresh reading.
        time.sleep(.2)
        self.queue.add_target(TV, 'now')
        self.wait(lambda: self.master.aired == [NFLN, TV])
        self.reading = {'playing': False, 'reason': 'its player is close'}
        time.sleep(.2)
        self.assertEqual(self.master.aired, [NFLN, TV])
        self.assertEqual(self.checks, [])


if __name__ == '__main__':
    unittest.main()
