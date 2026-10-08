import re
from importlib.resources import files
from pathlib import Path


def read_version() -> str:
    source = Path(__file__).resolve().parents[2] / "VERSION"
    value = (
        source.read_text(encoding="utf-8")
        if source.exists()
        else files("payment_processing").joinpath("VERSION").read_text(encoding="utf-8")
    ).strip()
    if re.fullmatch(r"\d+\.\d+\.\d+", value) is None:
        raise ValueError("VERSION must contain a semantic version such as 0.1.0")
    return value
