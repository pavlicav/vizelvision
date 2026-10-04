from pathlib import Path
import tempfile
import unittest

from roku_stream.controller import RokuStreamController
from roku_stream.errors import NavigationError
from roku_stream.feedback import VisualFeedback

from tests import test_controller
from tests.test_controller import FakeEcp

BILLS = {'game_id': 401872953, 'title': 'Los Angeles Chargers at Buffalo Bills',
         'away': {'name': 'Los Angeles Chargers', 'nickname': 'Chargers'},
         'home': {'name': 'Buffalo Bills', 'nickname': 'Bills'}}
# Text read from the live 720p guide on September 23 (OCR renders "NFL ST" as "NEL ST").
BILLS_HEADER = ('6:27 PM\nLos Angeles Chargers at Buffalo\nBills\nIn 3 days\n'
                'Sun, Sep 27, 1:00 PM « NEL ST - FOX')


def row(title, *, channel=None, live=True, ticket_logo=True):
    header = f'{title}\n' + ('' if live else 'In 3 days\n') + ('Sun · NEL ST · FOX' if not channel else 'FOX')
    return {'header': header, 'row': ('' if live else 'Upcoming: ') + title, 'channel': channel,
            'logo': ticket_logo and not channel}


class GuideFeedback:
    """A guide whose focus moves with the fake Roku's Down key."""
    ocr = object()

    def __init__(self, ecp, rows, *, logo_template=True):
        self.ecp, self.rows, self.logo_template = ecp, rows, logo_template

    def _row(self):
        index = self.ecp.keys.count('Down')
        return self.rows[min(index, len(self.rows) - 1)]

    def capture(self):
        return self._row()

    def read_guide_header(self, frame):
        text = frame['header']
        return {'text': text, 'sunday_ticket': 'NEL ST' in text, 'upcoming': 'In 3 days' in text}

    def read_guide_row(self, frame):
        return {'text': frame['row'], 'upcoming': frame['row'].startswith('Upcoming')}

    def identify_selected(self, channels, frame=None):
        if not frame['channel']:
            raise NavigationError('not a calibrated row')
        return {'channel': frame['channel']}

    def sunday_ticket_logo(self, frame):
        return {'matched': frame['logo'], 'difference': 1.0 if frame['logo'] else 40.0} if self.logo_template else None

    match_nfl_game = staticmethod(VisualFeedback.match_nfl_game)


class SundayTicketScanTests(unittest.TestCase):
    def scan(self, rows, game=BILLS, **options):
        self.ecp = FakeEcp()
        with tempfile.TemporaryDirectory() as directory:
            controller = RokuStreamController(test_controller.ControllerTests.config(None, Path(directory)),
                                              ecp=self.ecp, feedback=GuideFeedback(self.ecp, rows, **options),
                                              sleeper=lambda _: None)
            controller._open_channel_row = lambda *args, **kwargs: {'matched': True, 'channel': 'NBC'}
            anchor = min(controller.config.channels, key=lambda channel: channel.guide_index)
            self.events = []
            return controller._open_sunday_ticket_row(game, anchor, self.events)

    def test_finds_the_live_game_after_two_fresh_observations(self):
        result = self.scan([row('NBC', channel='NBC'), row('Carolina Panthers at Cleveland Browns'),
                            row('Los Angeles Chargers at Buffalo Bills'), row('Jets at Lions')])
        self.assertEqual(result['row_offset'], 2)
        self.assertEqual(self.ecp.keys, ['Down', 'Down'])  # No Select: the caller decides.
        self.assertEqual([o['teams'] for o in result['observations']],
                         [{'away': 'Los Angeles Chargers', 'home': 'Buffalo Bills'}] * 2)

    def test_upcoming_game_is_not_selected(self):
        with self.assertRaisesRegex(NavigationError, 'has not started'):
            self.scan([row('NBC', channel='NBC'), row('Los Angeles Chargers at Buffalo Bills', live=False)])
        self.assertNotIn('Select', self.ecp.keys)

    def test_live_ocr_text_from_the_device_matches(self):
        frame = {'header': BILLS_HEADER, 'row': 'Upcoming: Los Angeles Chargers at Buffalo Bills',
                 'channel': None, 'logo': True}
        with self.assertRaisesRegex(NavigationError, 'has not started'):
            self.scan([row('NBC', channel='NBC'), frame])

    def test_a_calibrated_channel_with_the_same_matchup_is_not_sunday_ticket(self):
        with self.assertRaisesRegex(NavigationError, 'not found'):
            self.scan([row('NBC', channel='NBC'), row('Los Angeles Chargers at Buffalo Bills', channel='FOX'),
                       row('Carolina Panthers at Cleveland Browns'), row('ESPN', channel='ESPN')])

    def test_scan_stops_after_the_sunday_ticket_block(self):
        rows = [row('NBC', channel='NBC'), row('Carolina Panthers at Cleveland Browns'),
                row('New York Jets at Detroit Lions'), row('FOX', channel='FOX')] + [row('x', channel='ESPN')] * 80
        with self.assertRaisesRegex(NavigationError, 'not found') as raised:
            self.scan(rows)
        self.assertEqual(raised.exception.details['rows_read'], 3)
        self.assertTrue(raised.exception.details['sunday_ticket_rows_seen'])

    def test_one_team_is_not_enough(self):
        with self.assertRaisesRegex(NavigationError, 'not found'):
            self.scan([row('NBC', channel='NBC'), row('Los Angeles Chargers at Kansas City Chiefs'),
                       row('ESPN', channel='ESPN')])

    def test_without_a_logo_template_uncalibrated_rows_still_qualify(self):
        result = self.scan([row('NBC', channel='NBC'), row('Los Angeles Chargers at Buffalo Bills')],
                           logo_template=False)
        self.assertEqual(result['row_offset'], 1)


class HeaderTextTests(unittest.TestCase):
    def header(self, text):
        feedback = object.__new__(VisualFeedback)
        feedback.ocr = type('Ocr', (), {'read': lambda self, *a, **k: type('O', (), {'text': text})()})()
        from roku_stream.feedback import PpmFrame
        return feedback.read_guide_header(PpmFrame(100, 100, bytes(30000)))

    def test_header_flags(self):
        self.assertEqual(self.header(BILLS_HEADER), {'text': BILLS_HEADER, 'sunday_ticket': True, 'upcoming': True})
        live = self.header('Los Angeles Chargers at Buffalo Bills\nSun, Sep 27, 1:00 PM • NFL ST • FOX')
        self.assertEqual((live['sunday_ticket'], live['upcoming']), (True, False))
        other = self.header('The front office discussed personnel status\nStarts in 5 min')
        self.assertEqual((other['sunday_ticket'], other['upcoming']), (False, True))


if __name__ == '__main__':
    unittest.main()
