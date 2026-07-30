"""Deterministic synthetic P&L-agent traffic for the offline demo.

Analyst sessions across asset classes and workflow stages, with a frequency-skewed
prompt distribution: ~10 hot templates instantiated with varying numbers/dates/books
(so normalization collapses them) plus a long tail of one-off prompts, a few of which
deliberately match no catalog skill (gap-proposal bait).
"""

import random
from datetime import UTC, datetime, timedelta

from .models import ScrapeReport, SpanRecord
from .storage import Store

PROJECT_DEFAULT = "pnl-agent"

ANALYSTS: tuple[str, ...] = (
    "analyst-priya", "analyst-marcus", "analyst-wei", "analyst-sofia",
    "analyst-diego", "analyst-amara", "analyst-tomasz", "analyst-hana",
)

ASSET_CLASSES: tuple[str, ...] = ("fx", "rates", "equities", "credit")

STAGES: tuple[str, ...] = (
    "fobo_recon", "plex", "flash_vs_formal", "adjustments", "commentary_signoff",
)

HOT_TEMPLATES: tuple[str, ...] = (
    "Why is there an {ac} recon break of {n}k on {book}?",
    "Draft sign-off commentary for the {desk} desk",
    "Show flash vs formal variance for {date}",
    "Suggest an adjustment for the {issue}",
    "Run PLEX attribution for {desk}",
    "Explain the top PLEX drivers for {desk} on {date}",
    "List unmatched FOBO trades over {n}k for {book}",
    "Post an adjustment of {n}k to {book} for the {issue}",
    "Summarise flash vs formal breaks above {n}k for {date}",
    "Is the {desk} desk ready for sign-off on {date}?",
)

_TEMPLATE_STAGES: dict[str, str] = {
    HOT_TEMPLATES[0]: "fobo_recon",
    HOT_TEMPLATES[1]: "commentary_signoff",
    HOT_TEMPLATES[2]: "flash_vs_formal",
    HOT_TEMPLATES[3]: "adjustments",
    HOT_TEMPLATES[4]: "plex",
    HOT_TEMPLATES[5]: "plex",
    HOT_TEMPLATES[6]: "fobo_recon",
    HOT_TEMPLATES[7]: "adjustments",
    HOT_TEMPLATES[8]: "flash_vs_formal",
    HOT_TEMPLATES[9]: "commentary_signoff",
}

# Zipf-ish frequency skew across the hot templates (aligned by index).
_HOT_WEIGHTS: tuple[int, ...] = (10, 8, 7, 6, 5, 4, 4, 3, 3, 2)
_HOT_FLOOR = 8  # every hot template repeats at least this often (when volume allows)

LONG_TAIL_PROMPTS: tuple[str, ...] = (
    "Translate this recon summary into French for the Paris controllers",
    "Translate the month-end sign-off note into Japanese",
    "Email this variance summary to my manager",
    "Email the adjustments log to the EMEA product control team",
    "What is the difference between clean and dirty P&L?",
    "Walk me through how PLEX decomposes carry and roll-down",
    "Which trades drove the overnight theta bleed on the vol book?",
    "Set up a recurring report of the top ten recon breaks every morning",
    "How do I escalate a stale price on an illiquid corporate bond?",
    "Compare today's new-deal P&L against the desk's monthly average",
    "Why does the flash number exclude the late Tokyo trades?",
    "Generate a checklist for quarter-end sign-off",
    "Show me the FX forward points used in yesterday's revaluation",
    "Which curves were rebuilt after the ECB announcement?",
    "Summarise the impact of the index roll on the credit book",
    "What was the funding cost charged to the equities desk this week?",
    "Find any adjustments older than thirty days that are still open",
    "Who approved the manual mark on the distressed bond position?",
    "Explain the residual between front office and back office cash balances",
    "Draft an explanation of basis risk for the new joiner on the desk",
    "How is the day-one P&L reserve released over time?",
    "Reconcile the dividend forecast against the custodian feed",
    "What FX rate source do we use for the Turkish lira?",
    "List the books that missed the flash cut-off yesterday",
    "Can you pull the intraday P&L snapshot from ten thirty?",
    "What changed in the pricing model for callable bonds this release?",
    "Order lunch for the month-end close team",
    "Remind me to call the Singapore controller at five",
)

