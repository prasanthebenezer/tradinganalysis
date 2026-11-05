"""Small on-disk cache so repeated agent calls don't re-download from Yahoo."""

from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parent.parent


def cache_dir() -> Path:
    d = Path(os.environ.get("TRADINGANALYSIS_CACHE_DIR") or _REPO_ROOT / ".cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(key: str) -> Path:
    # Hash the key so a symbol can never become a path.
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    return cache_dir() / f"{digest}.pkl"


def cached(key: str, max_age_s: float, fetch: Callable[[], Any]) -> Any:
    """Return the cached value for key if younger than max_age_s, else fetch and store it."""
    p = _path(key)
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age_s:
        try:
            with p.open("rb") as f:
                return pickle.load(f)
        except Exception:
            pass  # corrupt entry: refetch
    value = fetch()
    tmp = p.with_suffix(".tmp")
    with tmp.open("wb") as f:
        pickle.dump(value, f)
    tmp.replace(p)
    return value
