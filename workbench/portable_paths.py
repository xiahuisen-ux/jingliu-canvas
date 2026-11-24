"""Application data and optional backends live outside the downloaded code."""
import os
from pathlib import Path

DATA = Path(os.environ.get("JINGLIU_DATA") or (Path.home() / "Library/Application Support/Jingliu Canvas Studio")).expanduser().resolve()
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
BACKENDS = Path(os.environ.get("JINGLIU_BACKENDS") or DATA / "backends").expanduser().resolve()
