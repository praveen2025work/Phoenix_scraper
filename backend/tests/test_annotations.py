"""Tests for exchanging span annotations with Phoenix (pull, push, and mapping)."""

from datetime import UTC, datetime

import pytest

from phoenix_scraper import annotations
from phoenix_scraper.config import Settings
from phoenix_scraper.models import QueryFilters, SpanEvaluation, SpanRecord
from phoenix_scraper.storage import Store


class FakePhoenix:
    """Stands in for PhoenixClientWrapper — records calls, returns canned rows."""

    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []
        self.requested_span_ids: list[str] = []
        self.pushed: list[dict] = []

    def available(self) -> bool:
        return True

    def fetch_span_annotations(self, project: str, span_ids) -> list[dict]:
        self.requested_span_ids.extend(span_ids)
        return self.rows

    def push_span_annotations(self, project: str, payload) -> int:
        self.pushed.extend(payload)
        return len(payload)


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "a.db", project="pnl-agent")


def make_span(span_id: str) -> SpanRecord:
    return SpanRecord(
        span_id=span_id,
        trace_id="t1",
        project="pnl-agent",
        span_kind="LLM",
        start_time=datetime(2026, 8, 1, tzinfo=UTC),
        input_text="why is there a break?",
        output_text="an unsettled trade",
    )


class TestAnnotationMapping:
    def test_maps_nested_result_shape(self) -> None:
        result = annotations.annotation_to_evaluation({
            "id": "a1",
            "span_id": "abc123",
            "name": "correctness",
            "annotator_kind": "HUMAN",
            "result": {"label": "correct", "score": 0.85,
                       "explanation": "matches the ledger"},
            "created_at": "2026-08-01T10:00:00Z",
        })
        assert result is not None
        assert result.span_id == "abc123"
        assert result.name == "correctness"
        assert result.label == "correct"
        assert result.score == pytest.approx(0.85)
        assert result.explanation == "matches the ledger"
        assert result.annotator_kind == "HUMAN"
        assert result.source == "phoenix"
        assert result.created_at is not None and result.created_at.tzinfo is not None

    def test_maps_flattened_dataframe_shape(self) -> None:
        result = annotations.annotation_to_evaluation({
            "span_id": "abc123", "name": "helpfulness",
            "label": "helpful", "score": 1.0, "annotator_kind": "LLM",
        })
        assert result is not None
        assert result.label == "helpful"
        assert result.annotator_kind == "LLM"

    def test_percentage_scores_normalize_to_unit_interval(self) -> None:
        result = annotations.annotation_to_evaluation(
            {"span_id": "s", "name": "quality", "result": {"score": 85}}
        )
        assert result is not None
        assert result.score == pytest.approx(0.85)

    def test_missing_score_stays_none(self) -> None:
        result = annotations.annotation_to_evaluation(
            {"span_id": "s", "name": "note", "result": {"label": "reviewed"}}
        )
        assert result is not None
        assert result.score is None

    def test_unknown_annotator_kind_falls_back_to_human(self) -> None:
        result = annotations.annotation_to_evaluation(
            {"span_id": "s", "name": "n", "annotator_kind": "ROBOT"}
        )
        assert result is not None
        assert result.annotator_kind == "HUMAN"

    @pytest.mark.parametrize(
        "payload", [{}, {"span_id": "s"}, {"name": "n"}, {"span_id": "", "name": "n"}]
    )
    def test_unusable_annotations_are_dropped(self, payload: dict) -> None:
        assert annotations.annotation_to_evaluation(payload) is None

    def test_to_phoenix_annotation_shape(self) -> None:
        payload = annotations.to_phoenix_annotation({
            "span_id": "abc", "name": "output_refusal", "label": "refused",
            "score": 0.0, "explanation": "opens with a refusal", "target": "output",
        })
        assert payload["span_id"] == "abc"
        assert payload["name"] == "output_refusal"
        assert payload["annotator_kind"] == "CODE"
        assert payload["result"] == {
            "label": "refused", "score": 0.0, "explanation": "opens with a refusal"
        }
        assert payload["metadata"]["target"] == "output"
        # An identifier makes repeat pushes upsert rather than accumulate, and
        # keeps our rows distinct from a human's annotation of the same name.
        assert payload["identifier"] == "pheonix"

    def test_round_trip_preserves_label_and_score(self) -> None:
        original = SpanEvaluation(
            span_id="s1", name="output_empty", label="empty", score=0.0,
            explanation="no output", target="output",
        )
        [payload] = annotations.evaluations_to_annotations([original])
        back = annotations.annotation_to_evaluation(payload)
        assert back is not None
        assert (back.span_id, back.name, back.label, back.score) == (
            "s1", "output_empty", "empty", 0.0
        )
        assert back.annotator_kind == "CODE"

    def test_annotation_names(self) -> None:
        assert annotations.annotation_names(
            [{"name": "b"}, {"name": "a"}, {"name": ""}, {}]
        ) == ["a", "b"]


