import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from roku_stream import crawl, election
from roku_stream.config import MasterConfig
from roku_stream.crawl_desk import CrawlDesk

from tests.test_crawl import FakeMaster

FIXTURES = Path(__file__).with_name('fixtures') / 'election'
ALBERTA = election.DEFINITIONS / 'alberta-2026.json'
CLOSE = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc).timestamp()  # 8 PM Mountain, 10 PM Eastern
OFFICIAL = 'https://officialresults.elections.ab.ca/orEDResultsReferendum2026.cfm?EventId='
CSV_URL = 'https://alberta.io/api/referendum/results.csv'
CSV_HEAD = 'question,area_type,area_name,ed_number,option_a,option_b,rejected,stations_reported,stations_total,fetched_at\n'


def referendum_page(remain, separate, reported, units):
    """A results page the way Elections Alberta lays its pages out (open TR and TD tags,
    a provincial total row, a row per electoral division)."""
    return f'''<TABLE CELLPADDING=0 CELLSPACING=1 id="dataTbl"><thead><TR>
        <Th>ED<Th>ED Name<Th style="text-align:right;">Voting<BR>Locations
        <Th>Remain a province of Canada<Th>Commence the legal process to separate<Th>Rejected</tr></thead>
        <TR class="showTotal"><TD COLSPAN="2">Provincial Total<BR>Valid Vote Count Percentage
        <TD>{reported:,} of {units:,}<TD>{remain:,}<BR>{remain / max(1, remain + separate) * 100:.1f}%
        <TD>{separate:,}<BR>50%<TD>12
        <TR><TD><a href="x">1</a><TD>AIRDRIE-COCHRANE<TD>3 of 70<TD>1,000<TD>500<TD>1
        </TABLE>'''


class Response:
    def __init__(self, body, url):
        self.body, self.url = body.encode(), url

    def read(self, limit=None):
        return self.body

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Web:
    """The results sites: pages by URL; an official question not published yet redirects."""

    def __init__(self):
        self.pages, self.asked = {}, []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.asked.append(url)
        if url in self.pages:
            body = self.pages[url]
            if isinstance(body, Exception):
                raise body
            return Response(body, url)
        if url.startswith(OFFICIAL):
            return Response('<html>By-election results</html>',
                            'https://officialresults.elections.ab.ca/orResultsPGE.cfm?EventId=130')
        raise OSError(f'no page {url}')


