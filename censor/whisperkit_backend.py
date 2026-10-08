"""Opt-in subprocess backend. The regular app never builds or selects this SDK."""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .models import WordTimestamp
from .transcription import file_hash
from .utils import CensorError, write_json

SDK_VERSION = '1.1.0'
MODEL = 'openai_whisper-large-v3-v20240930_turbo'
MODEL_REVISION = '0f63a7800b00dd0226abd051b906c246e1907482'
TOKENIZER_REVISION = '41f01f3fe87f28c78e2fbf8b568835947dd65ed9'
COMPONENTS = ('AudioEncoder.mlmodelc', 'MelSpectrogram.mlmodelc', 'TextDecoder.mlmodelc')


def prepare_assets(folder: Path, offline=True):
    identity = dict(model=MODEL, revision=MODEL_REVISION, tokenizer_revision=TOKENIZER_REVISION)
    required = [folder / c / name for c in COMPONENTS
                for name in ('weights/weight.bin', 'coremldata.bin', 'model.mil')]
    required += [folder / 'tokenizer.json', folder / 'tokenizer_config.json', folder / 'bleep-model.json']
    if all(p.is_file() and p.stat().st_size > 0 for p in required):
        try:
            if json.loads((folder / 'bleep-model.json').read_text()) == identity:
                return
        except (ValueError, OSError):
            pass
    if offline:
        raise CensorError('WhisperKit model is not installed. Enable Allow first-time model download in Settings '
                          'or run scripts/prepare-whisperkit.py. It needs about 1.7 GB of disk space.')
    from huggingface_hub import snapshot_download, hf_hub_download
    import shutil
    folder.mkdir(parents=True, exist_ok=True)
    # An interrupted repair must not leave a valid marker on partial assets.
    (folder / 'bleep-model.json').unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='bleep-wk-download-', dir=folder.parent) as work:
        snapshot_download('argmaxinc/whisperkit-coreml', revision=MODEL_REVISION,
                          allow_patterns=[f'{MODEL}/{c}/**' for c in COMPONENTS], local_dir=work)
        for component in COMPONENTS:
            shutil.copytree(Path(work) / MODEL / component, folder / component, dirs_exist_ok=True)
        for name in ('tokenizer.json', 'tokenizer_config.json'):
            path = hf_hub_download('openai/whisper-large-v3-turbo', name, revision=TOKENIZER_REVISION)
            shutil.copyfile(path, folder / name)
    write_json(folder / 'bleep-model.json', identity)


def cache_identity(source, model_folder, executable, audio_index, progress=None):
    metadata = dict(schema=1, source_sha256=file_hash(source, progress), backend='whisperkit',
                    backend_version=SDK_VERSION, helper_sha256=file_hash(executable), model=MODEL,
                    model_revision=MODEL_REVISION, tokenizer_revision=TOKENIZER_REVISION,
                    local_model_files={str(p.relative_to(model_folder)): [p.stat().st_size, p.stat().st_mtime_ns]
                                       for p in sorted(model_folder.rglob('*')) if p.is_file()},
                    language='ru', audio_index=audio_index, word_timestamps=True, compute='CoreML defaults',
                    temperature=0, temperature_fallback_count=5, concurrent_workers=1,
                    max_initial_timestamp=1, suppress_blank=True,
                    chunking='vad/incremental', initial_prompt=None)
    return hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest(), metadata


class WhisperKitBackend:
    def __init__(self, executable: Path, model_folder: Path, stage=None):
        self.executable = executable
        self.model_folder = model_folder
        self.stage = stage or (lambda _: None)
        self.metrics = {}
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise CensorError('WhisperKit helper is missing. Build with scripts/build-macos.sh --whisperkit.')

    def transcribe(self, audio, progress):
        with tempfile.TemporaryDirectory(prefix='bleep-whisperkit-') as folder:
            work = Path(folder)
            output = work / 'words.json'
            request = work / 'request.json'
            write_json(request, dict(audio=str(audio), modelFolder=str(self.model_folder), output=str(output)))
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen([str(self.executable), str(request)], stdout=subprocess.PIPE,
                                           stderr=errors, text=True)
                failure = None
                try:
                    for line in process.stdout:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get('event') == 'progress':
                            progress(event['seconds'])
                        elif event.get('event') == 'stage':
                            self.stage(event['stage'])
                        elif event.get('event') == 'error':
                            failure = event.get('message')
                    code = process.wait()
                except BaseException:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                    raise
                finally:
                    process.stdout.close()
                if code or not output.exists():
                    errors.seek(0, 2); errors.seek(max(0, errors.tell() - 4000))
                    detail = failure or errors.read().decode('utf8', errors='replace')
                    raise CensorError(f'WhisperKit failed ({code}): {detail}. No fallback engine was used.')
            data = json.loads(output.read_text())
            self.metrics = {k: v for k, v in data.items() if k != 'words'}
            return [WordTimestamp(w['word'], w['start'], w['end']) for w in data['words']]
