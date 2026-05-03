# stt/

Speech-to-Text utilities. Standalone scripts — run directly via
`python3 stt/<script>.py`.

## Tools

| Script | What it does |
|---|---|
| [`azure_stt.py`](azure_stt.py) | Transcribe any video / audio file (anything `ffmpeg` can decode) using Azure Cognitive Services Speech SDK, with optional speaker diarization via `ConversationTranscriber`. Streams the transcript to a file as utterances arrive (`tail -f` friendly). |

## Prerequisites

```bash
# Azure Speech SDK
pip install azure-cognitiveservices-speech

# ffmpeg on PATH for the audio conversion step
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Linux

# Azure credentials (key + region)
export AZURE_SPEECH_KEY=<your-key>
export AZURE_SPEECH_REGION=westeurope
```

## Quick example

```bash
# Transcribe an mp4 with speaker diarization, English (default)
python3 stt/azure_stt.py lecture.mp4

# Italian, with custom phrase hints, no diarization
python3 stt/azure_stt.py lecture.mp4 \
  --language it-IT \
  --phrases acronym1 acronym2 \
  --no-diarization
```

## Why standalone (not packaged)

This is a development / validation tool — useful to evaluate Azure STT
quality and diarization against real recordings before committing to a
specific provider in a downstream pipeline. It is not a production
component, so it ships as a script rather than a versioned CLI command.
