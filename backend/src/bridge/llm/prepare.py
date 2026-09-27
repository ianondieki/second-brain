"""From a task's messages to a ``ModelRequest`` (docs/spec/08 LLM layer; docs/spec/09 Injection defences).

Validation of what callers pass (output schema, message order, cache breakpoints, tools, effort), the sanitiser and
nonce framing of every untrusted field, and the ledger form of the inputs: sanitised Tier-1 values, and for Tier-2
fields only the name, tier, length and what the sanitiser removed (never the value, with or without consent).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from bridge.llm.adapter import TextBlock, WireMessage
from bridge.llm.errors import LLMConfigError
from bridge.llm.registry import EFFORTS, Effort, ModelSpec, SanitiserPolicy, TaskSpec
from bridge.llm.sanitiser import FRAMING_RULES, frame, nonce_instruction, sanitise
from bridge.llm.types import InputField, Instruction, LLMOutput, Message, Tier

MAX_CACHE_BREAKPOINTS = 4  # the Messages API allows four cache_control blocks per request
SERVER_TOOL_MARK = "_"  # server tool types are versioned (web_search_20260209); custom tools have no type


@dataclass(frozen=True, slots=True)
class Prepared:
    system: tuple[TextBlock, ...]
    messages: tuple[WireMessage, ...]
    ledger_inputs: dict[str, Any]


def check_schema(schema: type[LLMOutput]) -> dict[str, Any]:
    """The output schema's JSON schema; refuses a schema without a required boolean ``injection_suspected``."""
    if not (isinstance(schema, type) and issubclass(schema, LLMOutput)):
        raise LLMConfigError("output schemas subclass bridge.llm.types.LLMOutput (injection_suspected in every schema)")
    flag = schema.model_fields.get("injection_suspected")
    if flag is None or flag.annotation is not bool or not flag.is_required():
        raise LLMConfigError(f"{schema.__name__}.injection_suspected must stay a required bool")
    return schema.model_json_schema()


def check_messages(messages: Sequence[Message]) -> None:
    if not messages:
        raise LLMConfigError("a call needs at least one message")
    if any(m.role == "system" for m in messages[1:]):
        raise LLMConfigError("only the first message may be the system prompt")
    if messages[-1].role != "user":
        raise LLMConfigError("the last message must be a user turn")


def check_breakpoints(breakpoints: Sequence[int] | None, count: int) -> frozenset[int]:
    points = frozenset(breakpoints or ())
    if len(points) > MAX_CACHE_BREAKPOINTS:
        raise LLMConfigError(f"at most {MAX_CACHE_BREAKPOINTS} cache breakpoints")
    if any(not 0 <= point < count for point in points):
        raise LLMConfigError("cache breakpoints are indexes into messages")
    return points


def check_tools(spec: TaskSpec, tools: Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    """Only tools listed in the task's ``allowed_tools`` (scouts, explainers and reporters have none); a custom tool
    must be ``strict``. ``tool_choice`` is never set anywhere."""
    for tool in tools or ():
        tool_type = str(tool.get("type") or "")
        server = SERVER_TOOL_MARK in tool_type
        kind = tool_type if server else str(tool.get("name") or "")  # server tools by type, custom tools by name
        if kind not in spec.allowed_tools:
            raise LLMConfigError(f"task {spec.name} may not use tool {kind or '(unnamed)'}")
        if not server and tool.get("strict") is not True:
            raise LLMConfigError(f"custom tool {kind} must set strict: true")
    return tuple(tools or ())


def resolve_effort(spec: TaskSpec, model: ModelSpec, override: str | None) -> Effort | None:
    if override is None:
        return spec.effort
    if override not in EFFORTS:
        raise LLMConfigError(f"effort must be one of {sorted(EFFORTS)}")
    if not model.supports_effort:
        raise LLMConfigError(f"{model.id} has no effort parameter")
    return cast(Effort, override)


def prompt_sha256(messages: Sequence[Message]) -> str:
    """Identifies the prompt version: a digest of every trusted instruction, never of untrusted text."""
    digest = hashlib.sha256()
    for message in messages:
        for part in message.parts:
            if isinstance(part, Instruction):
                digest.update(message.role.encode() + b"\x1f" + part.text.encode() + b"\x1e")
    return digest.hexdigest()


def field_record(field: InputField, text: str | None = None, removed: frozenset[str] = frozenset()) -> dict[str, Any]:
    record: dict[str, Any] = {"name": field.name, "tier": field.tier.value}
    if text is None:  # refused before sanitising: no value of any tier
        record["chars"] = len(field.value)
        return record
    record["chars"] = len(text)
    record["removed"] = sorted(removed)
    if field.tier is Tier.TIER1:
        record["value"] = text
    return record


def unsent_inputs(messages: Sequence[Message]) -> dict[str, Any]:
    """The ledger form of a call refused before sanitising (kill switch, Tier-2 guard): names and lengths only."""
    return {
        "prompt_sha256": prompt_sha256(messages),
        "fields": [field_record(f) for m in messages for f in m.fields],
    }


def prepare(
    spec: TaskSpec,
    messages: Sequence[Message],
    *,
    policy: SanitiserPolicy,
    nonce: str,
    breakpoints: frozenset[int],
) -> Prepared:
    """Sanitise and frame every field; the system prompt gets the framing rules (cacheable) and a per-call nonce
    line after the breakpoint. Call only after ``check_tier2`` passed."""
    head = messages[0] if messages[0].role == "system" else None
    system_text = "\n\n".join(p.text for p in head.parts if isinstance(p, Instruction)) if head else ""
    rules = f"{system_text}\n\n{FRAMING_RULES}" if system_text else FRAMING_RULES
    system = (TextBlock(rules, cache=head is not None and 0 in breakpoints), TextBlock(nonce_instruction(nonce)))
    wire: list[WireMessage] = []
    records: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.role == "system":
            continue
        blocks: list[TextBlock] = []
        for part in message.parts:
            if isinstance(part, Instruction):
                blocks.append(TextBlock(part.text))
                continue
            cap = min(part.max_chars or spec.max_field_chars, spec.max_field_chars)
            clean = sanitise(part.value, max_chars=cap, base64_run_chars=policy.base64_run_chars)
            blocks.append(TextBlock(frame(part.name, part.tier, clean.text, nonce)))
            records.append(field_record(part, clean.text, clean.removed))
        if index in breakpoints:
            blocks[-1] = replace(blocks[-1], cache=True)
        wire.append(WireMessage("user" if message.role == "user" else "assistant", tuple(blocks)))
    return Prepared(system, tuple(wire), {"prompt_sha256": prompt_sha256(messages), "fields": records})


def with_feedback(messages: tuple[WireMessage, ...], feedback: str) -> tuple[WireMessage, ...]:
    """The same conversation with ``feedback`` appended to the final user turn (the schema-failure retry)."""
    last = messages[-1]
    return (*messages[:-1], WireMessage(last.role, (*last.blocks, TextBlock(feedback))))
