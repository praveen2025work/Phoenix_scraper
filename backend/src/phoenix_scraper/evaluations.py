"""Code-based validation of LLM outputs and user prompts.

Phoenix validates an agent's behaviour with **span annotations**: named
judgements attached to a span, each carrying a label, a score and an
explanation, tagged with who made them — ``HUMAN`` (an analyst clicking thumbs
up/down), ``LLM`` (an llm-as-judge eval) or ``CODE`` (a deterministic
programmatic check). This module is the CODE annotator.

Being pure and offline (no model calls, no network) it runs over *every* span
rather than the 5-20% sample an LLM judge is affordable on, which is exactly
the split production teams use: cheap deterministic checks on 100% of traffic,
expensive semantic judges on a sample. Everything it emits is a
:class:`SpanEvaluation`, i.e. the same shape Phoenix's own annotations use, so
``annotations.py`` can push these back to Phoenix and pull HUMAN/LLM ones in
alongside them.

Scores are always 0-1 with **higher = better**; a check fails below
:data:`PASS_SCORE`. Every failure carries an explanation naming the evidence
(the matched phrase, the ungrounded figures, the missing terms) so an analyst
can confirm or dismiss it — a heuristic that cannot be audited is noise.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from .config import Settings
from .models import EvalTarget, SpanEvaluation

PASS_SCORE = 0.5
"""Scores below this count as a failed check in every rollup."""

_LLM = "LLM"
_TOOL = "TOOL"
_ERROR_STATUSES = frozenset({"ERROR"})

# ---- output checks -----------------------------------------------------------

# Refusals lead: a model that declines opens with it. Matching only the FIRST
# SENTENCE keeps "Reviewing the ledger, I cannot see a duplicate ticket" — an
# informative clause in a real answer — from reading as a refusal. The tradeoff
# is a refusal hidden behind a preamble sentence is missed; that is much rarer
# than the false positive, and a check that cries wolf gets switched off.
_REFUSAL_HEAD_CHARS = 240
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s")
_REFUSAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bi (?:cannot|can'?t|can not|am unable|'m unable|won'?t|will not)\b"),
    re.compile(r"\bi(?:'m| am) (?:sorry|afraid)\b"),
    re.compile(r"\b(?:unable|not able) to (?:help|assist|provide|comply|answer)\b"),
    re.compile(r"\bas an ai\b"),
    re.compile(r"\bi (?:don'?t|do not) have (?:access|the ability|enough information)\b"),
    re.compile(r"\bno (?:information|data) (?:is )?available\b"),
    re.compile(r"\b(?:cannot|can'?t) (?:help|assist) with (?:that|this)\b"),
)

# A complete answer ends on terminal punctuation or a closed structure. Anything
# else — a dangling comma, a mid-word cut, an unclosed brace — reads as truncated.
_SENTENCE_ENDINGS = ('.', '!', '?', '"', "'", ')', ']', '}', '`', ':', '»', '”')
_TRUNCATION_MIN_CHARS = 40
_LENGTH_FINISH_REASONS = frozenset({"length", "max_tokens", "maxtokens", "token_limit"})
_FINISH_REASON_KEYS = (
    "llm.invocation_parameters.finish_reason",
    "llm.output_messages.0.message.finish_reason",
    "finish_reason",
    "stop_reason",
)

# Degenerate repetition: a looping model repeats itself far more than prose does.
_REPETITION_MIN_WORDS = 30
_REPETITION_MAX_BIGRAM_REPEATS = 4

_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)

# Figures the model states: 2+ digits, so "1 trade" and years stay out of it.
_FIGURE_PATTERN = re.compile(r"\d[\d,.]*\d|\b\d{2,}\b")
_YEAR_PATTERN = re.compile(r"^(?:19|20)\d{2}$")

# ---- prompt checks -----------------------------------------------------------

_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier)\b"),
     "override of prior instructions"),
    (re.compile(r"\bdisregard (?:all |any )?(?:the )?(?:previous|prior|above|rules)\b"),
     "override of prior instructions"),
    (re.compile(r"\b(?:reveal|show|print|repeat|output) (?:me )?(?:your |the )?"
                r"(?:system|initial|original) (?:prompt|instructions?|message)\b"),
     "system-prompt extraction"),
    (re.compile(r"\byou are now\b|\bpretend (?:to be|you are)\b|\bact as if\b"),
     "persona override"),
    (re.compile(r"\bdeveloper mode\b|\bjailbreak\b|\bDAN mode\b", re.IGNORECASE),
     "known jailbreak marker"),
    (re.compile(r"\bwithout (?:any )?(?:restrictions|filters|safety|guardrails)\b"),
     "guardrail bypass"),
)

# A phone number must actually look like one — a country code, a parenthesised
# or trunk-prefixed area code, or the 3-3-4 grouping. Matching any two digit
# runs joined by a hyphen would flag "2020-2021", "1000-2000" and "500-600 bps",
# which is most of what a P&L desk writes; a PII check that fires on every year
# range gets ignored, and then it protects nothing.
_PHONE_PATTERN = re.compile(
    r"\+\d{1,3}[\s.-]?\d{1,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"  # +44 20 7555 0198
    r"|\(\d{2,5}\)[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"  # (020) 7555 0198
    r"|\b0\d{1,4}[\s.-]\d{3,4}[\s.-]?\d{3,4}\b"  # 0207 555 0198
    r"|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b"  # 555 123 4567
)

_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "email address"),
    (_PHONE_PATTERN, "phone number"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "IBAN"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "national insurance / SSN"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "card or account number"),
)

# An underspecified ask carries no subject the agent can act on: it is short and
# every word is either a stopword or a pronoun pointing at absent context.
_VAGUE_MAX_WORDS = 6
_VAGUE_REFERENTS = frozenset({"it", "that", "this", "them", "those", "these", "again",
                              "same", "one", "thing", "stuff"})

_STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by", "can",
    "could", "did", "do", "does", "for", "from", "had", "has", "have", "how", "i",
    "if", "in", "into", "is", "it", "its", "me", "my", "no", "not", "of", "on",
    "or", "our", "please", "s", "she", "should", "so", "some", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "this", "to", "up",
    "was", "we", "were", "what", "whats", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your", "he", "his", "her", "him", "us",
})

_WORD = re.compile(r"[a-z0-9_']+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class EvalOutcome:
    """One check's verdict; ``None`` from a checker means "not applicable"."""

    label: str
    score: float
    explanation: str