_AC_LABELS: dict[str, str] = {
    "fx": "FX", "rates": "rates", "equities": "equity", "credit": "credit",
}
_DESKS: dict[str, str] = {
    "fx": "FX", "rates": "rates", "equities": "equities", "credit": "credit",
}
_BOOKS: dict[str, tuple[str, ...]] = {
    "fx": ("EURUSD_LDN", "USDJPY_NY", "GBPUSD_LDN"),
    "rates": ("IRS_USD_NY", "GILTS_LDN", "BUNDS_FFT"),
    "equities": ("EQ_DELTA1_NY", "EQ_VOL_LDN", "EQ_INDEX_HK"),
    "credit": ("CDS_IG_NY", "BONDS_EM_LDN", "CLO_WH_NY"),
}
_ISSUES: tuple[str, ...] = (
    "stale FX fixing on the London book",
    "duplicated ticket in the back office ledger",
    "missed dividend accrual",
    "late booked novation",
    "wrong day-count on the swap leg",
)
_AMOUNTS: tuple[int, ...] = (25, 40, 75, 120, 150, 210, 300, 480, 620, 850)

_STAGE_TOOLS: dict[str, str] = {
    "fobo_recon": "recon_break_query",
    "plex": "plex_attribution_runner",
    "flash_vs_formal": "variance_report_fetcher",
    "adjustments": "adjustment_poster",
    "commentary_signoff": "commentary_drafter",
}
_STAGE_OUTPUTS: dict[str, str] = {
    "fobo_recon": "The break traces to an unsettled trade awaiting confirmation.",
    "plex": "Attribution complete: carry and new-deal P&L dominate the move.",
    "flash_vs_formal": "Variance driven by late marks applied after the flash cut.",
    "adjustments": "Proposed adjustment drafted and routed for approval.",
    "commentary_signoff": "Commentary drafted; figures reconcile to the formal ledger.",
}

_MODEL_SONNET = "us.anthropic.claude-sonnet-4-6"
_MODEL_HAIKU = "us.anthropic.claude-haiku-4-5"
_CHILD_SPAN_RATE = 0.30
_HAIKU_RATE = 0.20
_LOOKBACK_HOURS = 13 * 24  # keep every span strictly inside the last 14 days


