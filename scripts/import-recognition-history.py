"""Import local app caches without downloading models or running recognition."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from censor.recognition_history import import_cache
from censor.transcription import file_hash
from censor.ffmpeg import media_info, probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="Attach source name/duration only to caches with matching SHA-256")
    parser.add_argument("cache_dirs", type=Path, nargs="+")
    args = parser.parse_args()
    source_hash = file_hash(args.source) if args.source else None
    audio_indices = [stream["index"] for stream in probe(args.source)["streams"]
                     if stream["codec_type"] == "audio"] if args.source else []
    for directory in args.cache_dirs:
        for path in sorted(directory.glob("*.json")):
            metadata = json.loads(path.read_text())["metadata"]
            matches = source_hash is not None and metadata.get("source_sha256") == source_hash
            # Cache identity uses the absolute stream index; media_info takes an audio ordinal.
            info = media_info(args.source, audio_indices.index(metadata["audio_index"]), allow_audio=True) if matches else None
            import_cache(args.output, path, source=args.source.resolve() if matches else None,
                         duration=info.duration if info else None)
    print(args.output.resolve() / "runs.csv")


if __name__ == "__main__":
    main()
