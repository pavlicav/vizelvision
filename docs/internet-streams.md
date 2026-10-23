# Internet streams

The source ID is `internet`. It airs live streams from the web that TV Thing relays (TV
Thing's `internet_streams.py`, since 2026-10-23). The first is channel 29, **Pentulive**,
Yle Areena's puppy cam. A target names the stream by its TV Thing ID:

```json
{
  "source_id": "internet",
  "channel_id": "pentulive"
}
```

Use it like any other channel: **Play now**, **Add to queue** or **Schedule**, or
`POST /v1/master/prepare`. Queued, it is a live channel: it asks how long it plays, and
it stays on until then (or until the next timed entry).

## Adding a stream

Add it to TV Thing, not here. A stream listed in TV Thing's `internet_streams.json` (and
numbered in its `lineup.json`, or given the first free number in 370–379) shows up in
VizelVision by itself, the next time the source catalog is read (`catalog_cache_seconds`).
Nothing in VizelVision names a stream.

- `GET /v1/sources` lists `internet` as available while TV Thing lists at least one stream.
  Its count is the number of streams.
- `GET /v1/sources/internet/programs` lists them, from TV Thing's `GET api/v1/sources`
  (`lineup.internet`). Each row has the stream's `id`, its TV Thing `number` (29), `name`,
  and `note`. Live streams have no listings: `now` and `upcoming` stay empty, and the guide
  says `kind: "streams"`.
- A stream ID is lowercase letters, digits and dashes, as TV Thing's are. A row with any
  other ID is left out.

## Playing

The master worker opens `stream/internet/<id>/index.m3u8` on TV Thing
(`roku_stream/internet.py`, `StreamLease`). TV Thing keeps that URL fixed while the
upstream URL and its CDN token change. No tuner, lock or encoder is involved, so a stream
prepares beside whatever is on air, the antenna and the Roku included. Like library files,
any number can be open at once.

- **Preparation** asks the relay once. A stream that is not live fails with TV Thing's
  reason, for example *TV-Thing cannot play pentulive: Yle Areena has nothing live for
  1-78104441*. It does not wait for the decoder to time out.
- **Decoding** works as for an antenna channel's HLS (`DecodedInput`, uridecodebin).
  GStreamer 1.22 takes Yle's separate audio rendition and picks a variant itself. The
  stream needs both picture and sound, so an audio-only stream would not get ready.
- **A stall** holds the last picture for 8 s, as any live feed does. A stream that fails is
  put back on by the queue's feed recovery, from the same stream (there is no other source
  for it).
- **Ad mute** does not analyse internet streams.
- **The source preview** on Sources plays the prepared or on-air stream through the input
  preview proxy, like the antenna's.
