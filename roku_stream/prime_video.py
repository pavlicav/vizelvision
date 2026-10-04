"""Prime's public event metadata and observed Roku TNF playback.

Prime exposes no supported consumer playback API here. Read the structured
metadata shipped with its public pages; credentials/playback stay in the Roku
app. Missing or changed metadata fails closed, without guessing a weekly ID.
"""
from datetime import datetime
from html.parser import HTMLParser
import json
import math
import re
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .errors import NavigationError, RokuNotReadyError

SOURCE_ID = 'thursday-night-football'
NFL_URL = 'https://www.primevideo.com/-/en/tournament/amzn1.dv.icid.8dc09428-4ec1-49d5-80a9-73d52c5f7ad6'
MAX_PAGE_BYTES = 8 * 1024 * 1024
EASTERN = ZoneInfo('America/New_York')


def prime_nfl_game(game):
    return game.get('league') == 'nfl' and any(
        re.sub(r'[^a-z]', '', str(b.get('name', '')).lower()) in
        ('primevideo', 'amazonprime', 'amazonprimevideo', 'amazon', 'prime')
        for b in game.get('broadcasts', []) if isinstance(b, dict))


def teams_match(text, game):
    # Whole words, both teams: a city or a single team's mention is insufficient.
    text = re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()
    for side in ('away', 'home'):
        team = game.get(side) or {}
        names = [team.get('nickname'), team.get('name')]
        if not any(name and (' ' + re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip() + ' ')
                   in ' ' + text + ' ' for name in names):
            return False
    return True


