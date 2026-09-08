"""Rung 2 of the promotion ladder: how deterministic is this cluster's answer?

Pure and lexical — mask volatile tokens, then measure four things: do the
answers collapse to a few templates (`template_concentration`), does the agent
take the same route every time (`route_invariance`), are the answers similar to
each other (`output_self_similarity`), and does each input phrasing always yield
the same template (`slot_stability`). `score_cluster` blends them and gates on
`n_answer_spans`. No LLM — a low score is a real "keep the model" answer.
"""

from itertools import combinations

from rapidfuzz import fuzz

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
