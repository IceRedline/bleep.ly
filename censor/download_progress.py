"""Byte progress from pinned downloaders, without terminal output or synthetic completion."""
import io
import threading
import time


def byte_progress_bar(label, notify, total=None):
    from tqdm import tqdm

    counts = {}
    lock = threading.RLock()
    last_report = -float('inf')

    class DownloadProgress(tqdm):
        def __init__(self, *args, **kwargs):
            name = kwargs.pop('name', '')
            description = kwargs.get('desc', '') or ''
            # Hub reports transfer, reconstruction and file counts separately.
            # Reconstruction measures usable bytes; counting both doubles progress.
            self.track_bytes = (kwargs.get('unit') in {'B', 'iB'} and
                                not name.endswith('.transfer') and
                                not description.lower().endswith('downloading bytes'))
            self.progress_key = (name, description)
            kwargs.update(disable=False, file=io.StringIO())
            super().__init__(*args, **kwargs)
            self.report_bytes()

        def display(self, *args, **kwargs):
            return True

        def report_bytes(self):
            nonlocal last_report
            if not self.track_bytes or not hasattr(self, 'n'):
                return
            with lock:
                # Replacing the same key also resets an interrupted GigaAM attempt.
                counts[self.progress_key] = (max(0, self.n), max(0, self.total or 0))
                done = sum(value[0] for value in counts.values())
                size = total if total is not None else sum(value[1] for value in counts.values())
                now = time.monotonic()
                if done and now - last_report < .1 and (not size or done < size):
                    return
                last_report = now
                if size:
                    notify(f'{label} — {min(done, size) / 1e6:.1f} / {size / 1e6:.1f} MB',
                           min(.99, done / size))
                else:
                    notify(f'{label} — {done / 1e6:.1f} MB', 0)

        def update(self, n=1):
            result = super().update(n)
            self.report_bytes()
            return result

        def refresh(self, *args, **kwargs):
            result = super().refresh(*args, **kwargs)
            self.report_bytes()
            return result

    return DownloadProgress
