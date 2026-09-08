"""Rung 2 of the promotion ladder: how deterministic is this cluster's answer?

Pure and lexical — mask volatile tokens, then measure four things: do the
answers collapse to a few templates (`template_concentration`), does the agent
take the same route every time (`route_invariance`), are the answers similar to
each other (`output_self_similarity`), and does each input phrasing always yield
the same template (`slot_stability`). `score_cluster` blends them and gates on
`n_answer_spans`. No LLM — a low score is a real "keep the model" answer.
"""

from itertools import combinations

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


class DeterminismSignals(_Frozen):
    template_concentration: float
    route_invariance: float | None
    output_self_similarity: float
    slot_stability: float
    n_templates: int
    n_answer_spans: int
    route_applicable: bool


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

    signals = DeterminismSignals(
        template_concentration=round(conc, 4),
        route_invariance=round(route_inv, 4) if route_inv is not None else None,
        output_self_similarity=round(self_sim, 4),
        slot_stability=round(slots, 4),
        n_templates=k,
        n_answer_spans=n_answer_spans,
        route_applicable=route_applicable,
    )
    eligible = n_answer_spans >= min_answer_spans
    score = blend_determinism(signals) if eligible else 0.0
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
    )
