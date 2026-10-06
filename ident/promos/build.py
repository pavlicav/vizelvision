"""Build the station promos (roku_stream/promos.py): for each, <id>.mp4, a still
(<id>.png) and its manifest (<id>.json) in this folder; for 'only-on', also its music
without the voice (only-on-music.wav), which the web app voices again for each programme.

    /usr/bin/python3 ident/promos/build.py [ID ...] [--keys-file FILE] [--workers 2]
    /usr/bin/python3 ident/promos/build.py --still ID SECONDS out.png    one frame, live text drawn

1. Voice lines (script.json, voiced by ident/voice.py): only new or changed lines go to Deepgram.
2. The music (music.py) under a Python with numpy and scipy.
3. The picture (the promo's module, pycairo), piped into ffmpeg with the sound levelled
   to -20 LUFS, as the station ID is, and the ID's touch of VHS.

Everything runs at the lowest CPU priority. Each file replaces the old one in a single
rename; the manifest is written last, so master only ever sees a finished promo.
"""
import argparse
import importlib
import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IDENT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(IDENT))
sys.path.insert(0, str(IDENT.parent))
import common  # noqa: E402
import build as id_build  # noqa: E402  ident/build.py: measure(), numpy_python()
import voice  # noqa: E402

PROMOS = ('time-temp', 'watching', 'only-on', 'legal', 'press-start')
BUILD = IDENT / 'build' / 'promos'
LOUDNESS, TRUE_PEAK = id_build.LOUDNESS, id_build.TRUE_PEAK
VERSION = 1


def module(promo_id):
    return importlib.import_module(promo_id.replace('-', '_'))


_PICTURE = None


def _frame(index):
    return common.render_frame(_PICTURE, index)


def _init(promo_id):
    global _PICTURE
    os.nice(0)
    _PICTURE = module(promo_id)


def level(audio):
    m = id_build.measure(audio)
    return m, (f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:measured_I={m['input_i']}:"
               f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
               f"offset={m['target_offset']}:linear=true,aresample=48000")


def encode(promo_id, audio, workers):
    picture = module(promo_id)
    m, audio_filter = level(audio)
    out = HERE / f'{promo_id}.mp4'
    partial = out.with_suffix('.part.mp4')
    total = common.frames(picture.DURATION)
    command = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-threads', '2',
               '-f', 'rawvideo', '-pix_fmt', 'bgr0', '-s', f'{common.W}x{common.H}', '-r', str(common.FPS), '-i', '-',
               '-i', str(audio), '-vf', 'rgbashift=rh=-2:bh=2,noise=alls=4:allf=t,format=yuv420p', '-af', audio_filter,
               '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-maxrate', '9M', '-bufsize', '18M', '-profile:v', 'high', '-g', str(common.FPS),
               '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
               '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
               '-t', f'{picture.DURATION:.3f}', '-movflags', '+faststart', str(partial)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    started = time.monotonic()
    try:
        with multiprocessing.Pool(workers, initializer=_init, initargs=(promo_id,)) as pool:
            for index, frame in enumerate(pool.imap(_frame, range(total), chunksize=4)):
                encoder.stdin.write(frame)
                if index % (common.FPS * 2) == 0:
                    print(f'  picture: {index / common.FPS:4.1f} s  ({time.monotonic() - started:.0f} s elapsed)')
    finally:
        encoder.stdin.close()
        if encoder.wait():
            partial.unlink(missing_ok=True)
            raise SystemExit(f'ffmpeg could not encode {promo_id}')
    duration = verify(partial, picture.DURATION)
    partial.replace(out)
    return out, duration, m


def verify(path, expected):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    kinds = {s['codec_type'] for s in info['streams']}
    duration = float(info['format']['duration'])
    if kinds != {'video', 'audio'} or abs(duration - expected) > 0.1:
        raise SystemExit(f'{path.name} is wrong: tracks {sorted(kinds)}, {duration:.2f} s')
    return duration


