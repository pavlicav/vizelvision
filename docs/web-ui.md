# The web UI: the control room

Every page is in `roku_stream/static/ui/`, together with the scripts and styles they share.
It was rebuilt from scratch on 2026-10-01. The look is a broadcast control room, and colour
means state, as on a vision mixer:

- **red** is on air (PGM)
- **green** is ready (PVW)
- **amber** wants attention
- **blue** is something you can click

The pages stay plain. The how-it-works diagrams are hidden until you switch on
**Machinery**, and the command palette is there for keyboard users.

## Pages

| Page | What it is for |
|---|---|
| `/air` (home; `/` and `/cue-sheet` redirect here) | Master's output: the monitor (HLS), what is on air and its progress, what is prepared next, the end time of a held take, **Return to fallback**. Up next in full, with a search box at its top that adds any channel, game or recording. Tiles for the bar, the next break and the schedule. Machinery: the signal path with live track lag. |
| `/sources` | Every channel, game and recording, with the three ways on air: **Play now**, **+ Queue**, **Schedule**. One preview card per source group. The Roku live capture and its controls. The media library, and sports by league. A compact Up next sits alongside. |
| `/schedule` | Painting the weekly grid, with what will air drawn over it. The automation switch. Upcoming shows and games, and those removed by the sports feeds. The 24-hour rundown. Sports, and a form to add a show or game. Machinery: who gets master, in order. |
| `/crawl` | The register of everything the crawl can air (see [crawl.md](crawl.md#the-register)), what is on the bar now, and who holds it. The controls, in tabs: messages on the bar, rules, segments, sources, teams, station messages, history. Machinery: the next three hours as a timeline. |
| `/presentation` (`/production` and `/continuity` redirect here) | The off-air card and its audio, the station clock, [live Whisper captions](live-captions.md) (`#captions`), continuity, the station ID, **Promos** (`#promos`; [promos.md](promos.md): the station's bumpers in ad breaks, on or off, how often, fill, each promo with its still and live text, a preview player that lays the live text over the video, what master has cued, the temperature and programme it will show, and what aired), and a link to the sonic identity. Production's old tab links still work: `#crawl` goes to `/crawl` and `#monitor` to `/engineering#monitor`. |
| `/ads` (`/admute` and `/my-ads` redirect here) | Ads, in four tabs. Each tab has its own address, the last one is remembered, and only the tab on screen is polled. **Ad mute** (`#admute`; [ad-mute.md](ad-mute.md)): Off / Shadow / On. On air: the detector's state, a known ad playing, the words it hears, and the picture on master now with the 30 s before it, beside the quick fixes (**u** / **a**, also on On Air). Recent breaks with their pictures and a known-ad tag, to mark right or wrong. Known ads: the fingerprint database, this game's play-by-play learning, what it learnt lately, and the full list, each with Forget. Training recordings: games recorded on TV-Thing for training (with Cancel), and those left out and why. Each mute's reason (also on the diagnostic badge). How it works, and the settings (what it listens to, how it decides, what it learns, during a break). Machinery: the last hour of P(ad), mutes and seams. **Ad database** (`#database`; [ad-mute.md](ad-mute.md#the-ad-database)): every clip the known-ads database holds, as cards: its pictures, script (the words said over it, with times), status (known ad, heard once and how many more airings it needs, show sound), length, how often and when it was heard, and where from. Search (**/**) finds words in the scripts, names and programmes; filters for known, heard once and show sounds; sort by last heard, most heard, newest or longest. Name an ad (say, the advertiser), or Forget it. Machinery: clip id, hashes, seed and where its words came from. **My ads** (`#my-ads`; [my-ads.md](my-ads.md)): your own ads, aired in place of the breaks ad mute mutes. What is on air (your ad and how far in, or the break card), with the quick fixes (**u**, **a**) and Skip. Next up: what the breaks play next (what you queued, the rotation's next five ads, the station promo where its timing puts it), each with a Skip; Play next / Add to queue for any ad or promo. Upload by dropping videos (progress per file). The list in order: pictures (click to preview), length, loudness levelling, plays in the last hour and day, a switch, a limit (presets or custom), a volume trim, Queue, rename, move, delete. Shuffle or list order. The break card (the station card's words, or your picture) and the corner picture (corner, size). What aired: each play, cut-short ones marked. **Idents** (`#idents`; [station-id.md](station-id.md), [promos.md](promos.md)): the station's ID card (the legal ID's picture, VizelVision 19, Cable 70, WVHZ-DB Washington; the legal line, the sonic logo to hear, the voices, the announcer on duty, the promo rate). On air: an ID, the sports break (holding or not) or a promo, else what is on master; the next break, what it plays and between what, its words, and the next promo. Every ident as a card: the station ID and the Sports ID (their end cards; click to play), then the promos and legal ID (their stills as they would read now; click for the promo preview with its live text), each marked on air, next break or cued, with its length, voice and last airing. What aired: IDs and announced breaks (continuity, master's last ID) and promo plays, newest first. Settings stay on Presentation (Station ID, Continuity, Promos), linked from the tab. |
| `/engineering` | A health board for every part, the viewer monitor, Roku capture, how it works (a live map of what runs where), an API explorer for every endpoint (writes ask first), and this browser's interface settings, including live polling stats. |
| `/sonic` | The sonic identity sheet, in the shell. |
| `/calibration` | Moved to TV Thing's `/tv/roku.html` on 2026-10-06; redirects to Engineering › Roku. |

## Shared code

- **`vv.css`** holds the tokens and every part: panels, lamps, chips, buttons (`take` is red,
  for putting things on air), switches, tabs, tables, dialogs, toasts, the machinery and the
  palette. The fonts are bundled in `static/fonts`.
- **`vv.js`** is loaded right after `<header class="topbar" data-page="…">` and draws the top
  bar: the wordmark, the six areas, the tally (what master has on air), the station clock, the
  palette and the Machinery switch. It also provides `window.VV`:
  - `VV.api(path, body?, {method, timeout, raw})`: one fetch wrapper. The API key is kept in
    localStorage, so one sign-in covers every page. A 401 opens the sign-in dialog.
  - `VV.watch(path, ms, cb)`: a shared poller. Everything on a page that wants
    `v1/master`, say, shares one request. It pauses while the tab is hidden, and
    Engineering → Interface lists every poller live.
  - `VV.h`, `VV.fill` (DOM), `VV.fmt` (times, durations), `VV.toast` and `VV.confirm`.
  - `VV.label(target)`: names a target the same way on every page.
  - `VV.commands.add(...)`: adds palette entries and keys.
  - `VV.machinery.set(on)`.
- **`onair.js`** provides Play now, Add to queue and Schedule; the "plays until" dialog; the
  sports list; and the end-time dialog for a held take. **Add to queue** on a live source
  (a channel, game or listed program) opens the dialog first to ask how long it plays; a
  recording goes straight to the end of Up next, since it plays to its end. It also names
  guide rows and library files as items (`OnAir.guideItem`, `OnAir.recordingItem`), the same
  on every page.
  Sports includes **College Football (Power 5)** (`ncaaf`): games involving an ACC,
  Big Ten, Big 12, SEC or Pac-12 team, plus Notre Dame, using ESPN's current conference
  memberships. Nonconference opponents are included. The browser shows the next ten
  days, suggests configured broadcast channels, and schedules a four-hour window;
  live game status keeps a game on air through overtime until it finishes.
- **`find.js`** is the search box in On Air's Up next (`Find.box()`, passed to
  `UpNext.mount(host, {find})`; `/` focuses it). It loads every source's listings on first
  use and matches channels, games, recordings and later programs as you type (↑/↓, Enter,
  Esc). Picking a live source opens the plays-until dialog; a recording is added at once; a
  later program opens Schedule.
- **`queue.js`** is the Up next rundown, mounted on On Air in full and on Sources in compact form.
  It shows what will actually air: the playback projection (`GET /v1/playback`, as on the
  Schedule page) from what is on now, each row naming its Up next entry (with Move, Remove,
  Retry). A sign-off is one quiet *OFF AIR · test card* line, not an entry. Entries that
  the estimates leave out (a slot that ends while a game runs on, OFF AIR giving way) fold
  into **Won't air**, with the reason and Remove. The projection is fetched every 10 s, and
  again at once when what waits changes.
- **`bar.js`** is the crawl bar mimic, with master's colours at master's speed.
- **`continuity.js`** is the continuity panel.
- **`promos.js`** is the promos panel (Presentation), and its promo preview and file fetcher, which **`idents.js`** (Ads › Idents) uses too.
- **`testcard.js`/`.css`** draw the off-air test card.

## Keys

| Key | Does |
|---|---|
| Ctrl/⌘-K | Command palette (go anywhere; pause or resume Up next; run a crawl segment; …) |
| `?` | Keyboard shortcuts |
| `m` | Machinery on or off |
| `/` | Search on this page |
| `g` then `1`–`6` | Go to a page |
| `w` | Watch master (on On Air) |
| `r` | Refresh listings (on Sources) |

The palette can be turned off under Engineering → Interface.

## Serving

`api.py` serves the pages in `PAGES` from `static/ui/<name>.html`. Any
`/static/ui/<name>.(js|css)` is served from disk without a key. New UI files therefore need
**no restart**; only a new page name or a new route does. `MOVED` lists the old addresses and
where they redirect. Every page is public (it contains no data); every `v1/` call needs the
key when one is configured. URLs are relative, so the UI works the same at `:6970/` and
behind Apache at `/vizelvision/`.

## Tests

- **`tests/ui_harness.cjs`** loads the real pages and scripts. It answers the API from
  `tests/fixtures/ui/*.json` (live responses, trimmed) under the `/vizelvision/` prefix, and
  records every write. The clock is fixed at the fixtures' moment.
- **`browser_ui_pages.cjs`** checks every page at 1440 and 390 px: no errors, no unknown
  endpoints, no sideways scroll, and no writes from just looking. It also covers the palette,
  the keys, the machinery switch and the old-link forwarding.
- **`browser_ui_air.cjs`, `browser_ui_sources.cjs`, `browser_ui_schedule.cjs`,
  `browser_ui_crawl.cjs`, `browser_ui_presentation.cjs` and `browser_ui_idents.cjs`** check what each button sends,
  body for body. Presentation's suite also covers Engineering.
- **`browser_ui_admute.cjs`, `browser_ui_ads.cjs` and `browser_ui_my_ads.cjs`** do the same
  for the three tabs of Ads. The Ad database's suite also covers the tabs themselves.
- Calibration is TV Thing's now (its `roku.html`), with no browser suite here.
- **`browser_master_media.cjs`** watches real master HLS on On Air across a cut. It is run by
  `tests/master_preview_integration.py`.

Run any of them with `node tests/<file> /path/to/playwright`. `tests/test_ui.py` checks that
every page loads the core first and only asks for UI files that exist, and that every old
address redirects to a page.

The previous pages, scripts and browser tests are in `state/deploy-backup-20261001-222943-ui-rebuild`.
