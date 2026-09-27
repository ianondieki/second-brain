"""Seed step: placeholder legal and NDA templates from ``backend/seed/legal_templates.yaml`` (REQ-REPO-01).

Bodies are the DRAFT header plus ``[[LEGAL-PLACEHOLDER:<id>]]`` markers only; the advocate's wording replaces them at
G2 as new versions. Idempotent: rows are upserted on (kind, version). Changing the body of a version that has been
accepted fails on the acceptances' (template id, sha256) foreign keys, which is intended.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.config import BACKEND_DIR
from bridge.ids import uuid7
from bridge.legal.models import LegalTemplate, NdaTemplate

LEGAL_TEMPLATES_FILE = BACKEND_DIR / "seed" / "legal_templates.yaml"
PLACEHOLDER = "[[LEGAL-PLACEHOLDER:{id}]]"


def load_legal_templates(path: Path = LEGAL_TEMPLATES_FILE) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def template_body(header: str, placeholders: list[str]) -> str:
    """The seeded body: the DRAFT header, a blank line, then one marker line per placeholder id."""
    if not placeholders:
        raise ValueError("a seeded legal template needs at least one placeholder")
    return header + "\n\n" + "\n".join(PLACEHOLDER.format(id=p) for p in placeholders) + "\n"


def body_sha256(body: str) -> bytes:
    return hashlib.sha256(body.encode("utf-8")).digest()


async def seed_legal_templates(conn: AsyncConnection, data: dict[str, Any]) -> None:
    header = str(data["header"])
    legal: dict[tuple[str, str], tuple[Any, bytes]] = {}
    for row in data["legal_templates"]:
        body = template_body(header, [str(p) for p in row["placeholders"]])
        stmt = insert(LegalTemplate).values(
            id=uuid7(),
            kind=row["kind"],
            version=str(row["version"]),
            sha256=body_sha256(body),
            body=body,
            is_placeholder=True,
        )
        result = await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[LegalTemplate.kind, LegalTemplate.version],
                set_={
                    "sha256": stmt.excluded.sha256,
                    "body": stmt.excluded.body,
                    "is_placeholder": stmt.excluded.is_placeholder,
                },
            ).returning(LegalTemplate.id, LegalTemplate.sha256)
        )
        template_id, digest = result.one()
        legal[(str(row["kind"]), str(row["version"]))] = (template_id, digest)
    for row in data["nda_templates"]:
        template_id, digest = legal[(str(row["legal"]["kind"]), str(row["legal"]["version"]))]
        nda = insert(NdaTemplate).values(
            id=uuid7(), kind=row["kind"], version=str(row["version"]), legal_template_id=template_id, sha256=digest
        )
        await conn.execute(
            nda.on_conflict_do_update(
                index_elements=[NdaTemplate.kind, NdaTemplate.version],
                set_={"legal_template_id": nda.excluded.legal_template_id, "sha256": nda.excluded.sha256},
            )
        )