class Parsing(unittest.TestCase):
    def setUp(self):
        self.alberta = election.load(ALBERTA)
        self.q10 = self.alberta['contests'][0]
        self.q1 = self.alberta['contests'][1]

    def test_the_definition_has_ten_questions_with_question_10_first(self):
        self.assertEqual([c['id'] for c in self.alberta['contests']], ['q10'] + [f'q{n}' for n in range(1, 10)])
        self.assertEqual([o['label'] for o in self.q1['options']], ['Yes', 'No'])
        self.assertEqual(self.alberta['polls'][0]['close'], CLOSE)
        self.assertEqual(self.alberta['warnings'], [60, 30, 10])

    def test_an_elections_alberta_referendum_page_gives_the_provincial_total(self):
        # Elections Alberta's 2021 referendum page, as published: its "Provincial Total" row.
        tally = election.page_tally((FIXTURES / 'ab-referendum-2021-q1.html').read_text(), self.q1)
        self.assertEqual(tally['votes'], {'yes': 642501, 'no': 399169})

    def test_a_page_without_the_options_is_not_read(self):
        # Where the results site sends us before results are published: the by-election's page.
        self.assertIsNone(election.page_tally((FIXTURES / 'ab-by-election-2026.html').read_text(), self.q1))

    def test_voting_locations_reporting_come_from_the_total_row_or_the_page(self):
        tally = election.page_tally(referendum_page(700123, 300000, 1234, 6000), self.q10)
        self.assertEqual(tally, {'votes': {'remain': 700123, 'separate': 300000}, 'reported': 1234, 'units': 6000,
                                 'unit': 'voting locations'})
        plain = referendum_page(700123, 300000, 1234, 6000).replace('1,234 of 6,000', '6,000').replace('3 of 70', '70')
        divisions = election.page_tally(plain, self.q10)
        self.assertEqual((divisions['reported'], divisions['units'], divisions['unit'], divisions['areas']),
                         (1, 1, 'electoral divisions', True))
        said = election.page_tally(plain + '<p>1,234 of 6,000 voting locations reported</p>', self.q10)
        self.assertEqual((said['reported'], said['units'], said['unit']), (1234, 6000, 'voting locations'))

    def test_a_results_csv_gives_the_province_row_else_the_sum_of_its_divisions(self):
        source = self.alberta['sources'][1]
        text = (CSV_HEAD + '10,province,Alberta,,700000,300000,10,1234,6000,t\n'
                '10,ed,Airdrie,1,8000,3000,1,12,70,t\n1,ed,Airdrie,1,50,40,0,2,70,t\n1,ed,Banff,2,30,20,0,1,60,t\n')
        found = election.csv_tallies(text, self.alberta['contests'], source)
        self.assertEqual(found['q10'], {'votes': {'remain': 700000, 'separate': 300000}, 'reported': 1234,
                                        'units': 6000, 'unit': 'voting stations'})
        self.assertEqual((found['q1']['votes'], found['q1']['reported'], found['q1']['units']),
                         ({'yes': 80, 'no': 60}, 3, 130))
        self.assertNotIn('q2', found)


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = CLOSE - 3.5 * 3600  # 6:30 PM Eastern
        self.web = Web()
        self.state = Path(self.temp.name) / 'election-state.json'
        self.feed = self.make()

    def make(self):
        return election.ElectionFeed(state_path=self.state, opener=self.web, clock=lambda: self.now)

    def results(self, remain, separate, reported, units=6000):
        self.web.pages[OFFICIAL + '202610'] = referendum_page(remain, separate, reported, units)

    def test_before_polls_close_it_says_when_and_each_warning_is_news(self):
        self.feed.refresh()
        self.assertEqual(self.web.asked, [])  # no results to fetch yet
        [item] = self.feed.items()
        self.assertEqual((item['id'], item['tag'], item['heading']),
                         ('election:ab2026:polls', 'ALBERTA', 'POLLS CLOSE AT 10 PM ET'))
        self.assertTrue(item['text'].startswith(
            'Voting ends across Alberta at 10 PM Eastern, 8 PM Mountain: in 3 hours 30 minutes. Ten questions'))
        seen = []
        for minutes in (59, 45, 29, 9, 0.5):
            self.now = CLOSE - minutes * 60
            [item] = self.feed.items()
            seen.append((item['id'].rsplit(':', 1)[-1], item['heading']))
        self.assertEqual(seen, [('60', 'POLLS CLOSE IN 1 HOUR'), ('60', 'POLLS CLOSE IN 1 HOUR'),
                                ('30', 'POLLS CLOSE IN 30 MINUTES'), ('10', 'POLLS CLOSE IN 10 MINUTES'),
                                ('10', 'POLLS CLOSE IN 10 MINUTES')])
        self.assertIn('in under a minute', item['text'])

    def test_at_the_close_polls_are_closed_until_results_come_in(self):
        self.now = CLOSE + 60
        self.feed.refresh()
        [item] = self.feed.items()
        self.assertEqual((item['id'], item['heading']), ('election:ab2026:polls:closed', 'POLLS ARE CLOSED'))
        self.assertIn('Question 10 is counted first', item['text'])
        self.now = CLOSE + 3 * 3600
        self.assertEqual(len(self.feed.items()), 1)  # still no results: it stays
        self.results(1000, 500, 10)
        self.feed.refresh()
        self.assertEqual([i['id'] for i in self.feed.items()], ['election:ab2026:q10:e1'])

    def test_results_read_official_first_and_fall_back_to_the_csv(self):
        self.now = CLOSE + 3600
        self.web.pages[CSV_URL] = CSV_HEAD + '10,province,Alberta,,7000,3000,1,120,6100,t\n'
        self.feed.refresh()
        [item] = self.feed.items()
        self.assertEqual((item['tag'], item['heading']), ('ALBERTA Q10', 'SEPARATION'))
        self.assertEqual(item['text'], 'Remain 70.0% (7,000), Separate 30.0% (3,000). 120 of 6,100 voting stations '
                                       'reporting (2%). Unofficial results, via alberta.io.')
        self.results(712345, 287655, 1500)
        self.feed.refresh()
        [item] = self.feed.items()
        self.assertEqual(item['text'], 'Remain 71.2% (712,345), Separate 28.8% (287,655). 1,500 of 6,000 voting '
                                       'locations reporting (25%). Unofficial results, Elections Alberta.')
        sources = {s['name']: s for s in self.feed.status()['elections'][0]['sources']}
        self.assertEqual((sources['Elections Alberta']['contests'], sources['alberta.io']['contests']), (1, 0))

    def test_divisions_with_votes_are_never_all_in(self):
        self.now = CLOSE + 3600
        self.results(1000, 500, 10)
        self.web.pages[OFFICIAL + '202610'] = self.web.pages[OFFICIAL + '202610'].replace('10 of 6,000', '6,000').replace(
            '3 of 70', '70')
        self.feed.refresh()
        [item] = self.feed.items()
        self.assertIn('Results from 1 of 1 electoral divisions.', item['text'])
        self.assertFalse(self.feed.state['ab2026']['q10']['complete'])

    def test_one_unreachable_question_page_leaves_the_others(self):
        self.now = CLOSE + 3600
        self.results(1000, 500, 10)
        self.web.pages[OFFICIAL + '202601'] = OSError('timed out')
        self.feed.refresh()
        self.assertEqual(self.feed.items()[0]['id'], 'election:ab2026:q10:e1')
        sources = {s['name']: s for s in self.feed.status()['elections'][0]['sources']}
        self.assertEqual((sources['Elections Alberta']['ok'], sources['Elections Alberta']['note']),
                         (True, '1 of its pages unreachable'))

    def test_a_dead_source_never_stops_the_other_or_the_poll_times(self):
        self.now = CLOSE + 3600
        self.web.pages[OFFICIAL + '202610'] = OSError('timed out')
        self.web.pages[CSV_URL] = CSV_HEAD + '10,province,Alberta,,7000,3000,1,120,6100,t\n'
        self.feed.refresh()
        self.assertEqual(self.feed.items()[0]['id'], 'election:ab2026:q10:e1')
        sources = {s['name']: s for s in self.feed.status()['elections'][0]['sources']}
        self.assertEqual((sources['Elections Alberta']['note'], sources['alberta.io']['ok']),
                         ('1 of its pages unreachable; results pages not published yet', True))
        # Results nobody has read again for half an hour are dropped, not left frozen.
        self.web.pages[CSV_URL] = OSError('down')
        self.now += 1800
        self.feed.refresh()
        self.assertEqual(self.feed.items()[0]['id'], 'election:ab2026:polls:closed')

    def test_each_large_batch_is_a_new_edition_at_most_every_ten_minutes(self):
        self.now = CLOSE + 3600
        editions = []

        def poll(remain, separate, reported, minutes=1):
            self.results(remain, separate, reported)
            self.now += minutes * 60
            self.feed.refresh()
            editions.append(self.feed.items()[0]['id'].rsplit(':e', 1)[1])
        poll(1000, 500, 10)        # first results
        poll(1500, 800, 20)        # a trickle: the same edition, new numbers
        poll(30000, 9000, 40, 10)  # 36,700 more votes: a large batch
        poll(31000, 9500, 200)     # 160 more locations (2.7 points), but within 10 minutes of the last: held
        poll(31100, 9600, 205)
        poll(31200, 9700, 210, 9)  # the held batch goes out once 10 minutes have passed
        poll(40000, 15000, 6000)   # everything in: at once
        self.assertEqual(editions, ['1', '1', '2', '2', '2', '3', '4'])
        self.assertIn('All 6,000 voting locations reporting.', self.feed.items()[0]['text'])
        # A web restart neither repeats an edition nor forgets one.
        again = self.make()
        again.refresh()
        self.assertEqual(again.items()[0]['id'], 'election:ab2026:q10:e4')
        self.assertEqual(json.loads(self.state.read_text())['ab2026']['q10']['edition'], 4)

    def test_nothing_shows_outside_the_window(self):
        self.now = datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp()
        self.feed.refresh()
        self.assertEqual(self.feed.items(), [])
        self.assertEqual(self.feed.status()['elections'], [])

    def test_a_us_night_closes_state_by_state(self):
        definition = {
            'id': 'us2026', 'name': 'Election Night', 'tag': 'MIDTERMS', 'zone': 'America/New_York',
            'show_from': '2026-11-03T00:00:00-05:00', 'show_until': '2026-11-05T00:00:00-05:00',
            'polls': [{'where': 'in Georgia, Indiana, Kentucky, South Carolina, Vermont and Virginia',
                       'close': '2026-11-03T19:00:00-05:00'},
                      {'where': 'in most of Florida and Pennsylvania', 'close': '2026-11-03T20:00:00-05:00'}],
            'contests': [{'id': 'ga-sen', 'tag': 'GA SEN', 'name': 'Georgia Senate',
                          'options': [{'key': 'd', 'label': 'Ossoff (D)'}, {'key': 'r', 'label': 'Collins (R)'}]}],
            'sources': []}
        folder = Path(self.temp.name) / 'elections'
        folder.mkdir()
        (folder / 'us-2026.json').write_text(json.dumps(definition))
        feed = election.ElectionFeed(folder, opener=self.web, clock=lambda: self.now)
        self.now = datetime(2026, 11, 3, 23, 50, tzinfo=timezone.utc).timestamp()  # 6:50 PM Eastern
        self.assertEqual([(i['id'], i['heading']) for i in feed.items()],
                         [('election:us2026:polls:10', 'POLLS CLOSE IN 10 MINUTES'),
                          ('election:us2026:polls1', 'POLLS CLOSE AT 8 PM ET')])
        self.assertTrue(feed.items()[0]['text'].startswith('Voting ends in Georgia, Indiana, Kentucky, South Carolina, '
                                                           'Vermont and Virginia at 7 PM Eastern: in 10 minutes.'))


