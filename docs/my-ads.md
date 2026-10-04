# My ads

My ads puts your own ads on air in place of the commercial breaks that ad mute takes
off air. While ad mute has a break muted (mode **On**), master shows your ads with
their sound, one after another, until the programme comes back. When none of yours may
play, it shows a break card. The programme stays on screen small, in a framed corner
with a LIVE tab, so you see the moment it is back and can say "It's the show".

Everything is on the **My ads** tab of the Ads page (`/ads#my-ads`; `/my-ads` redirects
there).

## The flow

```text
 source ─▶ DecodedInput ─▶ shared programme delay ─▶ release ──────────────────────▶ master ─▶ viewers
                                                       │  ad mute's gain at this frame
                                                       │  ≥ ½: the programme, as always
                                                       └▶ < ½: the break (ad_break.py)
                                                            picture: my ad's frame, or the card
                                                                     + the programme, ¼ size, framed, LIVE
                                                            sound:   my ad's (crossfaded with the gain),
                                                                     or under the card the usual break bed

 helper thread: cue the next ad (decoded up to its first frames) ─ load the card ─ write the play log
```

- **Where it happens.** In `MasterMedia.release_programme`, where ad mute's gain is
  applied as each buffer leaves the programme delay. A break therefore starts and ends
  on the gain's own frames:
  - "It's the show" ends it as fast as it brings the sound back, mid-ad included.
  - A lapsed lease (the detector late or down) ends it too.
  - Shadow and Off never replace anything.
- **Ads are decoded ahead.** Each ad gets its own pipeline (`Reel`: a playbin with one
  picture and one sound, no subtitles), scaled and letterboxed to 1280×720. It decodes
  into appsinks that stop when full (about 12 frames), and frames and sound are pulled
  by the ad's own clock at master's pace. Nothing waits:
  - a slow ad holds its last frame
  - a failed ad gives way to the next ad or the card, and is left out for 10 minutes
  - the next ad is always cued (decoded up to its first frames), so it starts on the
    break's first frame, or the frame after the last ad ends
- **The corner.** The programme frame being replaced is drawn into the ad's frame at
  1/4 size (or 1/5, 1/3):
  - every 4th pixel of every 4th line, with a 4-pixel white frame and a red LIVE tab
  - bottom right by default, above the crawl and clear of the clock and the AD badge
  - in pure Python, about 1.5 ms a frame at 720p, and only during a break

  The plain AD badge is left off while your ad is on screen. The diagnostic badge,
  if switched on, still shows.
- **Sound.** An ad's sound replaces the programme's, crossfaded with ad mute's gain.
  Under the break card, the sound is ad mute's own break sound: silence or Cairo radio.

## Order and limits

- **Shuffle** (the default) plays every ad once, in a random order, before any plays
  again. A new round never starts with the ad that just aired.
- **In list order** goes top to bottom, then around again. **Shuffle the list** puts
  the list itself in a random order, once.
- **Limits** are per ad: at most N plays in any stretch of M minutes. The presets run
  from once every 15 minutes to once a day; **Custom** allows 1–50 plays in 5 minutes
  to a week. **Limit for new uploads** sets the limit each new upload gets.
- **What counts as a play:** a play counts towards a limit once half the ad has aired.
  An ad cut short by the programme's return before that does not count. While an ad
  airs, it counts already, so the next one cued respects its limit.
- **Sitting out:** an ad switched off, or over its limit, sits out. The page shows
  until when. With every ad out, the break card shows.

## Uploads

Drop videos on the page, or choose them: MP4, MOV, WebM, MKV, TS, AVI, MPEG and more,
up to 15 minutes and 4 GB each. The file is the request body
(`POST /v1/my-ads/upload?name=…`), streamed to disk. Then, at the lowest priority:
1. **ffprobe** checks that it has a picture and is 1 s to 15 min long. Otherwise it
   is refused and deleted.
2. **Loudness:** EBU R 128 (`ffmpeg ebur128`) measures it. It is levelled to the
   station's −20 LUFS (as the station ID and the TV recordings), never past −1 dB true
   peak. A per-ad volume trim (±6 dB) adjusts that.
3. **Pictures:** four, at 15/40/65/90%, as the Ad database has.

## The break card

The station ID's end card (`ident/animation.py` at 27.0 s) with its banner reading your
words: STAY TUNED by default, or any 1–32 characters. The web app draws it (about half a
second, `my_ads.render_card`) before it tells master. You can also upload a picture of
your own (PNG, JPEG, WebP); it is letterboxed to 16:9.

## Files

Beside the master socket (`state/master-candidate/`):

| File | Contents |
|---|---|
| `my-ads.json` | settings and the ads, in order (the web app writes it; master reads it every second) |
| `my-ads/<id>.<ext>` | the ads as uploaded |
| `my-ads/<id>-<n>.jpg` | their pictures |
| `my-ads/card-<hash>.png`, `my-ads/card-own-*.{png,jpg,webp}` | the break card (the station card's words, or your picture) |
| `my-ads-plays.jsonl` | what aired: `{kind: ad, id, name, at, seconds, length, complete, counted[, error]}` and `{kind: card, at, seconds}` (master writes it) |

## The API

| Route | |
|---|---|
| `GET /v1/my-ads` | settings, each ad with `present`, `allowed`, `again` and `played` (hour/day/week/last), master's `status`, ad mute's mode, the last 80 plays |
| `POST /v1/my-ads` | settings: `enabled`, `order`, `pip` {enabled, corner, size}, `card` {text}, `default_limit` |
| `POST /v1/my-ads/upload?name=` | an ad (the body is the file) |
| `POST /v1/my-ads/ads/<id>` · `DELETE` | one ad: `name`, `enabled`, `limit`, `trim_db` · delete it, its file and pictures |
| `POST /v1/my-ads/order` `{ids}` · `/shuffle` `{}` | reorder · a random order |
| `POST /v1/my-ads/card-image?name=` · `DELETE` | your own card picture · back to the station card |
| `GET /v1/my-ads/file/<name>` | an ad (`<id>`), a picture, or the card, for the page |

Master's status (`GET /v1/master` → `my_ads`): `active`, `state` (idle/ad/card), the ad
on air and its position, `cued`, `card`, and the ads `left_out` with why.

## Tests

```bash
/usr/bin/python3 -m unittest tests.test_my_ads                  # settings, rotation, limits, store, routes, the break with stand-in ads
nice -n 19 /usr/bin/python3 tests/myads_master_integration.py   # a real master: ads, card, corner, sound, cut short, play log
node tests/browser_ui_my_ads.cjs <playwright>                   # its tab
```

## Deploying

Changes to `ad_break.py` or `master_media.py` need a master restart. New routes need a
web restart. Both drop what is on air, so restart only with nothing on air, then
`POST /v1/queue/resume`. The page's own files (`static/ui/ads.html`, `my-ads.js`) need no restart.
