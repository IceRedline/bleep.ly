"""Sequential, uncached full-file GPU runs with resumable local artifacts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from censor.experimental_gpu import MODELS, prepare
from censor.recognition_history import write_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=[*MODELS, "large-v3-turbo"],
                        choices=[*MODELS, "large-v3", "large-v3-turbo"])
    parser.add_argument("--prepare", action="store_true", help="Download missing experimental weights before measurement")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "HF_HOME": str(ROOT / ".cache/huggingface"),
                   "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
                   "PYTORCH_ENABLE_MPS_FALLBACK": "0"}
    os.environ.update(environment)
    if args.prepare:
        for model in args.models:
            if model in MODELS:
                print("Preparing", model, flush=True)
                prepare(model, offline=False)
    environment["HF_HUB_OFFLINE"] = "1"
    rows = []
    failed = False
    for model in args.models:
        prefix = output / model
        result_path = prefix.with_suffix(".result.json")
        if result_path.exists():
            previous = json.loads(result_path.read_text())
            if previous["source"] != str(args.source.resolve()):
                raise ValueError("Output belongs to another source; choose a new directory.")
            rows.append(previous)
            failed |= previous["status"] != "ok"
            continue
        backend = MODELS[model][0] if model in MODELS else "mlx"
        python = ROOT / (".cache/asr-env/bin/python" if model in MODELS else ".venv/bin/python")
        request = dict(operation="analyze", source=str(args.source.resolve()), backend=backend,
                       model=model, offline=True, bypass_cache=True,
                       cache_dir=str(output / "cache"),
                       history_dir=str(ROOT / "тесты bleep.ly/recognition-history"))
        request_path = prefix.with_suffix(".request.json")
        request_path.write_text(json.dumps(request))
        print("Recognizing", model, flush=True)
        started = time.perf_counter()
        with prefix.with_suffix(".events.jsonl").open("w") as events, prefix.with_suffix(".stderr.log").open("w") as errors:
            process = subprocess.run([str(python), "-u", "-m", "censor.desktop", str(request_path)],
                                     cwd=ROOT, env=environment, stdout=events, stderr=errors)
        elapsed = time.perf_counter() - started
        records = [json.loads(line) for line in prefix.with_suffix(".events.jsonl").read_text().splitlines()]
        result = next((item for item in reversed(records) if item.get("event") == "result"), None)
        row = dict(model=model, backend=backend, source=str(args.source.resolve()), wall_seconds=elapsed,
                   status="ok" if process.returncode == 0 and result else "error")
        if row["status"] == "ok":
            if result["cache_hit"]:
                raise RuntimeError("Benchmark must never reuse transcript cache")
            row.update(total_words=len(result["words"]), explicit_words=sum(w["profane"] for w in result["words"]),
                       analysis_seconds=result["analysis_seconds"], duration_seconds=result["duration"])
            prefix.with_suffix(".review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            row["error"] = next((item["message"] for item in records if item.get("event") == "error"), "See stderr log")
            failed = True
        result_path.write_text(json.dumps(row, ensure_ascii=False, indent=2))
        rows.append(row)
        write_csv(output / "summary.csv", ["model", "backend", "source", "status", "total_words", "explicit_words",
                                           "duration_seconds", "analysis_seconds", "wall_seconds", "error"], rows)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
