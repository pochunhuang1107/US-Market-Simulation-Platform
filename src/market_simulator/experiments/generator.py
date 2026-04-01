from __future__ import annotations

import itertools
from copy import deepcopy


def _parse_part(part: str):
    if "[" in part and part.endswith("]"):
        name, idx = part[:-1].split("[", 1)
        return name, int(idx)
    return part, None


def set_nested(config: dict, path: str, value) -> None:
    parts = path.split(".")
    current = config

    for part in parts[:-1]:
        key, idx = _parse_part(part)
        current = current[key]
        if idx is not None:
            current = current[idx]

    last_key, last_idx = _parse_part(parts[-1])
    if last_idx is None:
        current[last_key] = value
    else:
        current[last_key][last_idx] = value


def generate_configs(base_config: dict, search_space: dict):
    keys = list(search_space.keys())
    value_lists = [search_space[k] for k in keys]

    for combo in itertools.product(*value_lists):
        cfg = deepcopy(base_config)
        for key, value in zip(keys, combo):
            set_nested(cfg, key, value)
        yield cfg