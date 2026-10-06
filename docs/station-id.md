# Station ID

A 30-second, 1990s-style VizelVision network ID plays between programs on master.
DJ Low Tide (Deepgram Aura-2 Orpheus, the voice Cairo Radio uses for that host) does
the voice-over over a synthesized jingle.

## When it plays

- **A recording always plays to its very end.** The ID follows it, then whatever is next:
  the next file (which starts from its first frame as the ID ends), another queue entry, or
  the test card. The ID never replaces a recording's ending, where a show keeps its
  payoffs (Jeopardy!'s final scores). This has been the rule since 2 October 2026. Before
  then, a file with another entry waiting behind it lost its last 30 seconds to the ID.
- **A live program before an *At time* queue entry** (a schedule change, OFF AIR, the
  sign-off) loses its last 30 seconds to the ID, so the next program starts when it
  would have. A recording on air then keeps its ending if that ending comes within the
  ID's length. The ID follows it, and the timed entry takes when the ID ends, up to 30 s
  late. A recording that would still be playing at the entry's time is cut by the entry
  anyway, so the ID covers that cut.
- **A manual take held until an end time** gets the ID in its last 30 seconds.
- **A held game that goes final** stays on master **3 minutes** past the final
  (`FINAL_BUFFER_SECONDS` in `source_queue.py`), then the ID plays, then what follows. The
  feeds call a game final at the last out or whistle. The picture runs behind them, and the
  final score airs after that. A scheduled game's return to the schedule waits out the same
  buffer. While it waits, Up next reads *Final · … · on for the final score, N more min*.
- **No ID plays** when nothing is on air (test card), over the ID itself, when the next
  entry is what is already on air, or when a timed entry arrives with under 27 seconds
  to go. Only a whole ID plays. The exception is the [Sports ID](#vizelvision-sports),
  which opens a game from the test card too.
- **Before a sporting event**, the break says what is next, holds until the game is
  ready, then plays the VizelVision Sports ID ([below](#vizelvision-sports)).

Manual control always wins. A manual take, Prepare or fallback cuts the ID like any
other source. A queued take, and a scheduled OFF AIR, wait for the ID's last half
second: the ID ends in black and silence, so that cut is invisible.

## Covering a channel change

The ID covers the switch to the next program. When a queued program is still being
prepared while the ID plays (typically the Roku changing channel, as from one game to
the next, which can take longer than 30 seconds), the ID **holds its end card**: the
VizelVision lockup with *Stay tuned*, just before its iris closes (27.9 s). The picture
freezes on that frame with silence. Once the next source is verified, the iris closes,
and the cut lands on the ID's black tail as usual. A hold gives up after two minutes:
the iris closes and master falls back to the test card. A failed or cancelled
preparation, or pausing the queue, releases the hold the same way.

- The coordinator asks for the hold (`ident_hold` with `hold: true`) when it starts
  preparing a queue entry with the ID on air, and releases it just before the take or
  when the operation ends. An early Roku preparation that finishes seconds before its
  entry releases keeps the hold, and that entry's take releases it.
- When the ID cuts in 30 s before a timed entry, the source it replaced is free at once,
  so a Roku entry starts preparing then, under the ID, instead of at its next 20-second
  retry.
- The worker freezes the ID's file input at the end card (`FileInput.freeze`): the
  decoder pauses, and the last frame and silence keep arriving just ahead of the clock,
  so master never stalls. `thaw` resumes the file after the held frames. `GET
  /v1/master` shows `ident.held`.
- `tests/ident_hold_integration.py` (opt-in, real GStreamer and the real ID file, no
  encoder or publisher): the hold keeps both tracks fresh without advancing the file;
  the file then plays to its end; timestamps never go backwards.

While the ID is on air, master shows **Station ID** with its progress. A file cued to
follow it shows *Plays when the station ID ends*. Other entries prepare during the ID
and take when it ends. The previous source is released when the ID cuts in, so a
tuner or the Roku is free for the next program.

## How it works

The worker keeps the ID decoded and parked at its start in a third master input slot
(slot 3, used only by the ID). It never uses a tuner and never disturbs what is on air
or what is cued in slots 1 and 2. After each airing a fresh copy is cued.

- `roku_stream/ident.py`: the file path, `IdentLease`, the 30-second length.
- `master_worker.py`: `_keep_ident` cues it, `_complete` plays it after a file, `ident`
  is the immediate command (`_ends_first` lets a recording that ends inside the ID finish
  first), and `_start_armed` keeps a file armed behind the ID waiting until the ID ends. `GET /v1/master` includes `ident: {enabled, ready, on_air,
  duration_seconds, error}` and `last_station_id`.
- `source_queue.py`: asks for the ID 30 s before *At time* entries and a take's end
  time, and when a held game ends after its final buffer (`ident_at` is recorded on the
  entry; `_game_over` applies the buffer).
- `source_coordinator.py`: `station_id()` and queued takes that wait for the ID to end.

A cued ID that fails to decode is logged and retried after a minute. It is not a
master error and never affects what is on air.

## VizelVision Sports

Before a sporting event, the break ends with the **VizelVision Sports ID**
(`ident/vizelvision-sports.mp4`). It is the same 30-second form as the ID, with the
same hit points, taken to the ballpark at night. The floodlights come on bank by bank over
a dark stadium. The field is turf in place of the neon grid. Sports balls pop in, the stands
flash with cameras, a scoreboard marquee spells out the line as it is read, and a SPORTS
banner slams in under the wordmark. The music uses the sonic identity's sports palette:
floodlight clunks, drumline, stadium organ, a crowd that claps the logo, the stadium horn and
tape grit. It has the open logo on the first hit and the closed logo, sung, on the key change.
It plays once the game is ready, right before the game, as the second half of the break.

Its one line, *"The following... is a presentation of Vizel Vision Sports."*, is read by
Deepgram Aura-2 **Jupiter** (`aura-2-jupiter-en`, "expressive, knowledgeable, baritone").
That makes it the station's third voice, after DJ Low Tide (Orpheus) and the continuity
announcers. Of the 41 English Aura-2 voices, nine deep or authoritative ones were voiced and
measured. Jupiter is the deepest American baritone, with a median pitch of 86 Hz against
99–148 Hz for the others. The pause after "The following" gives it the classic network
delivery, and in that take speech-to-text hears "Vizel Vision Sports" exactly; plain
phrasings came back as "Visol". The verified take is kept in
`ident/voice/sports-presentation.wav`.

- **A sporting event** is a game show on the schedule (kind `game`), or an Up next entry
  that carries its game (one queued by hand to hold until its final). A game's backup is
  not one.
- **The break before a game** (the user's order, 3 October 2026):
  1. It starts where the ID would: over the end of the program before the game, or right
     after a final when another game is next.
  2. The duty announcer says what just played and what is next ("Coming up: the Padres and
     the Brewers. Stay tuned."). With announcements off, or when the lines cannot be
     voiced, the plain ID plays in its place.
  3. Its *Stay tuned* end card (27.9 s) holds while the game's source is prepared. A
     YouTube TV channel change takes 22 to 137 s.
  4. Once the source is verified, the iris closes and the Sports ID plays.
  5. The game is taken on its black tail.

  With the game's source already prepared (the antenna, or a Roku warmed up early), the
  break runs straight through, about 60 s. A network game's YouTube TV has until the first
  end card before [the antenna](source-queue.md) takes over. A hold is asked for only in
  the first half, so a retried preparation never freezes the Sports ID mid-animation. A hold
  that runs out (two minutes) plays the Sports ID anyway, and the take lands at its end if
  the source is ready by then.
- **It also plays from the test card**: 30 s before a game's timed entry with nothing on
  air, the coordinator asks the worker for the break with `from_test_card`. Nothing just
  played, so there is no "That was…". Only a sports break is started that way, and only when
  it is the break cued.
- **How it is cued**: continuity (`roku_stream/continuity.py`) reads the playback
  projection every 20 seconds, announcements on or off. When the program after the next
  break is a game, it renders the announcement, joins it and the Sports ID into one file
  (`join()`: the picture copied, the sound encoded again) in the announcements folder as
  `sports-<hash>.mp4`, and cues it with `ident_file`. The worker plays it once and then
  returns to the plain ID. Presentation's Continuity tab (and On Air's Next break tile)
  shows it as the next break ("DJ Low Tide, then VizelVision Sports", every line), with
  Listen. A new announcement or a rebuilt ID gets a new name, so it is joined and cued again.
- **Before 3 October** the Sports ID replaced the announcement and played first, and its own
  end card held in silence while YouTube TV changed channel. That opened the game a minute
  or more before it came.

Rebuild it with `/usr/bin/python3 ident/build.py --sports`. The parts are:
`ident/sports_script.json` (the line, its voice, its start at 13.4 s, and the measured word
timings the marquee follows), `ident/sports_jingle.py`, `ident/sports_animation.py`
(`--still SECONDS out.png`), and `ident/sports_timeline.py` (the ID's marks plus the
floodlights, the line and the banner). Remove the file to stop it; the plain ID then plays
before games again.

## Promos and idents in ad breaks

The station's 5- and 10-second bumpers (a legal ID, the time and temperature, and others) play
in ad breaks, at least one every 15 minutes as breaks allow, not between programmes. See
[promos.md](promos.md).

**Ads › Idents** (`/ads#idents`) shows them all together: the station's ID card, the station
ID and the Sports ID with their end cards (click one to play it), the promos, what is on air
or cued for the next break, and what aired. The IDs' files are served at
`GET /v1/idents/{station-id,sports-id}.{mp4,png}`; settings stay on Presentation.

## Turning it off, or changing it

The worker plays `ident/vizelvision-id.mp4`. Rename or remove that file to stop the ID;
put it back to resume. A rebuilt file is picked up within a few seconds, without a
restart.

Rebuild with:

```sh
/usr/bin/python3 ident/build.py --keys-file /path/to/keys.env
```

- `ident/script.json`: DJ Low Tide's lines and when each starts. The text says
  "Vizel Vision" (two words) to guide the pronunciation; edit it if it sounds wrong.
- `ident/voice.py`: renders only lines whose text changed. Each line is kept in
  `ident/voice/<id>.wav` with its script, so rebuilds cost nothing. The key comes from
  `DEEPGRAM_API_KEY` or `--keys-file` and is never printed or stored.
- `ident/jingle.py`: the music (numpy/scipy, run with miniconda's Python), mixed with the
  voice and mastered to −20 LUFS, the loudness of the TV recordings.
- `ident/animation.py`: the picture (pycairo). `--still SECONDS out.png` draws one
  frame. The build draws the end card (27.9 s) beside the video as
  `ident/vizelvision-id.png` (`vizelvision-sports.png` for the Sports ID), the picture
  Ads › Idents shows.
- `ident/timeline.py`: the shared hit points, so picture and music stay together.

The build runs at the lowest CPU priority and takes about two minutes. The new file
replaces the old one in a single rename.

## Validation

- `tests/test_ident.py`: worker cue/cut/hand-off/failure (a recording keeps its ending), queue timing (the ID asked for
  its length before release, holds, the window), coordinator gating, and the end-card
  hold (only at the end card, released for the take, the two-minute limit, a hold
  belongs to one airing, a Roku preparing as soon as the ID frees it).
- `tests/ident_integration.py`: the real ID in the real master graph with isolated
  MediaMTX. The ID was cued without going on air. A program with the next file armed
  behind it played to its end (0.0 s left), the ID played 29.9 s, and the armed file
  followed from its start (0.4 s in). The last program got the ID and then fallback, all on
  one publisher. Re-run on 2 October 2026 after the change to recordings.

The Sports ID passes the same real-media check: `tests/ident_hold_integration.py`, run with
`IDENT_PATH` pointed at `vizelvision-sports.mp4`, held at 27.9 s with no gap over 98 ms.
`tests/test_continuity.py` (`SportsIdTests`) and `tests/test_ident.py` cover the cue and the
start from the test card. They also cover the sports break: the announcement and then the
Sports ID, joined by real ffmpeg into 3600 frames and 60 s. The take waits out the whole
break, YouTube TV has until the first end card, and no hold is asked for in the Sports
half. On 3 October the hold check ran on a joined break: held at 27.9 s for 5 s, then
through the seam and the Sports ID to its end, with no timestamps going backwards and no
gap over 92 ms.

## Deploying

The web app and the worker must both be restarted to pick this up
(`vizelvision-stack.target`). Either can go first: an old worker ignores the new
commands, and a new worker without the new web app still plays the ID around library
files. Check that master is not live first, then relaunch the Roku app and take the
channel back on air.

## Diagnosing a missing ID

Every ID that is asked for and not played is logged. The web app logs `Station ID skipped: …`
with the reason: nothing on air, already on air, not ready, or the next entry already on air.
The master worker logs `Station ID not played: it is not cued`. This was added after the
Phillies game went final on 30 September at 17:20 with no ID and no log line. The handoff
to the White Sox game went through (the Phillies return gave way to the game under way,
and the White Sox game was on air 1 min 43 s later), but it was not covered.

