# Ad mute

Ad mute finds the commercial breaks in live programmes and takes their sound down. In
**Shadow** it only marks them, with a big **AD** badge on screen. It errs towards sound:
when it is unsure, or when any part of it is down, the programme stays audible.

Everything is on the **Ad mute** tab of the Ads page (`/ads#admute`; `/admute` redirects
there). The two quick fixes are also on
**On Air**, as buttons and the keys **u** and **a**.

## The flow

```text
 source ─▶ DecodedInput ─┬─▶ analysis copies ───▶ vizelvision-admute (the detector)
                         │   picture · sound          1. watch   black frames, bug, picture
                         │                            2. listen  Whisper words, sound fingerprints
                         │                            3. weigh   one logistic model, per second
                         │                            4. decide  seams + Viterbi -> P(ad)
                         │                            5. policy  mute / confirm / unmute
                         │                                 │
                         │         gain schedule + lease ◀─┘   ◀── quick fixes (u / a)
                         ▼                                          from the page / On Air
                  source selector ─▶ shared programme delay ─▶ gain ─▶ master ─▶ viewers
                                     (6 s with captions)       (or Cairo radio under it)

 learning:  confirmed breaks, spot by spot ─┐
            spots wedged in a pod ───────────┤
            MLB play-by-play (live) ─────────┼─▶ known-ads database ──▶ "this sound is an ad I know"
            recordings (admute.seed) ────────┘   (fingerprints)          (and "this is show sound": never)
            TV-Thing recordings of games ──▶ fingerprints + training labels (admute/truth/auto)
            your marks and fixes ─▶ admute-labels.jsonl (training data)
```

### 1. It watches ahead of you

- **Delay:** master holds the programme a few seconds before anyone hears it. That is
  the shared programme delay (`programme_delay.py`):
  - `lookahead + 1 s`, or 6 s with live captions on (see
    [live captions](live-captions.md))
  - the two delays are not added
- **Tap:** each analysed input is decoded once, and leaky branches hand the detector a
  small copy as it decodes (`roku_stream/admute_link.py`):
  - grey 320x180 at the source rate
  - colour 224x224 once a second
  - 16 kHz mono sound
- **Lookahead:** the detector judges the moment about to air 3 s behind its newest
  frame, or 5 s with captions on. So it has seen and heard what follows a seam before
  that sound reaches anyone.
- **Fail-safe:** if that were ever wrong, master's lease would lapse and the sound
  come back.
- **Keeping up:** the lookahead only helps while every signal reaches the newest
  frame. The sidecar measures how far its analysis trails the media it has received
  (`behind` in admute-state.json). Past 1.5 s it logs a warning and the page says
  "detection N s behind". On 2026-10-03 the audio level grid lost each hole's length
  for good. A 4 s gap in TBS left detection 4.8 s behind, so every decision arrived
  after its moment had aired: the badge showed ~3 s into each ad, and nothing was
  muted. Holes and overlaps are now measured against the grid itself.

### 2. It listens

- **Words** (`admute/speech.py`, `admute/text.py`). The detector runs its own Whisper
  (base.en, one CPU thread, 4 s chunks) on each analysed source, whether or not
  captions are on. Per second, from the words around it but never across a black frame,
  it weighs:
  - a word lexicon learnt from labelled recordings
  - ad wording heard before
  - words repeated from earlier in the broadcast
  - the programme's own vocabulary of the last 45 minutes
  - "you" and "your"
- **Sound fingerprints** (`admute/fingerprint.py`). These are Shazam-style landmark
  hashes, about 32 a second. An ad's soundtrack is identical every time it airs; a
  programme's talk and crowd are not. Per second, never across a black frame:
  - **known ad:** the sound matches a clip in the known-ads database. This is the
    strongest single piece of evidence.
  - **repeat:** it repeats sound this broadcast already called an ad. A repeat of
    *anything* would not do: themes, stingers and goal songs repeat too.
  - **known show sound:** it matches show sound that repeats, like the Jeopardy theme.
    This can only argue for sound.

Words and fingerprints arrive a moment late. Each second's evidence is revised as they
come, and the decision waits for them, but never more than 10 s behind.

### 3. It weighs the evidence

