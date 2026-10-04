import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from roku_stream.errors import ConfigError
from roku_stream.master import MasterStreamError, _gst, diagnostics
from roku_stream.publication import LocalMediaMtx, PublicationMonitor, _read, _stop, cancellation_handlers, candidate_config, publication_test


class PublicationTests(unittest.TestCase):
    def test_missing_bindings_identifies_interpreter_and_system_python_command(self):
        with patch.dict("sys.modules", {"gi": None}), patch("sys.executable", "/opt/conda/bin/python3"):
            with self.assertRaises(MasterStreamError) as caught:
                _gst()
            self.assertEqual(caught.exception.details["python_executable"], "/opt/conda/bin/python3")
            self.assertIn("/usr/bin/python3 -m roku_stream master-check", str(caught.exception))
            result = diagnostics()
            self.assertFalse(result["bench_available"])
            self.assertEqual(result["python_executable"], "/opt/conda/bin/python3")

    def test_missing_bindings_fails_before_server_or_socket_creation(self):
        with patch("roku_stream.publication._gst", side_effect=MasterStreamError("bindings missing")), \
                patch("roku_stream.publication.LocalMediaMtx") as server, \
                patch("roku_stream.publication._free_ports") as ports:
            with self.assertRaisesRegex(MasterStreamError, "bindings missing"):
                publication_test()
            server.assert_not_called()
            ports.assert_not_called()

    def test_candidate_has_one_nonoverriding_path_and_only_loopback_listeners(self):
        path = "vv-publication-" + "a" * 32
        config = candidate_config((18554, 18888, 19997), path)
        self.assertEqual(set(config["paths"]), {path})
        self.assertFalse(config["paths"][path]["overridePublisher"])
        self.assertFalse(config["paths"][path]["record"])
        self.assertEqual(config["rtspTransports"], ["tcp"])
        for protocol in ("rtsp", "hls", "api"):
            self.assertTrue(config[protocol + "Address"].startswith("127.0.0.1:"))
        for protocol in ("rtmp", "webrtc", "srt", "moq", "playback"):
            self.assertFalse(config[protocol])
        user = config["authInternalUsers"][0]
        self.assertEqual(user["ips"], ["127.0.0.1"])
        self.assertEqual({p["path"] for p in user["permissions"] if "path" in p}, {path})

    def test_invalid_paths_ports_and_duration_fail_before_start(self):
        for path in ("master", "../master", "all_others", "vv-publication-abc"):
            with self.subTest(path=path), self.assertRaises(ConfigError):
                candidate_config((18554, 18888, 19997), path)
        for ports in ((1, 1, 2), (0, 2, 3), (True, 2, 3), (65536, 2, 3)):
            with self.subTest(ports=ports), self.assertRaises(ConfigError):
                candidate_config(ports, "vv-publication-" + "a" * 32)
        for duration in (0, 15, 31, True, float("nan"), float("inf")):
            with self.subTest(duration=duration), patch("roku_stream.publication.subprocess.Popen") as launch:
                with self.assertRaises(ConfigError):
                    publication_test(duration=duration)
                launch.assert_not_called()

    def test_server_removes_inherited_configuration_and_stops_on_exit(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as work, patch("roku_stream.publication._free_ports", return_value=(18554, 18888, 19997)):
            server = LocalMediaMtx(Path("/test/mediamtx"), Path(work))
            with patch.dict("os.environ", {"MTX_RTSPADDRESS": ":8554", "MTX_PATHDEFAULTS_RUNONREADY": "bad-command"}), \
                    patch("roku_stream.publication.subprocess.Popen", return_value=process) as launch, \
                    patch("roku_stream.publication._json", return_value={"items": []}):
                with server:
                    env = launch.call_args.kwargs["env"]
                    self.assertFalse(any(k.startswith("MTX_") for k in env))
                    config = json.loads((Path(work) / "mediamtx.yml").read_text())
                    self.assertEqual(config["rtspAddress"], "127.0.0.1:18554")
                process.terminate.assert_called_once()
                process.wait.assert_called_once_with(timeout=3)
                self.assertTrue(server.log.closed)

    def test_failed_start_reaps_process_and_closes_log(self):
        process = Mock()
        process.poll.return_value = 1
        with tempfile.TemporaryDirectory() as work, patch("roku_stream.publication._free_ports", return_value=(18554, 18888, 19997)):
            server = LocalMediaMtx(Path("/test/mediamtx"), Path(work))
            with patch("roku_stream.publication.subprocess.Popen", return_value=process):
                with self.assertRaises(MasterStreamError):
                    with server:
                        self.fail("An exited server cannot be ready")
            self.assertTrue(server.log.closed)
            process.terminate.assert_not_called()

    def test_server_escalates_termination_after_deadline(self):
        from subprocess import TimeoutExpired
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [TimeoutExpired("mediamtx", 3), 0]
        _stop(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_media_reads_have_a_size_limit(self):
        with patch("roku_stream.publication.urlopen", return_value=io.BytesIO(b"123456")):
            with self.assertRaises(MasterStreamError):
                _read("http://127.0.0.1/test", limit=5)

    def test_hls_uris_cannot_escape_candidate(self):
        monitor = object.__new__(PublicationMonitor)
        monitor.server = Mock(path="vv-publication-" + "a" * 32)
        monitor.server.hls_url = "http://127.0.0.1:18888/" + monitor.server.path + "/index.m3u8"
        base = monitor.server.hls_url
        self.assertEqual(monitor._hls_url(base, "part.mp4"), base.replace("index.m3u8", "part.mp4"))
        for uri in ("../../master/part.mp4", "http://other.test/file", "//other.test/file", "file:///tmp/file", "/master/index.m3u8"):
            with self.subTest(uri=uri), self.assertRaises(MasterStreamError):
                monitor._hls_url(base, uri)

    def test_release_failure_is_reported(self):
        monitor = object.__new__(PublicationMonitor)
        monitor.server = Mock()
        monitor.server.status.return_value = {"ready": True}
        monitor.close_reader = Mock()
        with patch("roku_stream.publication.time.monotonic", side_effect=[0, 7]):
            with self.assertRaisesRegex(MasterStreamError, "not released"):
                monitor.finished()
        monitor.close_reader.assert_called_once()

    def test_hls_separate_audio_rendition_is_validated(self):
        monitor = object.__new__(PublicationMonitor)
        monitor.server = Mock(path="vv-publication-" + "a" * 32)
        monitor.server.hls_url = "http://127.0.0.1:18888/" + monitor.server.path + "/index.m3u8"
        manifest = b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=300000,AUDIO="audio"\nvideo.m3u8\n'
        monitor._hls_rendition = Mock(side_effect=[[{"codec_name": "h264"}], [{"codec_name": "aac"}]])
        with patch("roku_stream.publication._read", return_value=manifest):
            monitor._hls()
        self.assertEqual([c.args[0] for c in monitor._hls_rendition.call_args_list], ["video", "audio"])
        self.assertEqual({s["codec_name"] for s in monitor.hls_probe}, {"h264", "aac"})

    def test_hls_missing_audio_fails(self):
        monitor = object.__new__(PublicationMonitor)
        monitor.server = Mock(path="vv-publication-" + "a" * 32)
        monitor.server.hls_url = "http://127.0.0.1:18888/" + monitor.server.path + "/index.m3u8"
        monitor._hls_rendition = Mock(return_value=[{"codec_name": "h264"}])
        with patch("roku_stream.publication._read", return_value=b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\nsegment.mp4\n"):
            with self.assertRaisesRegex(MasterStreamError, "H.264 and AAC"):
                monitor._hls()

    def test_sigterm_unwinds_cleanup_and_restores_previous_handler(self):
        import signal
        previous = signal.getsignal(signal.SIGTERM)
        cleaned = []
        with self.assertRaises(KeyboardInterrupt):
            with cancellation_handlers():
                try:
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                finally:
                    cleaned.append(True)
        self.assertEqual(cleaned, [True])
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)


if __name__ == "__main__":
    unittest.main()
