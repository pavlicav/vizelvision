# Continuity announcements

At every break, the announcer on duty says what just played and what is next, over
the station ID, in the style of BBC continuity:

> That was the Phillies and the Braves. You're watching Vizel Vision.
> Coming up: the White Sox and the Astros. Stay tuned.

The ID keeps its picture and music. For that break only, its voice-over (DJ Low
Tide's usual lines) is replaced by the announcer's. The lines sit on the ID's four
voice cues (7.8, 12.9, 16.9 and 21.2 s) and end before its *Stay tuned* end card. If
the next source is slow, the ID holds that card ([station ID](station-id.md)).

## The Continuity tab (Presentation)

The controls are in Presentation's **Continuity** tab (`/presentation#continuity`; the old
`/continuity` and `/production#continuity` addresses redirect there). The panel is
`static/ui/continuity.js`; the On Air page's **Next break** tile shows the next break too.

- **Announce at every break** turns it on or off. Off, the plain station ID plays.
  The switch saves at once and leaves other edits unsaved.
- **Who is on duty**: follow the **duty roster** by hour, or one announcer all day. The
  roster is a 24-hour strip. Pick a personality under *Paint hours with*, then click or
  drag across hours. The announcer is chosen by the hour the break is expected to air, not
  the hour it was cued. An hour whose personality was removed falls back to the announcer
  on duty.
- **Next break** shows the lines cued for the next ID, with **Listen**.
- **Announcer personalities**: a name, a Deepgram Aura voice, style notes, and up to
  four lines. `{just_played}` and `{up_next}` are filled in at each break, in the
  announcer's language: a game is "the Phillies and the Braves", or "les Phillies et les
  Braves" for a French voice. A line naming something unknown is left out, such as
  "Coming up" before OFF AIR. **Listen** voices unsaved edits over the ID music. The voice
  list is Deepgram's catalogue (read once a day), grouped by language with accent and
  character. Choosing a voice in another language swaps default lines for that language's
  defaults; lines you wrote stay.
- **Recent announcements** lists what aired, and when.

The roster starts with Cairo Radio's three on-air personalities and their shifts, as its
public log (`/api/log`, the endpoint `radio_info.py` already reads) showed them on 30
September. VizelVision does not call Cairo at runtime; they are copied into its settings:

| Personality | Voice | Lines | Roster hours |
|---|---|---|---|
| DJ Low Tide (The Old Rock Show, Classical, Daytime Alt; the ID's voice) | `aura-2-orpheus-en` | That was … / You're watching Vizel Vision. / Coming up: … / Stay tuned. | 0–9, 13–18, 19–23 |
| The Daytime Announcer (The Morning Show) | `aura-2-zeus-en` | You've been watching … / This is Vizel Vision. / Next: … / Stay with us. | 9–11, 18–19 |
| Amélie (L'heure québécoise) | `aura-2-agathe-fr` | C'était … / Vous regardez Vizel Vision. / À suivre : … / Restez avec nous. | 11–13, 23–24 |

VizelVision is pronounced **"VIZZLE-VISION"**. The English lines on air write it "Vizzle
Vision" (changed in the settings), so the voices say it that way; the defaults above, in
`continuity.py`, still spell it "Vizel Vision".

Only DJ Low Tide's voice is Cairo's own. Cairo does not publish the other two, so their
voices were chosen from Deepgram's catalogue to fit: a deep, smooth announcer, and a
French host.

## How it works

`roku_stream/continuity.py` runs in the web app and checks every 20 seconds:

1. What just played and what is next come from the [playback projection](../README.md#programming-schedule),
   so they follow the queue's rules. After a game, what is next is a game already
   under way, Up next recordings, or the schedule. Games are said as "the Phillies
   and the Braves" (team nicknames from the MLB Stats API or ESPN). Nothing is cued
   while master shows the test card, because no ID plays then.
2. Each line is voiced once with Deepgram Aura in the announcer's voice and kept in
   `state/.../continuity/voice/` by voice and text.
3. ffmpeg mixes the lines over the ID's music bed, `ident/build/music.wav` (the jingle
   without its voice, made by `ident/build.py`), as the ID mixes its own. Deepgram's lines
   come back anywhere from −19 to −28 LUFS, so each is measured and set to −20 LUFS
   against the bed, where the ID's lines sit. The music eases down 7 dB by each line's
   first word and back up after it, the same depth however loud the line. The mix is
   levelled to −20 LUFS in two passes, like the ID. The ID's picture is copied unchanged
   into `state/.../continuity/<hash>.mp4`.
4. The master worker's `ident_file` command cues that file for the next ID only.
   After it airs, the worker goes back to the plain ID, and continuity cues the next
   break's announcement. `GET /v1/master` shows `ident.file` and
   `last_station_id.file`. A worker restart that drops the announcement gets it again.

The break before a sporting event is two IDs in one file. First comes the announcement
("That was the Yankees and the Rays. … Coming up: the Padres and the Brewers. Stay
tuned."), or the plain ID when announcements are off. Then comes the VizelVision Sports ID
("The following... is a presentation of Vizel Vision Sports."). The first half's end card
holds while the game's source is prepared, so the Sports ID opens the game once it is
ready. It plays even from the test card, where there is no "That was…". Continuity cues it
the same way, as `sports-<hash>.mp4`. See [VizelVision Sports](station-id.md#vizelvision-sports).
A game already under way gets the [join bumper](station-id.md#the-join-bumper) in the Sports
ID's place, its score read over it, which the source coordinator asks for when the game
is ready.

A failure to voice or mix (no key, network) leaves the plain ID and shows the reason in
the tab. A rebuilt ID or music bed changes the file identity, so announcements are
mixed again.

## Settings and API

- `continuity.keys_file` in the configuration: a `KEY=value` file with
  `DEEPGRAM_API_KEY` (read when a line is voiced; `DEEPGRAM_API_KEY` in the environment
  wins). The key is never logged or stored elsewhere.
- `state/.../continuity.json`: `{enabled, on_duty, duty: "roster"|"fixed", roster: [24 ids or null],
  announcers: [{id, name, model, style, lines}]}`.
- `GET /v1/continuity`: settings, `next` (with `break_at`), `recent`, `error`, `voices`
  (`{id, language, accent, tags}`), `default_lines` by language, `on_duty_now`, `hour`,
  `ready` (key, music bed, ID).
- `POST /v1/continuity`: save settings.
- `POST /v1/continuity/preview` `{announcer: id or {name, model, lines}, just_played?, up_next?}`:
  `{lines, audio}`. `GET /v1/continuity/audio/<name>` serves previews and announcements.

## Validation

- `tests/test_continuity.py`: settings, which lines are said, placement on the voice
  cues, the service's cueing, airing, turning off, a lost announcement, a voice
  failure, and a real ffmpeg mix (on its cues, above the bed, at −20 LUFS; lines 20 dB
  apart come out level, with the music 7 dB down under each and back up between).
- `tests/test_ident.py`: the worker plays an announcement once in place of the ID, and
  only continuity files may replace it.
- `tests/browser_ui_presentation.cjs`: the Continuity tab (the switch saves only itself, roster painting,
  saving, the next break naming the teams).
- On the real ID with DJ Low Tide, the announcement measured −20.1 LUFS like the ID,
  with section levels within about 1 dB of it.
- On 1 October the lines were levelled. Before, each line kept Deepgram's level plus
  6 dB, and the music ducked by however loud the line was. Aired lines ranged from −21.7
  to −28.1 dBFS RMS, and a quiet first line ("C'était News at Noon.") sat 2.9 dB under the
  music. Remixed, the same lines range from −25.6 to −27.6 dBFS, against −26.7 to −27.8
  for the ID's own voice, and no line sits under the music.

## On air

Deployed on 30 September at 17:38 (web app and master worker), and switched on at 17:40.
The first cued announcement was DJ Low Tide after the White Sox and the Astros: "That was
the White Sox and the Astros. You're watching Vizel Vision. Stay tuned." ("Coming up" was
left out because OFF AIR follows.)
