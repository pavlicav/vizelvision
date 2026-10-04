# Sonic identity

The master sheet (the logo, signature moves, palette, playable reference renders, usage,
spec and rules) is in the web app at `/sonic`, linked from Presentation's **Sonic identity** tab
(`/presentation#sonic`). A copy is published at
https://claude.ai/artifact/FY9fM1hEaQVzno5Ed5Nom7.

The page's fonts (Big Shoulders Display, Barlow, IBM Plex Mono; SIL Open Font License)
are served from `static/fonts/`. Its audio is served from `ident/build/sonic/` at
`/static/sonic/<name>.mp3`, so rendering again updates the page. Both are public, like
the test card: brand material, not operational data.

For promos, bumpers and IDs, build from `ident/sonic.py`. It holds the shared constants
(`BPM`, `LOGO_OPEN`, `LOGO_CLOSED`, `LOGO_RHYTHM`, `HOME`, `LIFT`, `LOUDNESS`, `TAIL`),
the ballpark instruments (stadium organ, crowd with the logo clap, stadium horn), the
`grit` chain, and the reference sketches. It plays the station ID's own instruments
from `ident/jingle.py`.

    ~/miniconda3/bin/python3 ident/sonic.py ident/build/sonic   # WAV masters and MP3s at -20 LUFS

In brief: the logo is "Viz-el-Vi-sion", eighth, eighth, quarter, half at 120 BPM. Open
is C E G A (a question). Closed is up a whole step, D F# A D (an answer). Keys only move
up a whole step. Crowds and snares carry the logo's rhythm as a clap. Every piece ends
with its last half second silent. Everything is -20 LUFS, -2 dBTP, 48 kHz.

The first full piece built from it is the VizelVision Sports ID (`ident/sports_jingle.py`),
which plays before games. See [VizelVision Sports](station-id.md#vizelvision-sports).
