# VizelVision Roku Stream

**VizelVision is pronounced "VIZZLE-VISION":** *vizzle* as in *fizzle*, then *vision*. Every
spoken line should say it that way: announcers, promo and ident voice-overs, the station ID.
Text for text-to-speech writes it as two words, **"Vizzle Vision"**, so the voice cannot
misread "Vizel" (the continuity announcers' lines already do). Lines voiced before
7 October 2026 (the station ID, the Sports ID and the first nine promos) spell it
"Vizel Vision".

## At a glance

VizelVision is a small automated TV station on one Linux box. It takes live channels from
an antenna, YouTube TV and other streaming apps, and puts one of them on air at a time,
following a schedule. It dresses the output like a broadcast station (station ID, crawl,
promos, captions) and takes the sound out of the commercial breaks. Viewers watch a single
output stream, in a browser or on a Roku.

```text
  INPUTS                          MASTER                                   VIEWERS
  antenna tuners ─────────┐
  Roku: YouTube TV, MLB,  │      ┌───────────────────────────────────┐
    Sunday Ticket, TNF ───┼────▶ │ decode ─▶ switch ─▶ delay ─▶ mute │ ─▶ MediaMTX ─▶ browser,
  recordings (library) ───┤      │ + clock, crawl, captions, promos  │    (HLS/RTSP)   Roku app
  internet streams ───────┤      │                                   │
  station ID, promos, ────┘      └───────────────────────────────────┘
    My ads, off-air card                │ copy of the picture   ▲ when to mute
                                        ▼ and sound             │
                                   AD DETECTOR (vizelvision-admute)
  CONTROL: the web app (Up next, Schedule, sports, crawl, continuity, UI) tells master what to air.
```

### The input stack

- **TV Thing**, a separate service on the same host, owns the hardware:
  - the antenna tuners (digital and analog);
  - since 6 October, the source Roku and its HD PVR capture card (the "Roku lane").
- **Asking for a channel.** VizelVision asks TV Thing for a channel or a game under a lock,
  then plays the feed it gets back.
- **The Roku.** The Roku lane drives the Roku by remote control (ECP). It reaches YouTube TV,
  the MLB app, NFL Sunday Ticket, Prime Video's Thursday Night Football and, since
  22 October, NHL games on ESPN Unlimited. It checks the screen before it accepts that
  the right thing is playing.
- **The sources Up next can put on air:**
  - `tv-thing-digital` and `tv-thing-analog` (the antenna);
  - `youtube-tv`, `mlb`, `sunday-ticket`, `thursday-night-football` and `nhl` (the Roku);
  - `library` (finished recordings and other files);
  - `internet` ([internet streams](docs/internet-streams.md): live HLS from the web that TV
    Thing relays, such as Pentulive on 29);
  - the station's own material: the station ID, promos, My ads, and the off-air card with
    Cairo Radio under it.
- **When a feed fails.** A live feed that stalls holds its last picture for 8 s. One that
  fails is put back on air automatically. A broadcast network can move between YouTube TV
  and the antenna.

### The pieces

| Process | What it does |
| --- | --- |
| `vizelvision-web` (port 6970) | The control room: the web UI and API, and Up next (the only way on air). Also the Schedule, which follows MLB and ESPN to move, retitle or drop games, and favorite teams. Plus the crawl's rotation, the continuity announcer, the promo and My ads settings, and the station watch. |
| `vizelvision-master` | The GStreamer master. It decodes the input on air and the one being prepared, and cuts between them. It holds the programme a few seconds, draws the clock, crawl, captions and promos, encodes H.264 (NVENC) and publishes. Severe-weather alerts run here, so they air even if the web app is down. |
| `vizelvision-mediamtx` | Serves master's output over RTSP and HLS to the browser monitor and the Roku viewer app. |
| `vizelvision-admute` | The ad detector, below. |

The first three start together under `vizelvision-stack.target`
([master worker](docs/master-worker.md)).

### How ad detection works

Full detail is in [docs/ad-mute.md](docs/ad-mute.md).

1. **Look ahead.** Master holds the programme up to 13 s before anyone hears it. Meanwhile
   the detector gets a small copy of each live input: a low-resolution picture and 16 kHz
   sound. It has seen and heard what follows a possible break before that moment airs.
2. **Gather evidence, every second.**
   - **Picture:**
     - black frames and hard cuts, where breaks begin;
     - score bugs and channel logos, which mean the programme;
     - YouTube TV's "Sponsored" label, which means an ad;
     - whether the picture looks like the last few minutes of the programme;
     - an image model's read of the frame.
   - **Sound:**
     - Whisper's transcript: ad wording, and the programme's own vocabulary;
     - audio fingerprints of ads it has heard before.
   - **Claude Haiku** reads the transcript (and, when the detector is unsure, a few
     frames) and calls it ad or programme.
   - **MLB's live play-by-play** says when an inning break starts.
3. **Weigh it.** One logistic model turns the evidence into a probability that each second
   is an ad. A Viterbi pass over the black frames and cuts decides where breaks start and end.
4. **Err towards sound.**
   - A mute starts only at a seam, and is retracted unless it is confirmed within 10 s.
   - It never starts under a score bug the detector trusts.
   - The sound comes back as soon as the programme does.
   - When the detector is unsure, or any part of it is down, the sound stays on. Master's
     mute holds only while the detector keeps renewing it.
5. **Fill the break.** Master fades the sound out. It can play Cairo Radio under the break,
   or the station's own ads with the muted programme small in a corner, and its promos.
6. **Learn.** Each confirmed break adds its ads to the known-ads database. The operator's
   one-key fixes ("it's an ad", "it's the show") become training labels.

> **The source Roku moved to TV Thing on 2026-10-06.** TV Thing's *Roku lane* now owns the
> Roku (10.0.0.240) and its Hauppauge HD PVR: the YouTube TV, MLB, Thursday Night Football and
> Sunday Ticket navigation and screen recognition described below (now TV Thing's
> `roku_control/` package), the capture (the HD PVR's own H.264 copied to
> `/tv/stream/roku.m3u8`), its calibration (`/tv/roku.html`), recording, and a Manual Roku
> remote (the Roku tab of `/tv/`). The Roku has its own lock there, separate from the tuners.
>
> VizelVision asks TV Thing for a channel or game under that lock
> (`roku_stream/tv_roku.py`) and plays the lane's feed like a tuner's
> (`tv_control.RokuLease`): a navigation, the remote or a capture restart changes the lane's
> generation and fails the feed closed, and TV Thing reuses a recent verification, or
> checks that the Roku still plays, before it navigates again. The lock is held while a
> Roku feed is prepared or on air and kept across a web restart, which no longer drops it.
> YouTube TV's channels come from TV Thing's catalog when `config.master.json` has no
> `channels`. The controller routes below (`/v1/play`, `/v1/baseball/play`,
> `/v1/sunday-ticket/*`, `/v1/thursday-night-football/play`, `/v1/calibrate*`, `/v1/verify`,
> `/v1/preview`, `/v1/roku/signal|sources|capture|calibration`, `/v1/state`) answer **410**
> and point at TV Thing; `/v1/roku/status` and `/v1/operation` relay TV Thing's Roku lane.
> The CLI keeps `serve`, the `master-*` commands and `roku-status`. MediaMTX no longer has a
> `roku` path. See TV Thing's `API.md` ("The Roku lane").

**The web UI** ([docs/web-ui.md](docs/web-ui.md)) is a control room in six areas:
**On Air** (`/air`, the home: master's output, its monitor and Up next), **Sources** (every
channel, game and recording, with Play now, + Queue and Schedule), **Schedule**, **Crawl**
(every item the crawl can air, alerts first, with its first airing, repeats and next
airing), **Presentation** (the off-air card, the clock, continuity, the station ID, the
sonic identity) and **Engineering** (health, the viewer monitor, Roku capture and
calibration, how it works, an API explorer). Ctrl/⌘-K opens a command palette; **m** shows
the machinery, live diagrams of how each part works.

**Presentation → Live captions** adds optional local Whisper transcription to the
shared broadcast. Captions start off and can be switched on without restarting
master after deployment. See [live captions](docs/live-captions.md) for setup,
model choices, latency and status.

The [TV-Thing source integration](docs/source-implementation-status.md) adds an
optional multi-source guide at `/sources`. The [publication workflow](docs/publication-workflow.md)
now verifies GStreamer switching through a private MediaMTX server with independent
RTSP and HLS readers. See those documents for setup, validation, and remaining
work on the live master output. The [persistent master worker](docs/master-worker.md)
now adds TV-Thing prepare/take controls, tuner leases, fallback, publisher
recovery, and a browser master monitor. Its candidate setup is ready for local testing.
The [media library](docs/media-library.md) plays finished TV-Thing recordings
(and any other configured folders) to master through the queue, to play now or back to back.
Shows from Jellyfin can play with [ad breaks spliced in](docs/media-library.md#ad-breaks-for-shows-october-20):
a scan finds where each episode faded to black for its commercials, and My ads fill them.
Up next is the only way on air from the page: + Queue, then **Now** or a release time.
A 30-second [station ID](docs/station-id.md) plays between programs, and a
[continuity announcer](docs/continuity.md) can voice it: what just played, what is next.
Presentation holds the off-air and Cairo radio settings, continuity and the
[sonic identity](docs/sonic-identity.md) (`/sonic`); the [crawl](docs/crawl.md) (severe weather,
an override, and pop-up transit, alerts, weather and scores) has its own page, and the viewer
monitor is under Engineering.
Run `./deploy/install-master-stack.sh` to install and start all three processes
under `vizelvision-stack.target`, with automatic startup and process restarts.

This service turns a Roku return feed into a timer-driven local source. It
exposes an HTTP endpoint such as `play ESPN`, drives YouTube TV or MLB over
Roku ECP, reads the Roku’s USB video capture directly through V4L2, and
refuses to select a guide row or baseball game unless the visible UI agrees.

No cloud model, browser session, or YouTube account token is used at runtime.
Thursday Night Football reads structured event metadata from Prime Video's public
pages; other Roku navigation uses local observations. The Roku control path uses Python's standard library; the optional
master worker uses the system GStreamer Python bindings. The
lightweight local Tesseract executable reads ordinary UI text for diagnostics;
small stylized station marks use deterministic calibrated image templates
because OCR cannot reliably distinguish logos such as ESPN and ESPN2 at 480i.

## Verified hardware path

- Source Roku: `http://10.0.0.240:8060`, Streaming Stick 4K 3820R2, Roku OS 15.3.4
  (the `roku.url` in `config.json` and `config.master.json`)
- Viewer Roku: `http://10.0.0.111:8060`, Express+ 3710X, Roku OS 15.3.4; it runs
  the [master viewer app](#roku-master-viewer), with optional production monitoring and recovery
- YouTube TV Roku app: ID `195316`
- MLB Roku app: ID `14`, version `9.2.2`
- Roku video: Hauppauge HD PVR, component input 0, 1280×720 progressive at 60 fps
- Stable capture path: `/dev/v4l/by-id/usb-AMBA_Hauppauge_HD_PVR_00A4E5AC-video-index0`
- TV Thing runs independently; it is not used for Roku preview or verification
- Calibrated YouTube TV profile: Vivian
- Calibrated Washington, DC guide rows: NBC4/WRC, FOX 5/WTTG, ABC 7/WJLA,
  WUSA 9/CBS, WHUT/PBS, and DCW 50/WDCW
- Calibrated sports guide rows: ESPN, ESPN2, FS1, FS2, NBC Sports Network,
  Big Ten Network, NFL Network, TBS, TNT, SEC Network, ACC Network, ESPNU,
  ESPNEWS, NBA TV, CBS Sports Network, T2, Golf Channel, and Pickleball TV
- Calibrated network pages for every configured row. ESPN2, SEC Network, ACC
  Network, ESPNU, and ESPNEWS share the observed ESPN page; FS2 shares FS1's
  page.

The primary calibration directory is `state/templates-720p`, covering all 24
configured guide rows. Earlier RF/Dazzle templates remain in `state/templates`.
720p wordmarks require strong shape agreement and separation from competitors.
PBS additionally requires WHUT (DC) or WKAR (Lansing) in the selected program's
station metadata;
Big Ten requires BTN and rejects Overflow. Guide focus follows the highlighted
row when wrapped program headers shift the grid. Entry observes optional
promotional shelves and the sort toolbar before accepting a guide row.
With fresh capture enabled, positioning checks each row for the requested
channel instead of scrolling blindly to its saved index. This prevents lineup
changes from skipping a channel that has moved earlier in the guide; final
channel and playback verification still run before a cue succeeds.
`POST /v1/calibrate-current-network` with `{"channel":"NBC"}` verifies the
currently selected guide row, opens its station page through a verified focus
border, saves the page calibration, and verifies the return to the guide.

The September 9, 2026 [720p validation report](state/720p-validation/report.md)
records five successful live switches, API concurrency checks, and the final
browser preview. Calibration data and validation artifacts are local under
`state/`; preserve them when moving this installation.

The host's wired interface is named `eno1` and has `10.0.0.98/24`; both Rokus are
on that LAN over Wi-Fi. On the source Roku, **Settings > System > Advanced system settings >
Control by mobile apps** must remain set to **Enabled**.

## How a play request works

1. Check Roku ECP mode, installed app ID, and the configured local capture device.
2. Detect the current state as Roku Home/city, YouTube TV profile chooser,
   YouTube TV Home, location verification, Live guide, fullscreen program,
   channel description, or unknown. Roku ECP identifies the active app and
   player state; the selected return feed identifies the in-app surface.
3. Take the bounded action for that state: launch YouTube TV, select the
   verified far-left Vivian profile, confirm a visibly selected location
   verification request, enter Live, return from fullscreen or a description
   with Back, or recover a repeatedly unknown screen through Roku Home. Every
   transition is observed again before another action is sent.
4. If the Live guide is already open, identify its current calibrated row and
   move up or down relative to it. If the row is an unconfigured gap, anchor at
   the top of the Custom guide first.
5. Scan in the expected direction one row at a time. Raw V4L2 observations
   open a new stream and discard its first two frames. Hauppauge MPEG-TS
   capture stays open and waits for three newly decoded frames per observation.
   Both check device identity before and after capture. No HLS buffer is used.
   Only strongly recognized, unique rows can reverse the scan direction;
   unfamiliar rows such as temporary Sunday Ticket entries cannot act as anchors.
6. Compare the exact guide-row logo with all calibrated competitors. The local
   matcher combines contrast-normalized pixel distance with wordmark-shape
   correlation and can retain multiple analog blur variants. Two distinct fresh
   frames with strong logo separation and confirmed current-program focus can
   proceed directly to playback. Ambiguous affiliate logos cannot use this route.
7. Otherwise, visibly confirm the station tile's focus rectangle before opening
   its page. Compare the page's fixed network mark with a separate template and record
   local OCR output as supporting evidence. Channels that legitimately share a
   page are explicitly mapped while their guide-row templates remain distinct.
8. When a page was opened, return to the guide, restore program focus, and
   verify the exact row again.
9. Press OK and wait until Roku ECP reports YouTube TV media state `play`,
   while checking the return for recognized menus. This confirms player state
   after a verified selection; it does not independently identify the station
   in the playing video.

The direct backend supplies fresh observations from one continuously drained
capture stream. With `feedback.network_page_fallback` enabled, two distinct
strong guide observations can select directly; ambiguous stations still use
channel-page verification. Freshness measures new decoded frames after a
request barrier, not end-to-end hardware latency.

This boundary is intentional. Roku ECP can launch an app, send remote keys, and
report player state, but it cannot report YouTube TV's focused guide row.
YouTube TV also does not publish a network-level Roku deep-link contract.
The component capture supplies the actual Roku picture for verification.

## Baseball routing

The Cue Sheet's **Baseball** tab loads the selected day's games from MLB's
public Stats API and presents one provider-neutral schedule. A click chooses
the first source that can be controlled here:

1. A configured national YouTube TV channel such as ESPN, ESPN2, TBS, FOX,
   FS1, or ABC is preferred for a live national telecast.
2. Otherwise, an MLB.TV broadcast marked streamable by the schedule is opened
   in the signed-in MLB Roku app. Account-specific blackouts and entitlements
   are still verified in the app and fail safely.
3. Finished games prefer MLB when a replay is available. Older dates currently
   fail before navigation because the app's archive date selection is not
   verified; matching team names alone cannot distinguish games in a series.

The MLB app does not accept its Stats API `gamePk` or broadcast `mediaId` as a
working Roku deep link, so game selection uses the UI. The controller models
the white cursor in both the three-column Games grid and Home's three-card
Today’s Lineup carousel, OCRs only the selected card, and requires both teams
in two fresh observations before Select. Live requests also require a visible
LIVE badge in both observations; its red background provides evidence when
the tiny label cannot be read. Still-live games use Today’s Lineup even after
midnight changes the controller's date. The carousel is scanned one observed
card at a time, reversing at its boundary. Loading screens cause a wait.

After a verified game opens, the controller recognizes the video/audio feed
picker using its outlined video/audio buttons and selected row, accepts its focused
video feed, and handles MLB's separate **Catch Up /
Watch Live / Start From Beginning** prompt. Because Catch Up is initially
focused, it moves to and visibly confirms Watch Live before pressing Select.
Feed recognition supports both the composite and HD capture layouts, including
the Tigers' two video feeds and three audio feeds. Each layout requires visible
button outlines and an unambiguous highlighted feed before selection.
On re-entry, MLB may add a Resume row; that four-choice layout is recognized
and Resume is skipped when cueing live.
Visible menus take priority over stale Roku `play` metadata throughout.
Playback requires a verified feed or Watch Live action followed by two
consecutive fullscreen/player observations. Explicit audio-only playback is
rejected. Select is not repeated while an already-confirmed dialog closes.
The player still does not independently identify the game: identity comes
from the selected card and the observed transitions into video.

## Master source queue

**Thursday Night Football** is available as a Roku source and the suggested
source for NFL games listed on Prime Video. The Sports view and Schedule use
the ESPN game ID and Eastern game date; Up next retains the NFL end-of-game
gate and backup behavior. Prime's public NFL catalog resolves the event's
Amazon content ID at preparation time, checking both teams, its date, and
live status. It does not use last week's ID or open a replay when a broadcast
has ended. See [Prime Video integration](docs/thursday-night-football.md).

**NHL on ESPN Unlimited** (`nhl`) is the suggested source for NHL games whose only
national broadcast is ESPN+: out-of-market games and ESPN+ exclusives, streamed inside
YouTube TV. TV Thing finds the game on YouTube TV's ESPN page and never selects a
blacked-out stream. A blackout is shown in TV Thing's words and is not retried. See
[NHL on ESPN Unlimited](docs/nhl.md).

The deployed master service at `http://viviserv/vizelvision/` (On Air) has a mixed-source **Up next** queue. Digital/analog TV-Thing, YouTube TV, MLB and Thursday Night Football targets prepare and take to the continuous master stream. Pause/resume, missed/failed entry recovery, and source/program snapshots are on On Air (and, compact, beside Sources). **Set end time** on a live take asks for an end: :30 or the top of the hour, the TV-Thing program's listed end, the game's end, or a custom time. At that time the schedule takes master back. Legacy schedules use the same queue when master is enabled. Every service restart pauses automation for review. See [the source queue workflow](docs/source-queue.md).

## Programming schedule

`/schedule` is a weekly programming grid modeled on Cairo Radio's scheduler
(clocks painted onto a 7×24 grid, shows and calendar events that override it).
It is available with master enabled.

- **Programming blocks** are named, colored sources, such as *Morning news →
  YouTube TV · NBC*. Paint them onto a Monday–Sunday grid of half-hour cells.
- **OFF AIR** fills every unpainted cell. The grid and the next-24-hours rundown show it
  explicitly, and an OFF AIR change returns master to the off-air test card (Presentation).
- **Scheduled shows** are one-off, dated windows that override the grid, such as
  election coverage on a given evening. Shows and games may overlap but not start
  at the same time; a later one takes over from its start, and a game is never cut
  before its final ([details](docs/source-queue.md#games-and-recordings-september-30)).
- **Sports game mode** schedules an MLB, NFL, NBA, NHL, WNBA or NWSL game (picked from the day's
  schedule) with a reserved window, the source carrying it, and a **backup
  program**. The source can be any YouTube TV channel or over-the-air TV-Thing
  station; MLB can also use automatic routing. The page suggests a configured
  channel from the game's national broadcast. Sunday-afternoon NFL games on
  CBS/FOX are regional: a Washington or Baltimore game is suggested on WUSA or
  FOX 5, and other games on **NFL Sunday Ticket** (below). End-of-game status comes from the MLB
  Stats API, and from ESPN's public scoreboard for the other leagues (postponed or
  cancelled games also count as ended). The Sports view lists the NFL by week and the other
  leagues for the next ten days. When the game is final, the backup airs until the window ends. A game that runs past its window
  stays on air: later changes wait behind it, and the backup is skipped as
  superseded when the game finally ends. The backup can also be OFF AIR, or
  **Return to schedule** (the default): whatever the weekly grid and program shows
  have when the game goes final, unless a game already under way or recordings
  waiting in Up next come first (they play until the next live show starts). Up
  next shows the live score. Games are priority 2 and preempt the grid (priority 3).
- **NFL schedule** lists a whole week from ESPN's scoreboard
  (`GET /v1/sports/week?league=nfl[&seasontype=2&week=5]`, with the season's
  week calendar). **+ Add** schedules a game on its suggested channel with a
  3 h 45 min window that returns to the schedule; **Customize** opens the game
  form prefilled.
- **MLB** (the same section's MLB tab) lists the next 10 days from the MLB Stats
  API (`GET /v1/sports/upcoming?league=mlb&days=10`) with postseason series,
  game number, *if necessary* and TBD start times. Each game suggests the
  YouTube TV channel carrying it: shared listings such as "NBC/Peacock",
  "Peacock/NBCSN" or "FOX / FS1" are split and matched exactly to configured
  channels. With no configured channel, automatic routing uses MLB.TV. **+ Add**
  reserves 4 h; TBD games need **Customize** until MLB sets a time.
- **Up next** on On Air lists scheduled games and shows before they
  are queued, with their channel and what follows them.
- **This week** labels the grid's columns with this week's dates and draws *what
  will air* over the painted template (untick **Show what will air** to paint
  without it). The projection plays Up next and the schedule forward under the
  queue's rules. A game holds master until its estimated final: from the live
  inning or quarter, else a typical length from its start. Then a game under way,
  Up next recordings (with their file lengths) or the schedule follows. A live show
  cuts in on time, and OFF AIR gives way to recordings. Games, scheduled shows,
  Up next recordings, entries queued by hand, and blocks joined late are drawn;
  blocks airing as painted are not. **As it will air · next 24 hours** and the *On
  now* / *Next* cards use the same projection. It is an estimate: preparation
  time, station IDs, failures and a paused queue are not modelled.

Precedence is scheduled show > grid block > OFF AIR. The schedule does not cut
master directly. About ten minutes before each change it inserts an entry into
the master **Up next** queue in time order. The entry is labeled *Schedule ·
title*. Pause, Retry/Skip and the startup review therefore apply unchanged.
Adjacent segments on the same source produce no cut. A waiting entry whose slot
has ended is skipped as *superseded* instead of airing briefly. This happens
even while the queue is paused, so ended slots do not pile up in Up next.
Editing or stopping the schedule withdraws its waiting entries. Blocked entries
stay for the operator. Up next also shows the **Next scheduled** change that has not been queued yet,
OFF AIR included.

**Roku preparation.** Every timed queue entry for a Roku source (YouTube TV or
MLB), scheduled or manual, starts preparing five minutes before its release.
The early preparation navigates and verifies the Roku while the current
program stays on air; the release then takes the already-verified selection
without navigating again, so the cut lands on time. The Roku is one device, so
an entry cannot prepare early while the Roku itself is on air. It checks again
every 20 seconds and otherwise prepares at release, as before. A failed early
preparation retries every 20 seconds until release. At release, a failed Roku
preparation (nothing has been cut yet) is retried twice, 20 seconds apart,
before the entry blocks for Retry or Skip. Take failures are not retried
automatically.

Turning the schedule on queues only future changes. **Queue what's on now**
queues the current block to release in two seconds. Use it after enabling the
schedule or after a service restart. The queue still starts paused after every
restart, so resume it on On Air. Grid times use the server's local
time zone. State is stored in `state/programming.json`.

API: `GET /v1/programming` returns settings, `on_now`, a 24-hour `timeline` with
OFF AIR segments, and upcoming queue changes. `POST /v1/programming` saves
`{enabled, blocks, grid}`. `POST /v1/programming/shows` adds `{mode: "program",
title, target, start, end}` or `{mode: "game", game: {league, game_pk, game_date},
target, backup, backup_title, start, end}` (`league` is `mlb`, `nfl` or `nba`;
`target` is optional only for MLB). `GET /v1/sports/games?league=nfl&date=YYYY-MM-DD`
lists games with `game_id`, networks and a `suggested_target`. `DELETE /v1/programming/shows/<id>` removes a
show. `POST /v1/programming/take-current` queues the current segment.
`GET /v1/playback[?until=ISO]` returns the projection (default 24 h, up to 8 days):
`segments` of `{start, end, title, kind, target, game, estimated, notes, item}`, where
`kind` is `game`, `block`, `show`, `backup`, `off_air`, `recording`, `manual` or `ident`, and
`item` is the Up next entry it airs from (null for the schedule's own). `dropped` lists what
never airs, as `{item, key, title, kind, target, due, why}` (a slot that ends while a game
runs on, OFF AIR giving way, an entry outranked). A live channel queued to fill time stays
on until the next timed entry, or until the end it was given. The OFF AIR target is
`{"source_id": "off-air", "channel_id": "off-air"}`.

## NFL Sunday Ticket

YouTube TV lists each Sunday Ticket game as its own temporary guide row, days
ahead, all with the same Sunday Ticket logo and the matchup as the program
title ("Upcoming: Los Angeles Chargers at Buffalo Bills"). The source
`sunday-ticket` (channel_id = ESPN NFL game id, plus `date`) finds that row by
reading the guide:

1. Open the Live guide and verify the top configured row (NBC), as for any channel.
2. Press Down one row at a time. Each row's large header title and focused
   program text are read with local OCR, and the row's logo is compared with
   the calibrated Sunday Ticket logo (`state/templates-720p/sunday-ticket.json`).
3. Accept a row only when it is not a calibrated channel, carries the Sunday
   Ticket logo (or the header's "NFL ST"), and names both teams, in two fresh
   observations. A FOX row showing the same matchup is never used.
4. Refuse to select a game that is still "Upcoming". Queue entries keep
   retrying (up to 10 attempts, 20 s apart) until the feed goes live.

The scan stops after leaving the Sunday Ticket block or after every configured
row plus 40. On September 23 the Chargers-at-Bills row was found 6 rows below
NBC in 55 seconds. The logo was calibrated from that row.

`POST /v1/sunday-ticket/find {"game_id": 401872953, "date": "2026-09-27"}`
navigates to and verifies the row without selecting it (dry run).
`/v1/sunday-ticket/play` selects it. `/v1/sunday-ticket/calibrate` re-saves the
logo from the focused row after it verifies as that game. In the schedule's
sports mode, choose *NFL Sunday Ticket · this game* as the source.

## Station clock

Presentation → **Station clock** overlays the time in the top-right corner of master
output in Japanese broadcast style: bold white 24-hour numerals without a
leading zero (7:05) and a dark outline, with no box. Seconds are optional. The
clock covers everything on master, including the off-air card. It uses the
master worker's local time and is applied within one second of saving, without
a cut. It is off by default. Saved production settings from before this option
remain valid.

## Crawl and EAS alerts

The **Crawl** page runs a bar of scrolling text along the bottom of master
output, over everything on air. Severe weather (EAS warnings for DC from the decoder on
this server, NWS Severe/Extreme alerts) and the one manual **important message** run
continuously; a manual **override** holds the bar when needed. Otherwise a rotation pops
up one segment at a time and slides away: weather alerts, Metro and bus (WMATA), AlertDC,
weather, scores for the **teams you follow**, coming up, Cairo Radio (under the off-air
card), and station messages on their own schedules. Each context has its rule: pop-ups
during programs, important only during live games and the ID, always on over the off-air
card. The page lists every item with its status: on air, first airing or repeat, and when it
airs next (or why it is held). See [the crawl](docs/crawl.md).

## Viewer monitor

Engineering → **Viewer monitor** (**Viewer Roku · cable return**) configures the viewer Roku address,
VizelVision app ID, cable channel, automatic checks, and interval. The confirmed
viewer is **10.0.0.111 (Express+ 3710X)**, app **dev**, on **cable 70**. This is
separate from the source Roku at `10.0.0.240`. The installed monitor checks every
**6 hours**; new installations default to disabled until enabled on this page.
The scheduler lives in the web service and runs while the browser is closed.

Each check reads TV-Thing's current lock status, acquires its own short analog
lease without override, and checks the installed app, active app, and media
player through Roku ECP. If VizelVision is missing from the foreground or not
playing after a short settling period, it sends **one** `POST /launch/<app_id>`
and verifies playback again. Unreachable devices, an incorrect app ID, or an
inconclusive cable image do not trigger blind launch retries.

Checks defer 15 minutes while **any TV-Thing lock** is held, during recording or
scanning, or while another cable channel is active. Acquisition races fail
closed. There is no lock override option, including for manual checks. A check
leases cable 70 long enough to sample the cable return and master concurrently
for 30 seconds and saves a return image; it stops only a temporary stream it
created while still owning the lease, then releases its own token. Existing streams on the same channel are
left running. Digital viewing is not retuned or stopped.

The page shows the last result, next check, device identity, app/player details,
recovery attempt, cable image, cleanup errors, and the last 20 checks. **Check
now / recover** runs asynchronously with the saved settings, even if periodic
checks are disabled. Save schedules an immediate check when enabled. Settings,
results, and the next deadline persist in `production-monitor.json` beside the
master socket, so a web restart preserves the schedule. Normal checks and
failed recovery attempts wait the configured interval; deferred checks retry
after 15 minutes.

Healthy/recovered requires Roku playback **and a picture match to the configured
master HLS output**. The comparison uses coarse picture structure, allows up to
20 seconds of cable delay, and checks at least 10 seconds of aligned samples,
including the newest cable frames.
It tolerates analog noise, brightness differences, letterboxing, and modest
overscan. A held picture cannot pass against a visibly changing master; a still
image that matches still programming can pass. Static, blank video, and wrong
programming do not pass just because frames decode. A mismatch is unhealthy;
a missing reference is inconclusive. Diagnostics include similarity, matched
sample counts, alignment offset, and motion consistency. Offsets beyond the
window or severe distortion can produce a mismatch and need inspection.

Cable picture mismatches do not trigger blind relaunches. The check does not
prove a physical television's power/input state. A saved latest result that
lacks a master comparison is shown as inconclusive until a new check runs.

Authenticated API endpoints (using the existing API key when configured):

- `GET /v1/production/monitor` — settings, results, history, next deadline.
- `POST /v1/production/monitor` — full settings object, for example
  `{"enabled":true,"roku_ip":"10.0.0.111","cable_channel":70,"app_id":"dev","interval_hours":6}`.
- `POST /v1/production/monitor/check {}` — queue one check and recovery if needed;
  returns 202, or 409 if one is already pending/running. Poll the GET endpoint.

## Roku master viewer

`roku_app/` is a minimal Roku channel that launches straight into the master
feed at `http://10.0.0.98:6970/v1/master/media/index.m3u8`. It retries every
3 seconds if the feed is unavailable; OK or Play rejoins the live edge. Run
`roku_app/package.sh` and sideload `roku_app/vizelvision.zip` through the viewer
Roku's Development Application Installer. Edit the URL in
`roku_app/source/main.brs` if the host address changes. If `server.api_key` is
set, the app cannot fetch the feed until it sends the key.

MediaMTX labels its playlists HLS version 10, which Roku rejects as
"HLS playlist unsupported version". The `/v1/master/media/` proxy rewrites that
tag to version 7, which covers the non-low-latency fMP4 playlists it serves.
Reading MediaMTX's port directly will not work on Roku.

The section below describes the original Roku-only mode with master disabled and its separate state directory.

## Ordered playout queue

The **Up next** panel is a persistent ordered queue, not another scheduler.
Choose a YouTube TV channel and one release rule:

- **After game** binds the item to the exact `gamePk` of the last successfully
  verified baseball cue. The queue polls MLB status and releases the head item
  when the game becomes Final (or another terminal status such as Game Over,
  Completed Early, cancelled, or postponed).
- **At time** releases the item after the chosen timezone-aware timestamp.

Only the head item is evaluated, so later entries never jump the line when
their time arrives. Waiting entries can be moved up, moved down, or removed.
Running and completed entries cannot be reordered. Queue state survives service
restarts in `state/queue.json`; a formerly running entry is safely returned to
the front of the queue after a restart.

YouTube TV itself does not expose a documented subscriber Live-guide API. The
YouTube Live Streaming API is for creators managing broadcasts on their own
YouTube channels, not YouTube TV listings. Full network schedules would require
a separate EPG provider such as Gracenote On API or TV Media; the queue does not
scrape the YouTube TV UI for future airtimes.

Since October 18 TV-Thing reads those listings from the web itself (Gracenote's
station schedules, two days ahead, no tuner) and serves them in its guide as
`youtube-tv/NAME` rows. Since October 20 the Sources page shows them for YouTube
TV's channels (Now, Next, Later), a program there can be scheduled, and Play now
can end with it ("until SportsCenter ends").

## Run it

Install the local OCR executable once:

```bash
sudo apt install -y tesseract-ocr
tesseract --version
```

The controller prefers `/usr/bin/tesseract`. A rootless copy under
`vendor/tesseract/` is also detected as a fallback but is ignored by source
control. The checked-in `config.json` contains the verified device addresses and
timing:

```bash
python3 -m unittest discover -s tests -v
python3 -m roku_stream --config config.json status
python3 -m roku_stream --config config.json state
python3 -m roku_stream --config config.json plan ESPN
python3 -m roku_stream --config config.json play ESPN
python3 -m roku_stream --config config.json serve
```

The checked-in machine configuration listens on all local interfaces at port
`6969`, so another device on the LAN can open `http://10.0.0.98:6969/`. The
example configuration remains localhost-only. This installation has no API key,
so restrict port 6969 to trusted local networks at the host/router firewall.

Open `http://127.0.0.1:6969/` in a browser for the **VizelVision Cue Sheet**.
It loads the calibrated channel catalog from the API, groups Washington locals and
sports feeds, displays a two-frame-per-second selected-source monitor and
Roku readiness, and includes a date-selectable Baseball schedule. It disables
all cue buttons while a verified switch is running and reports the currently
detected app state and navigation phase. The monitor pauses during a switch so
it cannot compete with safety verification captures. The completed source is
marked as the last cued feed for that browser tab. The JSON health check remains
at `GET /health`.

The page follows the server's active cue after a reload, including cues started
from another browser or the queue. **Stop cue** cancels navigation after the
current device request; it does not stop whatever program is already playing.
Channels and Baseball tabs support arrow keys and remember the selected tab.

## Persistent service and Apache proxy

This machine runs VizelVision as the enabled `vivian` user service
`vizelvision.service`. User lingering is enabled, so systemd starts it during
boot without waiting for Vivian to log in. Useful commands are:

```bash
systemctl --user status vizelvision.service
systemctl --user restart vizelvision.service
journalctl --user -u vizelvision.service -f
```

To reinstall or update the user service after changing its unit file, run:

```bash
./deploy/install-user-service.sh
```

Apache needs one root-authorized installation step. Run this from the project
directory and enter the local sudo password when prompted:

```bash
./deploy/install-apache-proxy.sh
```

That enables the required Apache proxy modules, checks the Apache
configuration, and exposes the UI at `http://viviserv/vizelvision/` (or
`http://10.0.0.98/vizelvision/`). The redirect from `/vizelvision` to
`/vizelvision/` is intentional: UI assets, preview frames, and API requests use
relative URLs so the same build works directly on port 6969 and under the
Apache path prefix.

For a new installation, `./deploy/install-vizelvision.sh` performs both steps.
An alternative root-owned system service template remains in
`roku-stream.service.example`.

## API

Start a channel cue and receive HTTP 202 immediately (used by the Cue Sheet):

```bash
curl -sS -X POST http://127.0.0.1:6969/v1/play \
  -H 'Content-Type: application/json' \
  -d '{"channel":"ESPN","wait":false}'
```

The response contains `operation_id`, a relative `status_url`, and the accepted
operation. Poll `GET /v1/operations/<operation_id>` for `active`, `phase`,
`error`, and the final `result`. Admission reserves the controller immediately;
overlapping cues receive HTTP 409. `GET /v1/operation` remains the current cue
summary. Historical completion is labeled as the last cue, not current playback.
`POST /v1/operations/<operation_id>/cancel` stops only that cue; a stale ID
cannot cancel a newer operation. The browser retains its pending ID on reload.
`GET /v1/roku/status` includes freshly queried player metadata and `observed_at`;
`current_channel` is null because ECP does not establish station identity.

The latest 100 channel and baseball operations are retained under `state/operations/`:
JSON status/result, timestamped JSONL events, and the last observed PPM frame
on failure or cancellation. Unfinished operations are marked interrupted when
the service restarts; navigation is not automatically replayed.

Play immediately (the response is returned after visual and player checks):

```bash
curl -sS -X POST http://127.0.0.1:6969/v1/play \
  -H 'Content-Type: application/json' \
  -d '{"channel":"ESPN"}'
```

Inspect the exact plan without touching the Roku:

```bash
curl -sS -X POST http://127.0.0.1:6969/v1/play \
  -H 'Content-Type: application/json' \
  -d '{"channel":"ESPN","dry_run":true}'
```

Load a baseball date and cue a game through its automatically selected source:

```bash
curl -sS 'http://127.0.0.1:6969/v1/baseball/games?date=2026-09-07'
curl -sS -X POST http://127.0.0.1:6969/v1/baseball/play \
  -H 'Content-Type: application/json' \
  -d '{"game_pk":823254,"date":"2026-09-07","wait":false}'
```

Use a game ID and date from the current schedule. Baseball supports the same
operation polling and scoped cancellation as channel cues. The browser uses
`wait: false`; omitting it preserves the synchronous response.

Queue ESPN after the currently confirmed baseball game, or queue TBS for an
absolute time:

```bash
curl -sS -X POST http://127.0.0.1:6969/v1/queue \
  -H 'Content-Type: application/json' \
  -d '{"channel":"ESPN","release_type":"after_game"}'

curl -sS -X POST http://127.0.0.1:6969/v1/queue \
  -H 'Content-Type: application/json' \
  -d '{"channel":"TBS","release_type":"at_time","run_at":"2026-09-02T22:30:00-04:00"}'
```

Read the queue with `GET /v1/queue`, reorder an item with
`POST /v1/queue/<id>/move` and `{"direction":"up"}`, or remove a waiting item
with `DELETE /v1/queue/<id>`.

Schedule a switch. Timestamps must include an offset; jobs are persisted in
`state/jobs.json` and survive service restarts:

```bash
curl -sS -X POST http://127.0.0.1:6969/v1/schedules \
  -H 'Content-Type: application/json' \
  -d '{"channel":"ESPN","run_at":"2026-08-30T20:00:00-04:00"}'
```

Useful read-only routes are `GET /health`, `GET /v1/channels`, `GET /v1/state`,
`GET /v1/operation`, `GET /v1/roku/status`, `GET /v1/preview` (browser MJPEG),
`GET /v1/jobs`, and `GET /v1/jobs/<id>`. `GET /v1/operation` can be polled
during a cue without waiting for the controller lock and reports its detected
state, phase, and operator-facing message. `GET /v1/state` reports `roku_home`,
`youtube_tv_user_select`, `youtube_tv_home`,
`youtube_tv_location_verification`, `live_guide`, `full_program`,
`channel_description`, `join_live_or_start_from_beginning`, the MLB Home/grid/
loading/feed-picker/entitlement/error states, or `unknown`. YouTube TV's
selected location-verification and Join live choices are confirmed directly;
MLB's live-choice prompt is first moved to Watch Live, past Resume when present. Cancel a queued job
with `DELETE /v1/jobs/<id>`.

Configured channel names and useful aliases include:

| Group | API names and aliases |
| --- | --- |
| Washington, DC locals | `NBC` (`WRC`, `NBC4`), `FOX` (`WTTG`, `FOX 5`), `ABC` (`WJLA`, `ABC 7`), `CBS` (`WUSA`, `WUSA 9`), `PBS` (`WHUT`), `The CW` (`WDCW`, `DCW 50`) |
| National sports | `ESPN`, `ESPN2`, `FS1`, `FS2`, `NBC Sports Network`, `Big Ten Network` (`BTN`), `NFL Network`, `TBS`, `TNT` |
| Extended sports | `SEC Network` (`SECN`), `ACC Network` (`ACCN`), `ESPNU`, `ESPNEWS` (`ESPN News`), `NBA TV`, `CBS Sports Network` (`CBSSN`), `T2`, `Golf Channel`, `Pickleball TV` |

## Add another YouTube TV channel

1. Keep YouTube TV's Live guide on its Custom ordering. Add the channel to
   `config.json` with its zero-based `guide_index` and any aliases.
2. With the physical remote, highlight that channel's currently airing program
   in the main Live guide; do not open it.
3. Save and verify its local logo template. Repeating this command with a
   visibly verified row preserves a distinct analog observation as a variant:

   ```bash
   python3 -m roku_stream --config config.json calibrate "ESPN2"
   ```

4. Let the guarded calibrator verify the row, find the network tile, open and
   calibrate the page, then return to and re-verify the guide row:

   ```bash
   python3 -m roku_stream --config config.json calibrate-current-network "ESPN2"
   ```

   When multiple linear channels share one page, add a mapping such as
   `"network_page": "ESPN"`; ESPN2 uses that mapping in the checked-in config.
5. Run `plan`, then `play`. `GET /v1/channels` reports both guide-row and
   network-page calibration status.

A guide template can also be created without controlling the Roku from a raw
PPM frame already captured from the selected return feed:

```bash
python3 -m roku_stream --config config.json \
  calibrate-guide-frame "ESPN2" /path/to/observed-guide-frame.ppm
```

To check a highlighted row without changing it, run
`python3 -m roku_stream --config config.json verify ESPN` or POST the same
channel to `/v1/verify`.

If the Custom guide is reordered, update the indices. Existing visual templates
remain useful: a stale index produces a safe error instead of airing the wrong
station. Recalibrate only if the network logo or YouTube TV guide rendering
changes. Templates and scheduled jobs live under ignored `state/`; include that
directory in machine backups.

The Vivian profile safety template can be deliberately replaced only while the
correct first profile is visibly highlighted:

```bash
python3 -m roku_stream --config config.json calibrate-profile
```

## Operational notes

- **Calibration:** open `/calibration` from the shared navigation (direct URL:
  `http://viviserv:6970/calibration`). It reads `/v1/roku/calibration` every 500 ms
  after each completed request, with no overlapping browser polls. Timing queries
  have a two-second deadline and a shared 250 ms cache. It shows detected input
  resolution, scan and frame/field rate, USB identity/driver attachment, capture
  path/access, and shared decoder status. Unknown or stale readings cannot confirm
  the target. 720p60 requires 1280×720 progressive at 59.94 or 60 frames/s.
  The resolution-button watch records a **physical** button press, waits an
  adjustable 10–600 seconds (60 initially), then requires ten seconds of fresh
  matching readings. The watch can be extended, survives reload, and syncs between
  tabs in the same browser; it does not send Roku commands. Polling continues after
  the watch. It never opens a competing capture reader. All diagnostic API reads
  require the normal API key when configured; the page shell is public.
  Missing USB, USB with an unbound driver, a missing device path, permission errors,
  and missing component signal are reported separately. If USB appears with no
  capture driver, restore the Hauppauge power/USB connection before adjusting
  resolution. Incoming timings use
  [VIDIOC_QUERY_DV_TIMINGS](https://www.kernel.org/doc/html/v4.12/media/uapi/v4l/vidioc-query-dv-timings.html),
  not the driver's saved output size or the master stream format.
- The current Hauppauge HD PVR component source uses `input_format: "mpegts"`,
  `input_index: 0`, and `video_standard: null`, with its stable USB device path.
  `source_name` sets the label shown in the UI. Encoded capture uses
  `/usr/bin/v4l2-ctl` to select the input and FFmpeg to decode the device's
  transport stream at its incoming resolution (currently 1280×720 progressive).
  The decoder starts on the first preview or observation and keeps the card
  awake until service shutdown, including between browser connections and cues.
  A background reader continuously drains frames and retains only the newest;
  each request waits for three subsequent frames. This avoids reusing a cached
  image but does not measure the encoder's hardware latency. A stalled or failed
  stream fails the observation and is restarted on the next request.
  The monitor's Input readout polls detected component timings every two seconds,
  including resolution, scan mode, and field/frame rate when reported. Missing
  signal is shown explicitly instead of displaying the driver's last saved size.
  A detected format change reopens the decoder on its next capture request.
- For legacy raw capture, `feedback.backend: "direct"` selects local V4L2. Set `device` to
  its stable `/dev/v4l/by-id/` path, `input_format` to `yuyv422`,
  `video_standard` to `NTSC-M`, and `input_index` to `0` for this Dazzle.
  Each raw V4L2 observation opens and closes FFmpeg within a configured deadline;
  cancellation kills and reaps the child. No persistent encoder is needed.
- Preview shares serialized capture access but cannot overwrite cue evidence.
  It stops when a cue starts. Another application cannot stream the same
  exclusive USB input concurrently; that condition fails the capture clearly.
- TV Thing can continue using its separate tuner. The controller neither
  reads its HTTP API nor retunes it when direct capture is configured.
- The older HTTP adapter remains available with `backend: "tv_thing"` and
  `base_url` for existing installations. Its source selection and HLS settings
  apply only to that backend. Direct mode ignores saved TV Thing selections.
- Dazzle must use **NTSC-M** for this Roku. Direct capture applies it when
  opening the input. Changing capture hardware can require recalibration.
- Immediate overlapping cues return HTTP 409 instead of accumulating hidden
  requests. Queue items wait and retry when the Roku is busy. Stop a running
  cue with `POST /v1/operation/cancel`.
- Before the September 7 refactor, an ESPN API run took 112.3 seconds; the row-32 CBSSN test took
  266.6 seconds. Most of that is deliberate waiting for this old Roku and the
  former HLS feedback. Direct capture removes that stream wait; Roku app
  launches and video startup still need suitable lead time.
- The incremental refactor and its real-device results are recorded in
  `state/channel-refactor-validation.md`. Temporary Sunday Ticket rows can
  shift guide positions; only confident unique logos can redirect a scan.
- The configured Custom guide list currently covers six controllable DC locals
  and all 18 observed sports-carrying or sports-dedicated rows. WHUT, MPT, and
  WETA PBS occupy consecutive rows and expose effectively identical PBS marks
  in the small guide-logo crop. The `PBS` button deliberately targets the first
  row, WHUT, and that logo is never trusted as a relative-position anchor.
  Indices intentionally contain gaps for MPT, WETA PBS, and other unconfigured
  stations.

## Protocol references

- [Roku External Control Protocol](https://developer.roku.com/dev/docs/external-control-api)
- [YouTube TV Live guide and customization](https://support.google.com/youtubetv/answer/7067974)
