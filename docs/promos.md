# Station promos

VizelVision's own 5- and 10-second bumpers (idents and promos) play in the breaks that
ad mute takes off air, alongside [My ads](my-ads.md). **At least one plays every 15 minutes,
as breaks allow.** The settings are on the **Promos** tab of the Presentation page
(`/presentation#promos`; `/production` redirects there). **Ads › Idents** (`/ads#idents`)
shows them beside the station ID and the Sports ID, with what is cued and what aired.

## The five

| Promo | Length | What it is | Voice |
|---|---|---|---|
| **Time & Temperature** (`time-temp`) | 10 s | The 1970s station-break slide: the Washington skyline at dusk under a striped retro sun, a cream character-generator panel, and the time and temperature **as they are when it airs**, flipping in on the vibraphone's open logo. Easy-listening bossa, tape wow, film grain and gate weave. | The Daytime Announcer (`aura-2-zeus-en`): "Vizel Vision time... and temperature." |
| **You're Watching VizelVision** (`watching`) | 10 s | The station ID's jingle remixed for hype: a "you're, you're, you're" stutter build, the drop, the TV emblem bouncing on a spinning sunburst over a checkerboard, the wordmark stomping in on sixteenths, the stadium horn and the crowd, the lift to the closed logo. | DJ Low Tide (`aura-2-orpheus-en`), the ID's voice: "You're watching" / "Vizel Vision!" |
| **Only on VizelVision** (`only-on`) | 10 s | An orange cat pushes a mug off a side table, one nudge per note of the logo, stares you down while it teeters, and KRSSH. It leaps onto the TV and loafs there, and the set comes on showing **the programme on air**. ONLY ON VIZELVISION, a "mrrp" and a slow blink. | Ophelia (`aura-2-ophelia-en`): "{The programme}... only on Vizel Vision.", voiced for each programme |
| **Legal ID** (`legal`) | 5 s | "This is VizelVision 19, Cable 70." The emblem, a chrome 19 and CABLE 70 in its red box, and along the bottom, plainly, as a legal ID has them, **WVHZ-DB  WASHINGTON** under a hairline rule. | Jupiter (`aura-2-jupiter-en`), the Sports ID's baritone |
| **Press Start** (`press-start`) | 5 s | VizelVision as an 8-bit game: the TV sprite bumps a ? block, a V coin pops out (+19), the wordmark drops in and the closed logo plays on square waves. PRESS START. | none |

All five use the [sonic identity](sonic-identity.md): the open logo (C E G A) for "there's
more", the closed logo (D F# A D, a whole step up) for the answer, 120 BPM, −20 LUFS, a
silent tail. They also share the ID's Memphis look, chrome and TV emblem.

## When they play

- **Only in breaks ad mute takes off air**, which needs its mode **On**. They play in My ads'
  place, with the programme in the corner (My ads' picture-in-picture) so its return is seen.
- **Every N minutes (15 by default):** once that long has passed since the last promo started,
  the next break **opens** with one. If no break comes, the first break after that gets it.
  A promo cut short by the programme's return before half of it airs does not count, so the
  next break tries again. A promo that started before the break ended counts once half of it
  has aired, as an ad does.
- **Fill** (off by default): when My ads has nothing left to show (none uploaded, or all over
  their limits), promos stand in before the break card, each at most once a break.
- **My ads switched off:** a due promo still opens the break. The break then carries on as ad
  mute has it: the muted programme under its break sound.
- **The order** is shuffled: every promo once before any repeats, and never the same twice
  running.
- **Sitting out.** A promo switched off on the tab sits out. So does one whose live text isn't
  known: no temperature reading in the last 3 hours, or no programme name (a bare channel, or
  the web app not writing for 5 minutes). A promo that fails to decode is left out for 10
  minutes.

## Live text

Time & Temperature and Only on VizelVision carry text that is true when they air. Master
draws it over the promo's frames as they decode, so the video itself is built once.

- **Which text** comes from the promo's manifest (`ident/promos/<id>.json`, `overlays`):
  a field (`time`, `ampm`, `temperature`, `place`, `programme`), a box, when it shows, its
  style (font, size, colour, shadow, alignment, up to two lines), and how it enters (`flip`,
  `pop`, `fade`) and leaves (`fade`).
- **The pictures** come from `roku_stream/promo_overlay.py` (pycairo). It fits the text to its
  box (shrinking it, then wrapping to two lines, then an ellipsis) and renders it once per
  text.
- **On master**, `ad_break.PromoReel` decodes the promo like an ad, with GStreamer's
  `overlaycomposition` before its appsink. Each frame, the draw callback places the text's
  rectangle by the frame's own time and GStreamer blends it into the I420 frame in C. Frames are
  decoded about 0.2 s ahead of air, so the time is right to the second. If the text fails, the
  promo plays without it, and `my_ads.promos.draw_failed` in `GET /v1/master` says why.
- **The values** come from the web app's `PromoDesk` (`roku_stream/promos.py`), which writes
  `promos-now.json` beside the master socket every minute, and at once on a change:
  - **temperature**: api.weather.gov's latest reading at the crawl's weather station (its ZIP
    setting if one is set; Reagan National by default). It has its own `WeatherFeed`, fetched
    every 10 minutes and only while a promo shows the temperature.
  - **programme**: the playback projection's programme on air. A game reads "Lions at
    Panthers". Otherwise its title is used. A bare channel has no name, so Only on VizelVision
    sits out.

## A voiced name

Only on VizelVision says the programme's name. When the programme changes, the desk has the
line *"{The programme}... only on Vizel Vision."* voiced in Ophelia's voice. It uses the
continuity announcements' Deepgram client and voice cache (`state/master-candidate/continuity/voice`).
The desk places the line in the promo's voice slot (from 5.6 s, or earlier for a long
name, as early as 5.2 s, ending by 9.1 s). It mixes the line over the promo's music without
its voice (`ident/promos/only-on-music.wav`) with `continuity.mix`: the line levelled to
−20 LUFS, the music ducked 7 dB, the whole levelled to −20 LUFS, and the picture copied.
The copy is `promos/only-on-<hash>.mp4` beside the master socket, and the newest 12 are kept.
Until the copy is ready, or if Deepgram is unreachable (retried after 10 minutes) or the
name is too long to say in time, the promo airs as built, with its own line, "Only on Vizel
Vision!", and the name on the TV.

