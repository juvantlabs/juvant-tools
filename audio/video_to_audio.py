"""
video_to_audio.py — Extract audio from a video file using ffmpeg
================================================================
Wraps ffmpeg to pull the audio stream out of a video file and save it
as WAV (default), MP3, AAC, or raw PCM (16-bit 16kHz mono).

WAV is recommended for general audio work (lossless, widely compatible).
PCM is the raw format expected by speech-analysis pipelines (e.g. Whisper)
and downstream tools that consume raw 16k mono samples.
MP3/AAC are better when file size matters.

Usage:
  python3 video_to_audio.py input.mp4
  python3 video_to_audio.py input.mp4 --output-file output.wav
  python3 video_to_audio.py input.mp4 --format mp3
  python3 video_to_audio.py input.mp4 --format aac --output-file session.m4a
  python3 video_to_audio.py input.mp4 --format pcm --output-file audio.raw

Dependencies: ffmpeg must be installed and available on PATH
  macOS:  brew install ffmpeg
  Linux:  apt install ffmpeg
"""

import argparse
import subprocess
import sys
from pathlib import Path

FORMAT_SETTINGS = {
    "wav": {"ext": ".wav", "codec": "pcm_s16le", "extra": []},
    "mp3": {"ext": ".mp3", "codec": "libmp3lame", "extra": []},
    "aac": {"ext": ".m4a", "codec": "aac", "extra": []},
    # Raw signed 16-bit little-endian PCM, 16kHz, mono — no container
    "pcm": {"ext": ".raw", "codec": "pcm_s16le", "extra": ["-ar", "16000", "-ac", "1", "-f", "s16le"]},
}


def extract_audio(input_path: Path, output_path: Path, fmt: str) -> None:
    settings = FORMAT_SETTINGS[fmt]
    cmd = [
        "ffmpeg",
        "-y",                   # overwrite output without asking
        "-i", str(input_path),
        "-vn",                  # drop video stream
        "-acodec", settings["codec"],
        *settings["extra"],     # format-specific flags (e.g. -ar 16000 -ac 1 for pcm)
        str(output_path),
    ]

    print(f"[*] Input:  {input_path}")
    print(f"[*] Output: {output_path} ({fmt.upper()})")
    print(f"[*] Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(f"[!] ffmpeg failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[*] Done — {output_path} ({size_mb:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract audio from a video file using ffmpeg"
    )
    parser.add_argument("input", help="Input video file (e.g. recording.mp4)")
    parser.add_argument(
        "--output-file", "-o",
        default=None,
        help="Output audio file path (default: same name as input with new extension)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=FORMAT_SETTINGS.keys(),
        default="wav",
        help="Output audio format: wav (default), mp3, aac, pcm (16-bit 16kHz mono raw)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[!] File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    fmt = args.format
    if args.output_file:
        output_path = Path(args.output_file)
    else:
        output_path = input_path.with_suffix(FORMAT_SETTINGS[fmt]["ext"])

    extract_audio(input_path, output_path, fmt)


if __name__ == "__main__":
    main()
