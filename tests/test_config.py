import json
import tempfile
import unittest
from pathlib import Path

from roku_stream.config import load_config
from roku_stream.errors import ChannelNotFoundError, ConfigError


class ConfigTests(unittest.TestCase):
    def test_roku_preparation_freshness_is_bounded_and_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            root = {'channels': [{'name': 'NBC'}], 'master': {}}
            path.write_text(json.dumps(root))
            self.assertEqual(load_config(path).master.roku_prepare_max_age_seconds, 900)
            for age in (60, 3600):
                root['master']['roku_prepare_max_age_seconds'] = age
                path.write_text(json.dumps(root))
                self.assertEqual(load_config(path).master.roku_prepare_max_age_seconds, age)
            for age in (0, -1, 3601, True, '900'):
                root['master']['roku_prepare_max_age_seconds'] = age
                path.write_text(json.dumps(root))
                with self.subTest(age=age), self.assertRaises(ConfigError):
                    load_config(path)

    def test_eas_crawl_defaults_to_the_local_decoder_for_dc(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            root = {'channels': [{'name': 'NBC'}], 'master': {}}
            path.write_text(json.dumps(root))
            master = load_config(path).master
            self.assertEqual((master.eas_url, master.eas_areas), ('http://127.0.0.1:8090/eas', ('011001',)))
            root['master'] = {'eas_url': None, 'eas_areas': ['011001', '024031']}
            path.write_text(json.dumps(root))
            master = load_config(path).master
            self.assertEqual((master.eas_url, master.eas_areas), (None, ('011001', '024031')))
            for key, value in (('eas_url', 'ftp://x'), ('eas_url', 'http://user:pw@host/eas'), ('eas_areas', []),
                               ('eas_areas', ['11001']), ('eas_areas', '011001'), ('eas_areas', ['01100A'])):
                root['master'] = {key: value}
                path.write_text(json.dumps(root))
                with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                    load_config(path)

    def test_off_air_radio_url_defaults_to_cairo_and_requires_http(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            root = {'channels': [{'name': 'NBC'}], 'master': {}}
            path.write_text(json.dumps(root))
            self.assertEqual(load_config(path).master.off_air_radio_url, 'http://127.0.0.1:1615/cairo.mp3')
            root['master']['off_air_radio_url'] = 'https://radio.example.test/live.aac'
            path.write_text(json.dumps(root))
            self.assertEqual(load_config(path).master.off_air_radio_url, 'https://radio.example.test/live.aac')
            self.assertEqual(load_config(path).master.off_air_radio_info_url, 'http://127.0.0.1:1894')
            self.assertEqual(load_config(path).master.off_air_radio_gain_db, -9.0)
            for gain in (True, '-6', -41, 7):
                root['master']['off_air_radio_gain_db'] = gain
                path.write_text(json.dumps(root))
                with self.assertRaises(ConfigError):
                    load_config(path)
            root['master']['off_air_radio_gain_db'] = -6
            path.write_text(json.dumps(root))
            self.assertEqual(load_config(path).master.off_air_radio_gain_db, -6.0)
            del root['master']['off_air_radio_gain_db']
            root['master']['off_air_radio_info_url'] = None
            path.write_text(json.dumps(root))
            self.assertIsNone(load_config(path).master.off_air_radio_info_url)
            root['master']['off_air_radio_info_url'] = 'ftp://x'
            path.write_text(json.dumps(root))
            with self.assertRaises(ConfigError):
                load_config(path)
            del root['master']['off_air_radio_info_url']
            for url in ('file:///etc/passwd', 'http://', '', None, 5):
                root['master']['off_air_radio_url'] = url
                path.write_text(json.dumps(root))
                with self.subTest(url=url), self.assertRaises(ConfigError):
                    load_config(path)

    def test_roku_contribution_is_optional_and_confined_to_local_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            root = {'channels': [{'name': 'ABC'}], 'feedback': {
                'backend': 'direct', 'device': '/dev/video1', 'input_format': 'mpegts'}}
            path.write_text(json.dumps(root))
            self.assertIsNone(load_config(path).feedback.contribution_url)
            root['feedback']['contribution_url'] = 'rtsp://127.0.0.1:18554/roku'
            path.write_text(json.dumps(root))
            self.assertEqual(load_config(path).feedback.contribution_url, root['feedback']['contribution_url'])
            for url in ('rtsp://remote:18554/roku', 'rtsp://127.0.0.1:99999/roku',
                        'rtsp://127.0.0.1:0/roku', 'rtsp://127.0.0.1:18554/../master',
                        'rtsp://127.0.0.1:18554/roku?token=secret', 123):
                root['feedback']['contribution_url'] = url
                path.write_text(json.dumps(root))
                with self.subTest(url=url), self.assertRaises(ConfigError):
                    load_config(path)
            root['feedback'].update(contribution_url='rtsp://127.0.0.1:18554/roku', input_format='mjpeg')
            path.write_text(json.dumps(root))
            with self.assertRaises(ConfigError):
                load_config(path)

    def write_config(self, root: Path, channels: list[dict]) -> Path:
        path = root / "config.json"
        path.write_text(json.dumps({"channels": channels}), encoding="utf-8")
        return path

    def test_resolves_case_punctuation_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(
                self.write_config(
                    Path(directory),
                    [{"name": "ESPN2", "aliases": ["ESPN 2"], "guide_index": 7}],
                )
            )
            index, channel = config.resolve_channel("espn-2")
            self.assertEqual(index, 0)
            self.assertEqual(channel.name, "ESPN2")
            self.assertEqual(channel.guide_index, 7)

    def test_channel_can_share_a_network_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(
                Path(directory),
                [
                    {
                        "name": "ESPN2",
                        "guide_index": 7,
                        "network_page": "ESPN",
                    }
                ],
            )
            _, channel = load_config(path).resolve_channel("ESPN2")
            self.assertEqual(channel.network_page, "ESPN")

    def test_capture_feedback_requires_capture_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "feedback": {
                            "base_url": "http://tv.invalid",
                            "required_source": "capture",
                        },
                        "channels": [{"name": "ESPN"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_capture_feedback_loads_selected_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "feedback": {
                            "base_url": "http://tv.invalid",
                            "required_source": "capture",
                            "required_capture_id": "capture:dazzle",
                        },
                        "channels": [{"name": "ESPN"}],
                    }
                ),
                encoding="utf-8",
            )
            feedback = load_config(path).feedback
            self.assertEqual(feedback.required_source, "capture")
            self.assertEqual(feedback.required_capture_id, "capture:dazzle")

    def test_unknown_channel_lists_available_channels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(
                self.write_config(Path(directory), [{"name": "ESPN"}])
            )
            with self.assertRaises(ChannelNotFoundError) as caught:
                config.resolve_channel("TBS")
            self.assertEqual(caught.exception.details["available"], ["ESPN"])

    def test_rejects_alias_collision_between_channels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(
                Path(directory),
                [
                    {"name": "Fox Sports 1", "aliases": ["FS1"]},
                    {"name": "FS1"},
                ],
            )
            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
