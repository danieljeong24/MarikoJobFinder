import json
from pathlib import Path

import pytest

from job_watch.config import Employer, load_config

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def config():
    """The shipped config.yaml, so tests check the real keyword lists."""
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def load_fixture():
    def _load(name: str):
        path = FIXTURES / name
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_text(encoding="utf-8")

    return _load


def make_employer(type_: str, **options) -> Employer:
    return Employer(id="test", name="Test Firm", category="national", type=type_, options=options)
