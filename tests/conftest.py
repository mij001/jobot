import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobot.config import load_config  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


DEFAULT_CONFIG = FIXTURES / "default_config.yaml"


@pytest.fixture
def cfg():
    """The default settings (a frozen copy – your own config.yaml may differ)."""
    return load_config(DEFAULT_CONFIG)


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")
