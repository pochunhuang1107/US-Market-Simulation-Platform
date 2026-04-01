from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def hash_config(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def create_experiment_dir(base_dir: str | Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = Path(base_dir) / f"experiment_{ts}"
    path.mkdir(parents=True, exist_ok=True)
    return path