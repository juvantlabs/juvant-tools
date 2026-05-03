# audio/

Audio extraction and raw-PCM processing utilities. Standalone scripts —
run directly via `python3 audio/<script>.py`.

## Tools

| Script | What it does |
|---|---|
| [`video_to_audio.py`](video_to_audio.py) | Wraps `ffmpeg` to pull the audio stream out of any video file and save it as WAV (default), MP3, AAC, or raw PCM 16-bit 16kHz mono. |
| [`raw_pcm_to_wav.py`](raw_pcm_to_wav.py) | Convert a raw PCM capture file (8-byte header: `sampleRate` + `channelCount` as uint32le, then Int16 interleaved samples) into a WAV file. Trims silent frames, downmixes to mono, resamples to a configurable target rate (default 16 kHz). |

## Prerequisites

```bash
# ffmpeg must be on PATH for video_to_audio.py
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Linux
```

`raw_pcm_to_wav.py` uses only Python's stdlib (`struct`, `wave`).

## Quick examples

```bash
# Extract WAV from an MP4
python3 audio/video_to_audio.py recording.mp4

# Extract raw PCM 16k mono (the format speech-analysis pipelines expect)
python3 audio/video_to_audio.py recording.mp4 --format pcm --output-file audio.raw

# Process a raw PCM capture into WAV
python3 audio/raw_pcm_to_wav.py /tmp/audio_raw.bin /tmp/processed.wav
```
