"""
raw_pcm_to_wav.py — Convert a raw PCM capture file to WAV
==========================================================
Reads a raw binary file written in the simple "PCM with 8-byte header"
format described below, applies frame-by-frame processing (silence trim,
optional channel downmix, optional resampling), and writes a WAV file at
the configured target rate (16 kHz mono by default).

Useful when an upstream pipeline dumps raw PCM samples plus rate/channel
metadata for offline inspection, and you want to listen to the captured
audio without a fresh recording session.

Input file format:
    bytes 0-3:  sampleRate   (uint32 little-endian)
    bytes 4-7:  channelCount (uint32 little-endian)
    bytes 8+:   raw Int16 little-endian, channels interleaved

Usage:
    python3 raw_pcm_to_wav.py [--input PATH] [--output PATH]
                              [--target-rate HZ] [--frame-ms MS]
"""

import argparse
import struct
import wave
from pathlib import Path


def process(
    raw_path: Path,
    out_path: Path,
    target_rate: int,
    frame_ms: int,
    silence_threshold: int,
) -> None:
    with open(raw_path, "rb") as f:
        hdr = f.read(8)
        sample_rate   = struct.unpack_from("<I", hdr, 0)[0]
        channel_count = struct.unpack_from("<I", hdr, 4)[0]
        raw = f.read()

    total_samples = len(raw) // 2
    samples_all = struct.unpack(f"<{total_samples}h", raw)

    print(f"Raw file:      {raw_path}")
    print(f"Sample rate:   {sample_rate} Hz")
    print(f"Channels:      {channel_count}")
    print(f"Total samples: {total_samples} ({total_samples / sample_rate / channel_count:.2f}s of audio)")

    frame_samples_in  = sample_rate * frame_ms // 1000
    int_ratio = max(1, round(sample_rate / target_rate))
    frame_samples_out = frame_samples_in // int_ratio

    print(f"\nProcessing:    {sample_rate}Hz → {target_rate}Hz  (intRatio={int_ratio})")
    print(f"Frame size:    {frame_samples_in} input → {frame_samples_out} output samples ({frame_ms}ms)")

    frame_bytes_out = target_rate * frame_ms // 1000 * 2
    buf = bytearray()
    output_frames = []

    pos = 0
    while pos + frame_samples_in * channel_count <= total_samples:
        chunk = samples_all[pos: pos + frame_samples_in * channel_count]
        pos += frame_samples_in * channel_count

        chunk_peak = max(abs(s) for s in chunk)
        if chunk_peak < silence_threshold:
            continue

        if channel_count > 1:
            frames = len(chunk) // channel_count
            mono = []
            for i in range(frames):
                s = round(sum(chunk[i * channel_count + c] for c in range(channel_count)) / channel_count)
                mono.append(s)
        else:
            mono = list(chunk)

        out_len = len(mono) // int_ratio
        resampled = []
        for i in range(out_len):
            base = i * int_ratio
            s = round(sum(mono[base + j] for j in range(int_ratio)) / int_ratio)
            resampled.append(s)

        frame_bytes = struct.pack(f"<{len(resampled)}h", *resampled)
        buf.extend(frame_bytes)

        while len(buf) >= frame_bytes_out:
            output_frames.append(bytes(buf[:frame_bytes_out]))
            buf = buf[frame_bytes_out:]

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(target_rate)
        wf.writeframes(b"".join(output_frames))

    total_out_s = len(output_frames) * frame_ms / 1000
    print(f"\nOutput:        {out_path}")
    print(f"Frames:        {len(output_frames)} ({total_out_s:.2f}s)")
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="raw_pcm_to_wav.py",
        description="Convert a raw PCM capture (8-byte header + Int16 samples) to WAV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        default="/tmp/audio_raw.bin",
        help="Path to the raw PCM input file",
    )
    parser.add_argument(
        "--output", "-o",
        default="analyzed_output.wav",
        help="Path to the WAV output file",
    )
    parser.add_argument(
        "--target-rate",
        type=int,
        default=16000,
        metavar="HZ",
        help="Output sample rate",
    )
    parser.add_argument(
        "--frame-ms",
        type=int,
        default=20,
        metavar="MS",
        help="Frame duration in milliseconds",
    )
    parser.add_argument(
        "--silence-threshold",
        type=int,
        default=50,
        help="Per-frame absolute peak below which the frame is skipped (silence trim)",
    )
    args = parser.parse_args()

    process(
        raw_path=Path(args.input),
        out_path=Path(args.output),
        target_rate=args.target_rate,
        frame_ms=args.frame_ms,
        silence_threshold=args.silence_threshold,
    )


if __name__ == "__main__":
    main()