@dataclass(frozen=True)
class EvalContext:
    """Corpus-level facts a single-span check cannot compute on its own.

    ``trace_context`` holds, per trace, every piece of text the agent had in hand
    (the question plus tool results) — the reference an answer's figures are
    checked against. ``latency_thresholds_ms`` is keyed by span kind: a 200ms
    tool call and a 5s model call belong to different distributions, and one
    shared threshold would flag every LLM span or no tool span.
    """

    settings: Settings
    latency_thresholds_ms: Mapping[str, float]
    prompt_length_threshold: int | None
    trace_context: Mapping[str, str]
    traces_with_tools: frozenset[str]


Checker = Callable[[Mapping[str, Any], EvalContext], EvalOutcome | None]


def _register(
    name: str, target: EvalTarget
) -> Callable[[Checker], Checker]:
    def decorate(func: Checker) -> Checker:
        CHECKS.append((name, target, func))
        return func

    return decorate


CHECKS: list[tuple[str, EvalTarget, Checker]] = []


# ---- span-level checks -------------------------------------------------------


@_register("span_status", "span")
def check_span_status(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """The span itself failed — the most unambiguous validation signal there is."""
    status = str(span.get("status_code") or "OK").upper()
    if status in _ERROR_STATUSES:
        return EvalOutcome("error", 0.0, f"Span finished with status {status}.")
    return EvalOutcome("ok", 1.0, f"Span finished with status {status}.")


@_register("latency_outlier", "span")
def check_latency(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Spans far slower than others of their kind — a user-visible quality failure."""
    latency = span.get("latency_ms")
    kind = str(span.get("span_kind") or "UNKNOWN")
    threshold = ctx.latency_thresholds_ms.get(kind)
    if threshold is None or latency is None or pd.isna(latency):
        return None
    latency = float(latency)
    if latency > threshold:
        return EvalOutcome(
            "slow",
            0.0,
            f"{latency:.0f}ms exceeds the {threshold:.0f}ms outlier threshold "
            f"for {kind} spans.",
        )
    return EvalOutcome("normal", 1.0, f"{latency:.0f}ms is normal for a {kind} span.")


# ---- output checks -----------------------------------------------------------


@_register("output_empty", "output")
def check_output_empty(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """A user turn that produced no answer at all."""
    if not _is_user_turn(span):
        return None
    if not _text(span.get("output_text")):
        return EvalOutcome("empty", 0.0, "The model returned no output for this ask.")
    return EvalOutcome("present", 1.0, "The model returned an answer.")


@_register("output_refusal", "output")
def check_refusal(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """The model declined rather than answered.

    A refusal on an internal P&L question is almost always a false positive from
    an over-cautious model or a missing tool — not a safety win.
    """
    output = _text(span.get("output_text"))
    if not output:
        return None
    opening = _SENTENCE_SPLIT.split(output[:_REFUSAL_HEAD_CHARS], maxsplit=1)[0].casefold()
    for pattern in _REFUSAL_PATTERNS:
        match = pattern.search(opening)
        if match:
            return EvalOutcome(
                "refused", 0.0, f"Answer opens with a refusal marker: {match.group(0)!r}."
            )
    return EvalOutcome("answered", 1.0, "No refusal marker in the opening sentence.")


@_register("output_truncated", "output")
def check_truncated(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """The answer stops mid-thought — usually the completion token cap."""
    output = _text(span.get("output_text"))
    if not output:
        return None
    finish_reason = _finish_reason(span)
    if finish_reason and finish_reason.casefold() in _LENGTH_FINISH_REASONS:
        return EvalOutcome(
            "truncated", 0.0, f"Provider reported finish_reason={finish_reason!r}."
        )
    if len(output) < _TRUNCATION_MIN_CHARS:
        # Too short to judge by punctuation — "Yes." is a complete answer.
        return EvalOutcome("complete", 1.0, "Answer is short but terminated.")
    if not output.endswith(_SENTENCE_ENDINGS):
        return EvalOutcome(
            "truncated",
            0.0,
            f"Answer ends without terminal punctuation: …{output[-40:]!r}.",
        )
    unclosed = _unclosed_brackets(output)
    if unclosed:
        return EvalOutcome(
            "truncated", 0.0, f"Answer leaves {unclosed} unclosed."
        )
    return EvalOutcome("complete", 1.0, "Answer terminates cleanly.")


@_register("output_repetition", "output")
def check_repetition(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Degenerate looping — the model repeating itself instead of finishing."""
    output = _text(span.get("output_text"))
    words = _WORD.findall(output.casefold())
    if len(words) < _REPETITION_MIN_WORDS:
        return None
    diversity = len(set(words)) / len(words)
    threshold = ctx.settings.eval_repetition_threshold
    worst_bigram, repeats = _worst_bigram(words)
    if diversity < threshold:
        return EvalOutcome(
            "repetitive",
            0.0,
            f"Only {diversity:.0%} of {len(words)} words are distinct "
            f"(below the {threshold:.0%} floor).",
        )
    if repeats >= _REPETITION_MAX_BIGRAM_REPEATS:
        return EvalOutcome(
            "repetitive", 0.0, f"The phrase {worst_bigram!r} repeats {repeats} times."
        )
    return EvalOutcome("varied", 1.0, f"{diversity:.0%} of words are distinct.")


@_register("output_format_valid", "output")
def check_format(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Structured answers must parse — only checked when JSON was clearly intended."""
    output = _text(span.get("output_text"))
    if not output:
        return None
    payload = _strip_json_fence(output)
    asked_for_json = "json" in _text(span.get("input_text")).casefold()
    looks_like_json = payload.startswith(("{", "["))
    if not (asked_for_json and payload) and not looks_like_json:
        return None
    try:
        json.loads(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        return EvalOutcome("invalid_json", 0.0, f"Structured answer does not parse: {exc}.")
    return EvalOutcome("valid_json", 1.0, "Structured answer parses as JSON.")


@_register("answer_relevance", "output")
def check_relevance(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Lexical overlap between the ask and the answer — an on-topic proxy.

    Deliberately weak: it catches answers that share almost no vocabulary with
    the question (wrong tool, dropped context, generic boilerplate), not subtle
    wrongness, which needs an LLM judge. Full credit at the configured overlap.
    """
    if not _is_user_turn(span):
        return None
    prompt_terms = _content_terms(_text(span.get("input_text")))
    output = _text(span.get("output_text"))
    if not prompt_terms or not output:
        return None
    shared = prompt_terms & _content_terms(output)
    overlap = len(shared) / len(prompt_terms)
    target = ctx.settings.eval_relevance_overlap
    score = min(1.0, overlap / target) if target > 0 else 1.0
    if score < PASS_SCORE:
        missing = sorted(prompt_terms - shared)[:8]
        return EvalOutcome(
            "off_topic",
            score,
            f"Answer shares {overlap:.0%} of the question's terms "
            f"(target {target:.0%}); unaddressed: {', '.join(missing)}.",
        )
    label = "relevant" if overlap >= target else "partially_relevant"
    return EvalOutcome(
        label, score, f"Answer shares {overlap:.0%} of the question's terms."
    )


@_register("answer_groundedness", "output")
def check_groundedness(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Figures asserted in the answer that nothing in the trace supplied.

    Only applied to traces with **no tool calls**: when a tool ran it may
    legitimately have returned or the model legitimately computed a new number,
    and flagging that would be noise. With no tool in the trace, a fresh figure
    in a P&L answer came from the model alone — the highest-value hallucination
    signal available without a judge model.
    """
    if not _is_user_turn(span):
        return None
    trace_id = str(span.get("trace_id") or "")
    if trace_id in ctx.traces_with_tools:
        return None
    output = _text(span.get("output_text"))
    if not output:
        return None
    figures = _figures(output)
    if not figures:
        return None
    reference = ctx.trace_context.get(trace_id, "") + " " + _text(span.get("input_text"))
    grounded_figures = _figures(reference)
    unsupported = sorted(figures - grounded_figures)
    if unsupported:
        return EvalOutcome(
            "ungrounded",
            0.0,
            f"Answer states figures absent from the question and from every tool "
            f"result in the trace: {', '.join(unsupported[:6])}.",
        )
    return EvalOutcome(
        "grounded", 1.0, f"All {len(figures)} figures appear in the trace context."
    )


# ---- prompt checks -----------------------------------------------------------


@_register("prompt_injection", "prompt")
def check_injection(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Instruction-override attempts in a user prompt."""
    prompt = _text(span.get("input_text"))
    if not prompt:
        return None
    lowered = prompt.casefold()
    for pattern, description in _INJECTION_PATTERNS:
        match = pattern.search(lowered)
        if match:
            return EvalOutcome(
                "suspected_injection",
                0.0,
                f"Prompt contains {description}: {match.group(0)!r}.",
            )
    return EvalOutcome("clean", 1.0, "No instruction-override pattern in the prompt.")


@_register("prompt_pii", "prompt")
def check_pii(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Identifiers a user pasted into a prompt that then left the building."""
    prompt = _text(span.get("input_text"))
    if not prompt:
        return None
    found = [
        description for pattern, description in _PII_PATTERNS if pattern.search(prompt)
    ]
    if found:
        return EvalOutcome(
            "pii_present",
            0.0,
            f"Prompt appears to contain {', '.join(dict.fromkeys(found))} — "
            f"review before sharing this trace.",
        )
    return EvalOutcome("clean", 1.0, "No identifier pattern in the prompt.")


@_register("prompt_clarity", "prompt")
def check_clarity(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Asks too vague to answer — the agent has to guess, so the answer is a coin flip."""
    prompt = _text(span.get("input_text"))
    if not prompt:
        return None
    words = _WORD.findall(prompt.casefold())
    if not words:
        return None
    subject_terms = _content_terms(prompt) - _VAGUE_REFERENTS
    referents = sorted({word for word in words if word in _VAGUE_REFERENTS})
    pointing_at = ", ".join(referents) or "the request"
    # No concrete subject at ANY length: "can you please do that for me again"
    # is eleven words and still gives the agent nothing to act on.
    if not subject_terms:
        return EvalOutcome(
            "underspecified",
            0.0,
            f"{len(words)}-word ask with no concrete subject — the agent must "
            f"infer what {pointing_at} refers to.",
        )
    # A short ask whose single content word is a verb aimed at a pronoun
    # ("fix it again"): the verb is concrete, its object is not.
    if len(words) <= _VAGUE_MAX_WORDS and referents and len(subject_terms) == 1:
        return EvalOutcome(
            "underspecified",
            0.0,
            f"{len(words)}-word ask whose only concrete term is "
            f"{next(iter(subject_terms))!r} — the agent must infer what "
            f"{pointing_at} refers to.",
        )
    return EvalOutcome(
        "specific", 1.0, f"Ask carries {len(subject_terms)} concrete terms."
    )


@_register("prompt_length", "prompt")
def check_prompt_length(span: Mapping[str, Any], ctx: EvalContext) -> EvalOutcome | None:
    """Prompts far longer than the corpus norm — pasted dumps that bury the question."""
    prompt = _text(span.get("input_text"))
    if not prompt or ctx.prompt_length_threshold is None:
        return None
    if len(prompt) > ctx.prompt_length_threshold:
        return EvalOutcome(
            "oversized",
            0.0,
            f"{len(prompt)} characters exceeds the corpus outlier threshold of "
            f"{ctx.prompt_length_threshold}.",
        )
    return EvalOutcome("normal", 1.0, f"{len(prompt)} characters is within the norm.")


# ---- driver ------------------------------------------------------------------


def evaluate_spans(
    spans_df: pd.DataFrame, settings: Settings, now: datetime | None = None
) -> list[SpanEvaluation]:
    """Run every CODE check over ``spans_df`` and return the judgements.

    One row per (span, applicable check). Checks that do not apply to a span
    (a prompt check on a tool span, groundedness on a tool-backed trace) return
    nothing rather than a passing score, so rollups never dilute failure rates
    with spans that were never in scope.
    """
    if spans_df.empty:
        return []
    context = build_context(spans_df, settings)
    created_at = now or datetime.now(UTC)
    results: list[SpanEvaluation] = []
    for span in spans_df.to_dict("records"):
        span_id = str(span.get("span_id") or "")
        if not span_id:
            continue
        for name, target, checker in CHECKS:
            outcome = checker(span, context)
            if outcome is None:
                continue
            results.append(
                SpanEvaluation(
                    span_id=span_id,
                    name=name,
                    label=outcome.label,
                    score=outcome.score,
                    explanation=outcome.explanation,
                    annotator_kind="CODE",
                    target=target,
                    source="local",
                    created_at=created_at,
                )
            )
    return results


def build_context(spans_df: pd.DataFrame, settings: Settings) -> EvalContext:
    """Precompute the corpus statistics and per-trace reference text checks need."""
    return EvalContext(
        settings=settings,
        latency_thresholds_ms=_latency_thresholds(spans_df, settings),
        prompt_length_threshold=_prompt_length_threshold(spans_df, settings),
        trace_context=_trace_context(spans_df),
        traces_with_tools=_traces_with_tools(spans_df),
    )


def check_names() -> tuple[tuple[str, EvalTarget], ...]:
    """Registered (name, target) pairs — the catalog the UI and docs describe."""
    return tuple((name, target) for name, target, _ in CHECKS)


def evaluations_frame(evaluations: Iterable[SpanEvaluation]) -> pd.DataFrame:
    """Judgements as a DataFrame with a derived ``passed`` column."""
    rows = [e.model_dump() for e in evaluations]
    df = pd.DataFrame(rows, columns=list(SpanEvaluation.model_fields))
    return df.assign(passed=df["score"].fillna(1.0) >= PASS_SCORE)


# ---- helpers -----------------------------------------------------------------


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _is_user_turn(span: Mapping[str, Any]) -> bool:
    """An LLM span carrying a user-facing question — the unit users experience."""
    return str(span.get("span_kind") or "") == _LLM and bool(_text(span.get("input_text")))


def _content_terms(text: str) -> set[str]:
    """Meaningful lowercase words: stopwords, pure numbers, and 1-char tokens dropped."""
    return {
        word
        for word in _WORD.findall(text.casefold())
        if len(word) > 1 and word not in _STOPWORDS and not word.isdigit()
    }


def _figures(text: str) -> set[str]:
    """Numeric tokens, separator- and year-normalized so 1,250 == 1250."""
    out: set[str] = set()
    for raw in _FIGURE_PATTERN.findall(text):
        cleaned = raw.replace(",", "").rstrip(".")
        if not cleaned or _YEAR_PATTERN.match(cleaned):
            continue
        out.add(cleaned)
    return out


def _worst_bigram(words: list[str]) -> tuple[str, int]:
    counts: dict[tuple[str, str], int] = {}
    for pair in zip(words, words[1:], strict=False):
        counts[pair] = counts.get(pair, 0) + 1
    if not counts:
        return "", 0
    pair, repeats = max(counts.items(), key=lambda item: item[1])
    return " ".join(pair), repeats


_BRACKET_PAIRS = (("{", "}"), ("[", "]"), ("(", ")"))


def _unclosed_brackets(text: str) -> str:
    unclosed = [
        opening for opening, closing in _BRACKET_PAIRS
        if text.count(opening) > text.count(closing)
    ]
    return ", ".join(f"{b!r}" for b in unclosed)


def _strip_json_fence(text: str) -> str:
    match = _JSON_FENCE.match(text)
    return match.group(1).strip() if match else text


def _finish_reason(span: Mapping[str, Any]) -> str | None:
    attributes = _attributes(span)
    for key in _FINISH_REASON_KEYS:
        value = attributes.get(key)
        if value:
            return str(value)
    return None


def _attributes(span: Mapping[str, Any]) -> dict[str, Any]:
    """Span attributes as a dict — stored as a JSON string by the SQLite layer."""
    raw = span.get("attributes")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw not in ("", "{}"):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _outlier_threshold(
    values: pd.Series, quantile: float, factor: float
) -> float | None:
    """Quantile cut, floored at ``factor`` x median so tight distributions stay quiet.

    A bare p95 always flags 5% of a corpus however healthy it is; requiring the
    value to also be a multiple of the median means a consistent agent produces
    no outliers at all.
    """
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 20:
        return None
    return max(float(clean.quantile(quantile)), float(clean.median()) * factor)


def _latency_thresholds(
    spans_df: pd.DataFrame, settings: Settings
) -> dict[str, float]:
    """Outlier cut per span kind — kinds with too few spans get no threshold."""
    if "latency_ms" not in spans_df or "span_kind" not in spans_df:
        return {}
    thresholds: dict[str, float] = {}
    for kind, group in spans_df.groupby(spans_df["span_kind"].fillna("UNKNOWN")):
        threshold = _outlier_threshold(
            group["latency_ms"],
            settings.eval_outlier_quantile,
            settings.eval_outlier_factor,
        )
        if threshold is not None:
            thresholds[str(kind)] = threshold
    return thresholds


def _prompt_length_threshold(spans_df: pd.DataFrame, settings: Settings) -> int | None:
    if "input_text" not in spans_df:
        return None
    lengths = spans_df["input_text"].fillna("").astype(str).str.len()
    threshold = _outlier_threshold(
        lengths[lengths > 0], settings.eval_outlier_quantile, settings.eval_outlier_factor
    )
    return int(threshold) if threshold is not None else None


def _traces_with_tools(spans_df: pd.DataFrame) -> frozenset[str]:
    if "span_kind" not in spans_df or "trace_id" not in spans_df:
        return frozenset()
    tools = spans_df.loc[spans_df["span_kind"].isin([_TOOL, "RETRIEVER"]), "trace_id"]
    return frozenset(tools.dropna().astype(str))


def _trace_context(spans_df: pd.DataFrame) -> dict[str, str]:
    """Per trace, the text the agent had available beyond the LLM answers themselves."""
    if "trace_id" not in spans_df:
        return {}
    supporting = spans_df.loc[spans_df["span_kind"] != _LLM] if "span_kind" in spans_df \
        else spans_df
    if supporting.empty:
        return {}
    columns = [c for c in ("input_text", "output_text") if c in supporting.columns]
    if not columns:
        return {}
    joined = supporting[columns].fillna("").astype(str).agg(" ".join, axis=1)
    grouped = joined.groupby(supporting["trace_id"].astype(str)).agg(" ".join)
    return {
        trace_id: _WHITESPACE.sub(" ", text) for trace_id, text in grouped.items()
    }
