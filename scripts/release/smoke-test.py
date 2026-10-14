#!/usr/bin/env python3
"""Exercise the shipped runtimes with no Homebrew/Python/project in PATH."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('app', type=Path)
parser.add_argument('--recognize', type=Path, help='Optional short recording for real offline inference')
parser.add_argument('--model-cache', type=Path)
args = parser.parse_args()
app = args.app.resolve()
engine = app/'Contents/Resources/Engine'
helpers = app/'Contents/Helpers'
core = app/'Contents/Resources/Runtime/Python/bin/python3.11'
gpu = app/'Contents/Resources/Runtime/PythonGPU/bin/python3.11'

with tempfile.TemporaryDirectory(prefix='bleep-release-smoke-') as temporary:
    folder = Path(temporary)
    environment = {k:v for k,v in os.environ.items() if k in ['TMPDIR', 'USER', 'LOGNAME', 'LANG']}
    environment.update(PATH=f'{helpers}:/usr/bin:/bin', HOME=str(folder),
        PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
        XDG_CACHE_HOME=str(folder/'cache'), NUMBA_CACHE_DIR=str(folder/'numba'),
        HF_HOME=str(folder/'models/huggingface'), BLEEP_MODEL_CACHE=str(folder/'models'))
    for python in [core, gpu]:
        script = """
import sys, ssl, importlib, importlib.metadata
for module in ['censor.desktop', 'faster_whisper', 'mlx_whisper', 'torch', 'onnxruntime', 'numpy', 'certifi']:
    importlib.import_module(module)
import mlx.core as mx
assert mx.metal.is_available()
assert (mx.array([1,2,3]) * 2).tolist() == [2,4,6]
from numba import njit
@njit
def jit_probe(x): return x + 1
assert jit_probe(4) == 5
if 'PythonGPU' in sys.executable:
    for module in ['gigaam', 'parakeet_mlx', 'mlx_qwen3_asr', 'torchaudio', 'soundfile']:
        importlib.import_module(module)
    import torch
    assert torch.backends.mps.is_available()
    assert (torch.tensor([1,2],device='mps')*2).tolist() == [2,4]
print('Runtime imports, Metal and JIT passed:', sys.executable, flush=True)
"""
        subprocess.run([str(python), '-c', script], cwd=engine, env=environment, check=True)

    def ffmpeg(*arguments):
        return subprocess.check_output([str(helpers/'ffmpeg'), '-v', 'error', '-nostdin', *map(str,arguments)], env=environment)

    source = folder/'source with spaces.mov'
    ffmpeg('-f','lavfi','-i','testsrc2=size=160x120:rate=10:duration=2',
           '-f','lavfi','-i','sine=frequency=440:duration=2', '-c:v','mpeg4','-c:a','aac',source)
    transcript = folder/'review.json'
    transcript.write_text(json.dumps({'words':[{'word':'test','start':0.5,'end':1.0,'profane':True}]}))
    def worker(request, python=core):
        request_path = folder/'request.json'
        request_path.write_text(json.dumps(request))
        completed = subprocess.run([str(python), '-u','-m','censor.desktop',str(request_path)],
            cwd=engine, env=environment, capture_output=True,text=True)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        events = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith('{')]
        result = next((e for e in reversed(events) if e.get('event')=='result'),None)
        assert result, completed.stdout
        return result

    document = worker(dict(operation='analyze',source=str(source),transcript=str(transcript)))
    assert document['words'][0]['mute_start'] == 0.6
    assert abs(document['words'][0]['mute_end'] - 0.9) < 0.000001
    output = folder/'censored.mov'
    worker(dict(operation='export',document=document,output=str(output),format='video',sound='beep'))
    before = ffmpeg('-i',source,'-map','0:v:0','-c','copy','-f','hash','-hash','sha256','-')
    after = ffmpeg('-i',output,'-map','0:v:0','-c','copy','-f','hash','-hash','sha256','-')
    assert before == after, 'Export modified video packets'
    worker(dict(operation='export',document=document,output=str(folder/'censored.wav'),format='audio',sound='silence'))
    print('Imported transcript, approved mute timing, video stream copy and WAV export passed', flush=True)

    # Exercise the actual app entry point before any GPU model has been downloaded.
    # Reviewed-transcript imports bypass the model preparation/progress path.
    missing_request = folder/'missing-model-request.json'
    missing_request.write_text(json.dumps(dict(operation='analyze', source=str(source),
        backend='gigaam-mps', model='gigaam-v3', offline=True, cache_dir=str(folder/'recognition-cache'))))
    missing = subprocess.run([str(gpu), '-u', '-m', 'censor.desktop', str(missing_request)],
        cwd=engine, env=environment, capture_output=True, text=True, timeout=30)
    events = [json.loads(line) for line in missing.stdout.splitlines()]
    assert missing.returncode == 1, (missing.stdout, missing.stderr)
    assert any(event.get('stage') == 'Preparing speech model' for event in events), events
    assert events[-1].get('code') == 'model_download_required', events
    print('Cold-start GPU worker progress and download consent passed', flush=True)
    if args.recognize:
        if not args.model_cache: parser.error('--recognize requires --model-cache')
        environment['HF_HOME'] = str(args.model_cache.resolve()/'huggingface')
        environment['BLEEP_MODEL_CACHE'] = str(args.model_cache.resolve())
        for backend, model, python in [('faster-whisper','large-v3-turbo',core),('mlx','large-v3-turbo',core),
                                       ('gigaam-mps','gigaam-v3',gpu),('whisperkit','large-v3-turbo',core)]:
            document = worker(dict(operation='analyze',source=str(args.recognize.resolve()),backend=backend,model=model,
                language='ru',offline=True,cache_dir=str(folder/backend),
                whisperkit_executable=str(helpers/'BleepWhisperKit'),
                whisperkit_model_folder=str(args.model_cache.resolve()/'whisperkit/model')),python)
            assert len(document['words']) > 0, f'Empty recognition result from {backend}'
            print(f'Real offline inference passed: {backend}, {len(document["words"])} words', flush=True)
