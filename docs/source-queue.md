# Master source queue

The Sources page now has one persistent **Up next** list for digital TV-Thing, analog TV-Thing, YouTube TV and baseball. Entries prepare their source, verify decoded audio/video, and take the exact prepared input to master. Navigation or tuning completion alone does not mark an entry successful. Analog remains untested because no signal is connected.

On desktop the queue sits beside the guide; on mobile the fixed **Up next** button opens a full-height sheet.

## Up next is the only way on air (September 30)

The page no longer has **Prepare**, **Take to master**, **Prepare & take** or Library **Play now**. To put something on, queue it: **+ Queue** beside a listing or recording, or on a source card for its selected channel or game. **Now · front of Up next** (`release_type: "now"`) puts the entry at the head of Up next, in front of every waiting entry, due two seconds later. The cut then follows preparation and verification, as for any entry. A paused queue, or a manual take held until an end, still holds it; the composer says so. Now is refused for a program that has not started. Source cards preview a source while Up next prepares it and while it is on master. The Roku card's **Last known** line says when queuing the selected channel reuses a recent verification instead of navigating. **Cancel preparation** and **Return to fallback** remain as stop controls.

Up next starts with **ON AIR NOW**: **OFF AIR · test card** when nothing is on, with *Nothing scheduled* (or *until* the next scheduled program). A schedule gap appears ahead of time as **Next scheduled · OFF AIR · test card**, because `next_scheduled` now includes the grid's OFF AIR changes. When a recording (or the station ID) is last in the rundown and nothing is scheduled before it ends, a closing **Then · OFF AIR · test card** row shows that master returns to the test card. A live channel with nothing after it stays on, so it gets no OFF AIR row.

The master API (`/v1/master/prepare`, `/take`, `/take-known`, `/prepare-take`) is unchanged for API clients and tests.

## Games and recordings (September 30)

