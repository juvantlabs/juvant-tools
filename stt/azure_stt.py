"""
azure_stt.py — Azure Speech-to-Text for video / audio files
============================================================
Takes any video or audio file (MP4, AAC, WAV, or anything ffmpeg supports),
converts it to raw PCM 16-bit 16 kHz mono, and transcribes it using the
Azure Cognitive Services Speech SDK with optional speaker diarization
via ConversationTranscriber.

Standalone development tool for testing the Azure Speech pipeline against
real recordings. Not a production component — useful to validate STT
quality and diarization before integrating Azure Speech into a downstream
pipeline.

Usage:
    # Full transcription with diarization (default)
    python3 azure_stt.py lecture.mp4

    # Custom output file
    python3 azure_stt.py lecture.mp4 --output /tmp/transcript.txt

    # Without diarization
    python3 azure_stt.py lecture.mp4 --no-diarization

    # Custom language and phrase hints
    python3 azure_stt.py lecture.mp4 --language it-IT --phrases foo bar baz

    # Azure credentials via CLI (or set AZURE_SPEECH_KEY / AZURE_SPEECH_REGION env vars)
    python3 azure_stt.py lecture.mp4 --key <key> --region westeurope

Environment variables:
    AZURE_SPEECH_KEY      Azure Speech subscription key
    AZURE_SPEECH_REGION   Azure Speech region (e.g. westeurope)

Dependencies (not in requirements.txt — dev tool only):
    pip install azure-cognitiveservices-speech
    ffmpeg must be available on PATH
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="azure_stt.py",
        description="Azure Speech-to-Text for audio files with speaker diarization.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "input_file",
        help="Path to the input audio file (AAC, MP4, WAV, or any format supported by ffmpeg)",
    )
    p.add_argument(
        "--output",
        default="/tmp/azure_stt_transcript.txt",
        help="Path to the output transcript file",
    )
    p.add_argument(
        "--key",
        default=None,
        help="Azure Speech subscription key (default: AZURE_SPEECH_KEY env var)",
    )
    p.add_argument(
        "--region",
        default=None,
        help="Azure Speech region, e.g. westeurope (default: AZURE_SPEECH_REGION env var)",
    )
    p.add_argument(
        "--language",
        default="en-US",
        help="Speech recognition language in BCP-47 format",
    )
    p.add_argument(
        "--silence-timeout",
        type=int,
        default=1000,
        metavar="MS",
        help="End-of-sentence silence timeout in milliseconds",
    )
    p.add_argument(
        "--phrases",
        nargs="+",
        default=[],
        metavar="PHRASE",
        help="Custom phrase hints for the recognizer",
    )
    p.add_argument(
        "--no-diarization",
        action="store_true",
        help="Disable speaker diarization (use plain SpeechRecognizer instead of ConversationTranscriber)",
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=3200,
        metavar="BYTES",
        help="PCM chunk size in bytes fed to the push stream (default: 3200 = 100ms at 16kHz 16-bit mono)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Maximum seconds to wait for transcription to complete after PCM feed ends (default: auto from video duration + 20%% buffer)",
    )
    return p


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def check_ffmpeg() -> None:
    """Exit with a clear message if ffmpeg is not available on PATH."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: ffmpeg not found on PATH.")
        print("Install with: brew install ffmpeg  (macOS) or apt install ffmpeg  (Linux)")
        sys.exit(1)


