"""Repeatable, uncached desktop-engine comparison against a local reviewed transcript."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time


def normalized(word):
    return re.sub(r'[^\w]', '', word.casefold().replace('ё', 'е'))


def compare(reference, candidate, tolerance=0.5):
    """Lexical agreement is not gold WER unless the entire reference was reviewed.

    Detection uses an order-preserving one-to-one match of flagged occurrences
    whose centers differ by <= tolerance; spelling variants are allowed. Timing
    errors apply only to those matched occurrences. No unmatched word disappears
    from the recall denominator.
    """
    ref, hyp = reference['words'], candidate['words']
    a, b = [normalized(w['word']) for w in ref], [normalized(w['word']) for w in hyp]
    row = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1] + 1, row[j] + 1, row[j-1] + (word != other)))
        row = current
    expected = sorted([w for w in ref if w['profane']], key=lambda w: w['start'])
    found = sorted([w for w in hyp if w['profane']], key=lambda w: w['start'])
    # DP maximizes matched occurrences, then minimizes center error.
    n, m = len(expected), len(found)
    actions = [bytearray(m + 1) for _ in range(n + 1)]
    scores = [(0, 0.0)] * (m + 1)
    for i, word in enumerate(expected, 1):
        current = [(0, 0.0)]
        for j, other in enumerate(found, 1):
            choices = [(scores[j], 1), (current[j-1], 2)]
            delta = abs((word['start'] + word['end'] - other['start'] - other['end']) / 2)
            if delta <= tolerance:
                previous = scores[j-1]
                choices.append(((previous[0] + 1, previous[1] - delta), 3))
            score, action = max(choices, key=lambda item: item[0])
            current.append(score)
            actions[i][j] = action
        scores = current
    pairs = []
    i, j = n, m
    while i and j:
        action = actions[i][j]
        if action == 3:
            pairs.append((i-1, j-1)); i -= 1; j -= 1
        elif action == 1:
            i -= 1
        else:
            j -= 1
    matched_ref, matched_hyp = {i for i, _ in pairs}, {j for _, j in pairs}
    edges = [abs(expected[i][edge] - found[j][edge]) for i, j in pairs for edge in ('start', 'end')]
    return dict(reference_words=len(a), candidate_words=len(b),
                lexical_disagreement_rate=row[-1] / len(a) if a else None,
                expected_explicit=n, found_explicit=m, matched_explicit=len(pairs),
                recall=len(pairs) / n if n else None, precision=len(pairs) / m if m else None,
                mean_edge_error_seconds=statistics.mean(edges) if edges else None,
                max_edge_error_seconds=max(edges) if edges else None,
                occurrence_center_tolerance_seconds=tolerance,
                missed=[w for i, w in enumerate(expected) if i not in matched_ref],
                unmatched_findings=[w for j, w in enumerate(found) if j not in matched_hyp])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--engines', nargs='+', choices=['faster-whisper', 'mlx', 'whisperkit'],
                        default=['faster-whisper', 'mlx', 'whisperkit'])
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--audio-stream', type=int)
    parser.add_argument('--helper', type=Path, default=Path('.cache/whisperkit-build/release/BleepWhisperKit'))
    parser.add_argument('--model-folder', type=Path, default=Path('.cache/whisperkit/model'))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    source = args.source.resolve()
    reference = json.loads(args.reference.read_text())
    with source.open('rb') as source_file:
        digest = hashlib.file_digest(source_file, 'sha256').hexdigest()
    expected_digest = reference.get('metadata', {}).get('source_sha256')
    if expected_digest and digest != expected_digest:
        parser.error('Reference belongs to a different source (SHA-256 mismatch).')
    # New output directory prevents accidental replacement of previous measurements.
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(source=str(source), source_sha256=digest, reference=str(args.reference.resolve()),
                  platform=platform.platform(), machine=platform.machine(),
                  method='Sequential fresh processes, offline models, transcript cache bypassed. '
                         'Includes extraction and model load; repeats reuse OS/Core ML caches. '
                         'Lexical disagreement is not gold WER; reference text may be only partly corrected. '
                         'Occurrence recall allows spelling variants within 0.5s of reviewed word center.',
                  runs=[])
    for repeat in range(args.repeats):
        for backend in args.engines:
            prefix = args.output / f'{backend}-{repeat + 1}'
            request = dict(operation='analyze', source=str(source), cache_dir=str(args.output / 'cache'),
                           backend=backend, offline=True, bypass_cache=True,
                           audio_stream=args.audio_stream,
                           whisperkit_executable=str(args.helper.resolve()),
                           whisperkit_model_folder=str(args.model_folder.resolve()))
            request_path = prefix.with_suffix('.request.json')
            request_path.write_text(json.dumps(request))
            print(f'{backend}, run {repeat + 1}: recognizing…', flush=True)
            started = time.monotonic()
            with prefix.with_suffix('.events.jsonl').open('w') as events, prefix.with_suffix('.stderr.log').open('w') as errors:
                process = subprocess.run([sys.executable, '-m', 'censor.desktop', str(request_path)],
                                         stdout=events, stderr=errors)
            wall_seconds = time.monotonic() - started
            lines = [json.loads(line) for line in prefix.with_suffix('.events.jsonl').read_text().splitlines()]
            results = [event for event in lines if event.get('event') == 'result']
            entry = dict(engine=backend, repeat=repeat + 1, wall_seconds=wall_seconds,
                         exit_code=process.returncode)
            if process.returncode == 0 and results:
                document = results[-1]
                if document['cache_hit']:
                    raise RuntimeError('Benchmark reused transcript cache!')
                prefix.with_suffix('.review.json').write_text(json.dumps(document, ensure_ascii=False, indent=2))
                entry.update(analysis_seconds=document['analysis_seconds'], duration=document['duration'],
                             quality=compare(reference, document))
            else:
                entry['error'] = next((e.get('message') for e in lines if e.get('event') == 'error'), 'See stderr log')
            report['runs'].append(entry)
            (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    if any(run['exit_code'] or 'error' in run for run in report['runs']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
