"""Render the station ID's voice-over lines with Deepgram Aura (DJ Low Tide's voice).

Each line is rendered once and kept in voice/<id>.wav with its script beside it.
A line is only sent again when its text or model changes, so rebuilding the ID
costs nothing. The API key comes from DEEPGRAM_API_KEY or a KEY=value file given
with --keys-file; it is never printed or written anywhere.
"""
import argparse
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICE_DIR = HERE / 'voice'
SAMPLE_RATE = 48000
ATTEMPTS = 4


def api_key(keys_file):
    key = os.environ.get('DEEPGRAM_API_KEY')
    if not key and keys_file:
        for line in Path(keys_file).read_text().splitlines():
            name, _, value = line.strip().removeprefix('export ').partition('=')
            if name.strip() == 'DEEPGRAM_API_KEY':
                key = value.strip().strip('"\'')
    if not key:
        raise SystemExit('No Deepgram key: set DEEPGRAM_API_KEY or pass --keys-file')
    return key


def fingerprint(model, text):
    return hashlib.sha256(f'{model}\n{text}'.encode()).hexdigest()


def speak(key, model, text):
    request = urllib.request.Request(
        f'https://api.deepgram.com/v1/speak?model={model}&encoding=linear16&container=wav'
        f'&sample_rate={SAMPLE_RATE}',
        data=json.dumps({'text': text}).encode(),
        headers={'Authorization': f'Token {key}', 'Content-Type': 'application/json'})
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                audio = response.read()
                declared = response.headers.get('Content-Length')
            # A dropped stream is a line cut off mid-word: never keep one.
            if declared and len(audio) < int(declared):
                raise http.client.IncompleteRead(audio, int(declared) - len(audio))
            return audio
        except urllib.error.HTTPError as exc:
            raise SystemExit(f'Deepgram refused the line ({exc.code}): '
                             f'{exc.read()[:200].decode(errors="replace")}') from None
        except (http.client.IncompleteRead, ConnectionResetError, TimeoutError):
            if attempt + 1 == ATTEMPTS:
                raise
            time.sleep(1.5 * (attempt + 1))


def seal_wav(path):
    """Deepgram streams its WAV, so the header declares a placeholder length.
    Rewrite it for the PCM that actually arrived."""
    raw = path.read_bytes()
    at = raw.find(b'data', 12)
    if raw[:4] != b'RIFF' or at < 0:
        raise SystemExit(f'{path.name}: Deepgram did not return a WAV file')
    if int.from_bytes(raw[at + 4:at + 8], 'little') == len(raw) - at - 8:
        return
    pcm = raw[at + 8:]
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(pcm[:len(pcm) // 2 * 2])


def check_wav(path):
    seal_wav(path)
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, SAMPLE_RATE):
            raise SystemExit(f'{path.name}: unexpected audio format from Deepgram')
        frames = audio.getnframes()
        if frames < SAMPLE_RATE // 4:
            raise SystemExit(f'{path.name}: line is empty or too short')
        return frames / SAMPLE_RATE


def render(script, keys_file=None, force=False):
    VOICE_DIR.mkdir(exist_ok=True)
    key = None
    for line in script['lines']:
        model = line.get('model', script['model'])   # a line may have its own voice
        wav, meta = VOICE_DIR / f"{line['id']}.wav", VOICE_DIR / f"{line['id']}.json"
        digest = fingerprint(model, line['text'])
        try:
            current = json.loads(meta.read_text()).get('fingerprint') == digest and wav.exists()
        except (OSError, ValueError):
            current = False
        if current and not force:
            print(f"  {line['id']}: cached ({check_wav(wav):.2f} s)")
            continue
        key = key or api_key(keys_file)
        partial = wav.with_suffix('.wav.part')
        partial.write_bytes(speak(key, model, line['text']))
        seconds = check_wav(partial)
        partial.replace(wav)
        meta.write_text(json.dumps({'host': script.get('host'), 'model': model, 'text': line['text'],
                                    'fingerprint': digest, 'seconds': round(seconds, 3),
                                    'rendered_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}, indent=2) + '\n')
        print(f"  {line['id']}: rendered ({seconds:.2f} s)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--script', default=HERE / 'script.json', type=Path)
    parser.add_argument('--keys-file', type=Path, help='file with a DEEPGRAM_API_KEY=... line')
    parser.add_argument('--force', action='store_true', help='render every line again')
    args = parser.parse_args(argv)
    render(json.loads(args.script.read_text()), args.keys_file, args.force)


if __name__ == '__main__':
    sys.exit(main())