Up next has two lanes. The **timed rundown** is everything with a time or a game
gate, including the schedule's entries; it releases in order, as before.
**Recordings** queued *After what is on air* fill time: they play in order when
master is free (the test card, the end of a file, a game gone final, a schedule
gap), and wait while a live channel or a game owns master. A timed entry that
comes due cuts in even if recordings were queued ahead of it. Recordings pick up
again when the schedule next reaches OFF AIR. An entry due within 30 seconds
(the station ID's lead) keeps a recording from starting just before it.

**A game holds master until it is final.** Scheduled games already did: their
return-to-schedule entries wait on the final, and everything behind them waits.
Now a game queued by hand does too. When an entry you queued is taken and its
source carries a game that is live or starts within the hour, the queue holds
master until that game's final, the same as a take "until the game ends": Up next
shows *On air until … ends* with the score, and **Return to schedule now** ends
it early. This covers MLB, Sunday Ticket, a YouTube TV channel's national game, or
an over-the-air station matched to a network.

**When the game is final, what should be on now comes next, in this order:**

1. A game already under way: another scheduled game whose start has passed
   joins in progress.
2. Recordings waiting in Up next, back to back, until the next live show starts
   on time.
3. The regular schedule: the grid block or program show on now, or OFF AIR.

Only the regular schedule gives way. That is an OFF AIR entry, or a grid block,
program show or game "Return to schedule" entry already more than a minute under
way when it releases. It is skipped as *gave way*, with the reason, in Up next's
history. Games, fixed backup programs, and entries you queued never give way. OFF
AIR also gives way to a recording on air, so the schedule does not cut a file to
the test card; the station ID is not played over it either.

**Scores.** Game status now carries the score: *Phillies 4, Braves 2 · Top 8th*
(MLB Stats API with its linescore; ESPN's scoreboard for NFL and NBA, e.g.
*4th - 2:31*). Up next shows it on the ON AIR NOW row, on an entry waiting for the
final, and in a held take's *On air until … ends* line. `GET /v1/queue` returns the
latest check of each game under `games` (`"mlb:<game_pk>": {title, summary,
finished}`), and game status responses add `summary`.

**Overlapping shows.** Scheduled shows and games may overlap; they may not start
at the same time, and one game cannot be scheduled twice. A later show takes over
from its start. A game's window ends where the next show starts: the queue keeps
the game on air until its final, then joins that show in progress (or it gives
way, as above). "Return to schedule" follows the grid and program shows, never
another game.

## Adding entries

Use **+ Queue channel** or **+ Queue program** beside a listing. Upcoming programs default to their start time. Current channels default to **Now**; **At time** takes an explicit future local time. **After game** uses an exact MLB game/date. **Scheduled end** uses the selected program's end-time snapshot; it is an estimate and does not detect overruns. The server resolves program snapshots from its catalog rather than trusting client-supplied titles or times.

Only the head can release. Reorder or **Remove** waiting entries; Pause/Resume applies to all sources and legacy schedules. A release time starts preparation, so the actual cut follows tuning and verification. Same-resource transitions use fallback while retuning/navigating. This version does not prepare independent sources early.

A failed take blocks progression until Retry or Remove. A program past its saved end becomes Missed. **Tune channel anyway** explicitly waives that entry's program requirement and keeps its release condition. Listings are checked again before preparation and take; a changed/missing target program blocks, and unavailable fresh listings keep the head waiting. Live MLB status is checked through its catalog. A title, start-time or end-time change requires review. The scheduled-end *release gate* remains the estimate captured when added; target-program validation is separate.

Manual master actions and application-controlled Roku navigation pause queue release. A pause during preparation prevents a subsequent take; the entry requires Retry or Skip. A cut already submitted when Pause returns may finish. Cancel preparation or Return to fallback provides the explicit stop action. These controls remain serialized with queue operations.

## Manual takes end on time

Since September 30 only API clients take directly; the page's **Change end time** and **Return to schedule now** still manage such a take. The prompt below was the page's Take to master prompt and is now the Change end time prompt.

**Take to master** asks how long the source stays on air:

- **:30 or Top of the hour**, whichever comes next.
- **When the program ends**, for a TV-Thing channel whose guide lists the current program. The server reads the end time from its own guide copy. This also covers sports that TV-Thing lists, such as *NFL Football*. It is the listed time, so an overrun is cut off.
- **The game ends**, when the source is carrying an MLB, NFL or NBA game that is live or starts within the hour. This covers an MLB or Sunday Ticket target, a national game on a YouTube TV channel, or an over-the-air station whose name matches a configured channel alias (WTTG-HD is WTTG, which is FOX). Out-of-market Sunday games are not matched to the local station. The end is the game's final status, so overtime stays on air. The latest end is 12 hours after the take.
- **A custom end time**, up to 12 hours ahead.

The default is the game when one is matched, then the listed program, then the half hour. Until the end, the queue stays paused, and Up next shows *Manual take on air until …*. At the end, the queue resumes. If Up next already has an entry due, or one waiting on the same game, that entry follows. Otherwise the current schedule block goes to the head of Up next, or OFF AIR does when the schedule is off. **Return to schedule now** ends the take early, and **Change end time** sets a new end for whatever is on air.

Preparing or cancelling another source keeps the end. Return to fallback, the operator's **Pause queue**, and manual Roku navigation away from an on-air Roku feed clear it, and the queue then stays paused as before. A take without an end (API clients that omit `until`) also pauses the queue indefinitely. The end is not saved across a web restart: startup always pauses for review.

## Priority: a show that outranks what is on air cuts in (October 4)

Each scheduled show or game has a **priority**: Low, Normal (the default) or High. It is set on the Schedule page's form, or changed on the upcoming list (`POST /v1/programming/shows/<id>` with `{"priority": "high"}`). Grid blocks, OFF AIR, and takes queued by hand are Normal. A show's priority is read live, so changing it also affects a game already on air.

- **A show that outranks what holds master cuts in at its start.** For a take held by hand (until a game's final, a program's end or a time), the hold's end moves to the show's start. The station ID, the warm-up and the hand-back then run as they do for an end time, and Up next says *until <show> cuts in at <time>*. The hold keeps its own end under `hold.cut.until` and goes back to it if the show is removed or loses its priority. Only shows starting after the take do this: **Play now** is not cut by a show that is already due.
- **A scheduled game on air** is cut the same way. Once the show is due (its early preparation, or the station ID's 30 s), the entries ahead of it are skipped as `cut`. These are the game's return to the schedule, which was waiting for the final, and anything overdue behind it, provided each has a lower priority.
- **Equal or lower priority changes nothing:** what is on air keeps master, and the show joins in progress afterwards, as before.
- **A program show starting inside one that outranks it** waits for that one to end. A game held back this way joins in progress, and returns to the schedule from that point.

The first use was 2026-10-04: Braves at Dodgers (FS1, held by hand until its final) was to play until Lions at Panthers started at 8:20 PM. That night the hold's end was set to 8:20 with `POST /v1/master/hold`, before this was deployed.

## Feed recovery (October 1)

A live program whose feed fails on air goes back on by itself. Before this, on October 1
two tuner feeds failed. NHK's audio timestamps jumped back at 15:03. Judy Justice stalled
at 15:48 while TV-Thing restarted its stream on the same channel. Master treats either as
terminal ("prepare the source again"), and nothing put the programs back: NHK had aired for
under two minutes, and Judy Justice was a scheduled show. Master showed the test card until
the next entry.

- **What counts:** a tuner or Roku program that the queue put on air. The trigger is
  master on the test card, with master's `last_input_failure` naming that very input
  (by input id) as failed while on air. An operator's fallback, the end of a file, a
  failed preparation, and a feed replaced by the next program do not count.
- **A scheduled program** goes back on as itself: a copy of its entry at the head of Up
  next, two seconds out, with the same schedule key, title and slot. The next show still
  takes over at its time. It is not put back in the last 60 s of its slot, or when its
  game is already final. There is no station ID: the copy joins in progress.
- **A held take** (until an end time, or a game's final) still recovers through its hold:
  after 20 s on the test card it goes back on with the same end. It no longer has to have
  aired for two minutes first.
- **A tuner that is still restarting** gets more chances: a recovery entry's failed
  preparation is retried (3 attempts, 20 s apart) for any live source, not only a Roku.
- **A feed that keeps failing** goes back on at most 3 times in 15 minutes per channel.
  After that, it is left on the test card for the operator, with `Feed failed again; not
  put back` in the web log. Play now, or Retry on a blocked recovery entry, puts it back
  by hand.
- **A paused queue** leaves it to the operator.

### Error tolerance and the other source (October 4)

On October 4 the Colts at Commanders game (NFL Network on YouTube TV, 9:30) was failed off
the air eight times in 25 minutes, though its picture looked fine. YouTube TV stalled at
10:04:57 (1.8 s packet gaps) and was re-tuned (44 s); the new feed stalled at 10:05:54 and
failed 0.8 s later ("audio timestamps changed", 43 ms back) while master waited for it.
That failure read `was_on_air: false`, so nothing put it back. A manual pick from the Sunday
Ticket listing then searched Sunday Ticket, which does not carry NFL Network games. Over
the antenna, FOX 5 stalled at 10:21, 10:25 and 10:29: the queue had spent its three
put-backs by then, two of them while master was bringing the feed back by itself.

- **Master rides out stalls** (`DecodedInput`, `MasterWorker.STALL_HOLD_SECONDS`). A live
  input on air that delivers nothing for a second keeps its last picture on air, with
  silence, for up to 8 s (`Master input stalled on air; holding its picture`). When media
  arrives again it carries on (`Master input rode out a stall on air`). Only after 8 s does
  master cut to the test card and wait there, as before. Frames arriving over a second late
  are dropped, keeping the timeline. A small step back (under a second, a repeated audio
  packet) is dropped as overlap. Frames still late 1.5 s into a hold re-anchor the input
  past the held picture. A jump ahead of the clock still fails the input.
  `tests/live_stall_integration.py` reproduces the 3 s stall with real GStreamer.
- **Re-anchors are budgeted per minute**, 5 in 60 s, not 5 in an input's whole life.
- **A failure while master waits for an input** reports `was_on_air: true`
  (`during_recovery: true`), so the queue puts the program back on.
- **The other source** (`SourceCoordinator.alternates`): a program the antenna also
  carries goes back on from the antenna first, which tunes in seconds. That covers a
  network's station, a game the TV-Thing guide lists with both teams, or a Commanders game
  on NFL Network (`sports.LOCAL_SIMULCASTS`: FOX 5). Once the antenna has gone back on 3
  times in 15 minutes, YouTube TV is used alone. The reverse holds too: an antenna station
  falls back to its network on YouTube TV. Each source has its own budget. The program is
  left to the operator only when every source has used its budget (`Feed failed again; not
  put back: every source carrying it…`). Each recovery logs `Feed recovery: putting it back
  on…`, and each decision not to recover gives its reason.
- **Sunday Ticket** lists only the Sunday-afternoon CBS and FOX games (`on_sunday_ticket`),
  never a national exclusive such as NFL Network, ESPN or Sunday Night Football.

Up next shows the copy with *Its feed dropped (the error); going back on*, and the log shows
`Feed failed on air (the error)`. The rules are in `SourceQueue._recover_step` and
`_reair`, and are tested in `tests/test_feed_recovery.py`.

### Video left behind its audio, and back to YouTube TV (October 4, noon)

At 12:10:53 the YouTube TV feed's video came out over a second behind the clock while its
audio stayed on time. Master dropped every frame (476) and held the picture for the full 8 s.
The re-anchor 1.5 s into a hold never fired, because the tracks shared one lateness timer
and each on-time audio buffer reset it. Recovery then failed in 0.1 s: one anchor cannot fit
two tracks that are over a second apart. The game went back on from the antenna 22 s later,
because a held take waited out `HOLD_LOST_SECONDS` on the test card even though master had
already failed its input. It then stayed on the antenna, which is the worse picture.

- **Each track has its own lateness** (`DecodedInput.late_since`). If both tracks are late
  (or one is silent), the input re-anchors 1.5 s into a hold, as before. If only one track
  is late, the other is on time, and the late one is not catching up (its frames come no
  faster than 1.25× real time), the input fails at once with `Input video is over a second
  behind its audio`. A backlog arriving in a burst after a stall is left to catch up.
- **A held take goes back on as soon as master fails its input.** The hold records its
  `input_id`; `SourceCoordinator.input_failure` adds `recovering` while master still waits
  for the input on the test card. The 20 s timer remains for a test card with no failure.
- **Back to YouTube TV** (`SourceQueue._upgrade_step`). When the antenna is on air in
  YouTube TV's place, either by feed recovery or by the antenna taking over at release, the
  Roku is prepared beside it once the antenna has aired 30 s. The antenna stays on air.
  The preparation uses the same `_preroll` path as a warm-up (`keep_air`). Once it is
  ready, `SourceCoordinator.upgrade_queue` cuts to it with the `_upgrade` action. That
  action never navigates (no preparation means `YouTube TV is no longer prepared`, and the
  antenna stays) and never touches the hold. The queue moves the hold (or the watched
  airing) to the YouTube TV input, so nothing new is queued and Up next does not resume.
  The rules:
  - A failed preparation is tried again after 2 minutes, at most 3 times per airing.
  - It counts as a YouTube TV put-back, and it stops once YouTube TV has gone back on
    `UPGRADE_LIMIT` (2) times in 15 minutes. A feed that keeps failing there stays on the
    antenna, and the antenna keeps its own budget.
  - It does not run in a game's closing stretch or a slot's last 3 minutes. The Roku is the
    warm-up's then.
  - The content jumps back by YouTube TV's extra delay at the cut.

  Logs: `Back on YouTube TV from the antenna`, `Could not go back to YouTube TV (…); staying
  on the antenna`. Up next says *Preparing … on the Roku; it replaces the antenna once
  ready*. Tests: `tests/test_back_to_youtube_tv.py`, `tests/test_input_stalls.py`,
  `tests/test_feed_recovery.py`, `tests/test_antenna.py`.

### The Roku still playing: back on without navigating (October 4, afternoon)

A Roku feed that fails is nearly always a blip in the capture card, not the Roku. At 13:35
the Sunday Ticket game failed ("video over a second behind its audio"). Its verification
was over 15 minutes old, so it went back on by navigating Sunday Ticket again, which took
2 minutes. At 13:39 it failed again. The reattach without navigating failed 6 s in on a
12 ms audio step back. That threw the selection away, so the game was navigated again,
and the new feed failed the same way (43 ms) at 13:41. The game was off the air for
5 minutes while the Roku played it all along.

- **A small step back while preparing is dropped** (`DecodedInput._repeats`). A fresh
  session on the Roku capture repeats a few ms of audio several times in its first
  seconds. Each step back used to re-anchor the input, and once the re-anchors ran out
  (5 a minute) the preparation failed. A live input being prepared now drops a frame
  under a second behind what it already delivered, as overlap, as it does on air. A
  rewind over a second still re-anchors, and files are unchanged.
- **What the Roku plays is remembered until it navigates** (`SourceCoordinator.playing`).
  This is the target and the ECP app it was verified in. Every navigation clears it,
  including an operator's (`navigation_guard`). A restart clears it too.
- **A brief check, then a reattach** (`_not_playing`, `_resume_roku`). When a queue entry
  (`_queue`, `_preroll`, `_upgrade`) needs what the Roku still plays, it checks three things:
  - the Roku is in the same app;
  - ECP's player says `play`;
  - the capture card shows a moving picture within `PLAYING_SECONDS` (4 s).

  This covers the cases where the 15-minute reuse has lapsed or the capture restarted. If
  the check passes, the verification is renewed and the feed goes back on without
  navigating. The selection is kept, so an input on air still holds it. A restarted
  capture gets a new selection of the same feed. A failed check, or any navigation since,
  navigates as before. A manual *take known* still needs a recent preparation.
  "Moving" means over 0.5% of the sampled bytes changed by over 24 levels between two
  fresh frames. During play that day 46–64% changed; a near-still ad end card changed
  2–3%.
- **Feed recovery asks first** (`SourceQueue.roku_playing`). The Roku goes back on before
  the antenna when it passes the check, because it is as fast and the picture is
  better. A check that passed holds for 20 s, so the reattach does not repeat it. It
  counts against the Roku's recovery budget as before. Once that budget is used up, the
  antenna goes on.

Logs: `The Roku still plays …; its feed goes back on without navigating (the capture card
last stalled 1.8 s, at 13:39:14)`, or `The Roku no longer plays … (its player is pause);
putting it back on from the Roku means navigating`. Tests: `tests/test_source_coordinator.py`
(`StillPlayingTests`), `tests/test_feed_recovery.py`, `tests/test_input_stalls.py`.

## YouTube TV or the antenna (October 3)

NBC, FOX, ABC, CBS and The CW reach VizelVision two ways: YouTube TV through the Roku, and
TV-Thing's antenna, which carries the same Washington stations (WRC 4.1, WTTG 5.1, WJLA 7.1,
WUSA 9.1, WDCW 50.1; `roku_stream/networks.py`). A YouTube TV channel change on the Roku took
22–137 s in the queue's history (median about 70 s; 110 s for the FOX game at 20:00 on
October 3). The antenna tunes in 2–10 s. So a queue entry for one of these networks on
YouTube TV, or an MLB game that YouTube TV carries on one of them, plays from YouTube TV when
it is ready in time, and from the antenna otherwise.

- **In time** means by the entry's release. The early preparation (5 minutes ahead when the
  Roku is free, or under the station ID when the Roku was on air until then) is stopped at the
  release time if the Roku is still navigating. At release, a YouTube TV preparation that is
  ready is taken. Otherwise the antenna goes on, under the station ID's held end card when
  one is on air. With no time at all (Play now, a feed recovery), the antenna goes on at once
  unless YouTube TV is already prepared.
