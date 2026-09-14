"""Classify cluster text as skill-shaped (user questions) vs deterministic payloads.

Live Phoenix traces often put Bedrock invocation JSON, MCP tool selects, SQL,
file_path blobs, and API parameter dicts into ``input.value``. Those belong on
Rung 2 (make-deterministic), not Rung 1 (promote to skill). This module:

- extracts a clean user-facing question when one is wrapped in a model payload
- decides whether text is deterministic-shaped (tool/SQL/params) vs skill-shaped
"""

from __future__ import annotations

import json
import re
from typing import Any

_USER_QUERY_MARKERS = (
    re.compile(r"(?im)^\s*USER\s+QUERY\s*:\s*(.+?)(?:\n\s*\n|\Z)"),
    re.compile(r"(?im)\bUSER\s+QUERY\s*:\s*(.+?)(?:\n\s*\n|\Z)"),
)

_SQL_HEAD = re.compile(
    r"(?is)^\s*(?:with\b.+\bselect\b|select\b|insert\b|update\b|delete\b|create\b|"
    r"drop\b|alter\b|pragma\b|explain\b)\b"
)
_MCP_TOOL = re.compile(r"(?i)\bmcp__[a-z0-9_-]+__[a-z0-9_-]+\b")
_FILE_PATH_KEYS = re.compile(
    r"(?i)\b(?:file_path|filepath|document_id|documentid|s3://|s3_uri|object_key)\b"
)
_BEDROCK_MARKERS = re.compile(
    r"(?i)\b(?:anthropic_version|bedrock|inferenceConfig|system\s*:\s*\[|"
    r"\"messages\"\s*:)\b"
)
_PARAM_DICT_KEYS = re.compile(
    r"(?i)\b(?:endpoint|query|tool_name|toolName|parameters|params|arguments|"
    r"input_schema|content_type)\b"
)
_SELECT_MCP = re.compile(r"(?i)\bselect\s*:\s*mcp__")


