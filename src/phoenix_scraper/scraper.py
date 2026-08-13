"""Flatten OpenInference span rows into SpanRecords and pull them into the store."""

import json
import logging
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings
from .models import ScrapeReport, SpanRecord
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

logger = logging.getLogger(__name__)

_ATTR_PREFIX = "attributes."


def flatten_phoenix_row(row: dict, project: str) -> SpanRecord | None:
    """Map one Phoenix row (flattened columns OR nested attribute dicts) to a SpanRecord.

    Returns None when span_id, trace_id, or start_time is missing/unparseable.
    """
    flat = _flatten_keys(row)
    span_id = _text(_first(flat, "context.span_id", "span_id"))
    trace_id = _text(_first(flat, "context.trace_id", "trace_id"))
    start_time = _parse_dt(_first(flat, "start_time"))
    if not span_id or not trace_id or start_time is None:
        return None

    end_time = _parse_dt(_first(flat, "end_time"))
    latency_ms = _num(_first(flat, "latency_ms"))
    if latency_ms is None and end_time is not None:
        latency_ms = (end_time - start_time).total_seconds() * 1000.0

    kind = _text(_first(flat, "attributes.openinference.span.kind", "span_kind"))
    return SpanRecord(
        span_id=span_id,
        trace_id=trace_id,
        session_id=_text(_first(flat, "attributes.session.id")),
        project=project,
        name=_text(_first(flat, "name")) or "",
        span_kind=kind.upper() if kind else "UNKNOWN",
        start_time=start_time,
        end_time=end_time,
        latency_ms=latency_ms,
        status_code=_text(_first(flat, "status_code")) or "OK",
        model_name=_text(_first(flat, "attributes.llm.model_name")),
        user_id=_text(_first(flat, "attributes.user.id")),
        workflow_stage=_text(_first(flat, "attributes.metadata.workflow_stage")),
        asset_class=_text(_first(flat, "attributes.metadata.asset_class")),
        input_text=_text_value(_first(flat, "attributes.input.value")),
        output_text=_text_value(_first(flat, "attributes.output.value")),
        prompt_template=_text(_first(flat, "attributes.llm.prompt_template.template")),
        tokens_prompt=_int(_first(flat, "attributes.llm.token_count.prompt")),
        tokens_completion=_int(_first(flat, "attributes.llm.token_count.completion")),
        tokens_total=_int(_first(flat, "attributes.llm.token_count.total")),
        cost_usd=_num(_first(flat, "attributes.llm.cost.total")),
        attributes=_attributes_dict(row),
    )


def scrape_once(
    store: Store,
    client: PhoenixClientWrapper,
    settings: Settings,
    since: datetime | None = None,
) -> ScrapeReport:
    """One incremental pull from Phoenix with watermark + overlap dedup semantics.

    `since` bounds the FIRST pull only (no watermark yet) so huge projects don't
    require a full-history scan; once a watermark exists it takes precedence.
    """
    source_key = f"phoenix:{settings.project}"
    watermark_before = _ensure_utc(store.get_watermark(source_key))
    start = (
        watermark_before - timedelta(minutes=settings.scrape_overlap_minutes)
        if watermark_before is not None
        else _ensure_utc(since)
    )
    frame = client.fetch_spans(
        project=settings.project, start=start, end=None, limit=settings.scrape_limit
    )
    rows = _frame_rows(frame)
    records = [
        record
        for record in (flatten_phoenix_row(row, settings.project) for row in rows)
        if record is not None
    ]
    inserted = store.upsert_spans(records)

    latest = max((r.start_time for r in records), default=None)
    watermark_after = watermark_before
    if latest is not None and (watermark_before is None or latest > watermark_before):
        store.set_watermark(source_key, latest)
        watermark_after = latest
    return ScrapeReport(
        source="live",
        pulled=len(rows),
        inserted=inserted,
        skipped=len(rows) - inserted,
        watermark_before=watermark_before,
        watermark_after=watermark_after,
    )


def ingest_jsonl(store: Store, path: Path, project: str) -> ScrapeReport:
    """Offline ingestion: one JSON span object per line -> flatten -> upsert."""
    records: list[SpanRecord] = []
    pulled = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        pulled += 1
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("%s:%d skipped — invalid JSON (%s)", path, line_no, exc)
            continue
        if not isinstance(raw, dict):
            logger.warning("%s:%d skipped — expected a JSON object", path, line_no)
            continue
        record = flatten_phoenix_row(raw, project)
        if record is None:
            logger.warning("%s:%d skipped — missing span_id/trace_id/start_time", path, line_no)
            continue
        records.append(record)
    inserted = store.upsert_spans(records)
    return ScrapeReport(
        source="jsonl", pulled=pulled, inserted=inserted, skipped=pulled - inserted
    )


# ---- helpers -----------------------------------------------------------------
def _flatten_keys(data: dict, prefix: str = "") -> dict[str, Any]:
    """Dotted-key view of a possibly nested dict; dict values also kept whole."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, dict):
            out[full] = value
            out.update(_flatten_keys(value, f"{full}."))
        else:
            out[full] = value
    return out


def _frame_rows(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    # get_spans_dataframe indexes on context.span_id; recover it as a column.
    if frame.index.name:
        frame = frame.reset_index()
    return frame.to_dict("records")


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _first(flat: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = flat.get(key)
        if not _is_missing(value):
            return value
    return None


def _text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _text_value(value: Any) -> str:
    """input.value / output.value as text; structured payloads are JSON-encoded."""
    if _is_missing(value):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return _ensure_utc(value)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _attributes_dict(row: dict) -> dict[str, Any]:
    raw = row.get("attributes")
    if isinstance(raw, dict):
        return dict(raw)
    return {
        key[len(_ATTR_PREFIX):]: value
        for key, value in row.items()
        if isinstance(key, str) and key.startswith(_ATTR_PREFIX) and not _is_missing(value)
    }
