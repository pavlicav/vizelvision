# The crawl

The crawl is a bar of scrolling text along the bottom of master output, over everything
on air: programs, the off-air card and the station ID. It slides up when something
runs and slides away when it ends.

## Three layers

Highest first:

1. **Important.** Severe weather and the one manual important message. It runs
   continuously, in red, until it ends; nothing interrupts it.
   - EAS warnings for the watched area (DC, SAME `011001`), from the EAS decoder on this
     server (`~/eas_decoder`).
   - NWS alerts for the watched zones (`DCZ001`, `DCC001`) from api.weather.gov that are
     Severe or Extreme *and* Immediate or Expected (warnings; watches are "Future").
   - The **important message**: one slot, typed by the operator, for 30 minutes to 12
     hours or until cleared.
2. **Override.** The operator's message holds the bar, for a set time or until cleared.
3. **Bulletins.** The rotation (`roku_stream/crawl_desk.py`, in the web app) puts one
   segment on at a time. A bulletin runs one pass, then the bar slides away.

The master worker owns layers 1 and 2, so severe weather still airs if the web app is
down. It refuses a bulletin while either runs. Every bulletin carries a lease (10 min,
or 30 s for a loop that the web app renews every 10 s), so a stopped web app never
leaves one on air.

## The rotation

What the rotation does depends on what is on master:

| Context | Default | |
| --- | --- | --- |
| Programs | Pop-ups | one segment at a time, then the bar goes away |
| Live games | Important only | no rotation over a game |
| Off-air card | Always on | every segment's items loop without stopping |
| Station ID | Important only | |

The context comes from the worker: nothing on air means the off-air card, and the ID
slot on air means the station ID. A game is whatever the schedule projection says is on
now. Pop-ups follow the limits: at most 4 an hour, at least 5 minutes apart. Each segment
is due every N minutes; with *Only when it changes* it also waits for new items. The
most overdue segment goes first.

### Segments

| Segment | Source | Every |
| --- | --- | --- |
| Weather alerts | Lesser EAS and NWS alerts (watches, advisories, statements), from the worker | 10 min |
| Metro and bus | WMATA rail incidents and bus GTFS-realtime service alerts, for the routes you choose | 15 min |
| AlertDC | DC HSEMA's AlertDC list, last 24 hours, without police crime alerts | 30 min |
| Weather | api.weather.gov: now, and the next two forecast periods, for your ZIP (default Reagan National) | 30 min |
| Scores | ESPN: today's games for the teams you follow | 20 min |
| Coming up | The schedule projection: the next two programs | 30 min |
| Now on Cairo Radio | Cairo's public API: show and track, only under the off-air card while Cairo is the off-air audio | 15 min |
| Station messages | Your messages, each on its days, times and dates; one per pop-up, taking turns | 20 min |

Each item has a small tag box in front of it, such as RED LINE, BUS D50, NHL or TONIGHT.
Feeds poll only while their segment is on. Each keeps its last items through an
outage, then drops them when they go stale, so a dead feed goes quiet instead of airing
old delays. Street sweeping waits for spring: DC publishes sweeper GPS maps, not a
schedule API, and the season runs April to October.

### Feed options

Crawl → Sources → **Metro and bus** turns rail incidents and bus alerts on or off, and picks
the bus routes to show. Search WMATA's route list by number or name. With no routes
chosen, every route's alerts can air. A bus alert shows when it affects one of your
routes, and your routes lead its tag (BUS D60/D6X). **Weather location**
takes a ZIP code. It is looked up when saved (Zippopotam.us), so a wrong one is
refused. The forecast is then for that ZIP, and "now" comes from the nearest NWS station
reporting a temperature (for 20011: College Park, else Reagan National). Without a ZIP,
both come from the config (`crawl.weather_station`, `crawl.forecast_point`). These
options are applied as the items are read, so a change shows at once.

They live in `crawl-feeds.json` beside `crawl.json`. Only the web app reads it, so
changing them never needs the master worker restarted.

The WMATA key is read when the feed polls: first from the `WMATA_API_KEY` environment
variable, then from the `KEY=value` file at `crawl.keys_file` (on this host, the same file
Continuity reads). It is never logged or copied.

## Alerts

