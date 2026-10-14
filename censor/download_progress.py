"""Byte progress from pinned downloaders, without terminal output or synthetic completion."""
import io
import threading
import time
import weakref


def byte_progress_bar(label, notify, total=None, *, network_only=False):
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
            # Hub's reconstruction counter advances when large buffers reach disk.
            # Its transfer counter reports incoming network bytes continuously.
            # Never combine them: compression/deduplication change the byte totals.
            transfer = name.endswith('.transfer') or description.lower().endswith('downloading bytes')
            self.track_bytes = kwargs.get('unit') in {'B', 'iB'} and transfer == network_only
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
                # Xet's transfer-bar total is an estimate for terminal rendering,
                # not a Content-Length. It is even rewritten to n on completion.
                size = 0 if network_only else total if total is not None else sum(value[1] for value in counts.values())
                now = time.monotonic()
                if not force and done and now - last_report < .1 and (not size or done < size):
                    return
                last_report = now
                if size:
                    notify(f'{label} — {min(done, size) / 1e6:.1f} / {size / 1e6:.1f} MB',
                           min(.99, done / size))
                else:
                    suffix = ' downloaded' if network_only else ''
                    notify(f'{label} — {done / 1e6:.1f} MB{suffix}', 0)

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
