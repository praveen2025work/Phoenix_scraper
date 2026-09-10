"""Deterministic replacement for the LLM step behind `equity-recon-break`.

Scaffolded by pheonix from candidate fobo:d:b381d904a9df.
determinism_score 0.9496 — template_concentration 1.0, route_invariance 1.0, output_self_similarity 0.9057, slot_stability 0.9118.
"""
from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "template_1": 'the recon break on that book traces to an unsettled trade awaiting confirmation.',  # 31 answers
    "template_2": "as an ai model i do not have access to your firm's p&l systems.",  # 1 answers
    "template_3": 'i cannot access the ledger data needed to answer this.',  # 1 answers
    "template_4": 'the break is <num>against a tolerance of <num>, driven by <num>unmatched tickets.',  # 1 answers
}


DECISION_TABLE: dict[str, str] = {
    'why is there an credit recon break of <num> on <book>?': "template_1",
    'why is there an fx recon break of <num> on <book>?': "template_1",
    'why is there an equity recon break of <num> on <book>?': "template_1",
    'why is there an fx recon break of <num> on <book>?': "template_1",
    'why is there an equity recon break of <num> on <book>?': "template_1",
    'why is there an equity recon break of <num> on <book>?': "template_1",
    'why is there an equity recon break of <num> on <book>?': "template_1",
    'why is there an rates recon break of <num> on <book>?': "template_1",
}

def handle(prompt: str, context: list[dict]) -> str:
    """TODO: extract the slots from `prompt`, classify from `context`,
    return the filled TEMPLATES entry. test_equity_recon_break.py has the real cases."""
    raise NotImplementedError