When NWS and the EAS decoder both have an alert (the same event name), the NWS text
runs, because it is the official wording. The EAS copy is listed as a duplicate. An EAS
alert's text is the encoder-style summary from its header. For a severe one, the
decoder's transcript follows; it is speech recognition and can mishear names, so it can
be turned off. An NWS alert's text is its headline, then its description, up to 700
characters ("HAZARD..." reads "Hazard:"). Weekly and monthly tests are left out unless
switched on, and then pop up with the weather alerts. **Mute** in the register takes any one
alert out of the crawl (a dismissal, which the worker honours). SAME cannot cancel a warning; NWS alerts end when NWS ends them.

## The Crawl page

`/crawl` ([web-ui.md](web-ui.md)) is laid out around items, not segments:

- **On the bar now** shows a to-scale mimic of master's bar, the context and its rule,
  pop-ups this hour, and **Coming up on the bar**: the next planned pop-ups and loops.
- **Who holds the bar** shows the three layers and which one has it.
- **Alerts & items** is the register (below).
- **The controls**, in tabs:
  - **Messages on the bar**: the important message (it asks first) and the override, each
    with a duration.
  - **Rules**: the rule for each context, and the limits.
  - **Segments**: a card per segment with its switch, **Repeat every** *n* min, *only when it
    changes*, *new items pop up at once*, the contexts it airs in, feed health, a preview,
    and **Run now**.
  - **Sources**: the EAS and NWS switches and their health, Metro and bus, and the weather
    ZIP.
  - **Teams**, **Station messages** and **History**.
- **Machinery** draws the next three hours: the contexts ahead from the schedule, the rule
  in each, every planned pop-up, and the gap after each one.

## The register

The register lists every item the crawl can air, from every source, alerts first:

- **Alerts:** EAS, NWS, Metrorail, Metrobus, AlertDC, and the manual important and override
  messages.
- **Everything else:** weather, scores, coming up, Cairo and station messages.

**Columns.** Each row has its status, its airing, when it last aired, when it airs next, and
why:

| Status | Meaning |
|---|---|
| On air | In the pop-up running now. |
| Looping | In the important or override layer, or in an always-on loop. |
| Next | Planned. **Next** is when, with "at once" for new items and "loop" for an off-air loop. |
| Held | Not planned within three hours. **Why** says what holds it: quiet during games, the segment is off, not set to air in this context, repeat is off, a higher layer holds the bar, … |
| Muted | Taken out of the crawl. |
| Duplicate | An EAS copy of an NWS alert. |

**Airing** is **FIRST** if the airing on now, or the next one, is the item's first, and
**REPEAT** otherwise, with how many times it has aired.

**Actions.** **Air now** pops the item up at once, whatever the rules (not over a higher
layer). **Mute** and **Unmute** take it out of the crawl and put it back. EAS and NWS alerts
are dismissed in `crawl.json`, which the worker honours; anything else is muted in the
ledger. **Hold** copies the item into the override slot for a chosen time. Clicking a row
shows its id, source, layer, times and every airing.

**How it works**

- **Identity.** Each feed names its items: `rail:<IncidentID>`, `bus:<GTFS entity>`,
  `alertdc:<hash of time and title>`, `weather:now` and `weather:<period>`,
  `score:<league>:<game>`, `coming:<hash of start>`, `cairo:now`, `msg:<id>`.
  - The worker's alerts are `eas:<id>` and `nws:<urn>`. `alert_layers` builds
    `rotation_alerts` in the same order as its summaries, so the desk matches the n-th
    rotation alert to the n-th summary that is neither dismissed, important nor a duplicate.
    No master change was needed for this.
  - An item a feed cannot name is `<segment>:<hash of tag and text>`.
  - Ids and times ride on the items inside the web app. `_air()` strips everything but
    tag, heading and text before a bulletin goes to master.
- **The ledger.** `roku_stream/crawl_ledger.py` writes
  `state/master-candidate/crawl-ledger.json`, saved at most every 20 s, and on stop.
  - **Per item** it records first seen, last listed, first and last aired, the count, the
    last twelve airings (when, how it ended, context, layer, by hand, new), and muted.
  - **What counts as an airing.** The desk records one whenever a pop-up, a loop, or the
    worker's important or override layer starts carrying an item. A loop records each item
    once while it stays in.
  - **News for `new_now`.** The ledger replaced the in-memory "seen" set. An item is news if
    it has never aired and was first listed after the segment's first look, while its
    `new_now` was on. A restart remembers what was known, so it is not a burst.
  - An item no segment has listed for a day is forgotten.
