"""The NVENC probe logs why it chose x264, whatever goes wrong (10/22: an exception skipped it)."""
import types
import unittest
from unittest import mock

from roku_stream import master_media


class FakeGst:
    """Just enough of Gst for _nvenc_probe, with the failure chosen per test."""
    SECOND = 1
    State = types.SimpleNamespace(PLAYING="playing", NULL="null")
    StateChangeReturn = types.SimpleNamespace(FAILURE="failure", SUCCESS="success")
    MessageType = types.SimpleNamespace(ERROR=1, EOS=2)

    def __init__(self, *, factory=True, parse_error=None, start="success", message="eos"):
        self.factory, self.parse_error, self.start, self.message = factory, parse_error, start, message
        self.states = []
        self.ElementFactory = types.SimpleNamespace(find=lambda name: object() if self.factory else None)

    def parse_launch(self, description):
        if self.parse_error:
            raise self.parse_error
        gst = self

        class Pipeline:
            def set_state(self, state):
                gst.states.append(state)
                return gst.start if state == gst.State.PLAYING else gst.StateChangeReturn.SUCCESS

            def get_bus(self):
                return types.SimpleNamespace(timed_pop_filtered=lambda timeout, types_: gst._message())
        return Pipeline()

    def _message(self):
        if self.message == "eos":
            return types.SimpleNamespace(type=self.MessageType.EOS)
        if self.message == "error":
            return types.SimpleNamespace(type=self.MessageType.ERROR, parse_error=lambda: (
                types.SimpleNamespace(message="Could not initialize CUDA"), "gstnvbaseenc.c: cuInit failed"))
        return None


class NvencProbeTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(master_media, "_NVENC_WORKS", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def choose(self, gst):
        with self.assertLogs(master_media.__name__, "WARNING") as logs:
            encoder = master_media.video_encoder(gst, "auto", 60, 8000)
        return encoder.split()[0], logs.output[-1]

    def test_working_nvenc_is_chosen_and_logged(self):
        self.assertEqual(self.choose(FakeGst()), ("nvh264enc", f"WARNING:{master_media.__name__}:Master video encoder: nvh264enc"))

    def test_each_failure_falls_back_to_x264_and_says_why(self):
        for gst, why in ((FakeGst(factory=False), "no nvh264enc element"),
                         (FakeGst(parse_error=RuntimeError("no element \"nvh264enc\"")),
                          'RuntimeError: no element "nvh264enc"'),
                         (FakeGst(start="failure"), "the test pipeline would not start"),
                         (FakeGst(message=None), "no end of stream within 10 s"),
                         (FakeGst(message="error"), "Could not initialize CUDA (gstnvbaseenc.c: cuInit failed)")):
            with self.subTest(why=why):
                master_media._NVENC_WORKS = None
                encoder, line = self.choose(gst)
                self.assertEqual(encoder, "x264enc")
                self.assertTrue(line.endswith(f"x264enc (NVENC unusable: {why})"), line)

    def test_the_probe_runs_once_per_process(self):
        self.choose(FakeGst(message="error"))
        gst = FakeGst()
        self.assertEqual(master_media.video_encoder(gst, "auto", 60, 8000).split()[0], "x264enc")
        self.assertEqual(gst.states, [])

    def test_the_test_pipeline_is_always_stopped(self):
        gst = FakeGst(message="error")
        self.choose(gst)
        self.assertEqual(gst.states[-1], gst.State.NULL)


if __name__ == "__main__":
    unittest.main()
