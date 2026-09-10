"""Real observed (prompt -> answer) pairs for `equity-recon-break`. Ships red."""
import pytest

from .equity_recon_break import handle

CASES = [
    ('Why is there an credit recon break of 300k on CLO_WH_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an FX recon break of 300k on USDJPY_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 40k on EQ_DELTA1_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an FX recon break of 40k on USDJPY_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 850k on EQ_INDEX_HK?', 'I cannot access the ledger data needed to answer this.'),
    ('Why is there an equity recon break of 210k on EQ_INDEX_HK?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 40k on EQ_INDEX_HK?', 'The break is 487,320.55 against a tolerance of 25,000, driven by 14 unmatched tickets.'),
    ('Why is there an rates recon break of 620k on IRS_USD_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an rates recon break of 300k on BUNDS_FFT?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an FX recon break of 850k on EURUSD_LDN?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 75k on EQ_DELTA1_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation. The residual arises because the overnight feed from the custodian was applied after the cut-off and the remaining positions were'),
    ('Why is there an FX recon break of 120k on EURUSD_LDN?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 300k on EQ_VOL_LDN?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an credit recon break of 40k on CDS_IG_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 480k on EQ_DELTA1_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.'),
    ('Why is there an equity recon break of 850k on EQ_DELTA1_NY?', 'The recon break on that book traces to an unsettled trade awaiting confirmation.')
]


@pytest.mark.parametrize("prompt, expected", CASES)
def test_handle_matches_observed(prompt: str, expected: str) -> None:
    assert " ".join(handle(prompt, []).split()) == " ".join(expected.split())