def manifest(promo_id, loudness):
    picture = module(promo_id)
    return {'id': promo_id, 'version': VERSION, 'name': picture.NAME, 'kind': picture.KIND, 'order': picture.ORDER,
            'description': picture.DESCRIPTION, 'duration': picture.DURATION, 'file': f'{promo_id}.mp4',
            'still': f'{promo_id}.png', 'still_at': picture.STILL_AT, 'overlays': picture.OVERLAYS,
            'voice': getattr(picture, 'VOICE', None), 'loudness': {'input': loudness['input_i'], 'target': LOUDNESS},
            'built_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}


def still(promo_id, t, out, live=False):
    """A frame; with live, master's text drawn over it with sample values."""
    import cairo
    from roku_stream import promo_overlay
    picture = module(promo_id)
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, common.W, common.H)
    ctx = cairo.Context(surface)
    picture.draw(ctx, t, int(t * common.FPS))
    if live:
        overlays, problems = promo_overlay.validate_all(picture.OVERLAYS)
        if problems:
            raise SystemExit(f'{promo_id}: an overlay cannot be drawn: {problems[0]}')
        promo_overlay.draw(ctx, overlays, {'temperature': {'f': 72, 'place': 'Reagan National'},
                                           'programme': {'title': 'Jeopardy!'}}, t)
    partial = Path(out).with_name('.' + Path(out).name)
    surface.write_to_png(str(partial))
    partial.replace(out)


def build(promo_id, python, workers, keys_file):
    print(f'{promo_id}:')
    scripts = json.loads((HERE / 'script.json').read_text())
    if promo_id in scripts:
        if keys_file or os.environ.get('DEEPGRAM_API_KEY'):
            voice.render(scripts[promo_id], keys_file)
        missing = [line['id'] for line in scripts[promo_id]['lines'] if not (voice.VOICE_DIR / f"{line['id']}.wav").exists()]
        if missing:
            print(f"  voice: no Deepgram key; building without {', '.join(missing)}")
    BUILD.mkdir(parents=True, exist_ok=True)
    audio = BUILD / f'{promo_id}-audio.wav'
    subprocess.run([python, str(HERE / 'music.py'), promo_id, str(audio)], check=True)
    picture = module(promo_id)
    if getattr(picture, 'VOICE', None):
        music = BUILD / f'{promo_id}-music.wav'
        subprocess.run([python, str(HERE / 'music.py'), promo_id, str(music), '--no-voice'], check=True)
        _, audio_filter = level(music)
        stem = HERE / picture.VOICE['music']
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(music), '-af', audio_filter, '-c:a', 'pcm_s16le',
                        '-ac', '2', str(stem.with_suffix('.part.wav'))], check=True)
        stem.with_suffix('.part.wav').replace(stem)
    print(f'  picture: {common.frames(picture.DURATION)} frames at {common.FPS} fps')
    out, duration, loudness = encode(promo_id, audio, workers)
    still(promo_id, picture.STILL_AT, HERE / f'{promo_id}.png')
    target = HERE / f'{promo_id}.json'
    target.with_suffix('.part').write_text(json.dumps(manifest(promo_id, loudness), indent=2) + '\n')
    target.with_suffix('.part').replace(target)
    print(f"  done: {out.name} ({duration:.2f} s, {out.stat().st_size / 1e6:.1f} MB, "
          f"audio {loudness['input_i']} LUFS -> {LOUDNESS:g})")


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the station promos')
    parser.add_argument('promos', nargs='*', help='which (default: all): ' + ', '.join(PROMOS))
    parser.add_argument('--keys-file', type=Path, help='a file with DEEPGRAM_API_KEY=... for new voice lines')
    parser.add_argument('--numpy-python', help='Python to run the music with (needs numpy and scipy)')
    parser.add_argument('--workers', type=int, default=2, help='frame-drawing processes (default 2)')
    parser.add_argument('--still', nargs=3, metavar=('ID', 'SECONDS', 'OUT'), help='draw one frame, with live text')
    args = parser.parse_args(argv)
    os.nice(19)
    sys.stdout.reconfigure(line_buffering=True)
    if args.still:
        still(args.still[0], float(args.still[1]), args.still[2], live=True)
        return
    unknown = set(args.promos) - set(PROMOS)
    if unknown:
        raise SystemExit('Unknown promo: ' + ', '.join(sorted(unknown)))
    python = id_build.numpy_python(args.numpy_python)
    for promo_id in args.promos or PROMOS:
        build(promo_id, python, args.workers, args.keys_file)


if __name__ == '__main__':
    main()
