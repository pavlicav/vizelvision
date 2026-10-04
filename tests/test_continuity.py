from datetime import datetime, timezone
import json
import math
import time
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch

from roku_stream import continuity
from roku_stream.continuity import (Continuity, DEFAULT_LINES, LAST_WORD, SLOTS, SPORTS_LINE, defaults, is_game, mix,
                                    place, script, validate)
from roku_stream.errors import ConfigError


def tone(path, seconds, freq=220.0, level=0.3, rate=48000):
    """A stand-in for a voiced line: a steady tone of this length."""
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b''.join(struct.pack('<h', int(level * 32767 * math.sin(2 * math.pi * freq * i / rate)))
                                 for i in range(int(seconds * rate))))
    return path


class FakeVoice:
    def __init__(self, folder, lengths=None):
        self.folder, self.lengths, self.said = Path(folder), lengths or {}, []

    def available(self):
        return True

    def catalogue(self):
        return [{'id': 'aura-2-orpheus-en', 'language': 'en', 'accent': 'American', 'tags': []},
                {'id': 'aura-2-agathe-fr', 'language': 'fr', 'accent': 'French', 'tags': []}]

    def line(self, model, text):
        self.said.append((model, text))
        path = self.folder / f'{abs(hash((model, text)))}.wav'
        if not path.exists():
            tone(path, self.lengths.get(text, 1.5))
        return path


class FakeMaster:
    def __init__(self):
        self.files, self.state = [], {'ident': {'file': 'vizelvision-id.mp4', 'on_air': False}}

    def request(self, action='status', body=None):
        if action == 'status':
            return json.loads(json.dumps(self.state))
        assert action == 'ident_file'
        self.files.append(body['path'])
        self.state['ident']['file'] = Path(body['path']).name if body['path'] else 'vizelvision-id.mp4'
        return {'accepted': True}


class ScriptTests(unittest.TestCase):
    def test_defaults_are_cairo_radios_personalities_on_its_shifts(self):
        settings = validate(defaults())
        self.assertEqual([(a['name'], a['model']) for a in settings['announcers']],
                         [('DJ Low Tide', 'aura-2-orpheus-en'), ('The Daytime Announcer', 'aura-2-zeus-en'),
                          ('Amélie', 'aura-2-agathe-fr')])
        self.assertEqual(settings['announcers'][2]['lines'][1], 'Vous regardez Vizel Vision.')
        self.assertEqual((settings['duty'], settings['roster'][9], settings['roster'][11], settings['roster'][16]),
                         ('roster', 'daytime-announcer', 'amelie', 'low-tide'))
        self.assertFalse(settings['enabled'])
        removed = json.loads(json.dumps(defaults()))
        removed['announcers'].pop(2)  # Amélie's hours fall back to the announcer on duty.
        self.assertIsNone(validate(removed)['roster'][11])

    def test_settings_are_checked(self):
        base = defaults()
        for change, message in ((lambda s: s['announcers'][0].update(model='gpt-voice'), 'Aura'),
                                (lambda s: s['announcers'][0].update(lines=['That was {show}.']), 'show'),
                                (lambda s: s['announcers'].append(dict(s['announcers'][0])), 'different'),
                                (lambda s: s.update(on_duty='nobody'), 'on duty'),
                                (lambda s: s['announcers'][0].update(lines=['x'] * 5), 'lines')):
            value = json.loads(json.dumps(base))
            change(value)
            with self.assertRaisesRegex(ConfigError, message):
                validate(value)
        named = json.loads(json.dumps(base))
        named['announcers'].append({'name': 'Night Owl', 'model': 'aura-2-luna-en'})
        self.assertEqual(validate(named)['announcers'][-1]['id'], 'night-owl')
        self.assertEqual(validate(named)['announcers'][-1]['lines'], list(DEFAULT_LINES))

    def test_lines_about_nothing_known_are_left_out(self):
        self.assertEqual(script(DEFAULT_LINES, 'the Phillies and the Braves', 'the White Sox and the Astros'),
                         ['That was the Phillies and the Braves.', "You're watching Vizel Vision.",
                          'Coming up: the White Sox and the Astros.', 'Stay tuned.'])
        self.assertEqual(script(DEFAULT_LINES, 'News at Noon', None),
                         ['That was News at Noon.', "You're watching Vizel Vision.", 'Stay tuned.'])

    def test_lines_sit_on_the_id_voice_slots_and_end_before_the_end_card(self):
        self.assertEqual(place([2, 2, 3, 1]), list(SLOTS))
        self.assertEqual(place([4.5, 4.5, 4.5, 2]), [7.8, 12.9, 17.7, 22.5])  # A long line pushes the next.
        tight = place([5, 5, 5, 4])  # Too long for the slots: closer together, from earlier.
        self.assertLess(tight[0], SLOTS[0])
        self.assertLessEqual(tight[-1] + 4, LAST_WORD)
        self.assertIsNone(place([8, 8, 8]))


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'id.mp4').write_bytes(b'id')
        (root / 'music.wav').write_bytes(b'music')
        self.voice, self.master = FakeVoice(root), FakeMaster()
        self.segments = [{'kind': 'game', 'title': 'Philadelphia Phillies at Atlanta Braves'},
                         {'kind': 'game', 'title': 'Chicago White Sox at Houston Astros'}]
        spoken = {'Philadelphia Phillies at Atlanta Braves': 'the Phillies and the Braves',
                  'Chicago White Sox at Houston Astros': 'the White Sox and the Astros'}
        self.mixes = []

        def fake_mix(voiced, out, **kwargs):
            self.mixes.append((voiced, kwargs))
            Path(out).write_bytes(b'announcement')
            return Path(out)
        patcher = patch.object(continuity, 'mix', fake_mix)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.joins = []

        def fake_join(first, second, out):
            self.joins.append((Path(first), Path(second)))
            Path(out).write_bytes(Path(first).read_bytes() + b' + ' + Path(second).read_bytes())
            return Path(out)
        patcher = patch.object(continuity, 'join', fake_join)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = Continuity(root / 'continuity.json', root / 'continuity', voice=self.voice,
                                  project=lambda: self.segments,
                                  spoken=lambda s, lang='en': spoken.get(s['title'], s['title']),
                                  master=self.master, video=root / 'id.mp4', music=root / 'music.wav',
                                  sports=root / 'sports.mp4', start_worker=False)

    def enable(self, duty='fixed'):
        settings = self.service.settings()
        settings.update(enabled=True, duty=duty)
        self.service.save(settings)


