"""Opt-in real-media check of the wait fill: the real station ID held at its end card, with
real ads (My ads') and the real join bumper decoded by AdBreak's own reels over it, as master
would release them. The output is a stand-in (appsrc -> fakesink, 320x180), so no encoder
or publisher; the programme delay is simulated (frames are released DELAY after their pts).

Run off air from the repository root:
    nice -n 19 taskset -c 6,7 /usr/bin/python3 tests/wait_fill_integration.py
Checks: nothing is replaced before the end card freezes; from the first held frame an ad
replaces it, with its sound; once the next source is ready, the window's planned end is
where that ad ends plus the bumper's 10 s; the bumper follows the ad; the next source's
frames close the window; the plays are logged (to a scratch log, not the real one).
"""
from collections import deque
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.ad_break import AdBreak  # noqa: E402
from roku_stream.config import load_config  # noqa: E402
from roku_stream.ident import IDENT_HOLD_AT, IDENT_PATH  # noqa: E402
from roku_stream.master_media import FileInput  # noqa: E402
from roku_stream.my_ads import MyAds  # noqa: E402
from roku_stream.sports_join import JOIN_VIDEO  # noqa: E402
from tests.ident_hold_integration import Output as HoldOutput, wait  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DELAY = 2_000_000_000
ID, NEXT = (None, 0, 7), (None, 0, 9)


class Output(HoldOutput):
    """The ID hold test's stand-in, with what AdBreak needs (its size), and every buffer kept
    for the release thread."""
    width, height = 320, 180

    def __init__(self):
        self.released = deque()
        super().__init__()

    def _seen(self, pad, info, kind):
        buffer = info.get_buffer()
        with self.lock:
            self.released.append((kind, buffer.pts, buffer.copy_deep()))
        return super()._seen(pad, info, kind)


def main():
    config = load_config(ROOT / 'config.master.json')
    store = MyAds(config.master.socket_path, lenient=True)
    settings = store.read()
    # Only ads a wait may start, so the first one cued is one (the fill skips longer ones).
    settings = {**settings, 'ads': [a for a in settings['ads'] if a['duration'] <= AdBreak.FILL_LONGEST]}
    output = Output()
    gst = output.gst
    scratch = tempfile.TemporaryDirectory(prefix='vv-fill-')
    breaks = AdBreak(output, store.folder, Path(scratch.name) / 'plays.jsonl')
    breaks.configure(settings, {'mode': 'on'})
    ident = FileInput(output, 3, IDENT_PATH.resolve().as_uri(), start_seconds=25)
    frames, sounds, report = [], [], {'ok': False}
    state = {'take_at': None, 'stop': False}

    def release():
        """The programme delay: each buffer goes through AdBreak DELAY after its pts."""
        while not state['stop']:
            with output.lock:
                ready = []
                now = output.running_time()
                while output.released and output.released[0][1] + DELAY <= now:
                    ready.append(output.released.popleft())
            for kind, pts, buffer in ready:
                take = state['take_at']
                route = NEXT if take is not None and pts >= take else ID
                if kind == 'video':
                    shown = breaks.picture(buffer, pts + DELAY, pts, route)
                    frames.append((pts, shown is not None, breaks.reel_kind if shown is not None else None, route is NEXT))
                else:
                    mine = breaks.fill_sound(pts + DELAY, pts, buffer.get_size())
                    sounds.append((pts, mine is not None and any(mine[i] for i in range(0, len(mine), 97))))
            time.sleep(.005)

    releaser = threading.Thread(target=release, daemon=True)
    try:
        wait(lambda: breaks.cued is not None and breaks.cued.ad['duration'] <= breaks.FILL_LONGEST, 30, 'a short ad cued')
        ad = breaks.cued.ad
        report['ad'] = {'name': ad.get('name'), 'duration': ad['duration']}
        wait(ident.ready, 20, 'the ID decodes')
        ident.cue()
        ident.start()
        releaser.start()
        wait(lambda: (ident.progress().get('position_seconds') or 0) >= IDENT_HOLD_AT, 10, 'the end card')
        assert ident.freeze(), 'freeze refused'
        frozen_at = ident.frozen_at
        breaks.fill_start(frozen_at)
        time.sleep(4)
        ready = output.running_time()
        join = {'path': str(JOIN_VIDEO), 'seconds': 10.0}
        assert breaks.fill_finish(ready, join), 'the fill would not finish'
        wait(lambda: (breaks.fill_end() or {}).get('fixed'), ad['duration'] + 15, 'the bumper starts after the ad')
        planned = breaks.fill_end()
        report['planned_end_after_ready_s'] = round((planned['end'] - ready) / 1e9, 2)
        wait(lambda: output.running_time() >= planned['end'] - 300_000_000, 15, 'the bumper all but over')
        state['take_at'] = output.running_time()  # The take: what follows is the next source's.
        wait(lambda: breaks.state == 'idle' and breaks.fill is None, DELAY / 1e9 + 3, 'the window closes')
        time.sleep(.5)
        state['stop'] = True
        releaser.join(2)
        breaks._help()  # Write the play log (the helper's job).

        frame = 1_000_000_000 // output.fps
        early = [f for f in frames if f[1] and f[0] < frozen_at - frame]
        assert not early, f'replaced before the end card froze: {early[:3]}'
        replaced = [f for f in frames if f[1]]
        first = replaced[0][0] if replaced else None
        report['first_replaced_after_freeze_ms'] = round((first - frozen_at) / 1e6, 1) if first is not None else None
        assert first is not None and abs(first - frozen_at) <= 2 * frame, 'the ad starts on the first held frame'
        kinds = [f[2] for f in replaced]
        assert kinds[0] == 'ad' and 'join' in kinds, f'an ad, then the bumper: {sorted(set(k for k in kinds if k))}'
        switch = kinds.index('join')
        assert all(k == 'ad' for k in kinds[:switch]), 'nothing between the ad and the bumper'
        ad_seconds = (replaced[switch][0] - first) / 1e9
        report['ad_aired_s'] = round(ad_seconds, 2)
        assert abs(ad_seconds - ad['duration']) < .25, f'the ad played whole: {ad_seconds} of {ad["duration"]}'
        assert abs(planned['end'] - replaced[switch][0] - 10e9) < 50e6, 'the window ends 10 s into the bumper'
        after = [f for f in frames if f[3]]
        assert after and not any(f[1] for f in after if f[0] >= planned['end']), 'the next source is not replaced'
        loud = [s for s in sounds if s[1]]
        assert loud and loud[0][0] >= frozen_at - frame, 'the ad has its sound in the fill'
        report['sound_buffers'] = len(loud)
        plays = [json.loads(line) for line in (Path(scratch.name) / 'plays.jsonl').read_text().splitlines()]
        report['plays'] = [(p['kind'], p.get('name'), p['complete'], p.get('wait')) for p in plays]
        assert [(p['kind'], p['complete'], p.get('wait')) for p in plays] == [('ad', True, True), ('join', True, True)], plays
        assert not breaks.failed_once, 'AdBreak logged a failure'
        report['ok'] = True
    finally:
        state['stop'] = True
        ident.close()
        breaks.close()
        output.pipeline.set_state(gst.State.NULL)
        scratch.cleanup()
        print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
