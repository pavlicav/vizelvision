import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.caption_settings import CaptionSettings, DEFAULTS
from roku_stream.captions import CHUNK_BYTES, SHARED_WORDS_DELAY, LiveCaptions, caption_lines, timed_cues
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError
from roku_stream.master_worker import MasterWorker


def wait(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out')


class CaptionSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.master = MasterConfig(socket_path=Path(directory.name) / 'master.sock')
        self.settings = CaptionSettings(self.master.socket_path)

    def test_persistence_partial_updates_and_validation(self):
        self.assertEqual(self.settings.read(), DEFAULTS)
        self.settings.update({'enabled': True})
        self.assertTrue(CaptionSettings(self.master.socket_path).read()['enabled'])
        before = self.settings.read()
        for changes in ([], {'enabled': 1}, {'model': []}, {'model': '../model'}, {'language': []},
                        {'language': 'fr'}, {'unknown': True}):
            with self.subTest(changes=changes), self.assertRaises(ConfigError):
                self.settings.update(changes)
            self.assertEqual(self.settings.read(), before)
        self.settings.update({'model': 'small', 'language': 'auto'})
        self.settings.update({'enabled': False})
        self.assertEqual(self.settings.read(), {'enabled': False, 'model': 'small', 'language': 'auto'})

    def handler(self, authorized=True):
        master = Mock()
        master.request.return_value = {'state': 'live', 'captions': {'enabled': False, 'state': 'off'}}
        config = SimpleNamespace(master=self.master, server=SimpleNamespace(api_key='secret'))
        with patch('roku_stream.api.MasterClient', return_value=master):
            h = object.__new__(handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace()))
        h.path = '/v1/captions'
        h._authorize = Mock(return_value=authorized)
        h._body = Mock(return_value={'enabled': True})
        h._json = Mock()
        return h, master

    def test_api_authentication_validation_status_and_worker_outage(self):
        h, master = self.handler(False)
        h.do_POST()
        h.do_GET()
        h._body.assert_not_called()
        h._json.assert_not_called()
        h._authorize.return_value = True
        h.do_POST()
        self.assertEqual(h._json.call_args.args[0], 200)
        self.assertTrue(h._json.call_args.args[1]['settings']['enabled'])
        h._body.return_value = {'enabled': 'yes'}
        h.do_POST()
        self.assertEqual(h._json.call_args.args[0], 400)
        master.request.return_value = {'state': 'reconnecting', 'captions': {'text': 'old caption'}}
        h.do_GET()
        self.assertIsNone(h._json.call_args.args[1]['status'])
        self.assertIn('reconnect', h._json.call_args.args[1]['master_error'])
        master.request.side_effect = OSError('offline')
        h.do_GET()
        self.assertEqual(h._json.call_args.args[0], 200)
        self.assertIn('offline', h._json.call_args.args[1]['master_error'])
        h._body.return_value = {'enabled': False}
        h.do_POST()
        self.assertFalse(h._json.call_args.args[1]['settings']['enabled'])

    def test_worker_applies_saved_settings_and_bad_file_never_stops_publication(self):
        worker = MasterWorker(SimpleNamespace(master=self.master, tv_thing=TvThingConfig()), tv=Mock(),
                              status_reader=lambda: {'ready': True, 'source': {'id': 'publisher'}})
        worker.output = Mock()
        worker.output.status.return_value = {}
        worker.output.caption_status.return_value = {'enabled': True, 'state': 'listening', 'error': None}
        worker.output_started = time.monotonic()
        self.settings.update({'enabled': True})
        worker._tick()
        worker.output.configure_captions.assert_called_with(self.settings.read())
        self.assertEqual(worker.status()['captions']['state'], 'listening')
        self.settings.path.write_text('broken')
        worker.production_checked = 0
        worker._tick()
        self.assertIn('Cannot load live captions', worker.status()['captions']['error'])
        worker.output.take.assert_not_called()
        worker.output.close.assert_not_called()


def transcript(text='hello', start=0.5, end=1.5):
    return [{'start': start, 'end': end, 'text': text}]


