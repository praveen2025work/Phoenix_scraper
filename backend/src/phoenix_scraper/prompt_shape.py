"""Classify cluster text as skill-shaped (user questions) vs deterministic payloads.

Live Phoenix traces often put Bedrock invocation JSON, MCP tool selects, SQL,
file_path blobs, and API parameter dicts into ``input.value``. Those belong on
Rung 2 (make-deterministic), not Rung 1 (promote to skill). This module:

- extracts a clean user-facing question when one is wrapped in a model payload
- decides whether text is deterministic-shaped (tool/SQL/params) vs skill-shaped
- splits DataFrames into user-ask spans vs LLM/MCP analysis spans for each lane

Rung 1 asks are **session turns**: one root span per ``trace_id`` (Phoenix
Turns/Traces UI — typically ``agent_request``), not every nested LLM span.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from .turns import turn_root_spans

_USER_QUERY_MARKERS = (
    # Prefer a clean line / quoted value; stop before JSON wrappers.
    re.compile(r"(?im)USER\s+QUERY\s*:\s*\"([^\"]+)\""),
    re.compile(r"(?im)USER\s+QUERY\s*:\s*'([^']+)'"),
    re.compile(r"(?im)USER\s+QUERY\s*:\s*([^\n\"{}]+)"),
)

# A leading SQL *word* is not SQL: real prompts open with "Explain the top
# drivers...", "Update me on...", "Select the best hedge...". Each branch below
# therefore requires the follow-on token that makes the statement actual SQL.
_SQL_HEAD = re.compile(
    r"(?is)^\s*(?:"
    r"with\b.+\bselect\b.+\bfrom\b"
    r"|select\b.+\bfrom\b"
    r"|insert\s+into\b"
    r"|update\b.+\bset\b"
    r"|delete\s+from\b"
    r"|create\s+(?:temp\s+|temporary\s+|unique\s+)*(?:table|index|view|trigger|database)\b"
    r"|drop\s+(?:table|index|view|trigger|database)\b"
    r"|alter\s+table\b"
    r"|pragma\s+\w+"
    r"|explain\s+(?:query\s+plan\b|select\b|insert\b|update\b|delete\b)"
    r")"
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


def is_user_ask_span(span_kind: object, input_text: object) -> bool:
    """True when this span *could* be a user question (skill-shaped text).

    Kind may be LLM, CHAIN, or AGENT — Phoenix turn roots are often CHAIN
    ``agent_request``. Prefer :func:`filter_user_ask_spans`, which also collapses
    to one ask per trace.
    """
    kind = str(span_kind or "UNKNOWN").strip().upper()
    if kind not in {"LLM", "CHAIN", "AGENT"}:
        return False
    extracted = extract_user_prompt(str(input_text or ""))
    return is_skill_shaped(extracted)


def is_deterministic_source_span(span_kind: object, input_text: object) -> bool:
    """True when this span feeds skill→deterministic (Rung 2), not prompt→skill.

    Includes TOOL/RETRIEVER spans, deterministic-shaped payloads, and LLM spans
    that are not clean user asks (analysis / tool-router blobs). Turn-root
    CHAIN/AGENT asks are excluded here so they stay on Rung 1.
    """
    kind = str(span_kind or "UNKNOWN").strip().upper()
    raw = str(input_text or "").strip()
    if kind in {"TOOL", "RETRIEVER"}:
        return bool(raw) or kind == "TOOL"
    if not raw:
        return False
    if kind in {"CHAIN", "AGENT"} and is_user_ask_span(kind, raw):
        return False
    if is_deterministic_shaped(raw):
        return True
    if kind == "LLM" and not is_user_ask_span(kind, raw):
        return True
    return False


def filter_user_ask_spans(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Rows for prompt→skill: one skill-shaped ask per Phoenix session turn.

    Collapses each ``trace_id`` to its turn root (``agent_request`` / CHAIN),
    then keeps roots whose extracted input is skill-shaped. Nested
    thinking/tool/LLM spans inside the same turn are excluded.
    """
    if spans_df is None or spans_df.empty:
        return spans_df if spans_df is not None else pd.DataFrame()
    if "input_text" not in spans_df.columns:
        return spans_df.iloc[0:0].copy()
    roots = turn_root_spans(spans_df)
    if roots.empty:
        return roots
    kinds = (
        roots["span_kind"]
        if "span_kind" in roots.columns
        else pd.Series(["UNKNOWN"] * len(roots), index=roots.index)
    )
    mask = [
        is_user_ask_span(kind, text)
        for kind, text in zip(kinds, roots["input_text"], strict=False)
    ]
    return roots.loc[mask].copy()


def filter_deterministic_source_spans(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Rows that belong on the skill→deterministic path."""
    if spans_df is None or spans_df.empty:
        return spans_df if spans_df is not None else pd.DataFrame()
    if "input_text" not in spans_df.columns:
        return spans_df.iloc[0:0].copy()
    kinds = (
        spans_df["span_kind"]
        if "span_kind" in spans_df.columns
        else pd.Series(["UNKNOWN"] * len(spans_df), index=spans_df.index)
    )
    mask = [
        is_deterministic_source_span(kind, text)
        for kind, text in zip(kinds, spans_df["input_text"], strict=False)
    ]
    return spans_df.loc[mask].copy()


def expand_cluster_trace_members(
    in_scope: pd.DataFrame, span_ids: tuple[str, ...] | list[str]
) -> pd.DataFrame:
    """Member spans for Rung-2 scoring: direct hits plus same-trace companions.

    TOOL/MCP clusters often only contain the tool span; determinism still needs
    sibling LLM outputs on the same ``trace_id``.
    """
    if in_scope is None or in_scope.empty or "span_id" not in in_scope.columns:
        return in_scope if in_scope is not None else pd.DataFrame()
    wanted = {str(s) for s in span_ids}
    if not wanted:
        return in_scope.iloc[0:0].copy()
    direct = in_scope[in_scope["span_id"].astype(str).isin(wanted)]
    if direct.empty or "trace_id" not in in_scope.columns:
        return direct.copy()
    traces = {
        str(t) for t in direct["trace_id"].dropna().tolist() if str(t).strip()
    }
    if not traces:
        return direct.copy()
    return in_scope[in_scope["trace_id"].astype(str).isin(traces)].copy()


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