class DeskTests(unittest.TestCase):
    """The special report on the crawl: the poll warnings and each batch pop up at once."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = crawl.CrawlSettings(MasterConfig(socket_path=Path(self.temp.name) / 'master.sock'))
        self.settings.update({'segments': {k: {'enabled': k == 'election'} for k in crawl.SEGMENTS}})
        self.master, self.web = FakeMaster(), Web()
        self.now = CLOSE - 75 * 60
        self.feed = election.ElectionFeed(opener=self.web, clock=lambda: self.now)
        self.desk = CrawlDesk(self.settings, self.master, feeds={'election': self.feed}, clock=lambda: self.now)

    def tick(self):
        self.feed.refresh()
        self.desk.tick()

    def finish(self):
        key = self.master.state['crawl']['bulletin']['key']
        self.master.state['crawl']['bulletin'] = None
        self.master.state['crawl']['bulletins_ended'] = [{'key': key, 'how': 'done', 'at': self.now}]

    def test_warnings_and_results_pop_up_marked_new_and_ride_the_rounds(self):
        self.tick()
        first = self.master.sent[-1]  # what was on before the station looked: the next round, not news
        self.assertEqual((first['label'], first.get('flag'), first['items'][0]['heading']),
                         ('UPDATE', None, 'POLLS CLOSE AT 10 PM ET'))
        self.finish()
        self.now = CLOSE - 59 * 60
        self.tick()
        new = self.master.sent[-1]
        self.assertEqual((new['label'], new['flag'], new['style'], new['items'][0]['heading']),
                         ('SPECIAL REPORT', 'NEW', 'new', 'POLLS CLOSE IN 1 HOUR'))
        self.finish()
        self.now = CLOSE + 60
        self.tick()
        self.assertEqual(self.master.sent[-1]['items'][0]['heading'], 'POLLS ARE CLOSED')
        self.finish()
        self.now += 3 * 3600
        self.web.pages[OFFICIAL + '202610'] = referendum_page(1000, 500, 10, 6000)
        self.tick()
        batch = self.master.sent[-1]
        self.assertEqual((batch['flag'], batch['items'][0]['tag']), ('NEW', 'ALBERTA Q10'))
        self.assertEqual(self.desk.register()['items'][0]['source_name'], 'Election')


if __name__ == '__main__':
    unittest.main()
