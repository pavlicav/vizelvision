# Media library playout

The Sources page has a **Media Library** view for playing finished files to master.
The first collection is TV-Thing's recordings folder. More folders can be added as
extra roots. Files play through the same worker and master path as live sources.

## Browse

Open **Media Library** in the source list. Files are grouped by folder. TV-Thing
recordings are listed newest first, with their title, channel, air time and
duplicate marker (`(2)`, `(full)`). Other folders are listed in episode/name order.
Search matches titles, folders, channels and file names.

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
  "release_type": "after_current"}` (or `at_time` with `run_at`).
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

Not covered yet: previewing a file in the browser before playing it, starting partway
through a file, audio-only files, and adding library files to Schedule shows.
