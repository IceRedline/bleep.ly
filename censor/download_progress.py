"""Byte progress from pinned downloaders, without terminal output or synthetic completion."""
import io
import threading
import time
import weakref
from contextlib import contextmanager


@contextmanager
def sized_model_downloads():
    """Use streamed file bytes so progress and manifest totals share one unit.

    Each desktop worker prepares one model at a time. Restore SDK settings even
    on cancellation; HTTP retries, pinned revisions and cache validation stay in Hub.
    """
    from huggingface_hub import constants
    previous = constants.HF_HUB_DISABLE_XET, constants.DOWNLOAD_CHUNK_SIZE
    constants.HF_HUB_DISABLE_XET = True
    constants.DOWNLOAD_CHUNK_SIZE = 1024 * 1024
    try:
        yield
    finally:
        constants.HF_HUB_DISABLE_XET, constants.DOWNLOAD_CHUNK_SIZE = previous


def download_snapshot(snapshot_download, repo, name, offline, notify, **options):
    """Report one SDK snapshot with the same manifest used for its download."""
    notify(f"Checking {name} model", 0)
    if offline:
        return snapshot_download(repo, local_files_only=True, **options)
    # A local snapshot directory may contain only files from an interrupted
    # download. Online mode must check the pinned file list before using it.
    # Plain HTTP reports received file bytes continuously, against the same
    # manifest sizes. Xet's compressed wire bytes cannot use this denominator.
    with sized_model_downloads():
        notify(f"Checking {name} download size", 0)
        plan_bar = byte_progress_bar('', lambda *_: None)
        try:
            plan = snapshot_download(repo, dry_run=True, tqdm_class=plan_bar, **options)
        finally:
            plan_bar.finish()
        pending = [item for item in plan if item.will_download]
        total = sum(item.file_size for item in pending) if all(item.file_size is not None for item in pending) else 0
        notify(f"Connecting to download {name}", 0)
        progress_bar = byte_progress_bar(f"Downloading {name}", notify, total)
        try:
            path = snapshot_download(repo, tqdm_class=progress_bar, headers={'Accept-Encoding': 'identity'}, **options)
        finally:
            progress_bar.finish()
    notify(f"{name} model ready", 1)
    return path


@contextmanager
def reported_hub_downloads(name, notify):
    """Adapt Whisper loaders that call Hub internally, within one desktop worker.

    Keep the SDK's model aliases, file filters, revision, cache and offline rules.
    Restore its entry point on success, error and cancellation.
    """
    import huggingface_hub
    original = huggingface_hub.snapshot_download

    def snapshot(repo_id, **options):
        offline = options.pop('local_files_only', False)
        options.pop('tqdm_class', None)
        path = download_snapshot(original, repo_id, name, offline, notify, **options)
        notify(f"Loading {name} model", 0)
        return path

    huggingface_hub.snapshot_download = snapshot
    try:
        notify(f"Loading {name} model", 0)
        yield
    finally:
        huggingface_hub.snapshot_download = original


def byte_progress_bar(label, notify, total=None):
    from tqdm import tqdm

    counts = {}
    lock = threading.RLock()
    last_report = -float('inf')
    instances = weakref.WeakSet()
    finished = False

    class DownloadProgress(tqdm):
        def __init__(self, *args, **kwargs):
            name = kwargs.pop('name', '')
            description = kwargs.get('desc', '') or ''
            # HTTP updates the file counter for each received chunk, including
            # resumed bytes. Ignore Hub's duplicate transfer and file-count bars.
            transfer = name.endswith('.transfer') or description.lower().endswith('downloading bytes')
            self.track_bytes = kwargs.get('unit') in {'B', 'iB'} and not transfer
            self.progress_key = (name, description)
            instances.add(self)
            kwargs.update(disable=False, file=io.StringIO())
            super().__init__(*args, **kwargs)
            self.report_bytes()

        def display(self, *args, **kwargs):
            return True

        def report_bytes(self, *, force=False):
            nonlocal last_report
            if not self.track_bytes or not hasattr(self, 'n'):
                return
            with lock:
                if finished:
                    return
                # Replacing the same key also resets an interrupted GigaAM attempt.
                counts[self.progress_key] = (max(0, self.n), max(0, self.total or 0))
                done = sum(value[0] for value in counts.values())
                size = total if total is not None else sum(value[1] for value in counts.values())
                now = time.monotonic()
                if not force and done and now - last_report < .1 and (not size or done < size):
                    return
                last_report = now
                if size:
                    notify(f'{label} — {min(done, size) / 1e6:.1f} / {size / 1e6:.1f} MB',
                           min(.99, done / size))
                else:
                    notify(f'{label} — {done / 1e6:.1f} MB downloaded', 0)

        def update(self, n=1):
            result = super().update(n)
            self.report_bytes()
            return result

        def refresh(self, *args, **kwargs):
            result = super().refresh(*args, **kwargs)
            self.report_bytes()
            return result

        def close(self):
            if not getattr(self, 'disable', True):
                self.report_bytes(force=True)
            return super().close()

        @classmethod
        def finish(cls):
            # Hub can retain bars beyond snapshot_download's return. Flush while
            # the stage is active, then prevent late GC/callbacks reopening it.
            nonlocal finished
            with lock:
                if not finished:
                    for bar in list(instances):
                        bar.report_bytes(force=True)
                    finished = True

    return DownloadProgress
