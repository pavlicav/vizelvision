# The schedule: slots, sports slots and ideas

Rebuilt on 2026-11-09. Until then the Schedule page was a grid of half-hour cells that you
painted with blocks, each block one fixed channel. It was easy to paint by accident (above all
on a phone, where the grid also swallowed scrolling), a block named *Jeopardy* aired whatever
its channel had on, and overlapping games were drawn over each other. Sports priority was set
game by game, by hand, every week.

What plugs into the schedule did not change: it still feeds Up next about ten minutes ahead
with the same entries and keys ([source-queue.md](source-queue.md)), `GET /v1/playback` is the
same projection (each segment now also carries its schedule `key`), and the favorites planner,
continuity, the crawl and TV Thing's guide read it as before. The painted grid became slots on
the first start (the grid as it was is kept in `programming.v1.json` beside `programming.json`).

## The lineup: slots

A **slot** is a programme that repeats: the days of the week, a start to the minute, a length,
and what airs ([lineup.py](../roku_stream/lineup.py)):

| A slot airs | How the source is found |
|---|---|
| **A programme** by name | Each airing is looked up in the listings ([guide_index.py](../roku_stream/guide_index.py)), so the channel follows the programme: on its usual channel if it is listed there, else the antenna before YouTube TV. It takes the listed start and end when they are within 45 minutes of the slot's. Past the listings' reach (a day or two), or when they do not name it, it airs its **usual channel**; with none, that airing is skipped and says so. |
| **A channel** | Always that channel (what a painted block was). OFF AIR makes a planned test-card break. |
| **From the library** | One file of a folder per airing: the next in order (the place is remembered), the newest recording, or one at random. Ad breaks are spliced in where the file was scanned for them. The airing ends with the file: the rest of the slot is OFF AIR, and a file longer than its slot is cut only by something starting. |

Time no slot covers is OFF AIR. Where two slots overlap, the higher priority has the time, then
the one that starts later; the other resumes when it ends. An airing is **settled** 15 minutes
before it starts and stays so until it ends (`pins` in `programming.json`), so the entry in Up
next keeps its key whatever the listings do meanwhile. **Skip this one** leaves a single airing
out. Shows and games on a date still come before the lineup, exactly as before.

## Sports slots

A **sports slot** is a standing appointment with a league: *Monday Night Football* is the NFL
game that starts on a Monday between 7:00 and 11:30 PM on ESPN or ABC
([sports_slots.py](../roku_stream/sports_slots.py)). A rule has a league, days, the time of day
a game starts between, and optionally networks (`Prime Video`, `Sunday Ticket`, `ESPN Unlimited`
and `MLB.TV` name games no channel carries) and teams. Every 10 minutes, and at once after a
change, each game a rule finds in the next 8 days goes on the schedule as a game show, from its
start (less the lead-in) on the channel the sports catalog suggests, then back to the schedule
after the final.

- **Priority is the slot's**, in plain words on its form: *High* cuts in at the start, even
  into another game; *Normal* waits for a game on air to finish and joins in progress; *Low*
  gives way. Change it once and every game of the slot that has not started follows.
- **Air the best one** takes one game a day: a favorite's (by its place on the favorites list),
  then one on a regular channel rather than Sunday Ticket, then the earliest.
