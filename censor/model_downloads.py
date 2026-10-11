"""Identify missing model assets without treating inference/network errors as consent."""
from .utils import CensorError


class ModelDownloadRequired(CensorError):
    pass


def requires_model_download(error):
    # Imported only on failure; normal export/preview needs no Hub dependency.
    try:
        from huggingface_hub.errors import LocalEntryNotFoundError
        missing = (ModelDownloadRequired, LocalEntryNotFoundError)
    except ImportError:
        missing = (ModelDownloadRequired,)
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, missing):
            return True
        error = error.__cause__
    return False
