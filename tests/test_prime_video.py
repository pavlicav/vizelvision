import copy
import io
import json
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.config import FeedbackConfig, PrimeVideoConfig, RokuConfig, NavigationConfig
from roku_stream.ecp import EcpClient, RokuApp
from roku_stream.errors import ChannelNotFoundError, ConfigError, NavigationError
from roku_stream.feedback import PpmFrame, VisualFeedback
from roku_stream.prime_video import PrimeVideoCatalog, SOURCE_ID, observe, start_game
from roku_stream.roku_input import roku_target
from roku_stream.sources import SourceCatalog
from roku_stream.sports import SportsCatalog


GAME = {'league': 'nfl', 'game_id': 401872964, 'title': 'Pittsburgh Steelers at Cleveland Browns',
        'away': {'name': 'Pittsburgh Steelers', 'nickname': 'Steelers'},
        'home': {'name': 'Cleveland Browns', 'nickname': 'Browns'},
        'broadcasts': [{'name': 'Prime Video', 'market': 'national'}], 'state': 'in',
        'start_time': '2026-10-02T00:15Z', 'status': 'In Progress', 'finished': False}
EVENT = {'content_id': 'B0GZ57JWXN', 'title': 'Steelers vs. Browns', 'date': '2026-10-01',
         'live': True, 'url': 'https://www.primevideo.com/detail/B0GZ57JWXN'}


def page(body):
    return ('<script type="application/json" id="dv-web-page-hydration-data">' +
            json.dumps({'init': {'preparations': {'body': body}}}) + '</script>').encode()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.entity = {'titleID': EVENT['content_id'], 'entityType': 'EVENT', 'title': EVENT['title']}
        self.header = {'asin': EVENT['content_id'], 'entityType': 'EVENT', 'title': EVENT['title'],
                       'pageDateTimeBadge': 'Oct 1, 2026 7 PM EDT', 'liveState': {'isLive': True}}
        self.requests = []

    def catalog(self, request, timeout):
        self.requests.append(request.full_url)
        return io.BytesIO(page({'containers': [{'entities': [self.entity, self.entity]}]})
                          if 'tournament/' in request.full_url else
                          page({'atf': {'state': {'detail': {'headerDetail': {'event': self.header}}}}}))

    def resolve(self, game=None):
        return PrimeVideoCatalog(opener=self.catalog).resolve(game or GAME)

    def test_resolves_eastern_date_and_deduplicates_hero_and_card(self):
        self.assertEqual(self.resolve(), EVENT)
        self.assertEqual(len(self.requests), 2)

    def test_wrong_year_or_date_or_team_never_matches(self):
        for change in ({'pageDateTimeBadge': 'Oct 1, 2025 7 PM EDT'},
                       {'pageDateTimeBadge': 'Oct 11, 2026 7 PM EDT'}, {'title': 'Steelers vs. Bengals'}):
            with self.subTest(change=change):
                original = self.header.copy()
                self.header.update(change)
                with self.assertRaisesRegex(NavigationError, 'uniquely match'):
                    self.resolve()
                self.header = original

    def test_not_yet_live_and_replays_fail(self):
        self.header['liveState']['isLive'] = False
        with self.assertRaisesRegex(NavigationError, 'not started'):
            self.resolve()
        with self.assertRaisesRegex(NavigationError, 'ended'):
            self.resolve({**GAME, 'state': 'post'})

    def test_non_prime_and_schema_changes_fail_without_guessing(self):
        with self.assertRaisesRegex(NavigationError, 'not listed'):
            self.resolve({**GAME, 'broadcasts': [{'name': 'NBC'}]})
        self.assertEqual(self.requests, [])
        with self.assertRaisesRegex(NavigationError, 'metadata changed'):
            PrimeVideoCatalog(opener=lambda *a, **k: io.BytesIO(b'<html>Sign in</html>')).resolve(GAME)

    def test_deep_link_query_is_encoded(self):
        client = EcpClient('http://roku')
        with patch.object(client, '_request') as request:
            client.launch('13', content_id='a&b', media_type='live')
        request.assert_called_once_with('POST', 'launch/13?contentID=a%26b&mediaType=live')


