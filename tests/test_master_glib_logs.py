"""GLib's warnings never call into Python (they can be logged under GLib's signal lock,
and a Python thread holding the GIL may be waiting for that lock: a deadlock)."""
import unittest
import warnings


class GlibLogTests(unittest.TestCase):
    def test_a_glib_critical_does_not_become_a_python_warning(self):
        try:
            from roku_stream.master import _gst
            gst = _gst()
            from gi.repository import GObject
        except Exception as exc:   # no GStreamer here
            self.skipTest(str(exc))
        element = gst.ElementFactory.make("identity", None)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            GObject.signal_handler_disconnect(element, 987654)   # "has no handler with id", from C
        self.assertEqual([str(w.message) for w in caught], [])


if __name__ == "__main__":
    unittest.main()
