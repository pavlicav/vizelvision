"""The crawl on a real master publisher; never contacts source hardware, the EAS decoder or NWS.

Starts a private MediaMTX and a 720p60 master on the off-air card, then reads frames back
over RTSP: a DC alert as important news (red band and label box, nothing drawn above the
bar), a one-pass bulletin that slides away by itself and reports it finished, a station
override cutting in, and clearing back to the card, with the output real time throughout.
Then the bar along the top: a new item's blue band and red NEW box there (and nothing at the
bottom), the station clock stepped below it, and the same pass moving to the bottom.

Run: /usr/bin/python3 tests/crawl_integration.py [screenshot.png]
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream import crawl
from roku_stream.master_media import MasterMedia
from roku_stream.publication import LocalMediaMtx

W, H, FPS = 1280, 720, 60
RED, NAVY, WHITE = (158, 13, 18), (10, 23, 48), (255, 255, 255)
NEW_BLUE, FLAG_RED = (0, 61, 140), (214, 18, 26)


def wait(check, timeout=20, poll=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if poll:
            poll()
        if check():
            return
        time.sleep(.05)
    raise AssertionError('Timed out')


def pixels(url, points, screenshot=None):
    """RGB at each (x, y) of one decoded frame."""
    with tempfile.NamedTemporaryFile(suffix='.png') as frame:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-i', url,
                        '-frames:v', '1', '-update', '1', '-y', frame.name], check=True, timeout=20)
        if screenshot:
            Path(screenshot).write_bytes(Path(frame.name).read_bytes())
        result = []
        for x, y in points:
            raw = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', frame.name, '-vf',
                                  f'crop=1:1:{x}:{y}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                 check=True, capture_output=True, timeout=10).stdout
            result.append(tuple(raw))
        return result


def near(rgb, expected, tolerance=40):
    return all(abs(a - b) <= tolerance for a, b in zip(rgb, expected))


def main(screenshot=None):
    now = datetime.now(timezone.utc)
    alert = {'id': 1, 'valid': 1, 'event_code': 'SVR', 'event_desc': 'Severe Thunderstorm Warning',
             'severity': 'warning', 'originator': 'WXR', 'origin': 'radio', 'locations': ['011001'],
             'locations_detail': [{'code': '011001', 'name': 'District of Columbia, DC'}],
             'issued_utc': now.isoformat(), 'expires_utc': (now + timedelta(minutes=45)).isoformat(),
             'transcript': 'At 2 PM, a severe thunderstorm was located over Rock Creek Park, moving east at 25 mph.'}
    settings = crawl.CrawlSettings.validate({})
    important = crawl.compose(settings, [crawl.describe(alert, ('011001',), now)], 'WEATHER ALERT', now)
    bulletin = {'kind': 'bulletin', 'key': 'scores-test', 'label': 'SCORES', 'style': 'station', 'passes': 1,
                'items': [{'tag': 'NHL', 'heading': '', 'text': 'Capitals 3, Bruins 2'}]}
    override = crawl.compose(crawl.CrawlSettings.validate({'override': {'text': 'Game 3 tonight at 8'}}), [], None, now)
    with tempfile.TemporaryDirectory(prefix='vv-crawl-') as directory:
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), Path(directory)) as server:
            output = MasterMedia(server.rtsp_url, width=W, height=H, fps=FPS, bitrate=4500)
            try:
                wait(output.healthy)
                renderer = output.crawl
                # The band's top rows hold no glyphs. Right of the label box, the band; above the
                # bar, the card's bars; at the left, the label box.
                top = renderer.y + 3
                probes = [(W - 4, top), (W // 2, renderer.y - 40), (8, top)]
                before = pixels(server.rtsp_url, probes)
                assert not near(before[0], RED), before
                output.set_crawl(important)
                wait(lambda: renderer.scene is not None)
                time.sleep(3)
                after = pixels(server.rtsp_url, probes, screenshot)
                assert near(after[0], RED), after
                assert near(after[1], before[1], 24), (before, after)  # the picture above is untouched
                assert near(after[2], WHITE, 30), after  # WEATHER ALERT box
                # A bulletin replaces it, runs once, slides away and reports itself finished.
                output.set_crawl(bulletin)
                wait(lambda: renderer.scene is not None and renderer.scene.key == 'scores-test')
                time.sleep(1)
                running = pixels(server.rtsp_url, probes)
                assert near(running[0], NAVY) and near(running[2], (100, 219, 227)), running  # navy band, cyan SCORES box
                wait(lambda: output.crawl_finished() == 'scores-test', timeout=25, poll=output.poll)
                time.sleep(1)
                gone = pixels(server.rtsp_url, probes)
                assert near(gone[0], before[0], 24) and near(gone[2], before[2], 24), (before, gone)
                assert renderer.blocked, 'the draw handler is off once the bar is gone'
                output.set_crawl(override)
                wait(lambda: renderer.scene is not None)
                for _ in range(10):  # ten seconds of crawling must not slow the output
                    output.poll()
                    time.sleep(1)
                held = pixels(server.rtsp_url, probes)
                assert near(held[2], NAVY), held  # navy band, no label box
                lag = max(track['lag_seconds'] or 0 for track in output.status().values())
                assert lag < 1, output.status()
                output.set_crawl(None)
                time.sleep(1.5)
                cleared = pixels(server.rtsp_url, probes)
                assert near(cleared[0], before[0], 24) and near(cleared[2], before[2], 24), (before, cleared)
                assert output.healthy() and not renderer.failed and renderer.finished == 'scores-test'
                # Along the top during football: a new item, in its own colour with a NEW box.
                output.set_clock({'enabled': True, 'seconds': False})
                clock_ypad = output.clock_overlay.get_property('ypad')
                new = {'kind': 'bulletin', 'key': 'dc-new', 'label': 'DC ALERTS', 'flag': 'NEW', 'style': 'new',
                       'passes': 0, 'position': 'top', 'items': [{'tag': 'ALERTDC', 'heading': '', 'text': 'Road closed.'}]}
                high = renderer.top + 3
                above = [(W - 4, high), (8, high), (W - 4, top)]
                card = pixels(server.rtsp_url, above)
                output.set_crawl(new)
                wait(lambda: renderer.scene is not None and renderer.scene.key == 'dc-new')
                time.sleep(1.5)
                shown = pixels(server.rtsp_url, above, screenshot and screenshot.replace('.png', '-top.png'))
                assert near(shown[0], NEW_BLUE) and near(shown[1], FLAG_RED), shown  # blue band, red NEW box
                assert near(shown[2], card[2], 24), (card, shown)  # nothing at the bottom
                assert output.clock_overlay.get_property('ypad') >= renderer.top + renderer.bar, 'the clock steps below'
                # The same pass moved to the bottom slides away at the top and comes back there.
                output.set_crawl({**new, 'position': 'bottom'}, restart=False)
                time.sleep(2)
                moved = pixels(server.rtsp_url, above)
                assert near(moved[0], card[0], 24) and near(moved[2], NEW_BLUE), (card, moved)
                assert output.clock_overlay.get_property('ypad') == clock_ypad, 'the clock is back'
                output.set_crawl(None)
                time.sleep(1.5)
                assert renderer.blocked and not renderer.failed
                print(f'PASS: important alert drawn only in the bar, bulletin ran once and slid away, '
                      f'override cut in, cleared to the card; NEW along the top above the clock, moved to the '
                      f'bottom; lag {lag:.2f} s.')
            except Exception:
                print(server.log_path.read_text()[-4000:], file=sys.stderr)
                raise
            finally:
                output.close()


if __name__ == '__main__':
    main(*sys.argv[1:2])
