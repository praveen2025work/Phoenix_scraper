"""Rung 2 of the promotion ladder: how deterministic is this cluster's answer?

Pure and lexical — mask volatile tokens, then measure four things: do the
answers collapse to a few templates (`template_concentration`), does the agent
take the same route every time (`route_invariance`), are the answers similar to
each other (`output_self_similarity`), and does each input phrasing always yield
the same template (`slot_stability`).

Also detects **aggregation happening in the LLM** that should be offloaded to a
deterministic precompute or MCP call (`aggregation_offload_*`). No LLM judge —
a low score is a real "keep the model" answer.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Literal

import pandas as pd
from rapidfuzz import fuzz

from .insights_llm import _flow_signature
from .models import _Frozen
from .normalize import mask_volatile

_ROUTE_KINDS = frozenset({"TOOL", "RETRIEVER", "AGENT", "CHAIN"})
_COVER_TARGET = 0.90
_SELF_SIM_SAMPLE = 200
_SELF_SIM_MAX_PAIRS = 5000

_WEIGHTS = {
    "template_concentration": 0.4,
    "slot_stability": 0.3,
    "output_self_similarity": 0.2,
    "route_invariance": 0.1,
}

# Soft floor for creating an offload-aggregation candidate (vs full rung2_min).
_AGG_CREATION_FLOOR_DIV = 3
_AGG_CREATION_SCORE = 0.55
_AGG_EVIDENCE_SCORE = 0.70

_SQL_AGG_RE = re.compile(
    r"(?is)\b(?:sum|avg|average|count|min|max)\s*\(|\bgroup\s+by\b|\bhaving\b|"
    r"\brollup\b|\bpartition\s+by\b"
)
_NL_AGG_RE = re.compile(
    r"(?i)\b(?:"
    r"aggregat(?:e|es|ed|ion|ing)|"
    r"roll[\s-]?ups?|"
    r"grand\s+totals?|subtotals?|totals?|"
    r"sum(?:med|s)?(?:\s+of|\s+across|\s+by)?|"
    r"count(?:ed|ing|s)?|"
    r"averages?|means?|"
    r"breakdown|"
    r"top\s+\d+|bottom\s+\d+|ranked?\b|"
    r"how\s+many|"
    r"by\s+(?:desk|book|ccy|currency|pair|day|date|bucket)"
    r")\b"
)
_FIGURE_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?\s*[kKmMbB]?")
_SELECT_NO_AGG_RE = re.compile(
    r"(?is)\bselect\b.+\bfrom\b(?!.*\b(?:group\s+by|sum\s*\(|count\s*\(|avg\s*\())"
)
_ROWISH_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]|\d+[\).]|[A-Z]{2,6}\b).{0,80}\d"
)


class DeterminismSignals(_Frozen):
    template_concentration: float
    route_invariance: float | None
    output_self_similarity: float
    slot_stability: float
    n_templates: int
    n_answer_spans: int
    route_applicable: bool
    aggregation_in_llm: bool = False
    aggregation_offload_score: float = 0.0
    aggregation_reasons: tuple[str, ...] = ()
    aggregation_action: Literal["", "precompute_session", "mcp_aggregate"] = ""


class AggregationEvidence(_Frozen):
    """Whether the LLM is aggregating data that should be precomputed / MCP'd."""

    aggregation_in_llm: bool = False
    offload_score: float = 0.0
    reasons: tuple[str, ...] = ()
    recommended_action: Literal["", "precompute_session", "mcp_aggregate"] = ""


def detect_llm_aggregation(member_spans: pd.DataFrame) -> AggregationEvidence:
    """Lexical detection of aggregation work happening inside the LLM.

    A gap when the model is rolling up / summing / ranking from row-level context
    instead of receiving an already-aggregated MCP/SQL result (or session
    precompute). Not a gap when a TOOL already runs GROUP BY / SUM / COUNT.
    """
    if member_spans is None or member_spans.empty:
        return AggregationEvidence()

    kinds = member_spans["span_kind"].fillna("UNKNOWN").astype(str).str.upper()
    llm = member_spans.loc[kinds == "LLM"]
    tools = member_spans.loc[kinds.isin(["TOOL", "RETRIEVER"])]

    llm_outputs = [
        str(t)
        for t in llm.get("output_text", pd.Series(dtype=str)).fillna("").tolist()
        if str(t).strip()
    ]
    llm_inputs = [
        str(t)
        for t in llm.get("input_text", pd.Series(dtype=str)).fillna("").tolist()
        if str(t).strip()
    ]
    tool_payloads = [
        f"{row.get('input_text') or ''}\n{row.get('output_text') or ''}"
        for row in tools.to_dict("records")
    ]

    tool_does_agg = any(_SQL_AGG_RE.search(p) for p in tool_payloads)
    if tool_does_agg and not any(_llm_does_extra_agg(o) for o in llm_outputs):
        # Aggregation already lives in MCP/SQL; LLM is narrating.
        return AggregationEvidence()

    reasons: list[str] = []
    score = 0.0

    out_agg = sum(1 for o in llm_outputs if _looks_like_agg_answer(o))
    if llm_outputs and out_agg / len(llm_outputs) >= 0.35:
        reasons.append("llm_output_aggregates")
        score += 0.35

    in_rows = sum(1 for t in llm_inputs if _looks_like_row_level_data(t))
    if llm_inputs and in_rows / len(llm_inputs) >= 0.25:
        reasons.append("llm_input_has_row_data")
        score += 0.25

    if _tool_rows_llm_rollup(tool_payloads, llm_outputs):
        reasons.append("tool_rows_llm_rollup")
        score += 0.25

    if reasons and not tool_does_agg:
        reasons.append("no_agg_tool_on_trace")
        score += 0.15

    score = min(1.0, round(score, 4))
    if score < 0.35 or not reasons:
        return AggregationEvidence()

    action: Literal["", "precompute_session", "mcp_aggregate"] = (
        "mcp_aggregate" if tool_payloads else "precompute_session"
    )
    return AggregationEvidence(
        aggregation_in_llm=True,
        offload_score=score,
        reasons=tuple(reasons),
        recommended_action=action,
    )