- A game already on the schedule (by hand, or a favorite's) is left there and marked as the
  slot's. It keeps the higher of its own priority and the slot's, and gets its own back if the
  slot goes. Once you set a game's priority yourself, the slot leaves it alone.
- Its games that have not started come off when the slot is removed, switched off or no longer
  finds them. One you removed stays off.

Ready-made slots: Monday, Thursday and Sunday Night Football, the NFL's early and late Sunday
games, college football at noon, in the afternoon and in prime time, and one national NBA, NHL
or MLB game a night. Favorite teams ([favorites.md](favorites.md)) work beside them, unchanged.

## The page

- **The week** is a calendar: seven days from today (one day on a phone), every slot's airings,
  shows and games as cards. The **coloured edge** of each day is what will really air
  (`GET /v1/playback`). Things that overlap sit side by side, and each card says what becomes of
  it: *Joins late*, *Cut short*, *Won't air* (hatched, with the reason and what is on instead),
  *Not listed*. Nothing is painted. Tapping a card opens it; tapping an empty time offers what
  to add there, and nothing is added until its dialog is saved. With a mouse, a slot can be
  dragged to another time or by its lower edge to another length (a finger scrolls instead).
- **Every change has an Undo** on its toast, and saves at once: there is no unsaved state.
- **Ideas** (below) and **Draft a week for me**, which lays the ideas that fit beside the lineup
  on the week as dashed green cards, to add one by one or all at once.
- **Sports**: the sports slots, the ready-made ones, and every game by league as before.
- **Clashes**: each show or game that will not air from its start, why, and a button that
  settles it (*Cut in at its start*, *Let … finish*).
- **Lineup**: every slot as a list, with a switch each. **As it will air**: the next 24 hours.

## Ideas

`GET /v1/programming/ideas` ([discover.py](../roku_stream/discover.py)) suggests what the lineup
lacks, each with the request that adds it:

- **Sports slots** not yet set up that have a game coming.
- **Fix-ups**: slots on a fixed channel whose time the listings name. *News 10* on YouTube TV's
  NBC at 6 is *News4 at 6*: rename it and let it follow the listings.
- **Strips**: programmes listed at the same time on several days, scored for first-run
  episodes, the broadcast networks, the evening, and what the station already airs or records.
- **Coming up once**: live events, premieres and new prime-time episodes in the listings.
- **Library**: folders with enough files for a strip, with a free half hour to put them in.
- **Habits**: channels put on by hand at the same time on different days.

The guide reaches a day or two, so each read is also noted in the **atlas**
(`guide-atlas.json`): per channel and programme, the weekdays and times it was listed. After a
week it knows the week, and ideas (and the programme search) get better. Only titles and times
are kept; a programme unseen for four weeks is forgotten. No model is involved.

## API

| | |
|---|---|
| `GET /v1/programming` | `settings` (`enabled`, `slots`, `sports`, `shows`, `removed`), `airings` (each slot's airings for 8 days: `by` listings, usual, fixed, library, unlisted, empty or skipped; `label`, `listed`, `why`), `guide`, and the timeline as before. |
| `POST /v1/programming` | `{enabled}`: the automation switch. An old grid body (`blocks`, `grid`) still replaces the lineup. |
| `POST /v1/programming/slots`, `…/slots/<id>`, `DELETE …/slots/<id>` | Add, change (any fields) and remove a slot. Each answers with the whole schedule and `changed` or `removed_slot`. |
| `POST /v1/programming/slots/<id>/skip` | `{date, skip}`: leave one airing out, or put it back. |
| `GET /v1/programming/sports` | The sports slots, the ready-made ones not yet added, and the games the last pass found. |
| `POST /v1/programming/sports`, `…/sports/<id>`, `DELETE …/sports/<id>` | Add, change and remove a sports slot. `…/sports/preview` lists the games a rule would find; `…/sports/plan` runs the planner now. |
| `GET /v1/programming/ideas` | The ideas, by group, and the `draft`. `?fresh=1` works them out again. |
| `GET /v1/programming/search?q=` | Programmes by name: listed ones with their next airing, then ones the atlas remembers. |
| `GET /v1/programming/library` | The library folders a slot can air. |

Shows and games on a date (`…/shows`), `take-current` and `follow-games` are unchanged.

## Trying it without the station

`python3 -m tests.dev_schedule_server <state folder> [port]` serves the page and the real
handler over a schedule of its own, seeded from the live one, with the real listings, library
and sports feeds. Every other read comes from the live station and every other write is
refused, so the page can be changed against tonight's games while the station airs on.

Tests: `tests/test_lineup.py`, `tests/test_sports_slots.py`, `tests/test_discover.py` (with the
API), `tests/browser_ui_schedule.cjs` (fixtures from `tests/fixtures/ui/make_schedule.py`), and
the suites that were there before, which pass unchanged against the new engine.

Going back: stop the web service, restore the files from `state/deploy-backup-20261109-schedule`
and `programming.v1.json` over `programming.json`, and start it.