`admute/detector.py` combines everything, per second, in one logistic model
(`admute/model.json`, fitted by `admute.train`):
- **picture:**
  - the station or score bug, learnt from the last 15 minutes
  - cutting since the last black frame
  - whether it looks like the programme of the last 3–45 minutes
  - whether it looks like seconds already called ads
- **words and sound,** as above. The weight of known show sound is set by hand, and
  negative.

### 4. It decides where breaks are

- **Seams** are runs of black frames (strong), hard cuts, and digital silence at a cut
  (weak).
- **A two-state Viterbi** runs over seams and whole seconds. Going quiet needs a seam:
  black is the cheapest place (4), a hard cut costs more (see below); coming back is cheap
  anywhere.
- **Not every break fades to black.** WJLA fades to black at every programme/break seam
  (Jeopardy), and NBC flashes black in its breaks. Cable feeds often don't: in TBS's
  14:48 break on 10/3 the detector muted the first two ads, let the sound back during an
  NBA promo, and never muted again, because the next ads began on plain cuts. Until
  10/3, going quiet *needed* black; now a hard cut (a step difference over 30, a local
  peak) is a seam too. Black stays cheaper, so where a station marks its breaks with
  black, black still wins.
- **A short backward pass** gives P(ad) for the moment about to air.
- **No warm-up:** muting may start from the end of the grace after a take. The
  programme memory (recurrence, colour) needs ~5 minutes of the programme before it
  says anything; until then the other evidence decides alone. Until 10/3 nothing was
  muted before the memory existed (except a clearly known ad); the user dropped that
  warm-up because it didn't help much.

### 5. It errs towards sound (`admute/policy.py`, `roku_stream/admute_link.py`)

- **Starting a mute:**
  - A **provisional mute** starts when P(ad) ≥ T_provisional.
  - Outside games, it starts only at a black frame, at a hard cut when the seconds after
    it are clearly an ad (mean per-second logit ≥ 2), or on a clearly known ad. Black
    alone removed early starts on Jeopardy (4.3 s of show muted fell to 0.2 s); the cut
    rule keeps camera cuts in the programme from opening a mute.
  - In games it may start wherever the detector is sure, because NBC flashes black
    inside breaks, not always at their edges.
- **Confirm or retract:** the mute must **confirm** (≥ T_confirm) within 10 s, or it
  is retracted.
- **Steady, not flickering:** the lookahead decides both ways, so nothing waits longer.
  - A mute starts only if the seconds already seen beyond that point stay ad-like.
  - It ends when P(ad) < T_unmute **and** everything seen beyond agrees it's the
    programme.
  - A one-second flash therefore neither starts nor ends a mute.
- **Inning breaks:** for the first 130 s after MLB's feed says the inning ended, a mute
  ends only at a seam into clearly the programme (the seconds after it read −2.5 or
  lower, per-second logit).
  - A dip mid-shot, or a black frame into a spot that only looks like the game, keeps the
    mute. Those were most of the cut-outs.
  - On the 10/1 tape the game came back 124–167 s after the feed's end of inning.
  - After that, the detector is trusted as usual.
  - After 100 s of mute in a game, a seam brings the sound back unless what follows is
    clearly an ad.
- **After any unmute,** only a new black frame, or a hard cut into something clearly an
  ad, can mute again (black only until 10/3: that left TBS audible for the rest of a
  break).
- **Caps:** a mute ends after 300 s, or 240 s with a sports feed.
- **MLB gate:** with a game held on air, MLB's live feed vetoes mutes while play is
  live, and ends a mute still running.
- **In master** (fail audible):
  - The gain follows the detector's schedule only until its lease, about 2 s ahead,
    then fades back up.
  - A quick fix applies at once, even with the detector down.
  - Only mode **On** touches the sound.
- **During a break:** silence, or **Cairo radio** under the programme. The radio is
  master's own off-air decoder, which only reads the public stream. The picture stays
  on the source, unless **My ads** is on ([my-ads.md](my-ads.md)): then your own ads
  air in its place, with the programme in a corner, and the break card when none may
  play.
- **The AD badge** (top left): "AD?" while provisional, "AD" once confirmed, and in
  Shadow, SHADOW with the detector's confidence. In On, its caption follows the
  actual sound: MUTED, or NOT MUTED when master is not following the call (the lease
  lapsed: the detector is late or down). `badge_words` in admute_link.py.
