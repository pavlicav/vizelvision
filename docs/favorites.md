# Favorites

Crawl › Favorites (`roku_stream/favorites.py`) is one ranked list of favorite teams, and of
whole playoffs ("MLB · All playoffs, through the World Series", "College Football · All
bowls and playoffs"), best first. It lives in `favorites.json` beside `queue.json`; the
crawl's old followed teams seeded it on 2026-10-17.

- **Scores:** the crawl's Scores segment shows the favorites' games today, live ones first,
  each part by rank.
- **On air** (the switch): each favorite's game in the next 7 days goes on the Schedule
  whenever it is on a channel VizelVision gets: from its start (at once if under way) for
  the league's usual length, then back to the schedule after the final. The planner checks
  every 10 minutes and right after a change. Games on no such channel (ESPN+ only), or
  without a start time yet, are listed on the tab instead.

## Ranks

A favorite's game is a normal-priority game show that ranks a little above normal, the
higher on the list the more (`programming.show_rank`, `FAVORITE_SPAN`):

| What | Rank |
| --- | --- |
| High show | 2 |
| A take put on by hand with an end time (`source_queue.HELD`) | 1.5 |
| Favorites' games | 1 + 0.4 × (n − place) / n |
| Normal show, grid block, an entry queued by hand | 1 |
| Low show | 0 |

So when games overlap, the higher favorite cuts in on the lower at its start, and a lower
one starting during a higher one waits for its final and joins in progress if it is still
on. A favorite's game takes over from regular programming but never cuts a take you put
on by hand; it follows when the take ends. Two shows may not start together, so a
favorite's game starting with another show starts a second before it, or a second after
one that outranks it.

## What the planner changes

- It only adds and removes the game shows it made (`added_by: "favorites"`, with the
  `favorites` the game is: both teams', and the league's playoffs after the regular season).
- Ones that have not started come off when none of their favorites is on the list or the
  switch is off. Ones under way stay.
- A game it scheduled that someone removed from the Schedule is not put back
  (`planned` in `favorites.json`). Schedule it by hand to air it.
- A game already scheduled by hand is left alone.

ESPN lists Peacock exclusives as Peacock. YouTube TV carries them on NBC Sports Network,
so Peacock maps there (`sports.NETWORK_ALIASES`, `baseball._YTTV_NETWORKS`).

## API

- `GET /v1/favorites`: `{favorites, air, games, checked_at, errors, days, check_minutes}`.
  Each game has `status`: `scheduled`, `by_hand`, `off` (would go on air), `removed`,
  `tbd`, `no_channel` or `error`.
- `POST /v1/favorites`: `{favorites?: ["mlb:playoffs", "ncaaf:127", ...], air?: true}`.
  A favorite is `league:<ESPN team id>` or `league:playoffs`.

Tests: `tests/test_favorites.py`.
