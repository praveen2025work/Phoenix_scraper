"""Prefer OpenInference ``llm.input_messages`` / ``llm.output_messages`` text.

Phoenix docs (and OpenInference) put structured chat turns on these attributes.
Raw ``input.value`` is often a Bedrock/Anthropic invocation blob — messages are
the cleaner ask/answer when present.
"""

from __future__ import annotations

import json
from typing import Any


def messages_user_text(attributes: dict[str, Any] | None) -> str:
    """Last user message content from ``llm.input_messages`` (any nesting)."""
    if not attributes:
        return ""
    messages = _find_messages(attributes, side="input")
    return _last_role_text(messages, roles=("user", "human")) or _first_text(messages)


def messages_assistant_text(attributes: dict[str, Any] | None) -> str:
    """Last assistant/model message from ``llm.output_messages``."""
    if not attributes:
        return ""
    messages = _find_messages(attributes, side="output")
    return _last_role_text(
        messages, roles=("assistant", "model", "ai")
    ) or _first_text(messages)


def prefer_messages_io(
    *,
    attributes: dict[str, Any] | None,
    input_value: str = "",
    output_value: str = "",
) -> tuple[str, str]:
    """Return (input_text, output_text), preferring message attrs when non-empty."""
    attrs = attributes or {}
    user = messages_user_text(attrs)
    assistant = messages_assistant_text(attrs)
    return (user or input_value or "", assistant or output_value or "")


def _find_messages(attributes: dict[str, Any], *, side: str) -> list[Any]:
    keys = (
        (
            f"llm.{side}_messages",
            f"llm.{side}Messages",
            f"attributes.llm.{side}_messages",
            side + "_messages",
        )
        if side in {"input", "output"}
        else ()
    )
    for key in keys:
        found = _dig(attributes, key)
        if isinstance(found, list) and found:
            return found
        if isinstance(found, dict) and found:
            # Flattened index dict {"0": {...}, "1": {...}}
            ordered = [
                found[k] for k in sorted(found, key=lambda x: _index_key(x))
            ]
            if ordered:
                return ordered

    # Flattened OpenInference columns already expanded into attributes dict:
    # llm.input_messages.0.message.role / .content
    # (and attributes.llm.input_messages.… on dataframe rows)
    prefixes = (f"llm.{side}_messages.", f"attributes.llm.{side}_messages.")
    indexed: dict[int, dict[str, Any]] = {}
    for key, value in attributes.items():
        if not isinstance(key, str):
            continue
        matched_prefix = next((p for p in prefixes if key.startswith(p)), None)
        if matched_prefix is None:
            continue
        rest = key[len(matched_prefix) :]
        parts = rest.split(".")
        if not parts or not parts[0].isdigit():
            continue
        idx = int(parts[0])
        slot = indexed.setdefault(idx, {})
        path = parts[1:]
        if not path:
            slot["value"] = value
            continue
        leaf = path[-1]
        if leaf in {"role", "content", "text"}:
            slot[leaf] = value
        elif len(path) >= 2 and path[0] == "message":
            slot[path[1]] = value
    if indexed:
        return [indexed[i] for i in sorted(indexed)]
    return []


def _dig(mapping: dict[str, Any], dotted: str) -> Any:
    if dotted in mapping:
        return mapping[dotted]
    cur: Any = mapping
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _index_key(key: object) -> tuple[int, str]:
    text = str(key)
    return (int(text), text) if text.isdigit() else (10**9, text)


def _last_role_text(messages: list[Any], *, roles: tuple[str, ...]) -> str:
    wanted = {r.lower() for r in roles}
    for item in reversed(messages):
        role, text = _message_role_text(item)
        if role in wanted and text:
            return text
    return ""


def _first_text(messages: list[Any]) -> str:
    for item in messages:
        _, text = _message_role_text(item)
        if text:
            return text
    return ""


def _message_role_text(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        return ("", item.strip())
    if not isinstance(item, dict):
        return ("", "")
    # Shapes: {role, content}, {message: {role, content}}, {message.role, ...}
    msg = item.get("message") if isinstance(item.get("message"), dict) else item
    role = str(msg.get("role") or item.get("role") or "").strip().lower()
    content = msg.get("content", msg.get("text", item.get("content", item.get("text"))))
    return (role, _content_to_str(content))


def _content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        if isinstance(text, str):
            return text.strip()
        try:
            return json.dumps(content, default=str)
        except (TypeError, ValueError):
            return str(content)
    return str(content).strip()
