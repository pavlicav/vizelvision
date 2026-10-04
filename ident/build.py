"""Build the VizelVision station ID: vizelvision-id.mp4 beside this file. With --sports,
build the VizelVision Sports ID instead (vizelvision-sports.mp4), which plays before games.

    /usr/bin/python3 ident/build.py [--sports] [--keys-file FILE] [--workers 3]

1. DJ Low Tide's lines (voice.py): only lines that are missing or whose text
   changed are sent to Deepgram, and only when a key is available.
2. The jingle (jingle.py), under a Python that has numpy and scipy.
3. The picture (animation.py, pycairo), piped straight into ffmpeg with the
   audio normalised to the loudness of the TV recordings it plays between.

Everything runs at the lowest CPU priority: the live master shares this machine.
The finished file replaces the old one in a single rename, so a master that is
playing the ID keeps reading the old copy undisturbed.
"""
import argparse
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import animation  # noqa: E402
import sports_animation  # noqa: E402
import timeline as T  # noqa: E402
import voice  # noqa: E402

OUTPUT = HERE / 'vizelvision-id.mp4'
SPORTS_OUTPUT = HERE / 'vizelvision-sports.mp4'
BUILD = HERE / 'build'
MUSIC = BUILD / 'music.wav'  # The jingle without its voice, for continuity announcements.
LOUDNESS = -20.0   # LUFS: the TV-Thing recordings measure about -20.
TRUE_PEAK = -2.0


def numpy_python(explicit):
    candidates = [explicit] if explicit else [
        sys.executable, str(Path.home() / 'miniconda3' / 'bin' / 'python3'), shutil.which('python3')]
    for candidate in candidates:
        if candidate and subprocess.run([candidate, '-c', 'import numpy, scipy'],
                                        capture_output=True).returncode == 0:
            return candidate
    raise SystemExit('The jingle needs a Python with numpy and scipy: pass --numpy-python')


def measure(audio):
    result = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(audio), '-af',
         f'loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:print_format=json', '-f', 'null', '-'],
        capture_output=True, text=True, check=True)
    report = result.stderr
    return json.loads(report[report.rindex('{'):report.rindex('}') + 1])


def encode(audio, workers, picture=animation, output=OUTPUT):
    m = measure(audio)
    audio_filter = (f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:measured_I={m['input_i']}:"
                    f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                    f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
                    "aresample=48000")
    # A touch of VHS: red and blue a pixel or two apart, and moving grain.
    video_filter = 'rgbashift=rh=-2:bh=2,noise=alls=4:allf=t,format=yuv420p'
    partial = output.with_suffix('.part.mp4')
    command = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
               '-f', 'rawvideo', '-pix_fmt', 'bgr0', '-s', f'{T.WIDTH}x{T.HEIGHT}', '-r', str(T.FPS), '-i', '-',
               '-i', str(audio), '-vf', video_filter, '-af', audio_filter,
               '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-profile:v', 'high', '-g', str(T.FPS),
               '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
               '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
               '-t', f'{T.DURATION:.3f}', '-movflags', '+faststart', str(partial)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    total, started = picture.frames(), time.monotonic()
    try:
        with multiprocessing.Pool(workers) as pool:
            for index, frame in enumerate(pool.imap(picture.render, range(total), chunksize=4)):
                encoder.stdin.write(frame)
                if index % (T.FPS * 5) == 0:
                    print(f'  picture: {index / T.FPS:4.1f} s  ({time.monotonic() - started:.0f} s elapsed)')
    finally:
        encoder.stdin.close()
        if encoder.wait():
            partial.unlink(missing_ok=True)
            raise SystemExit('ffmpeg could not encode the ID')
    return partial, m


def verify(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                             'format=duration:stream=codec_type,codec_name,width,height,r_frame_rate',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    kinds = {s['codec_type'] for s in info['streams']}
    duration = float(info['format']['duration'])
    if kinds != {'video', 'audio'} or abs(duration - T.DURATION) > 0.1:
        raise SystemExit(f'The encoded ID is wrong: tracks {sorted(kinds)}, {duration:.2f} s')
    return duration


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the VizelVision station ID')
    parser.add_argument('--sports', action='store_true', help='build the VizelVision Sports ID')
    parser.add_argument('--keys-file', type=Path, help='a file with DEEPGRAM_API_KEY=... for new voice lines')
    parser.add_argument('--numpy-python', help='Python to run the jingle with (needs numpy and scipy)')
    parser.add_argument('--workers', type=int, default=3, help='frame-drawing processes (default 3)')
    args = parser.parse_args(argv)
    os.nice(19)
    sys.stdout.reconfigure(line_buffering=True)
    BUILD.mkdir(exist_ok=True)

    script = json.loads((HERE / ('sports_script.json' if args.sports else 'script.json')).read_text())
    missing = [line['id'] for line in script['lines'] if not (voice.VOICE_DIR / f"{line['id']}.wav").exists()]
    if args.keys_file or os.environ.get('DEEPGRAM_API_KEY'):
        print(f"Voice ({script['host']}, {script['model']}):")
        voice.render(script, args.keys_file)
    elif missing:
        print(f"Voice: no Deepgram key; building without {', '.join(missing)}")

    print('Jingle:')
    python = numpy_python(args.numpy_python)
    if args.sports:
        audio, picture, output = BUILD / 'sports-audio.wav', sports_animation, SPORTS_OUTPUT
        subprocess.run([python, str(HERE / 'sports_jingle.py'), str(audio)], check=True)
    else:
        audio, picture, output = BUILD / 'audio.wav', animation, OUTPUT
        subprocess.run([python, str(HERE / 'jingle.py'), str(audio)], check=True)
        # The same music without the voice: continuity announcements are mixed over it.
        subprocess.run([python, str(HERE / 'jingle.py'), '--no-voice', str(MUSIC)], check=True)

    print(f'Picture: {picture.frames()} frames at {T.FPS} fps')
    partial, loudness = encode(audio, args.workers, picture, output)
    duration = verify(partial)
    partial.replace(output)
    print(f"Done: {output} ({duration:.2f} s, {output.stat().st_size / 1e6:.1f} MB, "
          f"audio {loudness['input_i']} LUFS -> {LOUDNESS:g})")


if __name__ == '__main__':
    main()