class CaptionRuntimeTests(unittest.TestCase):
    def runtime(self, transcribe):
        self.now = 100.
        helper = Mock()
        helper.transcribe.side_effect = transcribe
        engine = LiveCaptions(factory=Mock(return_value=helper), clock=lambda: self.now)
        self.addCleanup(engine.close)
        return engine, helper

    def test_cues_follow_media_time_not_completion_or_wall_time(self):
        engine, helper = self.runtime(lambda pcm: transcript('<b>speech & words</b>'))
        engine.feed(bytes(CHUNK_BYTES), 10)
        self.assertIsNone(engine.thread)
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 10)
        wait(lambda: engine.status()['queued_cues'])
        self.assertEqual(engine.status()['text'], '')
        self.now += 100  # Completion / wall clock does not move subtitle timing.
        self.assertEqual(engine.text_at(10.4), '')
        self.assertEqual(engine.text_at(10.5), '<b>speech & words</b>')
        self.assertEqual(engine.text_at(11.7), '')
        engine.configure(DEFAULTS)
        wait(lambda: helper.close.called)

    def test_cut_keeps_in_flight_cues_for_the_old_buffered_tail(self):
        entered, release = threading.Event(), threading.Event()
        def recognize(pcm):
            entered.set()
            release.wait(2)
            return transcript('old source')
        engine, helper = self.runtime(recognize)
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 10, 'old')
        self.assertTrue(entered.wait(1))
        engine.feed(bytes(CHUNK_BYTES), 14, 'new')
        release.set()
        wait(lambda: engine.status()['queued_cues'] == 2)
        self.assertEqual(engine.text_at(10.7), 'old source')
        self.assertEqual(engine.text_at(14.2), '')
        self.assertEqual(engine.text_at(14.7), 'old source')  # Same fake speech, new timestamp.

    def test_cut_flushes_partial_audio_without_joining_sources(self):
        engine, helper = self.runtime(lambda pcm: transcript(end=.8))
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES // 4), 0, 'old')
        engine.feed(bytes(CHUNK_BYTES // 4), 1, 'new')
        wait(lambda: helper.transcribe.called)
        self.assertEqual(len(helper.transcribe.call_args.args[0]), CHUNK_BYTES // 4)
        self.assertEqual(engine.buffer_pts, 1)
        self.assertEqual(len(engine.buffer), CHUNK_BYTES // 4)

    def test_the_ad_detectors_words_stand_in_for_a_second_whisper(self):
        engine, helper = self.runtime(lambda pcm: transcript('own whisper'))
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES // 4), 0, 'game')                  # our own, until the detector's come
        engine.feed(bytes(CHUNK_BYTES), 1, 'game', words=[(1.2, 1.5, 'Freddie'), (1.55, 1.9, 'Freeman.'),
                                                         (2.6, 2.9, 'Strike')])
        wait(lambda: helper.transcribe.call_count == 1)
        self.assertEqual(len(helper.transcribe.call_args.args[0]), CHUNK_BYTES // 4,
                         'what was collected before still gets transcribed; nothing after it')
        self.assertEqual(engine.text_at(1.3), 'Freddie Freeman.')
        self.assertEqual(engine.text_at(2.7), 'Strike')
        self.assertEqual(engine.status()['words_from'], 'detector')
        self.assertEqual(engine.buffer, bytearray())
        engine.feed(bytes(CHUNK_BYTES), 5, 'game', words=[(2.0, 2.3, 'late')])   # its moment has aired
        self.assertEqual(engine.status()['late_cues'], 1)
        engine.feed(bytes(CHUNK_BYTES), 9, 'game')                       # the detector went away
        wait(lambda: helper.transcribe.call_count == 2)
        self.assertEqual(engine.status()['words_from'], 'whisper')

    def test_master_uses_the_detectors_words_only_with_time_for_them(self):
        from roku_stream.master_media import MasterMedia
        media = object.__new__(MasterMedia)
        media.gst = SimpleNamespace(SECOND=1_000_000_000)
        media.captions = SimpleNamespace(settings={**DEFAULTS, 'enabled': False})
        link = Mock()
        link.take_words.return_value = [(12_000_000_000, 12_500_000_000, 'hello')]
        tap = SimpleNamespace(link=link, key='k')
        media.programme = SimpleNamespace(delay_ns=int(SHARED_WORDS_DELAY * 1e9) - 1)
        self.assertIsNone(media._detector_words((tap, 2_000_000_000, 7)), 'a 6 s delay: words would come late')
        media.programme.delay_ns = 9_000_000_000
        self.assertIsNone(media._detector_words((tap, 2_000_000_000, 7)), 'captions are off')
        link.take_words.assert_not_called()
        media.captions.settings['enabled'] = True
        self.assertEqual(media._detector_words((tap, 2_000_000_000, 7)), [(10.0, 10.5, 'hello')])
        self.assertIsNone(media._detector_words((None, 0, 3)), 'an input the detector does not analyse')
        self.assertIsNone(media._detector_words(None))
        link.take_words.return_value = None
        self.assertIsNone(media._detector_words((tap, 0, 7)))

    def test_late_result_is_not_replayed_over_later_speech(self):
        entered, release = threading.Event(), threading.Event()
        def recognize(pcm):
            entered.set()
            release.wait(2)
            return transcript()
        engine, _ = self.runtime(recognize)
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 0)
        self.assertTrue(entered.wait(1))
        engine.text_at(3)
        release.set()
        wait(lambda: engine.status()['late_cues'] == 1)
        self.assertEqual(engine.text_at(3.1), '')
        self.assertEqual(engine.status()['queued_cues'], 0)

    def test_muted_ads_do_not_show_their_transcript(self):
        engine, _ = self.runtime(lambda pcm: transcript())
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 0)
        wait(lambda: engine.status()['queued_cues'])
        self.assertEqual(engine.text_at(.8, audible=False), '')
        self.assertEqual(engine.text_at(1, audible=True), 'hello')

    def test_disable_during_inference_cancels_and_clears_cues(self):
        entered, release = threading.Event(), threading.Event()
        def recognize(pcm):
            entered.set()
            release.wait(2)
            return transcript()
        engine, helper = self.runtime(recognize)
        helper.cancel.side_effect = release.set
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 0)
        self.assertTrue(entered.wait(1))
        engine.configure(DEFAULTS)
        wait(lambda: helper.close.called)
        self.assertEqual(engine.text_at(1), '')
        self.assertEqual(engine.status()['state'], 'off')

    def test_missing_dependency_reports_error_and_can_be_disabled(self):
        def unavailable(pcm):
            raise RuntimeError('Whisper is unavailable')
        engine, _ = self.runtime(unavailable)
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 0)
        wait(lambda: engine.status()['state'] == 'error')
        engine.configure(DEFAULTS)
        self.assertIsNone(engine.status()['error'])

    def test_slow_recognizer_has_bounded_pending_audio(self):
        entered, release = threading.Event(), threading.Event()
        def recognize(pcm):
            entered.set()
            release.wait(2)
            return transcript()
        engine, _ = self.runtime(recognize)
        engine.configure({**DEFAULTS, 'enabled': True})
        engine.feed(bytes(CHUNK_BYTES), 0)
        self.assertTrue(entered.wait(1))
        for i in range(1, 11):
            engine.feed(bytes(CHUNK_BYTES), i * 4)
        self.assertEqual(len(engine.pending), 2)
        self.assertEqual(engine.status()['dropped_chunks'], 8)
        self.now += 13
        release.set()
        wait(lambda: engine.status()['dropped_chunks'] >= 9)
        self.assertEqual(engine.status()['queued_cues'], 0)

    def test_words_split_into_phrases_and_invalid_timestamps_are_rejected(self):
        words = [{'start': 0.2, 'end': .7, 'text': 'Hello'}, {'start': .7, 'end': 1.2, 'text': 'world.'},
                 {'start': 2, 'end': 2.5, 'text': 'Next'}, {'start': 2.5, 'end': 3, 'text': 'sentence.'}]
        cues = timed_cues([{'words': words}], 10, 4)
        self.assertEqual(cues, [(10.2, 11.35, 'Hello world.'), (12, 13.15, 'Next sentence.')])
        self.assertEqual(timed_cues(transcript(start=float('nan')), 0, 4), [])
        self.assertEqual(timed_cues(transcript(end=10), 0, 4), [])
        self.assertEqual(timed_cues(transcript(start=-1), 0, 4), [])

    def test_caption_is_bounded_and_control_characters_removed(self):
        lines = caption_lines('word ' * 100 + '\x00finish').splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(len(line) <= 64 for line in lines))
        self.assertTrue(lines[-1].endswith('finish'))


if __name__ == '__main__':
    unittest.main()
