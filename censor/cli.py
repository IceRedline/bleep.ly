import argparse
import json
import logging
import math
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from .audio import prepare_sound, render_video
from .fcpxml import export_fcpxml
from .ffmpeg import extract_audio, media_info, require_tools, sound_duration
from .ranges import censor_ranges, middle_ranges
from .profanity import ProfanityMatcher
from .progress import Progress
from .mlx_backend import MLXWhisperBackend, resolve_model
from .speakers import cue_owners, diarize, identify_reference, label_words, validate_segments
from .transcription import (FasterWhisperBackend, cache_key, classify, load_cache,
                            parse_words, read_transcript, save_transcript)
from .utils import CensorError, timestamp


def nonnegative(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("must be finite and >= 0")
    return result


def attenuation(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result > 0:
        raise argparse.ArgumentTypeError("must be finite and <= 0 dB")
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="bleeply — locally censor Russian profanity in video without re-encoding video.")
    cli.add_argument("input", type=Path, help="source video")
    cli.add_argument("--sound", type=Path, help="custom WAV/audio file (required for rendering)")
    cli.add_argument("--sound-others", type=Path, help="second cue for other speakers; --sound is your cue")
    cli.add_argument("--speaker-reference", nargs=2, type=nonnegative, metavar=("START", "END"),
                     help="seconds in this video where only you speak; enables speaker labeling")
    cli.add_argument("--num-speakers", type=int, default=4, help="speaker count for diarization (default: 4)")
    cli.add_argument("--speaker-model-dir", type=Path,
                     default=Path(__file__).resolve().parent.parent / ".cache" / "speaker-models")
    cli.add_argument("--speaker-segments", type=Path, help="reuse local diarization JSON with --speaker-reference")
    cli.add_argument("--output", type=Path, help="video output; default: INPUT_censored.mov")
    cli.add_argument("--language", default="ru")
    cli.add_argument("--model", default="large-v3-turbo", help="model name, backend-compatible HF repo or local directory")
    cli.add_argument("--backend", choices=["faster-whisper", "mlx"],
                     help="skip the interactive CPU/Apple GPU menu; non-interactive default: faster-whisper")
    cli.add_argument("--compute-type", choices=["int8", "float16", "float32", "int8_float32"],
                     help="default: int8 for CPU, float16 for MLX; MLX supports float16/float32")
    cli.add_argument("--offline", action="store_true", help="forbid model downloads")
    cli.add_argument("--padding-before", type=nonnegative, default=.05, metavar="SECONDS")
    cli.add_argument("--padding-after", type=nonnegative, default=.08, metavar="SECONDS")
    cli.add_argument("--merge-gap", type=nonnegative, default=.02, metavar="SECONDS")
    cli.add_argument("--censor-style", choices=["middle", "full"], default="middle",
                     help="middle (default): cover only the middle 60%% of each word, capped by sound length; full: mute the whole padded word")
    cli.add_argument("--mode", choices=["mute", "duck"], default="mute")
    cli.add_argument("--duck-db", type=attenuation, default=-30, metavar="DB")
    cli.add_argument("--fcpxml", type=Path, help="export FCPXML + WAV assets; no video unless --output is also supplied")
    cli.add_argument("--words", type=Path, default=Path(__file__).resolve().parent.parent / "profanity.txt",
                     help="replacement blacklist (one Russian word/stem per line)")
    reporting = cli.add_mutually_exclusive_group()
    reporting.add_argument("--dry-run", action="store_true", help="report only; no persistent transcript/cache/media writes")
    reporting.add_argument("--transcribe-only", action="store_true", help="save review JSON and cache without rendering or requiring --sound")
    cli.add_argument("--from-transcript", type=Path, help="use edited word timestamps and flags without Whisper")
    cli.add_argument("--transcript-output", type=Path, help="save review JSON here; existing files are never overwritten")
    cli.add_argument("--cache-dir", type=Path, help="default: INPUT_DIRECTORY/.cache/auto-censor")
    cli.add_argument("--audio-stream", type=int, help="zero-based AUDIO stream to process; required for multiple audio tracks")
    cli.add_argument("--verbose", action="store_true")
    return cli


def select_backend(explicit: str | None, from_transcript: Path | None) -> str:
    if explicit is not None:
        return explicit
    if from_transcript or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "faster-whisper"
    print("\nКакое ускорение использовать?\n"
          "  1 — Apple GPU (MLX / Metal)\n"
          "  2 — Без GPU — CPU (faster-whisper)")
    while True:
        try:
            answer = input("Выберите 1 или 2 [Enter — 2]: ").strip()
        except EOFError as exc:
            raise CensorError("Выбор отменён. Для запуска без вопроса укажите --backend mlx или --backend faster-whisper.") from exc
        if answer == "1":
            return "mlx"
        if answer in {"", "2"}:
            return "faster-whisper"
        print("Введите 1 или 2.")


def unique_transcript(source: Path) -> Path:
    result = source.with_suffix(".transcript.json")
    index = 1
    while result.exists():
        result = source.with_name(f"{source.stem}.transcript.{index}.json")
        index += 1
    return result


def preflight(args: argparse.Namespace, source: Path, output: Path | None, transcript: Path | None) -> None:
    reads = [source, args.sound, args.sound_others, args.speaker_segments, args.from_transcript, args.words]
    protected = {p.resolve() for p in reads if p is not None}
    writes = [p.resolve() for p in (output, args.fcpxml, transcript) if p is not None]
    if len(set(writes)) != len(writes) or protected.intersection(writes):
        raise CensorError("Output paths must be distinct from each other and from all input files.")
    for path in writes:
        if path.exists():
            raise CensorError(f"Output already exists: {path}. Choose another name.")
    if output and output.suffix.lower() not in {".mov", ".mp4", ".mkv"}:
        raise CensorError("Unsupported output container. Choose .mov, .mp4 or .mkv; video always uses stream copy.")
    if args.fcpxml:
        if args.fcpxml.suffix.lower() != ".fcpxml":
            raise CensorError("--fcpxml must end in .fcpxml")
        media_dir = args.fcpxml.resolve().with_name(args.fcpxml.stem + "_media")
        if media_dir.exists() or any(p.is_relative_to(media_dir) for p in [*protected, *writes]):
            raise CensorError(f"FCPXML media directory must be new and separate from other paths: {media_dir}")


def execute(args: argparse.Namespace) -> None:
    if sys.version_info < (3, 11):
        raise CensorError("Python 3.11 or newer is required.")
    args.backend = select_backend(args.backend, args.from_transcript)
    args.compute_type = args.compute_type or ("float16" if args.backend == "mlx" else "int8")
    if args.backend == "mlx":
        args.model = resolve_model(args.model)
        if args.compute_type not in {"float16", "float32"}:
            raise CensorError("--backend mlx supports --compute-type float16 or float32.")
    elif args.compute_type == "float16":
        raise CensorError("CPU backend does not support float16; use int8 or float32.")
    source = args.input.resolve()
    require_tools()
    info = media_info(source, args.audio_stream)
    if args.speaker_reference:
        start, end = args.speaker_reference
        if not 0 <= start < end <= info.duration or not 1 <= args.num_speakers <= 100:
            raise CensorError("Reference must satisfy 0 <= START < END <= duration; speaker count must be 1..100.")
        if not (args.dry_run or args.transcribe_only or args.sound_others):
            raise CensorError("Supply --sound-others for speaker-based rendering, or use --transcribe-only.")
    if args.speaker_segments and not args.speaker_reference:
        raise CensorError("--speaker-segments requires --speaker-reference START END.")
    if args.sound_others and not (args.speaker_reference or args.from_transcript):
        raise CensorError("--sound-others requires --speaker-reference or a transcript with speaker labels.")
    print(f"bleeply\n{'─' * 24}\nInput: {source}\nDuration: {timestamp(info.duration)}", flush=True)
    if info.audio_count > 1:
        print("Note: output includes only the selected audio track (downmixed to stereo).")
    if args.transcribe_only and (args.output or args.fcpxml):
        raise CensorError("--transcribe-only cannot be combined with --output or --fcpxml.")
    output = (None if args.transcribe_only else
              args.output or (None if args.fcpxml else source.with_name(source.stem + "_censored.mov")))
    transcript = args.transcript_output or (None if args.from_transcript and not args.speaker_reference else unique_transcript(source))
    sound_seconds = None
    if args.dry_run and args.sound:
        sound_seconds = sound_duration(args.sound.resolve())
    if not args.dry_run:
        preflight(args, source, output, transcript)
        if not args.transcribe_only:
            if args.sound is None:
                raise CensorError("Supply --sound censor.wav for rendering, or use --dry-run / --transcribe-only.")
            sound_seconds = sound_duration(args.sound.resolve())
    if args.sound_others:
        sound_duration(args.sound_others.resolve())
    with tempfile.TemporaryDirectory(prefix="bleeply-") as folder:
        work = Path(folder)
        metadata = {"source": str(source)}
        if args.from_transcript:
            print(f"Using reviewed transcript: {args.from_transcript}", flush=True)
            words = read_transcript(args.from_transcript, info.duration)
        else:
            try:
                matcher = ProfanityMatcher.from_file(args.words)
            except (OSError, ValueError) as exc:
                raise CensorError(f"Cannot load blacklist: {exc}") from exc
            print("Checking transcription cache…", flush=True)
            with Progress("Reading input", source.stat().st_size, unit="bytes") as bar:
                key, metadata = cache_key(source, args.model, args.language, args.compute_type,
                                          info.audio_index, bar.update, backend=args.backend)
            cache_dir = args.cache_dir or source.parent / ".cache" / "auto-censor"
            cache_path = cache_dir / f"{key}.json"
            # A cache destination must never overwrite a user-selected input/output.
            if cache_path.resolve() in {p.resolve() for p in (source, args.sound, args.sound_others, args.speaker_segments,
                                                            args.words, output, args.fcpxml, transcript) if p}:
                raise CensorError("Cache path collides with an input or output file.")
            words = load_cache(cache_path, info.duration)
            if words is None:
                audio = work / "speech.wav"
                with Progress("Extracting audio", info.duration) as bar:
                    extract_audio(source, audio, info, bar.update)
                device = "Apple GPU / Metal" if args.backend == "mlx" else "CPU"
                print(f"Loading model / transcribing locally ({device}, {args.compute_type}). "
                      "First progress update follows the first segment.", flush=True)
                backend_type = MLXWhisperBackend if args.backend == "mlx" else FasterWhisperBackend
                backend = backend_type(args.model, args.language, args.compute_type, args.offline)
                with Progress("Transcribing", info.duration) as bar:
                    raw = backend.transcribe(audio, bar.update)
                # Whisper occasionally emits zero-duration punctuation/words.
                valid = [w for w in raw if w.end > w.start and w.start < info.duration]
                if len(valid) != len(raw):
                    print(f"Warning: ignored {len(raw) - len(valid)} words with empty/out-of-range timestamps.")
                words = parse_words({"words": [asdict(w) for w in valid]}, info.duration)
                if not args.dry_run:
                    save_transcript(cache_path, words, metadata)
            else:
                print("Using cached word timestamps.", flush=True)
            words = classify(words, matcher)
        if args.speaker_reference:
            if args.speaker_segments:
                segments = validate_segments(json.loads(args.speaker_segments.read_text()), info.duration)
            else:
                audio = work / "speech.wav"
                if not audio.exists():
                    with Progress("Extracting audio", info.duration) as bar:
                        extract_audio(source, audio, info, bar.update)
                with Progress("Identifying speakers", info.duration) as bar:
                    segments = diarize(audio, args.speaker_model_dir, args.num_speakers,
                                       args.cache_dir or source.parent / ".cache" / "auto-censor",
                                       bar.update, info.duration, save_cache=not args.dry_run)
            mine, reference = identify_reference(segments, *args.speaker_reference)
            words = label_words(words, segments, mine)
            metadata["speaker_reference"] = reference
            metadata["speaker_segments"] = segments
            print(f"Your voice: speaker {mine}; reference dominance: {reference['dominance']:.0%}.")
        if args.sound_others and any(w.profane and w.speaker is None for w in words):
            raise CensorError("Transcript has missing speaker labels. Supply --speaker-reference or label words as me/others/unknown.")
        if not args.dry_run and transcript:
            # All writes are preflighted before inference. No source JSON is rewritten.
            if transcript.exists():
                raise CensorError(f"Transcript appeared during processing: {transcript}")
            save_transcript(transcript, words, metadata, overwrite=False)
            print(f"Transcript: {transcript}")
        occurrences = [w for w in words if w.profane]
        ranges = (middle_ranges(words, info.duration, sound_seconds) if args.censor_style == "middle" else
                  censor_ranges(words, info.duration, args.padding_before, args.padding_after, args.merge_gap))
        owners = cue_owners(words, ranges) if args.sound_others else None
        if args.speaker_reference or args.sound_others:
            counts = {label: sum(w.speaker == label for w in occurrences) for label in ("me", "others", "unknown")}
            print(f"Profanity by speaker: {counts}")
            if counts["unknown"] or (owners and "unknown" in owners):
                print("Review unknown speaker labels in JSON. Ambiguous intervals use your original cue; nothing is left uncensored.")
        if args.censor_style == "middle":
            print("Censor style: word middle, single playback at original speed.")
            if sound_seconds is None:
                print("Interval durations are estimates without --sound; rendering also caps them to sound length.")
        print(f"Words detected: {len(words)}\nFound {len(occurrences)} profanity occurrences:\n")
        for word in occurrences:
            label = f" [{word.speaker}]" if word.speaker else ""
            print(f"[{timestamp(word.start)} - {timestamp(word.end)}] {word.word}{label}")
        print(f"\nTotal censored duration: {sum(r.duration for r in ranges):.2f} sec ({len(ranges)} merged intervals)")
        if not words:
            print("Warning: empty transcription. Check the audio stream/language or review manually.")
        if not ranges:
            print("No profanity detected.")
            return
        if args.dry_run:
            print("Dry run: no transcript, cache or output files written.")
            return
        if args.transcribe_only:
            print("Transcription saved; no media rendered.")
            return
        normalized = work / "sound.wav"
        print("Generating censor track…", flush=True)
        prepare_sound(args.sound.resolve(), normalized, sound_seconds)
        normalized_other = None
        if args.sound_others:
            normalized_other = work / "other-sound.wav"
            prepare_sound(args.sound_others.resolve(), normalized_other, sound_duration(args.sound_others.resolve()))
        if output:
            with Progress("Rendering video", info.duration) as bar:
                render_video(source, normalized, output.resolve(), info, ranges, args.mode, args.duck_db, work,
                             bar.update, other_sound=normalized_other, owners=owners)
            print(f"Output: {output.resolve()}", flush=True)
        if args.fcpxml:
            export_fcpxml(source, normalized, args.fcpxml.resolve(), info, ranges, args.mode, args.duck_db, work,
                          other_sound=normalized_other, owners=owners)
            print(f"FCPXML: {args.fcpxml.resolve()}", flush=True)
        print("Done.")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        execute(args)
        return 0
    except (CensorError, OSError, ValueError) as exc:
        if args.verbose:
            logging.exception("Processing failed")
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Temporary processing files removed.", file=sys.stderr)
        return 130
