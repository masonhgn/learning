"""Convert a .tts.txt file (output of md_to_tts.py) into an MP3 via Edge TTS.

Splits the input on <break time="Xs" /> tags, synthesizes each text chunk
through Microsoft's neural voices (free, no API key), and stitches the chunks
back together with real silence of the requested durations.

Requirements:
    pip install edge-tts pydub
    ffmpeg on PATH  (winget install ffmpeg)

Usage:
    python tts_to_mp3.py concept_primer.tts.txt
    python tts_to_mp3.py concept_primer.tts.txt --voice en-US-GuyNeural
"""

import argparse
import asyncio
import io
import re
import sys
from pathlib import Path

import edge_tts
from pydub import AudioSegment

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
BREAK_RE = re.compile(r'<break\s+time="([\d.]+)s"\s*/>')


async def synth(text: str, voice: str) -> AudioSegment:
    communicate = edge_tts.Communicate(text, voice)
    buf = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return AudioSegment.from_file(io.BytesIO(bytes(buf)), format="mp3")


async def build(input_path: Path, output_path: Path, voice: str) -> None:
    content = input_path.read_text(encoding="utf-8")
    content = content.replace("<speak>", "").replace("</speak>", "").strip()

    # re.split with a capturing group gives: [text, dur, text, dur, ..., text]
    parts = BREAK_RE.split(content)

    final = AudioSegment.empty()
    total_chunks = sum(1 for i, p in enumerate(parts) if i % 2 == 0 and p.strip())
    done = 0

    for i, part in enumerate(parts):
        if i % 2 == 0:
            text = part.strip()
            if not text:
                continue
            done += 1
            print(f"  [{done}/{total_chunks}] synthesizing {len(text)} chars...")
            final += await synth(text, voice)
        else:
            final += AudioSegment.silent(duration=int(float(part) * 1000))

    print(f"  exporting {output_path} ({len(final) / 1000:.1f}s)...")
    final.export(output_path, format="mp3", bitrate="96k")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"Edge TTS voice (default: {DEFAULT_VOICE}). "
                         "Run `edge-tts --list-voices` to see all.")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    output = args.output or args.input.with_suffix("").with_suffix(".mp3")
    print(f"{args.input} -> {output}  (voice: {args.voice})")
    await build(args.input, output, args.voice)


if __name__ == "__main__":
    asyncio.run(main())
