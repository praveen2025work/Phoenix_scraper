"""Tests for classical TF-IDF cosine similarity (no LLM)."""

from phoenix_scraper.text_similarity import cosine, tfidf_similarity, tokenize


def test_tokenize_drops_stopwords_and_pure_digits() -> None:
    toks = tokenize("Why is there an FX recon break of 100 on EURUSD?")
    assert "why" not in toks and "is" not in toks
    assert "fx" in toks and "recon" in toks and "break" in toks
    assert "eurusd" in toks
    assert "100" not in toks  # pure digits dropped


def test_identical_texts_score_high() -> None:
    text = "equity recon break for desk XYZ"
    assert tfidf_similarity(text, [text]) >= 0.99


def test_related_texts_score_higher_than_unrelated() -> None:
    query = "Why is there an FX recon break of 100k on EURUSD?"
    related = ["FX recon break triage for currency pairs"]
    unrelated = ["Convert my report to French please"]
    assert tfidf_similarity(query, related) > tfidf_similarity(query, unrelated)


def test_empty_inputs_score_zero() -> None:
    assert tfidf_similarity("", ["hello"]) == 0.0
    assert tfidf_similarity("hello", []) == 0.0
    assert cosine({}, {"a": 1.0}) == 0.0