class RoutingTests(unittest.TestCase):
    def test_prime_schedule_and_source_rows_keep_espn_game_and_date(self):
        config = Mock(channels=[])
        config.resolve_channel.side_effect = ChannelNotFoundError('none')
        sports = SportsCatalog(config, None)
        game = sports._suggest(GAME)
        target = {'source_id': SOURCE_ID, 'channel_id': str(GAME['game_id']), 'date': '2026-10-01'}
        self.assertEqual(game['suggested_target'], target)
        self.assertEqual(roku_target(target), target)
        for invalid in ('B0GZ57JWXN', '0', '-1', '１２'):
            with self.assertRaises(ConfigError):
                roku_target({**target, 'channel_id': invalid})
        sports.games = Mock(return_value={'date': '2026-10-01', 'games': [game, {**game, 'prime_video_target': None}]})
        listing = SourceCatalog(config, sports=sports).programs(SOURCE_ID, '2026-10-01')
        self.assertEqual(len(listing['channels']), 1)
        self.assertEqual(listing['channels'][0]['game']['id'], 'nfl:401872964')


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.ecp = Mock()
        self.ecp.device_info.return_value = {'ecp-setting-mode': 'enabled'}
        self.ecp.apps.return_value = [RokuApp('13', 'Prime Video')]
        self.ecp.active_app.return_value = RokuApp('13', 'Prime Video')
        self.player = {'state': 'play', 'plugin': {'id': '13'}, 'format': {'video': 'hevc_b', 'audio': 'aac_adts'}}
        self.ecp.media_player.return_value = self.player
        self.controller = Mock(ecp=self.ecp, feedback=Mock(assert_ready=Mock()), config=SimpleNamespace(
            roku=RokuConfig(), navigation=NavigationConfig(), prime_video=PrimeVideoConfig()))
        self.controller.feedback.capture.return_value = SimpleNamespace(rgb=bytes(range(256)) * 24)

    def run_game(self, observations):
        with patch('roku_stream.prime_video.observe', side_effect=observations):
            return start_game(self.controller, GAME, EVENT, [])

    def test_profile_then_two_verified_live_overlays(self):
        result = self.run_game([{'state': 'profile', 'focused_profile': True, 'matched': False},
                                *[{'state': 'game_overlay', 'matched': True}] * 2])
        self.assertTrue(result['selected_prime_event']['matched'])
        self.ecp.launch.assert_called_once_with('13', content_id=EVENT['content_id'], media_type='live')
        self.assertEqual([c.args[0] for c in self.ecp.keypress.call_args_list], ['Home', 'Select'])

    def test_sign_in_subscription_and_wrong_profile_are_actionable(self):
        for state in ('sign_in', 'subscription', 'profile'):
            with self.subTest(state=state):
                self.ecp.reset_mock()
                with self.assertRaises(NavigationError) as error:
                    self.run_game([{'state': state, 'matched': False}])
                self.assertIn('action_required', error.exception.details)
                self.assertEqual([c.args[0] for c in self.ecp.keypress.call_args_list], ['Home'])

    def test_existing_player_with_wrong_game_never_becomes_ready(self):
        with self.assertRaisesRegex(NavigationError, 'could not be visually verified'):
            self.run_game([{'state': 'unknown', 'matched': False}] * 24)
        self.assertNotIn('Select', [c.args[0] for c in self.ecp.keypress.call_args_list])

    def test_audio_only_and_wrong_plugin_are_rejected(self):
        for change in ({'format': {'audio': 'aac', 'video': 'none'}}, {'plugin': {'id': '195316'}}):
            with self.subTest(change=change):
                self.ecp.media_player.return_value = {**self.player, **change}
                with self.assertRaises(NavigationError):
                    self.run_game([{'state': 'game_overlay', 'matched': True}] * 24)

    def test_two_matches_must_be_consecutive(self):
        observations = [{'state': 'game_overlay', 'matched': True}, {'state': 'unknown', 'matched': False}]*12
        with self.assertRaises(NavigationError):
            self.run_game(observations)


class ObservedFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feedback = VisualFeedback(FeedbackConfig())
        cls.frames = {}
        for name in ('prime-profile', 'prime-live-overlay'):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(Path(__file__).parent / 'fixtures' / (name+'.jpg')),
                                  '-f', 'image2pipe', '-vcodec', 'ppm', '-'], check=True, capture_output=True).stdout
            cls.frames[name] = PpmFrame.parse(raw)

    def test_actual_focused_profile_and_other_name(self):
        result = observe(self.feedback, self.frames['prime-profile'], GAME, 'Vivian')
        self.assertEqual(result['state'], 'profile')
        self.assertTrue(result['focused_profile'])
        self.assertFalse(observe(self.feedback, self.frames['prime-profile'], GAME, 'Someone else')['focused_profile'])

    def test_actual_live_overlay_identifies_both_teams(self):
        self.assertTrue(observe(self.feedback, self.frames['prime-live-overlay'], GAME, '')['matched'])
        other = copy.deepcopy(GAME)
        other['home'] = {'nickname': 'Bengals', 'name': 'Cincinnati Bengals'}
        self.assertFalse(observe(self.feedback, self.frames['prime-live-overlay'], other, '')['matched'])


if __name__ == '__main__':
    unittest.main()
