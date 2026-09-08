"""Pure tests for the four Rung-2 sub-signals + the blend/gate."""

import pandas as pd

from phoenix_scraper import determinism as d

FUZZ = 90


class TestTemplates:
    def test_one_template_when_all_answers_match(self) -> None:
        answers = [f"The EUR break of {n}k on BUND is an unsettled trade." for n in range(20)]
        conc, k = d.template_concentration(answers, fuzz_threshold=FUZZ)
        assert k == 1 and conc == 1.0

    def test_two_templates_needed_below_90pct_coverage(self) -> None:
        a = [f"The EUR break of {n}k on BUND is an unsettled trade." for n in range(16)]
        b = [f"The break of {n}k matches a missing dividend accrual." for n in range(4)]
        conc, k = d.template_concentration(a + b, fuzz_threshold=FUZZ)
        assert k == 2 and conc == 0.75  # 16/20 = 80% < 90% -> need the 2nd template

    def test_high_variety_scores_low(self) -> None:
        stems = [
            "the reconciliation gap stems from a timing mismatch on settlement",
            "cash flow projections were revised after the treasury update meeting",
            "the desk flagged an unusual spread widening across credit names",
            "position limits were breached intraday and later corrected by ops",
            "the model recalibration shifted the attribution toward carry",
            "an amended trade booking resolved the outstanding confirmation",
        ]
        answers = [stems[i % len(stems)] + f" note {i}" for i in range(24)]
        conc, k = d.template_concentration(answers, fuzz_threshold=FUZZ)
        assert conc < 0.5 and k >= 3


class TestRouteInvariance:
    def test_all_same_flow(self) -> None:
        assert d.route_invariance(["LLM -> TOOL -> LLM"] * 10) == 1.0

    def test_split_flow(self) -> None:
        flows = ["LLM -> TOOL -> LLM"] * 7 + ["LLM -> TOOL x2 -> LLM"] * 3
        assert d.route_invariance(flows) == 0.7

    def test_empty(self) -> None:
        assert d.route_invariance([]) == 0.0


class TestSelfSimilarity:
    def test_identical_answers(self) -> None:
        assert d.output_self_similarity(["same text here"] * 5) == 1.0

    def test_unrelated_answers(self) -> None:
        assert d.output_self_similarity(
            ["the sky is blue today", "bananas ripen in warm rooms"]
        ) < 0.5

    def test_single_answer_is_perfectly_similar(self) -> None:
        assert d.output_self_similarity(["only one"]) == 1.0


class TestSlotStability:
    def test_stable_when_each_input_shape_maps_to_one_template(self) -> None:
        templates = d.build_templates(
            ["cause is an unsettled trade"] * 6 + ["cause is a missing accrual"] * 6,
            fuzz_threshold=FUZZ,
        )
        pairs = (
            [("why is there a break of 100k on BUND", "cause is an unsettled trade")] * 6
            + [("what caused the 50k adjustment on GILT", "cause is a missing accrual")] * 6
        )
        assert d.slot_stability(pairs, templates, fuzz_threshold=FUZZ) == 1.0

    def test_unstable_when_one_input_shape_splits(self) -> None:
        templates = d.build_templates(
            ["cause A here"] * 5 + ["cause B there"] * 5, fuzz_threshold=FUZZ
        )
        pairs = (
            [("why is there a break of 100k on BUND", "cause A here")] * 5
            + [("why is there a break of 200k on BUND", "cause B there")] * 5
        )
        # one masked input signature -> two templates 50/50
        assert d.slot_stability(pairs, templates, fuzz_threshold=FUZZ) == 0.5


def _member_spans(answers, prompts=None, flows_per_trace=None):
    prompts = prompts or ["why is there a break of 100k on BUND"] * len(answers)
    rows = []
    for i, (ans, prm) in enumerate(zip(answers, prompts, strict=False)):
        tid = f"t{i}"
        rows.append(dict(span_id=f"s{i}", trace_id=tid, span_kind="LLM",
                         input_text=prm, output_text=ans, start_time=i))
        for j, kind in enumerate((flows_per_trace or {}).get(tid, [])):
            rows.append(dict(span_id=f"s{i}-{j}", trace_id=tid, span_kind=kind,
                             input_text="", output_text="", start_time=i + 0.1 + j * 0.01))
    return pd.DataFrame(rows)


class TestBlendAndScore:
    def test_blend_drops_route_when_not_applicable(self) -> None:
        sig = d.DeterminismSignals(
            template_concentration=1.0, route_invariance=None,
            output_self_similarity=1.0, slot_stability=1.0,
            n_templates=1, n_answer_spans=12, route_applicable=False,
        )
        assert d.blend_determinism(sig) == 1.0

    def test_blend_weights(self) -> None:
        sig = d.DeterminismSignals(
            template_concentration=1.0, route_invariance=0.0,
            output_self_similarity=1.0, slot_stability=1.0,
            n_templates=1, n_answer_spans=12, route_applicable=True,
        )
        # (0.4*1 + 0.3*1 + 0.2*1 + 0.1*0) / 1.0 == 0.9
        assert round(d.blend_determinism(sig), 4) == 0.9

    def test_score_cluster_high_determinism(self) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        spans = _member_spans(answers)
        sig = d.score_cluster("c1", "t", "s", None, spans,
                              min_answer_spans=10, fuzz_threshold=90)
        assert sig.eligible is True
        assert sig.determinism_score > 0.8
        assert sig.signals.route_applicable is False  # no TOOL spans

    def test_score_cluster_insufficient_data(self) -> None:
        spans = _member_spans([f"answer {n}" for n in range(4)])
        sig = d.score_cluster("c2", "t", "s", None, spans,
                              min_answer_spans=10, fuzz_threshold=90)
        assert sig.eligible is False and sig.determinism_score == 0.0
        assert sig.n_answer_spans == 4

    def test_score_cluster_route_applicable_with_tools(self) -> None:
        answers = [f"The break of {n}k is unsettled." for n in range(12)]
        flows = {f"t{i}": ["TOOL"] for i in range(12)}
        spans = _member_spans(answers, flows_per_trace=flows)
        sig = d.score_cluster("c3", "t", "s", None, spans,
                              min_answer_spans=10, fuzz_threshold=90)
        assert sig.signals.route_applicable is True
        assert sig.signals.route_invariance == 1.0