- **The plan.** `CrawlDesk.plan()` plays the rules forward three hours:
  - the context ahead comes from the schedule projection: games, the off-air card,
    programs;
  - new items go first;
  - then the most overdue segment, at most `per_hour` an hour and `gap_minutes` apart;
  - `changed_only`, `repeat`, contexts and station-message turns are honoured;
  - a higher layer holds the bar until its end.

  A pop-up lasts as long as that segment's recent passes took, or, failing that, as long as
  its text takes at 16 px a character and 120 px/s. The plan assumes nothing new arrives.
  `GET /v1/crawl` reports each segment's next planned pop-up as `next_planned`.

## How master draws it

`roku_stream/crawl_render.py` puts an `overlaycomposition` after the station clock. A
background thread renders each crawl once with Pango (Nimbus Sans Bold) into opaque
512-pixel tiles. Each frame, the draw callback places only the tiles on screen. The bar
is 7.5% of the picture high and 3.5% above the bottom edge (54 px high, 26 px up, at
720p). It moves 120 px/s, two whole pixels a frame at 60 fps, and slides in and out over
0.35 s. At 720p60, about 2.6 ms of CPU per frame while it shows, and none while it
is off (the draw handler is blocked). A one-pass crawl reports its key in `finished`
once its text has passed behind the label box and the bar has slid away. A changed crawl
with the same key (a transcript arriving, the loop's items changing) follows the running
pass instead of jumping.

## Settings and API

`crawl.json` sits beside `production.json` (`state/master-candidate/` on the live stack).
The web app writes it and the worker reads it every second. A file from the first
version is read as the override.

- `GET /v1/crawl`: settings, the worker's crawl status (`on_air`, `kind`, `key`, `items`,
  `alerts`, `rotation_alerts`, `bulletin`, `bulletins_ended`, `eas`, `nws`), the
  rotation's status (`context`, `mode`, `segments` with previews, `history`), and the
  segment, context and mode names.
- `POST /v1/crawl`: changed settings (`rules` and `segments` merge key by key; `messages`,
  `teams` and the flags replace).
- `POST /v1/crawl/important`, `POST /v1/crawl/override`: `{text, label, style?, minutes}`.
  `minutes: null` runs until cleared; empty text clears.
- `POST /v1/crawl/dismiss`: `{source: "eas"|"nws", id, dismissed}`.
- `POST /v1/crawl/run`: `{segment}`.
- `POST /v1/crawl/feeds`: `{transit?: {rail, bus, routes}, weather?: {zip}}`. An empty ZIP
  goes back to the config's station. `GET /v1/crawl` includes them as `feeds`.
- `GET /v1/crawl/bus-routes`: WMATA's bus routes `[{id, name}]` (cached a day).
- `GET /v1/crawl/alerts`: the register. Its keys:
  - `items`: each with `id`, `source`, `segment`, `kind`, `layer`, `status`, `airing`,
    `air_count`, `first_seen`, `first_aired`, `last_aired`, `airings`, `next_at`,
    `next_how`, `why`, and the item's words and times.
  - `plan`: `spans`, `slots`, `loops`, `until`.
  - `gone`: items that ended in the last six hours.
  - Also `counts`, `context`, `mode`, `higher` and `running`.
- `POST /v1/crawl/alerts/<id>` (id URL-encoded): `{action: "air" | "mute" | "unmute"}`.
- `GET /v1/sports/teams?league=nhl`: a league's teams, for Teams to follow.

Worker socket: `{"action": "crawl", "body": {"bulletin": {...} | null}}`; see
`crawl.validate_bulletin`.

Config: `master.eas_url`, `master.eas_areas`, `master.nws_zones` (empty turns NWS
off), and the `crawl` section: `keys_file`, `weather_station` (KDCA), `weather_place`,
`forecast_point`.

## Tests

- `tests/test_crawl.py`: settings and migration, message windows, EAS and NWS wording,
  layers and keys, bulletin validation, the worker's layers and leases, the rotation's
  rules, the GTFS-realtime decoder, the feeds, and the API.
- `tests/crawl_integration.py` (`/usr/bin/python3`): a private MediaMTX and a real 720p60
  master. It reads frames back over RTSP to check an important alert, a bulletin that
  runs once and slides away by itself, an override, clearing, and output lag.
- `tests/test_crawl.py` also covers the register: bare items to master, first then repeat,
  EAS and NWS ids, the important layer as an airing, the plan against a game, air now and
  mute, and the ledger across a restart.
- `tests/browser_ui_crawl.cjs`: the Crawl page with mocked requests: register statuses,
  filters, details, every action and control, and phone width.
