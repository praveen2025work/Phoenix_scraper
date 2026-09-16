"""Flatten OpenInference span rows into SpanRecords and pull them into the store."""

import json
import logging
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings
from .llm_messages import prefer_messages_io
from .models import ScrapeReport, SpanRecord
from .normalize import format_user_text
from .phoenix_client import PhoenixClientWrapper
from .storage import Store
from .turns import span_records_from_session_turns

logger = logging.getLogger(__name__)

_ATTR_PREFIX = "attributes."


def flatten_phoenix_row(
    row: dict,
    project: str,
    *,
    stage_keys: Sequence[str] = (),
    asset_keys: Sequence[str] = (),
) -> SpanRecord | None:
    """Map one Phoenix row (flattened columns OR nested attribute dicts) to a SpanRecord.

    `stage_keys` / `asset_keys` are checked before the built-in STAGE_KEYS /
    ASSET_KEYS, so PHEONIX_STAGE_ATTR can point at a name this code never
    guessed. Returns None when span_id, trace_id, or start_time is
    missing/unparseable.
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
    parent_id = _text(
        _first(flat, "parent_id", "attributes.parent_id", "context.parent_id")
    ) or None
    attributes = _attributes_dict(row)
    # Prefer OpenInference llm.*_messages over raw input/output.value blobs.
    input_text, output_text = prefer_messages_io(
        attributes=attributes,
        input_value=_text_value(_first(flat, "attributes.input.value")),
        output_value=_text_value(_first(flat, "attributes.output.value")),
    )
    # Flattened message columns may live only on the row, not nested attributes.
    if not input_text or not output_text:
        flat_msgs_in, flat_msgs_out = prefer_messages_io(attributes=flat)
        input_text = input_text or flat_msgs_in
        output_text = output_text or flat_msgs_out
    # Escaped \\n → real breaks; extract typed ask when wrappers wrap USER QUERY.
    if input_text:
        from .prompt_shape import extract_user_prompt

        input_text = extract_user_prompt(input_text)
    if output_text:
        output_text = format_user_text(output_text)
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
        workflow_stage=_text(_first(flat, *stage_keys, *STAGE_KEYS)),
        asset_class=_text(_first(flat, *asset_keys, *ASSET_KEYS)),
        input_text=input_text,
        output_text=output_text,
        prompt_template=_text(_first(flat, "attributes.llm.prompt_template.template")),
        tokens_prompt=_int(_first(flat, "attributes.llm.token_count.prompt")),
        tokens_completion=_int(_first(flat, "attributes.llm.token_count.completion")),
        tokens_total=_int(_first(flat, "attributes.llm.token_count.total")),
        cost_usd=_num(_first(flat, "attributes.llm.cost.total")),
        attributes=attributes,
        parent_id=parent_id,
    )


def scrape_once(
    store: Store,
    client: PhoenixClientWrapper,
    settings: Settings,
    since: datetime | None = None,
    until: datetime | None = None,
    ignore_watermark: bool = False,
) -> ScrapeReport:
    """One incremental pull from Phoenix with watermark + overlap dedup semantics.

    `since` bounds the FIRST pull only (no watermark yet) so huge projects don't
    require a full-history scan; once a watermark exists it takes precedence.

    `ignore_watermark` opts out of that for a deliberate back-fill of `since`..`until`.
    The watermark only ever moves forward (see below), so pulling an old window can
    never rewind it — without this flag an older window is simply unreachable, because
    the watermark pins every pull after the first to "newer than what we already hold".
    """
    source_key = f"phoenix:{settings.project}"
    watermark_before = _ensure_utc(store.get_watermark(source_key))
    if ignore_watermark or watermark_before is None:
        start = _ensure_utc(since)
    else:
        start = watermark_before - timedelta(minutes=settings.scrape_overlap_minutes)
    rows, truncated = _fetch_window(client, settings, start, _ensure_utc(until))
    records = []
    dropped = 0
    for row in rows:
        record = flatten_phoenix_row(
            row, settings.project,
            stage_keys=settings.stage_attr_keys(),
            asset_keys=settings.asset_attr_keys(),
        )
        if record is None:
            # Unreadable, not a duplicate: no span_id, trace_id or start_time.
            dropped += 1
            logger.debug("dropped an unreadable Phoenix row: %.200s", row)
        else:
            records.append(record)
    inserted = store.upsert_spans(records)
    duplicates = len(records) - inserted

    turn_inserted = _enrich_session_turns(
        store, client, settings.project, records
    )
    root_inserted = _enrich_root_spans(
        store, client, settings, start, _ensure_utc(until)
    )
    if turn_inserted or root_inserted:
        inserted += turn_inserted + root_inserted
        logger.info(
            "turn enrichment for %s: session_turns=%d root_query=%d",
            settings.project, turn_inserted, root_inserted,
        )

    logger.info(
        "scrape %s: pulled %d, inserted %d, duplicates %d, unreadable %d%s",
        settings.project, len(rows), inserted, duplicates, dropped,
        " (TRUNCATED — Phoenix holds more)" if truncated else "",
    )
    if dropped:
        logger.warning(
            "%d of %d rows from %s had no span_id/trace_id/start_time and were "
            "discarded — run at DEBUG to see them",
            dropped, len(rows), settings.project,
        )

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
        dropped=dropped,
        duplicates=duplicates,
        watermark_before=watermark_before,
        watermark_after=watermark_after,
        truncated=truncated,
    )


def _enrich_session_turns(
    store: Store,
    client: PhoenixClientWrapper,
    project: str,
    records: list[SpanRecord],
) -> int:
    """Pull Phoenix session turns and upsert turn-root spans (agent_request IO).

    Best-effort: session APIs need Phoenix >= 13.5; failures log and return 0 so
    span scrape still succeeds. Offline analysis still derives turns from spans.
    """
    session_ids = sorted(
        {
            (r.session_id or "").strip()
            for r in records
            if (r.session_id or "").strip()
        }
    )
    if not session_ids:
        # Spans may omit session.id; fall back to listing recent project sessions.
        try:
            listed = client.list_project_sessions(project, limit=50)
        except Exception as exc:  # noqa: BLE001
            logger.info("session list skipped for %s: %s", project, exc)
            return 0
        for row in listed:
            sid = str(row.get("session_id") or row.get("id") or "").strip()
            if sid:
                session_ids.append(sid)
        session_ids = sorted(set(session_ids))
    if not session_ids:
        return 0

    # Cap enrichment so a huge project cannot explode the scrape.
    session_ids = session_ids[:100]
    turn_records: list[SpanRecord] = []
    for session_id in session_ids:
        try:
            turns = client.fetch_session_turns(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "session turns skipped for %s/%s: %s", project, session_id, exc
            )
            continue
        if not turns:
            continue
        user_id = next(
            (r.user_id for r in records if r.session_id == session_id and r.user_id),
            None,
        )
        turn_records.extend(
            span_records_from_session_turns(
                turns, project=project, session_id=session_id, user_id=user_id
            )
        )
    if not turn_records:
        return 0
    return store.upsert_spans_refresh(turn_records)


def _enrich_root_spans(
    store: Store,
    client: PhoenixClientWrapper,
    settings: Settings,
    start: datetime | None,
    end: datetime | None,
) -> int:
    """SpanQuery ``parent_id is None`` so turn roots survive truncated scrapes."""
    try:
        frame = client.fetch_root_spans(
            settings.project, start, end, settings.scrape_limit
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("root span query skipped for %s: %s", settings.project, exc)
        return 0
    rows = _frame_rows(frame)
    records: list[SpanRecord] = []
    for row in rows:
        record = flatten_phoenix_row(
            row,
            settings.project,
            stage_keys=settings.stage_attr_keys(),
            asset_keys=settings.asset_attr_keys(),
        )
        if record is not None:
            records.append(record)
    if not records:
        return 0
    return store.upsert_spans_refresh(records)


def _fetch_window(
    client: PhoenixClientWrapper,
    settings: Settings,
    start: datetime | None,
    end: datetime | None,
    depth: int = 0,
) -> tuple[list[dict], bool]:
    """Rows for [start, end], halving the window whenever a pull comes back full.

    `get_spans_dataframe` caps at `limit` and offers no cursor, so a page that is
    exactly `limit` long means Phoenix had more to give and the extras are simply
    lost. Asking for two narrower windows is the only way to reach them. Returns
    (rows, truncated); truncated is True only when a full page could NOT be split
    — an open-ended window, or the depth cap.
    """
    frame = client.fetch_spans(
        project=settings.project, start=start, end=end, limit=settings.scrape_limit
    )
    rows = _frame_rows(frame)
    # INFO (not DEBUG): operators watching a long Jun–Aug backfill need to see
    # depth climb and know it is intentional window-halving, not a stuck loop.
    logger.info(
        "slice depth=%d project=%s %s..%s -> %d rows (limit %d)",
        depth, settings.project, start, end, len(rows), settings.scrape_limit,
    )
    if len(rows) < settings.scrape_limit:
        return rows, False
    if start is None or end is None or depth >= settings.scrape_max_subdivisions:
        logger.warning(
            "Phoenix returned a full page of %d spans for %s..%s and it cannot be "
            "narrowed further (depth %d/%d); some spans were NOT scraped. Raise "
            "PHEONIX_SCRAPE_LIMIT (currently %d) — one bigger page beats many small "
            "ones — or PHEONIX_SCRAPE_MAX_SUBDIVISIONS, or run a shorter window.",
            len(rows), start, end, depth, settings.scrape_max_subdivisions,
            settings.scrape_limit,
        )
        return rows, True
    mid = start + (end - start) / 2
    if mid <= start or mid >= end:  # window too small to halve
        return rows, True
    left, left_cut = _fetch_window(client, settings, start, mid, depth + 1)
    right, right_cut = _fetch_window(client, settings, mid, end, depth + 1)
    return left + right, left_cut or right_cut


def ingest_jsonl(
    store: Store,
    path: Path,
    project: str,
    *,
    stage_keys: Sequence[str] = (),
    asset_keys: Sequence[str] = (),
) -> ScrapeReport:
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
        record = flatten_phoenix_row(
            raw, project, stage_keys=stage_keys, asset_keys=asset_keys
        )
        if record is None:
            logger.warning("%s:%d skipped — missing span_id/trace_id/start_time", path, line_no)
            continue
        records.append(record)
    inserted = store.upsert_spans(records)
    return ScrapeReport(
        source="jsonl", pulled=pulled, inserted=inserted, skipped=pulled - inserted
    )


# ---- helpers -----------------------------------------------------------------
def _candidates(names: tuple[str, ...]) -> tuple[str, ...]:
    """Every place a custom field realistically lands, canonical name first.

    OpenInference puts user fields under `attributes.metadata.`; some SDKs set
    them flat on `attributes.`; a JSONL export can carry a bare column. Reading
    exactly one key silently drops data the agent already emits, so try them all
    — this only ever finds a value that is really there, it never invents one.
    """
    return tuple(f"{prefix}{name}" for name in names for prefix in _ATTR_LOOKUP_PREFIXES)


_ATTR_LOOKUP_PREFIXES = ("attributes.metadata.", "attributes.", "metadata.", "")
STAGE_KEYS = _candidates(("workflow_stage", "workflowStage", "stage"))
ASSET_KEYS = _candidates(("asset_class", "assetClass"))


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
    # get_spans_dataframe indexes on context.span_id; recover it as a column —
    # unless the response also kept it as a column, where reset_index() would
    # raise "cannot insert ..., already exists".
    if frame.index.name:
        frame = frame.reset_index(drop=frame.index.name in frame.columns)
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