- **Diagnostic badge** (a switch): during every mute, two more lines say how sure it is
  and what says so. The lines are set when the mute starts and once more when it
  confirms, not every half second. New words never restart the badge's fade-in.
  For example:
  - `95% · KNOWN AD` / `Braves at Dodgers · heard 3x`
  - `90% · PICTURE` / `no station or score bug + fast cutting · black frame`
  - `YOU · it's an ad` / `detector: 0% ad`

  The reason is computed per mute by the detector (`Session.why`): the evidence that
  pushed hardest in the last three seconds, grouped as picture, words or sound, and for
  a known ad, the clip it matched. The same reasons are on the page under each break.

### 6. You fix it in one press

- **It's the show** (u): the sound comes back now, and there is no new mute until the
  programme has run a while. If a known ad was playing, that clip is forgotten.
- **It's an ad** (a): mutes now, until the programme comes back at a seam (or the cap).
- Both act on the picture shown beside them, which is what is on master now. Your own
  player runs a few seconds behind it.
- Fixes and review marks go to `admute-labels.jsonl` as training data (with *Keep my
  corrections as training data* on).

### 7. It learns ads (the known-ads database)

The database (`admute-prints.npz`, beside the master socket) holds **ad clips** and
**show sounds**. A 30 s ad is about 1,000 hashes (≈ 10 kB); 50 breaks take under
1 MB.

**Spots:** ads are learnt **spot by spot**, cut at black frames (4–95 s each). Breaks
never repeat as a whole, but their ads do, in any order.

| Source | When | Counts as an ad |
|---|---|---|
| **Confirmed breaks** (*Learn ads from breaks it confirms*) | 10 min after a break ends, unless marked "Was the show"; each of its spots stored | a spot **wedged** between two others: when it airs again (2 airings); a spot at a break's edge: on its 3rd airing |
| **Spots wedged in a pod** (with the same switch) | live, as soon as the black frame after it arrives: any 4–95 s stretch between black frames with such stretches on both sides (the shape of a break), even if the detector made nothing of it | **while its next airing plays** |
| **MLB play-by-play** (*Learn each game's breaks from MLB's play-by-play*) | as the game goes, each break about 2 min after the next first pitch (and the last at the end), spot by spot | at once |
| **Recordings** (`python -m admute.seed`) | when you run it; the sidecar loads the seed (`admute/known_ads_extra.npz`) once, by its tag | at once |
| **Training recordings and the inbox** (`admute-seeds/`) | a recorded game once processed, or any seed dropped there: merged within a minute, no restart | at once |

**Shows are protected:** a stretch next to a long programme stretch is never wedged, so
a theme or cold open beside a break is not learnt this way. Known show sound vetoes it
anyway.

**Why spots matter:** they don't help a game hearing everything for the first time: only
about 15% of a game's ad time repeats within that game. They help a lot once ads recur
across programmes and days: Jeopardy 09-24 went from 74% to 85% of ad time muted, with no
more show muted.

**How a game's breaks are found.** MLB's feed gives each half-inning's last pitch and
the next first pitch, in real time. The broadcast arrives late by an unknown lag
(YouTube TV: tens of seconds; a paused Roku: minutes), which can drift as the stream
rebuffers. Nothing is recorded: the detector already holds the game's black frames, its
own evidence and the fingerprints. So:
1. The game's lag is the shift, from −90 s to +300 s, that puts black frames at the most
   inning edges.
2. Each break's lag is found again within 45 s of that, so drift is followed.
3. A break runs from the first black frame after its last out to the last one before
   its first pitch. Its edges are the broadcast's own, not the feed's.
4. It is kept only if the detector, which knows nothing of the feed, finds at least 60%
   of it ad-like.