class _Hydration(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reading = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.reading = dict(attrs).get('id') == 'dv-web-page-hydration-data'

    def handle_endtag(self, tag):
        if tag == 'script':
            self.reading = False

    def handle_data(self, data):
        if self.reading:
            self.parts.append(data)


def parse_page(raw):
    try:
        parser = _Hydration()
        parser.feed(raw.decode('utf-8'))
        body = json.loads(''.join(parser.parts))['init']['preparations']['body']
        if not isinstance(body, dict):
            raise ValueError('Invalid body')
        return body
    except (ValueError, KeyError, TypeError) as exc:
        raise NavigationError('Prime Video event metadata changed or is unavailable; retry later') from exc


class PrimeVideoCatalog:
    def __init__(self, *, opener=urlopen, timeout=12):
        self.opener, self.timeout = opener, timeout

    def _page(self, url):
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en-US,en;q=0.9'})
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(MAX_PAGE_BYTES + 1)
            if len(raw) > MAX_PAGE_BYTES:
                raise ValueError('Oversized Prime Video page')
        except (OSError, URLError, ValueError) as exc:
            raise NavigationError('Could not load Prime Video event metadata', details={'reason': str(exc)}) from exc
        return parse_page(raw)

    def resolve(self, game):
        try:
            return self._resolve(game)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise NavigationError('Prime Video event metadata changed or is unavailable; retry later') from exc

    def _resolve(self, game):
        if not prime_nfl_game(game):
            raise NavigationError('This NFL game is not listed on Prime Video')
        if game.get('finished') or game.get('state') == 'post':
            raise NavigationError('This Prime Video game has ended; live preparation will not open a replay')
        try:
            start = datetime.fromisoformat(game['start_time'].replace('Z', '+00:00'))
            if start.tzinfo is None:
                raise ValueError('Missing timezone')
            day = start.astimezone(EASTERN).date()
        except (KeyError, TypeError, ValueError) as exc:
            raise NavigationError('The NFL game has no confirmed start date') from exc
        body = self._page(NFL_URL)
        candidates = set()
        for container in body.get('containers', []):
            for entity in container.get('entities', []):
                if entity.get('entityType') != 'EVENT' or not teams_match(str(entity.get('title', '')), game):
                    continue
                asin = entity.get('titleID', '')
                if re.fullmatch(r'[A-Z0-9]{10}', asin):
                    candidates.add(asin)
        matches = []
        if len(candidates) > 8:
            raise NavigationError('Prime Video returned too many matching events; check its catalog')
        for asin in sorted(candidates):
            detail = self._page('https://www.primevideo.com/-/en/detail/' + asin)
            headers = detail.get('atf', {}).get('state', {}).get('detail', {}).get('headerDetail', {})
            for header in headers.values():
                if (header.get('asin') != asin or header.get('entityType') != 'EVENT'
                        or not teams_match(str(header.get('title', '')), game)):
                    continue
                # Prime's event starts at pregame, before ESPN's kickoff. Compare
                # the explicit Eastern event date, never the catalog's "LIVE" alone.
                badge = header.get('pageDateTimeBadge', '')
                expected = f'{day.strftime("%b")} {day.day}, {day.year}'
                if not re.match(re.escape(expected) + r'\s', badge):
                    continue
                matches.append({'content_id': asin, 'title': header['title'], 'date': day.isoformat(),
                                'live': header.get('liveState', {}).get('isLive') is True,
                                'url': 'https://www.primevideo.com/detail/' + asin})
        if len(matches) != 1:
            raise NavigationError('Could not uniquely match this game and date in Prime Video',
                                  details={'game_id': game.get('game_id'), 'date': day.isoformat(),
                                           'matches': len(matches)})
        if not matches[0]['live']:
            raise NavigationError('Prime Video has not started the live broadcast yet; prepare again when it is live')
        return matches[0]


def observe(feedback, frame, game, profile_name):
    if feedback.ocr is None:
        raise NavigationError('Local OCR is required to verify Prime Video')
    w, h = frame.width, frame.height
    header = feedback.ocr.read(frame, crop=(int(w*.045), int(h*.04), int(w*.70), int(h*.21)), psm=11).text
    # The playback title and LIVE Main Broadcast are in a fixed top-left overlay.
    matched = teams_match(header, game) and bool(re.search(r'\blive\b', header, re.I)) \
        and 'main broadcast' in header.lower()
    if matched:
        return {'state': 'game_overlay', 'matched': True, 'text': header}
    # Crop the profile pane: full-frame contrast normalization loses the small
    # text against this mostly empty dark-blue screen.
    pane = feedback.ocr.read(frame, crop=(int(w*.06), int(h*.04), int(w*.55), int(h*.49)), psm=11).text
    text = pane + '\n' + feedback.ocr.read(frame, psm=11).text
    normalized = ' '.join(text.lower().split())
    if any(s in normalized for s in ('sign in', 'sign-in', 'amazon.com/mytv', 'register your device', 'scan the qr')):
        return {'state': 'sign_in', 'matched': False}
    if any(s in normalized for s in ('start your free trial', 'start your 30', 'join prime', 'subscribe to watch',
                                    'subscription required', 'not available in your location')):
        return {'state': 'subscription', 'matched': False}
    if re.search(r'\bkids?\b', normalized) and re.search(r'\bnew\b', normalized):
        # Observed Prime Roku profile chooser: the focused first avatar is
        # enlarged with a bright ring. Verify its name and ring, never Select
        # a remembered position on an unrecognized screen.
        first = feedback.ocr.read(frame, crop=(int(w*.175), int(h*.085), int(w*.55), int(h*.20)), psm=11).text
        ring = sum(frame.luma(round(w*(169 + 51*math.cos(a))/1280),
                              round(h*(101 + 51*math.sin(a))/720)) > 145
                   for a in (i*math.tau/24 for i in range(24)))
        name_matches = bool(profile_name and re.search(r'\b' + re.escape(profile_name) + r'\b', first, re.I))
        return {'state': 'profile', 'matched': False, 'focused_profile': name_matches and ring >= 12}
    return {'state': 'unknown', 'matched': False}


def start_game(controller, game, event, events):
    feedback, ecp, config = controller.feedback, controller.ecp, controller.config
    if feedback is None:
        raise NavigationError('Visual feedback is required for Prime Video')
    feedback.assert_ready()
    if ecp.device_info().get('ecp-setting-mode', '').lower() != 'enabled':
        raise RokuNotReadyError('Roku Control by mobile apps must be set to Enabled')
    app = next((app for app in ecp.apps() if app.name.casefold() == 'prime video'), None)
    if app is None or not app.id:
        raise RokuNotReadyError('Prime Video is not installed on the source Roku')
    controller._publish_operation(phase='launching_prime_video', message=f"Opening {event['title']} on Prime Video")
    # A cold launch clears previous content. An active app/player alone cannot
    # confirm that Prime accepted a new content ID.
    ecp.keypress('Home')
    controller._sleep(config.navigation.post_exit_settle_seconds)
    ecp.launch(app.id, content_id=event['content_id'], media_type='live')
    ecp.wait_for_active_app(app.id, timeout=config.roku.launch_timeout_seconds,
                            interval=config.roku.poll_interval_seconds)
    controller._sleep(3)
    selected_profile = False
    overlay_requests = 0
    verified = []
    # Bounded observations; all sleeps retain the controller's cancellation path.
    for attempt in range(24):
        controller._sleep(config.roku.poll_interval_seconds)
        if ecp.active_app().id != app.id:
            raise NavigationError('Prime Video stopped being the active Roku app')
        player = ecp.media_player()
        frame = feedback.capture()
        observation = observe(feedback, frame, game, config.prime_video.profile_name)
        events.append({'event': 'prime_observation', 'attempt': attempt, 'observation': observation,
                       'player_state': player.get('state')})
        state = observation['state']
        if state == 'sign_in':
            raise NavigationError('Sign in to Prime Video on the Roku, then prepare Thursday Night Football again',
                                  details={'action_required': 'prime_video_sign_in'})
        if state == 'subscription':
            raise NavigationError('Prime Video requires an eligible subscription or location; check the Roku',
                                  details={'action_required': 'prime_video_entitlement'})
        if state == 'profile':
            verified.clear()
            if selected_profile:
                continue  # The accepted Select can take several frames to close.
            if not observation.get('focused_profile'):
                raise NavigationError('Select your adult Prime Video profile on the Roku, then prepare again',
                                      details={'action_required': 'prime_video_profile'})
            ecp.keypress('Select')
            selected_profile = True
            controller._sleep(2)
            continue
        playing = (player.get('state') == 'play' and player.get('error') != 'true'
                   and (player.get('plugin') or {}).get('id') == app.id
                   and bool((player.get('format') or {}).get('video'))
                   and (player.get('format') or {}).get('video') != 'none')
        if player.get('error') == 'true':
            raise NavigationError('Prime Video reported a playback error')
        if playing and observation['matched']:
            verified.append(observation)
            if len(verified) >= 2:
                # Let the player controls fade and make the final capture fresh.
                controller._sleep(6)
                frame = feedback.capture()
                final = ecp.media_player()
                if ecp.active_app().id != app.id or final.get('state') != 'play' \
                        or (final.get('plugin') or {}).get('id') != app.id or final.get('error') == 'true':
                    raise NavigationError('Prime Video stopped after game verification')
                # A black/lost capture must not become an on-air selection.
                samples = frame.rgb[::max(1, len(frame.rgb)//2000)]
                if not samples or max(samples) - min(samples) < 25:
                    raise NavigationError('Prime Video is playing but the Roku picture is blank; prepare again')
                return {'roku_app': 'Prime Video', 'player_state': 'play',
                        'selected_prime_event': {'matched': True, **event, 'observations': verified},
                        'playback_evidence': 'two_live_matchup_overlays_with_prime_video_playback',
                        'playback_observation_count': len(verified)}
        else:
            verified.clear()
            if playing and overlay_requests < 3:
                ecp.keypress('Up')  # Reveal title/Live metadata without pausing.
                overlay_requests += 1
    raise NavigationError('Prime Video opened, but the requested live game could not be visually verified; check the Roku')
