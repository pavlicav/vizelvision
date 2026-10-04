"""Whisper helper. Length-prefixed 16 kHz F32LE PCM in, one JSON result per chunk out.

Run with the Python containing faster-whisper, independently of GStreamer's Python.
Models must be cached beforehand: enabling captions never downloads anything.
"""
import argparse
import json
import os
import struct
import sys


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--language', required=True)
    args = parser.parse_args()
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    try:
        from faster_whisper import WhisperModel
        import numpy as np
        model = WhisperModel(args.model, device='cpu', compute_type='int8', cpu_threads=2,
                             num_workers=1, local_files_only=True)
    except Exception as exc:
        emit({'error': 'Whisper is unavailable. Install the captions extra and cache the selected model '
                       'with the caption Python (see docs/live-captions.md). ' + str(exc)[:300]})
        return
    emit({'ready': True})
    while header := sys.stdin.buffer.read(4):
        if len(header) != 4:
            return
        size, = struct.unpack('!I', header)
        if not 0 < size <= 16000 * 4 * 8 or size % 4:
            return
        pcm = sys.stdin.buffer.read(size)
        if len(pcm) != size:
            return
        try:
            audio = np.frombuffer(pcm, dtype='<f4').copy()
            # A quiet feed cannot produce a hallucinated subtitle; VAD also suppresses
            # most music/noise. Models still make mistakes, as with any live ASR.
            if np.max(np.abs(audio)) < .005:
                emit({'text': '', 'segments': []})
                continue
            segments, _ = model.transcribe(audio, language=None if args.language == 'auto' else args.language,
                                           beam_size=1, temperature=0, condition_on_previous_text=False,
                                           word_timestamps=True, vad_filter=True,
                                           vad_parameters={'min_silence_duration_ms': 400})
            rows = [{'start': s.start, 'end': s.end, 'text': s.text.strip(),
                     'words': [{'start': w.start, 'end': w.end, 'text': w.word} for w in (s.words or [])]}
                    for s in segments if s.no_speech_prob < .6 and s.avg_logprob > -1 and s.compression_ratio < 2.4]
            emit({'text': ' '.join(s['text'] for s in rows)[:1000], 'segments': rows})
        except Exception as exc:
            emit({'error': 'Whisper transcription failed: ' + str(exc)[:300]})


if __name__ == '__main__':
    main()
