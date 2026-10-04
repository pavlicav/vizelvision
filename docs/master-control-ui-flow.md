# Master Control: source previews and take-to-master

> Superseded on 2026-10-01 by the control-room UI ([web-ui.md](web-ui.md)): Master Control became
> **On Air** (`/air`) and **Sources** (`/sources`). The flow below is kept as history.

September 16, 2026. Revised direction from operator feedback. The first source-preview increment is implemented and deployed on September 16. The worker still supports on-air plus one prepared candidate.

September 23 update: the prepared-source action is labelled **Take to master**, with a second button beside the master summary. It only takes an already-prepared source.

Later September 23 update: YouTube TV and MLB share one **Roku** menu and grouped channel/game dropdown. Its **Last known** line shows the verified selection and timestamp. **Take to master** can reuse a matching verification up to 15 minutes old, reconnecting decoded media without navigation when necessary. **Prepare Roku** explicitly navigates again. Queue preparation automatically reuses matching recent state. See [Roku preparation history and API](roku-master.md).

September 26 update: each source card also has **Prepare & take** (`POST /v1/master/prepare-take` with the same target as Prepare). It is one operation: prepare the selected channel, and cut to it as soon as the worker has verified its audio and video -- the same prepare-then-take path a queue entry uses, but started by hand, so it pauses the queue like any manual take. While it runs the card reads "Preparing · takes to master when ready…". It never takes an input that is not ready, and Cancel before the take leaves master where it was. For the Roku it reuses a matching recent verification, as queue preparation does, instead of navigating again.

September 30 update: **Up next is the only way on air.** The page no longer has Prepare, Take to master, Prepare & take or Library Play now. Each source card has **+ Queue** for its selected channel or game, and the composer's **Now · front of Up next** puts it on as soon as Up next prepares and verifies it. Cards preview a source while Up next prepares it and while it is on master. Up next starts with an **ON AIR NOW** row, which reads **OFF AIR · test card** when nothing is on, and shows the schedule's OFF AIR gaps as they come up. See [Up next is the only way on air](source-queue.md#up-next-is-the-only-way-on-air-september-30). The steps below describe the page before this change.

## Operator flow

1. Open Master Control. Keep the published master monitor and its on-air identity visible, with the queue beside it on desktop.
2. Open a source menu and choose a channel/game from its current/upcoming listings. Browsing does not tune.
3. Select **Prepare** on that source. Acquire the input, select the program/channel, and verify fresh audio and video. Show Preparing locally on the source card.
4. Once verified, show the source's own moving preview, channel/program identity, audio availability, and Ready state. Enable **Take to master** on that card and beside the prepared-source summary above the monitor. The summary action remains available when browsing another source. Preview playback and master playback are distinct and clearly labelled.
5. **Take to master** commits the exact prepared selection ID without preparing or tuning another channel. Changing the channel picker only changes the next Prepare action. Only the confirmed cut changes the on-air label. Manual takes pause queue release. Keep the master player attached throughout. A rejected request stays visible through status polling and is cleared by the next manual master command; it is never retried automatically against a replacement input.
6. **+ Queue** schedules that same qualified source/program through the existing queue. Queue release performs prepare/verify/send automatically; adding or browsing an entry does not change playback.

Muted previews are the default. Enable listening on one monitor at a time. A stale, expired, replaced or failed preparation disables its Take action, even if the browser still displays an old image. Pending operations also disable taking. Browser buffering/playback status is distinct from backend media readiness.

Roku live capture opens automatically while selecting a YouTube TV channel or baseball game, showing the Roku menus as navigation proceeds. It shares the existing capture reader without updating channel verification evidence. Once preparation finishes, the automatic capture closes and the qualified source preview takes over. Live capture remains available manually in either Roku source menu.

## Page layout

- Master monitor with current on-air source/program at the top.
- Source cards below it: source picker, current/upcoming listings, local preview, Prepare, Take to master, + Queue, and preparation/error state.
- Persistent Up next panel on desktop; queue sheet on mobile.
- Roku preview, source selection and related controls move inside the appropriate source menu. Retire the separate Roku Cue Sheet as a public page after those controls are available in the new page. Redirect the old page/root entry to Master Control; preserve required control APIs and saved queue/history.

## Source grouping

The Sources page groups YouTube TV and MLB under one Roku menu item and preview card. The dropdown groups channels and games by service; the guide retains provider names and queue targets retain their exact source/game IDs. TV-Thing analog is excluded from the source menu, cards and guide, including All sources, following operator feedback on September 18.

Source IDs, channel mappings, saved targets and hardware ownership are unchanged. Analog remains optional/testing. If analog will eventually carry Roku output, define the physical route and verification rules before representing the two capture paths as one program source.

MLB and YouTube TV use one Roku. Their cards must display that shared-resource constraint and invalidate the previous prepared selection when navigation changes the Roku. Preparing another channel on the same TV-Thing tuner also interrupts that tuner. Explain the fallback transition before preparation; there is no promise of an independent preview for two channels on one device.

## Delivered first increment

- Source cards with channel/game picker, Prepare, muted source preview, exact-ID Take to master, and preview retry. The current/upcoming guide and queue composer remain below the cards.
- Bounded source HLS proxy at `/v1/inputs/<selection-id>/media/index.m3u8`. It reuses the TV-Thing HLS or shared Roku contribution, validates the private worker selection before/after each fetch, rewrites manifest media references to opaque names, and bounds response size, concurrent readers and reference storage. MediaMTX session redirects are restricted to the same stream directory.
- Worker preview descriptors expire when readiness is lost, the candidate is replaced/cancelled, or refresh stops. No extra hardware capture owner is created.
- Players persist across status polling and a take of the same selection. Replaced/expired previews are cleared; only one monitor is unmuted at once. Playback buffering remains separate from backend readiness.
- YouTube TV navigation item. Roku capture diagnostics and input settings live inside the source area. `/` and `/cue-sheet` redirect to `/sources`, including the LAN proxy prefix. The archived HTML and required control APIs remain on disk for compatibility.
- Input recovery and capture diagnostics promoted with the preview backend. The original intermittent stall still requires observation; injected-pause validation does not establish its root cause.

## Validation

218 Python tests and five browser suites pass: source guide, master controls, Roku preparation, source queue and preview lifetime. The real GStreamer/MediaMTX fixture validates selection-bound HLS renditions/media, invalidation after navigation, exact-ID takes, queue release, and bounded recovery with the master publisher and reader unchanged. See `input-recovery-validation.json`.

Live deployment validation through Apache `/vizelvision/` confirmed the root redirect, advancing 1280×720 muted NBC preview, capture controls, mobile fit, and no browser/media-request errors. Opening diagnostics and closing the browser preserved the prepared selection. Master remained on fallback and the four saved queue records were retained, with release paused. A bounded two-hour diagnostic observer was started.

## Next steps

1. Observe the deployed capture and master recovery during sustained use and review recorded stall evidence.
2. Support multiple independently prepared inputs if required. Extend worker slots/leases and IPC/status with bounded warm-input lifetime and explicit release. Currently preparing another candidate replaces the previous one; taking releases the old on-air input.
3. Add advance preparation ahead of queue release, interrupted-take reconciliation and clearer schedule-overlap handling.
4. Validate analog when a test signal is connected. Hardware-specific analog testing remains intentionally pending.
