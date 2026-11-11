# Ads 5

A channel of nothing but ads: My ads' whole library and the station's idents, all day, on TV
Thing's channel 5 and on its own page, **http://viviserv/ads5/** (or `http://viviserv:6975/ads5/`
before the Apache route is in).

It is a fork of VizelVision's breaks. The ads are the same files and it picks them with the same
selector (the mix, `ad_mix.Mix`, or the shuffle or list order, `my_ads.Rotation`). Everything
else is its own: which ads are on, their limits, the mix's tuning and shares, the idents' switches,
the play log and every count. Nothing done on Ads 5 reaches VizelVision's breaks, and nothing done
there reaches Ads 5, except the library itself. An ad uploaded, renamed, levelled or given a kind
on the Ads page shows up on Ads 5 too; a new one is switched on, with Ads 5's default limit.

## The format

| Setting | Default | |
|---|---|---|
| `ident_every` | 5 (copied from VizelVision's promos) | an ident after this many minutes of ads; 0: none |
| `station_id_every` | 30 | the 30 s station ID this often; 0: never |
| `open_with_ident` | on | an ident first whenever the channel starts (someone tunes in) |
| `order` | mix (copied) | `mix`, `shuffle` or `list` |
| `longest_ad` | 0 (any) | ads longer than this many seconds sit out |
| `idents` | on | station promos and idents at all |
| `limits`, `limits_from`, `default_limit` | copied | as My ads' |
| `always_on` | off | keep airing with nobody watching (its plays count, though nobody saw them) |

The idents are the station promos (`ident/promos`), each with its own switch on Ads 5. A promo with
live text (Time & Temperature, the forecast, Heure décimale) is encoded again for each airing, with
its text drawn as it will air (the time then, VizelVision's temperature reading). "Only on" says
"Ads 5". Sports promos sit out (no game is on), unless queued by hand. Seasonal ones keep their windows.

## How it plays

```text
 My ads' files ─┐                                  ┌─ Next up (drawn 6 ahead: format → idents, station ID, ads)
 ident/promos ──┼─ ads5_prep: encode once ─ clips ─┤
 station ID ────┘  720p60 H.264 + AAC, −20 LUFS,   └─ the channel: segment by segment, timestamps shifted
                   2 s segments (state/ads5/clips)     to run on (ads5_ts) ─ live.m3u8 ─ TV Thing ch 5, the page
```

- **Encoded once, joined live.** Each clip is encoded alike, levelled as master levels it (the
  ad's `gain_db` + `trim_db`) and kept. The first pass over the library takes about half an hour
  (two workers at nice 19, plus one for whatever is about to air) and about 4 GB. Joining clips
  shifts each one's PTS, DTS and PCR to carry on from the last, and carries the continuity counters
  on. So the stream reads as one encoder's, with no discontinuities, and nothing is encoded while it plays.
- **Only while watched**, as Trains. A request for `live.m3u8` or a segment counts as watching.
  `index.m3u8` (TV Thing's 5-minute cache, VizelVision's keep-warm pings) does not. After 60 s with
  nobody watching it stops; the next viewer starts it at once, and the first segments are ready on
  the first request. The page stops watching while its tab is hidden.
- **Skip** cuts what is on air at the next segment. The viewer sees it 4 to 6 s later (the player's
  distance behind the live edge).
- A clip not encoded yet when its turn comes is passed over for the next one that is ready.

## The page

The player (sound off until you turn it on), what's on air (the one on *your* screen, from the
playlist's program dates), the next few minutes as a strip, the format (with an hour's wheel),
Next up (move, skip, draw again), the mix (each kind's share), and the library: every ad and ident
with Ads 5's switch, limit, counts, Next / Queue, and what aired. Its files are
`roku_stream/static/ads5/` and need no restart.

## The API (for agents and scripts)

```bash
curl -s viviserv:6975/ads5/v1/status                         # on air, Next up, aired
curl -s viviserv:6975/ads5/v1/library                        # every ad and ident, kinds, counts, clips
curl -s -XPOST viviserv:6975/ads5/v1/settings -d '{"ident_every": 2}'
curl -s -XPOST viviserv:6975/ads5/v1/settings -d '{"station_id_every": 15, "longest_ad": 60}'
curl -s -XPOST viviserv:6975/ads5/v1/ads/<id> -d '{"enabled": false, "limit": {"count": 1, "minutes": 60}, "boost": 2}'
curl -s -XPOST viviserv:6975/ads5/v1/promos/<id> -d '{"enabled": false}'
curl -s -XPOST viviserv:6975/ads5/v1/mix -d '{"kinds": {"transit": {"weight": 6}}, "tuning": {"rest_hours": 12}}'
curl -s -XPOST viviserv:6975/ads5/v1/next -d '{"op": "add", "kind": "ad", "id": "<id>", "next": true}'   # kind: ad, promo, id (station)
curl -s -XPOST viviserv:6975/ads5/v1/next -d '{"op": "skip", "key": "on-air"}'
curl -s -XPOST viviserv:6975/ads5/v1/fork -d '{}'            # copy VizelVision's settings again (the log stays)
```

Every change answers at once and draws Next up again (what you queued by hand stays). Bad values
answer 400 with what is allowed.

## Files

`state/ads5/`: `settings.json`, `mix.json` (tuning, each kind's share and wear, each ad's boost and
wear; the kinds themselves and which ad is which kind are read from VizelVision's `my-ads-mix.json`),
`plays.jsonl` (rows as `my-ads-plays.jsonl`'s, with kinds `ad`, `promo` and `id`), `queue.json`,
`clips/<kind>-<name>-<hash>/` (segments and `meta.json`), and `live/` (live-text renders, cleared after).

## Running it

```bash
systemctl --user status vizelvision-ads5          # deploy/vizelvision-ads5.service
journalctl --user -u vizelvision-ads5 -f
/usr/bin/python3 -m unittest tests.test_ads5       # fork, format, queue, a real splice, routes
```

A restart costs viewers a few seconds; nothing else depends on it. TV Thing lists it as
`internet ads5` on 5 (`internet_streams.json`, `lineup.json`), so VizelVision's **A channel
instead** picker offers it for breaks too. The Apache route is `deploy/ads5-apache.conf` (its
comment has the commands).