class ServiceTests(ServiceFixture):
    def test_off_means_the_plain_id(self):
        self.service.step()
        self.assertEqual((self.master.files, self.voice.said), ([], []))

    def test_the_next_break_is_announced_and_cued_once(self):
        self.enable()
        self.service.step()
        self.assertEqual([text for _, text in self.voice.said],
                         ['That was the Phillies and the Braves.', "You're watching Vizel Vision.",
                          'Coming up: the White Sox and the Astros.', 'Stay tuned.'])
        self.assertTrue(all(model == 'aura-2-orpheus-en' for model, _ in self.voice.said))
        (voiced, kwargs), = self.mixes
        self.assertEqual([start for _, start in voiced], list(SLOTS))
        self.assertEqual(Path(kwargs['video']).name, 'id.mp4')
        cued = self.service.status()['next']
        self.assertEqual((cued['name'], cued['just_played'], cued['up_next']),
                         ('DJ Low Tide', 'the Phillies and the Braves', 'the White Sox and the Astros'))
        self.assertEqual(self.master.files, [str(self.service.work_dir / cued['file'])])
        self.service.step()  # Nothing changed: not sent again.
        self.assertEqual(len(self.master.files), 1)
        # It airs; the next break (after the White Sox) is announced in turn.
        self.master.state['last_station_id'] = {'file': cued['file'], 'at': time.time()}
        self.segments = [{'kind': 'game', 'title': 'Chicago White Sox at Houston Astros'},
                         {'kind': 'off_air', 'title': 'OFF AIR', 'target': {'source_id': 'off-air'}}]
        self.service.step()
        status = self.service.status()
        self.assertEqual(status['recent'][0]['file'], cued['file'])
        self.assertEqual(status['next']['lines'], ['That was the White Sox and the Astros.',
                                                   "You're watching Vizel Vision.", 'Stay tuned.'])
        self.assertEqual(len(self.master.files), 2)

    def test_the_roster_puts_the_host_of_the_breaks_hour_on_duty_in_their_language(self):
        import time as clock
        self.enable('roster')
        eleven = clock.mktime(clock.strptime('2026-09-30 11:40', '%Y-%m-%d %H:%M'))  # Amélie's shift.
        self.segments[0]['end'] = datetime.fromtimestamp(eleven, timezone.utc).isoformat()
        self.service.spoken = lambda segment, lang='en': {'fr': 'les Phillies et les Braves'}.get(lang, segment['title'])
        self.service.step()
        cued = self.service.status()['next']
        self.assertEqual(cued['name'], 'Amélie')
        self.assertEqual(cued['lines'][0], "C'était les Phillies et les Braves.")
        self.assertTrue(all(model == 'aura-2-agathe-fr' for model, _ in self.voice.said))

    def test_preview_uses_a_sample_in_the_announcers_language(self):
        self.segments = []
        result = self.service.preview('amelie')
        self.assertEqual(result['lines'][0], "C'était les Phillies et les Braves.")

    def test_nothing_is_cued_when_the_id_will_not_play(self):
        self.enable()
        self.segments = [{'kind': 'off_air', 'title': 'OFF AIR', 'target': {'source_id': 'off-air'}}]
        self.service.step()
        self.assertEqual(self.master.files, [])

    def test_turning_it_off_returns_the_plain_id(self):
        self.enable()
        self.service.step()
        settings = self.service.settings()
        settings['enabled'] = False
        self.service.save(settings)
        self.service.step()
        self.assertEqual(self.master.files[-1], None)

    def test_a_worker_that_lost_the_announcement_gets_it_again(self):
        self.enable()
        self.service.step()
        self.master.state['ident']['file'] = 'vizelvision-id.mp4'  # Restarted.
        self.service.step()
        self.service.step()
        self.assertEqual(len(self.master.files), 2)

    def test_a_voice_failure_leaves_the_plain_id_and_says_why(self):
        self.enable()
        self.voice.line = lambda model, text: (_ for _ in ()).throw(ConfigError('No Deepgram key'))
        self.service.step()
        self.assertEqual((self.master.files, self.service.status()['error']), ([], 'No Deepgram key'))

    def test_preview_and_audio_names(self):
        result = self.service.preview('low-tide', 'News at Noon', None)
        self.assertEqual(result['lines'], ['That was News at Noon.', "You're watching Vizel Vision.", 'Stay tuned.'])
        self.assertTrue(result['audio'].endswith('.wav'))
        self.assertTrue(self.service.audio(result['audio']).is_file())
        for bad in ('../continuity.json', 'x.mp4', None):
            with self.assertRaises(ConfigError):
                self.service.audio(bad)