## Building them

```sh
/usr/bin/python3 ident/promos/build.py [ID ...] [--keys-file /path/to/keys.env] [--workers 2]
/usr/bin/python3 ident/promos/build.py --still only-on 7.6 frame.png    # one frame, live text drawn
```

- `ident/promos/script.json`: the voice lines, by promo. Only new or changed lines go to
  Deepgram (`ident/voice.py`), and they are kept in `ident/voice/promo-*.wav`.
- `ident/promos/music.py` (numpy, scipy: miniconda's Python): the five cues, from
  `ident/jingle.py` and `ident/sonic.py`, plus a vibraphone, pizzicato, a slide whistle, a
  smashing mug, a meow, a projector clack and chip channels.
- `ident/promos/<id>.py` (pycairo): each picture. Hit points are constants at the top, and
  `music.py` follows the same times.
- `ident/promos/common.py`: grain, the iris, fades, a 5×7 pixel face, and the ID's kit.

Everything runs at the lowest priority. The build writes `<id>.mp4` (60 fps, H.264 CRF 21
capped at 9 Mbit/s, AAC, −20 LUFS, the ID's touch of VHS), a still (`<id>.png`) and,
last, the manifest. Master reads the manifests every second and picks up a rebuilt promo
by itself. A promo cued from the old file is re-cued.

## Files

| Where | What |
|---|---|
| `ident/promos/<id>.mp4`, `.png`, `.json` | the promos, a still of each, their manifests |
| `ident/promos/only-on-music.wav` | Only on VizelVision's music without its voice, for the voiced copies |
| `promos.json` (beside the master socket) | settings: `enabled`, `every`, `fill`, and each promo's `enabled` (the web app writes it) |
| `promos-now.json` | the live values: `at`, `temperature` {f, c, place, station, observed_at}, `programme` {title, spoken, variants} |
| `promos/<promo>-<hash>.mp4` | the voiced copies |
| `my-ads-plays.jsonl` | promos are logged with My ads' plays: `{kind: promo, id, name, at, seconds, length, complete, counted}` |

## The API

| Route | |
|---|---|
| `GET /v1/promos` | settings, each promo (manifest, `enabled`, `ready`/`why`, plays today/this week/last), the live values and errors, master's status, ad mute's mode, `last`, `next_due`, `due`, the last 40 plays |
| `POST /v1/promos` | `{enabled, every, fill}` |
| `POST /v1/promos/promo/<id>` | `{enabled}` |
| `GET /v1/promos/file/<name>` | a promo, its still or music, or a voiced copy |
| `GET /v1/promos/still/<id>.png` | its still with its live text as it would read now |
| `GET /v1/promos/overlay/<id>/<n>.png` | one live text as it would read now (the page's preview player lays them over the video) |

Master's status (`GET /v1/master` → `my_ads`): `state` is `promo` while one airs (with
`promo`: id, name, duration, position, since), and `pass` for a break with My ads off.
`promos` has {active, cued, last, due, draw_failed}.

## Tests

```bash
/usr/bin/python3 -m unittest tests.test_promos     # settings, library, values, live text, the desk, the break, the routes
/usr/bin/python3 tests/promos_master_integration.py  # a real promo with live text decoded through PromoReel
```

## Deploying

`ad_break.py`, `master_media.py` and `master_worker.py` need a master restart. The routes
and the desk need a web restart. The page (`static/ui/promos.js`, `presentation.*`) needs
no restart. Promos ship **on**, every 15 minutes, fill off.
