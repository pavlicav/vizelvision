# Election special report

On an election night the crawl's **Election special report** segment (Crawl → Segments)
tells viewers when polls close, then carries the results as they come in. Its pop-ups are
labelled **SPECIAL REPORT**; each item's tag names the election and the contest
(`ALBERTA Q10`), and its heading the contest (`SEPARATION`).

It was built for Alberta's referendum of October 19, 2026 (ten questions) as a practice
run for the US midterms: everything about one election lives in a JSON definition, and
the crawl code knows nothing about Alberta.

## What airs

| When | Item | Pops up at once (NEW) |
| --- | --- | --- |
| Until an hour before the close | **POLLS CLOSE AT 10 PM ET**: when, in Eastern and the local zone, the countdown, and the definition's `preview` | no (it rides the update rounds) |
| 60, 30 and 10 minutes before (`warnings`) | **POLLS CLOSE IN 30 MINUTES** | yes, each one |
| From the close until results come in (and 30 minutes after) | **POLLS ARE CLOSED**, then the definition's `closed` text | yes |
| Each contest with results | each option's share and votes, then how many reporting units are in, then the source: "Remain 71.2% (712,345), Separate 28.8% (287,655). 1,500 of 6,000 voting locations reporting (25%). Unofficial results, Elections Alberta." | on each large batch |

Contests air in the definition's order (Alberta counts Question 10 first). A contest with no
votes yet is left out. Results not read again for 30 minutes are dropped, so a dead source
never leaves an old count on air.

**Large batches.** Each contest's item has an edition, part of its id
(`election:ab2026:q10:e3`). A new edition is news, so the desk pops it up at once, marked
NEW, on its own. Between editions the numbers still update, and the rounds carry the latest.
A new edition starts on:

- the first results;
- everything in (100% reporting);
- a large batch since the last poll (once a minute): `batch.votes` more votes (Alberta:
  20,000), or `batch.reporting` more of the units (0.02: two points of the voting places).

There is at most one edition every `batch.minutes` (10) per contest. A large batch inside
that window waits and goes out once it ends. The first results and everything in go out at
once. Editions are saved in `election-state.json` beside crawl.json, so a web restart
neither repeats an edition nor misses a batch that came in while it was down.

The segment follows the crawl's rules like any other: pop-ups in programs (and games, as
set now), the always-on loop over the off-air card, along the top during football.

## Sources: official first

A definition lists its sources in order. For each contest the first source with votes
wins, so official results are used whenever they are there. The others fill in only the
contests the official source lacks, and the item then says whose numbers they are
("Unofficial results, via alberta.io."). Results are fetched only from five minutes before
the first close. Crawl → Segments shows each source's health on the segment's card.

Kinds of source (`election.py`, `ElectionFeed._read`):

- **`elections_alberta`**: Elections Alberta's results site, one page per question
  (`orEDResultsReferendum2026.cfm?EventId=2026NN`; the contest's `keys.elections_alberta`
  is the NN event). Until results are published the site redirects to its by-election
  page, which reads as "not published yet". The page's layout for 2026 was not public
  before the night, so the reader is lenient. It handles HTML that leaves its TR and TD
  tags open. It finds an option's column by the words in its header (`match`). It takes
  the provincial total row, or else sums the rows. It reads "1,234 of 6,000" for the
  voting locations; failing that, it counts the electoral divisions with votes. It was
  checked against Elections Alberta's 2021 referendum page (`tests/fixtures/election/`).
- **`csv`**: any CSV with a row per contest and area. Column names come from the
  definition: `contest`, `options` (one column per option, in order), `reported`, `units`,
  and `area` and `total_areas` to pick the province-wide row (else the rows of one area
  kind are summed). Alberta's fallback is alberta.io's `results.csv`, which reads Elections
  Alberta.

## A definition

`roku_stream/elections/*.json`. Every file is read, again every five minutes, so a new one
shows without a restart. An election shows between `show_from` and `show_until`.

```json
{
  "id": "ab2026",                    // in item ids: lowercase, up to 24
  "name": "Alberta Election Special Report",
  "tag": "ALBERTA",                  // leads every item's tag (with the contest's, up to 20 characters)
  "show_from": "2026-10-19T00:00:00-06:00",
  "show_until": "2026-10-23T00:00:00-06:00",
  "zone": "America/Edmonton", "zone_name": "Mountain",   // times also in this zone
  "polls": [{"where": "across Alberta", "close": "2026-10-19T20:00:00-06:00"}],
  "warnings": [60, 30, 10],          // minutes before each close
  "preview": "…",                    // after the first closing's countdown
  "closed": "…",                     // after the last closing's "polls are closed"
  "batch": {"votes": 20000, "reporting": 0.02, "minutes": 10},
  "sort": "fixed",                   // or "votes": options by votes, most first
  "contests": [{"id": "q10", "tag": "Q10", "name": "Separation",
                "keys": {"elections_alberta": "202610", "csv": "10"},
                "options": [{"key": "remain", "label": "Remain", "match": ["remain"]}, …]}],
  "sources": [{"kind": "elections_alberta", "name": "Elections Alberta", "official": true, "url": "…{key}"}, …]
}
```

A contest without `options` is Yes/No.

## The US midterms (November 3, 2026)

Write `roku_stream/elections/us-2026.json`:

- **Several closings.** `polls` takes one entry per closing time, each with its `where`
  ("in Georgia, Indiana, Kentucky, South Carolina, Vermont and Virginia" at 7 PM Eastern).
  Each closing has its own countdown, warnings and "closed" item. `zone` "America/New_York"
  shows Eastern only.
- **Races.** Contests are races, their options candidates (`"label": "Ossoff (D)"`), with
  `"sort": "votes"`. Set `batch.votes` to suit each race's size.
- **Sources.** Each official source is a state's or county's results site, so a new
  `kind` goes in `ElectionFeed._read` for each layout used. Many states and counties publish
  on Scytl Clarity (ENR), whose summary JSON or CSV is one adapter for all of them; the
  `csv` kind already reads a summary CSV. List the official source first and a
  national aggregator after it. AP's feed needs a contract.
- **Calls.** Nothing here calls a race: the crawl shows counts and how much is in.

## Tests

`tests/test_election.py` (`/usr/bin/python3 -m unittest tests.test_election`) covers:

- the Alberta definition;
- Elections Alberta's 2021 page, and its by-election page refused;
- reporting units from the total row or the page;
- the CSV;
- the poll-closing timeline and its warnings;
- official ahead of the fallback, a dead source, stale results;
- the batch editions and their cooldown, across a restart;
- a US night with two closings;
- the desk: the warnings and each batch pop up marked NEW.