JEOPARDY = {'kind': 'block', 'title': 'Jeopardy', 'end': '2026-10-02T00:00:00+00:00',
            'target': {'source_id': 'tv-thing-digital', 'channel_id': 'wrc'}}
GAME = {'kind': 'game', 'title': 'Philadelphia Phillies at Atlanta Braves', 'game': {'league': 'mlb', 'game_pk': 1},
        'target': {'source_id': 'youtube-tv', 'channel_id': 'mlb'}}
OFF_AIR = {'kind': 'off_air', 'title': 'OFF AIR', 'target': {'source_id': 'off-air'}}


class SportsIdTests(ServiceFixture):
    """The break before a game says what is next, then plays the VizelVision Sports ID."""

    def setUp(self):
        super().setUp()
        self.sports = self.service.sports
        self.sports.write_bytes(b'sports id')
        self.segments = [JEOPARDY, GAME]

    def cued(self):
        return self.service.status()['next']

    def test_a_game_is_what_has_kind_game_or_carries_one(self):
        self.assertTrue(is_game(GAME))
        self.assertTrue(is_game({'kind': 'manual', 'title': 'Phillies', 'game': {'game_pk': 1}}))
        backup = {'kind': 'backup', 'title': 'OFF AIR', 'game': None, 'target': {'source_id': 'off-air'}}
        for segment in (JEOPARDY, OFF_AIR, backup, None):
            self.assertFalse(is_game(segment))

    def test_the_break_before_a_game_cues_the_plain_id_then_the_sports_id(self):
        self.service.step()  # Announcements are off: the plain ID, then the Sports ID.
        (path,) = self.master.files
        self.assertTrue(Path(path).name.startswith('sports-'))
        self.assertEqual(Path(path).parent, self.service.work_dir)
        self.assertEqual(Path(path).read_bytes(), b'id + sports id')
        cued = self.cued()
        self.assertEqual((cued['name'], cued['lines'], cued['just_played'], cued['up_next']),
                         ('VizelVision Sports', [SPORTS_LINE], 'Jeopardy', 'the Phillies and the Braves'))
        self.assertEqual(cued['break_at'], datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp())
        self.assertEqual(self.voice.said, [])
        self.assertEqual(self.service.audio(cued['file']), Path(path))  # Listen works for it too.
        self.service.step()
        self.assertEqual((len(self.master.files), len(self.joins)), (1, 1))

    def test_the_announcement_says_what_is_next_before_the_sports_id(self):
        self.enable()
        self.service.step()
        path = Path(self.master.files[-1])
        self.assertTrue(path.name.startswith('sports-'))
        self.assertEqual(path.read_bytes(), b'announcement + sports id')
        said = [text for _, text in self.voice.said]
        self.assertEqual(said, ['That was Jeopardy.', "You're watching Vizel Vision.",
                                'Coming up: the Phillies and the Braves.', 'Stay tuned.'])
        cued = self.cued()
        self.assertEqual((cued['name'], cued['lines']), ('DJ Low Tide, then VizelVision Sports', said + [SPORTS_LINE]))
        ((first, second),) = self.joins
        self.assertEqual((first.parent, second), (self.service.work_dir, self.sports))
        self.service.step()  # Nothing new: the same announcement, the same joined file.
        self.assertEqual((len(self.master.files), len(self.joins)), (1, 1))

    def test_an_announcement_that_cannot_be_voiced_leaves_the_plain_id_first(self):
        self.enable()
        self.voice.line = lambda model, text: (_ for _ in ()).throw(ConfigError('No Deepgram key'))
        self.service.step()
        self.assertEqual(Path(self.master.files[-1]).read_bytes(), b'id + sports id')
        self.assertIn('No Deepgram key', self.service.status()['error'])

    def test_it_opens_a_game_from_the_test_card(self):
        self.segments = [OFF_AIR, GAME]
        self.service.step()
        self.assertTrue(Path(self.master.files[-1]).name.startswith('sports-'))
        self.assertEqual(self.cued()['just_played'], 'OFF AIR')
        self.enable()  # Announced, nothing just played: no "That was".
        self.service.step()
        self.assertEqual(self.cued()['lines'], ["You're watching Vizel Vision.", 'Coming up: the Phillies and the Braves.',
                                                'Stay tuned.', SPORTS_LINE])

    def test_one_game_after_another(self):
        self.segments = [GAME, {**GAME, 'title': 'Chicago White Sox at Houston Astros', 'game': {'game_pk': 2}}]
        self.service.step()
        self.assertEqual(self.cued()['up_next'], 'the White Sox and the Astros')
        self.segments = [GAME, {**GAME, 'title': 'Phillies again'}]  # The same game going on: no break.
        self.master.files.clear()
        self.service.step()
        self.assertNotIn('sports-', ''.join(Path(f).name for f in self.master.files if f))

    def test_no_sports_id_before_anything_else_or_without_the_file(self):
        for segments in ([JEOPARDY, OFF_AIR], [GAME, {**OFF_AIR, 'kind': 'backup'}], [JEOPARDY], []):
            self.segments = segments
            self.service.step()
        self.assertEqual(self.master.files, [])
        self.sports.unlink()
        self.segments = [JEOPARDY, GAME]
        self.service.step()
        self.assertEqual(self.master.files, [])

    def test_after_it_airs_the_next_break_is_back_to_normal_and_the_next_game_gets_it_again(self):
        self.service.step()
        name = self.cued()['file']
        self.master.state['last_station_id'] = {'file': name, 'at': time.time()}
        self.master.state['ident']['file'] = 'vizelvision-id.mp4'  # The worker went back to the plain ID.
        self.segments = [GAME, {**OFF_AIR, 'kind': 'backup'}]
        self.service.step()
        status = self.service.status()
        self.assertEqual((status['recent'][0]['file'], status['next']), (name, None))
        self.assertEqual(len(self.master.files), 1, 'nothing more to send: the plain ID is cued')
        # Tomorrow: the same file is cued again, and an old airing of it does not count.
        self.master.state['last_station_id']['at'] = time.time() - 3600
        self.segments = [JEOPARDY, GAME]
        self.service.step()
        self.service.step()
        self.assertEqual((self.master.files[-1], self.cued()['aired_at']), (str(self.service.work_dir / name), None))

    def test_a_rebuilt_sports_id_is_cued_under_a_new_name(self):
        self.service.step()
        first = self.master.files[-1]
        self.sports.write_bytes(b'sports id, rebuilt')
        self.service.step()
        self.assertNotEqual(self.master.files[-1], first)
        self.assertEqual(Path(self.master.files[-1]).read_bytes(), b'id + sports id, rebuilt')

    def test_without_a_projection_the_cue_stays(self):
        self.service.step()
        self.service.project = lambda: (_ for _ in ()).throw(RuntimeError('queue unavailable'))
        self.service.step()
        self.assertEqual(len(self.master.files), 1)


