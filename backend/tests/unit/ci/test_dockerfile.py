"""The backend image carries every file the app reads by default (config/, ai/, seed/): a Settings default path, or a
module-level path under BACKEND_DIR, that the Dockerfile does not COPY would fail only at runtime in the image."""

from __future__ import annotations

import json
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


def test_the_api_keeps_idle_connections_longer_than_the_proxy() -> None:
    """P16-F flake: Next.js rewrites proxy /api through httpxy's keep-alive agent (no idle timeout), so uvicorn closes
    idle sockets; with its default 5 s, the e2e suite's ordinary gaps between requests sometimes reused a socket in
    the moment it closed and got a plain 500. A longer keep-alive narrows that window (it does not remove it)."""
    cmd = next(line for line in DOCKERFILE.read_text(encoding="utf-8").splitlines() if line.startswith("CMD "))
    args = json.loads(cmd.removeprefix("CMD "))
    assert args[0] == "uvicorn"
    assert "--timeout-keep-alive" in args, "uvicorn's default keep-alive (5 s) matches the e2e suite's request gaps"
    assert int(args[args.index("--timeout-keep-alive") + 1]) >= 60
