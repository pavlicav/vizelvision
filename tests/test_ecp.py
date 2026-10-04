import unittest
import urllib.error
from unittest.mock import patch

from roku_stream.ecp import EcpClient, RokuApp
from roku_stream.errors import EcpError


class LaunchTests(unittest.TestCase):
    def test_accepted_launch_with_timed_out_response_is_observed_not_replayed(self):
        for cause in (TimeoutError(), urllib.error.URLError(TimeoutError())):
            with self.subTest(cause=cause):
                client = EcpClient('http://roku.test')
                with patch('urllib.request.urlopen', side_effect=cause) as request:
                    with patch.object(client, 'active_app', return_value=RokuApp('195316', 'YouTube TV')):
                        client.launch('195316')
                self.assertEqual(request.call_count, 1)

    def test_timeout_with_wrong_app_still_fails(self):
        client = EcpClient('http://roku.test', launch_timeout=0)
        with patch('urllib.request.urlopen', side_effect=TimeoutError()):
            with patch.object(client, 'active_app', return_value=RokuApp('14', 'MLB')):
                with self.assertRaises(EcpError):
                    client.launch('195316')

    def test_other_errors_are_not_hidden_by_active_app(self):
        client = EcpClient('http://roku.test')
        with patch('urllib.request.urlopen', side_effect=OSError('refused')):
            with patch.object(client, 'active_app') as active:
                with self.assertRaises(EcpError):
                    client.launch('195316')
                active.assert_not_called()
