# NHL on ESPN Unlimited

The source ID is `nhl`. It airs the NHL games that ESPN Unlimited streams inside YouTube
TV. That covers out-of-market games (NHL Power Play) and ESPN+ exclusives. YouTube TV's
main plan has included ESPN Unlimited since 2026-09-01. TV Thing's Roku lane learned to
find these games on 2026-10-22 (branch `nhl-guide`), and first played Mammoth at Kraken.
The source's channel ID is the ESPN NHL game ID, and its date is the game's Eastern date:

```json
{
  "source_id": "nhl",
  "channel_id": "401802671",
  "date": "2026-10-22"
}
```

Use the target like any other Roku game: **Play now**, **Add to queue** or **Schedule**,
or `POST /v1/master/prepare`. Queued, it holds master until the NHL final, through the
same end-of-game gate, backup program and return to the schedule as Sunday Ticket. A
game joined in progress gets the "We now join…" bumper ("in the second period").

## Which games

`roku_stream/espn_unlimited.py` mirrors TV Thing's `nhl_on_espn_unlimited`. An NHL game
streams on ESPN Unlimited when ESPN's scoreboard lists a national **ESPN+** broadcast. A
game on ESPN, ABC, TNT or NHL Network has no ESPN+ broadcast, so it airs from that
channel instead. The function returns:

- **`exclusive`**: an ESPN+ exclusive, also listed on Disney+ or Hulu, with no regional
  broadcast to black it out;
- **`blackout`**: the teams whose home market may black the game out, and where. The
  markets are `WSH` (DC) and `DET` (Lansing). YouTube TV places the Roku in one or the
  other, and it moves between them;
- **`home`** and **`away`**: the regional broadcasts whose commentary those streams carry.

Each NHL game in the sports catalog (`SportsCatalog._suggest`) gets two fields:

- `espn_unlimited`: the stream, as above;
- `espn_unlimited_target`: the target, set only when the game streams there.

For an ESPN+ game that no configured channel carries, `suggested_target` is the `nhl`
target. The note says what kind of stream it is, and where it may be blacked out. A game
that is also on a configured channel keeps that channel as the suggestion, and the
Schedule's source picker offers ESPN Unlimited beside it. **Favorites** schedule a ranked
team's ESPN+ games from the suggestion, so they air on `nhl` by themselves. On
2026-10-23 that meant six Maple Leafs and Red Wings games in the next week, which until
then had been *no channel*. The first is Maple Leafs at Oilers, Saturday at 7 PM ET.

`GET /v1/sources/nhl/programs?date=YYYY-MM-DD` lists the day's ESPN Unlimited games:

- one row per game, its program id `nhl:<game id>`;
- each with its `espn_unlimited` details;
- live games under `now`, games still to come under `upcoming`.

Sources shows the source once TV Thing offers `nhl` in its source list, so it stays hidden
until TV Thing's `nhl-guide` branch is deployed. Sports, Schedule and Favorites offer `nhl`
targets regardless. Until that deploy, TV Thing refuses them, and Up next shows its words
(*TV-Thing refused tune: …*).

## Preparation

The coordinator first resolves the game. The ESPN scoreboard must list it on that date
with an ESPN+ broadcast. If it does not, the error is *This NHL game is not on ESPN
Unlimited; choose the channel carrying it*, and the Roku is not moved. Then the
coordinator posts `POST api/v1/tune {"source": "nhl", "channel_id", "date", "token"}` to
TV Thing, under the Roku lane's lock, and follows the navigation.

TV Thing then does the following:

1. It opens YouTube TV's ESPN page and goes to its Live section.
2. It moves down the rows, one per sport, to the NHL row.
3. It reads the cards across the row to find the game. A game has two adjacent streams,
   away then home; an exclusive has one.
4. It prefers the home stream, unless a crossed-out eye on the card shows that stream is
   blacked out.
5. It verifies that the game plays.

A cue takes 3–4 minutes. A queued game prepares up to 5 minutes before its release, as
any Roku entry does.

## Refusals and retries

TV Thing's reasons reach the entry in Up next (Play now goes through Up next too) in its own words:

| TV Thing | What VizelVision shows | Retried? |
| --- | --- | --- |
| `espn_game_not_listed`: no live NHL row, or the game is not on it | *The Roku could not find it: … it may not have started* | Yes, up to 5 tries (`SLOW_START_ATTEMPTS`) |
| `espn_game_blacked_out`: blocked on every card, found before Select | *… is blacked out on YouTube TV where the Roku is* | No |
| `program_blocked`: the player shows "This program's blocked in your area" | *YouTube TV blocks this program where the Roku is (a blackout)* | No |
| A refused tune (HTTP 4xx), e.g. not an ESPN+ game | *TV-Thing refused tune: …* | Retried like any failed preparation |

- **A game not live yet is retried.** The ESPN page lists a game only once its stream is
  live, so the release may come before it shows up. Each attempt is minutes of Roku, so
  the game gets 5 tries, fewer than Sunday Ticket's 10.
- **A blackout is never retried.** A blackout raises `tv_roku.RokuRefusedError` (code
  `roku_refused`). The queue blocks the entry at once with TV Thing's message, instead of
  walking the ESPN page again for the same answer. Choose a channel that carries the game,
  or skip it.
- **How a blackout is recognised.** TV Thing's operation reports `espn_game_blacked_out`
  only as `navigation_failed`, so the blackout is recognised by its wording.
  `program_blocked` keeps its own code.
- **Error bodies.** `TvControl` now reads TV Thing's error body on any HTTP error, so a
  refused request names its reason instead of "HTTP 400". It keeps the error's `code` in
  the exception's `details`.

## Limits

- **No antenna backup.** ESPN Unlimited is on no antenna station, so a cue that is late
  waits for the Roku. Feed recovery puts it back on from the same source, unless the
  antenna's guide happens to name the game.
- **Blackouts depend on YouTube TV's market.** VizelVision cannot know in advance where
  YouTube TV places the Roku. The schedule's note only warns that a Capitals or Red Wings
  game may be blacked out. TV Thing finds out on the card.
- **Deploying.** It needs TV Thing's `nhl-guide` deployed, a `vizelvision-web` restart and
  a `vizelvision-master` restart. The master worker checks a Roku input's source against
  `ROKU_SOURCE_IDS` too, so until it restarts it refuses an `nhl` input. Restart both
  only when nothing is on air.