@unittest.skipUnless(shutil.which('ffmpeg'), 'needs ffmpeg')
class MixTests(unittest.TestCase):
    def test_lines_land_on_their_slots_over_ducked_music_at_the_id_loudness(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            music = folder / 'music.wav'
            # A steady bed stands in for the ID's music.
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anoisesrc=d=30:c=pink:a=0.1',
                            '-ac', '2', '-ar', '48000', str(music)], check=True)
            # Speech-like levels: a line sits a few dB over the bed, as a voice would.
            lines = [(tone(folder / 'a.wav', 1.5, 300, .08), 7.8), (tone(folder / 'b.wav', 1.5, 300, .08), 12.9)]
            out = mix(lines, folder / 'out.wav', music=music)
            report = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(out), '-af',
                                     'loudnorm=print_format=json', '-f', 'null', '-'], capture_output=True, text=True).stderr
            loudness = float(json.loads(report[report.rindex('{'):report.rindex('}') + 1])['input_i'])
            self.assertAlmostEqual(loudness, -20.0, delta=1.0)
            with wave.open(str(out)) as audio:
                rate, frames = audio.getframerate(), audio.readframes(audio.getnframes())
            samples = struct.unpack(f'<{len(frames) // 2}h', frames)

            def level(a, b):
                part = samples[int(a * rate) * 2:int(b * rate) * 2]
                return 20 * math.log10(math.sqrt(sum(x * x for x in part) / len(part)) / 32768 + 1e-12)
            self.assertAlmostEqual(len(samples) / 2 / rate, 30, delta=.1)
            self.assertGreater(level(8.0, 9.0), level(4.0, 5.0) + 3, 'the line sits above the bed')

    def test_lines_are_levelled_and_the_music_ducks_the_same_under_each(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            music = folder / 'music.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anoisesrc=d=30:c=pink:a=0.3',
                            '-ac', '2', '-ar', '48000', str(music)], check=True)
            # Deepgram's lines come back at different levels: these are 20 dB apart.
            lines = [(tone(folder / 'quiet.wav', 1.5, 300, .02), 7.8), (tone(folder / 'loud.wav', 1.5, 300, .2), 12.9)]
            out = mix(lines, folder / 'out.wav', music=music)

            def level(a, b, band='lowpass=f=600'):
                """RMS in dB of the output from a to b seconds: the tone's band, or the music's above it."""
                report = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-ss', str(a), '-t', str(b - a),
                                         '-i', str(out), '-af', f'{band},volumedetect', '-f', 'null', '-'],
                                        capture_output=True, text=True).stderr
                return float(report.split('mean_volume:')[1].split('dB')[0])
            self.assertAlmostEqual(level(8.2, 9.0), level(13.3, 14.1), delta=1.0, msg='each line at the same level')
            music_alone, under = level(4.0, 5.0, 'highpass=f=2000'), level(8.2, 9.0, 'highpass=f=2000')
            self.assertAlmostEqual(music_alone - under, continuity.DUCK_DB, delta=1.0)
            self.assertAlmostEqual(music_alone - level(13.3, 14.1, 'highpass=f=2000'), continuity.DUCK_DB, delta=1.0)
            self.assertAlmostEqual(music_alone, level(10.5, 12.0, 'highpass=f=2000'), delta=1.0,
                                   msg='the music comes back up between lines')

    @unittest.skipUnless(continuity.IDENT_PATH.is_file() and continuity.SPORTS_IDENT_PATH.is_file(),
                         'needs the built IDs')
    def test_the_sports_break_is_the_id_then_the_sports_id_in_one_file(self):
        with tempfile.TemporaryDirectory() as folder:
            out = continuity.join(continuity.IDENT_PATH, continuity.SPORTS_IDENT_PATH, Path(folder) / 'sports-0.mp4')
            probe = json.loads(subprocess.run(
                ['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
                 'stream=codec_type,nb_read_frames,duration:format=duration', '-of', 'json', str(out)],
                capture_output=True, text=True, check=True).stdout)
            streams = {s['codec_type']: s for s in probe['streams']}
            self.assertEqual(int(streams['video']['nb_read_frames']), 3600)  # Both IDs' 1800 frames.
            self.assertAlmostEqual(float(probe['format']['duration']), 60, delta=.1)
            self.assertAlmostEqual(float(streams['audio']['duration']), 60, delta=.1)
            # The Sports ID's open is in the second half: its sound starts again after the seam.
            report = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-ss', '31', '-t', '4', '-i', str(out),
                                     '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True).stderr
            self.assertGreater(float(report.split('mean_volume:')[1].split('dB')[0]), -45)


if __name__ == '__main__':
    unittest.main()
