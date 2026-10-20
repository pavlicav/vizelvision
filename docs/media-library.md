# Media library playout

The Sources page has a **Media Library** view for playing finished files to master.
The first collection is TV-Thing's recordings folder. More folders can be added as
extra roots. Files play through the same worker and master path as live sources.

## Browse

Open **Media Library** in the source list. Files are grouped by folder. TV-Thing
recordings are listed newest first, with their title, channel, air time and
duplicate marker (`(2)`, `(full)`). Other folders are listed in episode/name order.
Search matches titles, folders, channels and file names.

Shows (a root with ad breaks: Jellyfin TV) are listed by show, then season, each closed until
opened (*How It's Made · 21 seasons · 255 episodes*, then *Season 2 · 13 episodes*, with
**+ Add all to queue** on each season). What you open or close stays that way in this browser.
Left alone, a show and season open by themselves while one of their episodes is on air, cued,
or has its ads strip open. A search opens everything it finds.

Only finished files are listed. TV-Thing writes a recording as `*.part` and renames
it into the folder when complete, so a recording in progress does not appear. The
web app checks each file once with `ffprobe` in the background and caches the
result in `library-cache.json` beside the queue. A file is re-checked when its
size or modification time changes. Master needs both video and audio, so files
without one of them are shown with the reason and cannot be played.

## Play

- **+ Queue** is the only way to put a file on air (since September 30). With nothing
  from the library on master it defaults to **Now**: the file goes to the front of Up
  next and plays from the beginning. While a file is on air it defaults to **When the
  current recording ends**.
- Up next checks that the file decodes, then parks it paused at its start. TV-Thing
  recordings begin with about 1.6 seconds of audio before the first video frame. The
  cue skips that audio-only lead-in (up to 5 seconds), so a take or back-to-back cut
  gets picture and sound at once. Files are independent of the
  tuners and the Roku: preparing a file never interrupts what is on air.
- While a file is on air, the master notice shows position / length and a
  progress bar. Every file plays to its very end. Then the [station ID](station-id.md)
  plays, and master returns to the test card, unless a queued file is cued to follow. A cued
  file follows the ID and starts from its first frame.

Up next shows **Then · OFF AIR · test card** after the last file when nothing is scheduled before it ends.

## Queue

**+ Queue** on a file opens the composer with **After what is on air · fills time**
selected while a file is on master, else **Now**. **At time** is also available.
**Queue all in order** adds a whole folder, oldest recording (or first episode)
first, skipping files that cannot play.