- **A station ID that covers the change** gives YouTube TV until the ID's tail (an entry
  released at the start of an ID, after a game's final, for example). If YouTube TV fails
  outright in that time, the antenna goes on at once.
- **The antenna busy** on another channel (a TV-Thing recording, say) or TV-Thing being down
  means YouTube TV after all, however long it takes, as before.
- **Afterwards** the Roku is prepared beside the antenna and the program goes back to
  YouTube TV once it is ready (since October 4; see "Back to YouTube TV" above). A dropped
  feed goes back on from the antenna first (feed recovery), then returns to YouTube TV the
  same way.
- **The choice** is the target's: `"antenna": false` on a `youtube-tv` or `mlb` target means
  YouTube TV only (it waits, as before). A `tv-thing-digital` target is the antenna only. The
  Play now / Add to queue / Schedule dialog shows Source (YouTube TV, else the antenna · YouTube
  TV only · Antenna) for these networks and their games. The Schedule page's source pickers
  show *If YouTube TV is late*.
- **What you see:** Up next marks a waiting YouTube TV entry with its antenna backup, and an
  entry the antenna took with *From the antenna · 4.1 WRC-HD (the reason)*. The web log says
  `YouTube TV was not ready by 20:00:00: the antenna takes over (5.1 WTTG-DT)`.

