"""The "We now join..." bumper: the update read before master joins a game in progress."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import wave

from roku_stream import sports_join
from roku_stream.errors import ConfigError
from roku_stream.sports_join import SportsJoin, game_of, line


def mlb(away, home, half='Bottom', inning=5, state='Live'):
    return {'state': state, 'period': inning, 'half': half,
            'away': {'nickname': 'Dodgers', 'score': away}, 'home': {'nickname': 'Braves', 'score': home}}


def espn(away, home, period=4, detail='4th - 8:31', clock=511.0, state='in'):
    return {'state': state, 'period': period, 'detail': detail, 'clock': clock,
            'away': {'nickname': 'Bengals', 'score': str(away)}, 'home': {'nickname': 'Jaguars', 'score': str(home)}}


class LineTests(unittest.TestCase):
    def test_baseball(self):
        self.assertEqual(line('mlb', mlb(1, 3)),
                         'We now join the Dodgers and the Braves, with the Braves leading 3 to 1 in the bottom of the fifth.')
        self.assertEqual(line('mlb', mlb(2, 2, 'Top', 9)),
                         'We now join the Dodgers and the Braves, who are tied at 2 in the top of the ninth.')
        self.assertEqual(line('mlb', mlb(0, 0, 'Middle', 1)),
                         'We now join the Dodgers and the Braves, who are scoreless in the middle of the first.')
        self.assertEqual(line('mlb', mlb(4, 3, 'End', 11)),
                         'We now join the Dodgers and the Braves, with the Dodgers leading 4 to 3 at the end of the eleventh.')

    def test_football(self):
        self.assertEqual(line('nfl', espn(7, 7)),
                         'We now join the Bengals and the Jaguars, who are tied at 7 in the fourth quarter.')
        self.assertEqual(line('nfl', espn(14, 7, 2, 'Halftime', 0)),
                         'We now join the Bengals and the Jaguars, with the Bengals leading 14 to 7 at halftime.')
        self.assertEqual(line('nfl', espn(17, 20, 4, '4th - 2:31', 151.0)),
                         'We now join the Bengals and the Jaguars, with the Jaguars leading 20 to 17, '
                         'with under 3 minutes left in the fourth quarter.')
        self.assertEqual(line('nfl', espn(3, 0, 1, 'End of 1st Quarter', 0)),
                         'We now join the Bengals and the Jaguars, with the Bengals leading 3 to 0 at the end of the first quarter.')
        self.assertEqual(line('nfl', espn(20, 20, 5, 'OT - 9:12', 552.0)),
                         'We now join the Bengals and the Jaguars, who are tied at 20 in overtime.')

    def test_hockey_and_soccer(self):
        self.assertTrue(line('nhl', espn(1, 2, 2, '2nd - 10:00', 600.0)).endswith('in the second period.'))
        self.assertTrue(line('nwsl', espn(1, 0, 2, "67'", 4020.0)).endswith('in the second half.'))

    def test_only_a_game_under_way(self):
        self.assertIsNone(line('mlb', mlb(0, 0, None, None, 'Preview')))
        self.assertIsNone(line('mlb', {**mlb(0, 0), 'period': None}), 'warming up: no inning yet')
        self.assertIsNone(line('nfl', espn(0, 0, 0, None, None, 'pre')))
        self.assertIsNone(line('nfl', espn(24, 10, state='post')))
        self.assertIsNone(line('nfl', {**espn(7, 7), 'away': {'nickname': 'Bengals', 'score': None}}))
        self.assertIsNone(line('mlb', None))

    def test_the_game_a_queue_entry_airs(self):
        game = {'league': 'nfl', 'game_pk': 401, 'game_date': '2026-10-08', 'title': 'Bengals at Jaguars'}
        self.assertEqual(game_of(SimpleNamespace(game=game, hold_end=None, target={})),
                         {'league': 'nfl', 'game_pk': 401, 'game_date': '2026-10-08'})
        held = SimpleNamespace(game=None, hold_end={'game': {'league': 'mlb', 'game_pk': 849822, 'game_date': '2026-10-07'}},
                               target={'source_id': 'youtube-tv', 'channel_id': 'TBS'})
        self.assertEqual(game_of(held)['game_pk'], 849822)
        self.assertEqual(game_of(None, {'source_id': 'mlb', 'channel_id': '849841', 'date': '2026-09-30'}),
                         {'league': 'mlb', 'game_pk': 849841, 'game_date': '2026-09-30'})
        self.assertIsNone(game_of(SimpleNamespace(game=None, hold_end=None, target={'source_id': 'youtube-tv', 'channel_id': 'NBC'})))


def wav(path, seconds):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(bytes(int(48000 * seconds) * 2))
    return path


class ClipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        video, music = self.root / 'join.mp4', self.root / 'join.wav'
        video.write_bytes(b'video')
        music.write_bytes(b'music')
        self.said, self.mixed, self.length = [], [], 4.0
        self.game = mlb(1, 3)

        def voice_line(model, text):
            self.said.append((model, text))
            return wav(self.root / f'line-{len(self.said)}.wav', self.length)

        def mix(voiced, out, *, music, video, length):
            self.mixed.append((voiced[0][1], Path(music).name, Path(video).name, length))
            Path(out).write_bytes(b'mixed')

        self.join = SportsJoin(self.root / 'continuity', voice=SimpleNamespace(line=voice_line),
                               sports=lambda league, pk, day: self.game, mix=mix, video=video, music=music)
        self.ref = {'league': 'mlb', 'game_pk': 849822, 'game_date': '2026-10-07'}

    def test_voiced_once_by_its_words_and_placed_after_the_slam(self):
        clip = self.join.clip(self.ref, timeout=5)
        self.assertEqual(clip['line'], 'We now join the Dodgers and the Braves, with the Braves leading 3 to 1 in the bottom of the fifth.')
        self.assertTrue(Path(clip['path']).name.startswith('join-') and Path(clip['path']).is_file())
        self.assertEqual(clip['seconds'], sports_join.LENGTH)
        self.assertEqual(self.said, [(sports_join.MODEL, clip['line'])])
        self.assertEqual(self.mixed, [(sports_join.START, 'join.wav', 'join.mp4', sports_join.LENGTH)])
        self.assertEqual(self.join.clip(self.ref, timeout=5)['path'], clip['path'])
        self.assertEqual(len(self.said), 1, 'the same score: the same clip')
        self.game = mlb(1, 4)
        self.assertNotEqual(self.join.clip(self.ref, timeout=5)['path'], clip['path'], 'a run scored: voiced again')

    def test_a_long_line_starts_early_and_one_too_long_goes_without(self):
        self.length = 7.9
        self.join.clip(self.ref, timeout=5)
        self.assertAlmostEqual(self.mixed[-1][0], sports_join.END - 7.9)
        self.length, self.game = 9.0, mlb(2, 3)
        self.assertIsNone(self.join.clip(self.ref, timeout=5))
        self.assertIn('too long', self.join.error)

    def test_no_bumper_before_the_game_or_without_its_files(self):
        self.game = mlb(0, 0, None, None, 'Preview')
        self.assertIsNone(self.join.clip(self.ref, timeout=5))
        self.assertIsNone(self.join.clip(None))
        self.game = mlb(1, 3)
        self.join.video.unlink()
        self.assertIsNone(self.join.clip(self.ref, timeout=5))
        self.assertEqual(self.said, [])

    def test_a_slow_voice_is_not_waited_on_but_finishes_for_next_time(self):
        gate = threading.Event()
        line_was = self.join.voice.line

        def slow(model, text):
            gate.wait(5)
            return line_was(model, text)
        self.join.voice = SimpleNamespace(line=slow)
        self.assertIsNone(self.join.clip(self.ref, timeout=.05))
        gate.set()
        self.assertIsNotNone(self.join.clip(self.ref, timeout=5))
        self.assertEqual(len(self.said), 1)

    def test_warm_voices_it_ahead(self):
        self.join.warm(self.ref)
        for _ in range(100):
            if self.mixed:
                break
            threading.Event().wait(.02)
        self.assertEqual(len(self.mixed), 1)
        self.assertIsNotNone(self.join.clip(self.ref, timeout=0))

    def test_a_refused_line_is_reported(self):
        def refuse(model, text):
            raise ConfigError('Deepgram refused the line (401)')
        self.join.voice = SimpleNamespace(line=refuse)
        self.assertIsNone(self.join.clip(self.ref, timeout=5))
        self.assertIn('401', self.join.error)


if __name__ == '__main__':
    unittest.main()