Since September 30, *After what is on air* entries **fill time** around the timed
rundown. They play in order, back to back, whenever master is free: the test card
is up, the file on air ends, a game goes final, or the schedule reaches OFF AIR.
While a live channel or a game owns master they wait. A timed live entry (a
schedule block or show starting on time, or one queued at a time) cuts in at its
start even when recordings were queued ahead of it, and the recordings pick up
again at the next gap. The cut recording is not replayed. A schedule block that is
already under way when master frees up (for example after a game ran long) gives
way to them. See [what follows a game](source-queue.md#games-and-recordings-september-30).
The same condition can be chosen for a TV or Roku entry while a recording is on air.

The first waiting recording is cued early and armed behind the on-air file. The worker cuts to the cued file at the end of the current one:

- it starts the next file 0.4 seconds early, so its first frames are ready at the cut;
- the cut happens without fallback and on the same publisher;
- the queue then marks the entry taken without preparing it again.

*At time* library entries are also cued within five minutes of release.

Pausing the queue disarms the cue, so the next file will not start by itself. It
stays prepared for an explicit take, and is cued again on resume. After a restart,
the worker starts on fallback and nothing is replayed. Cued entries are cued again.

## Ad breaks for shows (October 20)

Shows from Jellyfin can play with **ad breaks spliced in**: the file pauses at each of its act
breaks, My ads (and station promos) play over it, and then the show goes on. This is only for
a folder set up for it (`"ad_breaks": true`, the **Jellyfin TV** root), never TV-Thing's
recordings, whose breaks were cut out live.

**On the Media Library page**, a show's row has **+ Add ads** beside Play and Queue. It opens a
strip under the row:

- **Each break**: how long each break runs, 0:15 to 3:00 in 15-second steps (remembered for
  the next show). Ads play one after another until the show is back. The show waits for the ad
  on air when the time is up if it ends within 15 s; otherwise that ad is cut. There is never
  black at the end of a break: if an ad ends before the show is back, the next one starts and is
  cut where the show comes back.
- **Scan for ad breaks**: finds the breaks in this file (about half a minute) and says how many
  there are and where: *3 ad breaks · at 5:48, 11:00, 16:35*. Nothing is ever scanned on its
  own. What a scan found is kept in `library-cache.json` until the file changes; **Scan again**
  repeats it.

With Add ads on and breaks found, **▶ Play** and **+ Queue** (and the **More** dialog) put the
show on with them. Up next shows *Recording · 21:56 · ad breaks of 1:00*, and counts the breaks'
time when it works out when a recording ends. While the show is on air, its row says how many
breaks are done and when the next one is. Until a scan has found breaks, Play and Queue put the
show on without ads.

**How the breaks are found** ([library_breaks.py](../roku_stream/library_breaks.py)). A show
made for commercial TV fades to black *and* goes silent at the same moment at each act break;
an ordinary cut keeps its narration or music going, so it never counts. The scan listens to the
whole sound track for quiet moments (seconds), then decodes only a couple of seconds of picture
around each one to check for black. Fades less than 45 s apart are one transition (the fade,
the show's "How It's Made" return bumper, the next product's title), and the break goes at the
first. None in the first or last 90 s; about one break every 7 minutes (3 in a half hour),
picking the transitions nearest even spacing, at least 2.5 minutes apart. Some files (Season 31's
web copies) still have the network's ~6 s slugs of black and silence: those are the breaks
exactly, and the show plays on from the end of the slug's black.

Checked on six How It's Made episodes from seasons 1, 2, 10, 15, 21 and 31: every one got 3
breaks, at about 5:45, 11:00 and 16:00-16:35, each at the end of a segment just before the
return bumper.

**On master** ([master_worker.py](../roku_stream/master_worker.py)): 15 s before a break the
first ad is cued (any length, unlike a wait fill's), 2 s before the file is told where to stop,
and from the break's frame nothing more is passed on; the file freezes on that dark frame and
the [wait fill](my-ads.md#filling-a-wait)'s machinery shows the ads full frame over it. While
it waits, the file stays paused on the next frame (it does not decode on). At the break's length
on master's input side (or where the ad then on air ends, if within 15 s), the file seeks to
the break's resume point and plays on, with an unbroken timeline; what airs is the programme
delay (13 s) behind, and the ads carry on over it until the show's first frame airs. With none
of My ads or promos able to play, the break is skipped. Taking another source mid-break ends it.

Fixed on the first evening (October 20): the end of a break was decided on what aired, so the
show came back a programme delay late and the held black frame filled 5-10 s; and the paused
file decoded on in the background during a break, reached its end, and "ended" (the station ID,
then the test card) as the break closed. Plays are logged with `programme_break: true` ("in a show's ad break"
on the My ads page).

**Sound tracks.** Jellyfin's files can carry a dozen dubbed tracks, Bulgarian first. A file in
a root with ad breaks that has more than one is decoded with `uridecodebin3`, which plays only
the picture and the English track (else the first). TV-Thing recordings decode as before.

## Configuration

```json
"library": {
  "enabled": true,
  "roots": [
    {"id": "tv-recordings", "name": "TV Recordings", "path": "/mnt/sda1/media/TV Recordings"}
  ]
}
```

- `id`: lowercase letters, digits and hyphens. It is the first part of every item ID
  (`tv-recordings/Jeopardy! - 7.1 WJLA - 2026-09-23 1930.mp4`) and is saved in queue
  entries, so keep it stable.
- Add a root per folder, for example `{"id": "movies", "name": "Movies", "path": "/mnt/sda1/media/Movies"}`.
  Folders are scanned recursively, up to 8 levels deep and 20,000 files, skipping
  hidden files and folders.
- Listed extensions: `.mp4 .m4v .mkv .ts .mov .webm .avi .mpg .mpeg`.
- `ad_breaks` (default false): the root's files can be scanned and queued with ad breaks
  (above). The Jellyfin TV root is
  `{"id": "jellyfin-tv", "name": "Jellyfin TV", "path": "/mnt/sda1/media/library/tv", "ad_breaks": true}`.

Both the web app and the worker read the same `library` block. Restart
`vizelvision-stack.target` after changing it.

## Safety

- The browser and the worker socket accept only item IDs, never paths or URLs.
- An ID is resolved inside its configured root. `..`, hidden components and absolute
  paths are refused, and a symlink that leads out of the root is refused at play time.
- Files are only read. The library never erases or renames anything.

## API

- `GET /v1/sources/library/programs`: `roots` and `items` (`id`, `title`, `channel`,
  `aired`, `variant`, `collection`, `bytes`, `duration`, `playable`, `reason`, `probe`).
- `POST /v1/master/prepare` with `{"source_id": "library", "channel_id": "<item id>"}`,
  then `POST /v1/master/take` with the `prepared_id` returned in status.
- `POST /v1/queue` with `{"target": {"source_id": "library", "channel_id": "<item id>"},
  "release_type": "after_current"}` (or `at_time` with `run_at`). A show adds
  `"ad_breaks": <seconds>` (15-180, steps of 15) to the target, once a scan has found breaks.
- `POST /v1/sources/library/scan` with `{"channel_id": "<item id>"}`: scan a show for ad breaks.
  Items of a root with ad breaks carry `ad_breaks: {state (not_scanned | waiting | scanning | ok |
  none | failed), at: [seconds], slugs, reason, scanned}`. On air, `break_plan` says how its
  breaks are going (`count`, `aired`, `skipped`, `state`, `next_at`, `left_seconds`).
- `GET /v1/master`: an on-air or prepared file has `media: {position_seconds,
  duration_seconds}`. A prepared file cued behind the on-air one has `after_input_id`.
  `last_completed` records the last file that ended, plus `next_input_id` when
  master cut directly to the next file.

## Validation

- `tests/test_library.py`: ID confinement and symlink refusal, name parsing, probe
  cache, file take/end/armed-cut/disarm behavior in the worker, and queue +
  coordinator cueing, arming, reuse and pause.
- `tests/library_integration.py [--hd] [--real FILE]`: real GStreamer worker and
  isolated MediaMTX. A cued file waits at 0.0 s, take starts at ~0.1 s, the armed
  second file cuts in automatically at ~0.4 s on the same publisher, and the last
  file ends on fallback. `--real` also plays 20 s of an actual recording. A 720p run
  on the Jeopardy recording played at a steady 30 fps.
- `tests/browser_ui_sources.cjs /path/to/playwright`: a recording's Add to queue body, add-all in
  order, search, and phone width. Up next's OFF AIR row after the last file is drawn by
  `static/ui/queue.js`.

- `tests/test_library_breaks.py`: picking breaks, scanning only when asked and keeping the
  result, the break of a set length, and the worker's prime/arm/hold/play on; with the system
  Python for the GStreamer parts. `tests/library_breaks_integration.py FILE --scan` plays a real
  show through its first break (run as a user who can read the file). On S02E02 (12 tracks) it
  played the English one, held a black frame and played on with no gap over 113 ms; on
  S31E01 it skipped the slug's remaining black.

Not covered yet: previewing a file in the browser before playing it, starting partway
through a file, audio-only files, and adding library files to Schedule shows.
