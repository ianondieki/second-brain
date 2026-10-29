"""The database's backstop of the state machine's table: ``engagement_main_path_predecessors``, read from the newest
Alembic revision that defines it (revision 0003 created it; revision 0015 replaced it in place, 3b between stages 2
and 3). In a revision that replaces it, the upgrade's definition comes first (the restore of the earlier body for the
downgrade follows it)."""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"
_DEFINITION = re.compile(r"CREATE (?:OR REPLACE )?FUNCTION engagement_main_path_predecessors")
_ROW = re.compile(r"WHEN '([A-Z_]+)' THEN '\{([A-Z_,]*)\}'")


def database_predecessors() -> dict[str, set[str]]:
    """WHEN '<state>' THEN '{<states>}': each main-path state and the states it may be entered from."""
    for revision in sorted(VERSIONS.glob("*.py"), reverse=True):
        source = revision.read_text(encoding="utf-8")
        found = _DEFINITION.search(source)
        if found is not None:
            body = source[found.start() :]
            body = body[: body.index("$$;")]
            return {state: set(filter(None, before.split(","))) for state, before in _ROW.findall(body)}
    raise AssertionError("no revision defines engagement_main_path_predecessors")
