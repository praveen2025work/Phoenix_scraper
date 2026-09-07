"""The capability workspace: capabilities/<id>/ and its capability.yaml.

A capability is defined on disk — capability.yaml is the source of truth — and
mirrored into the `capabilities` table by `pheonix capability sync`. This module
owns the disk side only: id rules, path layout, reading, writing, scaffolding.
"""

import logging
import re
from pathlib import Path

import yaml

from .models import Capability, CapabilityFilter

logger = logging.getLogger(__name__)

CONFIG_NAME = "capability.yaml"
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_FILTER_KEYS = ("project", "workflow_stage", "asset_class", "model_name", "search")
_STATUSES = ("active", "paused")


def validate_id(cap_id: str) -> str:
    """Return ``cap_id`` unchanged, or raise ValueError if it is not a valid slug.

    Valid: 1-64 chars, lowercase ascii letters / digits / hyphens, first char a
    letter. Underscores are out so ids never collide with the ``<id>`` masks in
    normalize.py, and so a capability id is always a safe directory name.
    """
    if not _ID_RE.match(cap_id):
        raise ValueError(
            f"Invalid capability id {cap_id!r}: 1-64 chars, lowercase letters, "
            f"digits and hyphens, starting with a letter."
        )
    return cap_id


def capability_dir(root: Path, cap_id: str) -> Path:
    return Path(root) / cap_id


def config_path(root: Path, cap_id: str) -> Path:
    return capability_dir(root, cap_id) / CONFIG_NAME


def _clean(value: object) -> str | None:
    """Blank / whitespace-only yaml values mean 'unset', matching Settings."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_capability(root: Path, cap_id: str) -> Capability:
    """Parse ``capabilities/<cap_id>/capability.yaml`` into a Capability.

    Raises FileNotFoundError when the file is absent, ValueError when it is not a
    mapping or a nested section has the wrong shape. An unrecognised ``status``
    falls back to ``active`` rather than failing the load.
    """
    path = config_path(root, cap_id)
    if not path.is_file():
        raise FileNotFoundError(f"No {CONFIG_NAME} for capability {cap_id!r} at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    filter_raw = raw.get("filter") or {}
    if not isinstance(filter_raw, dict):
        raise ValueError(f"{path}: 'filter' must be a mapping")
    thresholds_raw = raw.get("thresholds") or {}
    if not isinstance(thresholds_raw, dict):
        raise ValueError(f"{path}: 'thresholds' must be a mapping")
    status = raw.get("status")
    return Capability(
        id=validate_id(str(raw.get("id") or cap_id)),
        name=str(raw.get("name") or cap_id),
        description=str(raw.get("description") or ""),
        filter=CapabilityFilter(**{k: _clean(filter_raw.get(k)) for k in _FILTER_KEYS}),
        window_days=int(raw.get("window_days", 30)),
        thresholds={str(k): float(v) for k, v in thresholds_raw.items()},
        status=status if status in _STATUSES else "active",
    )


def dump_capability(capability: Capability) -> str:
    """Serialise a Capability to capability.yaml text with a stable key order."""
    body = {
        "id": capability.id,
        "name": capability.name,
        "description": capability.description,
        "filter": {key: getattr(capability.filter, key) for key in _FILTER_KEYS},
        "window_days": capability.window_days,
        "thresholds": dict(capability.thresholds),
        "status": capability.status,
    }
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
