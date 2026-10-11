"""Limits for disposable desktop data, never recordings, exports, or models."""
import contextlib
import fcntl
from pathlib import Path
import re
import shutil
import time

from .utils import CensorError

MEDIA_LIMIT = 4 * 1024**3
RECOGNITION_LIMIT = 256 * 1024**2
MAX_AGE = 30 * 86400
HEADROOM = 1024**3
HASH = re.compile(r'[0-9a-f]{64}')
UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')


def tree_size(path):
    path = Path(path)
    if path.is_symlink() or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(tree_size(p) for p in path.iterdir())


def reserve_preview(session, protected, needed, limit=MEDIA_LIMIT):
    """Called with the session worker lock held. Evict only app-owned audio."""
    session = Path(session).resolve()
    protected = {Path(p).resolve() for p in protected}
    candidates = []
    for folder in session.iterdir():
        if folder.is_symlink() or not folder.is_dir():
            continue
        if UUID.fullmatch(folder.name):
            candidates.append(folder)
        elif folder.name == 'audio':
            candidates.extend(p for p in folder.iterdir()
                              if p.is_dir() and not p.is_symlink() and HASH.fullmatch(p.name))
    used = tree_size(session)
    variants = sum(bool(UUID.fullmatch(p.name)) for p in candidates)
    for folder in sorted(candidates, key=lambda p: p.stat().st_mtime):
        if used + needed <= limit and variants <= 8:
            break
        if folder in protected:
            continue
        size = tree_size(folder)
        shutil.rmtree(folder)
        used -= size
        if UUID.fullmatch(folder.name):
            variants -= 1
    if used + needed > limit:
        raise CensorError('This preview would exceed the 4 GB temporary audio limit. '
                          'Original playback and export remain available. Open a shorter recording for censored preview.')
    if shutil.disk_usage(session).free < needed + HEADROOM:
        raise CensorError('Not enough free disk space for preview audio. Free some space and try again. '
                          'Original playback and export remain available.')


@contextlib.contextmanager
def preview_worker(request):
    if not request.get('managed_cache'):
        yield
        return
    cache = Path(request['preview_cache'])
    cache.mkdir(parents=True, exist_ok=True)
    # Serialize cancellation/replacement workers before evicting another track.
    with lease(cache.parent), (cache / '.worker-lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


@contextlib.contextmanager
def lease(folder):
    """Keep scratch files protected if the GUI exits while a worker is still alive."""
    marker = Path(folder) / '.owner-lock'
    if not marker.is_file() or marker.is_symlink():
        yield
        return
    with marker.open('r') as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        yield


def prune_recognition(cache, history, limit=RECOGNITION_LIMIT, now=None):
    """Trim transcript files and history pairs together; keep the index coherent.

    Uses the same history lock as record_run. Never recurse into model caches or
    trust paths from a snapshot when deleting files.
    """
    from .recognition_history import FIELDS, write_csv, csv_text
    import json
    cache, history = Path(cache), Path(history)
    if cache.is_symlink() or history.is_symlink():
        return
    history.mkdir(parents=True, exist_ok=True)
    now = time.time() if now is None else now
    with (history / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = []
        if cache.is_dir():
            for path in cache.glob('*.json'):
                if not path.is_symlink() and HASH.fullmatch(path.stem):
                    entries.append(([path], path.stat().st_mtime, None))
        runs = history / 'runs'
        if runs.is_dir() and not runs.is_symlink():
            for path in runs.glob('*.json'):
                if path.is_symlink() or not (UUID.fullmatch(path.stem) or
                        path.stem.startswith('import-') and HASH.fullmatch(path.stem[7:])):
                    continue
                try:
                    summary = json.loads(path.read_text())['summary']
                    if not isinstance(summary, dict):
                        summary = None
                except (OSError, ValueError, KeyError, TypeError):
                    summary = None
                pair = path.with_suffix('.csv')
                files = [path] + ([pair] if pair.is_file() and not pair.is_symlink() else [])
                entries.append((files, path.stat().st_mtime, summary))
            for pair in runs.glob('*.csv'):
                if pair.is_symlink() or not (UUID.fullmatch(pair.stem) or
                        pair.stem.startswith('import-') and HASH.fullmatch(pair.stem[7:])):
                    continue
                snapshot = pair.with_suffix('.json')
                if not snapshot.exists() and not snapshot.is_symlink():
                    entries.append(([pair], pair.stat().st_mtime, None))
        # Incomplete atomic writes left by a killed worker are disposable too.
        for folder in (cache, history, runs):
            if folder.is_symlink() or not folder.is_dir():
                continue
            for path in folder.iterdir():
                if path.is_symlink() or not path.is_file() or not path.name.startswith('.'):
                    continue
                if (re.fullmatch(r'\.[0-9a-f]{64}\.json\.[a-z0-9_]{8}', path.name) or
                        re.fullmatch(r'\.history-[a-z0-9_]{8}', path.name)):
                    if path.stat().st_mtime < now - 86400:
                        entries.append(([path], path.stat().st_mtime, None))
        index = history / 'runs.csv'
        if index.is_symlink():
            return
        header_size = len(csv_text(FIELDS, []).encode('utf-8'))
        def row_size(summary):
            return 0 if summary is None else len(csv_text(FIELDS, [summary]).encode('utf-8')) - header_size
        used = header_size + 3 + sum(sum(p.stat().st_size for p in files) + row_size(summary)
                                    for files, _, summary in entries)
        survivors = []
        for files, modified, summary in sorted(entries, key=lambda e: e[1]):
            if modified < now - MAX_AGE or used > limit:
                for path in files:
                    size = path.stat().st_size
                    path.unlink()
                    used -= size
                used -= row_size(summary)
            elif summary is not None:
                survivors.append(summary)
        if index.exists() or survivors:
            write_csv(index, FIELDS, survivors)


@contextlib.contextmanager
def recognition_cache(request):
    """Bound app-owned recognition data before and after each analysis, including failures."""
    if not request.get('managed_cache') or not request.get('cache_dir'):
        yield
        return
    cache = Path(request['cache_dir'])
    history = Path(request['history_dir'])
    def trim():
        try:
            prune_recognition(cache, history)
        except OSError:
            # Cleanup cannot turn an otherwise successful analysis into an error.
            import logging
            logging.getLogger(__name__).exception('Could not trim recognition cache')
    trim()
    try:
        yield
    finally:
        trim()