def extract_user_prompt(text: str) -> str:
    """Return the user-facing question when ``text`` wraps one; else stripped text.

    Handles Bedrock/Anthropic-style JSON (``messages`` / system payloads) and
    plain ``USER QUERY:`` markers embedded in larger system prompts.
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    marker = _extract_user_query_marker(raw)
    if marker:
        return marker

    parsed = _try_parse_json(raw)
    if parsed is not None:
        from_json = _user_text_from_payload(parsed)
        if from_json:
            return from_json.strip()

    # JSON-ish string that failed full parse — still try marker / message scrapes.
    if _looks_like_structured(raw):
        scraped = _scrape_user_from_blob(raw)
        if scraped:
            return scraped

    return raw


def display_title(text: str, *, max_len: int = 200) -> str:
    """Card title: extracted user prompt, truncated."""
    cleaned = extract_user_prompt(text).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def is_deterministic_shaped(text: str) -> bool:
    """True when text looks like a tool/SQL/params payload, not a user question."""
    raw = (text or "").strip()
    if not raw:
        return False

    # Prefer the extracted user question when present — a Bedrock wrapper that
    # contains a real USER QUERY is skill-shaped after extraction.
    extracted = extract_user_prompt(raw)
    if extracted and extracted != raw and not _payload_markers(extracted):
        return False

    return _payload_markers(extracted or raw)


def is_skill_shaped(text: str) -> bool:
    """True when text should appear in the promote-to-skill / skill-gaps lane."""
    raw = (text or "").strip()
    if not raw:
        return False
    return not is_deterministic_shaped(raw)


def _payload_markers(text: str) -> bool:
    s = text.strip()
    if not s:
        return False

    if _SELECT_MCP.search(s) or _MCP_TOOL.search(s):
        return True
    if _SQL_HEAD.match(s) or _looks_like_sql_blob(s):
        return True
    if _FILE_PATH_KEYS.search(s) and _looks_like_structured(s):
        return True
    if _BEDROCK_MARKERS.search(s) and _looks_like_structured(s):
        # Unextracted Bedrock/Anthropic invocation blob.
        return True
    if _looks_like_param_dict(s):
        return True
    return False

def _looks_like_sql_blob(text: str) -> bool:
    lower = text.casefold()
    if "session_id" in lower and ("select" in lower or "from " in lower):
        return True
    if " from " in lower and " where " in lower and ";" in text:
        return True
    return False


def _looks_like_structured(text: str) -> bool:
    s = text.lstrip()
    return s.startswith(("{", "[", "'{")) or ('{' in s and ("'" in s or '"' in s))


def _looks_like_param_dict(text: str) -> bool:
    if not _looks_like_structured(text):
        return False
    if not _PARAM_DICT_KEYS.search(text):
        return False
    # Short NL questions mentioning "query" should not match.
    if len(text) < 40 and not text.lstrip().startswith(("{", "[")):
        return False
    parsed = _try_parse_json(text)
    if isinstance(parsed, dict):
        keys = {str(k).casefold() for k in parsed}
        payload_keys = {
            "query", "tool_name", "toolname", "parameters", "params", "arguments",
            "endpoint", "file_path", "filepath", "document_id", "input",
        }
        if keys & payload_keys:
            return True
        # Nested select:mcp__… style
        for v in parsed.values():
            if isinstance(v, str) and (_MCP_TOOL.search(v) or _SELECT_MCP.search(v)):
                return True
    # Python-repr dicts that failed JSON parse
    if text.lstrip().startswith(("{", "'{")) and _PARAM_DICT_KEYS.search(text):
        return True
    return False


def _extract_user_query_marker(text: str) -> str | None:
    for pat in _USER_QUERY_MARKERS:
        m = pat.search(text)
        if m:
            found = m.group(1).strip().strip('"').strip("'")
            if found:
                return found
    return None

def _try_parse_json(text: str) -> Any | None:
    s = text.strip()
    if not s:
        return None
    # Python-ish single quotes → try a light normalisation for common cases.
    candidates = [s]
    if s.startswith("'") and s.endswith("'"):
        candidates.append(s[1:-1])
    for cand in candidates:
        try:
            return json.loads(cand)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def _user_text_from_payload(payload: Any) -> str | None:
    if isinstance(payload, str):
        return _extract_user_query_marker(payload) or (
            payload.strip() if not _looks_like_structured(payload) else None
        )
    if isinstance(payload, list):
        # Anthropic messages list — take last user content.
        for item in reversed(payload):
            if isinstance(item, dict) and str(item.get("role", "")).lower() == "user":
                return _content_to_text(item.get("content"))
        return None
    if not isinstance(payload, dict):
        return None

    for key in ("user_query", "userQuery", "question", "prompt"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    messages = payload.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, dict) and str(item.get("role", "")).lower() == "user":
                text = _content_to_text(item.get("content"))
                if text:
                    return text

    # System / instructions may embed USER QUERY:
    for key in ("system", "instructions", "input"):
        val = payload.get(key)
        if isinstance(val, str):
            marker = _extract_user_query_marker(val)
            if marker:
                return marker
        elif isinstance(val, list):
            for block in val:
                if isinstance(block, dict):
                    marker = _extract_user_query_marker(_content_to_text(block) or "")
                    if marker:
                        return marker
                elif isinstance(block, str):
                    marker = _extract_user_query_marker(block)
                    if marker:
                        return marker
    return None


def _content_to_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        marker = _extract_user_query_marker(content)
        return (marker or content).strip() or None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        joined = "\n".join(parts).strip()
        if not joined:
            return None
        marker = _extract_user_query_marker(joined)
        return marker or joined
    return None


def _scrape_user_from_blob(text: str) -> str | None:
    marker = _extract_user_query_marker(text)
    if marker:
        return marker
    # "role": "user" … "text": "…"
    m = re.search(
        r'(?is)"role"\s*:\s*"user".*?(?:"text"|"content")\s*:\s*"((?:\\.|[^"\\])*)"',
        text,
    )
    if m:
        try:
            return json.loads(f'"{m.group(1)}"').strip()
        except (TypeError, ValueError, json.JSONDecodeError):
            return m.group(1).strip()
    return None
