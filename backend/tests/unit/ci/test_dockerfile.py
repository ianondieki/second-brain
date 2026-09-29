"""The backend image carries every file the app reads by default (config/, ai/, seed/): a Settings default path, or a
module-level path under BACKEND_DIR, that the Dockerfile does not COPY would fail only at runtime in the image."""

from __future__ import annotations

import re
from pathlib import Path

from bridge.config import BACKEND_DIR, Settings
from bridge.seed import reference

DOCKERFILE = BACKEND_DIR / "Dockerfile"
COPY = re.compile(r"^COPY\s+(?!--from)(?P<sources>.+?)\s+\S+\s*$", re.MULTILINE)


def copied() -> set[str]:
    """Top-level names of backend/ copied into the image."""
    names: set[str] = set()
    for match in COPY.finditer(DOCKERFILE.read_text(encoding="utf-8")):
        names.update(Path(source).parts[0] for source in match.group("sources").split())
    return names


def default_paths() -> list[Path]:
    paths = [field.default for field in Settings.model_fields.values() if isinstance(field.default, Path)]
    return [*paths, reference.REFERENCE_FILE]


def test_the_image_copies_every_default_path() -> None:
    in_image = copied()
    for path in default_paths():
        top = path.relative_to(BACKEND_DIR).parts[0]
        assert top in in_image, f"backend/Dockerfile does not COPY {top}/ (needed for {path.name})"
        assert path.is_file(), path


def test_the_expected_directories_are_copied() -> None:
    assert {"src", "alembic", "config", "ai", "seed"} <= copied()
    assert "models.yaml" in {p.name for p in default_paths()}