def _allocate_hot(n_hot: int, rng: random.Random) -> list[int]:
    """Split n_hot draws across hot templates by skewed weight, honouring the floor."""
    total_w = sum(_HOT_WEIGHTS)
    counts = [n_hot * w // total_w for w in _HOT_WEIGHTS]
    order = list(range(len(_HOT_WEIGHTS)))
    rng.shuffle(order)
    for i in order[: n_hot - sum(counts)]:
        counts[i] += 1
    floor = _HOT_FLOOR if n_hot >= _HOT_FLOOR * len(_HOT_WEIGHTS) else 0
    for i in range(len(counts)):
        while counts[i] < floor:
            donor = max(range(len(counts)), key=lambda k: counts[k])
            counts[donor] -= 1
            counts[i] += 1
    return counts


def _fill_template(
    template: str, asset_class: str, base: datetime, rng: random.Random
) -> str:
    date = (base - timedelta(days=rng.randint(0, 13))).date().isoformat()
    return template.format(
        ac=_AC_LABELS[asset_class],
        n=rng.choice(_AMOUNTS),
        book=rng.choice(_BOOKS[asset_class]),
        desk=_DESKS[asset_class],
        date=date,
        issue=rng.choice(_ISSUES),
    )


def _build_prompt_plan(
    turns_per_session: list[int], rng: random.Random
) -> list[tuple[str | None, str]]:
    """One (template_or_None, stage) entry per user turn, shuffled deterministically."""
    total_turns = sum(turns_per_session)
    n_tail = min(len(LONG_TAIL_PROMPTS), total_turns // 8)
    hot_counts = _allocate_hot(total_turns - n_tail, rng)
    plan: list[tuple[str | None, str]] = [
        (template, _TEMPLATE_STAGES[template])
        for template, count in zip(HOT_TEMPLATES, hot_counts, strict=True)
        for _ in range(count)
    ]
    plan.extend((None, rng.choice(STAGES)) for _ in range(n_tail))
    rng.shuffle(plan)
    return plan


def generate_fixture_spans(
    n_sessions: int = 60, seed: int = 42, project: str = PROJECT_DEFAULT
) -> list[SpanRecord]:
    rng = random.Random(seed)
    base = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    turns_per_session = [rng.randint(3, 6) for _ in range(n_sessions)]
    plan = _build_prompt_plan(turns_per_session, rng)
    tail_texts = list(LONG_TAIL_PROMPTS)
    rng.shuffle(tail_texts)

    spans: list[SpanRecord] = []
    turn_index = 0
    for s in range(n_sessions):
        session_id = f"fixture-sess-{s:03d}"
        user_id = rng.choice(ANALYSTS)
        asset_class = ASSET_CLASSES[s % len(ASSET_CLASSES)]
        cursor = base - timedelta(
            hours=rng.randint(2, _LOOKBACK_HOURS), minutes=rng.randint(0, 59)
        )
        for t in range(turns_per_session[s]):
            template, stage = plan[turn_index]
            if template is not None:
                text = _fill_template(template, asset_class, base, rng)
            else:
                text = tail_texts.pop()
            cursor += timedelta(minutes=rng.randint(2, 7), seconds=rng.randint(0, 59))
            spans.extend(
                _turn_spans(
                    rng=rng, project=project, session_id=session_id, user_id=user_id,
                    asset_class=asset_class, stage=stage, template=template,
                    text=text, start=cursor, session_idx=s, turn_idx=t,
                )
            )
            turn_index += 1
    return spans


def _turn_spans(
    *, rng: random.Random, project: str, session_id: str, user_id: str,
    asset_class: str, stage: str, template: str | None, text: str,
    start: datetime, session_idx: int, turn_idx: int,
) -> list[SpanRecord]:
    """Spans emitted by one user turn: an LLM span plus optional AGENT+TOOL children."""
    trace_id = f"fixture-trace-{session_idx:03d}-{turn_idx:02d}"
    prefix = f"fixture-{session_idx:03d}-{turn_idx:02d}"
    tokens_prompt = rng.randint(180, 900)
    tokens_completion = rng.randint(60, 420)
    latency_ms = round(rng.uniform(900.0, 6500.0), 1)
    common = dict(
        trace_id=trace_id, session_id=session_id, project=project,
        user_id=user_id, workflow_stage=stage, asset_class=asset_class,
    )
    turn: list[SpanRecord] = [
        SpanRecord(
            span_id=f"{prefix}-llm",
            name="llm-call",
            span_kind="LLM",
            start_time=start,
            end_time=start + timedelta(milliseconds=latency_ms),
            latency_ms=latency_ms,
            model_name=_MODEL_HAIKU if rng.random() < _HAIKU_RATE else _MODEL_SONNET,
            input_text=text,
            output_text=_STAGE_OUTPUTS[stage],
            prompt_template=template,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tokens_total=tokens_prompt + tokens_completion,
            cost_usd=None,
            attributes={"llm.provider": "aws.bedrock"},
            **common,
        )
    ]
    if rng.random() < _CHILD_SPAN_RATE:
        agent_start = start + timedelta(milliseconds=rng.randint(50, 400))
        agent_latency = round(rng.uniform(200.0, 1500.0), 1)
        tool_start = agent_start + timedelta(milliseconds=rng.randint(20, 150))
        tool_latency = round(rng.uniform(80.0, 1200.0), 1)
        turn.append(
            SpanRecord(
                span_id=f"{prefix}-agent",
                name="pnl-agent-step",
                span_kind="AGENT",
                start_time=agent_start,
                end_time=agent_start + timedelta(milliseconds=agent_latency),
                latency_ms=agent_latency,
                attributes={"agent.stage": stage},
                **common,
            )
        )
        turn.append(
            SpanRecord(
                span_id=f"{prefix}-tool",
                name=_STAGE_TOOLS[stage],
                span_kind="TOOL",
                start_time=tool_start,
                end_time=tool_start + timedelta(milliseconds=tool_latency),
                latency_ms=tool_latency,
                attributes={"tool.name": _STAGE_TOOLS[stage]},
                **common,
            )
        )
    return turn


def seed_demo(store: Store, n_sessions: int = 60, seed: int = 42) -> ScrapeReport:
    """Insert deterministic fixture spans into the store; idempotent on re-run."""
    records = generate_fixture_spans(n_sessions=n_sessions, seed=seed)
    watermark_key = f"fixtures:{PROJECT_DEFAULT}"
    watermark_before = store.get_watermark(watermark_key)
    inserted = store.upsert_spans(records)
    watermark_after = watermark_before
    if records:
        latest = max(r.start_time for r in records)
        if watermark_before is None or latest > watermark_before:
            store.set_watermark(watermark_key, latest)
            watermark_after = latest
    return ScrapeReport(
        source="fixtures",
        pulled=len(records),
        inserted=inserted,
        skipped=len(records) - inserted,
        watermark_before=watermark_before,
        watermark_after=watermark_after,
    )
