"""A small RFC 5545 reader for the calendar tests (REQ-DEV-02, card test B3): it refuses a bare line feed or a line
over 75 octets, unfolds continuation lines and unescapes TEXT values."""

from __future__ import annotations

from datetime import UTC, datetime

TEXT_PROPERTIES = frozenset({"SUMMARY", "LOCATION", "DESCRIPTION", "PRODID"})


def unescape(value: str) -> str:
    out, chars = [], iter(value)
    for char in chars:
        if char != "\\":
            out.append(char)
            continue
        following = next(chars)
        out.append("\n" if following in "nN" else following)
    return "".join(out)


def parse(body: bytes) -> list[tuple[str, str]]:
    """The content lines of ``body`` as (name, value), unfolded and (for TEXT) unescaped."""
    text = body.decode("utf-8")
    assert text.endswith("\r\n")
    physical = text[:-2].split("\r\n")
    assert all("\n" not in line and "\r" not in line for line in physical), "a bare line break"
    assert all(len(line.encode("utf-8")) <= 75 for line in physical), "a line over 75 octets"
    logical: list[str] = []
    for line in physical:
        if line.startswith(" "):
            logical[-1] += line[1:]
        else:
            logical.append(line)
    found = []
    for line in logical:
        name, _, value = line.partition(":")
        found.append((name, unescape(value) if name in TEXT_PROPERTIES else value))
    return found


def one(lines: list[tuple[str, str]], name: str) -> str:
    [value] = [v for n, v in lines if n == name]
    return value


def instant(value: str) -> datetime:
    assert value.endswith("Z")
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
