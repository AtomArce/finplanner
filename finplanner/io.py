"""Load/save state.json into/out of PlannerConfig.

state.json carries a few non-config keys (_comment, institution_picks._options_reference)
that we preserve on round-trip so saving doesn't drop the reference data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import PlannerConfig

_PASSTHROUGH_TOP = ("_comment",)


def load_config(path: str | Path) -> PlannerConfig:
    raw = json.loads(Path(path).read_text())
    return _config_from_raw(raw)


def _config_from_raw(raw: dict[str, Any]) -> PlannerConfig:
    data = {k: v for k, v in raw.items() if not k.startswith("_")}
    # state.json nests jurisdiction/tax_year under _meta; map it onto meta.
    if "_meta" in raw:
        data["meta"] = raw["_meta"]
    # Drop the _options_reference block inside institution_picks before validation.
    picks = data.get("institution_picks")
    if isinstance(picks, dict):
        data["institution_picks"] = {
            k: v for k, v in picks.items() if not k.startswith("_")
        }
    return PlannerConfig.model_validate(data)


def save_config(cfg: PlannerConfig, path: str | Path) -> None:
    out = cfg.model_dump(mode="json", exclude_none=False)
    # Restore the _meta key shape state.json uses.
    out["_meta"] = out.pop("meta", {})
    Path(path).write_text(json.dumps(out, indent=2, default=str))


def config_from_dict(raw: dict[str, Any]) -> PlannerConfig:
    """Parse a config from a dict (e.g. from a user-uploaded JSON file)."""
    return _config_from_raw(raw)


def config_to_json(cfg: PlannerConfig) -> str:
    """Serialize cfg to the state.json wire format as a string (no file I/O)."""
    out = cfg.model_dump(mode="json", exclude_none=False)
    out["_meta"] = out.pop("meta", {})
    return json.dumps(out, indent=2, default=str)