The rules are in `SourceCoordinator._prepare_live`, and are tested in `tests/test_antenna.py`.
`ROKU_FASTEST` (10 s) is the least time worth trying YouTube TV in.

## The Roku is prepared before a program ends (October 3)

Until now the Roku was prepared early only for a timed entry, 5 minutes before its time. Two
kinds of entry never were. The first is an entry waiting on a game's final: a game's return
to the schedule, or anything behind a game held until its final (Up next is paused then). The
second is a Roku entry queued after a recording. It was prepared as soon as the recording
started, so its preparation had expired (15 minutes) by the end of a long recording. Either
way the Roku changed channel only at the cut, 22–137 s under the station ID's end card.

Now, while another source is on air (the antenna, a TV-Thing channel, a recording), the
Roku entry that follows is prepared when what is on air is about to end:

- **A game in its closing stretch**: the 9th inning or later; the last 2:00 of the 4th quarter
  or overtime (NFL, NBA, WNBA); the last 2:00 of the 3rd period or overtime (NHL); the 88th
  minute (NWSL). A game already final counts too. This is `sports.closing`, read from MLB's
  linescore and ESPN's clock; `game_status` returns it as `closing`.
- **A show held to an end time** (a time, or its listed program end): its last 3 minutes.
- **A recording**: its last 3 minutes (`ENDING_SECONDS`), when a Roku entry is next after it.
  A recording after a recording is still cued at once, as before.

