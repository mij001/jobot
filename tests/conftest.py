import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobot.config import load_config  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg():
    """The shipped config.yaml, so tests also guard the defaults users get."""
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")
