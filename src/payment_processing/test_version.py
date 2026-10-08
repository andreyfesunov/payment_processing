from importlib.metadata import version
from pathlib import Path

from payment_processing.version import read_version


def test_version_matches_source_and_installed_metadata() -> None:
    expected = (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    assert read_version() == expected
    assert version("payment-processing") == expected