**What follows** is worked out the way the queue will choose it. After a held take: a game
under way, then recordings, then the next entry when it is due or waits on this game. If none
of those applies, it is the schedule's block on now, which joins Up next only when the take
ends (`Programming.on_now`). After a game's return entry: a game under way, then recordings
when the return gives way to them, then the first return whose slot is still on. Only a Roku
entry is prepared, and never while the Roku is on air.

- **The cut** reuses the preparation and goes at once. A network's antenna backup still
  applies: a preparation not ready by a show's end time is stopped there, and the antenna goes
  on. For a game there is no end time, so YouTube TV gets as long as it takes.
- **A preparation that expires** before the game ends (after 15 minutes) is done again.
- **One that fails** is tried 3 times, 20 s apart, then left to the cut. A release for
  another channel that comes due meanwhile (Play now, feed recovery) stops it. A release for
  the same channel waits for it.
- **What you see:** the entry says *Preparing early, while Phillies at Braves finishes*, then
  *Prepared early; goes on when Phillies at Braves ends* (a game's return adds *· prepared
  early* to the score). The schedule's block has no row yet, so Up next's status line says
  *NBC is ready on the Roku for when Phillies at Braves ends.* `GET /v1/queue` returns that
  as `warm` (`target`, `title`, `ends`, `state`: preparing, ready, failed or stopped, `error`).
  The web log says `Preparing {…} early, while … finishes` and `Prepared {…} early`.