def _looks_like_agg_answer(text: str) -> bool:
    if not _NL_AGG_RE.search(text) and not _SQL_AGG_RE.search(text):
        return False
    return len(_FIGURE_RE.findall(text)) >= 1


def _llm_does_extra_agg(text: str) -> bool:
    """True when the answer still looks like the model computed a rollup."""
    lower = text.casefold()
    return _looks_like_agg_answer(text) and (
        "i calculated" in lower
        or "i summed" in lower
        or "adding up" in lower
        or "across the following rows" in lower
    )


def _looks_like_row_level_data(text: str) -> bool:
    if _SELECT_NO_AGG_RE.search(text):
        return True
    row_lines = _ROWISH_LINE_RE.findall(text)
    if len(row_lines) >= 4:
        return True
    if len(_FIGURE_RE.findall(text)) >= 6 and not _SQL_AGG_RE.search(text):
        return True
    return False


def _tool_rows_llm_rollup(tool_payloads: list[str], llm_outputs: list[str]) -> bool:
    if not tool_payloads or not llm_outputs:
        return False
    big_tools = [
        p for p in tool_payloads if len(p) >= 400 or len(_FIGURE_RE.findall(p)) >= 6
    ]
    if not big_tools:
        return False
    biggest = max(len(p) for p in big_tools)
    short_rollups = [
        o
        for o in llm_outputs
        if _looks_like_agg_answer(o) and len(o) < biggest * 0.6
    ]
    return bool(short_rollups)


def build_templates(answers: list[str], *, fuzz_threshold: int) -> list[tuple[str, int]]:
    """(masked representative, count) per merged template, largest first."""
    groups: dict[str, int] = {}
    for answer in answers:
        masked = mask_volatile(answer)
        groups[masked] = groups.get(masked, 0) + 1
    ordered = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
    templates: list[list] = []  # [representative, count]
    for masked, n in ordered:
        for tmpl in templates:
            if fuzz.token_set_ratio(masked, tmpl[0]) >= fuzz_threshold:
                tmpl[1] += n
                break
        else:
            templates.append([masked, n])
    templates.sort(key=lambda t: -t[1])
    return [(t[0], t[1]) for t in templates]


def template_concentration(answers: list[str], *, fuzz_threshold: int) -> tuple[float, int]:
    if not answers:
        return 0.0, 0
    templates = build_templates(answers, fuzz_threshold=fuzz_threshold)
    total = sum(n for _, n in templates)
    covered = 0
    k = 0
    for _, n in templates:
        covered += n
        k += 1
        if covered / total >= _COVER_TARGET:
            break
    return max(0.0, 1.0 - (k - 1) * 0.25), k


def route_invariance(flows: list[str]) -> float:
    if not flows:
        return 0.0
    counts: dict[str, int] = {}
    for flow in flows:
        counts[flow] = counts.get(flow, 0) + 1
    return max(counts.values()) / len(flows)


def output_self_similarity(
    answers: list[str],
    *,
    sample: int = _SELF_SIM_SAMPLE,
    max_pairs: int = _SELF_SIM_MAX_PAIRS,
) -> float:
    masked = [mask_volatile(a) for a in answers[:sample]]
    if len(masked) < 2:
        return 1.0
    ratios: list[float] = []
    for a, b in combinations(masked, 2):
        ratios.append(fuzz.token_set_ratio(a, b) / 100.0)
        if len(ratios) >= max_pairs:
            break
    return sum(ratios) / len(ratios) if ratios else 1.0


def _template_of(
    masked_answer: str, templates: list[tuple[str, int]], fuzz_threshold: int
) -> str:
    for rep, _ in templates:
        if fuzz.token_set_ratio(masked_answer, rep) >= fuzz_threshold:
            return rep
    return masked_answer