class TestPull:
    def test_stores_annotations_for_known_spans(self, settings: Settings) -> None:
        store = Store(settings.db_path)
        store.upsert_spans([make_span("s1"), make_span("s2")])
        client = FakePhoenix([
            {"span_id": "s1", "name": "correctness", "annotator_kind": "HUMAN",
             "result": {"label": "incorrect", "score": 0.0}},
            {"span_id": "s2", "name": "helpfulness", "annotator_kind": "LLM",
             "result": {"label": "helpful", "score": 1.0}},
        ])

        report = annotations.pull_annotations(store, client, settings)

        assert report.direction == "pull"
        assert report.spans_considered == 2
        assert report.annotations == 2
        assert report.stored == 2
        df = store.evaluations_frame(QueryFilters(limit=100))
        assert set(df["source"]) == {"phoenix"}
        assert set(df["annotator_kind"]) == {"HUMAN", "LLM"}
        store.close()

    def test_annotations_for_unknown_spans_are_skipped(self, settings: Settings) -> None:
        # A foreign span id would violate the join the whole quality view rests on.
        store = Store(settings.db_path)
        store.upsert_spans([make_span("s1")])
        client = FakePhoenix([
            {"span_id": "s1", "name": "a", "result": {"score": 1.0}},
            {"span_id": "not-ours", "name": "a", "result": {"score": 0.0}},
        ])

        report = annotations.pull_annotations(store, client, settings)

        assert report.annotations == 2
        assert report.stored == 1
        assert report.skipped == 1
        store.close()

    def test_no_spans_means_no_request(self, settings: Settings) -> None:
        store = Store(settings.db_path)
        client = FakePhoenix()
        report = annotations.pull_annotations(store, client, settings)
        assert report.spans_considered == 0
        assert client.requested_span_ids == []
        store.close()

    def test_pull_is_idempotent(self, settings: Settings) -> None:
        store = Store(settings.db_path)
        store.upsert_spans([make_span("s1")])
        client = FakePhoenix(
            [{"span_id": "s1", "name": "correctness", "result": {"score": 1.0}}]
        )
        annotations.pull_annotations(store, client, settings)
        second = annotations.pull_annotations(store, client, settings)
        assert second.stored == 0  # replaced in place, not duplicated
        assert len(store.evaluations_frame(QueryFilters(limit=100))) == 1
        store.close()

    def test_phoenix_annotations_survive_a_local_re_evaluation(
        self, settings: Settings
    ) -> None:
        # Local checks are ours to recompute; Phoenix's data is not ours to drop.
        store = Store(settings.db_path)
        store.upsert_spans([make_span("s1")])
        annotations.pull_annotations(
            store, FakePhoenix(
                [{"span_id": "s1", "name": "correctness", "result": {"score": 0.0}}]
            ), settings,
        )
        store.replace_local_evaluations(
            [SpanEvaluation(span_id="s1", name="output_empty", label="present", score=1.0)]
        )
        store.replace_local_evaluations([])

        df = store.evaluations_frame(QueryFilters(limit=100))
        assert list(df["name"]) == ["correctness"]
        store.close()


class TestPush:
    def _store_with_local_evals(self, settings: Settings) -> Store:
        store = Store(settings.db_path)
        store.upsert_spans([make_span("s1"), make_span("s2")])
        store.replace_local_evaluations([
            SpanEvaluation(span_id="s1", name="output_refusal", label="refused",
                           score=0.0, explanation="refusal marker", target="output"),
            SpanEvaluation(span_id="s2", name="output_refusal", label="answered",
                           score=1.0, explanation="clean", target="output"),
        ])
        return store

    def test_pushes_only_failures_by_default(self, settings: Settings) -> None:
        store = self._store_with_local_evals(settings)
        client = FakePhoenix()

        report = annotations.push_annotations(store, client, settings)

        assert report.direction == "push"
        assert report.annotations == 1
        assert report.stored == 1
        assert client.pushed[0]["span_id"] == "s1"
        assert client.pushed[0]["annotator_kind"] == "CODE"
        store.close()

    def test_push_all_includes_passing_checks(self, settings: Settings) -> None:
        store = self._store_with_local_evals(settings)
        client = FakePhoenix()

        report = annotations.push_annotations(
            store, client, settings, only_failures=False
        )

        assert report.annotations == 2
        store.close()

    def test_phoenix_sourced_annotations_are_never_pushed_back(
        self, settings: Settings
    ) -> None:
        # Echoing Phoenix's own annotations back at it would duplicate its data.
        store = self._store_with_local_evals(settings)
        store.upsert_evaluations([
            SpanEvaluation(span_id="s1", name="correctness", label="wrong", score=0.0,
                           source="phoenix", annotator_kind="HUMAN"),
        ])
        client = FakePhoenix()

        annotations.push_annotations(store, client, settings)

        assert [a["name"] for a in client.pushed] == ["output_refusal"]
        store.close()

    def test_nothing_to_push_is_not_an_error(self, settings: Settings) -> None:
        store = Store(settings.db_path)
        report = annotations.push_annotations(store, FakePhoenix(), settings)
        assert report.annotations == 0
        store.close()
