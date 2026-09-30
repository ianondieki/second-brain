"""REQ-SEC-04 (P16-E1 item 6): logs carry no personal data or secrets. The audit as a test: every structlog call in
``bridge`` names a constant event and only fields that were reviewed (ids, counts, codes, types, times and config
names) or that the key filter redacts, so a new field that could carry an address, a phone number, a name, free text,
a token or a URL fails here until it is reviewed. The key filter itself redacts the personal-data keys."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bridge import logging as bridge_logging

SRC = Path(bridge_logging.__file__).resolve().parent
LEVELS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "msg"})
# Reviewed fields (P16-E1): ids and hashes of rows, counts, enum values and machine codes, exception type names,
# times, money, model and task names, and config names. Never a person's data or a secret.
SAFE_FIELDS = frozenset(
    {
        "anchored", "attempt", "attempts", "batch_id", "batches", "budget_seconds", "candidates", "cap_usd",
        "category", "chain_id", "chains", "columns", "constraint", "cost_usd", "count", "custom_id", "day",
        "deferred", "delivery_id", "delivery_ids", "demo_fallback", "detail", "discarded", "engagement_id",
        "error", "error_type", "event_id", "failed", "failed_today", "free_slots", "heads", "items", "key_id",
        "kind", "latency_ms", "matched", "model", "prices_verified", "proposal_id", "provider", "provider_status",
        "published", "purpose", "reason", "recipients", "rejected", "rows", "run_id", "scanned", "scout_id", "seq",
        "snapshot_at", "source", "spent_usd", "sqlstate", "stage", "status", "step", "stop_reason", "table",
        "task", "today", "trace_id", "transient", "tsa_time", "user_id", "variable", "verification_id", "version",
        "will_retry_on",
    }
)  # fmt: skip
# ``error`` is an exception's type name, or a provider's reply with every address redacted and its length capped
# (``bridge.notifications.email.redact_addresses``); ``detail`` is a fixed sentence.
# Events named through a variable, each assigned only string constants; and ``**`` fields, each counts by status.
NAMED_EVENTS = {("notifications/deliveries.py", "event")}
SPREAD_FIELDS = {("reminders/dispatch.py", "_counts(report)")}


def _redacted(field: str) -> bool:
    value: object = bridge_logging._redact(None, "", {field: "x"})[field]
    return value == "[redacted]"


def _log_calls() -> list[tuple[str, int, ast.Call]]:
    calls = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LEVELS):
                continue
            owner = node.func.value
            is_log = isinstance(owner, ast.Name) and owner.id in {"log", "logger"}
            is_log |= isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id == "get_logger"
            if is_log:
                calls.append((path.relative_to(SRC).as_posix(), node.lineno, node))
    return calls


def test_the_audit_sees_every_log_call() -> None:
    calls = _log_calls()
    assert len(calls) >= 60
    assert {where for where, _, _ in calls} >= {"auth/service.py", "llm/client.py", "notifications/deliveries.py"}


def test_every_log_call_names_a_constant_event_and_reviewed_fields() -> None:
    problems = []
    for where, line, call in _log_calls():
        event = call.args[0] if call.args else None
        named = isinstance(event, ast.Name) and (where, event.id) in NAMED_EVENTS
        if not (isinstance(event, ast.Constant) and isinstance(event.value, str)) and not named:
            problems.append(f"{where}:{line} event {ast.unparse(event) if event else None}")
        if len(call.args) > 1:
            problems.append(f"{where}:{line} positional arguments are formatted into the event")
        for keyword in call.keywords:
            if keyword.arg is None:
                if (where, ast.unparse(keyword.value)) not in SPREAD_FIELDS:
                    problems.append(f"{where}:{line} **{ast.unparse(keyword.value)}")
            elif keyword.arg not in SAFE_FIELDS and not _redacted(keyword.arg):
                problems.append(f"{where}:{line} field {keyword.arg}")
    assert problems == []


def test_named_events_are_assigned_constants_only() -> None:
    for where, name in NAMED_EVENTS:
        tree = ast.parse((SRC / where).read_text(encoding="utf-8"))
        values = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
        ]
        assert values
        assert all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in values), where


@pytest.mark.parametrize(
    "field",
    [
        "phone",
        "msisdn",
        "display_name",
        "signer_name",
        "email_address",
        "reason_text",
        "other_text",
        "body",
        "url",
        "magic_link",
        "otp",
        "recovery_codes",
        "pepper",
        "session",
        "csrf",
        "credentials",
        "api_key",
        "private_key",
        "password",
        "access_token",
        "client_secret",
        "totp_code",
        "cookie",
        "authorization",
    ],
)
def test_the_key_filter_redacts_personal_data_and_secrets(field: str) -> None:
    assert _redacted(field)
    assert _redacted(field.upper())


def test_reviewed_fields_pass_the_key_filter_unchanged() -> None:
    kept = {field for field in SAFE_FIELDS if not _redacted(field)}
    assert kept == SAFE_FIELDS
