# Thursday Night Football on Prime Video

The source ID is `thursday-night-football`. Its channel ID is the ESPN NFL
game ID, with the game's Eastern date. It appears in Sources, NFL Sports,
and the game source picker in Schedule. Prime broadcasts are suggested from
the schedule's broadcast metadata, including special Friday games; a
Thursday date alone does not identify a Prime broadcast.

```json
{
  "source_id": "thursday-night-football",
  "channel_id": "401872964",
  "date": "2026-10-01"
}
```

Use that target with the existing queue or `POST /v1/master/prepare`.
Preparation uses the shared Roku navigation guard, capture, selection lease,
and contribution checks. Queue a game until its NFL final to retain the
existing backup/return-to-schedule behavior. The diagnostic route
`POST /v1/thursday-night-football/play` takes `game_id` (integer) and `date`;
it cues the source Roku without taking it to master.

## Prime metadata and Roku behavior

There is no supported consumer Prime playback API used here. The resolver
reads the JSON hydration data delivered by Prime's public
[NFL page](https://www.primevideo.com/-/en/tournament/amzn1.dv.icid.8dc09428-4ec1-49d5-80a9-73d52c5f7ad6)
and the matching event's detail page. Requests are bounded to 12 seconds
and 8 MiB each. It requires both team names, one unambiguous event on the
correct Eastern date, and Prime's live status. Schema changes, unavailable
catalogs, upcoming broadcasts, and replays produce an error before launch.
This is an observed public-page format, not an Amazon API compatibility
guarantee. No Amazon credentials or cookies are collected or stored.

The installed Prime Video app is discovered by name (observed Roku ID `13`).
The controller launches it with `contentID=<event ASIN>&mediaType=live` using
[Roku ECP](https://developer.roku.com/dev/docs/external-control-api).
A fresh Home/launch clears previous content. Two consecutive fresh capture
observations must show both requested teams and `LIVE Main Broadcast` while
Roku reports Prime Video video playback. An accepted launch or generic
player `play` state alone is insufficient. Up reveals the player overlay
when needed. Controls are allowed to fade before the final capture.

The observed profile chooser may be accepted only when the configured name
and the enlarged first profile's focus ring are visible. Configure
`"prime_video": {"profile_name": "Vivian"}` (the default), or use an empty
name to leave selection to the operator. Unrecognized profiles, sign-in,
and subscription prompts stop with an actionable error. Complete those in
Prime on the Roku and prepare again. The controller never enters credentials
or accepts a trial/subscription purchase.

## Verification

On October 1, 2026, the public catalog resolved Steelers–Browns to
`B0GZ57JWXN`. The source Roku's Prime Video `16.0.361` accepted the live
deep link. After selecting the visibly focused Vivian profile it played
the live main broadcast, without a new login. Captured profile and player
overlay frames are regression fixtures. This does not establish support
for replay selection, other sports, alternate broadcasts, or other profile
layouts.

Focused checks include catalog/date/team validation, refusal of wrong
content and audio-only playback, profile/login handling, source and queue
integration, and the browser's game source selection.