def get_video_duration(input_path: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve Azure Speech key and region from CLI args or environment variables."""
    key = args.key or os.environ.get("AZURE_SPEECH_KEY", "")
    region = args.region or os.environ.get("AZURE_SPEECH_REGION", "")
    if not key:
        print("ERROR: Azure Speech key not provided.")
        print("Use --key or set the AZURE_SPEECH_KEY environment variable.")
        sys.exit(1)
    if not region:
        print("ERROR: Azure Speech region not provided.")
        print("Use --region or set the AZURE_SPEECH_REGION environment variable.")
        sys.exit(1)
    return key, region


# ---------------------------------------------------------------------------
# Audio conversion
# ---------------------------------------------------------------------------

def convert_to_pcm(input_path: Path) -> Path:
    """
    Convert any video/audio file to raw PCM 16-bit 16 kHz mono using ffmpeg.
    Returns the path to a temporary PCM file (caller is responsible for deletion).
    """
    pcm_path = Path(tempfile.mktemp(suffix=".raw"))
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-f", "s16le",
        str(pcm_path),
    ]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(f"ERROR: ffmpeg failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"  PCM size: {pcm_path.stat().st_size:,} bytes")
    return pcm_path


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe(
    pcm_path: Path,
    key: str,
    region: str,
    language: str,
    silence_timeout_ms: int,
    extra_phrases: list[str],
    use_diarization: bool,
    chunk_size: int,
    timeout_seconds: int,
    output_file,
) -> list[dict]:
    """
    Feed the PCM file to Azure Speech and collect utterance results.
    Each utterance is appended to output_file immediately as it arrives,
    so `tail -f <output>` shows live progress.
    """
    # Late import so --help works without the SDK installed
    try:
        import azure.cognitiveservices.speech as speechsdk  # noqa: PLC0415
    except ImportError:
        print("ERROR: azure-cognitiveservices-speech is not installed.")
        print("Install with: pip install azure-cognitiveservices-speech")
        sys.exit(1)

    # --- Speech config --------------------------------------------------
    config = speechsdk.SpeechConfig(subscription=key, region=region)
    config.speech_recognition_language = language
    config.request_word_level_timestamps()
    config.set_profanity(speechsdk.ProfanityOption.Raw)
    config.set_property(
        speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption,
        "TrueText",
    )
    config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
        str(silence_timeout_ms),
    )

    # --- Audio stream ---------------------------------------------------
    stream = speechsdk.audio.PushAudioInputStream(
        speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
    )
    audio_config = speechsdk.audio.AudioConfig(stream=stream)

    # --- Results and control flags -------------------------------------
    results: list[dict] = []
    done = False
    canceled_reason: str = ""

    all_phrases = list(set(extra_phrases))

    # --- Build recognizer ----------------------------------------------
    if use_diarization:
        recognizer = speechsdk.transcription.ConversationTranscriber(
            speech_config=config,
            audio_config=audio_config,
        )
        phrase_list = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
        for phrase in all_phrases:
            phrase_list.addPhrase(phrase)

        def on_transcribed(evt: speechsdk.transcription.ConversationTranscriptionEventArgs) -> None:
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                offset_ms = evt.result.offset // 10000
                entry = {
                    "offset_ms": offset_ms,
                    "speaker": evt.result.speaker_id or "Unknown",
                    "text": evt.result.text,
                }
                results.append(entry)
                line = f"[{offset_ms:8d}ms] [{entry['speaker']}] {entry['text']}"
                print(f"  {line}")
                output_file.write(line + "\n")
                output_file.flush()

        def on_stopped(evt) -> None:  # noqa: ANN001
            nonlocal done
            done = True

        def on_canceled(evt: speechsdk.transcription.ConversationTranscriptionCanceledEventArgs) -> None:
            nonlocal done, canceled_reason
            canceled_reason = f"{evt.reason}"
            if evt.reason == speechsdk.CancellationReason.Error:
                canceled_reason += f" — {evt.error_details}"
            done = True

        recognizer.transcribed.connect(on_transcribed)
        recognizer.session_stopped.connect(on_stopped)
        recognizer.canceled.connect(on_canceled)
        recognizer.start_transcribing_async()

    else:
        # Plain SpeechRecognizer without diarization
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=config,
            audio_config=audio_config,
        )
        phrase_list = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
        for phrase in all_phrases:
            phrase_list.addPhrase(phrase)

        def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                offset_ms = evt.result.offset // 10000
                entry = {
                    "offset_ms": offset_ms,
                    "speaker": "Speaker",
                    "text": evt.result.text,
                }
                results.append(entry)
                line = f"[{offset_ms:8d}ms] [Speaker] {entry['text']}"
                print(f"  {line}")
                output_file.write(line + "\n")
                output_file.flush()

        def on_stopped(evt) -> None:  # noqa: ANN001
            nonlocal done
            done = True

        def on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
            nonlocal done, canceled_reason
            canceled_reason = f"{evt.reason}"
            if evt.reason == speechsdk.CancellationReason.Error:
                canceled_reason += f" — {evt.error_details}"
            done = True

        recognizer.recognized.connect(on_recognized)
        recognizer.session_stopped.connect(on_stopped)
        recognizer.canceled.connect(on_canceled)
        recognizer.start_continuous_recognition_async()

    # --- Feed PCM -------------------------------------------------------
    pcm_size = pcm_path.stat().st_size
    fed_bytes = 0
    print(f"\nFeeding PCM to Azure Speech ({pcm_size:,} bytes, chunk={chunk_size}B)...")

    with open(pcm_path, "rb") as f:
        while chunk := f.read(chunk_size):
            stream.write(chunk)
            fed_bytes += len(chunk)
    stream.close()
    print(f"  Feed complete: {fed_bytes:,} bytes sent.")

    # --- Wait for session_stopped ---------------------------------------
    print(f"Waiting for transcription to complete (timeout: {timeout_seconds}s)...")
    deadline = time.time() + timeout_seconds
    while not done and time.time() < deadline:
        time.sleep(0.1)

    if not done:
        print(f"WARNING: Transcription timed out after {timeout_seconds}s — writing partial results.")
    elif canceled_reason:
        print(f"ERROR: Transcription canceled: {canceled_reason}")
        if not results:
            sys.exit(1)

    # --- Stop recognizer -----------------------------------------------
    if use_diarization:
        recognizer.stop_transcribing_async()
    else:
        recognizer.stop_continuous_recognition_async()

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_header(f, input_path: Path, language: str, use_diarization: bool) -> None:
    """Write the transcript header. Called once before transcription starts."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    diarization_label = "enabled" if use_diarization else "disabled"
    lines = [
        "=" * 60,
        "  Azure Speech-to-Text Transcript",
        "=" * 60,
        f"Input       : {input_path.resolve()}",
        f"Language    : {language}",
        f"Date        : {now}",
        f"Diarization : {diarization_label}",
        "=" * 60,
        "",
    ]
    f.write("\n".join(lines) + "\n")
    f.flush()


def write_footer(f, results: list[dict]) -> None:
    """Append the summary footer. Called once after transcription ends."""
    unique_speakers = len(set(r["speaker"] for r in results))
    total_duration_ms = results[-1]["offset_ms"] if results else 0
    lines = [
        "",
        "=" * 60,
        f"Total utterances  : {len(results)}",
        f"Unique speakers   : {unique_speakers}",
        f"Total duration    : {total_duration_ms}ms",
        "=" * 60,
    ]
    f.write("\n".join(lines) + "\n")
    f.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Validate input file
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    # Check ffmpeg
    check_ffmpeg()

    # Resolve timeout dynamically from video duration if not set manually
    duration_s = get_video_duration(input_path)
    if args.timeout is not None:
        timeout = args.timeout
        timeout_source = "manual"
    elif duration_s > 0:
        timeout = int(duration_s * 1.2) + 60   # duration + 20% + 60s buffer
        timeout_source = f"auto ({int(duration_s)}s video + 20% + 60s buffer)"
    else:
        timeout = 600
        timeout_source = "fallback (duration unknown)"

    # Resolve Azure credentials
    key, region = resolve_credentials(args)

    print(f"\n=== Azure STT ===")
    print(f"Input      : {input_path}")
    print(f"Output     : {args.output}")
    print(f"Language   : {args.language}")
    print(f"Diarization: {'enabled' if not args.no_diarization else 'disabled'}")
    print(f"Region     : {region}")
    print(f"Phrases    : {args.phrases or '(none)'}")
    print(f"Timeout    : {timeout}s ({timeout_source})")
    print()

    # Convert to PCM
    print("[*] Step 1/2 — Converting video to PCM audio...")
    pcm_path = convert_to_pcm(input_path)
    print("[*] Video processing done.\n")

    use_diarization = not args.no_diarization

    print("[*] Step 2/2 — Starting transcription with Azure Speech...")
    with open(args.output, "w", encoding="utf-8") as out_f:
        write_header(out_f, input_path, args.language, use_diarization)
        print(f"[*] Streaming transcript to {args.output} — run: tail -f {args.output}\n")

        try:
            results = transcribe(
                pcm_path=pcm_path,
                key=key,
                region=region,
                language=args.language,
                silence_timeout_ms=args.silence_timeout,
                extra_phrases=args.phrases,
                use_diarization=use_diarization,
                chunk_size=args.chunk_size,
                timeout_seconds=timeout,
                output_file=out_f,
            )
        finally:
            if pcm_path.exists():
                pcm_path.unlink()
                print(f"\nTemporary PCM file deleted: {pcm_path}")

        write_footer(out_f, results)

    unique_speakers = len(set(r["speaker"] for r in results))
    print(f"\n=== STT complete ===")
    print(f"Output file     : {args.output}")
    print(f"Utterances      : {len(results)}")
    print(f"Unique speakers : {unique_speakers}")


if __name__ == "__main__":
    main()
