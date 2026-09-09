#!/usr/bin/env python3
"""Answer "is it pulling, and what is it filtering on?" from the store itself.

    cd backend && python scripts/diagnose_scrape.py

Read-only. Prints, in order: which code is loaded, the settings actually in
effect, what the store holds, and — per capability — the funnel from every span
down to the ones the run would analyse, so the stage that drops to zero is
visible instead of being inferred from an empty screen.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "src"))

from phoenix_scraper.capability import (  # noqa: E402
    capability_query_filters,
    load_all_capabilities,
)
from phoenix_scraper.config import load_settings  # noqa: E402
from phoenix_scraper.models import QueryFilters  # noqa: E402
from phoenix_scraper.phoenix_client import PhoenixClientWrapper  # noqa: E402
from phoenix_scraper.storage import Store  # noqa: E402

FILTER_COLUMNS = ("project", "workflow_stage", "asset_class", "span_kind", "model_name")


def rule(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> int:
    rule("1. code")
    has_new = (BACKEND / "src/phoenix_scraper/logging_setup.py").is_file()
    print(f"  logging_setup.py present : {has_new}")
    if not has_new:
        print("  -> this is the OLD code. git pull && reinstall before reading on.")

    settings = load_settings()
    rule("2. settings in effect")
    print(f"  endpoint     : {settings.phoenix_endpoint or '(UNSET)'}")
    print(f"  project      : {settings.project!r}")
    print(f"  db_path      : {Path(settings.db_path).resolve()}")
    print(f"  scrape_limit : {settings.scrape_limit}")
    print(f"  http_timeout : {settings.http_timeout}")
    print(f"  log_level    : {getattr(settings, 'log_level', '(old code)')}")
    print(f"  stage_attr   : {settings.stage_attr_keys() or '(none — using built-ins)'}")
    print(f"  asset_attr   : {settings.asset_attr_keys() or '(none — using built-ins)'}")

    client = PhoenixClientWrapper(settings)
    reason = client.unavailable_reason() if has_new else (
        None if client.available() else "not available"
    )
    print(f"  phoenix      : {'REACHABLE (configured)' if reason is None else reason}")

    rule("3. what the store holds")
    with Store(settings.db_path) as store:
        total = store.span_count()
        print(f"  spans stored : {total}")
        if not total:
            print("  -> nothing has ever been scraped into this database.")
            return 0

        conn = store._conn  # noqa: SLF001 — read-only diagnostic
        lo, hi = conn.execute(
            "SELECT MIN(start_time), MAX(start_time) FROM spans"
        ).fetchone()
        print(f"  time range   : {lo}  ..  {hi}")
        n_text = conn.execute(
            "SELECT COUNT(*) FROM spans WHERE input_text IS NOT NULL AND input_text != ''"
        ).fetchone()[0]
        print(f"  with a prompt: {n_text}  (clustering ignores the other {total - n_text})")

        for col in FILTER_COLUMNS:
            rows = conn.execute(
                f"SELECT COALESCE({col}, '(NULL)') v, COUNT(*) n FROM spans "
                f"GROUP BY 1 ORDER BY n DESC LIMIT 8"
            ).fetchall()
            shown = ", ".join(f"{r['v']}={r['n']}" for r in rows)
            print(f"  {col:<13}: {shown}")

        rule("4. per-capability funnel")
        caps = load_all_capabilities(settings.capabilities_dir)
        if not caps:
            print(f"  no capabilities under {settings.capabilities_dir.resolve()}")
            return 0
        now = datetime.now(UTC)
        for cap in caps:
            start = now - timedelta(days=cap.window_days)
            print(f"\n  {cap.id}  (status={cap.status}, window={cap.window_days}d)")
            active = {
                k: v for k, v in cap.filter.model_dump().items()
                if (len(v) if isinstance(v, (list, tuple)) else v)
            }
            print(f"    filter: {active or 'none (all spans)'}")
            print("    every clause below is AND-ed, and text columns use exact '='")

            # Add one clause at a time so the one that zeroes it out is obvious.
            steps: list[tuple[str, QueryFilters]] = [
                ("all spans", QueryFilters(limit=1_000_000)),
                (f"+ window (last {cap.window_days}d)",
                 QueryFilters(start=start, end=now, limit=1_000_000)),
            ]
            running = {"start": start, "end": now, "limit": 1_000_000}
            for field in ("project", "workflow_stage", "asset_class", "model_name"):
                value = getattr(cap.filter, field)
                if value:
                    running[field] = value
                    steps.append((f"+ {field}={value!r}", QueryFilters(**running)))
            if cap.filter.search:
                running["search"] = cap.filter.search
                steps.append((f"+ search~{cap.filter.search!r}", QueryFilters(**running)))
            if cap.filter.search_any:
                running["search_any"] = tuple(cap.filter.search_any)
                steps.append((
                    f"+ search_any~{list(cap.filter.search_any)}", QueryFilters(**running)
                ))

            for label, qf in steps:
                print(f"      {len(store.spans_frame(qf)):>7}  {label}")

            final = store.spans_frame(
                capability_query_filters(cap, start=start, end=now, limit=1_000_000)
            )
            if final.empty:
                print("      -> 0 in scope: the last clause above that dropped to 0 is why.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