The rules are in `SourceQueue._warm_step` and `_warm_candidate_locked`. They are tested in
`tests/test_warm.py`, including a run with the real coordinator: the Roku is prepared under a
game on the antenna, and taken without navigating again.

## Persistence and compatibility

With master enabled, `queue.json` uses a version-2 object containing items and pause state. The original array is backed up as `queue.pre-master.json` on first migration. Legacy entries become YouTube TV targets without losing order, conditions or history. Existing `jobs.json` schedules are imported once, in time order after the existing queue. Their original file is preserved; stable import IDs prevent duplicate execution. `/v1/schedules` and `/v1/jobs` now adapt to the same queue; there is no independent scheduler thread in master mode.

Every service start pauses automation for review. An entry saved as running becomes blocked with an interrupted/unknown-outcome message. It is never replayed automatically. Check the actual master and choose Retry or Skip, then Resume. This is operator reconciliation; automatic restart reconciliation has not been implemented.

With master disabled, the existing Roku-only queue and scheduler retain their original behavior. Do not point that mode at migrated version-2 state; use its separate original configuration/state directory.

## API

- `GET /v1/queue`: `master_queue`, `paused`, `pause_reason`, `hold` (a manual take's `target`, `until`, `program` or `game`, and game `detail`), `schedule_enabled`, `items`, `master_on_air`; legacy `on_air` remains the last confirmed Roku selection.
- `POST /v1/master/take` and `/take-known` accept an optional `until`: `{"kind": "time", "at": ISO}`, `{"kind": "program", "program_id"}` or `{"kind": "game", "league", "game_pk", "game_date"}`. `POST /v1/master/hold` with `{until}` changes the end of what is on air.
- `GET /v1/master/end-options?source_id=&channel_id=[&date=]`: the `games` and TV-Thing `program` a take can end with, and `returns_to` (`schedule` or `off_air`).
- `GET /v1/networks`: each network on both YouTube TV and the antenna: `network`, `call_sign`, `youtube_tv` (its channel) and `antenna` (`source_id`, `channel_id`, `number`, `name`, or null when TV-Thing does not list it).
- `POST /v1/queue`: `target` (`source_id`, `channel_id`, optional game `date` / TV `quality`, optional `antenna: false` for YouTube TV only), `release_type`, and `run_at` or `after_game`. `release_type: "now"` needs neither: the entry goes to the head, due in two seconds, and is stored as `at_time`.
- `next_scheduled` in `GET /v1/queue` is the next schedule change not yet queued, including OFF AIR (`kind: "off_air"`, target `off-air`). Optional `program_id` binds a live-program snapshot. Legacy `channel` requests remain supported.
- `scheduled_end` requires `after_program: {target, program_id}`; its end is resolved on the server.
- `POST /v1/queue/pause`, `/resume`.
- `POST /v1/queue/{id}/move` with `direction: up|down`.
- `POST /v1/queue/{id}/skip`, `/retry`, `/tune-anyway`.
- `DELETE /v1/queue/{id}`: the homepage's **Remove** for a waiting or blocked entry. An entry
  you added is deleted. One the schedule added stays listed as skipped ("Removed from Up
  next"), because the schedule's next sync would add a missing entry back. Removing or
  skipping a recording already cued to follow the on-air file un-cues it, so it does not
  play anyway. Running entries cannot be removed.
- `POST /v1/queue/clear` `{}`: **Clear queue** removes every waiting or blocked entry added
  with Play now or Add to queue; scheduled programs stay. It returns the queue with
  `removed`, the count. The homepage asks first.
- Existing `DELETE /v1/queue/{id}` removes a waiting entry.

Master queue operations expose their `queue_item_id` and target. Media input failures retain the failed target, whether it was on air, and each track's last-buffer age/count in `last_input_failure`; the same diagnostic is logged to the master service journal.

## Validation

- Unit coverage: state migration, restart ambiguity, strict order, failed/missed/changed entries, busy retry, pause/reorder during game lookup, take admission, legacy API compatibility and confirmed master takes.
- `tests/test_manual_hold.py`: time, program and game ends, early return, what follows (schedule block, OFF AIR, a due entry), end validation before any cut, and game matching. `tests/browser_ui_air.cjs`: the end prompt's default and exact body, Up next's actions (resume, move, retry, remove, clear with confirmation) and Return to fallback.
- `tests/browser_ui_sources.cjs`: Play now (resuming a paused queue), Add to queue, Schedule, the library's add-all in order, the Roku card, filter persistence and phone width. `tests/test_source_queue.py` covers Now going to the head and releasing, and refusing a program that has not started.
- `tests/roku_master_integration.py`: generated media with real GStreamer, worker IPC and MediaMTX; queue prepare/take plus continuous subscriber verification. Controls are simulated. Report: `roku-master-validation.json`.
- `tests/live_source_queue.py`: opt-in real NBC queue test with continuous subscriber and 30-second on-air observation. Requires operator authorization and an empty pending queue; leaves NBC on master and automation paused. Report: `live-source-queue-validation.json`.
- Current digital and Roku feeds each passed 300-second isolated media observations with no retuning, no backwards timestamps, and unchanged publisher/viewer sessions. Reports: `current-tv-input-validation.json`, `current-roku-input-validation.json`.

The earlier input-stall root cause was not reproduced by these observations. The new diagnostics make a recurrence attributable; the freshness thresholds have not been loosened.

September 13 live result: the real NBC queue take passed, including 30 seconds on air, H.264 1280×720/AAC stereo 48 kHz, one capture owner, and the same publisher and subscriber across the switch. No backwards timestamps were observed. NBC was left live with the queue paused.
