from datetime import date
from pathlib import Path

import pytest

from finplanner.io import load_config

STATE = Path(__file__).resolve().parent.parent / "state.json"


@pytest.fixture
def base_cfg():
    """The project's state.json, with a fixed signing date for deterministic month math."""
    cfg = load_config(STATE)
    cfg.severance.signing_date = date(2026, 6, 1)
    return cfg