On the 10/1 game, against hand labels:
- With lags of 0, 60 and 200 s simulated, and 40 s drifting to 100 s, 99.7% of what it
  called ad was ad (62% of the game's ad time was found).
- With a lag far outside the range (10 minutes), it learnt only 4 breaks, and those were
  real.

**Safety.**
- **Edges:** each break's edges are trimmed (2 s at the start, 5 s at the end).
- **Never an ad:**
  - Any second that sounds like known show sound, or like this broadcast's settled
    show, is never stored as an ad.
  - Show sound heard twice, well clear of any break (in a broadcast, or across
    recordings), becomes a known show sound and can never be an ad.
- **No duplicates:** each ad is stored once; hearing it again counts it, not copies it.
- **Forgetting:** "It's the show" during a known ad, "Was the show" on a break, or
  **Forget** on the page removes a clip within a second. It is then learnt again only
  from new breaks.
- **Old clips:** clips not heard for 60 days are dropped (3,000 ads at most), and
  seeded clips are kept.

### Scripts and pictures (the Ad database)

Every clip keeps its **script**: the words Whisper heard over it, on the clip's own clock
(`script` in its entry in `admute-prints.npz`: words, the parts of the clip they cover,
and where they came from). They are filled in three ways:

| When | Words from |
|---|---|
| A clip is stored (a spot, a pod, a game's break) or heard again as a clip it already has | the broadcast, as transcribed live (the detector keeps 30 min of words) |
| A known ad airs again and part of it has no script yet | the broadcast, once that airing is over (`PrintEvidence.scribe`). Clips learnt before 10/3, and stored whole breaks, fill in a spot at a time |
| A recording holds it (`python -m admute.scripts backfill`, and every training recording) | the recording's cached words, or Whisper on just that stretch. The clip is found window by window (8 s), so an ad inside a stored break is found on its own |

A stretch Whisper did not hear (speech off, or a chunk dropped while it was behind) gives
no script rather than an empty one; an empty script means it heard the stretch and there
were no words (music only). A part already scripted is replaced only by a clearly fuller
one.

Each ad also keeps up to four **pictures** (`admute-ads/<clip>-<i>.jpg`, 256x144, at 15,
40, 65 and 90% of it): from the page's pictures of the airing it was learnt or heard
again from, or from a recording (`admute.scripts`). They go when the clip goes.

### Training recordings (TV-Thing)

With **Record over-the-air games on TV-Thing for training** on, games in VizelVision's
own schedule are recorded on TV-Thing and learnt from (`admute/recordings.py`). The
user unit `vizelvision-admute-recordings.timer` runs it every 10 minutes.

1. **Plan.**
   - **What gets a timer:** each game in the next 24 h on an over-the-air network gets a
     TV-Thing timer, from 5 min before its start to 4 h after. The Washington stations:
     FOX → WTTG 5.1, NBC → WRC 4.1, CBS → WUSA 9.1, ABC → WJLA 7.1.
   - **Titles:** these timers are titled "… (ad training)".
   - **Existing timers:** a timer already recording that channel, one of yours say, is
     learnt from rather than duplicated.
   - **Not recorded, with the reason listed on the page:**
     - cable-only games (TBS, FS1, NFL Network)
     - a clash with another TV-Thing recording, since TV-Thing records one digital
       channel at a time
     - a clash with VizelVision airing a different TV-Thing channel then. TV-Thing can
       stream the channel it records, but not change channel.
   - **Cancel** on the page cancels VizelVision's own timer in TV-Thing. For a timer of
     yours, it only stops learning from it.
2. **Record.** TV-Thing records into its library, where the recording stays.
3. **Learn,** once the recording is finished (at the lowest priority):
   - picture and sound features, Whisper words, fingerprints
   - for MLB, its breaks from the play-by-play, sent to the known-ads inbox
   - training labels in `admute/truth/auto/`: the breaks as **ad**, play in progress
     (first pitch to last pitch of each half-inning) as **show**. The rest is
     **ignore**, including 30 s before to 4 min after every pitching change, which
     often stops play for ads.

   On the 10/1 game these labels matched the hand labels on 99.7% of the ad seconds and
   100% of the show seconds. The next `admute.train` includes them.
4. **Leagues without play-by-play yet** (NFL…) are recorded and transcribed, but get no
   labels.

**What a full database buys.** The 10/1 game, judged by a model that never saw sports,
was 44% muted when only Jeopardy's ads were known. With every one of its ads known, it
was **96% muted**:
- show muted fell from 36 to 15 s
- late returns fell from 33 to 11 s

## The Ad database

The **Ad database** tab of Ads (`/ads#database`) shows every clip in the known-ads
database, as a card: its pictures, its script with times, its status (**known ad**;
**heard once**, with how many more airings it needs; **show sound**), its length, how
often and when it was heard, and where from (a programme, a recording, a game's
play-by-play).
- **Search** (**/**) finds words in the scripts, names and programmes, and marks them.
- **Filters:** ads, known, heard once, show sounds. **Sort:** last heard, most heard,
  newest, longest.
- **Name** an ad (say, the advertiser): `POST /v1/admute/name` → `admute-commands.jsonl`,
  applied by the detector within a second.
- **Forget** works as on the Ad mute tab.
- The tab reads `GET /v1/admute/known` (the sidecar's `admute-prints.json`) every 15 s,
  and pictures from `GET /v1/admute/ad/<clip>-<i>.jpg`.

## The page (Ads › Ad mute, `/ads#admute`)

| Part | What it shows and does |
|---|---|
| **Off / Shadow / On** | Off: nothing analysed and no lookahead. Shadow: only the AD badge. On: breaks go quiet (asks first). Applies to sources prepared after the switch. |
| **On air** | The detector's state and P(ad), and "a known ad is playing". **Hears:** shows Whisper's last words. The picture on master now, with a strip of the 30 s before it (each with the detector's call: red muted, amber leaning ad). The two quick fixes. **Pause for this program.** |
| **Recent breaks** | The last 40. For each: pictures before, at and after it (click for the whole break), its length, the call (with a **known ad** tag when its sound matched one) and its reason, how it ended, and **Ad ✓** / **Was the show**. **It missed a break** records a time range as an ad. Times are air times, as the clock on screen showed them. |
| **On air: Why** | The current mute's reason, as on the diagnostic badge. |
| **Training recordings** | Games planned, recording or recorded on TV-Thing, with Cancel, and what was learnt from each: breaks fingerprinted, labels saved. **Not recorded** lists each game left out, and why. |
| **Known ads** | How many ads are known (and how many are from recordings and games), how many were heard once, and the show sounds. This game's play-by-play learning so far, and the broadcast's lag. What it learnt or forgot lately, each with **Forget**. **All known ads and show sounds**: the full list, most recently heard first, each with **Forget**. |
| **How it works** | The flow above, in five steps. |
| **Last hour** (machinery, **m**) | P(ad), mutes, black frames and the sports feed, plus the model, Whisper's load and the known-ads count. |

Settings (**Save settings**; the mode and sound reach master within a second):

| Panel | Option | Default |
|---|---|---|
| What it listens to | TV-Thing channels · Roku apps | on |
| | Use MLB's live feed: never mute while play is live | on |
| | Never mute these programmes (title substrings) | — |
| How it decides | Sensitivity (cautious ↔ eager) | balanced |
| | Listen to what is said (Whisper), about a third of a core per source | on |
| | Longest mute | 300 s |
| | Lookahead (applies to sources prepared after saving) | 3 s |
| What it learns | Recognise ads heard before (audio fingerprints) | on |
| | Learn ads from breaks it confirms | on |
| | Learn each game's breaks from MLB's play-by-play | on |
| | Record over-the-air games on TV-Thing for training | on |
| | Keep my corrections as training data | on |
| During a break | Sound: silence or Cairo radio (and its level) | silence |
| | AD badge on screen: in shadow / always / never | in shadow |
| | Diagnostic badge: each mute's confidence and source | off |

## Files

Beside the master socket (`state/master-candidate/`):

| File | Contents |
|---|---|
| `admute.json` | settings |
| `admute-state.json` | what the detector sees, every second (the page reads it) |
| `admute-labels.jsonl` | your fixes and review marks (training data) |
| `admute-prints.npz` | the known-ads database |
| `admute-prints.json` | its list of clips, for the page |
| `admute-adtext.json` | ad wording heard before (words) |
| `admute-commands.jsonl` | the pages' requests to the detector (Forget, names) |
| `admute-ads/<clip>-<i>.jpg` | each ad's pictures, for the Ad database |
| `admute-seeds/` | the inbox for seeds and for scripts from `admute.scripts` (`*.scripts.json`); merged ones move to `done/` |
| `admute-recordings.json` | training recordings: planned, recording, learnt, and those left out |
| `admute-recordings-skip.json` | games you cancelled on the page |
| `admute-frames/<input>/<second>.jpg` | the page's pictures: 256x144, one a second, kept 3 h |
| `admute.sock` | master ↔ detector |

In the repository: `admute/model.json` (the model), `admute/known_ads_extra.npz` (the
seed), `admute/truth/` (hand labels) and `admute/truth/auto/` (labels from training
recordings).

## Tools

```bash
cd ~/vizelVision
PY=/home/vivian/miniconda3/bin/python3
# recordings, once each (cached in state/admute/cache)
$PY -m admute.replay extract TAPE --thumbs     # picture and sound features
$PY -m admute.speech TAPE                      # Whisper words, in live-sized chunks
$PY -m admute.fingerprint TAPE                 # sound fingerprints
# known ads from recordings
$PY -m admute.seed recording TAPE...           # its labelled ad blocks (truth file or the stripper's "(no ads).json")
$PY -m admute.seed game TAPE --game-pk N --tape-start ISO    # an MLB game, its breaks from the feed
$PY -m admute.seed build [--inbox]             # write the seed, or hand it to the running detector
# scripts and pictures for known ads that lack them, found in the library's recordings
$PY -m admute.scripts backfill [--dry-run]
$PY -m admute.scripts scan TAPE...             # in these recordings only
# training recordings (also every 10 min by vizelvision-admute-recordings.timer)
$PY -m admute.recordings status                # planned, recording, learnt, left out
$PY -m admute.recordings sync                  # plan timers now, learn from finished recordings
# measuring and training
$PY -m admute.replay score [--lookahead 5] [--no-text] [--no-prints]   # every tape with a truth file
$PY -m admute.train --loo-replay --lookahead 5   # honest numbers: each tape scored by a model fitted without it
$PY -m admute.train                              # refit admute/model.json
$PY -m admute.lab sheet TAPE START END --step 10 # contact sheets, for labelling by eye
```

## Deploying

- **The detector:** changes to `admute/` need only `systemctl --user restart
  vizelvision-admute`. That never touches the air (the sound is left alone while it is
  down), but the programme on air loses its programme memory for ~5 minutes.
- **Web and master:** changes to the page's routes or settings need a web restart. **Only
  restart web or master with nothing on air**: check `GET /v1/master` (`on_air`,
  `prepared`) and `GET /v1/queue` (`hold`) first, and stop if anything is there. A web
  restart drops a Roku feed and pauses Up next; afterwards, `POST /v1/queue/resume`.
- **Restoring a dropped feed:** queue it as Now, with the same target and its original
  end as `until`. That restores its hold.
- **First install:** `./deploy/install-master-stack.sh`, which installs
  `vizelvision-admute.service` and `vizelvision-admute-recordings.timer` into the stack
  target. The recordings job runs fresh code on every run, so it needs no restart.

## Measured on recordings

The labelled tapes:
- **Jeopardy!** on WJLA, 09-23 and 09-24 (labels from the offline stripper)
- the **10/1 NL Wild Card Game 3** on WRC/NBC, 3 h, hand-labelled from contact sheets

Each tape is scored by a model fitted without it. Its word lexicon, ad wording and known
ads are learnt without it too. The lookahead is 5 s, as live with captions on.

| Held-out tape | Picture only | + words | + fingerprints (as deployed) |
|---|---|---|---|
| Jeopardy 09-23: show muted / ad time muted | 4.3 s / 80% | 4.3 s / 85% | **0.2 s / 90%** |
| Jeopardy 09-24 | 0.1 s / 77% | 0.1 s / 76% | 0.1 s / 74% |
| MLB (the model has seen no sports) | 75 s / 54% | 36.5 s / 44% | 36.3 s / 44% |

- **MLB:** this is the hard case, a game with none of its ads known. With them all known
  it reaches 96% (see Known ads), which is why games now teach the database as they go.
- **Words:** per-second accuracy rose from 86, 86 and 83% to 89, 90 and 88%. On sports
  they halve the show lost, but mute less of the ads, which is the trade the design asks
  for.
- **A young programme vocabulary** reads as "ad" (a 49 s false mute in a first try), so
  that feature waits for about 10 minutes of talk.
- **5 s vs 3 s lookahead:** less show muted across the three tapes (46 vs 52 s), with
  ad coverage the same or better.
- **Steady mutes (10/3).** Lookahead agreement, and the inning-break hold, scored on
  the held-out MLB tape. "Leaked" is ad time audible after a break's first mute; "re-mutes"
  counts how often a break cut out and back in.

  | MLB tape, held out | Show muted | Ad coverage | Leaked | Re-mutes |
  |---|---|---|---|---|
  | 5 s lookahead, before | 36.3 s | 44.0% | 1078 s | 9 |
  | 5 s lookahead, steady | 37.4 s | 64.7% | 485 s | 6 |
  | 3 s lookahead, before | 43.8 s | 45.1% | 1035 s | 13 |
  | 3 s lookahead, steady | 50.7 s | 62.1% | 546 s | 8 |

  Jeopardy is unchanged.

- **Cuts as seams (10/3).** Black required (before) against black or a hard cut (cut costs
  24 to start a break, black 4; at a cut a mute starts only if the seconds after it read
  ≥ 2, and re-arms only 10 s after an unmute). "No black at edges" takes the black frames
  out within 2 s of every labelled break edge, as a feed that cuts straight into its
  breaks would look. These runs use the deployed model (fitted on all three tapes) with
  known ads from the other tapes only, lookahead 5 s, so compare the rows with each other,
  not with the held-out tables above. Show muted / ad time muted:

  | Tape | Before | After |
  |---|---|---|
  | Jeopardy 09-23 | 0.2 s / 90% | 3.2 s / 92% |
  | Jeopardy 09-23, no black at edges | 7.4 s / 65% | 3.4 s / 92% |
  | Jeopardy 09-24 | 0.1 s / 85% | 0.1 s / 94% |
  | Jeopardy 09-24, no black at edges | 2.0 s / 74% | 1.9 s / 93% |
  | MLB 10/1 | 26.9 s / 95% | 27.8 s / 95% |
  | MLB 10/1, no black at edges | 45 s / 86% | 89 s / 94% |

  - Jeopardy 09-23's extra 3 s is a video clue (a full-screen photo of Felix Baumgartner
    in Red Bull gear), which looks like an ad.
  - A cut cost of 8 or 12 started mutes 7–11 s early in MLB breaks (the end of an inning
    looks ad-like); 16 and 24 did not. Re-arming at a cut straight after an unmute
    re-muted the first 28 s of the game (a sponsored open), hence the 10 s wait.
  - **Open:** MLB with no black at its edges still mutes more show than before. Most of it
    is late returns (37 → 74 s) where the game comes back on a plain cut.

## Tests

```bash
/usr/bin/python3 -m unittest tests.test_admute tests.test_admute_api            # settings, link, policy, worker, routes
/home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_text           # words, late evidence, pictures, sessions
/home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_prints         # fingerprints, spots and pods, known ads, show veto, forgetting, game learning, reasons, scripts, cut seams
/home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_recordings     # TV-Thing timers: planning, clashes, cancelling, labels
/home/vivian/miniconda3/bin/python3 tests/admute_sidecar_integration.py          # the detector over its socket, a real tape
/usr/bin/python3 tests/admute_master_integration.py                              # tap, delay, mute, badge, bed on a real master
/usr/bin/python3 tests/admute_live_input_spike.py roku 60                        # read-only: the live Roku feed through the tap
node tests/browser_ui_admute.cjs <playwright>                                    # the Ad mute tab and On Air
node tests/browser_ui_ads.cjs <playwright>                                       # the Ad database, and the Ads page's tabs
```

## Known limits and next steps

- **Programme boundaries on one channel.** When two shows run back to back, the next
  show's opening can look like an ad until the memory catches up. The cap, a quick fix
  or a per-title exception covers it.
- **New networks and sports.** The model has seen one game (NBC). The known-ads database
  is how sports gets better: every game now teaches it. Leagues other than MLB have no
  play-by-play learning or gate yet (ESPN's feeds could provide both).
- **Whisper's cost.** About a third to two-thirds of a core per analysed source. When it
  falls behind, chunks are dropped and those seconds are judged without words.
- **Words and corrections are not yet turned into training rows** automatically.
  Labels are recorded; retraining is by hand (`admute.train`).
- **Whole breaks are stored as one clip** (several ads). A single ad airing later still
  matches inside it, but splitting breaks into ads would make the database smaller.
- **Learning still leans on black.** Spots are cut at black frames, and a game's breaks
  are matched to black frames (for its 99.7% precision). A break with no black inside it
  is longer than any spot and is not stored. Splitting breaks where their sound repeats
  another airing's would not need black.
