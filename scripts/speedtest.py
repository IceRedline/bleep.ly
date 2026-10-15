#!/usr/bin/env python3
"""Reproducible Turbo audio benchmark through the application's desktop worker."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / "benchmarks/turbo-en.json"
WORK = ROOT / ".cache/speedtest"
HELPER = ROOT / ".cache/whisperkit-build/release/BleepWhisperKit"
REFERENCE_AUDIO = ROOT / "benchmarks/fixtures/turbo-en.flac"
PACKAGES = ("faster-whisper", "ctranslate2", "mlx-whisper", "mlx", "mlx-metal", "onnxruntime", "numpy", "huggingface-hub", "av")
MODES = {"cpu": "CPU · faster-whisper int8", "gpu": "GPU · MLX float16", "ane": "CPU + Neural Engine · WhisperKit"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.PIPE).strip()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_audio(audio, manifest):
    """Compare decoded PCM, independent of FLAC encoder version / metadata."""
    info = json.loads(capture("ffprobe", "-v", "error", "-show_streams", "-of", "json", str(audio)))
    streams = info["streams"]
    if (len(streams) != 1 or streams[0]["codec_type"] != "audio"
            or streams[0]["codec_name"] != "flac"
            or int(streams[0]["sample_rate"]) != manifest["sample_rate"]
            or streams[0]["channels"] != manifest["channels"]):
        raise ValueError("Reference must be audio-only FLAC, mono, 16000 Hz; use make speedtest-audio.")
    decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(audio), "-map", "0:a:0",
                              "-f", "s16le", "-c:a", "pcm_s16le", "-"], capture_output=True, check=True).stdout
    if (hashlib.sha256(decoded).hexdigest() != manifest["audio_pcm_sha256"]
            or len(decoded) != manifest["samples"] * 2):
        raise ValueError("Reference audio mismatch. Use the exact full reference, without cuts or normalization.")
    return sha256(audio)


def prepare_audio(video, output, manifest):
    if sha256(video) != manifest["video_sha256"]:
        raise ValueError("Reference video mismatch; the YouTube version has a different duration. See benchmarks/README.md.")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(video), "-map", "0:a:0", "-vn",
                    "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", "-map_metadata", "-1", "-c:a", "flac", str(output)], check=True)
    validate_audio(output, manifest)


def model_fingerprints(folder):
    return {str(p.relative_to(folder)): sha256(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and ".cache" not in p.relative_to(folder).parts}


def prepare(manifest, wk_model):
    from huggingface_hub import snapshot_download
    from censor.whisperkit_backend import prepare_assets, MODEL_REVISION, TOKENIZER_REVISION
    for mode, spec in manifest["models"].items():
        folder = WORK / "models" / mode
        print(f"Downloading / verifying {mode} weights (outside measurement)…", flush=True)
        snapshot_download(spec["repo"], revision=spec["revision"], local_dir=folder,
                          allow_patterns=spec["patterns"], max_workers=2)
        save(WORK / f"{mode}-assets.json", {"revision": spec["revision"], "files": model_fingerprints(folder)})
    prepare_assets(wk_model, offline=False)
    save(WORK / "ane-assets.json", {"revision": MODEL_REVISION, "tokenizer_revision": TOKENIZER_REVISION,
                                    "files": model_fingerprints(wk_model)})


def verify_assets(mode, manifest, wk_model):
    marker = json.loads((WORK / f"{mode}-assets.json").read_text())
    if mode == "ane":
        from censor.whisperkit_backend import prepare_assets, MODEL_REVISION, TOKENIZER_REVISION
        prepare_assets(wk_model, offline=True)
        if marker.get("tokenizer_revision") != TOKENIZER_REVISION:
            raise ValueError("WhisperKit tokenizer revision changed; run prepare again.")
        revision, folder = MODEL_REVISION, wk_model
    else:
        revision, folder = manifest["models"][mode]["revision"], WORK / "models" / mode
    if marker["revision"] != revision or not marker["files"] or marker["files"] != model_fingerprints(folder):
        raise ValueError(f"{mode} weights changed or are incomplete; run prepare again.")
    return marker


def host_info():
    def sysctl(key):
        return capture("sysctl", "-n", key)
    displays = json.loads(capture("system_profiler", "SPDisplaysDataType", "-json"))["SPDisplaysDataType"]
    # Whitelist hardware fields: never publish host names, usernames or serials.
    return {"chip": sysctl("machdep.cpu.brand_string"), "memory_bytes": int(sysctl("hw.memsize")),
            "physical_cpu_cores": int(sysctl("hw.physicalcpu")), "logical_cpu_cores": int(sysctl("hw.logicalcpu")),
            "gpu_cores": [item.get("sppci_cores") for item in displays],
            "macos": platform.mac_ver()[0], "os_build": capture("sw_vers", "-buildVersion"),
            "architecture": platform.machine(), "python": platform.python_version(),
            "power_source": capture("pmset", "-g", "batt").splitlines()[0],
            "power_settings": capture("pmset", "-g", "custom"),
            "thermal_status": capture("pmset", "-g", "therm")}


def source_info():
    """GitHub ZIPs have no .git; fingerprint executable source in either case."""
    paths = set((ROOT / "censor").rglob("*.py"))
    paths.update(ROOT.glob("profanity*.txt"))
    paths.update(ROOT.glob("requirements*.txt"))
    paths.update((ROOT / "experiments/WhisperKitRunner").glob("Package.*"))
    paths.update((ROOT / "experiments/WhisperKitRunner/Sources").rglob("*.swift"))
    paths.update([ROOT / "scripts/speedtest.py", ROOT / "scripts/release/requirements-mlx-macos15.lock"])
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file()):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + sha256(path).encode() + b"\0")
    result = dict(source_sha256=digest.hexdigest(), git_commit=None, git_dirty=None)
    try:
        # An archive unpacked inside some other repository must not inherit its identity.
        if Path(capture("git", "-C", str(ROOT), "rev-parse", "--show-toplevel")).resolve() == ROOT.resolve():
            result.update(git_commit=capture("git", "-C", str(ROOT), "rev-parse", "HEAD"),
                          git_dirty=bool(capture("git", "-C", str(ROOT), "status", "--porcelain")))
    except (OSError, subprocess.CalledProcessError):
        pass
    return result


def stop_process(process):
    # The worker spawns FFmpeg / WhisperKit; kill the whole fresh session on
    # timeout or cancellation so the next timing cannot overlap an orphan.
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        process.wait()


def run_worker(request, directory, timeout):
    directory.mkdir(parents=True)
    save(directory / "request.json", request)
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                   "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "PYTHONUNBUFFERED": "1"}
    started = time.perf_counter()
    with (directory / "events.jsonl").open("w") as events, (directory / "stderr.log").open("w") as errors:
        process = subprocess.Popen([sys.executable, "-m", "censor.desktop", str(directory / "request.json")],
                                   cwd=ROOT, env=environment, stdout=events, stderr=errors, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process(process)
            return {"status": "error", "code": "timeout", "wall_seconds": time.perf_counter() - started}
        except BaseException:
            stop_process(process)
            raise
    wall = time.perf_counter() - started
    records = []
    for line in (directory / "events.jsonl").read_text().splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    result = next((r for r in reversed(records) if r.get("event") == "result"), None)
    if code or not result:
        failure = next((r for r in reversed(records) if r.get("event") == "error"), {})
        # Detailed errors can contain local paths; keep them in private logs.
        return {"status": "error", "code": failure.get("code", f"worker_exit_{code}"), "wall_seconds": wall}
    if result["cache_hit"]:
        return {"status": "error", "code": "unexpected_cache_hit", "wall_seconds": wall}
    if not result["words"]:
        return {"status": "error", "code": "empty_transcript", "wall_seconds": wall}
    row = {"status": "ok", "wall_seconds": wall, "analysis_seconds": result["analysis_seconds"],
           "duration_seconds": result["duration"], "word_count": len(result["words"])}
    snapshots = list((directory / "history/runs").glob("*.json"))
    if len(snapshots) != 1:
        return {"status": "error", "code": "missing_run_metrics", "wall_seconds": wall}
    history = json.loads(snapshots[0].read_text())
    row["recognition_seconds"] = history["summary"]["recognition_seconds"]
    row["native_metrics"] = history["metadata"].get("native_metrics", {})
    return row


def summarize(runs, repeats, duration):
    rows = {}
    for mode in MODES:
        measured = [r for r in runs if r["mode"] == mode and r["iteration"] > 0]
        initial = next((r for r in runs if r["mode"] == mode and r["iteration"] == 0), None)
        row = {"label": MODES[mode], "status": "incomplete", "first_wall_seconds": initial.get("wall_seconds") if initial else None}
        all_mode = [r for r in runs if r["mode"] == mode]
        if any(r["status"] != "ok" for r in all_mode):
            row["status"] = "error"
        elif len(measured) == repeats and initial is not None:
            times = [r["wall_seconds"] for r in measured]
            row.update(status="ok", median_seconds=statistics.median(times), min_seconds=min(times), max_seconds=max(times),
                       realtime_factor=statistics.median(times) / duration)
        rows[mode] = row
    return rows


def markdown(report):
    lines = ["# Turbo speed test", "", f"{report['host']['chip']} · {report['host']['memory_bytes'] / 2**30:g} GiB · macOS {report['host']['macos']}", "",
             "| Pipeline | First observed (s) | Repeated median (s) | Range (s) | RTF |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in report["summary"].values():
        first = f"{row['first_wall_seconds']:.2f}" if row['first_wall_seconds'] is not None else "—"
        values = (f"{row['median_seconds']:.2f} | {row['min_seconds']:.2f}–{row['max_seconds']:.2f} | {row['realtime_factor']:.3f}"
                  if row["status"] == "ok" else f"{row['status']} | — | —")
        lines.append(f"| {row['label']} | {first} | {values} |")
    lines += ["", "Each measurement launches a fresh worker, bypasses transcript caches and forbids model downloads.",
              "The first observed run is excluded from the median; OS / Core ML caches may already be warm.", ""]
    return "\n".join(lines)


def run(args, manifest):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Run natively on an Apple Silicon Mac, outside a sandbox / Rosetta.")
    audio = args.audio.resolve()
    audio_hash = validate_audio(audio, manifest)
    assets = {mode: verify_assets(mode, manifest, args.whisperkit_model) for mode in MODES}
    if not HELPER.is_file():
        raise ValueError("Build the WhisperKit helper with make speedtest-setup first.")
    versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    wheel_tags = {name: [line.removeprefix("Tag: ") for line in
                        (importlib.metadata.distribution(name).read_text("WHEEL") or "").splitlines()
                        if line.startswith("Tag: ")] for name in PACKAGES}
    output = args.output.resolve() if args.output else WORK / ("run-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": 1, "fixture": manifest, "audio_file_sha256": audio_hash,
              "timestamp_utc": datetime.now(timezone.utc).isoformat(), "host": host_info(), "packages": versions,
              "wheel_tags": wheel_tags,
              "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
              **source_info(),
              "ffmpeg": capture("ffmpeg", "-version").splitlines()[0],
              "helper_sha256": sha256(HELPER), "model_assets": assets,
              "repeats": args.repeats, "cooldown_seconds": args.cooldown, "runs": []}
    print(f"Local artifacts: {output}", flush=True)
    def checkpoint():
        report["summary"] = summarize(report["runs"], args.repeats, manifest["duration_seconds"])
        save(output / "report.json", report)
        (output / "report.md").write_text(markdown(report))
    checkpoint()
    failed = False
    try:
        # Round-robin so all modes get first/repeated runs throughout the session.
        # Fresh subprocesses preserve application launch semantics and free memory.
        for iteration in range(args.repeats + 1):
            for mode in MODES:
                if any(r["mode"] == mode and r["status"] != "ok" for r in report["runs"]):
                    continue
                directory = output / f"{mode}-{iteration}"
                request = {"operation": "analyze", "source": str(audio), "audio_stream": 0, "language": "en",
                           "backend": {"cpu": "faster-whisper", "gpu": "mlx", "ane": "whisperkit"}[mode],
                           "model": str(WORK / "models" / mode) if mode != "ane" else "large-v3-turbo",
                           "offline": True, "bypass_cache": True, "cache_dir": str(directory / "cache"),
                           "history_dir": str(directory / "history"), "whisperkit_executable": str(HELPER),
                           "whisperkit_model_folder": str(args.whisperkit_model.resolve()),
                           "whisperkit_compute_units": "cpuAndNeuralEngine"}
                print(f"{mode}: {'first observed' if iteration == 0 else f'repeat {iteration}/{args.repeats}'}", flush=True)
                row = run_worker(request, directory, args.timeout)
                if row["status"] == "ok" and abs(row["duration_seconds"] - manifest["duration_seconds"]) > .1:
                    row.update(status="error", code="duration_mismatch")
                if mode == "ane" and row["status"] == "ok" and row["native_metrics"].get("compute_units") != "cpuAndNeuralEngine":
                    row.update(status="error", code="compute_policy_not_confirmed")
                row.update(mode=mode, iteration=iteration)
                report["runs"].append(row)
                failed |= row["status"] != "ok"
                checkpoint()
                print(f"  {row['status']}: {row['wall_seconds']:.2f} s", flush=True)
                time.sleep(args.cooldown)
    finally:
        checkpoint()
    print(output / "report.md", flush=True)
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audio = sub.add_parser("audio", help="Create the canonical FLAC from the full reference video")
    audio.add_argument("--video", type=Path, required=True)
    audio.add_argument("--output", type=Path, default=WORK / "turbo-en.flac")
    prep = sub.add_parser("prepare", help="Explicitly download and fingerprint pinned weights")
    verify = sub.add_parser("verify-audio", help="Validate the bundled reference before downloading models")
    verify.add_argument("--audio", type=Path, default=REFERENCE_AUDIO)
    bench = sub.add_parser("run", help="Run all three pipelines sequentially, with network downloads disabled")
    for target in [prep, bench]:
        target.add_argument("--whisperkit-model", type=Path, default=ROOT / ".cache/whisperkit/model")
    bench.add_argument("--audio", type=Path, default=REFERENCE_AUDIO)
    bench.add_argument("--output", type=Path)
    bench.add_argument("--repeats", type=int, default=3, help="Measured runs per pipeline after one first-observed run")
    bench.add_argument("--timeout", type=float, default=3600, help="Maximum seconds per worker")
    bench.add_argument("--cooldown", type=float, default=15, help="Idle seconds between workers")
    args = parser.parse_args(argv)
    if args.command == "run" and (args.repeats < 1 or args.timeout <= 0 or args.cooldown < 0):
        parser.error("Require repeats >= 1, timeout > 0, cooldown >= 0")
    manifest = json.loads(MANIFEST.read_text())
    os.environ.update(HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_XET="1", DO_NOT_TRACK="1")
    try:
        if args.command == "audio":
            prepare_audio(args.video, args.output, manifest)
        elif args.command == "prepare":
            prepare(manifest, args.whisperkit_model)
        elif args.command == "verify-audio":
            validate_audio(args.audio, manifest)
            print("Reference audio verified.")
        else:
            return run(args, manifest)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Speed test failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