def slot_stability(
    pairs: list[tuple[str, str]],
    templates: list[tuple[str, int]],
    *,
    fuzz_threshold: int,
) -> float:
    if not pairs:
        return 0.0
    by_input: dict[str, list[str]] = {}
    for prompt, answer in pairs:
        key = mask_volatile(prompt)
        by_input.setdefault(key, []).append(
            _template_of(mask_volatile(answer), templates, fuzz_threshold)
        )
    total = 0
    weighted = 0.0
    for tmpls in by_input.values():
        counts: dict[str, int] = {}
        for t in tmpls:
            counts[t] = counts.get(t, 0) + 1
        modal_share = max(counts.values()) / len(tmpls)
        weighted += modal_share * len(tmpls)
        total += len(tmpls)
    return weighted / total if total else 0.0


class Rung2Signal(_Frozen):
    cluster_id: str
    title: str
    signature: str
    matched_skill: str | None
    determinism_score: float
    n_answer_spans: int
    eligible: bool
    signals: DeterminismSignals
    templates: tuple[tuple[str, int], ...] = ()
    met_evidence_bar: bool = False
    subtype: str = ""  # "" | "offload_aggregation"
    aggregation_in_llm: bool = False
    aggregation_offload_score: float = 0.0


def blend_determinism(signals: DeterminismSignals) -> float:
    """Weighted mean over available signals (route dropped + renormalised N/A)."""
    available = {
        "template_concentration": signals.template_concentration,
        "slot_stability": signals.slot_stability,
        "output_self_similarity": signals.output_self_similarity,
    }
    if signals.route_applicable and signals.route_invariance is not None:
        available["route_invariance"] = signals.route_invariance
    num = sum(_WEIGHTS[k] * v for k, v in available.items())
    den = sum(_WEIGHTS[k] for k in available)
    return round(num / den, 4) if den else 0.0


def _flows_for(member_spans: pd.DataFrame) -> tuple[list[str], bool]:
    if member_spans.empty or "trace_id" not in member_spans.columns:
        return [], False
    flows: list[str] = []
    applicable = False
    for _tid, group in member_spans.groupby("trace_id", sort=False):
        ordered = group.sort_values("start_time")
        kinds = list(ordered["span_kind"].fillna("UNKNOWN"))
        flows.append(_flow_signature(kinds))
        if _ROUTE_KINDS.intersection(kinds):
            applicable = True
    return flows, applicable


def aggregation_creation_floor(min_answer_spans: int) -> int:
    return max(3, min_answer_spans // _AGG_CREATION_FLOOR_DIV)


def score_cluster(
    cluster_id: str,
    title: str,
    signature: str,
    matched_skill: str | None,
    member_spans: pd.DataFrame,
    *,
    min_answer_spans: int,
    fuzz_threshold: int,
) -> Rung2Signal:
    if member_spans.empty:
        answer_rows = member_spans
    else:
        answer_rows = member_spans[
            (member_spans["span_kind"] == "LLM")
            & (member_spans["output_text"].fillna("").astype(str).str.strip() != "")
        ]
    answers = (
        [str(t) for t in answer_rows["output_text"].tolist()]
        if not answer_rows.empty
        else []
    )
    prompts = (
        [str(t) for t in answer_rows["input_text"].fillna("").tolist()]
        if not answer_rows.empty
        else []
    )
    n_answer_spans = len(answers)

    if answers:
        templates = build_templates(answers, fuzz_threshold=fuzz_threshold)
        conc, k = template_concentration(answers, fuzz_threshold=fuzz_threshold)
        self_sim = output_self_similarity(answers)
        slots = slot_stability(
            list(zip(prompts, answers, strict=False)), templates,
            fuzz_threshold=fuzz_threshold,
        )
    else:
        templates, conc, k, self_sim, slots = [], 0.0, 0, 0.0, 0.0
    flows, route_applicable = _flows_for(member_spans)
    route_inv = route_invariance(flows) if flows else None
    agg = detect_llm_aggregation(member_spans)

    signals = DeterminismSignals(
        template_concentration=round(conc, 4),
        route_invariance=round(route_inv, 4) if route_inv is not None else None,
        output_self_similarity=round(self_sim, 4),
        slot_stability=round(slots, 4),
        n_templates=k,
        n_answer_spans=n_answer_spans,
        route_applicable=route_applicable,
        aggregation_in_llm=agg.aggregation_in_llm,
        aggregation_offload_score=agg.offload_score,
        aggregation_reasons=agg.reasons,
        aggregation_action=agg.recommended_action,
    )
    eligible = n_answer_spans >= min_answer_spans
    score = blend_determinism(signals) if eligible else 0.0
    subtype = "offload_aggregation" if agg.aggregation_in_llm else ""
    return Rung2Signal(
        cluster_id=cluster_id,
        title=title,
        signature=signature,
        matched_skill=matched_skill,
        determinism_score=score,
        n_answer_spans=n_answer_spans,
        eligible=eligible,
        signals=signals,
        templates=tuple(templates[:10]),
        subtype=subtype,
        aggregation_in_llm=agg.aggregation_in_llm,
        aggregation_offload_score=agg.offload_score,
    )
